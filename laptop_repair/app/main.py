"""Server-rendered web application, usable directly or through HA Ingress."""

import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException

from .db import DONOR_STATUSES, STATUSES
from .services import DomainError, Store, integer, money_display, money_input

APP_DIR = Path(__file__).parent
COOKIE_NAME = "laptop_repair_csrf"


def load_secret(data_dir):
    path = data_dir / "session.key"
    try:
        with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
            handle.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    key = path.read_text().strip()
    if not key:
        raise RuntimeError("session.key is empty. Restore it or remove it to generate a new key.")
    return key


def prefix_for(request):
    prefix = request.headers.get("x-ingress-path", "").rstrip("/")
    if not re.fullmatch(r"(?:/[A-Za-z0-9_.~-]+)*", prefix) or any(
        segment in (".", "..") for segment in prefix.split("/")
    ):
        raise DomainError("Invalid Ingress path.")
    return prefix


async def checked_form(request: Request):
    # Yielding keeps uploaded temporary files open until the endpoint finishes.
    async with request.form(max_files=10, max_fields=50) as form:
        token = form.get("csrf_token", "")
        cookie = request.cookies.get(COOKIE_NAME, "")
        if not isinstance(token, str) or not token or not secrets.compare_digest(token.encode(), cookie.encode()):
            raise DomainError("This form has expired or is invalid. Reload the page and try again.", 403)
        try:
            request.app.state.signer.loads(token)
        except BadSignature:
            raise DomainError("This form has expired or is invalid. Reload the page and try again.", 403) from None
        yield form


CheckedForm = Annotated[FormData, Depends(checked_form)]


