"""
The admin activity log.

Routes call `log_activity` after an action has succeeded, so the log only
ever records things that actually happened. It commits on its own.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityLog

WAT = timezone(timedelta(hours=1))


def actor_label(user: Any) -> Optional[str]:
    if user is None:
        return None
    return getattr(user, "full_name", None) or (user.email.split("@")[0] if getattr(user, "email", None) else None)


def snapshot(obj: Any, fields: Iterable[str]) -> dict:
    """Plain values of `fields` on `obj`, for diffing before/after an edit."""
    out = {}
    for f in fields:
        value = getattr(obj, f, None)
        out[f] = getattr(value, "value", value)  # enums -> their value
    return out


def diff(before: dict, after: dict) -> dict:
    return {k: {"from": before.get(k), "to": after.get(k)} for k in after if before.get(k) != after.get(k)}


async def log_activity(
    db: AsyncSession,
    actor: Any,
    action: str,
    entity_type: str,
    summary: str,
    *,
    entity_id: Optional[str] = None,
    entity_label: Optional[str] = None,
    changes: Optional[dict] = None,
) -> None:
    db.add(ActivityLog(
        actor_id=getattr(actor, "id", None),
        actor_name=actor_label(actor),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        summary=summary[:500],
        changes=changes or None,
    ))
    await db.commit()


def _filters(
    entity_type: Optional[str],
    entity_id: Optional[str],
    actor_id: Optional[str],
    search: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
) -> list:
    filters = []
    if entity_type:
        filters.append(ActivityLog.entity_type == entity_type)
    if entity_id:
        filters.append(ActivityLog.entity_id == entity_id)
    if actor_id:
        filters.append(ActivityLog.actor_id == actor_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(or_(ActivityLog.summary.ilike(term), ActivityLog.entity_label.ilike(term)))
    if date_from:
        filters.append(ActivityLog.created_at >= datetime.combine(date_from, time.min, WAT).astimezone(timezone.utc))
    if date_to:
        filters.append(ActivityLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, WAT).astimezone(timezone.utc))
    return filters


async def list_activity(
    db: AsyncSession,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    filters = _filters(entity_type, entity_id, actor_id, search, date_from, date_to)
    total = (await db.execute(select(func.count(ActivityLog.id)).where(*filters))).scalar_one()
    rows = (
        await db.execute(
            select(ActivityLog).where(*filters)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id)
            .offset(skip).limit(limit)
        )
    ).scalars().all()
    return {"items": rows, "total": total}
