from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.main import app
from app.models.delivery import Delivery
from app.models.order import DeliveryMethod, Order, OrderItem, OrderStatus as S
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")


@pytest_asyncio.fixture
async def admin():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="admin", email="a@x.com", is_superuser=True)
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest_asyncio.fixture
async def orders(session_factory):
    async with session_factory() as db:
        db.add_all([
            User(id="amaka", email="amaka@example.com", hashed_password="x", full_name="Amaka Obi", phone="0803111"),
            Product(id="leg", name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts", stock_quantity=50),
        ])

        def make(oid, status, *, user=None, guest=None, method="paystack", pickup=False, slot_day=None, paid=True, minutes_ago=0):
            o = Order(id=oid, status=status, user_id=user, guest_info=guest, payment_method=method,
                      delivery_method=DeliveryMethod.PICKUP if pickup else DeliveryMethod.DELIVERY,
                      subtotal=18000, total_amount=18000,
                      paid_at=datetime.now(timezone.utc) if paid else None,
                      created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
            o.items.append(OrderItem(product_id="leg", quantity=1, price_at_time=18000))
            if not pickup:
                o.delivery = Delivery(address="Plot 7", city="Abuja", state="FCT", delivery_zone="wuse",
                                      delivery_date=slot_day, time_slot="10:00 - 11:00" if slot_day else None)
            db.add(o)

        make("paid0001", S.PAID, user="amaka", slot_day=YESTERDAY, minutes_ago=1)      # overdue
        make("proc0002", S.PROCESSING, guest={"fullName": "Tunde Bello", "email": "t@x.com", "phone": "0809"}, minutes_ago=2)
        make("codp0003", S.PENDING, user="amaka", method="cod", paid=False, minutes_ago=3)
        make("unpd0004", S.AWAITING_VERIFICATION, user="amaka", paid=False, minutes_ago=4)
        make("pick0005", S.PROCESSING, user="amaka", pickup=True, minutes_ago=5)
        make("canc0006", S.CANCELLED, user="amaka", minutes_ago=6)
        await db.commit()


@pytest.mark.asyncio
async def test_views_search_and_rows(client: AsyncClient, admin, orders):
    ids = lambda r: [o["id"] for o in r.json()]
    assert ids(await client.get("/admin/orders/", params={"view": "needs_action"})) == ["paid0001", "proc0002", "codp0003", "pick0005"]
    assert ids(await client.get("/admin/orders/", params={"view": "unpaid"})) == ["unpd0004"]
    assert ids(await client.get("/admin/orders/", params={"search": "tunde"})) == ["proc0002"]
    assert ids(await client.get("/admin/orders/", params={"search": "#PICK"})) == ["pick0005"]
    assert ids(await client.get("/admin/orders/", params={"method": "pickup"})) == ["pick0005"]

    rows = {o["id"]: o for o in (await client.get("/admin/orders/")).json()}
    assert rows["paid0001"]["customer_name"] == "Amaka Obi" and rows["paid0001"]["overdue"] is True
    assert rows["proc0002"]["is_guest"] is True and rows["proc0002"]["customer_phone"] == "0809"
    assert rows["paid0001"]["delivery_zone_name"] == "Wuse / Wuse 2"


@pytest.mark.asyncio
async def test_summary(client: AsyncClient, admin, orders):
    s = (await client.get("/admin/orders/summary")).json()
    assert s["counts"]["all"] == 6
    assert s["counts"]["needs_action"] == 4
    assert s["counts"]["unpaid"] == 1
    assert s["overdue"] == 1


@pytest.mark.asyncio
async def test_manual_status_rules(client: AsyncClient, admin, orders):
    put = lambda oid, st: client.put(f"/admin/orders/{oid}/status", params={"status": st})
    detail = (await client.get("/admin/orders/paid0001")).json()
    assert detail["allowed_moves"] == ["processing"]

    assert (await put("unpd0004", "paid")).status_code == 400       # only Paystack marks paid
    assert (await put("unpd0004", "processing")).status_code == 400
    assert (await put("codp0003", "processing")).status_code == 200  # COD accepted
    assert (await put("paid0001", "processing")).status_code == 200
    assert (await put("proc0002", "in_transit")).status_code == 400  # delivery needs dispatch
    assert (await put("proc0002", "delivered")).status_code == 400   # delivery needs PIN
    assert (await put("pick0005", "in_transit")).status_code == 200  # ready for pickup
    assert (await put("pick0005", "delivered")).status_code == 200   # collected
    assert (await put("canc0006", "processing")).status_code == 400


@pytest.mark.asyncio
async def test_dispatch_and_pin_rules(client: AsyncClient, admin, orders):
    courier = {"courier_name": "Ibrahim", "courier_phone": "0802", "courier_service": "Gokada"}
    assert (await client.put("/admin/orders/unpd0004/dispatch", json=courier)).status_code == 400
    assert (await client.put("/admin/orders/codp0003/dispatch", json=courier)).status_code == 400  # accept first

    out = await client.put("/admin/orders/proc0002/dispatch", json=courier)
    assert out.status_code == 200
    body = out.json()
    assert body["status"] == "in_transit"
    pin = body["delivery"]["delivery_pin"]
    assert pin and len(pin) == 4

    wrong = "0000" if pin != "0000" else "1111"
    assert (await client.put("/admin/orders/proc0002/confirm-delivery", json={"pin": wrong})).status_code == 400
    ok = await client.put("/admin/orders/proc0002/confirm-delivery", json={"pin": pin})
    assert ok.status_code == 200 and ok.json()["status"] == "delivered"

    # A cancelled order can never be "confirmed" delivered, even with a PIN.
    assert (await client.put("/admin/orders/canc0006/confirm-delivery", json={"pin": "1234"})).status_code == 400


@pytest.mark.asyncio
async def test_requires_admin(client: AsyncClient):
    assert (await client.get("/admin/orders/summary")).status_code == 401
