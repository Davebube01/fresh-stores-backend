import pytest
from httpx import AsyncClient

from app.core.limiter import limiter
from app.models.order import Order, OrderStatus
from app.models.user import User

AMAKA = "a1b2c3d4-0000-4000-8000-000000000001"
GUEST = "a1b2c3d4-0000-4000-8000-000000000002"   # same short number as AMAKA
TUNDE = "ffff0000-0000-4000-8000-000000000003"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True


async def _seed(session_factory):
    async with session_factory() as db:
        db.add(User(id="u1", email="amaka@example.com", hashed_password="x"))
        for oid, uid, guest in [
            (AMAKA, "u1", None),
            (GUEST, None, {"fullName": "G", "email": "Guest@Example.com", "phone": "080"}),
            (TUNDE, None, {"fullName": "T", "email": "tunde@example.com", "phone": "080"}),
        ]:
            db.add(Order(id=oid, user_id=uid, guest_info=guest, status=OrderStatus.PROCESSING,
                         payment_method="cod", subtotal=1, total_amount=1))
        await db.commit()


async def track(client, number, email):
    return await client.get("/api/v1/orders/track", params={"order_number": number, "email": email})


@pytest.mark.asyncio
async def test_full_and_short_numbers(client: AsyncClient, session_factory):
    await _seed(session_factory)
    assert (await track(client, TUNDE, "tunde@example.com")).json()["id"] == TUNDE
    assert (await track(client, "#FFFF0000", " Tunde@Example.com ")).json()["id"] == TUNDE
    # Same 8-char prefix, told apart by the email.
    assert (await track(client, "#A1B2C3D4", "amaka@example.com")).json()["id"] == AMAKA
    assert (await track(client, "a1b2c3d4", "guest@example.com")).json()["id"] == GUEST


@pytest.mark.asyncio
async def test_mismatches_all_look_the_same(client: AsyncClient, session_factory):
    await _seed(session_factory)
    for number, email in [
        ("#FFFF0000", "amaka@example.com"),  # wrong email
        ("#FFFF", "tunde@example.com"),      # too short to be safe
        ("%%%%%%%%", "tunde@example.com"),   # wildcards aren't order numbers
        ("#00000000", "tunde@example.com"),  # no such order
    ]:
        res = await track(client, number, email)
        assert res.status_code == 404, number
        assert res.json()["detail"] == "Order not found or invalid credentials"
