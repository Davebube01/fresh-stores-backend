"""
Low-stock thresholds and alerts.

A product is low on stock when it has at most its threshold left: its own
`low_stock_threshold` if set, otherwise the store-wide default from settings.

An alert (AdminNotification) is raised only when a stock change *crosses*
into low or out-of-stock, not on every sale while it stays low, and the
product's open alerts are marked read automatically once it's restocked
past the point they were about.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import AdminNotification
from app.models.product import Product
from app.services.settings_service import get_low_stock_threshold

LOW = "low_stock"
OUT = "out_of_stock"


def threshold_expr(default: float):
    """SQL expression for a product's effective threshold."""
    return func.coalesce(Product.low_stock_threshold, default)


def effective_threshold(product: Product, default: float) -> float:
    return float(product.low_stock_threshold) if product.low_stock_threshold is not None else default


def _qty(value: float) -> str:
    return f"{value:g}"


async def check_stock_alert(db: AsyncSession, product_id: str, previous: float, new: float) -> None:
    """Raise or resolve alerts for one stock change. Does not commit."""
    if new == previous:
        return
    product = await db.get(Product, product_id)
    if product is None:
        return
    threshold = effective_threshold(product, await get_low_stock_threshold(db))

    if new > previous:
        # Restocked: close the alerts the new level has made obsolete.
        kinds = [LOW, OUT] if new > threshold else [OUT] if new > 0 else []
        if kinds:
            await db.execute(
                update(AdminNotification)
                .where(
                    AdminNotification.product_id == product_id,
                    AdminNotification.read_at.is_(None),
                    AdminNotification.kind.in_(kinds),
                )
                .values(read_at=datetime.now(timezone.utc))
            )
        return

    if not product.is_active:
        return
    went_out = previous > 0 >= new
    went_low = previous > threshold >= new
    if not (went_out or went_low):
        return

    if new <= 0:
        kind, title = OUT, f"{product.name} is out of stock"
        body = "Customers can't order it until it's restocked."
    else:
        kind, title = LOW, f"{product.name} is running low"
        body = f"{_qty(new)} left (alert at {_qty(threshold)})."
    db.add(AdminNotification(
        kind=kind, title=title, body=body, product_id=product_id, link=f"/admin/products/{product.slug}",
    ))


async def list_notifications(db: AsyncSession, limit: int = 20) -> dict:
    unread = (
        await db.execute(select(func.count(AdminNotification.id)).where(AdminNotification.read_at.is_(None)))
    ).scalar_one()
    rows = (
        await db.execute(
            select(AdminNotification)
            .order_by(AdminNotification.read_at.is_not(None), AdminNotification.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return {"unread_count": unread, "items": rows}


async def mark_read(db: AsyncSession, notification_id: str | None = None) -> int:
    query = update(AdminNotification).where(AdminNotification.read_at.is_(None))
    if notification_id is not None:
        query = query.where(AdminNotification.id == notification_id)
    result = await db.execute(query.values(read_at=datetime.now(timezone.utc)))
    await db.commit()
    return result.rowcount or 0
