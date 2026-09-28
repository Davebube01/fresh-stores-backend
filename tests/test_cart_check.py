import pytest
from httpx import AsyncClient

from app.models.product import Product


async def _seed(session_factory):
    async with session_factory() as db:
        db.add_all([
            Product(id="whole", name="Whole Goat", slug="whole-goat", price=85000, category="goat-meat",
                    stock_quantity=2, weight_options=[
                        {"label": "Half", "price": 45000, "stock_units": 0.5},
                        {"label": "Full", "price": 85000, "stock_units": 1},
                    ]),
            Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=8),
            Product(id="ribs", name="Goat Ribs", slug="goat-ribs", price=6000, category="goat-parts", stock_quantity=0),
            Product(id="hidden", name="Hidden", slug="hidden", price=100, category="goat-parts", stock_quantity=5, is_active=False),
        ])
        await db.commit()


def line(key, pid, qty, price=None, size=None):
    return {"key": key, "product_id": pid, "quantity": qty, "unit_price": price, "weight_option": size}


@pytest.mark.asyncio
async def test_statuses(client: AsyncClient, session_factory):
    await _seed(session_factory)
    res = await client.post("/api/v1/cart/check", json={"items": [
        line("a", "head", 2, price=4500),
        line("b", "head", 1, price=4000),        # price went up
        line("c", "ribs", 1, price=6000),        # sold out
        line("d", "hidden", 1, price=100),       # switched off
        line("e", "gone", 1, price=1),           # deleted
        line("f", "whole", 1, price=85000),      # needs a size
        line("g", "whole", 1, price=85000, size="Huge"),
    ]})
    assert res.status_code == 200
    got = {l["key"]: l for l in res.json()["lines"]}
    assert got["a"]["status"] == "ok" and got["a"]["max_quantity"] == 8
    assert got["b"]["status"] == "price_changed" and got["b"]["unit_price"] == 4500
    assert got["b"]["max_quantity"] == 6  # shares stock with line a
    assert got["c"]["status"] == "out_of_stock"
    assert got["d"]["status"] == "unavailable" and got["e"]["status"] == "unavailable"
    assert got["f"]["status"] == "unavailable" and "size" in got["f"]["message"]
    assert got["g"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_sizes_share_stock(client: AsyncClient, session_factory):
    await _seed(session_factory)
    # 2 whole goats in stock: 1 Full uses 1, leaving room for 2 Halves (0.5 each).
    res = await client.post("/api/v1/cart/check", json={"items": [
        line("full", "whole", 1, price=85000, size="Full"),
        line("half", "whole", 5, price=45000, size="Half"),
    ]})
    got = {l["key"]: l for l in res.json()["lines"]}
    assert got["full"]["status"] == "ok"
    assert got["half"]["status"] == "reduced" and got["half"]["max_quantity"] == 2


@pytest.mark.asyncio
async def test_validation(client: AsyncClient):
    assert (await client.post("/api/v1/cart/check", json={"items": [line("x", "head", 0)]})).status_code == 422
    assert (await client.post("/api/v1/cart/check", json={"items": []})).json() == {"lines": []}
