from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.delivery_zones import zone_name
from app.crud.refresh_token import revoke_all_user_sessions
from app.models.delivery import Delivery
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User

CustomerSort = Literal["recent", "spent", "orders", "name", "last_order"]

WAT = timezone(timedelta(hours=1))

# Money actually taken — the same rule the dashboard uses: paid online, or a
# cash-on-delivery order that has been delivered. Never cancelled orders.
MONEY_TAKEN = and_(
    Order.status != OrderStatus.CANCELLED,
    or_(
        Order.paid_at.isnot(None),
        and_(Order.payment_method == "cod", Order.status == OrderStatus.DELIVERED),
    ),
)


def _order_stats_subquery():
    """Per-user order stats in one pass, to LEFT JOIN onto users (no N+1)."""
    return (
        select(
            Order.user_id.label("user_id"),
            func.sum(case((Order.status != OrderStatus.CANCELLED, 1), else_=0)).label("orders_count"),
            func.sum(case((MONEY_TAKEN, 1), else_=0)).label("paid_orders"),
            func.coalesce(func.sum(case((MONEY_TAKEN, Order.total_amount), else_=0.0)), 0.0).label("total_spent"),
            func.max(Order.created_at).label("last_order_at"),
        )
        .where(Order.user_id.isnot(None))
        .group_by(Order.user_id)
        .subquery()
    )


def _row(user: User, orders_count, paid_orders, total_spent, last_order_at) -> dict:
    return {
        "id": user.id,
        "name": user.full_name or user.email.split("@")[0],
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar_url,
        "address": user.address,
        "joinDate": user.created_at,
        "ordersCount": int(orders_count or 0),
        "totalSpent": float(total_spent or 0.0),
        "status": "active" if user.is_active else "inactive",
        "email_verified": bool(user.email_verified),
        "paid_orders": int(paid_orders or 0),
        "last_order_at": last_order_at,
    }


