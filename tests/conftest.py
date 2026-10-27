import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import Store, money_input


def laptop_form(**overrides):
    return {
        "title": "ThinkPad T480", "purchase_price": "4000.00",
        "shipping_cost": "800.00", "resale_price": "", "status": "purchased",
        "notes": "No power", "ebay_url": "https://www.ebay.com/itm/123",
        **overrides,
    }


def part_form(**overrides):
    return {"title": "RAM 8GB", "unit_price": "300.00", "stock": "5", "comment": "DDR4", **overrides}


def edit_laptop(store, laptop_id, **overrides):
    laptop = store.laptop(laptop_id)
    form = {**laptop, "version": str(laptop["version"])}
    for key in ("purchase_price", "shipping_cost", "resale_price"):
        form[key] = money_input(laptop[key])
    return {**form, **overrides}


def edit_part(store, part_id, **overrides):
    part = store.part(part_id)
    return {
        **part, "unit_price": money_input(part["unit_price"]),
        "stock": str(part["stock"]), "version": str(part["version"]), **overrides,
    }


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    return store


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client
