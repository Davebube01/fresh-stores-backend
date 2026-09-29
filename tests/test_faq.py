import pytest
from httpx import AsyncClient

from app.main import app
from app.models.user import User
from app.services.faq_service import DEFAULT_FAQS
from app.utils.dependencies import get_current_active_superuser


def _as(role: str):
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id=role, email=f"{role}@x.com", full_name=role.title(), is_superuser=True, staff_role=role
    )


@pytest.mark.asyncio
async def test_defaults_until_the_store_saves_its_own(client: AsyncClient):
    public = (await client.get("/api/v1/faqs")).json()
    assert len(public) == len(DEFAULT_FAQS) and all(f["id"] is None for f in public)
    assert {f["section"] for f in public} == {"ordering", "delivery", "payment", "account"}

    _as("owner")
    try:
        admin = (await client.get("/admin/faqs")).json()
        assert admin["is_default"] is True and len(admin["items"]) == len(DEFAULT_FAQS)
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)


@pytest.mark.asyncio
async def test_save_reorder_hide_and_delete(client: AsyncClient):
    _as("owner")
    try:
        items = [
            {"section": "delivery", "question": "Do you deliver on Sundays?", "answer": "Yes, 10am to 4pm."},
            {"section": "payment", "question": "Can I pay in cash?", "answer": "Yes, on delivery.", "is_published": False},
            {"section": "ordering", "question": "  Is it halal?  ", "answer": "Yes, every goat."},
        ]
        saved = (await client.put("/admin/faqs", json={"items": items})).json()
        assert [f["question"] for f in saved] == ["Do you deliver on Sundays?", "Can I pay in cash?", "Is it halal?"]

        public = (await client.get("/api/v1/faqs")).json()
        assert [f["question"] for f in public] == ["Do you deliver on Sundays?", "Is it halal?"]  # hidden one left out

        # Reorder, edit one in place, drop another.
        sunday, _, halal = saved
        again = [{**halal, "answer": "Yes, all of it."}, sunday]
        saved = (await client.put("/admin/faqs", json={"items": again})).json()
        assert [f["id"] for f in saved] == [halal["id"], sunday["id"]]  # same rows, kept their ids
        assert saved[0]["answer"] == "Yes, all of it."
        assert (await client.get("/admin/faqs")).json()["is_default"] is False

        assert (await client.put("/admin/faqs", json={"items": []})).status_code == 422
        assert (await client.put("/admin/faqs", json={"items": [{**sunday, "section": "misc"}]})).status_code == 422
        activity = (await client.get("/admin/activity")).json()
        assert any("FAQ page" in (row.get("summary") or "") for row in activity.get("items", activity))

        _as("manager")
        assert (await client.get("/admin/faqs")).status_code == 403  # settings are owner-only
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)
