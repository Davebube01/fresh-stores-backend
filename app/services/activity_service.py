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

# Actions worth a second look: money taken back, things removed, data taken
# out of the system, and changes to who can do what. The Activity page flags
# these and can show only them.
FLAGGED_ACTIONS = frozenset({
    "sale.voided", "order.cancelled", "product.deleted", "category.deleted", "message.deleted",
    "staff.added", "staff.updated", "staff.password_reset", "staff.signed_out", "export.downloaded",
    "sale.till_discrepancy",
})


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
    flagged: bool = False,
) -> list:
    filters = []
    if flagged:
        filters.append(ActivityLog.action.in_(FLAGGED_ACTIONS))
    if entity_type:
        filters.append(ActivityLog.entity_type == entity_type)
    if entity_id:
        filters.append(ActivityLog.entity_id == entity_id)
    if actor_id:
        filters.append(ActivityLog.actor_id == actor_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(or_(
            ActivityLog.summary.ilike(term), ActivityLog.entity_label.ilike(term), ActivityLog.actor_name.ilike(term),
        ))
    if date_from:
        filters.append(ActivityLog.created_at >= datetime.combine(date_from, time.min, WAT).astimezone(timezone.utc))
    if date_to:
        filters.append(ActivityLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, WAT).astimezone(timezone.utc))
    return filters


async def _links(db: AsyncSession, rows: list) -> dict:
    """Where each entry's subject lives in the admin, by entry id (when it still exists)."""
    from app.models.product import Product

    product_ids = {r.entity_id for r in rows if r.entity_type == "product" and r.entity_id}
    slugs = {}
    if product_ids:
        slugs = dict((await db.execute(select(Product.id, Product.slug).where(Product.id.in_(product_ids)))).all())
    links = {}
    for r in rows:
        if r.entity_type == "order" and r.entity_id:
            links[r.id] = f"/admin/orders/{r.entity_id}"
        elif r.entity_type == "sale" and r.entity_id:
            links[r.id] = f"/admin/sales/{r.entity_id}"
        elif r.entity_type == "message" and r.entity_id and r.action != "message.deleted":
            links[r.id] = f"/admin/messages?open={r.entity_id}"
        elif r.entity_type == "product" and r.entity_id in slugs:
            links[r.id] = f"/admin/products/{slugs[r.entity_id]}"
        elif r.entity_type == "category" and r.action != "category.deleted":
            links[r.id] = "/admin/categories"
        elif r.entity_type == "staff":
            links[r.id] = "/admin/staff"
        elif r.entity_type == "settings":
            links[r.id] = "/admin/settings"
    return links


async def list_activity(
    db: AsyncSession,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    flagged: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    filters = _filters(entity_type, entity_id, actor_id, search, date_from, date_to, flagged)
    total = (await db.execute(select(func.count(ActivityLog.id)).where(*filters))).scalar_one()
    rows = (
        await db.execute(
            select(ActivityLog).where(*filters)
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id)
            .offset(skip).limit(limit)
        )
    ).scalars().all()
    links = await _links(db, rows)
    items = [
        {
            "id": r.id, "actor_id": r.actor_id, "actor_name": r.actor_name, "action": r.action,
            "entity_type": r.entity_type, "entity_id": r.entity_id, "entity_label": r.entity_label,
            "summary": r.summary, "changes": r.changes, "created_at": r.created_at,
            "flagged": r.action in FLAGGED_ACTIONS, "link": links.get(r.id),
        }
        for r in rows
    ]
    return {"items": items, "total": total}


async def activity_summary(
    db: AsyncSession,
    *,
    search: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict:
    """Counts for the Activity page's filters, over the same search and dates (not type or person)."""
    filters = _filters(None, None, None, search, date_from, date_to)
    total = (await db.execute(select(func.count(ActivityLog.id)).where(*filters))).scalar_one()
    flagged = (await db.execute(
        select(func.count(ActivityLog.id)).where(*filters, ActivityLog.action.in_(FLAGGED_ACTIONS))
    )).scalar_one()
    types = dict((await db.execute(
        select(ActivityLog.entity_type, func.count(ActivityLog.id)).where(*filters).group_by(ActivityLog.entity_type)
    )).all())
    actors = (await db.execute(
        select(ActivityLog.actor_id, func.max(ActivityLog.actor_name), func.count(ActivityLog.id))
        .where(*filters, ActivityLog.actor_id.isnot(None))
        .group_by(ActivityLog.actor_id)
        .order_by(func.count(ActivityLog.id).desc())
    )).all()
    return {
        "total": total,
        "flagged": flagged,
        "types": types,
        "actors": [{"id": a, "name": n or "Unknown", "count": c} for a, n, c in actors],
    }
