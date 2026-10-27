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
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS laptops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    purchase_price INTEGER NOT NULL CHECK(purchase_price >= 0),
    shipping_cost INTEGER NOT NULL CHECK(shipping_cost >= 0),
    resale_price INTEGER CHECK(resale_price >= 0),
    status TEXT NOT NULL DEFAULT 'purchased' CHECK(status IN (
        'purchased', 'shipped_usa', 'np_accepted', 'shipped_ua',
        'delivered', 'fixed', 'listed', 'sold')),
    notes TEXT NOT NULL DEFAULT '',
    ebay_url TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
    comment TEXT NOT NULL DEFAULT '',
    stock INTEGER NOT NULL CHECK(stock >= 0),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1
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
CREATE INDEX IF NOT EXISTS laptop_parts_laptop ON laptop_parts(laptop_id);
CREATE INDEX IF NOT EXISTS laptop_parts_part ON laptop_parts(part_id);
CREATE INDEX IF NOT EXISTS attachments_laptop ON attachments(laptop_id);
CREATE INDEX IF NOT EXISTS laptops_status ON laptops(status);
PRAGMA user_version = 1;
"""


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "laptop_repair.sqlite3"

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database is newer than this application version.")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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
