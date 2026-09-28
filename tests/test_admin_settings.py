import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core import delivery_zones as dz
from app.main import app
from app.models.product import Product
from app.models.user import User
from app.services.inventory_service import get_inventory
from app.utils.dependencies import get_current_active_superuser


@pytest.fixture(autouse=True)
def _restore_zone_registry():
    # The fee lookup is module state; don't let one test's edits leak into others.
    yield
    dz.DELIVERY_ZONES.clear()
    dz.DELIVERY_ZONES.update({k: dict(v) for k, v in dz.DEFAULT_ZONES.items()})
    dz.ZONE_NAMES.clear()
    dz.ZONE_NAMES.update({k: str(v["name"]) for k, v in dz.DEFAULT_ZONES.items()})


@pytest_asyncio.fixture
async def admin():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="admin", email="a@x.com", is_superuser=True)
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest.mark.asyncio
async def test_requires_admin(client: AsyncClient):
    assert (await client.get("/admin/settings")).status_code == 401
    assert (await client.put("/admin/settings/zones", json={"zones": []})).status_code == 401


@pytest.mark.asyncio
async def test_defaults_are_seeded(client: AsyncClient, admin):
    body = (await client.get("/admin/settings")).json()
    assert body["store"]["store_name"] == "Everything Fresh"
    assert body["store"]["low_stock_threshold"] == 5
    assert len(body["zones"]) == 8
    assert body["zones"][0]["id"] == "wuse"  # cheapest first
    assert body["payments"]["webhook_url"].endswith("/api/v1/payments/webhook")
    assert "secret" not in str(body["payments"]).lower()


@pytest.mark.asyncio
async def test_store_details_save_and_show_publicly(client: AsyncClient, admin, session_factory):
    bad = await client.put("/admin/settings/store", json={"store_name": "EF", "contact_email": "not-an-email"})
    assert bad.status_code == 422

    res = await client.put("/admin/settings/store", json={
        "store_name": "Everything Fresh", "contact_email": "hello@everythingfresh.ng", "contact_phone": " ",
        "pickup_address": "Plot 12, Wuse 2", "low_stock_threshold": 10,
    })
    assert res.status_code == 200
    assert res.json()["contact_phone"] is None  # blank -> cleared

    public = (await client.get("/api/v1/store")).json()
    assert public["pickup_address"] == "Plot 12, Wuse 2"
    assert "low_stock_threshold" not in public

    # The threshold drives the inventory page.
    async with session_factory() as db:
        db.add(Product(name="Leg", slug="leg", price=1, category="x", stock_quantity=8))
        await db.commit()
        inv = await get_inventory(db)
    assert inv["summary"]["low_stock_threshold"] == 10
    assert inv["summary"]["low_stock"] == 1


@pytest.mark.asyncio
async def test_zone_edits_reach_checkout_fee_lookup(client: AsyncClient, admin):
    zones = (await client.get("/admin/settings")).json()["zones"]
    kept = [z for z in zones if z["id"] != "airport"]  # drop Airport from the list
    payload = [{"id": z["id"], "name": z["name"], "fee": 2800 if z["id"] == "wuse" else z["fee"], "is_active": True} for z in kept]
    payload.append({"name": "Lugbe & Airport Road", "fee": 6000, "is_active": True})

    res = await client.put("/admin/settings/zones", json={"zones": payload})
    assert res.status_code == 200
    saved = {z["id"]: z for z in res.json()}
    assert saved["lugbe-airport-road"]["fee"] == 6000
    assert saved["airport"]["is_active"] is False  # left out -> switched off, not deleted

    assert dz.get_zone_fee("wuse") == 2800
    with pytest.raises(ValueError):
        dz.get_zone_fee("airport")
    assert dz.zone_name("airport") == "Airport"  # old orders still readable

    public = (await client.get("/api/v1/delivery/zones")).json()
    assert "airport" not in {z["id"] for z in public}
    assert public[-1]["id"] == "lugbe-airport-road"


@pytest.mark.asyncio
async def test_zone_list_rules(client: AsyncClient, admin):
    none_active = await client.put("/admin/settings/zones", json={"zones": [{"id": "wuse", "name": "Wuse", "fee": 1, "is_active": False}]})
    assert none_active.status_code == 400

    dupes = await client.put("/admin/settings/zones", json={"zones": [
        {"name": "Kubwa", "fee": 1}, {"name": "kubwa", "fee": 2},
    ]})
    assert dupes.status_code == 400 and "twice" in dupes.json()["detail"]
