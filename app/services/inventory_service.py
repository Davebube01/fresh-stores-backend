"""
Stock overview for the admin Inventory page: what's running low, how fast
it's selling, and every stock change across the catalogue (the per-product
log already exists on the product page; this is the store-wide view).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.services.settings_service import get_low_stock_threshold
from app.services.stock_alerts import effective_threshold

VELOCITY_DAYS = 7


async def get_inventory(
    db: AsyncSession,
    *,
    reason: str | None = None,
    product_id: str | None = None,
    skip: int = 0,
    limit: int = 30,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)

    threshold = await get_low_stock_threshold(db)
    products = (await db.execute(select(Product).where(Product.is_active == True))).scalars().all()  # noqa: E712

    summary = {
        "active_products": len(products),
        "in_stock": sum(1 for p in products if (p.stock_quantity or 0) > effective_threshold(p, threshold)),
        "low_stock": sum(1 for p in products if 0 < (p.stock_quantity or 0) <= effective_threshold(p, threshold)),
        "out_of_stock": sum(1 for p in products if (p.stock_quantity or 0) <= 0),
        "units_on_hand": float(sum(max(p.stock_quantity or 0, 0) for p in products)),
        "stock_value": float(sum(max(p.stock_quantity or 0, 0) * (p.price or 0) for p in products)),
        # What the stock on hand cost us, for products with a cost price.
        "stock_cost_value": float(sum(
            max(p.stock_quantity or 0, 0) * p.cost_price for p in products if p.cost_price is not None
        )),
        "products_without_cost": sum(1 for p in products if p.cost_price is None),
        "low_stock_threshold": threshold,
    }

    # Net units that left through orders recently: order_placed rows are
    # negative, order_cancelled rows give them back.
    since = now - timedelta(days=VELOCITY_DAYS)
    sold_rows = await db.execute(
        select(StockMovement.product_id, -func.sum(StockMovement.change))
        .where(
            StockMovement.created_at >= since,
            StockMovement.reason.in_(("order_placed", "order_cancelled")),
        )
        .group_by(StockMovement.product_id)
    )
    sold = {pid: max(float(n or 0), 0.0) for pid, n in sold_rows.all()}

    needs_restock = []
    for p in products:
        stock = float(p.stock_quantity or 0)
        product_threshold = effective_threshold(p, threshold)
        if stock > product_threshold:
            continue
        per_day = sold.get(p.id, 0.0) / VELOCITY_DAYS
        needs_restock.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "image_url": p.image_url,
            "category": p.category,
            "price": float(p.price or 0),
            "stock_quantity": stock,
            "low_stock_threshold": product_threshold,
            "sold_last_7_days": sold.get(p.id, 0.0),
            "days_left": round(max(stock, 0) / per_day, 1) if per_day > 0 else None,
        })
    # Most urgent first: out of stock, then fastest to run out, then lowest.
    needs_restock.sort(key=lambda r: (
        r["stock_quantity"] > 0,
        r["days_left"] if r["days_left"] is not None else float("inf"),
        r["stock_quantity"],
    ))

    filters = []
    if reason:
        filters.append(StockMovement.reason == reason)
    if product_id:
        filters.append(StockMovement.product_id == product_id)

    total = (await db.execute(select(func.count(StockMovement.id)).where(*filters))).scalar_one()
    rows = await db.execute(
        select(StockMovement, Product.name, Product.slug, User.full_name, User.email)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(User, User.id == StockMovement.admin_id)
        .where(*filters)
        .order_by(StockMovement.created_at.desc(), StockMovement.id)
        .offset(skip)
        .limit(limit)
    )
    movements = [
        {
            "id": m.id,
            "product_id": m.product_id,
            "product_name": name,
            "product_slug": slug,
            "change": m.change,
            "previous_quantity": m.previous_quantity,
            "new_quantity": m.new_quantity,
            "reason": m.reason,
            "note": m.note,
            "order_id": m.order_id,
            "admin_name": (admin_name or (admin_email.split("@")[0] if admin_email else None)),
            "created_at": m.created_at,
        }
        for m, name, slug, admin_name, admin_email in rows.all()
    ]

    return {"summary": summary, "needs_restock": needs_restock, "movements": movements, "movements_total": total}
