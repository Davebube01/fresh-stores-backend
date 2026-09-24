from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.main import app
from app.models.delivery import Delivery
from app.models.order import DeliveryMethod, Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.services.dashboard_service import WAT, get_dashboard
from app.utils.dependencies import get_current_active_superuser

# Thu 24 Sep 2026, 14:30 in Abuja.
NOW = datetime(2026, 9, 24, 14, 30, tzinfo=WAT)


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


async def _seed(session_factory):
    async with session_factory() as db:
        amaka = User(email="amaka@example.com", hashed_password="x", full_name="Amaka Obi")
        leg = Product(name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts", stock_quantity=3)
        ribs = Product(name="Goat Ribs", slug="goat-ribs", price=15500, category="goat-parts", stock_quantity=0)
        whole = Product(name="Whole Goat", slug="whole-goat", price=85000, category="goat-meat", stock_quantity=40)
        hidden = Product(name="Old Pack", slug="old-pack", price=1000, category="bundles", stock_quantity=0, is_active=False)
        db.add_all([amaka, leg, ribs, whole, hidden])
        await db.flush()

        def order(status, paid_at=None, created_at=None, user=None, guest=None, items=(), total=0.0, slot=None, day=None,
                  method="paystack", updated_at=None):
            o = Order(
                status=status,
                payment_method=method,
                updated_at=_utc(updated_at or created_at or paid_at or NOW),
                user_id=user.id if user else None,
                guest_info=guest,
                delivery_method=DeliveryMethod.DELIVERY,
                subtotal=total,
                total_amount=total,
                delivery_fee=2500,
                paid_at=_utc(paid_at) if paid_at else None,
                created_at=_utc(created_at or paid_at or NOW),
            )
            for product, qty in items:
                o.items.append(OrderItem(product_id=product.id, quantity=qty, price_at_time=product.price))
            if slot:
                # Stored the way checkout stores it: the browser's toISOString().
                o.delivery = Delivery(
                    address="Plot 7", city="Abuja", state="FCT", delivery_zone="wuse",
                    delivery_date=_utc(day).isoformat().replace("+00:00", "Z"), time_slot=slot,
                )
            db.add(o)
            return o

        today_0030 = NOW.replace(hour=0, minute=30)  # 23:30 UTC the day before
        # Today: two paid orders.
        order(OrderStatus.PROCESSING, paid_at=NOW.replace(hour=9), user=amaka,
              items=[(leg, 2)], total=36000, slot="10:00 - 11:00", day=today_0030)
        order(OrderStatus.DELIVERED, paid_at=NOW.replace(hour=11), guest={"fullName": "Tunde Bello"},
              items=[(whole, 1)], total=85000, slot="12:00 - 13:00", day=today_0030)
        order(OrderStatus.PAID, paid_at=NOW.replace(hour=13), user=amaka,
              items=[(leg, 1)], total=18000, slot="14:00 - 15:00", day=today_0030)
        # Yesterday, same window: one paid order.
        order(OrderStatus.PROCESSING, paid_at=NOW - timedelta(days=1, hours=3), user=amaka,
              items=[(ribs, 2)], total=31000)
        # Cancelled after payment: never revenue.
        order(OrderStatus.CANCELLED, paid_at=NOW.replace(hour=10), user=amaka, items=[(whole, 1)], total=85000)
        # Unpaid checkout today: counted in the status mix only.
        order(OrderStatus.PENDING, created_at=NOW.replace(hour=12), guest={"fullName": "Hauwa Musa"},
              items=[(leg, 1)], total=18000)
        # Cash on delivery: delivered today (revenue), and one accepted but not sent.
        order(OrderStatus.DELIVERED, method="cod", created_at=NOW - timedelta(days=2), updated_at=NOW.replace(hour=12),
              guest={"fullName": "Chinedu Eze"}, items=[(ribs, 1)], total=15500)
        order(OrderStatus.PENDING, method="cod", created_at=NOW - timedelta(days=5), user=amaka,
              items=[(whole, 1)], total=85000, slot="16:00 - 17:00", day=today_0030)
        # 10 days ago: inside 30d only.
        order(OrderStatus.DELIVERED, paid_at=NOW - timedelta(days=10), user=amaka, items=[(whole, 2)], total=170000)
        await db.commit()


@pytest.mark.asyncio
async def test_today_kpis_compare_against_yesterday(session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        data = await get_dashboard(db, "today", now=NOW)

    k = data["kpis"]
    # 3 online payments + 1 COD order delivered today.
    assert k["revenue"] == 36000 + 85000 + 18000 + 15500
    assert k["orders"] == 4
    assert k["avg_order_value"] == pytest.approx(154500 / 4)
    assert k["revenue_prev"] == 31000
    assert k["orders_prev"] == 1
    # PAID, two PROCESSING and the pending COD order are waiting; the 10:00 one's slot has ended.
    assert k["awaiting_dispatch"] == 4
    assert k["overdue_dispatch"] == 1


@pytest.mark.asyncio
async def test_slots_status_mix_stock_and_top_products(session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        data = await get_dashboard(db, "today", now=NOW)

    slots = {s["time_slot"]: s for s in data["todays_deliveries"]}
    assert slots["10:00 - 11:00"]["state"] == "overdue"
    assert slots["12:00 - 13:00"]["state"] == "done"
    assert slots["14:00 - 15:00"]["state"] == "now"
    assert slots["16:00 - 17:00"]["state"] == "upcoming"  # the pending COD order is a real delivery
    assert slots["10:00 - 11:00"]["orders"][0]["customer_name"] == "Amaka Obi"
    assert slots["10:00 - 11:00"]["orders"][0]["delivery_zone"] == "Wuse / Wuse 2"

    mix = {s["status"]: s["count"] for s in data["status_breakdown"]}
    # Placed today only (the COD orders were placed on earlier days).
    assert mix == {"pending": 1, "paid": 1, "processing": 1, "delivered": 1, "cancelled": 1}

    assert [p["name"] for p in data["low_stock"]] == ["Goat Ribs", "Goat Leg"]  # inactive excluded
    assert data["out_of_stock_count"] == 1
    assert data["low_stock_count"] == 1

    top = data["top_products"]
    assert top[0]["name"] == "Goat Leg" and top[0]["units"] == 3 and top[0]["revenue"] == 54000
    assert len(data["recent_orders"]) == 6


@pytest.mark.asyncio
async def test_30d_series_covers_every_day(session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        data = await get_dashboard(db, "30d", now=NOW)

    series = data["revenue_series"]
    assert len(series) == 30
    assert series[-1]["date"] == NOW.date()
    assert series[-1]["revenue"] == 139000 + 15500
    assert sum(p["revenue"] for p in series) == 154500 + 31000 + 170000
    assert data["kpis"]["orders"] == 6


@pytest.mark.asyncio
async def test_endpoint_requires_admin(client: AsyncClient):
    res = await client.get("/admin/dashboard")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_endpoint_returns_dashboard(client: AsyncClient, session_factory):
    await _seed(session_factory)
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="admin", email="a@x.com", is_superuser=True)
    try:
        res = await client.get("/admin/dashboard", params={"range": "7d"})
        bad = await client.get("/admin/dashboard", params={"range": "year"})
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)

    assert res.status_code == 200
    body = res.json()
    assert body["range"] == "7d"
    assert len(body["revenue_series"]) == 7
    assert set(body["kpis"]) >= {"revenue", "orders", "avg_order_value", "awaiting_dispatch"}
    assert bad.status_code == 422
