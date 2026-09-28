from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.cache import clear_product_caches
from app.main import app
from app.models.notification import AdminNotification
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.services.dashboard_service import WAT, get_dashboard
from app.utils.dependencies import get_current_active_superuser


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
        id="admin", email="ada@test.com", hashed_password="x", is_superuser=True
    )
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


async def _seed(session_factory):
    async with session_factory() as db:
        db.add_all([
            Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="per-kg", stock_quantity=20,
                    cost_price=6000, weight_options=[
                        {"label": "1kg", "price": 8500, "stock_units": 1},
                        {"label": "2kg", "price": 16000, "stock_units": 2},
                    ], parts=["Hind leg", "Front leg"]),
            Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=6),
            Product(id="old", name="Old", slug="old", price=100, category="x", stock_quantity=5, is_active=False),
        ])
        await db.commit()


async def _stock(session_factory, pid):
    async with session_factory() as db:
        return (await db.execute(select(Product.stock_quantity).where(Product.id == pid))).scalar_one()


@pytest.mark.asyncio
async def test_ring_up_sale(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)
    res = await client.post("/admin/sales", json={
        "payment_method": "cash",
        "customer_name": "Mama Nkechi",
        "items": [
            {"product_id": "leg", "quantity": 2, "weight_option": "2kg", "part": "Hind leg"},
            # Weighed off the scale: 1.7kg at the best per-kg rate (₦8,000 from the 2kg size).
            {"product_id": "leg", "amount": 1.7, "part": "Front leg"},
            {"product_id": "head", "quantity": 2},
        ],
        "discount_amount": 600, "discount_note": "Regular customer",
    })
    assert res.status_code == 201, res.text
    sale = res.json()
    assert sale["channel"] == "walk_in"
    assert sale["status"] == "delivered"
    assert sale["paid_at"] is not None
    assert sale["served_by_name"] == "Ada Admin"
    assert sale["customer_name"] == "Mama Nkechi"
    lines = [(i["selected_option"], i["quantity"], i["price_at_time"]) for i in sale["items"]]
    assert lines == [
        ("2kg · Hind leg", 2, 16000),
        ("1.7kg (weighed) · Front leg", 1, 13600),
        (None, 2, 4500),
    ]
    assert sale["subtotal"] == 32000 + 13600 + 9000
    assert sale["total_amount"] == 54600 - 600
    assert await _stock(session_factory, "leg") == pytest.approx(20 - 4 - 1.7)
    assert await _stock(session_factory, "head") == 4

    # Crossing the default threshold (5) raised the usual alert.
    async with session_factory() as db:
        alerts = (await db.execute(select(AdminNotification.title))).scalars().all()
    assert alerts == ["Goat Head is running low"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, message", [
    ({"items": [{"product_id": "head", "quantity": 7}]}, "enough stock"),
    ({"items": [{"product_id": "old", "quantity": 1}]}, "no longer available"),
    ({"items": [{"product_id": "leg", "weight_option": "5kg", "part": "Hind leg"}]}, "isn't available"),
    ({"items": [{"product_id": "head", "quantity": 1}], "discount_amount": 5000, "discount_note": "x"}, "more than"),
    ({"items": [{"product_id": "head", "quantity": 1}], "discount_amount": 500}, "why the discount"),
])
async def test_rejected_sales_change_nothing(client: AsyncClient, session_factory, as_admin, payload, message):
    await _seed(session_factory)
    res = await client.post("/admin/sales", json={"payment_method": "pos", **payload})
    assert res.status_code == 400
    assert message in res.json()["detail"]
    assert await _stock(session_factory, "head") == 6
    async with session_factory() as db:
        assert (await db.execute(select(StockMovement))).first() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("item", [
    {"product_id": "leg", "amount": 1.5, "weight_option": "1kg"},
    {"product_id": "leg", "amount": 1.5, "quantity": 2},
    {"product_id": "leg", "amount": -1},
])
async def test_invalid_weighed_lines(client: AsyncClient, session_factory, as_admin, item):
    await _seed(session_factory)
    res = await client.post("/admin/sales", json={"payment_method": "cash", "items": [item]})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_void_restores_stock_once(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)
    sale = (await client.post("/admin/sales", json={
        "payment_method": "transfer", "items": [{"product_id": "head", "quantity": 3}],
    })).json()
    assert await _stock(session_factory, "head") == 3

    res = await client.post(f"/admin/sales/{sale['id']}/void", json={"reason": "Rang up twice"})
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"
    assert res.json()["cancellation_reason"] == "Rang up twice"
    assert await _stock(session_factory, "head") == 6

    again = await client.post(f"/admin/sales/{sale['id']}/void", json={"reason": "Again"})
    assert again.status_code == 400
    assert await _stock(session_factory, "head") == 6


@pytest.mark.asyncio
async def test_day_summary_and_orders_page_separation(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)
    for method, qty in [("cash", 1), ("cash", 2), ("pos", 1)]:
        await client.post("/admin/sales", json={"payment_method": method, "items": [{"product_id": "head", "quantity": qty}]})
    voided = (await client.post("/admin/sales", json={
        "payment_method": "transfer", "items": [{"product_id": "head", "quantity": 1}],
    })).json()
    await client.post(f"/admin/sales/{voided['id']}/void", json={"reason": "Mistake"})

    day = (await client.get("/admin/sales")).json()
    assert day["summary"] == {
        "count": 3, "total": 18000,
        "by_payment_method": {"cash": 13500, "transfer": 0, "pos": 4500},
        "voided_count": 1, "voided_total": 4500,
    }
    assert len(day["sales"]) == 4

    # Walk-ins stay off the Orders page and its counts.
    assert (await client.get("/admin/orders/")).json() == []
    assert (await client.get("/admin/orders/summary")).json()["counts"]["all"] == 0
    # But a sale is readable on its own (for the receipt).
    assert (await client.get(f"/admin/sales/{voided['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_dashboard_counts_walk_in_revenue_net_of_discount(client: AsyncClient, session_factory, as_admin):
    await _seed(session_factory)
    await client.post("/admin/sales", json={
        "payment_method": "cash", "items": [{"product_id": "leg", "quantity": 1, "weight_option": "2kg", "part": "Hind leg"}],
        "discount_amount": 1000, "discount_note": "Bulk",
    })
    async with session_factory() as db:
        data = await get_dashboard(db, "today", now=datetime.now(timezone.utc).astimezone(WAT))
    kpis = data["kpis"]
    assert kpis["revenue"] == 15000
    assert kpis["walk_in_revenue"] == 15000
    # 16,000 - 12,000 cost - 1,000 discount.
    assert kpis["gross_profit"] == 3000
    assert kpis["profit_coverage"] == 1
    assert data["status_breakdown"] == []
    assert data["recent_orders"] == []
