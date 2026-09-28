from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.main import app
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.services.inventory_service import get_inventory
from app.utils.dependencies import get_current_active_superuser

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


async def _seed(session_factory):
    async with session_factory() as db:
        admin = User(id="admin-1", email="chimdi@example.com", hashed_password="x", full_name="Chimdi A", is_superuser=True)
        leg = Product(id="leg", name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts", stock_quantity=3)
        ribs = Product(id="ribs", name="Goat Ribs", slug="goat-ribs", price=6000, category="goat-parts", stock_quantity=0)
        head = Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts", stock_quantity=5)
        whole = Product(id="whole", name="Whole Goat", slug="whole-goat", price=85000, category="goat-meat", stock_quantity=8)
        hidden = Product(id="old", name="Old", slug="old", price=1, category="x", stock_quantity=0, is_active=False)
        db.add_all([admin, leg, ribs, head, whole, hidden])

        def mv(pid, change, reason, days_ago, admin_id=None, note=None):
            db.add(StockMovement(product_id=pid, change=change, previous_quantity=0, new_quantity=0,
                                 reason=reason, admin_id=admin_id, note=note, created_at=NOW - timedelta(days=days_ago)))

        # Goat Leg sold 7 in the last week (one cancelled back): 6 net -> ~3.5 days left at 3 in stock.
        mv("leg", -4, "order_placed", 1)
        mv("leg", -3, "order_placed", 3)
        mv("leg", 1, "order_cancelled", 2)
        mv("leg", -10, "order_placed", 20)  # too old to count
        mv("head", 12, "restock", 0.5, admin_id="admin-1", note="Monday delivery")
        await db.commit()


@pytest.mark.asyncio
async def test_summary_and_restock_priorities(session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        data = await get_inventory(db, now=NOW)

    s = data["summary"]
    assert (s["active_products"], s["in_stock"], s["low_stock"], s["out_of_stock"]) == (4, 1, 2, 1)
    assert s["units_on_hand"] == 16
    assert s["stock_value"] == 3 * 18000 + 5 * 4500 + 8 * 85000

    names = [r["name"] for r in data["needs_restock"]]
    assert names == ["Goat Ribs", "Goat Leg", "Goat Head"]  # out first, then fastest to run out
    leg = data["needs_restock"][1]
    assert leg["sold_last_7_days"] == 6
    assert leg["days_left"] == 3.5
    assert data["needs_restock"][2]["days_left"] is None  # nothing sold recently


@pytest.mark.asyncio
async def test_movement_log_filters_and_names(session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        everything = await get_inventory(db, now=NOW)
        restocks = await get_inventory(db, reason="restock", now=NOW)
        leg_only = await get_inventory(db, product_id="leg", limit=2, now=NOW)

    assert everything["movements_total"] == 5
    assert everything["movements"][0]["product_name"] == "Goat Head"  # newest first
    assert everything["movements"][0]["admin_name"] == "Chimdi A"
    assert restocks["movements_total"] == 1 and restocks["movements"][0]["note"] == "Monday delivery"
    assert leg_only["movements_total"] == 4 and len(leg_only["movements"]) == 2


@pytest.mark.asyncio
async def test_endpoint_auth_and_validation(client: AsyncClient, session_factory):
    assert (await client.get("/admin/inventory")).status_code == 401
    await _seed(session_factory)
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="admin-1", email="a@x.com", is_superuser=True)
    try:
        ok = await client.get("/admin/inventory", params={"reason": "restock"})
        bad = await client.get("/admin/inventory", params={"reason": "stolen"})
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)
    assert ok.status_code == 200 and ok.json()["movements_total"] == 1
    assert bad.status_code == 422
