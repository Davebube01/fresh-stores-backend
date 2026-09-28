from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.cache import clear_product_caches
from app.main import app
from app.models.order import DeliveryMethod, Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.services.dashboard_service import WAT, get_dashboard
from app.services.inventory_service import get_inventory
from app.utils.dependencies import get_current_active_superuser

NOW = datetime(2026, 9, 24, 14, 30, tzinfo=WAT)
GUEST = {"fullName": "Guest", "email": "guest@test.com", "phone": "08012345678"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_product_caches()
    yield
    clear_product_caches()


@pytest.fixture
def as_admin():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id="admin", email="admin@test.com", hashed_password="x", is_superuser=True
    )
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest.mark.asyncio
async def test_cost_price_is_admin_only(client: AsyncClient, session_factory, as_admin):
    res = await client.post("/admin/products", json={
        "name": "Goat Leg", "slug": "goat-leg", "price": 8500, "category": "per-kg",
        "stock_quantity": 20, "cost_price": 6000,
        "weight_options": [{"label": "1kg", "price": 8500, "stock_units": 1}],
    })
    assert res.status_code == 200, res.text
    product_id = res.json()["id"]
    assert res.json()["cost_price"] == 6000

    res = await client.put(f"/admin/products/{product_id}", json={"cost_price": 6200})
    assert res.json()["cost_price"] == 6200
    assert (await client.get(f"/admin/products/{product_id}")).json()["cost_price"] == 6200

    # Customers never see it: not on the product, nor inside their order.
    public = (await client.get(f"/api/v1/products/{product_id}")).json()
    assert "cost_price" not in public
    order = (await client.post("/api/v1/orders/checkout", json={
        "is_guest": True, "guest_info": GUEST, "payment_method": "cod", "delivery_method": "pickup",
        "items": [{"product_id": product_id, "quantity": 1, "weight_option": "1kg"}],
    })).json()
    assert "cost_price" not in order["items"][0]["product"]
    assert "cost_at_time" not in order["items"][0]


@pytest.mark.asyncio
async def test_negative_cost_rejected(client: AsyncClient, as_admin):
    res = await client.post("/admin/products", json={
        "name": "X", "slug": "x", "price": 100, "category": "per-kg", "cost_price": -1,
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_checkout_snapshots_cost_per_size(client: AsyncClient, session_factory):
    async with session_factory() as db:
        db.add(Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="per-kg",
                       stock_quantity=20, cost_price=6000, weight_options=[
                           {"label": "1kg", "price": 8500, "stock_units": 1},
                           {"label": "2kg", "price": 16000, "stock_units": 2},
                       ]))
        await db.commit()

    res = await client.post("/api/v1/orders/checkout", json={
        "is_guest": True, "guest_info": GUEST, "payment_method": "cod", "delivery_method": "pickup",
        "items": [{"product_id": "leg", "quantity": 2, "weight_option": "2kg"}],
    })
    assert res.status_code == 200, res.text

    async with session_factory() as db:
        item = (await db.execute(select(OrderItem))).scalar_one()
    assert item.cost_at_time == 12000  # 2kg × ₦6,000/kg


def _paid_order(product, qty, price, paid_at, cost_at_time=None, stock_units=1.0):
    return Order(
        status=OrderStatus.PROCESSING, payment_method="paystack", delivery_method=DeliveryMethod.PICKUP,
        guest_info={"fullName": "Guest"}, subtotal=qty * price, total_amount=qty * price, delivery_fee=0,
        paid_at=paid_at.astimezone(timezone.utc), created_at=paid_at.astimezone(timezone.utc),
        updated_at=paid_at.astimezone(timezone.utc),
        items=[OrderItem(product_id=product.id, quantity=qty, price_at_time=price,
                         cost_at_time=cost_at_time, stock_units=stock_units)],
    )


@pytest.mark.asyncio
async def test_dashboard_profit(session_factory):
    async with session_factory() as db:
        leg = Product(name="Goat Leg", slug="goat-leg", price=8500, category="per-kg", stock_quantity=10, cost_price=6000)
        whole = Product(name="Whole Goat", slug="whole", price=85000, category="goat-meat", stock_quantity=2, cost_price=70000)
        veg = Product(name="Tomatoes", slug="tomatoes", price=1500, category="vegetables", stock_quantity=5)
        db.add_all([leg, whole, veg])
        await db.flush()
        db.add_all([
            # Snapshotted cost (cost has since risen to 6,000; the snapshot wins).
            _paid_order(leg, 2, 8500, NOW.replace(hour=9), cost_at_time=5000),
            # Older order with no snapshot: falls back to the current cost.
            _paid_order(whole, 1, 85000, NOW.replace(hour=10)),
            # No cost known anywhere: left out of profit.
            _paid_order(veg, 2, 1500, NOW.replace(hour=11)),
            # Yesterday.
            _paid_order(leg, 1, 8500, NOW - timedelta(days=1, hours=2), cost_at_time=6000),
        ])
        await db.commit()

        data = await get_dashboard(db, "today", now=NOW)

    kpis = data["kpis"]
    assert kpis["revenue"] == 17000 + 85000 + 3000
    assert kpis["gross_profit"] == (17000 - 10000) + (85000 - 70000)
    assert kpis["gross_profit_prev"] == 2500
    assert kpis["profit_margin"] == pytest.approx(22000 / 102000)
    assert kpis["profit_coverage"] == pytest.approx(102000 / 105000)

    top = {p["name"]: p for p in data["top_products"]}
    assert top["Goat Leg"]["profit"] == 7000
    assert top["Whole Goat"]["profit"] == 15000
    assert top["Tomatoes"]["profit"] is None


@pytest.mark.asyncio
async def test_dashboard_profit_null_without_costs(session_factory):
    async with session_factory() as db:
        veg = Product(name="Tomatoes", slug="tomatoes", price=1500, category="vegetables", stock_quantity=5)
        db.add(veg)
        await db.flush()
        db.add(_paid_order(veg, 1, 1500, NOW.replace(hour=9)))
        await db.commit()
        kpis = (await get_dashboard(db, "today", now=NOW))["kpis"]
    assert kpis["gross_profit"] is None
    assert kpis["profit_margin"] is None
    assert kpis["profit_coverage"] == 0


@pytest.mark.asyncio
async def test_inventory_stock_value_at_cost(session_factory):
    async with session_factory() as db:
        db.add_all([
            Product(name="Goat Leg", slug="goat-leg", price=8500, category="per-kg", stock_quantity=10, cost_price=6000),
            Product(name="Tomatoes", slug="tomatoes", price=1500, category="vegetables", stock_quantity=4),
        ])
        await db.commit()
        summary = (await get_inventory(db, now=NOW))["summary"]
    assert summary["stock_cost_value"] == 60000
    assert summary["products_without_cost"] == 1
    assert summary["stock_value"] == 85000 + 6000
