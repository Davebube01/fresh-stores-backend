from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.v1 import account as account_api
from app.core import throttle
from app.core.limiter import limiter
from app.core.security import get_password_hash, verify_password
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.account_service import create_reset_token


@pytest.fixture(autouse=True)
def _no_limits():
    limiter.enabled = False
    throttle._hits.clear()
    yield
    limiter.enabled = True
    throttle._hits.clear()


@pytest.fixture
def sent(monkeypatch):
    """Capture reset emails instead of logging them."""
    outbox = []

    async def fake_send(email, name, url, minutes):
        outbox.append({"email": email, "url": url})

    monkeypatch.setattr(account_api, "send_password_reset_email", fake_send)
    return outbox


async def _seed(session_factory):
    async with session_factory() as db:
        db.add_all([
            User(id="u1", email="amaka@example.com", hashed_password=get_password_hash("old-password-1")),
            User(id="boss", email="boss@example.com", hashed_password=get_password_hash("x" * 10), is_superuser=True),
            RefreshToken(user_id="u1", token_hash="t1", family_id="f1", realm="customer",
                         expires_at=datetime.now(timezone.utc) + timedelta(days=5)),
        ])
        await db.commit()


@pytest.mark.asyncio
async def test_forgot_password_never_reveals_accounts(client: AsyncClient, session_factory, sent):
    await _seed(session_factory)
    for email in ["Amaka@Example.com", "nobody@example.com", "boss@example.com"]:
        res = await client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert res.status_code == 200 and res.json() == {"sent": True}
    # Only the real customer got an email (not the unknown address, not staff).
    assert [m["email"] for m in sent] == ["amaka@example.com"]
    assert "/reset-password?token=" in sent[0]["url"]


@pytest.mark.asyncio
async def test_reset_link_works_once_and_signs_out_everywhere(client: AsyncClient, session_factory):
    await _seed(session_factory)
    async with session_factory() as db:
        token = create_reset_token((await db.execute(select(User).where(User.id == "u1"))).scalar_one())

    short = await client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "short"})
    assert short.status_code == 422

    ok = await client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "brand-new-pass"})
    assert ok.status_code == 200

    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.id == "u1"))).scalar_one()
        tok = (await db.execute(select(RefreshToken))).scalar_one()
    assert verify_password("brand-new-pass", user.hashed_password)
    assert user.email_verified is True
    assert tok.revoked_at is not None

    again = await client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "another-pass-9"})
    assert again.status_code == 400  # the password changed, so the link is dead

    junk = await client.post("/api/v1/auth/reset-password", json={"token": "not-a-token", "new_password": "another-pass-9"})
    assert junk.status_code == 400


@pytest.mark.asyncio
async def test_public_resend_verification(client: AsyncClient, session_factory, monkeypatch):
    outbox = []

    async def fake_send(email, name, url):
        outbox.append(email)

    monkeypatch.setattr(account_api, "send_verification_email", fake_send)
    async with session_factory() as db:
        db.add_all([
            User(id="new", email="new@example.com", hashed_password="x"),
            User(id="done", email="done@example.com", hashed_password="x", email_verified=True),
        ])
        await db.commit()
    for email in ["NEW@example.com", "done@example.com", "ghost@example.com"]:
        res = await client.post("/api/v1/auth/resend-verification-public", json={"email": email})
        assert res.json() == {"sent": True}
    assert outbox == ["new@example.com"]  # only the unverified account
