import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.limiter import limiter
from app.main import app
from app.models.contact import ContactMessage, ContactReply
from app.models.order import Order, OrderStatus
from app.models.notification import AdminNotification
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

GOOD = {"name": "Amaka Obi", "email": "Amaka@Example.com", "topic": "bulk", "message": "Can you do 3 whole goats for a wedding on Saturday?"}


@pytest.fixture(autouse=True)
def _no_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.mark.asyncio
async def test_message_is_stored_and_flagged(client: AsyncClient, session_factory):
    res = await client.post("/api/v1/contact", json={**GOOD, "phone": " ", "order_ref": "#A1B2C3D4"})
    assert res.status_code == 201
    async with session_factory() as db:
        msg = (await db.execute(select(ContactMessage))).scalar_one()
        note = (await db.execute(select(AdminNotification))).scalar_one()
    assert msg.email == "amaka@example.com" and msg.phone is None and msg.status == "new"
    assert note.kind == "contact_message" and "Amaka Obi" in note.title and msg.id in note.link


@pytest.mark.asyncio
async def test_validation_and_honeypot(client: AsyncClient, session_factory):
    assert (await client.post("/api/v1/contact", json={**GOOD, "message": "hi"})).status_code == 422
    assert (await client.post("/api/v1/contact", json={**GOOD, "email": "nope"})).status_code == 422
    assert (await client.post("/api/v1/contact", json={**GOOD, "topic": "spam"})).status_code == 422
    bot = await client.post("/api/v1/contact", json={**GOOD, "website": "http://spam.example"})
    assert bot.status_code == 201  # looks fine to the bot...
    async with session_factory() as db:
        assert (await db.execute(select(ContactMessage))).first() is None  # ...but nothing is saved


@pytest.mark.asyncio
async def test_admin_inbox(client: AsyncClient):
    assert (await client.get("/admin/messages")).status_code == 401
    await client.post("/api/v1/contact", json=GOOD)
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="o", email="owner@x.com", full_name="Owner", is_superuser=True, staff_role="owner")
    try:
        inbox = (await client.get("/admin/messages")).json()
        assert inbox["new_count"] == 1
        mid = inbox["messages"][0]["id"]
        done = (await client.patch(f"/admin/messages/{mid}", json={"status": "handled"})).json()
        assert done["status"] == "handled" and done["handled_by"] == "Owner"
        assert (await client.get("/admin/messages", params={"status": "new"})).json() == {"messages": [], "new_count": 0, "handled_count": 1}

        app.dependency_overrides[get_current_active_superuser] = lambda: User(id="c", email="c@x.com", is_superuser=True, staff_role="cashier")
        assert (await client.get("/admin/messages")).status_code == 403  # cashiers can't read them
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)



def _owner():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(id="o", email="owner@x.com", full_name="Owner", is_superuser=True, staff_role="owner")


@pytest.mark.asyncio
async def test_search_filter_and_counts(client: AsyncClient):
    await client.post("/api/v1/contact", json=GOOD)
    await client.post("/api/v1/contact", json={**GOOD, "name": "Tunde Bello", "email": "tunde@example.com", "topic": "delivery",
                                                  "message": "My rider hasn't arrived yet, it's been an hour."})
    _owner()
    try:
        by_topic = (await client.get("/admin/messages", params={"topic": "delivery"})).json()
        assert [m["name"] for m in by_topic["messages"]] == ["Tunde Bello"] and by_topic["new_count"] == 1
        found = (await client.get("/admin/messages", params={"q": "wedding"})).json()
        assert [m["name"] for m in found["messages"]] == ["Amaka Obi"]
        assert (await client.get("/admin/messages", params={"topic": "spam"})).status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest.mark.asyncio
async def test_reply_is_kept_and_marks_handled(client: AsyncClient, session_factory):
    async with session_factory() as db:
        db.add(Order(id="a1b2c3d4-0000-4000-8000-000000000001", status=OrderStatus.DELIVERED, total_amount=1, subtotal=1))
        await db.commit()
    await client.post("/api/v1/contact", json={**GOOD, "topic": "order", "order_ref": "#A1B2C3D4"})
    _owner()
    try:
        mid = (await client.get("/admin/messages")).json()["messages"][0]["id"]
        one = (await client.get(f"/admin/messages/{mid}")).json()
        assert one["order_id"] == "a1b2c3d4-0000-4000-8000-000000000001" and one["replies"] == []

        assert (await client.post(f"/admin/messages/{mid}/reply", json={"body": " "})).status_code == 422
        res = (await client.post(f"/admin/messages/{mid}/reply", json={"body": "Yes, we can. Call us on 0803 000 0000."})).json()
        assert res["status"] == "handled" and res["handled_by"] == "Owner"
        assert [(r["body"], r["sent_by"]) for r in res["replies"]] == [("Yes, we can. Call us on 0803 000 0000.", "Owner")]

        again = (await client.post(f"/admin/messages/{mid}/reply", json={"body": "One more thing.", "mark_handled": False})).json()
        assert len(again["replies"]) == 2 and again["status"] == "handled"  # replying doesn't reopen it
        activity = (await client.get("/admin/activity")).json()
        rows = activity.get("items", activity)
        assert any(r.get("summary") == "Replied to Amaka Obi's message" for r in rows)
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest.mark.asyncio
async def test_delete_removes_message_and_replies(client: AsyncClient, session_factory):
    await client.post("/api/v1/contact", json=GOOD)
    _owner()
    try:
        mid = (await client.get("/admin/messages")).json()["messages"][0]["id"]
        await client.post(f"/admin/messages/{mid}/reply", json={"body": "Thanks!"})
        assert (await client.delete(f"/admin/messages/{mid}")).status_code == 204
        assert (await client.get(f"/admin/messages/{mid}")).status_code == 404
        async with session_factory() as db:
            assert (await db.execute(select(ContactReply))).first() is None
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)
