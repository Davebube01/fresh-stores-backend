from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, update
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.core.cache import clear_product_caches
from app.core.config import settings
from app.core.payment_window import payment_deadline
from app.crud.product import restore_stock
from app.models.order import Order, OrderItem
from app.models.delivery import Delivery
from app.schemas.order import OrderCreate, DispatchUpdate

async def get_order(db: AsyncSession, order_id: str) -> Optional[Order]:
    result = await db.execute(
        select(Order).options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.delivery)
        ).where(Order.id == order_id)
    )
    return result.scalars().first()

async def claim_guest_orders(db: AsyncSession, user_id: str, email: str) -> int:
    """
    Attach earlier guest orders placed with this email to a new account, so
    "My Orders" isn't empty for someone who checked out as a guest first.

    Only call this once the user has verified the email address (see the
    verify-email endpoint): otherwise anyone registering with someone else's
    email would inherit that person's guest orders — address, phone, PIN.
    """
    result = await db.execute(
        update(Order)
        .where(
            Order.user_id.is_(None),
            func.lower(Order.guest_info["email"].as_string()) == email.strip().lower(),
        )
        .values(user_id=user_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount


logger = logging.getLogger("orders")

# What the customer's Order History tabs mean. Ongoing includes unpaid orders
# (still waiting on payment or confirmation) — they're live, not finished.
ONGOING_STATUSES = ["pending", "awaiting_verification", "paid", "processing", "in_transit"]
UNPAID_STATUSES = ["pending", "awaiting_verification"]
ORDER_GROUPS = {
    "ongoing": ONGOING_STATUSES,
    "completed": ["delivered"],
    "cancelled": ["cancelled"],
}


async def get_user_orders(
    db: AsyncSession, user_id: str, skip: int = 0, limit: int = 100, group: str = "all"
) -> List[Order]:
    query = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.delivery)
    ).where(Order.user_id == user_id)
    if group in ORDER_GROUPS:
        query = query.where(Order.status.in_(ORDER_GROUPS[group]))
    query = query.order_by(Order.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def get_user_order_counts(db: AsyncSession, user_id: str) -> dict:
    result = await db.execute(
        select(Order.status, func.count()).where(Order.user_id == user_id).group_by(Order.status)
    )
    by_status = {getattr(status, "value", status): count for status, count in result.all()}

    counts = {group: sum(by_status.get(st, 0) for st in statuses) for group, statuses in ORDER_GROUPS.items()}
    counts["all"] = sum(by_status.values())
    return counts

async def create_order(db: AsyncSession, order_in: OrderCreate, user_id: Optional[str] = None, subtotal: float = 0.0, delivery_fee: float = 0.0, total_amount: float = 0.0) -> Order:
    # subtotal/delivery_fee/total_amount are trusted as given — the caller
    # (order_service.process_checkout) is the single place that computes
    # them, so this must not recompute or override its numbers.
    db_order = Order(
        user_id=user_id,
        guest_info=order_in.guest_info.model_dump() if order_in.guest_info else None,
        payment_method=order_in.payment_method,
        delivery_method=order_in.delivery_method,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total_amount=total_amount,
        status="pending"
    )
    db.add(db_order)
    await db.commit()
    await db.refresh(db_order)
    return db_order

async def create_order_item(db: AsyncSession, order_id: str, product_id: str, quantity: int, price_at_time: float, selected_option: Optional[str] = None, stock_units: float = 1.0, cost_at_time: Optional[float] = None):
    db_item = OrderItem(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        price_at_time=price_at_time,
        selected_option=selected_option,
        stock_units=stock_units,
        cost_at_time=cost_at_time,
    )
    db.add(db_item)
    await db.commit()

async def create_delivery(db: AsyncSession, order_id: str, delivery_info: dict):
    db_delivery = Delivery(
        order_id=order_id,
        **delivery_info
    )
    db.add(db_delivery)
    await db.commit()

async def update_order_status(db: AsyncSession, order_id: str, status: str) -> Optional[Order]:
    db_order = await get_order(db, order_id)
    if not db_order:
        return None

    # Delivery orders must be confirmed with the delivery PIN (see
    # confirm_delivery below), not just clicked through — that's the entire
    # point of having a PIN. Pickup orders are unaffected: there's no
    # courier to verify, the customer collects it in person.
    if status == "delivered" and db_order.delivery_method == "delivery" and db_order.delivery:
        raise ValueError("Delivery orders must be confirmed with the delivery PIN, not set directly.")

    # Cancelling records a reason and releases stock — see cancel_order.
    if status == "cancelled":
        raise ValueError("Use the cancel action for this: it records a reason for the customer.")

    # Cancelled and delivered are final. (Un-cancelling would put an order
    # back in play without re-reserving the stock that cancelling released.)
    current = getattr(db_order.status, "value", db_order.status)
    if current in ("cancelled", "delivered") and status != current:
        raise ValueError(f"A {current} order can't be changed.")

    db_order.status = status
    await db.commit()

    # Re-fetch rather than refresh(): refresh() expires the items/product
    # relationships already eager-loaded by get_order() above, and lazily
    # reloading them during response serialization fails outside the
    # request's async context (MissingGreenlet). Pre-existing bug, not
    # introduced here — surfaced by actually exercising this path.
    return await get_order(db, order_id)

async def cancel_order(
    db: AsyncSession,
    order_id: str,
    reason: str,
    cancelled_by: str,
    allowed_from: Optional[List[str]] = None,
) -> Optional[Order]:
    """
    Cancels an order, records why, and gives its reserved stock back.

    The status change is a single conditional UPDATE ("...WHERE status IN
    allowed"), so if a customer's cancel, an admin's cancel, the payment
    webhook and the expiry sweep race each other, exactly one wins — stock
    can't be returned twice, and an order that just got paid can't be
    cancelled out from under the payment.
    Returns None if the order doesn't exist; raises ValueError if it can't be
    cancelled (in its current state, or without a reason).
    """
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("Please give a reason for cancelling.")
    reason = reason[:300]

    db_order = await get_order(db, order_id)
    if not db_order:
        return None

    current = getattr(db_order.status, "value", db_order.status)
    if current == "cancelled":
        raise ValueError("This order is already cancelled.")
    if current == "delivered":
        raise ValueError("A delivered order can't be cancelled.")

    if allowed_from is None:
        allowed_from = [st for st in ONGOING_STATUSES]
    result = await db.execute(
        update(Order)
        .where(Order.id == order_id, Order.status.in_(allowed_from))
        .values(
            status="cancelled",
            cancellation_reason=reason,
            cancelled_by=cancelled_by,
            cancelled_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise ValueError("This order's status just changed, so it can't be cancelled here.")

    for item in db_order.items:
        await restore_stock(db, item.product_id, item.quantity * (item.stock_units or 1), order_id=order_id)
    await db.commit()
    clear_product_caches()

    db.expire_all()
    return await get_order(db, order_id)


async def expire_stale_unpaid_orders(db: AsyncSession, older_than: Optional[timedelta] = None) -> int:
    """
    Cancels online-payment orders nobody paid for, so abandoned checkouts
    stop holding stock. Cash-on-delivery orders are unpaid by design and are
    left alone. Returns how many were cancelled.
    """
    window = older_than or timedelta(minutes=settings.ORDER_PAYMENT_WINDOW_MINUTES)
    cap = timedelta(minutes=settings.ORDER_MAX_PAYMENT_HOLD_MINUTES)
    now = datetime.now(timezone.utc)

    # Same rule as core.payment_window.payment_deadline: idle for a full
    # window since the last payment attempt, or past the hard cap.
    result = await db.execute(
        select(Order.id).where(
            Order.status.in_(UNPAID_STATUSES),
            or_(Order.updated_at < now - window, Order.created_at < now - cap),
            or_(Order.payment_method.is_(None), Order.payment_method != "cod"),
        )
    )
    cancelled = 0
    for (order_id,) in result.all():
        try:
            await cancel_order(db, order_id, "Payment not completed", "system", allowed_from=UNPAID_STATUSES)
            cancelled += 1
        except ValueError:
            pass  # got paid or cancelled in the meantime — exactly what the guard is for
    if cancelled:
        logger.info("Auto-cancelled %d unpaid order(s) older than %s", cancelled, older_than)
    return cancelled


async def expire_if_overdue(db: AsyncSession, order: Order) -> Order:
    """
    If this order is past its payment deadline, cancel it right now instead of
    waiting for the next background sweep, so someone looking at it (or about
    to pay for it) never sees a dead order still marked as payable.
    """
    deadline = payment_deadline(order.status, order.payment_method, order.created_at, order.updated_at)
    if deadline is None or deadline > datetime.now(timezone.utc):
        return order
    try:
        return await cancel_order(db, order.id, "Payment not completed", "system", allowed_from=UNPAID_STATUSES) or order
    except ValueError:
        # Paid or cancelled by someone else in the meantime; show what it is now.
        return await get_order(db, order.id) or order


_last_expiry_sweep = 0.0


async def maybe_expire_stale_orders(db: AsyncSession) -> None:
    """Cheap on-demand sweep (at most once a minute) so a customer's list is never stale."""
    global _last_expiry_sweep
    now = time.monotonic()
    if now - _last_expiry_sweep < 60:
        return
    _last_expiry_sweep = now
    await expire_stale_unpaid_orders(db)


async def set_dispatch_info(db: AsyncSession, order_id: str, dispatch: DispatchUpdate) -> Optional[Order]:
    db_order = await get_order(db, order_id)
    if not db_order:
        return None

    if not db_order.delivery:
        # Pickup orders (or any order with no delivery record) have no
        # courier to assign — the customer collects it themselves.
        raise ValueError("This order has no delivery to dispatch")

    db_order.delivery.courier_name = dispatch.courier_name
    db_order.delivery.courier_phone = dispatch.courier_phone
    db_order.delivery.courier_service = dispatch.courier_service
    db_order.delivery.courier_reference = dispatch.courier_reference

    # Generate the delivery PIN once, the first time a courier is assigned —
    # re-dispatching (e.g. correcting a phone number) shouldn't invalidate a
    # PIN the customer may already have noted down.
    if not db_order.delivery.delivery_pin:
        db_order.delivery.delivery_pin = f"{random.randint(0, 9999):04d}"

    await db.commit()
    return await get_order(db, order_id)

async def confirm_delivery(db: AsyncSession, order_id: str, pin: str) -> Optional[Order]:
    db_order = await get_order(db, order_id)
    if not db_order:
        return None

    if not db_order.delivery or not db_order.delivery.delivery_pin:
        raise ValueError("This order has no delivery PIN to confirm against.")

    if db_order.delivery.delivery_pin != pin.strip():
        raise ValueError("Incorrect delivery PIN.")

    db_order.status = "delivered"
    await db.commit()
    return await get_order(db, order_id)
