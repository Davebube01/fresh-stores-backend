from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import get_password_hash, hash_token, verify_password
from app.main import app
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.utils.dependencies import get_current_active_user

PASSWORD = "old-password-1"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest_asyncio.fixture
async def customer(session_factory):
    async with session_factory() as db:
        db.add(User(id="u1", email="amaka@example.com", full_name="Amaka", hashed_password=get_password_hash(PASSWORD)))
        await db.commit()

    # Like the real dependency: load the user in the request's own DB session.
    async def current(db=Depends(get_db)):
        return (await db.execute(select(User).where(User.id == "u1"))).scalar_one()

    app.dependency_overrides[get_current_active_user] = current
    yield
    app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_requires_sign_in(client: AsyncClient):
    assert (await client.patch("/api/v1/account/profile", json={"full_name": "X Y"})).status_code == 401
    assert (await client.get("/api/v1/account/addresses")).status_code == 401


@pytest.mark.asyncio
async def test_profile_update_normalises_phone(client: AsyncClient, customer):
    res = await client.patch("/api/v1/account/profile", json={"full_name": "  Amaka Obi ", "phone": "+234 803 111 2222"})
    assert res.status_code == 200
    assert res.json()["full_name"] == "Amaka Obi" and res.json()["phone"] == "08031112222"
    bad = await client.patch("/api/v1/account/profile", json={"full_name": "Amaka", "phone": "12345"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_password_change_keeps_this_session_only(client: AsyncClient, customer, session_factory):
    exp = datetime.now(timezone.utc) + timedelta(days=5)
    async with session_factory() as db:
        db.add_all([
            RefreshToken(user_id="u1", token_hash=hash_token("this-device"), family_id="fam-here", realm="customer", expires_at=exp),
            RefreshToken(user_id="u1", token_hash=hash_token("phone"), family_id="fam-phone", realm="customer", expires_at=exp),
        ])
        await db.commit()

    wrong = await client.post("/api/v1/auth/password", json={"current_password": "nope", "new_password": "new-password-2"})
    assert wrong.status_code == 400
    short = await client.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422

    client.cookies.set("refresh_token", "this-device")
    ok = await client.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "new-password-2"})
    assert ok.status_code == 200 and ok.json()["other_sessions_ended"] == 1

    async with session_factory() as db:
        tokens = {t.family_id: t for t in (await db.execute(select(RefreshToken))).scalars()}
        user = (await db.execute(select(User).where(User.id == "u1"))).scalar_one()
    assert tokens["fam-here"].revoked_at is None
    assert tokens["fam-phone"].revoked_at is not None
    assert verify_password("new-password-2", user.hashed_password)


@pytest.mark.asyncio
async def test_addresses(client: AsyncClient, customer):
    home = await client.post("/api/v1/account/addresses", json={"label": "Home", "zone_id": "wuse", "address": "Plot 7, Wuse 2", "apartment": " "})
    assert home.status_code == 201
    h = home.json()
    assert h["is_default"] is True  # first one
    assert h["zone_name"] == "Wuse / Wuse 2" and h["zone_fee"] == 2500 and h["apartment"] is None

    nowhere = await client.post("/api/v1/account/addresses", json={"label": "X", "zone_id": "mars", "address": "Crater 1, Mars"})
    assert nowhere.status_code == 400

    office = (await client.post("/api/v1/account/addresses", json={
        "label": "Office", "zone_id": "maitama", "address": "12 Aguiyi Ironsi St", "is_default": True,
    })).json()
    listed = (await client.get("/api/v1/account/addresses")).json()
    assert [a["label"] for a in listed] == ["Office", "Home"]  # default first
    assert [a["is_default"] for a in listed] == [True, False]

    assert (await client.post(f"/api/v1/account/addresses/{h['id']}/default")).json()["is_default"] is True
    assert (await client.delete(f"/api/v1/account/addresses/{h['id']}")).status_code == 204
    left = (await client.get("/api/v1/account/addresses")).json()
    assert len(left) == 1 and left[0]["id"] == office["id"] and left[0]["is_default"] is True  # default moved over

    assert (await client.delete("/api/v1/account/addresses/not-mine")).status_code == 404
