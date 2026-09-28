import pytest
from httpx import AsyncClient

from app.core.cache import clear_product_caches
from app.models.category import Category
from app.models.product import Product


@pytest.fixture(autouse=True)
def _fresh_cache():
    # Caches are module-level; don't let another test's responses leak in.
    clear_product_caches()
    yield
    clear_product_caches()


async def _seed(session_factory):
    async with session_factory() as db:
        db.add_all([
            Category(name="Goat Parts", slug="goat-parts"),
            Product(name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts", stock_quantity=10,
                    weight_options=["1kg", "2kg"], parts=["Hind leg", "Front leg"]),
            Product(name="Goat Ribs", slug="goat-ribs", price=15500, category="goat-parts", stock_quantity=0),
            Product(name="Goat Head", slug="goat-head", price=14000, category="goat-parts", stock_quantity=4),
            Product(name="Hidden Cut", slug="hidden-cut", price=1, category="goat-parts", is_active=False),
            Product(name="Ugu Leaves", slug="ugu", price=1500, category="vegetables", stock_quantity=20),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_detail_by_slug_with_category_and_related(client: AsyncClient, session_factory):
    await _seed(session_factory)
    res = await client.get("/api/v1/products/slug/goat-leg")
    assert res.status_code == 200
    body = res.json()
    assert body["product"]["name"] == "Goat Leg"
    assert body["product"]["parts"] == ["Hind leg", "Front leg"]
    assert body["category_name"] == "Goat Parts"
    # Same category only, no inactive or self, in-stock first.
    assert [p["slug"] for p in body["related"]] == ["goat-head", "goat-ribs"]


@pytest.mark.asyncio
async def test_unknown_category_and_missing_products(client: AsyncClient, session_factory):
    await _seed(session_factory)
    ugu = (await client.get("/api/v1/products/slug/ugu")).json()
    assert ugu["category_name"] is None and ugu["related"] == []

    assert (await client.get("/api/v1/products/slug/hidden-cut")).status_code == 404
    assert (await client.get("/api/v1/products/slug/nope")).status_code == 404