def create_app(data_dir=None):
    @asynccontextmanager
    async def lifespan(app):
        directory = Path(data_dir or os.environ.get("DATA_DIR", "/data"))
        app.state.store = Store(directory)
        app.state.store.initialize()
        app.state.signer = URLSafeSerializer(load_secret(directory), salt="laptop-repair-csrf")
        yield

    app = FastAPI(title="Laptop Repair Manager", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    templates.env.filters["money"] = money_display
    templates.env.filters["money_input"] = money_input
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @app.middleware("http")
    async def browser_context(request, call_next):
        try:
            request.state.prefix = prefix_for(request)
        except DomainError as error:
            return PlainTextResponse(error.message, status_code=400)
        cookie = request.cookies.get(COOKIE_NAME, "")
        try:
            if not cookie:
                raise BadSignature("Missing token")
            request.app.state.signer.loads(cookie)
            token = cookie
        except BadSignature:
            token = request.app.state.signer.dumps(secrets.token_hex(32))
        request.state.csrf_token = token
        response = await call_next(request)
        if token != cookie:
            response.set_cookie(
                COOKIE_NAME, token, httponly=True, samesite="lax",
                secure=request.url.scheme == "https", path=request.state.prefix + "/",
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def page(request, template, *, status_code=200, **context):
        return templates.TemplateResponse(
            request=request, name=template, status_code=status_code,
            context={
                "url": lambda path: request.state.prefix + path,
                "csrf_token": request.state.csrf_token,
                "statuses": STATUSES,
                "donor_statuses": DONOR_STATUSES,
                "notice": request.query_params.get("notice", ""),
                **context,
            },
        )

    def redirect(request, path, notice=""):
        suffix = "?" + urlencode({"notice": notice}) if notice else ""
        return RedirectResponse(request.state.prefix + path + suffix, status_code=303)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return page(request, "error.html", status_code=error.status_code, error=error.message, code=error.status_code)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return page(request, "error.html", status_code=error.status_code, error=str(error.detail), code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return page(request, "error.html", status_code=422, error="Invalid record identifier or request.", code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, error):
        if "locked" not in str(error).lower():
            raise error
        return page(request, "error.html", status_code=503, error="The database is busy. Please try again shortly.", code=503)

    @app.get("/health")
    def health(request: Request):
        with request.app.state.store.db.connect() as conn:
            conn.execute("SELECT COUNT(*) FROM laptops").fetchone()
        return {"status": "ok"}

    @app.get("/")
    def dashboard(request: Request):
        return page(request, "dashboard.html", nav="dashboard", summary=request.app.state.store.dashboard())

    @app.get("/laptops")
    def laptops(request: Request, q: str = "", status: str = ""):
        if status and status not in STATUSES:
            raise DomainError("Choose a valid status filter.")
        return page(request, "laptops.html", nav="laptops", laptops=request.app.state.store.laptops(q, status), q=q, status=status)

    @app.get("/laptops/new")
    def laptop_new(request: Request):
        return page(request, "laptop_form.html", nav="laptops", laptop=None,
                    values={"status": "purchased", "purchase_price": "0.00", "shipping_cost": "0.00"})

    @app.post("/laptops/new")
    def laptop_create(request: Request, form: CheckedForm):
        try:
            laptop_id = request.app.state.store.save_laptop(form)
        except DomainError as error:
            return page(request, "laptop_form.html", nav="laptops", laptop=None, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, f"/laptops/{laptop_id}", "Laptop added.")

    @app.get("/laptops/{laptop_id}")
    def laptop_detail(request: Request, laptop_id: int):
        store = request.app.state.store
        parts = [part for part in store.parts() if part["donor_laptop_id"] != laptop_id]
        return page(request, "laptop_detail.html", nav="laptops", laptop=store.laptop(laptop_id), parts=parts)

    @app.get("/laptops/{laptop_id}/edit")
    def laptop_edit(request: Request, laptop_id: int):
        laptop = request.app.state.store.laptop(laptop_id)
        values = {**laptop, **{key: money_input(laptop[key]) for key in ("purchase_price", "shipping_cost", "resale_price")}}
        return page(request, "laptop_form.html", nav="laptops", laptop=laptop, values=values)

    @app.post("/laptops/{laptop_id}/edit")
    def laptop_update(request: Request, laptop_id: int, form: CheckedForm):
        store = request.app.state.store
        laptop = store.laptop(laptop_id)
        try:
            store.save_laptop(form, laptop_id)
        except DomainError as error:
            return page(request, "laptop_form.html", nav="laptops", laptop=laptop, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, f"/laptops/{laptop_id}", "Laptop updated.")

    @app.post("/laptops/{laptop_id}/delete")
    def laptop_delete(request: Request, laptop_id: int, form: CheckedForm):
        request.app.state.store.delete_laptop(laptop_id)
        return redirect(request, "/laptops", "Laptop deleted and assigned parts returned to stock.")

    @app.post("/laptops/{laptop_id}/parts")
    def assign_part(request: Request, laptop_id: int, form: CheckedForm):
        part_id = integer(form.get("part_id", ""), "Part", minimum=1, maximum=2**31)
        request.app.state.store.assign(laptop_id, part_id, form.get("quantity", ""), form.get("transfer_value", ""))
        return redirect(request, f"/laptops/{laptop_id}", "Part assigned; stock updated.")

    @app.post("/laptops/{laptop_id}/parts/{assignment_id}/edit")
    def assignment_edit(request: Request, laptop_id: int, assignment_id: int, form: CheckedForm):
        quantity = form.get("quantity", "")
        integer(quantity, minimum=1)
        request.app.state.store.change_assignment(laptop_id, assignment_id, quantity)
        return redirect(request, f"/laptops/{laptop_id}", "Assignment quantity updated.")

    @app.post("/laptops/{laptop_id}/parts/{assignment_id}/delete")
    def assignment_delete(request: Request, laptop_id: int, assignment_id: int, form: CheckedForm):
        request.app.state.store.change_assignment(laptop_id, assignment_id, "0")
        return redirect(request, f"/laptops/{laptop_id}", "Part returned to stock.")

    @app.post("/laptops/{laptop_id}/attachments")
    def attachment_upload(request: Request, laptop_id: int, form: CheckedForm):
        files = [file for file in form.getlist("files") if isinstance(file, UploadFile) and file.filename]
        request.app.state.store.add_attachments(laptop_id, files)
        return redirect(request, f"/laptops/{laptop_id}", "Files uploaded.")

    @app.get("/laptops/{laptop_id}/attachments/{attachment_id}")
    def attachment_download(request: Request, laptop_id: int, attachment_id: int):
        store = request.app.state.store
        file = store.attachment(laptop_id, attachment_id)
        path = store.upload_dir / file["storage_name"]
        if not path.is_file():
            raise DomainError("The attachment file is missing. Restore it from a backup.", 404)
        return FileResponse(path, filename=file["filename"], media_type="application/octet-stream")

    @app.post("/laptops/{laptop_id}/attachments/{attachment_id}/delete")
    def attachment_delete(request: Request, laptop_id: int, attachment_id: int, form: CheckedForm):
        request.app.state.store.delete_attachment(laptop_id, attachment_id)
        return redirect(request, f"/laptops/{laptop_id}", "Attachment deleted.")

    @app.get("/parts")
    def parts(request: Request, q: str = "", archived: bool = False):
        return page(request, "parts.html", nav="parts", parts=request.app.state.store.parts(q, archived), q=q, archived=archived)

    @app.get("/parts/new")
    def part_new(request: Request):
        return page(request, "part_form.html", nav="parts", part=None, values={"unit_price": "0.00", "stock": "0"})

    @app.post("/parts/new")
    def part_create(request: Request, form: CheckedForm):
        try:
            request.app.state.store.save_part(form)
        except DomainError as error:
            return page(request, "part_form.html", nav="parts", part=None, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, "/parts", "Part added.")

    @app.get("/parts/{part_id}/edit")
    def part_edit(request: Request, part_id: int):
        part = request.app.state.store.part(part_id)
        return page(request, "part_form.html", nav="parts", part=part, values={**part, "unit_price": money_input(part["unit_price"])})

    @app.post("/parts/{part_id}/edit")
    def part_update(request: Request, part_id: int, form: CheckedForm):
        store = request.app.state.store
        part = store.part(part_id)
        try:
            store.save_part(form, part_id)
        except DomainError as error:
            return page(request, "part_form.html", nav="parts", part=part, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, "/parts", "Part updated.")

    @app.post("/parts/{part_id}/delete")
    def part_delete(request: Request, part_id: int, form: CheckedForm):
        notice = request.app.state.store.delete_part(part_id)
        return redirect(request, "/parts", notice)

    @app.post("/parts/{part_id}/restore")
    def part_restore(request: Request, part_id: int, form: CheckedForm):
        request.app.state.store.restore_part(part_id)
        return redirect(request, "/parts", "Part restored.")

    @app.get("/laptops/{laptop_id}/recover")
    def recovery_form(request: Request, laptop_id: int):
        laptop = request.app.state.store.laptop(laptop_id)
        return page(request, "recovery_form.html", nav="laptops", laptop=laptop,
                    values={"stock": "1", "unit_price": "0.00"})

    @app.post("/laptops/{laptop_id}/recover")
    def recover_part(request: Request, laptop_id: int, form: CheckedForm):
        store = request.app.state.store
        laptop = store.laptop(laptop_id)
        try:
            store.recover_part(laptop_id, form)
        except DomainError as error:
            return page(request, "recovery_form.html", nav="laptops", laptop=laptop, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, f"/laptops/{laptop_id}", "Recovered part batch added to inventory. No income recorded yet.")

    @app.get("/parts/{part_id}/sell")
    def part_sale_form(request: Request, part_id: int):
        store = request.app.state.store
        part = store.part(part_id)
        if part["donor_laptop_id"] is None:
            raise DomainError("Direct sales are available for recovered parts only.")
        return page(request, "recovery_sale_form.html", nav="parts", part=part,
                    laptop=store.laptop(part["donor_laptop_id"]), values={"quantity": "1"})

    @app.post("/parts/{part_id}/sell")
    def part_sale(request: Request, part_id: int, form: CheckedForm):
        store = request.app.state.store
        part = store.part(part_id)
        if part["donor_laptop_id"] is None:
            raise DomainError("Direct sales are available for recovered parts only.")
        laptop = store.laptop(part["donor_laptop_id"])
        try:
            store.sell_recovered_part(part_id, form)
        except DomainError as error:
            return page(request, "recovery_sale_form.html", nav="parts", part=part, laptop=laptop, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, f"/laptops/{laptop['id']}", "Part sale recorded; stock and donor proceeds updated.")

    @app.get("/laptops/{laptop_id}/scrap")
    def scrap_sale_form(request: Request, laptop_id: int):
        return page(request, "recovery_sale_form.html", nav="laptops", part=None,
                    laptop=request.app.state.store.laptop(laptop_id), values={})

    @app.post("/laptops/{laptop_id}/scrap")
    def scrap_sale(request: Request, laptop_id: int, form: CheckedForm):
        store = request.app.state.store
        laptop = store.laptop(laptop_id)
        try:
            store.sell_scrap(laptop_id, form)
        except DomainError as error:
            return page(request, "recovery_sale_form.html", nav="laptops", part=None, laptop=laptop, values=form,
                        error=error.message, status_code=error.status_code)
        return redirect(request, f"/laptops/{laptop_id}", "Chassis / scrap proceeds recorded.")

    @app.post("/laptops/{laptop_id}/recovery-sales/{sale_id}/cancel")
    def cancel_recovery_sale(request: Request, laptop_id: int, sale_id: int, form: CheckedForm):
        request.app.state.store.cancel_recovery_sale(laptop_id, sale_id)
        return redirect(request, f"/laptops/{laptop_id}", "Sale cancelled; proceeds reversed and any sold parts returned to stock.")

    return app


app = create_app()
