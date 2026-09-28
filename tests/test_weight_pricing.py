import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.cache import clear_product_caches
from app.crud.order import cancel_order
from app.models.product import Product
from app.models.stock_movement import StockMovement


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_product_caches()
    yield
    clear_product_caches()


GUEST = {"fullName": "Guest", "email": "guest@test.com", "phone": "08012345678"}


async def _seed(session_factory):
    async with session_factory() as db:
        db.add_all([
            # Legacy row: bare labels, stocked in kg.
            Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="per-kg",
                    stock_quantity=24, weight_options=["1kg", "2kg"], parts=["Hind leg", "Front leg"]),
            # New-style row with explicit per-size prices.
            Product(id="whole", name="Whole Goat", slug="whole-goat", price=85000, category="goat-meat",
                    stock_quantity=6, weight_options=[
                        {"label": "Half", "price": 45000, "stock_units": 0.5},
                        {"label": "Full", "price": 85000, "stock_units": 1},
                    ]),
            Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts",
                    stock_quantity=8),
            Product(id="hidden", name="Hidden", slug="hidden", price=100, category="goat-parts",
                    stock_quantity=5, is_active=False),
        ])
        await db.commit()


async def _checkout(client, items):
    return await client.post("/api/v1/orders/checkout", json={
        "is_guest": True, "guest_info": GUEST, "payment_method": "cod",
        "delivery_method": "pickup", "items": items,
    })


async def _stock(session_factory, product_id):
    async with session_factory() as db:
        return (await db.execute(select(Product.stock_quantity).where(Product.id == product_id))).scalar_one()


@pytest.mark.asyncio
async def test_legacy_sizes_are_priced_and_stocked_by_weight(client: AsyncClient, session_factory):
    await _seed(session_factory)
    res = await client.get("/api/v1/products/leg")
    assert res.json()["weight_options"] == [
        {"label": "1kg", "price": 8500, "stock_units": 1},
        {"label": "2kg", "price": 17000, "stock_units": 2},
    ]

    res = await _checkout(client, [
        # The client-sent price is ignored.
        {"product_id": "leg", "quantity": 3, "weight_option": "2kg", "part": "Hind leg", "price_at_time": 1},
    ])
    assert res.status_code == 200, res.text
    order = res.json()
    assert order["total_amount"] == 51000
    assert order["items"][0]["price_at_time"] == 17000
    assert order["items"][0]["selected_option"] == "2kg · Hind leg"
    assert await _stock(session_factory, "leg") == 18  # 3 × 2kg

    async with session_factory() as db:
        await cancel_order(db, order["id"], reason="Changed mind", cancelled_by="admin")
    assert await _stock(session_factory, "leg") == 24


@pytest.mark.asyncio
async def test_explicit_size_prices_and_fractional_stock(client: AsyncClient, session_factory):
    await _seed(session_factory)
    res = await _checkout(client, [{"product_id": "whole", "quantity": 2, "weight_option": "Half"}])
    assert res.status_code == 200, res.text
    assert res.json()["total_amount"] == 90000
    assert await _stock(session_factory, "whole") == 5

    async with session_factory() as db:
        movements = (await db.execute(select(StockMovement).where(StockMovement.product_id == "whole"))).scalars().all()
    assert [m.change for m in movements] == [-1]


@pytest.mark.asyncio
async def test_legacy_combined_label_still_accepted(client: AsyncClient, session_factory):
    await _seed(session_factory)
    res = await _checkout(client, [{"product_id": "leg", "quantity": 1, "selected_option": "2kg · Front leg"}])
    assert res.status_code == 200, res.text
    assert res.json()["total_amount"] == 17000


@pytest.mark.asyncio
async def test_not_enough_stock_by_weight(client: AsyncClient, session_factory):
    await _seed(session_factory)
    # 13 × 2kg = 26kg, only 24kg in stock.
    res = await _checkout(client, [{"product_id": "leg", "quantity": 13, "weight_option": "2kg", "part": "Hind leg"}])
    assert res.status_code == 400
    assert "enough stock" in res.json()["detail"]
    assert await _stock(session_factory, "leg") == 24


@pytest.mark.asyncio
@pytest.mark.parametrize("item, message", [
    ({"product_id": "leg", "quantity": 1, "weight_option": "10kg", "part": "Hind leg"}, "isn't available"),
    ({"product_id": "leg", "quantity": 1, "part": "Hind leg"}, "Choose a size"),
    ({"product_id": "leg", "quantity": 1, "weight_option": "1kg", "part": "Tail"}, "isn't available"),
    ({"product_id": "leg", "quantity": 1, "weight_option": "1kg"}, "Choose a cut"),
    ({"product_id": "hidden", "quantity": 1}, "no longer available"),
])
async def test_invalid_lines_are_rejected(client: AsyncClient, session_factory, item, message):
    await _seed(session_factory)
    res = await _checkout(client, [item])
    assert res.status_code == 400
    assert message in res.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [0, -3])
async def test_non_positive_quantity_rejected(client: AsyncClient, session_factory, quantity):
    await _seed(session_factory)
    res = await _checkout(client, [{"product_id": "head", "quantity": quantity}])
    assert res.status_code == 422
    assert await _stock(session_factory, "head") == 8


@pytest.mark.asyncio
async def test_product_without_sizes_uses_base_price(client: AsyncClient, session_factory):
    await _seed(session_factory)
    res = await _checkout(client, [{"product_id": "head", "quantity": 2}])
    assert res.status_code == 200, res.text
    assert res.json()["total_amount"] == 9000
    assert await _stock(session_factory, "head") == 6
