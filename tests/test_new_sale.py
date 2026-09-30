import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.cache import clear_product_caches
from app.main import app
from app.models.activity import ActivityLog
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser


@pytest_asyncio.fixture
async def till(session_factory):
    clear_product_caches()
    async with session_factory() as db:
        db.add_all([
            User(id="kemi", email="kemi@shop.com", full_name="Kemi", hashed_password="x", is_superuser=True, staff_role="cashier"),
            Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="goat-parts", stock_quantity=5),
        ])
        await db.commit()
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id="kemi", email="kemi@shop.com", full_name="Kemi", hashed_password="x", is_superuser=True, staff_role="cashier")
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)
    clear_product_caches()


async def _stock(session_factory):
    async with session_factory() as db:
        return (await db.execute(select(Product.stock_quantity).where(Product.id == "leg"))).scalar_one()


@pytest.mark.asyncio
async def test_same_sale_sent_twice_is_sold_once(client: AsyncClient, session_factory, till):
    body = {"payment_method": "pos", "items": [{"product_id": "leg", "quantity": 2}], "client_ref": "till-1-abc12345"}
    first = await client.post("/admin/sales", json=body)
    again = await client.post("/admin/sales", json=body)
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert await _stock(session_factory) == 3  # taken once, not twice
    async with session_factory() as db:
        assert (await db.execute(select(func.count(Order.id)))).scalar_one() == 1
        assert (await db.execute(select(func.count(ActivityLog.id)).where(ActivityLog.action == "sale.created"))).scalar_one() == 1

    other = await client.post("/admin/sales", json={**body, "client_ref": "till-1-def67890"})
    assert other.json()["id"] != first.json()["id"] and await _stock(session_factory) == 1


@pytest.mark.asyncio
async def test_cash_tendered_for_change(client: AsyncClient, till):
    short = await client.post("/admin/sales", json={
        "payment_method": "cash", "items": [{"product_id": "leg"}], "cash_tendered": 8000})
    assert short.status_code == 400 and "less than the total" in short.json()["detail"]

    sale = (await client.post("/admin/sales", json={
        "payment_method": "cash", "items": [{"product_id": "leg"}], "cash_tendered": 10000})).json()
    assert sale["cash_tendered"] == 10000 and sale["total_amount"] == 8500
    assert (await client.get(f"/admin/sales/{sale['id']}")).json()["cash_tendered"] == 10000

    # Only cash has change: a tendered amount on a POS sale is ignored.
    pos = (await client.post("/admin/sales", json={
        "payment_method": "pos", "items": [{"product_id": "leg"}], "cash_tendered": 20000})).json()
    assert pos["cash_tendered"] is None
