from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.crud.customer import get_customers_summary
from app.main import app
from app.models.delivery import Delivery
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def admin():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="admin", email="a@x.com", is_superuser=True)
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


async def _seed(session_factory):
    async with session_factory() as db:
        amaka = User(id="amaka", email="amaka@example.com", hashed_password="x", full_name="Amaka Obi",
                     phone="08031112222", email_verified=True, created_at=NOW - timedelta(days=3))
        tunde = User(id="tunde", email="tunde@example.com", hashed_password="x", full_name="Tunde Bello",
                     created_at=NOW - timedelta(days=90))
        quiet = User(id="quiet", email="quiet@example.com", hashed_password="x", created_at=NOW - timedelta(days=40))
        boss = User(id="boss", email="boss@example.com", hashed_password="x", is_superuser=True)
        leg = Product(id="leg", name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts")
        db.add_all([amaka, tunde, quiet, boss, leg])

        def order(uid, status, total, paid=True, method="paystack", days_ago=1, guest=None, zone=None):
            o = Order(user_id=uid, status=status, total_amount=total, subtotal=total, payment_method=method,
                      paid_at=(NOW - timedelta(days=days_ago)) if paid else None,
                      created_at=NOW - timedelta(days=days_ago), guest_info=guest)
            o.items.append(OrderItem(product_id="leg", quantity=2, price_at_time=9000))
            if zone:
                o.delivery = Delivery(address="Plot 7, Wuse 2", city="Abuja", state="FCT", delivery_zone=zone)
            db.add(o)

        order("amaka", OrderStatus.DELIVERED, 36000, zone="wuse")
        order("amaka", OrderStatus.PROCESSING, 18000, days_ago=2, zone="wuse")
        order("amaka", OrderStatus.CANCELLED, 50000, days_ago=2)               # never counts
        order("amaka", OrderStatus.PENDING, 9000, paid=False, days_ago=1)      # placed, not paid
        order("tunde", OrderStatus.DELIVERED, 12000, paid=False, method="cod", days_ago=60)  # cash, delivered
        order(None, OrderStatus.PAID, 5000, guest={"fullName": "G", "email": "Guest@Mail.com"})
        order(None, OrderStatus.PAID, 5000, guest={"fullName": "G", "email": "guest@mail.com"})
        db.add(RefreshToken(user_id="tunde", token_hash="h", family_id="f", realm="customer",
                            expires_at=NOW + timedelta(days=5)))
        await db.commit()


@pytest.mark.asyncio
async def test_list_counts_only_money_taken(client: AsyncClient, admin, session_factory):
    await _seed(session_factory)
    rows = {c["id"]: c for c in (await client.get("/admin/customers")).json()}
    assert "boss" not in rows
    a = rows["amaka"]
    assert a["ordersCount"] == 3          # cancelled excluded, unpaid pending included
    assert a["paid_orders"] == 2
    assert a["totalSpent"] == 54000       # no cancelled, no unpaid
    assert a["email_verified"] is True
    assert rows["tunde"]["totalSpent"] == 12000  # COD counts once delivered
    assert rows["quiet"]["ordersCount"] == 0 and rows["quiet"]["last_order_at"] is None


@pytest.mark.asyncio
async def test_search_sort_and_status_filter(client: AsyncClient, admin, session_factory):
    await _seed(session_factory)
    by_phone = (await client.get("/admin/customers", params={"search": "0803111"})).json()
    assert [c["id"] for c in by_phone] == ["amaka"]
    by_spent = (await client.get("/admin/customers", params={"sort": "spent"})).json()
    assert [c["id"] for c in by_spent] == ["amaka", "tunde", "quiet"]
    by_last = (await client.get("/admin/customers", params={"sort": "last_order"})).json()
    assert by_last[-1]["id"] == "quiet"
    assert (await client.get("/admin/customers", params={"sort": "nope"})).status_code == 422


@pytest.mark.asyncio
async def test_summary(session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        s = await get_customers_summary(db, now=NOW)
    assert s == {
        "total_customers": 3,
        "new_this_month": 1,          # Amaka joined 25 Sep
        "active_last_30_days": 1,     # Tunde's order was 60 days ago
        "repeat_customers": 1,        # Amaka: 2 paid orders
        "verified": 1,
        "guest_customers": 1,         # same email, different case
    }


@pytest.mark.asyncio
async def test_detail_and_deactivate(client: AsyncClient, admin, session_factory):
    await _seed(session_factory)
    d = (await client.get("/admin/customers/amaka")).json()
    assert d["cancelled_orders"] == 1
    assert d["avg_order_value"] == 27000
    assert d["favourites"][0]["name"] == "Goat Leg" and d["favourites"][0]["units"] == 4
    assert d["addresses"] == [{"address": "Plot 7, Wuse 2", "zone": "Wuse / Wuse 2", "times_used": 2, "last_used": d["addresses"][0]["last_used"]}]
    assert len(d["recent_orders"]) == 4

    off = await client.patch("/admin/customers/tunde/status", json={"is_active": False})
    assert off.status_code == 200 and off.json()["status"] == "inactive"
    async with session_factory() as db:
        tok = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == "tunde"))).scalar_one()
        assert tok.revoked_at is not None
    assert (await client.patch("/admin/customers/boss/status", json={"is_active": False})).status_code == 404
    assert (await client.get("/admin/customers/nope")).status_code == 404


@pytest.mark.asyncio
async def test_requires_admin(client: AsyncClient):
    assert (await client.get("/admin/customers/summary")).status_code == 401
    assert (await client.patch("/admin/customers/x/status", json={"is_active": False})).status_code == 401
