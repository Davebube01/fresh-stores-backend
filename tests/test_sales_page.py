from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.cache import clear_product_caches
from app.main import app
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

WAT = timezone(timedelta(hours=1))


def act_as(role: str):
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id="kemi", email="kemi@shop.com", full_name="Kemi", hashed_password="x", is_superuser=True, staff_role=role)


@pytest_asyncio.fixture
async def shop(session_factory):
    clear_product_caches()
    async with session_factory() as db:
        db.add_all([
            User(id="kemi", email="kemi@shop.com", full_name="Kemi", hashed_password="x", is_superuser=True, staff_role="owner"),
            Product(id="leg", name="Goat Leg", slug="goat-leg", price=8500, category="goat-parts", stock_quantity=20, cost_price=6000),
            Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=6),
        ])
        await db.commit()
    act_as("owner")
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)
    clear_product_caches()


async def _sell(client, method, items):
    res = await client.post("/admin/sales", json={"payment_method": method, "items": items})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_day_summary_has_best_sellers_hours_and_profit(client: AsyncClient, shop):
    await _sell(client, "cash", [{"product_id": "leg", "quantity": 2}])      # 17,000, cost 12,000
    await _sell(client, "pos", [{"product_id": "head"}])                      # 4,500, no cost price
    voided = await _sell(client, "cash", [{"product_id": "leg"}])
    await client.post(f"/admin/sales/{voided['id']}/void", json={"reason": "Rung twice"})

    day = (await client.get("/admin/sales")).json()
    assert day["cash_expected"] == 17000
    assert [(t["name"], t["quantity"], t["total"]) for t in day["top_items"]] == [("Goat Leg", 2, 17000), ("Goat Head", 1, 4500)]
    assert sum(h["count"] for h in day["hourly"]) == 2 and sum(h["total"] for h in day["hourly"]) == 21500
    assert day["profit"] == 21500 - 12000 and day["profit_complete"] is False  # the head has no cost price
    assert all(s["served_by_name"] == "Kemi" for s in day["sales"])

    act_as("cashier")
    cashier_view = (await client.get("/admin/sales")).json()
    assert cashier_view["profit"] is None  # no cost access, no profit


@pytest.mark.asyncio
async def test_cash_up(client: AsyncClient, shop):
    await _sell(client, "cash", [{"product_id": "leg", "quantity": 2}])
    today = datetime.now(timezone.utc).astimezone(WAT).date()

    act_as("cashier")  # the person on the till can cash up
    short = await client.put(f"/admin/sales/till/{today}", json={"opening_float": 5000, "counted_cash": 21000, "note": "Gave change from my purse"})
    assert short.status_code == 200, short.text
    till = short.json()
    assert (till["expected_cash"], till["counted_cash"], till["difference"]) == (22000, 21000, -1000)
    assert till["counted_by"] == "Kemi"

    act_as("owner")
    assert (await client.get("/admin/sales")).json()["till"]["difference"] == -1000
    activity = (await client.get("/admin/activity", params={"flagged": True})).json()["items"]
    assert any(a["action"] == "sale.till_discrepancy" and "₦1,000 short" in a["summary"] for a in activity)

    # Recounted and it balances: replaces the count, not flagged.
    again = (await client.put(f"/admin/sales/till/{today}", json={"opening_float": 5000, "counted_cash": 22000})).json()
    assert again["difference"] == 0 and again["note"] is None
    assert (await client.get("/admin/activity", params={"q": "balanced"})).json()["total"] == 1

    tomorrow = today + timedelta(days=1)
    assert (await client.put(f"/admin/sales/till/{tomorrow}", json={"counted_cash": 0})).status_code == 400
    assert (await client.put(f"/admin/sales/till/{today}", json={"counted_cash": -5})).status_code == 422
