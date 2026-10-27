import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.services import DomainError, Store
from conftest import edit_laptop, edit_part, laptop_form, part_form


def donor_and_recipient(store):
    donor = store.save_laptop(laptop_form(title="Donor", purchase_price="2000", shipping_cost="0", status="unrepairable"))
    recipient = store.save_laptop(laptop_form(title="Recipient", purchase_price="1000", shipping_cost="0"))
    return donor, recipient


def recover(store, donor, **overrides):
    return store.recover_part(donor, part_form(title="Screen", stock="1", unit_price="700", **overrides))


def test_recovery_estimates_and_transfers_do_not_create_business_profit(store):
    donor, recipient = donor_and_recipient(store)
    batch = recover(store, donor)
    assert store.laptop(donor)["profit"] == -200000
    assert store.laptop(donor)["recovered_stock_value"] == 70000
    before = store.dashboard()
    assert before["revenue"] == 0
    assert before["profit"] == -200000
    assert before["workspace_result"] == -300000

    assignment = store.assign(recipient, batch, "1")
    assert store.part(batch)["stock"] == 0
    assert store.laptop(donor)["transfer_credits"] == 70000
    assert store.laptop(donor)["profit"] == -130000
    assert store.laptop(recipient)["total_cost"] == 170000
    assert store.laptop(recipient)["external_cost"] == 100000
    after = store.dashboard()
    for key in ("revenue", "profit", "workspace_result", "total_cost", "investment"):
        assert after[key] == before[key]
    assert after["transfer_credits"] == 70000

    store.save_laptop(edit_laptop(store, recipient, status="sold", resale_price="2000"), recipient)
    assert store.laptop(recipient)["profit"] == 30000
    assert store.dashboard()["profit"] == -100000
    assert sum(laptop["profit"] for laptop in store.laptops()) == -100000
    store.change_assignment(recipient, assignment, "0")
    assert store.laptop(donor)["transfer_credits"] == 0
    assert store.laptop(recipient)["repair_cost"] == 0
    assert store.dashboard()["profit"] == -100000


def test_transfer_values_are_frozen_and_returns_reverse_exact_credit(store):
    donor, recipient = donor_and_recipient(store)
    batch = store.recover_part(donor, part_form(stock="5", unit_price="700"))
    assignment = store.assign(recipient, batch, "2", transfer_value="650.25")
    store.save_part(edit_part(store, batch, unit_price="900", title="New title"), batch)
    assert store.laptop(donor)["transfer_credits"] == 130050
    store.change_assignment(recipient, assignment, "3")
    assert store.laptop(donor)["transfer_credits"] == 195075
    store.change_assignment(recipient, assignment, "1")
    assert store.laptop(donor)["transfer_credits"] == 65025
    assert store.part(batch)["stock"] == 4
    assert store.laptop(donor)["transfers"][0]["title"] == "RAM 8GB"
    store.assign(recipient, batch, "1")
    assert store.laptop(donor)["transfer_credits"] == 155025
    store.delete_laptop(recipient)
    assert store.laptop(donor)["transfer_credits"] == 0
    assert store.part(batch)["stock"] == 5


def test_direct_sales_and_scrap_are_cash_and_cancel_atomically(store):
    donor, _ = donor_and_recipient(store)
    batch = store.recover_part(donor, part_form(stock="3", unit_price="700"))
    sale = store.sell_recovered_part(batch, {"quantity": "2", "amount": "1100.25", "comment": "Buyer paid"})
    scrap = store.sell_scrap(donor, {"title": "Remaining chassis", "amount": "200"})
    assert store.part(batch)["stock"] == 1
    assert store.laptop(donor)["part_sales"] == 110025
    assert store.laptop(donor)["scrap_sales"] == 20000
    assert store.laptop(donor)["profit"] == -69975
    assert store.dashboard()["revenue"] == 130025
    assert store.dashboard()["profit"] == -69975
    assert store.laptop(donor)["recovered_parts"][0]["sold"] == 2

    store.delete_part(batch)
    store.cancel_recovery_sale(donor, sale)
    assert store.part(batch)["stock"] == 3
    assert store.part(batch)["archived"] == 1
    assert store.laptop(donor)["part_sales"] == 0
    assert store.dashboard()["revenue"] == 20000
    with pytest.raises(DomainError, match="already been cancelled"):
        store.cancel_recovery_sale(donor, sale)
    assert store.part(batch)["stock"] == 3
    store.cancel_recovery_sale(donor, scrap)
    assert store.laptop(donor)["profit"] == -200000
    assert store.dashboard()["revenue"] == 0
    assert all(row["cancelled"] and row["cancelled_at"] for row in store.laptop(donor)["recovery_sales"])


