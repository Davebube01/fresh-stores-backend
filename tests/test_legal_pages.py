import pytest
from httpx import AsyncClient

from app.main import app
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser


def _as(role: str):
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id=role, email=f"{role}@x.com", full_name=role.title(), is_superuser=True, staff_role=role
    )


@pytest.mark.asyncio
async def test_defaults_are_filled_from_store_details(client: AsyncClient):
    for slug, title in (("terms", "Terms of service"), ("privacy", "Privacy policy")):
        page = (await client.get(f"/api/v1/pages/{slug}")).json()
        assert page["title"] == title and page["is_default"] is True
        assert "{" not in page["body"]  # every placeholder filled
        assert "Everything Fresh" in page["body"] and "Abuja, Nigeria" in page["body"]
        assert "[Contact page](/contact)" in page["body"]
    assert (await client.get("/api/v1/pages/cookies")).status_code == 422

    _as("owner")
    try:
        await client.put("/admin/settings/store", json={
            "store_name": "Mama's Meats", "contact_email": "hi@mamas.ng", "contact_phone": "0803 000 0000",
            "low_stock_threshold": 5,
        })
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)
    body = (await client.get("/api/v1/pages/privacy")).json()["body"]
    assert "Mama's Meats" in body
    assert "by email at [hi@mamas.ng](mailto:hi@mamas.ng), by phone on 0803 000 0000 or through our [Contact page](/contact)" in body


@pytest.mark.asyncio
async def test_edit_and_reset(client: AsyncClient):
    assert (await client.get("/admin/pages/terms")).status_code == 401
    _as("owner")
    try:
        admin = (await client.get("/admin/pages/terms")).json()
        assert admin["is_default"] is True and "{store_name}" in admin["body"] and admin["body"] == admin["default_body"]

        own = "## Our terms\n" + "{store_name} sells goat meat. " * 10
        saved = (await client.put("/admin/pages/terms", json={"body": own})).json()
        assert saved["is_default"] is False and saved["updated_by"] == "Owner"
        public = (await client.get("/api/v1/pages/terms")).json()
        assert public["is_default"] is False and public["body"].startswith("## Our terms\nEverything Fresh sells")
        assert (await client.get("/api/v1/pages/privacy")).json()["is_default"] is True  # the other page is untouched

        # Saving the default text again goes back to following the default.
        reset = (await client.put("/admin/pages/terms", json={"body": admin["default_body"]})).json()
        assert reset["is_default"] is True

        assert (await client.put("/admin/pages/terms", json={"body": "too short"})).status_code == 422

        _as("manager")
        assert (await client.get("/admin/pages/privacy")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_superuser, None)
