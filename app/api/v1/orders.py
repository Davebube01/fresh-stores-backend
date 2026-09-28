from __future__ import annotations

import re

from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.order import Order
from app.core.pagination import MAX_PAGE_SIZE
from app.schemas.order import CancelOrderRequest, OrderCreate, OrderResponse, OrderSummary
from app.crud.order import (
    UNPAID_STATUSES,
    cancel_order,
    expire_if_overdue,
    get_order,
    get_user_order_counts,
    get_user_orders,
    maybe_expire_stale_orders,
)
from app.services.order_service import process_checkout
from app.services.email_service import send_order_confirmation
from app.utils.dependencies import get_current_user, get_optional_current_user
from app.models.user import User

router = APIRouter()

@router.post("/checkout", response_model=OrderResponse)
async def checkout(
    order_in: OrderCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    user_id = current_user.id if current_user else None
    try:
        order = await process_checkout(db, order_in, user_id=user_id)
        
        # Fire email if we have contact info
        recipient_email = current_user.email if current_user else (
            order.guest_info.get("email") if isinstance(order.guest_info, dict) else None
        )
        if recipient_email:
            tracking_url = f"{settings.FRONTEND_URL}/order-tracking?id={order.id}"
            background_tasks.add_task(
                send_order_confirmation,
                email=recipient_email,
                order_id=order.id,
                total_amount=order.total_amount,
                tracking_url=tracking_url
            )
            
        return order
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# Guests look orders up by number + email, so keep guessing slow.
TRACK_LIMIT = "20/minute"


def _order_email(order: Order, user_email: Optional[str]) -> str:
    if order.user_id:
        return (user_email or "").lower()
    info = order.guest_info if isinstance(order.guest_info, dict) else {}
    return str(info.get("email", "")).lower()


@router.get("/track", response_model=OrderResponse)
@limiter.limit(TRACK_LIMIT)
async def track_public_order(
    request: Request,
    email: str = Query(..., max_length=254),
    order_number: str = Query(..., max_length=64),
    db: AsyncSession = Depends(get_db),
):
    """
    Public order lookup for guests: the order number plus the email it was
    placed with. Accepts the full order ID or the short number customers see
    (e.g. "#1A2B3C4D", the first 8 characters). Every mismatch answers the
    same 404, so it doesn't reveal which orders exist.
    """
    not_found = HTTPException(status_code=404, detail="Order not found or invalid credentials")
    number = order_number.strip().lstrip("#").lower()
    email = email.strip().lower()
    # Hex and hyphens only: also keeps LIKE wildcards (% _) out of the prefix match.
    if len(number) < 8 or not email or not re.fullmatch(r"[0-9a-f-]+", number):
        raise not_found

    rows = (await db.execute(
        select(Order.id, User.email)
        .outerjoin(User, User.id == Order.user_id)
        .where(Order.id.like(f"{number}%") if len(number) < 36 else Order.id == number)
        .limit(20)
    )).all()
    matches = []
    for order_id, user_email in rows:
        order = await get_order(db, order_id)
        if order and _order_email(order, user_email) == email:
            matches.append(order)
    # A short number shared by two of this person's orders is ambiguous.
    if len(matches) != 1:
        raise not_found
    return await expire_if_overdue(db, matches[0])

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    order = await get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Orders placed by a registered user may only be viewed by that user.
    # Guest orders (user_id is None) remain reachable by ID, since that's
    # how the anonymous post-checkout payment-status polling works.
    if order.user_id and (not current_user or current_user.id != order.user_id):
        raise HTTPException(status_code=404, detail="Order not found")

    return await expire_if_overdue(db, order)

@router.get("/me/orders", response_model=List[OrderResponse])
async def read_my_orders(
    group: Literal["all", "ongoing", "completed", "cancelled"] = "all",
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await maybe_expire_stale_orders(db)
    return await get_user_orders(db, current_user.id, skip=skip, limit=limit, group=group)


@router.get("/me/summary", response_model=OrderSummary)
async def read_my_order_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """How many orders are in each Order History tab."""
    await maybe_expire_stale_orders(db)
    return await get_user_order_counts(db, current_user.id)


# Why an order can't be cancelled online, by its current status.
_NOT_CANCELLABLE = {
    "paid": "This order has already been paid for. Please contact us to cancel it.",
    "processing": "We're already preparing this order. Please contact us to cancel it.",
    "in_transit": "This order is already on its way, so it can't be cancelled online. Please contact us.",
    "delivered": "This order has already been delivered.",
    "cancelled": "This order is already cancelled.",
}


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_my_order(
    order_id: str,
    body: CancelOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Customers can cancel their own order until it's paid for / being prepared.
    After that a person has to step in (refunds are handled manually).
    """
    order = await get_order(db, order_id)
    # Same answer for "doesn't exist" and "isn't yours".
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Order not found")

    status = getattr(order.status, "value", order.status)
    if status not in UNPAID_STATUSES:
        raise HTTPException(status_code=400, detail=_NOT_CANCELLABLE.get(status, "This order can't be cancelled online."))

    try:
        return await cancel_order(db, order_id, body.reason, "customer", allowed_from=UNPAID_STATUSES)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
