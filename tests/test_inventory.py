from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.db import STATUSES
from app.services import DomainError, Store, money, money_display, money_input
from conftest import edit_laptop, edit_part, laptop_form, part_form


def test_exact_profit_and_historical_prices(store):
    laptop = store.save_laptop(laptop_form(resale_price="8000.00"))
    ram = store.save_part(part_form())
    ssd = store.save_part(part_form(title="SSD", unit_price="650.00", stock="1"))
    assignment = store.assign(laptop, ram, "2")
    store.assign(laptop, ssd, "1")
    assert store.laptop(laptop)["repair_cost"] == 125000
    assert store.laptop(laptop)["total_cost"] == 605000
    assert store.laptop(laptop)["profit"] == 195000
    assert store.part(ram)["stock"] == 3

    store.save_part(edit_part(store, ram, title="New RAM name", unit_price="450.00"), ram)
    assert store.laptop(laptop)["profit"] == 195000
    assert store.laptop(laptop)["assignments"][0]["title"] == "RAM 8GB"
    store.change_assignment(laptop, assignment, "3")
    assert store.laptop(laptop)["repair_cost"] == 155000
    store.assign(laptop, ram, "1")
    assert store.laptop(laptop)["repair_cost"] == 200000
    assert store.laptop(laptop)["assignments"][-1]["unit_price"] == 45000


def test_returns_and_failed_changes_are_atomic(store):
    laptop = store.save_laptop(laptop_form())
    part = store.save_part(part_form(stock="3"))
    assignment = store.assign(laptop, part, "2")
    with pytest.raises(DomainError, match="Not enough stock"):
        store.change_assignment(laptop, assignment, "4")
    with pytest.raises(DomainError, match="Not enough stock"):
        store.assign(laptop, part, "2")
    assert store.part(part)["stock"] == 1
    assert store.laptop(laptop)["assignments"][0]["quantity"] == 2
    store.change_assignment(laptop, assignment, "1")
    assert store.part(part)["stock"] == 2
    store.change_assignment(laptop, assignment, "0")
    assert store.part(part)["stock"] == 3
    assert store.laptop(laptop)["assignments"] == []


def test_concurrent_assignments_cannot_oversell(store):
    laptop = store.save_laptop(laptop_form())
    part = store.save_part(part_form(stock="1"))
    barrier = Barrier(2)

    def assign():
        barrier.wait(timeout=5)
        try:
            store.assign(laptop, part, "1")
            return True
        except DomainError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(assign) for _ in range(2)]
        assert sorted(future.result() for future in futures) == [False, True]
    assert store.part(part)["stock"] == 0
    assert len(store.laptop(laptop)["assignments"]) == 1


def test_stale_inventory_form_cannot_overwrite_stock(store):
    laptop = store.save_laptop(laptop_form())
    part = store.save_part(part_form())
    stale_form = edit_part(store, part, title="Changed title")
    store.assign(laptop, part, "2")
    with pytest.raises(DomainError, match="changed since") as error:
        store.save_part(stale_form, part)
    assert error.value.status_code == 409
    assert store.part(part)["stock"] == 3
    assert store.part(part)["title"] == "RAM 8GB"


def test_archive_restore_and_laptop_deletion(store):
    laptop = store.save_laptop(laptop_form())
    part = store.save_part(part_form(stock="4"))
    assignment = store.assign(laptop, part, "2")
    store.assign(laptop, part, "1")
    assert "archived" in store.delete_part(part)
    assert store.parts() == []
    assert store.parts(archived=True)[0]["stock"] == 1
    with pytest.raises(DomainError, match="archived"):
        store.assign(laptop, part, "1")
    with pytest.raises(DomainError, match="archived"):
        store.change_assignment(laptop, assignment, "3")
    store.change_assignment(laptop, assignment, "1")
    assert store.part(part)["stock"] == 2
    store.delete_laptop(laptop)
    assert store.part(part)["stock"] == 4
    assert store.part(part)["archived"] == 1
    store.restore_part(part)
    assert store.parts()[0]["archived"] == 0
    assert "deleted" in store.delete_part(part)
    with pytest.raises(DomainError):
        store.part(part)