async def get_admin_customers(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    status: Optional[Literal["active", "inactive"]] = None,
    sort: CustomerSort = "recent",
):
    stats = _order_stats_subquery()
    orders_count = func.coalesce(stats.c.orders_count, 0)
    paid_orders = func.coalesce(stats.c.paid_orders, 0)
    total_spent = func.coalesce(stats.c.total_spent, 0.0)

    query = (
        select(User, orders_count, paid_orders, total_spent, stats.c.last_order_at)
        .outerjoin(stats, stats.c.user_id == User.id)
        .where(User.is_superuser == False)  # noqa: E712
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(or_(User.full_name.ilike(term), User.email.ilike(term), User.phone.ilike(term)))
    if status == "active":
        query = query.where(User.is_active == True)  # noqa: E712
    elif status == "inactive":
        query = query.where(User.is_active == False)  # noqa: E712

    order_by = {
        "recent": [User.created_at.desc()],
        "spent": [total_spent.desc(), User.created_at.desc()],
        "orders": [orders_count.desc(), User.created_at.desc()],
        "name": [func.lower(func.coalesce(User.full_name, User.email)).asc()],
        # Customers who never ordered go last.
        "last_order": [stats.c.last_order_at.is_(None), stats.c.last_order_at.desc()],
    }[sort]

    result = await db.execute(query.order_by(*order_by).offset(skip).limit(limit))
    return [_row(*r) for r in result.all()]


async def get_customers_summary(db: AsyncSession, now: Optional[datetime] = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(WAT)
    month_start = datetime.combine(now.date().replace(day=1), time.min, WAT).astimezone(timezone.utc)
    last_30 = (now - timedelta(days=30)).astimezone(timezone.utc)

    customers = select(User.id).where(User.is_superuser == False)  # noqa: E712
    total = (await db.execute(select(func.count()).select_from(customers.subquery()))).scalar_one()
    new = (await db.execute(select(func.count(User.id)).where(User.is_superuser == False, User.created_at >= month_start))).scalar_one()  # noqa: E712
    verified = (await db.execute(select(func.count(User.id)).where(User.is_superuser == False, User.email_verified == True))).scalar_one()  # noqa: E712

    active = (await db.execute(
        select(func.count(func.distinct(Order.user_id)))
        .join(User, User.id == Order.user_id)
        .where(User.is_superuser == False, Order.created_at >= last_30)  # noqa: E712
    )).scalar_one()

    paid_per_user = (
        select(Order.user_id, func.count(Order.id).label("n"))
        .join(User, User.id == Order.user_id)
        .where(User.is_superuser == False, MONEY_TAKEN)  # noqa: E712
        .group_by(Order.user_id)
        .subquery()
    )
    repeat = (await db.execute(select(func.count()).select_from(paid_per_user).where(paid_per_user.c.n >= 2))).scalar_one()

    guest_email = func.lower(Order.guest_info["email"].as_string())
    guests = (await db.execute(
        select(func.count(func.distinct(guest_email))).where(Order.user_id.is_(None), Order.guest_info.isnot(None))
    )).scalar_one()

    return {
        "total_customers": total,
        "new_this_month": new,
        "active_last_30_days": active,
        "repeat_customers": repeat,
        "verified": verified,
        "guest_customers": guests,
    }


async def get_admin_customer_by_id(db: AsyncSession, customer_id: str):
    user = (await db.execute(select(User).where(User.id == customer_id))).scalar_one_or_none()
    if not user:
        return None

    stats = _order_stats_subquery()
    row = (await db.execute(
        select(stats.c.orders_count, stats.c.paid_orders, stats.c.total_spent, stats.c.last_order_at)
        .where(stats.c.user_id == user.id)
    )).first()
    orders_count, paid_orders, total_spent, last_order_at = row if row else (0, 0, 0.0, None)
    base = _row(user, orders_count, paid_orders, total_spent, last_order_at)

    extra = (await db.execute(
        select(
            func.sum(case((Order.status == OrderStatus.CANCELLED, 1), else_=0)),
            func.min(Order.created_at),
        ).where(Order.user_id == user.id)
    )).first()

    recent = (await db.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.delivery))
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(20)
    )).scalars().all()

    favourites = (await db.execute(
        select(
            OrderItem.product_id, Product.name, Product.slug, Product.image_url,
            func.sum(OrderItem.quantity), func.count(func.distinct(OrderItem.order_id)),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.user_id == user.id, MONEY_TAKEN)
        .group_by(OrderItem.product_id, Product.name, Product.slug, Product.image_url)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
    )).all()

    addresses = (await db.execute(
        select(Delivery.address, Delivery.delivery_zone, func.count(Delivery.id), func.max(Order.created_at))
        .join(Order, Order.id == Delivery.order_id)
        .where(Order.user_id == user.id)
        .group_by(Delivery.address, Delivery.delivery_zone)
        .order_by(func.max(Order.created_at).desc())
        .limit(5)
    )).all()

    paid = base["paid_orders"]
    return {
        **base,
        "cancelled_orders": int(extra[0] or 0) if extra else 0,
        "first_order_at": extra[1] if extra else None,
        "avg_order_value": base["totalSpent"] / paid if paid else 0.0,
        "recent_orders": [
            {
                "id": o.id,
                "status": getattr(o.status, "value", o.status),
                "total_amount": o.total_amount,
                "created_at": o.created_at,
                "items": [{"id": i.id, "quantity": i.quantity} for i in o.items],
                "delivery_method": getattr(o.delivery_method, "value", o.delivery_method),
                "payment_method": o.payment_method,
                "delivery_zone": zone_name(o.delivery.delivery_zone) if o.delivery else None,
            }
            for o in recent
        ],
        "favourites": [
            {"product_id": pid, "name": name, "slug": slug, "image_url": img, "units": float(units or 0), "times_ordered": int(times or 0)}
            for pid, name, slug, img, units, times in favourites
        ],
        "addresses": [
            {"address": addr, "zone": zone_name(zone), "times_used": int(n), "last_used": last}
            for addr, zone, n, last in addresses
        ],
    }


async def set_customer_active(db: AsyncSession, customer_id: str, is_active: bool) -> Optional[User]:
    """Deactivating blocks sign-in and ends the customer's existing sessions."""
    user = (await db.execute(
        select(User).where(User.id == customer_id, User.is_superuser == False)  # noqa: E712
    )).scalar_one_or_none()
    if not user:
        return None
    user.is_active = is_active
    await db.commit()
    if not is_active:
        await revoke_all_user_sessions(db, user.id)
    await db.refresh(user)
    return user