def test_sale_uses_total_proceeds_and_keeps_snapshot_after_inventory_edits(store):
    donor, _ = donor_and_recipient(store)
    batch = store.recover_part(donor, part_form(stock="3"))
    store.sell_recovered_part(batch, {"quantity": "2", "amount": "400"})
    store.save_part(edit_part(store, batch, unit_price="999", title="Edited name"), batch)
    sale = store.laptop(donor)["recovery_sales"][0]
    assert sale["amount"] == 40000
    assert sale["title"] == "RAM 8GB"
    assert store.dashboard()["recovery_cash"] == 40000


def test_batches_keep_distinct_donors_and_cannot_be_self_assigned(store):
    first, _ = donor_and_recipient(store)
    second = store.save_laptop(laptop_form(title="Second donor", status="parted_out"))
    purchased = store.save_part(part_form(title="Screen"))
    batch1 = recover(store, first)
    batch2 = recover(store, second)
    assert len({purchased, batch1, batch2}) == 3
    assert store.part(purchased)["donor_laptop_id"] is None
    assert store.part(batch1)["donor_laptop_id"] == first
    assert store.part(batch2)["donor_laptop_id"] == second
    with pytest.raises(DomainError, match="own donor"):
        store.assign(first, batch1, "1")
    assert store.part(batch1)["stock"] == 1
    with pytest.raises(DomainError) as error:
        store.delete_laptop(first)
    assert error.value.status_code == 409
    assert "archived" in store.delete_part(batch1)
    assert store.parts(archived=True)[0]["donor_laptop_id"] == first
    with pytest.raises(DomainError, match="recovery history"):
        store.delete_laptop(first)


def test_sale_cancellation_checks_donor_and_preserves_history(store):
    donor, other = donor_and_recipient(store)
    batch = recover(store, donor)
    sale = store.sell_recovered_part(batch, {"quantity": "1", "amount": "500"})
    with pytest.raises(DomainError) as error:
        store.cancel_recovery_sale(other, sale)
    assert error.value.status_code == 404
    assert store.part(batch)["stock"] == 0
    store.cancel_recovery_sale(donor, sale)
    with pytest.raises(DomainError, match="recovery history"):
        store.delete_laptop(donor)


def test_concurrent_sale_and_assignment_cannot_consume_same_unit(store):
    donor, recipient = donor_and_recipient(store)
    batch = recover(store, donor)
    barrier = Barrier(2)

    def act(sell):
        barrier.wait(timeout=5)
        try:
            if sell:
                store.sell_recovered_part(batch, {"quantity": "1", "amount": "800"})
            else:
                store.assign(recipient, batch, "1")
            return True
        except DomainError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(act, sell) for sell in (True, False)]
        assert sorted(f.result() for f in futures) == [False, True]
    assert store.part(batch)["stock"] == 0
    laptop = store.laptop(donor)
    assert laptop["recovered_parts"][0]["sold"] + laptop["recovered_parts"][0]["assigned"] == 1
    assert (laptop["part_sales"], laptop["transfer_credits"]) in {(80000, 0), (0, 70000)}


def test_stale_stock_form_after_sale_is_rejected(store):
    donor, _ = donor_and_recipient(store)
    batch = recover(store, donor)
    stale = edit_part(store, batch)
    sale = store.sell_recovered_part(batch, {"quantity": "1", "amount": "0"})
    with pytest.raises(DomainError, match="changed since"):
        store.save_part(stale, batch)
    assert store.part(batch)["stock"] == 0
    stale = edit_part(store, batch)
    store.cancel_recovery_sale(donor, sale)
    with pytest.raises(DomainError, match="changed since"):
        store.save_part(stale, batch)
    assert store.part(batch)["stock"] == 1


@pytest.mark.parametrize("form", [
    {"quantity": "2", "amount": "100"},
    {"quantity": "0", "amount": "100"},
    {"quantity": "1.5", "amount": "100"},
    {"quantity": "1", "amount": "-1"},
])
def test_invalid_sales_leave_stock_and_cash_unchanged(store, form):
    donor, _ = donor_and_recipient(store)
    batch = recover(store, donor)
    with pytest.raises(DomainError):
        store.sell_recovered_part(batch, form)
    assert store.part(batch)["stock"] == 1
    assert store.laptop(donor)["recovery_sales"] == []


def test_recovery_requires_donor_status_and_existing_repairs_return_normally(store):
    donor, recipient = donor_and_recipient(store)
    with pytest.raises(DomainError, match="status"):
        recover(store, recipient)
    with pytest.raises(DomainError, match="at least one"):
        store.recover_part(donor, part_form(stock="0"))
    purchased = store.save_part(part_form())
    assignment = store.assign(donor, purchased, "1")
    store.change_assignment(donor, assignment, "0")
    assert store.part(purchased)["stock"] == 5
    assert store.laptop(donor)["recovered_parts"] == []
    with pytest.raises(DomainError, match="recovered parts only"):
        store.sell_recovered_part(purchased, {"quantity": "1", "amount": "500"})
    with pytest.raises(DomainError, match="only be entered"):
        store.assign(recipient, purchased, "1", "100")
    batch = recover(store, donor)
    store.delete_part(batch)
    with pytest.raises(DomainError, match="archived"):
        store.sell_recovered_part(batch, {"quantity": "1", "amount": "500"})
    store.restore_part(batch)
    store.assign(recipient, batch, "1", "0")
    assert store.laptop(donor)["transfer_credits"] == 0