@pytest.mark.parametrize("status", list(reversed(STATUSES)))
def test_all_statuses_allow_manual_out_of_order_changes(store, status):
    laptop = store.save_laptop(laptop_form(status="sold"))
    part = store.save_part(part_form())
    store.assign(laptop, part, "1")
    store.save_laptop(edit_laptop(store, laptop, status=status), laptop)
    assert store.laptop(laptop)["status"] == status
    assert store.part(part)["stock"] == 4


def test_zero_blank_and_dashboard_realized_profit(store):
    blank = store.save_laptop(laptop_form(status="sold"))
    zero = store.save_laptop(laptop_form(status="sold", resale_price="0"))
    sold = store.save_laptop(laptop_form(status="sold", resale_price="6000.25"))
    store.save_laptop(laptop_form(status="listed", resale_price="9999"))
    store.save_part(part_form(unit_price="0.29", stock="3"))
    assert store.laptop(blank)["profit"] is None
    assert store.laptop(zero)["profit"] == -480000
    assert store.laptop(sold)["profit"] == 120025
    summary = store.dashboard()
    assert summary["profit"] == -359975
    assert summary["revenue"] == 600025
    assert summary["missing_sales"] == 1
    assert summary["investment"] == 480000
    assert summary["total_cost"] == 1920000
    assert summary["stock_value"] == 87


@pytest.mark.parametrize("value", ["-1", "1.001", "NaN", "Infinity", "1e3", "", "1,000", "1000000000", "9" * 100])
def test_invalid_money_is_rejected(value):
    with pytest.raises(DomainError):
        money(value)


def test_money_format_and_precision():
    assert money("0.29") * 3 == 87
    assert money("1.1") == 110
    assert money_input(123456789) == "1234567.89"
    assert money_display(123456789) == "1,234,568 UAH"
    assert money_input(None) == ""
    assert money_display(None) == "—"
    assert money_display(-1) == "0 UAH"
    assert money_display(60000) == "600 UAH"
    assert money_display(60049) == "600 UAH"
    assert money_display(60050) == "601 UAH"
    assert money_display(-60050) == "−601 UAH"


def test_invalid_inputs_do_not_create_records(store):
    for overrides in ({"title": " "}, {"status": "repairing"}, {"ebay_url": "javascript:alert(1)"}):
        with pytest.raises(DomainError):
            store.save_laptop(laptop_form(**overrides))
    for stock in ("-1", "1.5", "1000001"):
        with pytest.raises(DomainError):
            store.save_part(part_form(stock=stock))
    assert store.laptops() == []
    assert store.parts() == []


def test_cross_laptop_assignment_rejected_and_persistence(store):
    first = store.save_laptop(laptop_form())
    second = store.save_laptop(laptop_form(title="Other laptop"))
    part = store.save_part(part_form())
    assignment = store.assign(first, part, "2")
    with pytest.raises(DomainError) as error:
        store.change_assignment(second, assignment, "0")
    assert error.value.status_code == 404
    restarted = Store(store.db.data_dir)
    restarted.initialize()
    assert restarted.part(part)["stock"] == 3
    assert restarted.laptop(first)["repair_cost"] == 60000


def test_search_filters_and_archived_stock_value(store):
    first = store.save_laptop(laptop_form(title="Dell Latitude", status="fixed"))
    store.save_laptop(laptop_form())
    part = store.save_part(part_form(comment="Compatible with Dell"))
    store.assign(first, part, "1")
    store.delete_part(part)
    assert [row["id"] for row in store.laptops("dell", "fixed")] == [first]
    assert store.laptops("' OR 1=1 --") == []
    assert store.parts("dell", archived=True)[0]["id"] == part
    assert store.dashboard()["stock_value"] == 120000
