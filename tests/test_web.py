import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import MAX_FILE_SIZE
from conftest import edit_laptop, edit_part, laptop_form, part_form


def token(client, prefix=""):
    response = client.get(prefix + "/laptops/new")
    assert response.status_code == 200
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def post(client, path, data=None, files=None):
    return client.post(path, data={"csrf_token": token(client), **(data or {})}, files=files, follow_redirects=False)


def test_full_purchase_repair_sale_workflow(client):
    store = client.app.state.store
    assert post(client, "/parts/new", part_form()).status_code == 303
    response = post(client, "/laptops/new", laptop_form())
    assert response.status_code == 303
    laptop_id = store.laptops()[0]["id"]
    part_id = store.parts()[0]["id"]
    assert "Laptop added" in client.get(response.headers["location"]).text
    detail = f"/laptops/{laptop_id}"
    assert post(client, detail + "/parts", {"part_id": str(part_id), "quantity": "2"}).status_code == 303
    assert store.part(part_id)["stock"] == 3
    assert "5,400 UAH" in client.get(detail).text
    assert post(client, detail + "/edit", edit_laptop(store, laptop_id, status="sold", resale_price="7000.50")).status_code == 303
    assert "1,601 UAH" in client.get(detail).text
    assert "1,601 UAH" in client.get("/").text
    assert "ThinkPad T480" in client.get("/laptops?status=sold&q=thinkpad").text
    assert "No laptops found" in client.get("/laptops?status=fixed").text
    assert post(client, f"/parts/{part_id}/edit", edit_part(store, part_id, unit_price="500")).status_code == 303
    assert store.laptop(laptop_id)["repair_cost"] == 60000
    assignment = store.laptop(laptop_id)["assignments"][0]["id"]
    assignment_path = detail + f"/parts/{assignment}"
    assert post(client, assignment_path + "/edit", {"quantity": "1"}).status_code == 303
    assert store.part(part_id)["stock"] == 4
    assert post(client, assignment_path + "/delete").status_code == 303
    assert store.part(part_id)["stock"] == 5
    assert post(client, detail + "/delete").status_code == 303
    assert client.get(detail).status_code == 404


def test_multiline_resale_description_create_edit_display_and_clear(client):
    store = client.app.state.store
    description = "ThinkPad T480\n\nRepaired and tested.\n<script>Plain text only</script>"
    response = post(client, "/laptops/new", laptop_form(resale_description=description))
    assert response.status_code == 303
    laptop = store.laptops()[0]
    assert laptop["resale_description"] == description
    detail = f"/laptops/{laptop['id']}"
    html = client.get(detail).text
    assert 'class="preserve-lines">ThinkPad T480\n\nRepaired and tested.' in html
    assert "&lt;script&gt;Plain text only&lt;/script&gt;" in html
    assert "<script>Plain text only</script>" not in html
    edit_html = client.get(detail + "/edit").text
    assert '<textarea name="resale_description"' in edit_html
    assert "ThinkPad T480\n\nRepaired and tested." in edit_html
    updated = "Updated listing\nIncludes charger"
    form = edit_laptop(store, laptop["id"], resale_description=updated)
    invalid = post(client, detail + "/edit", {**form, "purchase_price": "-1"})
    assert invalid.status_code == 400
    assert updated in invalid.text
    assert post(client, detail + "/edit", form).status_code == 303
    assert store.laptop(laptop["id"])["resale_description"] == updated
    assert post(client, detail + "/edit", edit_laptop(store, laptop["id"], resale_description="x" * 10001)).status_code == 400
    assert post(client, detail + "/edit", edit_laptop(store, laptop["id"], resale_description="")).status_code == 303
    assert store.laptop(laptop["id"])["resale_description"] == ""


def test_csrf_missing_forged_and_cross_browser(client, tmp_path):
    csrf = token(client)
    assert client.post("/parts/new", data=part_form()).status_code == 403
    assert client.post("/parts/new", data={**part_form(), "csrf_token": "fake"}).status_code == 403
    assert client.post("/parts/new", data={**part_form(), "csrf_token": "токен"}).status_code == 403
    with TestClient(create_app(tmp_path)) as other:
        assert other.post("/parts/new", data={**part_form(), "csrf_token": csrf}).status_code == 403
    client.cookies.set("laptop_repair_csrf", "forged")
    assert client.post("/parts/new", data={**part_form(), "csrf_token": "forged"}).status_code == 403
    assert client.app.state.store.parts() == []


def test_forms_preserve_values_and_escape_html(client):
    response = post(client, "/laptops/new", laptop_form(title="<script>alert(1)</script>", purchase_price="-1"))
    assert response.status_code == 400
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "No power" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert post(client, "/parts/new", part_form(stock="-1")).status_code == 400
    assert client.get("/laptops/invalid").status_code == 422
    assert client.get("/laptops/999").status_code == 404
    assert client.get("/laptops?status=unknown").status_code == 400


def test_archive_and_restore_through_ui(client):
    store = client.app.state.store
    laptop = store.save_laptop(laptop_form())
    part = store.save_part(part_form())
    store.assign(laptop, part, "1")
    assert post(client, f"/parts/{part}/delete").status_code == 303
    assert "RAM 8GB" in client.get("/parts?archived=true").text
    assert "This part is archived" in client.get(f"/parts/{part}/edit").text
    assert post(client, f"/parts/{part}/restore").status_code == 303
    assert store.part(part)["archived"] == 0


