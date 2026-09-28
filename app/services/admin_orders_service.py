"""
Listing, filtering and counting orders for the admin Orders page, plus the
rules for which status moves an admin may make by hand.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.delivery_zones import zone_name
from app.models.delivery import Delivery
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User

WAT = timezone(timedelta(hours=1))
S = OrderStatus

# Walk-in (counter) sales live on the Sales page, not here.
ONLINE = "online"

_COD_PENDING = and_(Order.status == S.PENDING, Order.payment_method == "cod")

VIEW_FILTERS = {
    "all": None,
    "needs_action": or_(Order.status.in_([S.PAID, S.PROCESSING]), _COD_PENDING),
    # Online orders still waiting for payment (COD "pending" means accepted).
    "unpaid": and_(Order.status.in_([S.PENDING, S.AWAITING_VERIFICATION]), ~_COD_PENDING),
    "paid": Order.status == S.PAID,
    "processing": Order.status == S.PROCESSING,
    "in_transit": Order.status == S.IN_TRANSIT,
    "delivered": Order.status == S.DELIVERED,
    "cancelled": Order.status == S.CANCELLED,
}


def status_value(order: Order) -> str:
    return getattr(order.status, "value", order.status)


def allowed_manual_moves(order: Order) -> set[str]:
    """
    Status changes an admin may make directly via PUT /status. Dispatch,
    PIN confirmation and cancelling have their own endpoints and checks.
    """
    current = status_value(order)
    pickup = order.delivery is None
    cod = order.payment_method == "cod"
    moves: dict[str, set[str]] = {
        # Online orders are only ever marked paid by Paystack.
        "pending": {"processing"} if cod else set(),
        "awaiting_verification": set(),
        "paid": {"processing"},
        # Delivery orders go out via dispatch (courier + PIN) instead.
        "processing": {"in_transit"} if pickup else set(),
        # Pickup: collected in person. Either kind can be taken back to processing.
        "in_transit": {"delivered", "processing"} if pickup else {"processing"},
        "delivered": set(),
        "cancelled": set(),
    }
    return moves.get(current, set())


def _slot_end(d: Delivery | None) -> Optional[datetime]:
    if not d or not d.delivery_date or not d.time_slot:
        return None
    try:
        raw = datetime.fromisoformat(d.delivery_date.replace("Z", "+00:00"))
        day = raw.astimezone(WAT).date() if raw.tzinfo else raw.date()
        end = d.time_slot.split("-")[1].strip()
        return datetime.combine(day, time.fromisoformat(end), WAT)
    except (ValueError, IndexError):
        return None


def _is_overdue(order: Order, now: datetime) -> bool:
    if status_value(order) not in ("paid", "processing") and not (
        status_value(order) == "pending" and order.payment_method == "cod"
    ):
        return False
    end = _slot_end(order.delivery)
    return end is not None and now >= end


def to_row(order: Order, now: Optional[datetime] = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(WAT)
    guest = order.guest_info or {}
    user = order.user
    return {
        **{c: getattr(order, c) for c in (
            "id", "user_id", "guest_info", "payment_method", "payment_reference", "subtotal", "delivery_fee",
            "total_amount", "items", "delivery", "created_at", "updated_at", "paid_at",
            "cancellation_reason", "cancelled_by", "cancelled_at",
            "channel", "discount_amount", "discount_note",
        )},
        "status": status_value(order),
        "delivery_method": getattr(order.delivery_method, "value", order.delivery_method) or "delivery",
        "customer_name": (user.full_name or user.email.split("@")[0]) if user else (guest.get("fullName") or guest.get("email") or "Guest"),
        "customer_email": user.email if user else guest.get("email"),
        "customer_phone": (user.phone if user else None) or guest.get("phone"),
        "is_guest": user is None,
        "overdue": _is_overdue(order, now),
        "delivery_zone_name": zone_name(order.delivery.delivery_zone) if order.delivery else None,
        "allowed_moves": sorted(allowed_manual_moves(order)),
    }


def _options():
    return (
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.delivery),
        selectinload(Order.user),
    )


async def get_admin_order_row(db: AsyncSession, order_id: str) -> Optional[dict]:
    order = (await db.execute(select(Order).options(*_options()).where(Order.id == order_id))).scalar_one_or_none()
    return to_row(order) if order else None


async def list_admin_orders(
    db: AsyncSession,
    *,
    view: str = "all",
    search: Optional[str] = None,
    method: Optional[Literal["delivery", "pickup"]] = None,
    zone: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sort: Literal["newest", "oldest"] = "newest",
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    query = (
        select(Order)
        .options(*_options())
        .outerjoin(User, User.id == Order.user_id)
        .outerjoin(Delivery, Delivery.order_id == Order.id)
        .where(Order.channel == ONLINE)
    )
    if VIEW_FILTERS.get(view) is not None:
        query = query.where(VIEW_FILTERS[view])
    if method:
        query = query.where(Order.delivery_method == method)
    if zone:
        query = query.where(Delivery.delivery_zone == zone)
    if date_from:
        query = query.where(Order.created_at >= datetime.combine(date_from, time.min, WAT).astimezone(timezone.utc))
    if date_to:
        query = query.where(Order.created_at < datetime.combine(date_to + timedelta(days=1), time.min, WAT).astimezone(timezone.utc))
    if search and search.strip():
        q = search.strip().lstrip("#").lower()
        term = f"%{q}%"
        query = query.where(or_(
            Order.id.ilike(f"{q}%"),
            User.full_name.ilike(term),
            User.email.ilike(term),
            User.phone.ilike(term),
            Order.guest_info["fullName"].as_string().ilike(term),
            Order.guest_info["email"].as_string().ilike(term),
            Order.guest_info["phone"].as_string().ilike(term),
            Order.payment_reference.ilike(term),
        ))

    query = query.order_by(Order.created_at.asc() if sort == "oldest" else Order.created_at.desc()).offset(skip).limit(limit)
    orders = (await db.execute(query)).scalars().unique().all()
    now = datetime.now(timezone.utc)
    return [to_row(o, now) for o in orders]


async def orders_summary(db: AsyncSession) -> dict:
    counts = {}
    for view, cond in VIEW_FILTERS.items():
        q = select(func.count(Order.id)).where(Order.channel == ONLINE)
        if cond is not None:
            q = q.where(cond)
        counts[view] = (await db.execute(q)).scalar_one()

    waiting = (await db.execute(
        select(Order).options(selectinload(Order.delivery)).where(VIEW_FILTERS["needs_action"])
    )).scalars().all()
    now = datetime.now(timezone.utc).astimezone(WAT)
    return {"counts": counts, "overdue": sum(1 for o in waiting if _is_overdue(o, now))}
