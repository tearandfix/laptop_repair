"""SQLite schema and explicit, short-lived transactions."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

STATUSES = {
    "purchased": "Purchased",
    "shipped_usa": "Shipped USA",
    "np_accepted": "NP accepted",
    "shipped_ua": "Shipped UA",
    "delivered": "Delivered",
    "fixed": "Fixed",
    "listed": "Listed",
    "sold": "Sold",
    "unrepairable": "Unrepairable",
    "parted_out": "Parted out",
}

DONOR_STATUSES = {"unrepairable", "parted_out"}
SCHEMA_VERSION = 3

LAPTOP_SCHEMA = """
CREATE TABLE IF NOT EXISTS laptops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    purchase_price INTEGER NOT NULL CHECK(purchase_price >= 0),
    shipping_cost INTEGER NOT NULL CHECK(shipping_cost >= 0),
    resale_price INTEGER CHECK(resale_price >= 0),
    status TEXT NOT NULL DEFAULT 'purchased' CHECK(status IN (
        'purchased', 'shipped_usa', 'np_accepted', 'shipped_ua',
        'delivered', 'fixed', 'listed', 'sold', 'unrepairable', 'parted_out')),
    notes TEXT NOT NULL DEFAULT '',
    resale_description TEXT NOT NULL DEFAULT '',
    ebay_url TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

SCHEMA = LAPTOP_SCHEMA + """
CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
    comment TEXT NOT NULL DEFAULT '',
    stock INTEGER NOT NULL CHECK(stock >= 0),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1,
    donor_laptop_id INTEGER REFERENCES laptops(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS laptop_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    laptop_id INTEGER NOT NULL REFERENCES laptops(id) ON DELETE CASCADE,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
    quantity INTEGER NOT NULL CHECK(quantity > 0)
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    laptop_id INTEGER NOT NULL REFERENCES laptops(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    storage_name TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL CHECK(size >= 0)
);
CREATE TABLE IF NOT EXISTS recovery_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_laptop_id INTEGER NOT NULL REFERENCES laptops(id) ON DELETE RESTRICT,
    part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    quantity INTEGER,
    amount INTEGER NOT NULL CHECK(amount >= 0),
    comment TEXT NOT NULL DEFAULT '',
    cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    cancelled_at TEXT,
    CHECK((part_id IS NULL AND quantity IS NULL) OR (part_id IS NOT NULL AND quantity > 0))
);
CREATE INDEX IF NOT EXISTS laptop_parts_laptop ON laptop_parts(laptop_id);
CREATE INDEX IF NOT EXISTS laptop_parts_part ON laptop_parts(part_id);
CREATE INDEX IF NOT EXISTS attachments_laptop ON attachments(laptop_id);
CREATE INDEX IF NOT EXISTS laptops_status ON laptops(status);
CREATE INDEX IF NOT EXISTS recovery_sales_donor ON recovery_sales(donor_laptop_id);
"""


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "laptop_repair.sqlite3"

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # SQLite needs FK enforcement disabled outside the transaction to replace
        # the laptops table's status CHECK without cascading deletes into repairs.
        with self.connect(write=True, foreign_keys=False) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError("Database is newer than this application version.")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(laptops)")}
            if columns and version < 3:
                if "resale_description" not in columns:
                    conn.execute("ALTER TABLE laptops ADD COLUMN resale_description TEXT NOT NULL DEFAULT ''")
                sequence = conn.execute("SELECT seq FROM sqlite_sequence WHERE name='laptops'").fetchone()
                conn.execute(LAPTOP_SCHEMA.replace("IF NOT EXISTS laptops", "laptops_new"))
                names = "id, title, purchase_price, shipping_cost, resale_price, status, notes, resale_description, ebay_url, version, created_at"
                conn.execute(f"INSERT INTO laptops_new ({names}) SELECT {names} FROM laptops")
                conn.execute("DROP TABLE laptops")
                conn.execute("ALTER TABLE laptops_new RENAME TO laptops")
                if sequence:
                    conn.execute("UPDATE sqlite_sequence SET seq=MAX(seq, ?) WHERE name='laptops'", (sequence[0],))
            # Execute individual DDL statements without executescript's implicit
            # commit: migrations either succeed in full or roll back in full.
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            part_columns = {row[1] for row in conn.execute("PRAGMA table_info(parts)")}
            if "donor_laptop_id" not in part_columns:
                conn.execute("ALTER TABLE parts ADD COLUMN donor_laptop_id INTEGER REFERENCES laptops(id) ON DELETE RESTRICT")
            conn.execute("CREATE INDEX IF NOT EXISTS parts_donor ON parts(donor_laptop_id)")
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Database migration found broken references; no changes were saved.")
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def connect(self, *, write=False, foreign_keys=True):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
        try:
            # Reserve the write lock BEFORE reading stock, preventing lost updates.
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