def test_manual_status_changes_never_mutate_recovery_stock_or_sales(store):
    donor, _ = donor_and_recipient(store)
    batch = recover(store, donor)
    store.sell_recovered_part(batch, {"quantity": "1", "amount": "500"})
    for status in ("parted_out", "delivered", "unrepairable", "sold"):
        store.save_laptop(edit_laptop(store, donor, status=status), donor)
        assert store.part(batch)["stock"] == 0
        assert store.laptop(donor)["part_sales"] == 50000
    assert store.dashboard()["missing_sales"] == 1


LEGACY_SCHEMA = """
CREATE TABLE laptops (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
    purchase_price INTEGER NOT NULL, shipping_cost INTEGER NOT NULL, resale_price INTEGER,
    status TEXT NOT NULL CHECK(status IN ('purchased','shipped_usa','np_accepted','shipped_ua','delivered','fixed','listed','sold')),
    notes TEXT NOT NULL DEFAULT '', resale_description TEXT NOT NULL DEFAULT '', ebay_url TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT '2026-10-27T00:00:00Z'
);
CREATE TABLE parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, unit_price INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '', stock INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE laptop_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, laptop_id INTEGER NOT NULL REFERENCES laptops(id) ON DELETE CASCADE,
    part_id INTEGER NOT NULL REFERENCES parts(id), title TEXT NOT NULL, unit_price INTEGER NOT NULL, quantity INTEGER NOT NULL
);
CREATE TABLE attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, laptop_id INTEGER NOT NULL REFERENCES laptops(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE, size INTEGER NOT NULL
);
PRAGMA user_version = 2;
"""


def test_v2_upgrade_preserves_relationships_files_sequences_and_new_statuses(tmp_path):
    with sqlite3.connect(tmp_path / "laptop_repair.sqlite3") as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute("INSERT INTO laptops (id,title,purchase_price,shipping_cost,status,resale_description) VALUES (7,'Original',200000,0,'fixed','Multiline\nlisting')")
        conn.execute("INSERT INTO laptops (id,title,purchase_price,shipping_cost,status) VALUES (20,'Deleted',0,0,'purchased')")
        conn.execute("DELETE FROM laptops WHERE id=20")
        conn.execute("INSERT INTO parts (id,title,unit_price,stock) VALUES (9,'RAM',30000,2)")
        conn.execute("INSERT INTO laptop_parts (laptop_id,part_id,title,unit_price,quantity) VALUES (7,9,'RAM',25000,1)")
        conn.execute("INSERT INTO attachments (laptop_id,filename,storage_name,size) VALUES (7,'receipt','abc',7)")
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads/abc").write_bytes(b"receipt")
    store = Store(tmp_path)
    store.initialize()
    assert store.laptop(7)["repair_cost"] == 25000
    assert store.laptop(7)["resale_description"] == "Multiline\nlisting"
    assert store.laptop(7)["attachments"][0]["storage_name"] == "abc"
    assert (tmp_path / "uploads/abc").read_bytes() == b"receipt"
    assert store.part(9)["donor_laptop_id"] is None
    assert store.part(9)["stock"] == 2
    assert store.save_laptop(laptop_form()) > 20
    store.save_laptop(edit_laptop(store, 7, status="parted_out"), 7)
    batch = recover(store, 7)
    sale = store.sell_recovered_part(batch, {"quantity": "1", "amount": "300"})
    store.initialize()
    assert store.laptop(7)["recovery_sales"][0]["id"] == sale
    with store.db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_migration_rolls_back_original_database(tmp_path):
    with sqlite3.connect(tmp_path / "laptop_repair.sqlite3") as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.execute("INSERT INTO parts (id,title,unit_price,stock) VALUES (1,'RAM',1,1)")
        conn.execute("INSERT INTO laptop_parts (laptop_id,part_id,title,unit_price,quantity) VALUES (999,1,'Orphan',1,1)")
    with pytest.raises(RuntimeError, match="broken references"):
        Store(tmp_path).initialize()
    with sqlite3.connect(tmp_path / "laptop_repair.sqlite3") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "donor_laptop_id" not in {row[1] for row in conn.execute("PRAGMA table_info(parts)")}
        assert conn.execute("SELECT COUNT(*) FROM laptop_parts").fetchone()[0] == 1
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_sales'").fetchone() is None
