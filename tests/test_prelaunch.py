import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings, settings
from app.crud.user import seed_admin_user
from app.models.order import Order, OrderStatus
from app.models.user import User

SECRET = "sk_test_unit_secret"


@pytest.fixture
def paystack(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "ENV", "development")
    return monkeypatch


async def _order(session_factory, total=17000.0, reference="GOAT-ref-1") -> str:
    async with session_factory() as db:
        order = Order(status=OrderStatus.PENDING, payment_method="paystack", subtotal=total, total_amount=total,
                      delivery_fee=0, payment_reference=reference, guest_info={"fullName": "G"})
        db.add(order)
        await db.commit()
        return order.id


async def _status(session_factory, order_id):
    async with session_factory() as db:
        order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
        return order.status, order.paid_at, order.payment_gateway_response


def _signed(body: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    return raw, {"x-paystack-signature": sig, "content-type": "application/json"}


def _charge(reference="GOAT-ref-1", amount=1_700_000, currency="NGN") -> dict:
    return {"event": "charge.success", "data": {"reference": reference, "amount": amount, "currency": currency}}


# --- Paystack webhook ----------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_rejects_unsigned_and_forged_calls_in_any_env(client: AsyncClient, session_factory, paystack):
    order_id = await _order(session_factory)
    raw = json.dumps(_charge()).encode()
    for env in ("development", "production"):
        paystack.setattr(settings, "ENV", env)
        unsigned = await client.post("/api/v1/payments/webhook", content=raw, headers={"content-type": "application/json"})
        forged_raw, forged_headers = _signed(_charge(), secret="sk_test_someone_else")
        forged = await client.post("/api/v1/payments/webhook", content=forged_raw, headers=forged_headers)
        assert (unsigned.status_code, forged.status_code) == (401, 401)
    assert (await _status(session_factory, order_id))[0] == OrderStatus.PENDING


@pytest.mark.asyncio
async def test_webhook_needs_a_configured_key(client: AsyncClient, session_factory, paystack):
    paystack.setattr(settings, "PAYSTACK_SECRET_KEY", None)
    raw, headers = _signed(_charge())
    assert (await client.post("/api/v1/payments/webhook", content=raw, headers=headers)).status_code == 503


@pytest.mark.asyncio
async def test_signed_full_payment_marks_order_paid(client: AsyncClient, session_factory, paystack):
    order_id = await _order(session_factory)
    raw, headers = _signed(_charge())
    assert (await client.post("/api/v1/payments/webhook", content=raw, headers=headers)).status_code == 200
    status, paid_at, _ = await _status(session_factory, order_id)
    assert status == OrderStatus.PROCESSING and paid_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("amount, currency, reason", [
    (1_000_000, "NGN", "paid 1000000 kobo, order total is 1700000 kobo"),
    (1_700_000, "USD", "paid in USD, expected NGN"),
    (None, "NGN", "no amount in the payment confirmation"),
])
async def test_short_or_wrong_payment_is_recorded_not_applied(client, session_factory, paystack, amount, currency, reason):
    order_id = await _order(session_factory)
    raw, headers = _signed(_charge(amount=amount, currency=currency))
    assert (await client.post("/api/v1/payments/webhook", content=raw, headers=headers)).status_code == 200
    status, paid_at, gateway = await _status(session_factory, order_id)
    assert status == OrderStatus.PENDING and paid_at is None
    assert [r["reason"] for r in gateway["rejected_payments"]] == [reason]


@pytest.mark.asyncio
async def test_simulator_only_in_development_with_test_keys(client: AsyncClient, session_factory, paystack):
    order_id = await _order(session_factory)

    paystack.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_live_real_money")
    assert (await client.post("/api/v1/payments/webhook/simulate", json={"reference": "GOAT-ref-1"})).status_code == 403
    paystack.setattr(settings, "PAYSTACK_SECRET_KEY", SECRET)
    paystack.setattr(settings, "ENV", "production")
    assert (await client.post("/api/v1/payments/webhook/simulate", json={"reference": "GOAT-ref-1"})).status_code == 403

    paystack.setattr(settings, "ENV", "development")
    assert (await client.post("/api/v1/payments/webhook/simulate", json={"reference": "nope"})).status_code == 404
    assert (await client.post("/api/v1/payments/webhook/simulate", json={"reference": "GOAT-ref-1"})).status_code == 200
    assert (await _status(session_factory, order_id))[0] == OrderStatus.PROCESSING


# --- First owner account --------------------------------------------------------

@pytest.mark.asyncio
async def test_no_default_admin_without_configuration(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAIL", None)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", None)
    async with session_factory() as db:
        assert await seed_admin_user(db) is None
        assert (await db.execute(select(User))).first() is None


@pytest.mark.asyncio
async def test_first_owner_from_env_only_once(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "Owner@Shop.com")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "a-long-owner-password")
    async with session_factory() as db:
        owner = await seed_admin_user(db)
        assert (owner.email, owner.staff_role, owner.is_superuser) == ("owner@shop.com", "owner", True)
        # Already has an admin: never creates or resets one again.
        monkeypatch.setattr(settings, "ADMIN_EMAIL", "other@shop.com")
        assert await seed_admin_user(db) is None
        assert len((await db.execute(select(User))).all()) == 1


