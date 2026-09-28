import csv
import io

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.cache import clear_product_caches
from app.main import app
from app.models.activity import ActivityLog
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

GUEST = {"fullName": "Tunde Bello", "email": "tunde@test.com", "phone": "08012345678"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_product_caches()
    yield
    clear_product_caches()


@pytest_asyncio.fixture
async def as_admin(session_factory):
    async with session_factory() as db:
        db.add(User(id="admin", email="ada@test.com", full_name="Ada Admin", hashed_password="x", is_superuser=True))
        await db.commit()
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id="admin", email="ada@test.com", full_name="Ada Admin", hashed_password="x", is_superuser=True
    )
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


async def _seed(session_factory):
    async with session_factory() as db:
        db.add(Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="per-kg", stock_quantity=20,
                       cost_price=6000, weight_options=[{"label": "1kg", "price": 8500, "stock_units": 1}]))
        await db.commit()


def _rows(res) -> list[dict]:
    text = res.content.decode("utf-8")
    assert text.startswith("﻿")  # BOM so Excel reads ₦ and names right
    return list(csv.DictReader(io.StringIO(text[1:])))


async def _log(session_factory) -> list[tuple]:
    async with session_factory() as db:
        rows = (await db.execute(select(ActivityLog).order_by(ActivityLog.created_at))).scalars().all()
    return [(a.actor_name, a.action, a.summary, a.changes) for a in rows]


@pytest.mark.asyncio
async def test_admin_actions_are_logged(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)

    await client.put("/admin/products/leg", json={"price": 9000, "cost_price": 6200})
    await client.put("/admin/products/leg", json={"price": 9000})  # no change: not logged
    await client.post("/admin/products/leg/stock", json={"change": 5, "reason": "restock", "note": "Market run"})
    sale = (await client.post("/admin/sales", json={
        "payment_method": "cash", "items": [{"product_id": "leg", "weight_option": "1kg"}],
    })).json()
    await client.post(f"/admin/sales/{sale['id']}/void", json={"reason": "Mistake"})
    ref = f"#{sale['id'][:8].upper()}"

    assert await _log(session_factory) == [
        ("Ada Admin", "product.updated", "Updated Goat Leg: price, cost price",
         {"price": {"from": 8500.0, "to": 9000.0}, "cost_price": {"from": 6000.0, "to": 6200.0}}),
        ("Ada Admin", "stock.adjusted", "Added 5 to Goat Leg stock (restock) — Market run",
         {"stock": {"from": 20.0, "to": 25.0}}),
        ("Ada Admin", "sale.created", f"Rang up sale {ref} for ₦8,500 (cash)", None),
        ("Ada Admin", "sale.voided", f"Voided sale {ref} (₦8,500): Mistake", None),
    ]

    page = (await client.get("/admin/activity", params={"entity_type": "sale"})).json()
    assert page["total"] == 2
    assert [e["action"] for e in page["items"]] == ["sale.voided", "sale.created"]  # newest first
    assert (await client.get("/admin/activity", params={"q": "market run"})).json()["total"] == 1


@pytest.mark.asyncio
async def test_orders_and_sale_lines_export(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)
    await client.post("/api/v1/orders/checkout", json={
        "is_guest": True, "guest_info": GUEST, "payment_method": "cod", "delivery_method": "pickup",
        "items": [{"product_id": "leg", "quantity": 2, "weight_option": "1kg"}],
    })
    await client.post("/admin/sales", json={
        "payment_method": "pos", "items": [{"product_id": "leg", "amount": 1.5}],
        "discount_amount": 750, "discount_note": "Friend",
    })

    res = await client.get("/admin/exports/orders.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == 'attachment; filename="orders-all-time.csv"'
    orders = _rows(res)
    assert [(o["Channel"], o["Customer"], o["Payment method"], o["Discount"], o["Total"]) for o in orders] == [
        ("Online", "Tunde Bello", "cod", "0.00", "17000.00"),
        ("Walk-in", "", "pos", "750.00", "12000.00"),
    ]

    lines = _rows(await client.get("/admin/exports/sale_lines.csv"))
    assert [(l["Size / cut"], l["Quantity"], l["Line total"], l["Line cost"], l["Line profit"]) for l in lines] == [
        ("1kg", "2", "17000.00", "12000.00", "5000.00"),
        ("1.5kg (weighed)", "1", "12750.00", "9000.00", "3750.00"),
    ]

    # Exports are themselves logged.
    assert [a[2] for a in await _log(session_factory) if a[1] == "export.downloaded"] == [
        "Exported orders as CSV", "Exported sale lines as CSV",
    ]


@pytest.mark.asyncio
async def test_date_range_and_snapshot_exports(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)
    await client.post("/admin/products/leg/stock", json={"change": -2, "reason": "correction", "note": "Spoiled"})

    res = await client.get("/admin/exports/stock_movements.csv", params={"date_from": "2020-01-01", "date_to": "2020-01-31"})
    assert res.headers["content-disposition"].endswith('filename="stock-movements-2020-01-01-to-2020-01-31.csv"')
    assert _rows(res) == []
    moves = _rows(await client.get("/admin/exports/stock_movements.csv"))
    assert [(m["Product"], m["Change"], m["Reason"], m["Note"], m["By"]) for m in moves] == [
        ("Goat Leg", "-2", "correction", "Spoiled", "Ada Admin"),
    ]

    products = _rows(await client.get("/admin/exports/products.csv"))
    assert products[0]["Stock value at cost"] == "108000.00"  # 18kg × ₦6,000
    assert products[0]["Sizes"] == "1kg ₦8500"

    assert (await client.get("/admin/exports/orders.csv", params={"date_from": "2026-02-01", "date_to": "2026-01-01"})).status_code == 400
    assert (await client.get("/admin/exports/secrets.csv")).status_code == 422


@pytest.mark.asyncio
async def test_legacy_sizes_upgrade_is_not_logged_as_a_change(client: AsyncClient, session_factory, as_admin):
    async with session_factory() as db:
        db.add(Product(id="onion", name="Onions", slug="onions", price=1000, category="vegetables",
                       stock_quantity=10, weight_options=["1kg"]))
        await db.commit()
    # The form sends sizes back in the new {label, price, stock_units} form.
    await client.put("/admin/products/onion", json={
        "weight_options": [{"label": "1kg", "price": 1000, "stock_units": 1}], "low_stock_threshold": 4,
    })
    assert [a[3] for a in await _log(session_factory)] == [{"low_stock_threshold": {"from": None, "to": 4.0}}]
