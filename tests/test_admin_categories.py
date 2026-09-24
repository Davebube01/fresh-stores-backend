import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.main import app
from app.models.category import Category
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser


@pytest_asyncio.fixture
async def admin():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="admin", email="a@x.com", is_superuser=True)
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest_asyncio.fixture
async def seeded(session_factory):
    async with session_factory() as db:
        parts = Category(name="Goat Parts", slug="goat-parts")
        veg = Category(name="Vegetables", slug="vegetables", is_active=False)
        db.add_all([
            parts, veg,
            Product(name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts"),
            Product(name="Goat Ribs", slug="goat-ribs", price=15500, category="goat-parts", is_active=False),
        ])
        await db.commit()
        return {"parts": parts.id, "veg": veg.id}


@pytest.mark.asyncio
async def test_list_requires_admin(client: AsyncClient):
    assert (await client.get("/admin/categories")).status_code == 401


@pytest.mark.asyncio
async def test_list_includes_inactive_and_product_counts(client: AsyncClient, admin, seeded):
    res = await client.get("/admin/categories")
    assert res.status_code == 200
    rows = {c["slug"]: c for c in res.json()}
    assert rows["goat-parts"]["product_count"] == 2  # inactive products count too
    assert rows["vegetables"]["product_count"] == 0
    assert rows["vegetables"]["is_active"] is False


@pytest.mark.asyncio
async def test_create_validates_slug_and_rejects_duplicates(client: AsyncClient, admin, seeded):
    bad = await client.post("/admin/categories", json={"name": "Bundles", "slug": "Bundles & Packs"})
    assert bad.status_code == 422

    ok = await client.post("/admin/categories", json={"name": " Bundles ", "slug": "bundles"})
    assert ok.status_code == 201
    assert ok.json()["name"] == "Bundles" and ok.json()["product_count"] == 0

    dup_name = await client.post("/admin/categories", json={"name": "goat parts", "slug": "other"})
    assert dup_name.status_code == 409 and "name" in dup_name.json()["detail"]
    dup_slug = await client.post("/admin/categories", json={"name": "Other", "slug": "goat-parts"})
    assert dup_slug.status_code == 409 and "slug" in dup_slug.json()["detail"]


@pytest.mark.asyncio
async def test_slug_rename_moves_products(client: AsyncClient, admin, seeded, session_factory):
    res = await client.put(f"/admin/categories/{seeded['parts']}", json={"slug": "goat-cuts"})
    assert res.status_code == 200
    assert res.json()["product_count"] == 2

    async with session_factory() as db:
        cats = (await db.execute(select(Product.category))).scalars().all()
    assert set(cats) == {"goat-cuts"}

    clash = await client.put(f"/admin/categories/{seeded['parts']}", json={"slug": "vegetables"})
    assert clash.status_code == 409


@pytest.mark.asyncio
async def test_delete_blocked_while_products_use_it(client: AsyncClient, admin, seeded):
    blocked = await client.delete(f"/admin/categories/{seeded['parts']}")
    assert blocked.status_code == 409
    assert "2 products" in blocked.json()["detail"]

    assert (await client.delete(f"/admin/categories/{seeded['veg']}")).status_code == 200
    assert (await client.delete(f"/admin/categories/{seeded['veg']}")).status_code == 404