@pytest.mark.parametrize("password", ["adminpassword123", "short-pass"])
def test_production_refuses_weak_admin_password(password):
    with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
        Settings(ENV="production", SECRET_KEY="x" * 40, ADMIN_PASSWORD=password, _env_file=None)
    Settings(ENV="production", SECRET_KEY="x" * 40, ADMIN_PASSWORD="", _env_file=None)  # empty = not set


# --- ALLOWED_ORIGINS as typed into a hosting dashboard -------------------------

@pytest.mark.parametrize("raw, expected", [
    ("https://everything-fresh.netlify.app", ["https://everything-fresh.netlify.app"]),
    ("https://a.app/, https://b.app", ["https://a.app", "https://b.app"]),
    ('["https://a.app", "https://b.app/"]', ["https://a.app", "https://b.app"]),
])
def test_allowed_origins_from_environment(monkeypatch, raw, expected):
    # Read from a real environment variable: that's where the JSON pre-parsing bit.
    monkeypatch.setenv("ALLOWED_ORIGINS", raw)
    assert Settings(_env_file=None).ALLOWED_ORIGINS == expected


# --- Hosted Postgres URLs pasted as-is ------------------------------------------

@pytest.mark.parametrize("pasted, expected", [
    ("postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
     "postgresql+asyncpg://u:p@ep-x.eu-central-1.aws.neon.tech/neondb?ssl=require"),
    ("postgres://u:p@dpg-abc-a/fresh", "postgresql+asyncpg://u:p@dpg-abc-a/fresh"),
    ("postgresql://u:p@host/db?sslmode=verify-full&application_name=api",
     "postgresql+asyncpg://u:p@host/db?ssl=verify-full&application_name=api"),
    ("postgresql://u:p@host/db?channel_binding=require", "postgresql+asyncpg://u:p@host/db"),
    ("sqlite+aiosqlite:///./sql_app.db", "sqlite+aiosqlite:///./sql_app.db"),
])
def test_database_url_from_hosting_providers(pasted, expected):
    assert Settings(DATABASE_URL=pasted, _env_file=None).async_database_url == expected


def test_neon_style_url_builds_an_asyncpg_engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    url = Settings(DATABASE_URL="postgresql://u:p@h/db?sslmode=require&channel_binding=require",
                   _env_file=None).async_database_url
    engine = create_async_engine(url)
    assert engine.dialect.driver == "asyncpg"
    assert engine.url.query == {"ssl": "require"}


# --- Migrations on a fresh database ---------------------------------------------

def _migrate(db_path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}"}
    return subprocess.run([sys.executable, "-m", "app.db_migrate"], env=env, capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parent.parent)


def test_migrate_builds_an_empty_database_and_is_rerunnable(tmp_path):
    import sqlite3
    from alembic.script import ScriptDirectory
    from app.db_migrate import _alembic_config

    db = tmp_path / "fresh.db"
    first = _migrate(db)
    assert first.returncode == 0, first.stderr
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert {"users", "products", "orders", "order_items", "activity_log"} <= tables
    assert con.execute("select version_num from alembic_version").fetchone()[0] == head
    con.close()

    again = _migrate(db)
    assert again.returncode == 0, again.stderr


def test_migrate_refuses_tables_without_history(tmp_path):
    import sqlite3
    db = tmp_path / "legacy.db"
    sqlite3.connect(db).execute("create table users (id text primary key)").connection.commit()
    result = _migrate(db)
    assert result.returncode == 1
    assert "no Alembic history" in result.stderr
