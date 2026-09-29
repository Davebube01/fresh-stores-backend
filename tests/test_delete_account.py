from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import get_password_hash, hash_token
from app.main import app
from app.models.address import SavedAddress
from app.models.contact import ContactMessage
from app.models.delivery import Delivery
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser, get_current_active_user

PASSWORD = "my-password-1"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest_asyncio.fixture
async def customer(session_factory):
    async with session_factory() as db:
        db.add_all([
            User(id="u1", email="amaka@example.com", full_name="Amaka Obi", phone="08031112222",
                 hashed_password=get_password_hash(PASSWORD), email_verified=True),
            Product(id="leg", name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts"),
            SavedAddress(user_id="u1", label="Home", address="Plot 7, Wuse 2", zone_id="wuse", is_default=True),
            RefreshToken(user_id="u1", token_hash=hash_token("phone"), family_id="f1", realm="customer",
                         expires_at=datetime.now(timezone.utc) + timedelta(days=5)),
            ContactMessage(name="Amaka Obi", email="amaka@example.com", message="Old question, answered", user_id="u1", status="handled"),
            ContactMessage(name="Amaka Obi", email="amaka@example.com", message="Still waiting on this", user_id="u1", status="new"),
        ])
        o = Order(id="o1", user_id="u1", status=OrderStatus.DELIVERED, total_amount=18000, subtotal=18000,
                  payment_method="paystack", paid_at=datetime.now(timezone.utc),
                  guest_info={"fullName": "Amaka Obi", "email": "amaka@example.com", "phone": "08031112222"})
        o.items.append(OrderItem(product_id="leg", quantity=1, price_at_time=18000))
        o.delivery = Delivery(address="Plot 7, Wuse 2", landmark="Blue gate", instructions="Call on arrival",
                              city="Abuja", state="FCT", delivery_zone="wuse", delivery_pin="1234")
        db.add(o)
        await db.commit()

    async def current(db=Depends(get_db)):
        return (await db.execute(select(User).where(User.id == "u1"))).scalar_one()

    app.dependency_overrides[get_current_active_user] = current
    yield
    app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_needs_sign_in_and_the_right_password(client: AsyncClient, customer):
    app.dependency_overrides.pop(get_current_active_user, None)
    assert (await client.post("/api/v1/auth/delete-account", json={"password": PASSWORD})).status_code == 401
    # Signed in again for the rest of the test.
    async def current(db=Depends(get_db)):
        return (await db.execute(select(User).where(User.id == "u1"))).scalar_one()
    app.dependency_overrides[get_current_active_user] = current

    wrong = await client.post("/api/v1/auth/delete-account", json={"password": "nope"})
    assert wrong.status_code == 400 and "password" in wrong.json()["detail"]


@pytest.mark.asyncio
async def test_blocked_while_an_order_is_in_progress(client: AsyncClient, customer, session_factory):
    async with session_factory() as db:
        db.add(Order(user_id="u1", status=OrderStatus.IN_TRANSIT, total_amount=9000, subtotal=9000, payment_method="cod"))
        await db.commit()
    res = await client.post("/api/v1/auth/delete-account", json={"password": PASSWORD})
    assert res.status_code == 400 and "in progress" in res.json()["detail"]
    async with session_factory() as db:
        assert (await db.get(User, "u1")).deleted_at is None


@pytest.mark.asyncio
async def test_wipes_personal_details_but_keeps_order_records(client: AsyncClient, customer, session_factory):
    res = await client.post("/api/v1/auth/delete-account", json={"password": PASSWORD})
    assert res.status_code == 200 and res.json() == {"deleted": True}
    assert "refresh_token" in res.headers.get("set-cookie", "")  # cookie cleared

    async with session_factory() as db:
        user = await db.get(User, "u1")
        order = await db.get(Order, "o1")
        delivery = (await db.execute(select(Delivery).where(Delivery.order_id == "o1"))).scalar_one()
        addresses = (await db.execute(select(SavedAddress))).scalars().all()
        tokens = (await db.execute(select(RefreshToken))).scalars().all()
        messages = (await db.execute(select(ContactMessage))).scalars().all()

    assert user.deleted_at is not None and not user.is_active
    assert user.email.endswith("@deleted.invalid") and user.full_name == "Deleted customer" and user.phone is None
    # The order and its money stay for the books; who and where don't.
    assert order.total_amount == 18000 and order.guest_info is None
    assert delivery.address == "Removed at the customer's request" and delivery.landmark is None
    assert delivery.instructions is None and delivery.delivery_pin is None and delivery.delivery_zone == "wuse"
    assert addresses == [] and tokens == []
    assert [m.message for m in messages] == ["Still waiting on this"] and messages[0].user_id is None

    # The same email can sign up again.
    app.dependency_overrides.pop(get_current_active_user, None)
    again = await client.post("/api/v1/auth/register", json={
        "email": "amaka@example.com", "password": "another-pass-9", "full_name": "Amaka Obi", "phone": "08031112222",
    })
    assert again.status_code == 201


@pytest.mark.asyncio
async def test_deleted_accounts_leave_the_admin_customer_list(client: AsyncClient, customer):
    await client.post("/api/v1/auth/delete-account", json={"password": PASSWORD})
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="o", email="o@x.com", is_superuser=True, staff_role="owner")
    try:
        assert (await client.get("/admin/customers")).json() == []
        assert (await client.get("/admin/customers/u1")).status_code == 404
        assert (await client.patch("/admin/customers/u1/status", json={"is_active": True})).status_code == 404
        assert (await client.get("/admin/customers/summary")).json()["total_customers"] == 0
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)
