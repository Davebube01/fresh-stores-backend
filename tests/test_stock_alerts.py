from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.cache import clear_product_caches
from app.main import app
from app.models.notification import AdminNotification
from app.models.product import Product
from app.models.user import User
from app.services.dashboard_service import WAT, get_dashboard
from app.services.inventory_service import get_inventory
from app.utils.dependencies import get_current_active_superuser

GUEST = {"fullName": "Guest", "email": "guest@test.com", "phone": "08012345678"}
NOW = datetime(2026, 9, 24, 14, 30, tzinfo=WAT)


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


async def _seed(session_factory, *products):
    async with session_factory() as db:
        db.add_all(products)
        await db.commit()


async def _buy(client, product_id, quantity):
    return await client.post("/api/v1/orders/checkout", json={
        "is_guest": True, "guest_info": GUEST, "payment_method": "cod", "delivery_method": "pickup",
        "items": [{"product_id": product_id, "quantity": quantity}],
    })


async def _alerts(session_factory):
    async with session_factory() as db:
        rows = (await db.execute(select(AdminNotification).order_by(AdminNotification.created_at))).scalars().all()
    return [(n.kind, n.title, n.body, n.read_at is not None) for n in rows]


@pytest.mark.asyncio
async def test_alert_once_when_crossing_store_default(client: AsyncClient, session_factory):
    # Store default threshold is 5.
    await _seed(session_factory, Product(id="head", name="Goat Head", slug="goat-head", price=4500,
                                         category="goat-parts", stock_quantity=6))
    assert (await _buy(client, "head", 2)).status_code == 200  # 6 -> 4: crosses
    assert (await _buy(client, "head", 1)).status_code == 200  # 4 -> 3: already low
    assert await _alerts(session_factory) == [
        ("low_stock", "Goat Head is running low", "4 left (alert at 5).", False),
    ]


@pytest.mark.asyncio
async def test_product_threshold_overrides_default(client: AsyncClient, session_factory):
    await _seed(session_factory, Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="per-kg",
                                         stock_quantity=12, low_stock_threshold=10))
    assert (await _buy(client, "leg", 3)).status_code == 200
    assert await _alerts(session_factory) == [
        ("low_stock", "Goat Leg is running low", "9 left (alert at 10).", False),
    ]


@pytest.mark.asyncio
async def test_out_of_stock_alert(client: AsyncClient, session_factory):
    await _seed(session_factory, Product(id="head", name="Goat Head", slug="goat-head", price=4500,
                                         category="goat-parts", stock_quantity=3))
    assert (await _buy(client, "head", 3)).status_code == 200  # already low; now out
    assert await _alerts(session_factory) == [
        ("out_of_stock", "Goat Head is out of stock", "Customers can't order it until it's restocked.", False),
    ]


@pytest.mark.asyncio
async def test_failed_checkout_leaves_no_alert(client: AsyncClient, session_factory):
    await _seed(
        session_factory,
        Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=6),
        Product(id="ribs", name="Goat Ribs", slug="goat-ribs", price=6000, category="goat-parts", stock_quantity=1),
    )
    res = await client.post("/api/v1/orders/checkout", json={
        "is_guest": True, "guest_info": GUEST, "payment_method": "cod", "delivery_method": "pickup",
        "items": [{"product_id": "head", "quantity": 3}, {"product_id": "ribs", "quantity": 5}],
    })
    assert res.status_code == 400
    assert await _alerts(session_factory) == []


@pytest.mark.asyncio
async def test_restock_resolves_alerts_and_inactive_products_stay_quiet(client: AsyncClient, session_factory, as_admin):
    await _seed(
        session_factory,
        Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=2),
        Product(id="old", name="Old Pack", slug="old-pack", price=1000, category="bundles", stock_quantity=8,
                is_active=False),
    )
    await client.post("/admin/products/head/stock", json={"change": -2, "reason": "correction"})
    await client.post("/admin/products/old/stock", json={"change": -8, "reason": "correction"})
    assert [a[0] for a in await _alerts(session_factory)] == ["out_of_stock"]

    # Back to 3: still low, so only the out-of-stock alert closes.
    await client.post("/admin/products/head/stock", json={"change": 3, "reason": "restock"})
    assert [a[3] for a in await _alerts(session_factory)] == [True]


@pytest.mark.asyncio
async def test_notification_endpoints(client: AsyncClient, session_factory, as_admin):
    await _seed(
        session_factory,
        Product(id="a", name="A", slug="a", price=100, category="x", stock_quantity=6),
        Product(id="b", name="B", slug="b", price=100, category="x", stock_quantity=6),
    )
    await _buy(client, "a", 2)
    await _buy(client, "b", 6)

    body = (await client.get("/admin/notifications")).json()
    assert body["unread_count"] == 2
    assert [n["title"] for n in body["items"]] == ["B is out of stock", "A is running low"]
    assert body["items"][0]["link"] == "/admin/products/b"

    first = body["items"][0]["id"]
    assert (await client.post(f"/admin/notifications/{first}/read")).status_code == 200
    assert (await client.post(f"/admin/notifications/{first}/read")).status_code == 404
    body = (await client.get("/admin/notifications")).json()
    assert body["unread_count"] == 1
    assert body["items"][0]["title"] == "A is running low"  # unread first

    assert (await client.post("/admin/notifications/read-all")).json() == {"marked": 1}
    assert (await client.get("/admin/notifications")).json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_thresholds_in_admin_views(client: AsyncClient, session_factory, as_admin):
    await _seed(
        session_factory,
        Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="per-kg",
                stock_quantity=8, low_stock_threshold=10),
        Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=8),
    )
    leg = (await client.get("/admin/products/leg")).json()
    head = (await client.get("/admin/products/head")).json()
    assert (leg["low_stock_threshold"], leg["effective_low_stock_threshold"]) == (10, 10)
    assert (head["low_stock_threshold"], head["effective_low_stock_threshold"]) == (None, 5)

    res = await client.put("/admin/products/head", json={"low_stock_threshold": 2})
    assert res.json()["effective_low_stock_threshold"] == 2

    async with session_factory() as db:
        inventory = await get_inventory(db, now=NOW)
        dashboard = await get_dashboard(db, "today", now=NOW)
    # Leg (8 <= 10) is low; Head (8 > 2) isn't.
    assert inventory["summary"]["low_stock"] == 1
    assert [(r["name"], r["low_stock_threshold"]) for r in inventory["needs_restock"]] == [("Goat Leg", 10)]
    assert [(p["name"], p["low_stock_threshold"]) for p in dashboard["low_stock"]] == [("Goat Leg", 10)]
