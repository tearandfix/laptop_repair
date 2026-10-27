"""Validation, exact money calculations, inventory rules, and file storage."""

import logging
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from .db import DONOR_STATUSES, STATUSES, Database

MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_MONEY = 99_999_999_999
MAX_QUANTITY = 1_000_000
logger = logging.getLogger(__name__)


class DomainError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def text(value, label, *, required=False, limit=10000):
    if not isinstance(value, str):
        raise DomainError(f"{label} must be text.")
    value = value.strip()
    if required and not value:
        raise DomainError(f"{label} is required.")
    if len(value) > limit:
        raise DomainError(f"{label} must be at most {limit} characters.")
    return value


def money(value, label="Price", *, optional=False):
    value = text(value, label, limit=30)
    if optional and not value:
        return None
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise DomainError(f"{label} must be a non-negative amount with at most two decimal places.")
    whole, _, fraction = value.partition(".")
    cents = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if cents > MAX_MONEY:
        raise DomainError(f"{label} must not exceed 999,999,999.99 UAH.")
    return cents


def integer(value, label="Quantity", *, minimum=0, maximum=MAX_QUANTITY):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}", value):
        raise DomainError(f"{label} must be a whole number.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise DomainError(f"{label} must be between {minimum:,} and {maximum:,}.")
    return number


def money_input(cents):
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def money_display(cents):
    if cents is None:
        return "—"
    # Round half away from zero using integer arithmetic; avoid displaying −0.
    whole = (abs(cents) + 50) // 100
    sign = "−" if cents < 0 and whole else ""
    return f"{sign}{whole:,} UAH"


def laptop_values(form):
    status = text(form.get("status", "purchased"), "Status")
    if status not in STATUSES:
        raise DomainError("Choose a valid laptop status.")
    url = text(form.get("ebay_url", ""), "eBay URL", limit=2000)
    if url:
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ("http", "https") and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid:
            raise DomainError("eBay URL must be an HTTP or HTTPS link.")
    return {
        "title": text(form.get("title", ""), "Title", required=True, limit=200),
        "purchase_price": money(form.get("purchase_price", ""), "Purchase price"),
        "shipping_cost": money(form.get("shipping_cost", ""), "Shipping cost"),
        "resale_price": money(form.get("resale_price", ""), "Resale price", optional=True),
        "status": status,
        "notes": text(form.get("notes", ""), "Notes"),
        "resale_description": text(form.get("resale_description", ""), "Resale listing description"),
        "ebay_url": url,
    }


def part_values(form):
    return {
        "title": text(form.get("title", ""), "Title", required=True, limit=200),
        "unit_price": money(form.get("unit_price", ""), "Unit price"),
        "comment": text(form.get("comment", ""), "Comment"),
        "stock": integer(form.get("stock", ""), "Stock quantity"),
    }


def required_row(conn, table, record_id):
    # Table names are only supplied by internal callers, never request input.
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
    if row is None:
        raise DomainError("The requested record was not found.", 404)
    return dict(row)


LAPTOP_QUERY = """
SELECT l.*, COALESCE(p.repair_cost, 0) AS repair_cost,
    COALESCE(p.transfer_cost, 0) AS transfer_cost,
    COALESCE(t.transfer_credits, 0) AS transfer_credits,
    COALESCE(s.part_sales, 0) AS part_sales,
    COALESCE(s.scrap_sales, 0) AS scrap_sales,
    COALESCE(s.sale_count, 0) AS recovery_sale_count,
    COALESCE(r.batch_count, 0) AS recovered_batch_count,
    COALESCE(r.stock_value, 0) AS recovered_stock_value
FROM laptops l LEFT JOIN (
    SELECT lp.laptop_id, SUM(lp.unit_price * lp.quantity) AS repair_cost,
        SUM(CASE WHEN p.donor_laptop_id IS NOT NULL THEN lp.unit_price * lp.quantity ELSE 0 END) AS transfer_cost
    FROM laptop_parts lp JOIN parts p ON p.id = lp.part_id GROUP BY lp.laptop_id
) p ON p.laptop_id = l.id
LEFT JOIN (
    SELECT p.donor_laptop_id, SUM(lp.unit_price * lp.quantity) AS transfer_credits
    FROM laptop_parts lp JOIN parts p ON p.id = lp.part_id
    WHERE p.donor_laptop_id IS NOT NULL GROUP BY p.donor_laptop_id
) t ON t.donor_laptop_id = l.id
LEFT JOIN (
    SELECT donor_laptop_id, COUNT(*) AS sale_count,
        SUM(CASE WHEN cancelled=0 AND part_id IS NOT NULL THEN amount ELSE 0 END) AS part_sales,
        SUM(CASE WHEN cancelled=0 AND part_id IS NULL THEN amount ELSE 0 END) AS scrap_sales
    FROM recovery_sales GROUP BY donor_laptop_id
) s ON s.donor_laptop_id = l.id
LEFT JOIN (
    SELECT donor_laptop_id, COUNT(*) AS batch_count, SUM(stock * unit_price) AS stock_value
    FROM parts WHERE donor_laptop_id IS NOT NULL GROUP BY donor_laptop_id
) r ON r.donor_laptop_id = l.id
"""


def with_totals(row):
    laptop = dict(row)
    laptop["total_cost"] = laptop["purchase_price"] + laptop["shipping_cost"] + laptop["repair_cost"]
    laptop["external_cost"] = laptop["total_cost"] - laptop["transfer_cost"]
    laptop["recovery_cash"] = laptop["part_sales"] + laptop["scrap_sales"]
    laptop["has_recovery_history"] = bool(laptop["recovered_batch_count"] or laptop["recovery_sale_count"])
    laptop["is_donor"] = laptop["has_recovery_history"] or laptop["status"] in DONOR_STATUSES
    laptop["profit"] = (
        None if laptop["resale_price"] is None and not laptop["is_donor"] else
        (laptop["resale_price"] or 0) + laptop["recovery_cash"] + laptop["transfer_credits"] - laptop["total_cost"]
    )
    return laptop


class Store:
    def __init__(self, data_dir: Path):
        self.db = Database(data_dir)
        self.upload_dir = data_dir / "uploads"

    def initialize(self):
        self.db.initialize()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        # Recover unreferenced files left by an interrupted upload or deletion.
        with self.db.connect() as conn:
            referenced = {row[0] for row in conn.execute("SELECT storage_name FROM attachments")}
        for path in self.upload_dir.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}", path.name) and path.name not in referenced:
                self.remove_files([path.name])

    def laptops(self, query="", status=""):
        with self.db.connect() as conn:
            rows = conn.execute(
                LAPTOP_QUERY + " WHERE instr(lower(l.title), lower(?)) > 0 "
                "AND (? = '' OR l.status = ?) ORDER BY l.id DESC",
                (query, status, status),
            ).fetchall()
        return [with_totals(row) for row in rows]

    def laptop(self, laptop_id):
        with self.db.connect() as conn:
            row = conn.execute(LAPTOP_QUERY + " WHERE l.id = ?", (laptop_id,)).fetchone()
            if row is None:
                raise DomainError("Laptop not found.", 404)
            laptop = with_totals(row)
            laptop["assignments"] = [dict(r) for r in conn.execute(
                "SELECT lp.*, p.archived, p.donor_laptop_id FROM laptop_parts lp JOIN parts p ON p.id = lp.part_id "
                "WHERE lp.laptop_id = ? ORDER BY lp.id", (laptop_id,)
            )]
            laptop["attachments"] = [dict(r) for r in conn.execute(
                "SELECT * FROM attachments WHERE laptop_id = ? ORDER BY id", (laptop_id,)
            )]
            laptop["recovered_parts"] = [dict(r) for r in conn.execute(
                "SELECT p.*, COALESCE(a.assigned, 0) AS assigned, COALESCE(s.sold, 0) AS sold "
                "FROM parts p LEFT JOIN (SELECT part_id, SUM(quantity) AS assigned FROM laptop_parts GROUP BY part_id) "
                "a ON a.part_id=p.id LEFT JOIN (SELECT part_id, SUM(quantity) AS sold FROM recovery_sales "
                "WHERE cancelled=0 GROUP BY part_id) s ON s.part_id=p.id WHERE p.donor_laptop_id=? ORDER BY p.id",
                (laptop_id,),
            )]
            laptop["recovery_sales"] = [dict(r) for r in conn.execute(
                "SELECT * FROM recovery_sales WHERE donor_laptop_id=? ORDER BY id DESC", (laptop_id,)
            )]
            laptop["transfers"] = [dict(r) for r in conn.execute(
                "SELECT lp.*, l.title AS recipient_title FROM laptop_parts lp JOIN parts p ON p.id=lp.part_id "
                "JOIN laptops l ON l.id=lp.laptop_id WHERE p.donor_laptop_id=? ORDER BY lp.id", (laptop_id,)
            )]
        return laptop

    def save_laptop(self, form, laptop_id=None):
        values = laptop_values(form)
        with self.db.connect(write=True) as conn:
            if laptop_id is None:
                cursor = conn.execute(
                    "INSERT INTO laptops (title, purchase_price, shipping_cost, resale_price, status, notes, ebay_url, resale_description) "
                    "VALUES (:title, :purchase_price, :shipping_cost, :resale_price, :status, :notes, :ebay_url, :resale_description)",
                    values,
                )
                return cursor.lastrowid
            required_row(conn, "laptops", laptop_id)
            values.update(id=laptop_id, version=integer(form.get("version", ""), "Record version", minimum=1))
            cursor = conn.execute(
                "UPDATE laptops SET title=:title, purchase_price=:purchase_price, shipping_cost=:shipping_cost, "
                "resale_price=:resale_price, status=:status, notes=:notes, ebay_url=:ebay_url, "
                "resale_description=:resale_description, version=version+1 "
                "WHERE id=:id AND version=:version", values,
            )
            if not cursor.rowcount:
                raise DomainError("This laptop changed since you opened it. Reload before saving again.", 409)
        return laptop_id

    def parts(self, query="", archived=False):
        with self.db.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT p.*, l.title AS donor_title FROM parts p LEFT JOIN laptops l ON l.id=p.donor_laptop_id "
                "WHERE p.archived = ? "
                "AND (instr(lower(p.title), lower(?)) > 0 OR instr(lower(p.comment), lower(?)) > 0) "
                "ORDER BY p.title COLLATE NOCASE, p.id", (int(archived), query, query),
            )]

    def part(self, part_id):
        with self.db.connect() as conn:
            part = required_row(conn, "parts", part_id)
            part["donor_title"] = (
                required_row(conn, "laptops", part["donor_laptop_id"])["title"]
                if part["donor_laptop_id"] is not None else None
            )
            return part

    def save_part(self, form, part_id=None):
        values = part_values(form)
        with self.db.connect(write=True) as conn:
            if part_id is None:
                return conn.execute(
                    "INSERT INTO parts (title, unit_price, comment, stock) VALUES (:title, :unit_price, :comment, :stock)",
                    values,
                ).lastrowid
            required_row(conn, "parts", part_id)
            values.update(id=part_id, version=integer(form.get("version", ""), "Record version", minimum=1))
            result = conn.execute(
                "UPDATE parts SET title=:title, unit_price=:unit_price, comment=:comment, stock=:stock, version=version+1 "
                "WHERE id=:id AND version=:version", values,
            )
            if not result.rowcount:
                raise DomainError("This part or its stock changed since you opened it. Reload before saving again.", 409)
        return part_id

    def delete_part(self, part_id):
        with self.db.connect(write=True) as conn:
            part = required_row(conn, "parts", part_id)
            used = part["donor_laptop_id"] is not None or conn.execute(
                "SELECT 1 FROM laptop_parts WHERE part_id = ? LIMIT 1", (part_id,)
            ).fetchone()
            if used:
                conn.execute("UPDATE parts SET archived=1, version=version+1 WHERE id=?", (part_id,))
            else:
                conn.execute("DELETE FROM parts WHERE id=?", (part_id,))
        return "Part archived; repair and recovery history are preserved." if used else "Part deleted."

    def restore_part(self, part_id):
        with self.db.connect(write=True) as conn:
            required_row(conn, "parts", part_id)
            conn.execute("UPDATE parts SET archived=0, version=version+1 WHERE id=?", (part_id,))

    def assign(self, laptop_id, part_id, quantity, transfer_value=""):
        quantity = integer(quantity, minimum=1)
        with self.db.connect(write=True) as conn:
            required_row(conn, "laptops", laptop_id)
            part = required_row(conn, "parts", part_id)
            if part["donor_laptop_id"] == laptop_id:
                raise DomainError("A recovered part cannot be assigned back to its own donor laptop.")
            if part["archived"]:
                raise DomainError("Restore this archived part before assigning it.")
            if part["stock"] < quantity:
                raise DomainError(f"Not enough stock: only {part['stock']} available.")
            transfer_value = text(transfer_value, "Transfer value")
            if transfer_value and part["donor_laptop_id"] is None:
                raise DomainError("A transfer value can only be entered for a recovered part.")
            unit_price = money(transfer_value, "Transfer value") if transfer_value else part["unit_price"]
            conn.execute("UPDATE parts SET stock=stock-?, version=version+1 WHERE id=?", (quantity, part_id))
            return conn.execute(
                "INSERT INTO laptop_parts (laptop_id, part_id, title, unit_price, quantity) VALUES (?, ?, ?, ?, ?)",
                (laptop_id, part_id, part["title"], unit_price, quantity),
            ).lastrowid

    def change_assignment(self, laptop_id, assignment_id, quantity):
        # Zero is used exclusively by the explicit removal action.
        quantity = integer(quantity)
        with self.db.connect(write=True) as conn:
            assignment = required_row(conn, "laptop_parts", assignment_id)
            if assignment["laptop_id"] != laptop_id:
                raise DomainError("Assignment not found on this laptop.", 404)
            part = required_row(conn, "parts", assignment["part_id"])
            difference = quantity - assignment["quantity"]
            if difference > 0 and part["archived"]:
                raise DomainError("Restore this archived part before assigning additional units.")
            if difference > part["stock"]:
                raise DomainError(f"Not enough stock: only {part['stock']} additional units available.")
            conn.execute("UPDATE parts SET stock=stock-?, version=version+1 WHERE id=?", (difference, part["id"]))
            if quantity == 0:
                conn.execute("DELETE FROM laptop_parts WHERE id=?", (assignment_id,))
            else:
                conn.execute("UPDATE laptop_parts SET quantity=? WHERE id=?", (quantity, assignment_id))

    def delete_laptop(self, laptop_id):
        with self.db.connect(write=True) as conn:
            required_row(conn, "laptops", laptop_id)
            if conn.execute("SELECT 1 FROM parts WHERE donor_laptop_id=? LIMIT 1", (laptop_id,)).fetchone() or conn.execute(
                "SELECT 1 FROM recovery_sales WHERE donor_laptop_id=? LIMIT 1", (laptop_id,)
            ).fetchone():
                raise DomainError("This donor has recovery history and must be retained. Use the Parted out status instead.", 409)
            for row in conn.execute("SELECT part_id, SUM(quantity) FROM laptop_parts WHERE laptop_id=? GROUP BY part_id", (laptop_id,)):
                conn.execute("UPDATE parts SET stock=stock+?, version=version+1 WHERE id=?", (row[1], row[0]))
            files = [r[0] for r in conn.execute("SELECT storage_name FROM attachments WHERE laptop_id=?", (laptop_id,))]
            conn.execute("DELETE FROM laptops WHERE id=?", (laptop_id,))
        self.remove_files(files)

    def recover_part(self, laptop_id, form):
        values = part_values(form)
        if values["stock"] < 1:
            raise DomainError("Recover at least one unit.")
        with self.db.connect(write=True) as conn:
            donor = required_row(conn, "laptops", laptop_id)
            if donor["status"] not in DONOR_STATUSES:
                raise DomainError("Set the laptop status to Unrepairable or Parted out before recovering parts.")
            return conn.execute(
                "INSERT INTO parts (title, unit_price, comment, stock, donor_laptop_id) VALUES (?, ?, ?, ?, ?)",
                (values["title"], values["unit_price"], values["comment"], values["stock"], laptop_id),
            ).lastrowid

    def sell_recovered_part(self, part_id, form):
        quantity = integer(form.get("quantity", ""), minimum=1)
        amount = money(form.get("amount", ""), "Total sale amount")
        comment = text(form.get("comment", ""), "Sale comment")
        with self.db.connect(write=True) as conn:
            part = required_row(conn, "parts", part_id)
            if part["donor_laptop_id"] is None:
                raise DomainError("Direct sales are available for recovered parts only.")
            if part["archived"]:
                raise DomainError("Restore this archived part before selling it.")
            if part["stock"] < quantity:
                raise DomainError(f"Not enough stock: only {part['stock']} available.")
            conn.execute("UPDATE parts SET stock=stock-?, version=version+1 WHERE id=?", (quantity, part_id))
            return conn.execute(
                "INSERT INTO recovery_sales (donor_laptop_id, part_id, title, quantity, amount, comment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (part["donor_laptop_id"], part_id, part["title"], quantity, amount, comment),
            ).lastrowid

    def sell_scrap(self, laptop_id, form):
        title = text(form.get("title", ""), "Sale description", required=True, limit=200)
        amount = money(form.get("amount", ""), "Sale amount")
        comment = text(form.get("comment", ""), "Sale comment")
        with self.db.connect(write=True) as conn:
            donor = required_row(conn, "laptops", laptop_id)
            has_batches = conn.execute("SELECT 1 FROM parts WHERE donor_laptop_id=?", (laptop_id,)).fetchone()
            if donor["status"] not in DONOR_STATUSES and not has_batches:
                raise DomainError("Set the laptop status to Unrepairable or Parted out before recording scrap proceeds.")
            return conn.execute(
                "INSERT INTO recovery_sales (donor_laptop_id, title, amount, comment) VALUES (?, ?, ?, ?)",
                (laptop_id, title, amount, comment),
            ).lastrowid

    def cancel_recovery_sale(self, laptop_id, sale_id):
        with self.db.connect(write=True) as conn:
            sale = required_row(conn, "recovery_sales", sale_id)
            if sale["donor_laptop_id"] != laptop_id:
                raise DomainError("Sale not found on this donor laptop.", 404)
            if sale["cancelled"]:
                raise DomainError("This sale has already been cancelled.", 409)
            if sale["part_id"] is not None:
                conn.execute(
                    "UPDATE parts SET stock=stock+?, version=version+1 WHERE id=?", (sale["quantity"], sale["part_id"])
                )
            conn.execute(
                "UPDATE recovery_sales SET cancelled=1, cancelled_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id=?",
                (sale_id,),
            )

    def add_attachments(self, laptop_id, files):
        if not files or len(files) > 10:
            raise DomainError("Choose between 1 and 10 files.")
        stored = []
        try:
            with self.db.connect(write=True) as conn:
                required_row(conn, "laptops", laptop_id)
                for upload in files:
                    filename = text(upload.filename or "", "Filename", required=True, limit=255)
                    if upload.size is not None and upload.size > MAX_FILE_SIZE:
                        raise DomainError(f"{filename} exceeds the 20 MiB file limit.", 413)
                    storage_name = uuid4().hex
                    stored.append(storage_name)
                    size = 0
                    with (self.upload_dir / storage_name).open("xb") as target:
                        while chunk := upload.file.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_FILE_SIZE:
                                raise DomainError(f"{filename} exceeds the 20 MiB file limit.", 413)
                            target.write(chunk)
                    conn.execute(
                        "INSERT INTO attachments (laptop_id, filename, storage_name, size) VALUES (?, ?, ?, ?)",
                        (laptop_id, filename, storage_name, size),
                    )
        except BaseException:
            self.remove_files(stored)
            raise

    def attachment(self, laptop_id, attachment_id):
        with self.db.connect() as conn:
            row = required_row(conn, "attachments", attachment_id)
        if row["laptop_id"] != laptop_id:
            raise DomainError("Attachment not found on this laptop.", 404)
        return row

    def delete_attachment(self, laptop_id, attachment_id):
        with self.db.connect(write=True) as conn:
            row = required_row(conn, "attachments", attachment_id)
            if row["laptop_id"] != laptop_id:
                raise DomainError("Attachment not found on this laptop.", 404)
            conn.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
        self.remove_files([row["storage_name"]])

    def remove_files(self, storage_names):
        for name in storage_names:
            try:
                (self.upload_dir / name).unlink(missing_ok=True)
            except OSError:
                logger.exception("Unable to remove attachment %s; will retry on startup", name)

    def dashboard(self):
        with self.db.connect() as conn:
            laptops = [with_totals(row) for row in conn.execute(LAPTOP_QUERY + " ORDER BY l.id DESC")]
            stock = [dict(row) for row in conn.execute("SELECT stock, unit_price, donor_laptop_id FROM parts")]
        sold = [laptop for laptop in laptops if laptop["status"] == "sold" and laptop["resale_price"] is not None]
        closed = [laptop for laptop in laptops if laptop["status"] in DONOR_STATUSES or laptop in sold]
        laptop_revenue = sum(laptop["resale_price"] for laptop in sold)
        recovery_cash = sum(laptop["recovery_cash"] for laptop in laptops)
        # Transfers allocate costs between laptops, but never create business
        # revenue or profit, even when only one side has reached a closed status.
        revenue = laptop_revenue + recovery_cash
        external_cost = sum(laptop["external_cost"] for laptop in laptops)
        return {
            "count": len(laptops),
            "total_cost": external_cost,
            "investment": sum(laptop["external_cost"] for laptop in laptops if laptop["status"] not in DONOR_STATUSES | {"sold"}),
            "stock_value": sum(part["stock"] * part["unit_price"] for part in stock),
            "recovered_stock_value": sum(part["stock"] * part["unit_price"] for part in stock if part["donor_laptop_id"] is not None),
            "laptop_revenue": laptop_revenue,
            "recovery_cash": recovery_cash,
            "transfer_credits": sum(laptop["transfer_credits"] for laptop in laptops),
            "revenue": revenue,
            "profit": revenue - sum(laptop["external_cost"] for laptop in closed),
            "workspace_result": revenue - external_cost,
            "missing_sales": sum(laptop["status"] == "sold" and laptop["resale_price"] is None for laptop in laptops),
            "status_counts": {status: sum(laptop["status"] == status for laptop in laptops) for status in STATUSES},
            "recent": laptops[:5],
        }
