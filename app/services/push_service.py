"""
Web Push for the admin PWA.

Sending a push never raises into the caller: the action that triggered a
notification (an order saved, stock adjusted) must succeed even if every
push in the world fails. Failures are logged instead. A subscription that
the push service reports as gone (404/410 — the browser unsubscribed, the
user cleared site data, ...) is deleted, so the table doesn't slowly fill
with dead endpoints.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterable

from pywebpush import WebPushException, webpush_async
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import permissions_for
from app.models.notification import AdminNotification
from app.models.push_subscription import PushSubscription, generate_uuid
from app.models.user import User
from app.schemas.push import PushSubscribeRequest

logger = logging.getLogger("push")


def configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


async def subscribe(db: AsyncSession, user_id: str, sub: PushSubscribeRequest, user_agent: str | None) -> None:
    now = datetime.now(timezone.utc)
    values = dict(
        user_id=user_id, endpoint=sub.endpoint, p256dh=sub.keys.p256dh, auth=sub.keys.auth,
        user_agent=(user_agent or "")[:255] or None, last_seen_at=now,
    )
    # A given browser's endpoint is stable across page loads, so "subscribe
    # again" (e.g. every login) should update the row, not fail on the
    # unique constraint or pile up duplicates.
    if db.bind.dialect.name == "postgresql":
        stmt = pg_insert(PushSubscription).values(id=generate_uuid(), **values)
        stmt = stmt.on_conflict_do_update(index_elements=["endpoint"], set_=values)
        await db.execute(stmt)
    else:
        existing = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == sub.endpoint))).scalar_one_or_none()
        if existing:
            for k, v in values.items():
                setattr(existing, k, v)
        else:
            db.add(PushSubscription(**values))
    await db.commit()


async def unsubscribe(db: AsyncSession, user_id: str, endpoint: str) -> None:
    await db.execute(delete(PushSubscription).where(PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint))
    await db.commit()


async def _send_one(db: AsyncSession, sub: PushSubscription, payload: dict) -> None:
    try:
        await webpush_async(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=60 * 60,  # if the device is offline, the push service holds it this long
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            await db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
            await db.commit()
        else:
            logger.warning("Push to %s failed (%s): %s", sub.endpoint[:60], status, exc)
    except Exception:
        logger.exception("Push to %s failed", sub.endpoint[:60])


async def _send_to_subscriptions(db: AsyncSession, subs: Iterable[PushSubscription], payload: dict) -> None:
    if not configured():
        logger.info("VAPID keys not configured — skipping push (would have sent: %s)", payload.get("title"))
        return
    for sub in subs:
        await _send_one(db, sub, payload)


async def send_to_user(db: AsyncSession, user_id: str, *, title: str, body: str | None = None, link: str | None = None) -> None:
    subs = (await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))).scalars().all()
    await _send_to_subscriptions(db, subs, {"title": title, "body": body, "link": link})


async def notify_staff(db: AsyncSession, permission: str, *, title: str, body: str | None = None, link: str | None = None) -> None:
    """Pushes to every active staff member whose role has `permission` (see app/core/permissions.py)."""
    staff = (await db.execute(select(User).where(User.is_superuser.is_(True), User.is_active.is_(True)))).scalars().all()
    recipients = [u for u in staff if permission in permissions_for(u)]
    if not recipients:
        return
    subs = (
        await db.execute(select(PushSubscription).where(PushSubscription.user_id.in_([u.id for u in recipients])))
    ).scalars().all()
    await _send_to_subscriptions(db, subs, {"title": title, "body": body, "link": link})


async def deliver_pending(db: AsyncSession, limit: int = 50) -> int:
    """
    Pushes every AdminNotification created since the last sweep (whatever
    kind — stock alerts, contact messages, new orders, ...) to whoever can
    see the bell, i.e. anyone with the "notifications" permission. Push and
    the in-app bell are one event stream delivered two ways, so this
    deliberately doesn't filter by kind.

    Kept completely separate from where AdminNotification rows are created
    (stock_alerts.py, contact.py, order_service.py, ...): those already run
    inside careful, sometimes multi-step transactions, and firing an HTTP
    request to a push service partway through one would hold it open for no
    reason. This just picks up whatever's new, on its own schedule.
    """
    rows = (
        await db.execute(
            select(AdminNotification)
            .where(AdminNotification.pushed_at.is_(None))
            .order_by(AdminNotification.created_at)
            .limit(limit)
        )
    ).scalars().all()
    for row in rows:
        await notify_staff(db, "notifications", title=row.title, body=row.body, link=row.link)
        row.pushed_at = datetime.now(timezone.utc)
    if rows:
        await db.commit()
    return len(rows)
