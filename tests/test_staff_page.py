import pytest
from httpx import AsyncClient

from app.core.limiter import limiter
from app.main import app
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser


@pytest.fixture(autouse=True)
def _fresh():
    limiter.reset()
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


def act_as_owner():
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id="owner-1", email="owner@shop.com", full_name="Owner", hashed_password="x",
        is_superuser=True, is_active=True, staff_role="owner",
    )


def _row(listing: dict, staff_id: str) -> dict:
    return next(s for s in listing["staff"] if s["id"] == staff_id)


async def _login(client: AsyncClient, password: str) -> dict:
    res = await client.post("/admin/auth/login", json={"email": "kemi@shop.com", "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_temporary_password_until_they_change_it(client: AsyncClient):
    act_as_owner()
    kemi = (await client.post("/admin/staff", json={
        "email": "kemi@shop.com", "full_name": "Kemi Ade", "role": "cashier", "password": "counter-2026",
    })).json()
    assert kemi["password_is_temporary"] is True and kemi["active_sessions"] == 0
    app.dependency_overrides.pop(get_current_active_superuser)

    headers = await _login(client, "counter-2026")
    assert (await client.get("/admin/auth/me", headers=headers)).json()["password_is_temporary"] is True
    await client.post("/admin/auth/change-password", headers=headers,
                      json={"current_password": "counter-2026", "new_password": "my-own-pass-1"})
    assert (await client.get("/admin/auth/me", headers=headers)).json()["password_is_temporary"] is False

    # A reset by the owner makes it temporary again.
    act_as_owner()
    await client.post(f"/admin/staff/{kemi['id']}/reset-password", json={"password": "fresh-start-9"})
    assert _row((await client.get("/admin/staff")).json(), kemi["id"])["password_is_temporary"] is True


@pytest.mark.asyncio
async def test_owner_signs_staff_out_everywhere(client: AsyncClient):
    act_as_owner()
    kemi = (await client.post("/admin/staff", json={
        "email": "kemi@shop.com", "full_name": "Kemi Ade", "role": "cashier", "password": "counter-2026",
    })).json()
    app.dependency_overrides.pop(get_current_active_superuser)
    await _login(client, "counter-2026")  # the till
    await _login(client, "counter-2026")  # her phone

    act_as_owner()
    assert _row((await client.get("/admin/staff")).json(), kemi["id"])["active_sessions"] == 2
    assert (await client.post(f"/admin/staff/{kemi['id']}/sign-out")).status_code == 204
    after = _row((await client.get("/admin/staff")).json(), kemi["id"])
    assert after["active_sessions"] == 0 and after["is_active"] is True  # still allowed to sign back in
    assert (await client.post("/admin/staff/owner-1/sign-out")).status_code == 400
    assert (await client.post("/admin/staff/nobody/sign-out")).status_code == 404
    activity = (await client.get("/admin/activity", params={"entity_type": "staff"})).json()
    rows = activity.get("items", activity)
    assert any(r.get("summary") == "Signed Kemi Ade out of every device" for r in rows)

    # Their password still works: signing out isn't deactivating.
    app.dependency_overrides.pop(get_current_active_superuser)
    await _login(client, "counter-2026")
