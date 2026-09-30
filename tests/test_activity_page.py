from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.main import app
from app.models.activity import ActivityLog
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def log(session_factory):
    async with session_factory() as db:
        db.add(Product(id="p1", name="Goat Leg", slug="goat-leg", price=18000, category="goat-parts"))
        db.add_all([
            ActivityLog(actor_id="kemi", actor_name="Kemi", action="sale.created", entity_type="sale", entity_id="s1",
                        summary="Sold Goat Leg", created_at=NOW - timedelta(minutes=5)),
            ActivityLog(actor_id="kemi", actor_name="Kemi", action="sale.voided", entity_type="sale", entity_id="s1",
                        summary="Voided sale #S1", created_at=NOW - timedelta(minutes=4)),
            ActivityLog(actor_id="owner", actor_name="Owner", action="product.updated", entity_type="product", entity_id="p1",
                        entity_label="Goat Leg", summary="Updated Goat Leg: price", created_at=NOW - timedelta(minutes=3)),
            ActivityLog(actor_id="owner", actor_name="Owner", action="product.deleted", entity_type="product", entity_id="gone",
                        entity_label="Goat Head", summary="Deleted Goat Head", created_at=NOW - timedelta(minutes=2)),
            ActivityLog(actor_id="owner", actor_name="Owner", action="staff.added", entity_type="staff", entity_id="kemi",
                        summary="Added Kemi as cashier", created_at=NOW - timedelta(days=10)),
        ])
        await db.commit()
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id="owner", email="o@x.com", full_name="Owner", is_superuser=True, staff_role="owner")
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest.mark.asyncio
async def test_flags_and_links(client: AsyncClient, log):
    items = {i["summary"]: i for i in (await client.get("/admin/activity")).json()["items"]}
    assert items["Voided sale #S1"]["flagged"] and items["Deleted Goat Head"]["flagged"] and items["Added Kemi as cashier"]["flagged"]
    assert not items["Sold Goat Leg"]["flagged"] and not items["Updated Goat Leg: price"]["flagged"]
    assert items["Sold Goat Leg"]["link"] == "/admin/sales/s1"
    assert items["Updated Goat Leg: price"]["link"] == "/admin/products/goat-leg"
    assert items["Deleted Goat Head"]["link"] is None  # nothing left to open
    assert items["Added Kemi as cashier"]["link"] == "/admin/staff"


@pytest.mark.asyncio
async def test_filters_and_summary(client: AsyncClient, log):
    flagged = (await client.get("/admin/activity", params={"flagged": True})).json()
    assert flagged["total"] == 3
    kemi = (await client.get("/admin/activity", params={"actor_id": "kemi"})).json()
    assert [i["summary"] for i in kemi["items"]] == ["Voided sale #S1", "Sold Goat Leg"]
    by_name = (await client.get("/admin/activity", params={"q": "kemi"})).json()  # search covers who did it
    assert by_name["total"] == 3

    # From yesterday (Abuja), so the run doesn't depend on the time of day; leaves out the 10-day-old entry.
    since = (NOW.astimezone(timezone(timedelta(hours=1))) - timedelta(days=1)).date().isoformat()
    summary = (await client.get("/admin/activity/summary", params={"date_from": since})).json()
    assert summary["total"] == 4 and summary["flagged"] == 2
    assert summary["types"] == {"sale": 2, "product": 2}
    assert [(a["name"], a["count"]) for a in summary["actors"]] == [("Kemi", 2), ("Owner", 2)] or \
           sorted((a["name"], a["count"]) for a in summary["actors"]) == [("Kemi", 2), ("Owner", 2)]


@pytest.mark.asyncio
async def test_export_follows_filters(client: AsyncClient, log):
    res = await client.get("/admin/exports/activity.csv", params={"actor_id": "kemi", "flagged": True})
    lines = res.text.strip().splitlines()
    assert lines[0].lstrip("﻿").startswith("Date,Who,Action,What,Summary,Flagged")
    assert len(lines) == 2 and "sale.voided" in lines[1] and lines[1].endswith(",yes")