def test_upload_download_delete_and_laptop_cleanup(client):
    store = client.app.state.store
    laptop = store.save_laptop(laptop_form())
    other = store.save_laptop(laptop_form(title="Other"))
    base = f"/laptops/{laptop}"
    files = [("files", ("../../receipt.html", b"<script>test</script>", "text/html")),
             ("files", ("Фото.txt", b"photo", "text/plain"))]
    assert post(client, base + "/attachments", files=files).status_code == 303
    attachments = store.laptop(laptop)["attachments"]
    assert len(attachments) == 2
    assert len(list(store.upload_dir.iterdir())) == 2
    assert all(re.fullmatch(r"[a-f0-9]{32}", row["storage_name"]) for row in attachments)
    first = attachments[0]["id"]
    response = client.get(base + f"/attachments/{first}")
    assert response.content == b"<script>test</script>"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/laptops/{other}/attachments/{first}").status_code == 404
    assert post(client, f"/laptops/{other}/attachments/{first}/delete").status_code == 404
    assert post(client, base + f"/attachments/{first}/delete").status_code == 303
    assert len(list(store.upload_dir.iterdir())) == 1
    part = store.save_part(part_form())
    store.assign(laptop, part, "2")
    assert post(client, base + "/delete").status_code == 303
    assert list(store.upload_dir.iterdir()) == []
    assert store.part(part)["stock"] == 5


def test_oversized_upload_rolls_back_all_files(client):
    store = client.app.state.store
    laptop = store.save_laptop(laptop_form())
    response = post(client, f"/laptops/{laptop}/attachments", files=[
        ("files", ("small.txt", b"small")),
        ("files", ("large.bin", b"x" * (MAX_FILE_SIZE + 1))),
    ])
    assert response.status_code == 413
    assert store.laptop(laptop)["attachments"] == []
    assert list(store.upload_dir.iterdir()) == []
    assert post(client, f"/laptops/{laptop}/attachments").status_code == 400


def test_upload_count_limit(client):
    store = client.app.state.store
    laptop = store.save_laptop(laptop_form())
    response = post(client, f"/laptops/{laptop}/attachments", files=[
        ("files", (f"{index}.txt", b"text")) for index in range(11)
    ])
    assert response.status_code == 400
    assert store.laptop(laptop)["attachments"] == []


def test_restart_retains_data_files_and_cookie(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        laptop = app.state.store.save_laptop(laptop_form())
        assert post(client, f"/laptops/{laptop}/attachments", files={"files": ("receipt.txt", b"receipt")}).status_code == 303
        csrf = token(client)
        cookie = client.cookies.get("laptop_repair_csrf")
    (tmp_path / "uploads" / ("f" * 32)).write_bytes(b"interrupted upload")
    with TestClient(create_app(tmp_path)) as client:
        client.cookies.set("laptop_repair_csrf", cookie)
        attachment = client.app.state.store.laptop(laptop)["attachments"][0]
        assert client.get(f"/laptops/{laptop}/attachments/{attachment['id']}").content == b"receipt"
        assert not (tmp_path / "uploads" / ("f" * 32)).exists()
        assert client.post("/parts/new", data={**part_form(), "csrf_token": csrf}, follow_redirects=False).status_code == 303


def test_ingress_urls_forms_assets_cookies_and_redirects(tmp_path):
    app = create_app(tmp_path)
    prefix = "/api/hassio_ingress/test-token"

    async def ingress_proxy(scope, receive, send):
        if scope["type"] == "http":
            assert scope["path"].startswith(prefix)
            scope = {**scope, "path": scope["path"][len(prefix):] or "/"}
            scope["raw_path"] = scope["path"].encode()
            scope["headers"] = [*scope["headers"], (b"x-ingress-path", prefix.encode())]
        await app(scope, receive, send)

    with TestClient(ingress_proxy) as client:
        response = client.get(prefix + "/")
        assert response.status_code == 200
        assert f"Path={prefix}/" in response.headers["set-cookie"]
        for path in ("/", "/laptops", "/laptops/new", "/parts", "/parts/new"):
            page = client.get(prefix + path)
            assert page.status_code == 200
            for url in re.findall(r'(?:href|action|src)="([^"]+)"', page.text):
                assert url.startswith((prefix + "/", "#"))
        assert client.get(prefix + "/static/style.css").status_code == 200
        csrf = token(client, prefix)
        response = client.post(prefix + "/laptops/new", data={**laptop_form(), "csrf_token": csrf}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith(prefix + "/laptops/1?")
        assert client.get(response.headers["location"]).status_code == 200


@pytest.mark.parametrize("prefix", ["//evil.example", "/../escape", "/x?y", "/x\\y"])
def test_invalid_ingress_header_is_rejected(client, prefix):
    assert client.get("/", headers={"x-ingress-path": prefix}).status_code == 400


def test_stale_forms_show_conflict(client):
    store = client.app.state.store
    laptop = store.save_laptop(laptop_form())
    part = store.save_part(part_form())
    stale_laptop = edit_laptop(store, laptop)
    stale_part = edit_part(store, part)
    store.save_laptop(edit_laptop(store, laptop, status="delivered"), laptop)
    store.assign(laptop, part, "1")
    assert post(client, f"/laptops/{laptop}/edit", stale_laptop).status_code == 409
    assert post(client, f"/parts/{part}/edit", stale_part).status_code == 409
    assert store.laptop(laptop)["status"] == "delivered"
    assert store.part(part)["stock"] == 4


def test_health_and_addon_configuration(client):
    assert client.get("/health").json() == {"status": "ok"}
    config = yaml.safe_load((Path(__file__).parents[1] / "laptop_repair/config.yaml").read_text())
    assert config["ingress"] is True
    assert config["ingress_port"] == 8099
    assert config["backup"] == "cold"
    assert set(config["arch"]) == {"amd64", "aarch64"}
    assert "ports" not in config
