from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.models.order import Order, OrderItem, OrderStatus
from app.schemas.order import OrderResponse, DispatchUpdate, ConfirmDeliveryRequest, CancelOrderRequest
from app.utils.dependencies import get_current_active_superuser
from app.crud.order import get_order, update_order_status, set_dispatch_info, confirm_delivery, cancel_order
from app.schemas.admin_orders import AdminOrderRow, OrderView, OrdersSummary
from app.services.admin_orders_service import (
    allowed_manual_moves, get_admin_order_row, list_admin_orders, orders_summary, status_value,
)

router = APIRouter()

@router.get("/", response_model=List[AdminOrderRow])
async def get_admin_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    view: OrderView = "all",
    search: Optional[str] = Query(None, max_length=100),
    method: Optional[Literal["delivery", "pickup"]] = None,
    zone: Optional[str] = Query(None, max_length=60),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sort: Literal["newest", "oldest"] = "newest",
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Orders for admin management, with the customer's name on each row.
    Search matches the order number, customer name/email/phone or payment reference.
    """
    return await list_admin_orders(
        db, view=view, search=search, method=method, zone=zone,
        date_from=date_from, date_to=date_to, sort=sort, skip=skip, limit=limit,
    )

@router.get("/summary", response_model=OrdersSummary)
async def get_admin_orders_summary(
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """Counts for each tab on the Orders page, and how many are past their slot."""
    return await orders_summary(db)

@router.get("/{id}", response_model=AdminOrderRow)
async def get_admin_order(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Get detailed order information, with the customer and the status moves
    currently allowed.
    """
    order = await get_admin_order_row(db, id)
    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    return order

@router.put("/{id}/status", response_model=OrderResponse)
async def update_admin_order_status(
    id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Update the status of an order.
    """
    valid_statuses = [s.value for s in OrderStatus]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )

    existing = await get_order(db, id)
    if not existing:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Order not found")
    current = status_value(existing)
    # Cancelling, and delivering with a PIN, are refused below with their own
    # explanations; everything else must be a move the rules allow.
    handled_below = status == "cancelled" or (status == "delivered" and existing.delivery is not None)
    if status != current and not handled_below and status not in allowed_manual_moves(existing):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"A {current.replace('_', ' ')} order can't be moved to {status.replace('_', ' ')} by hand.",
        )

    try:
        order = await update_order_status(db, id, status)
    except ValueError as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    return order

@router.put("/{id}/cancel", response_model=OrderResponse)
async def cancel_admin_order(
    id: str,
    payload: CancelOrderRequest,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Cancel an order. The reason is required and is shown to the customer.
    """
    try:
        order = await cancel_order(db, id, payload.reason, "admin")
    except ValueError as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not order:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order

@router.put("/{id}/confirm-delivery", response_model=OrderResponse)
async def confirm_admin_order_delivery(
    id: str,
    payload: ConfirmDeliveryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Mark a delivery order as delivered by entering the PIN the courier
    collected from the customer on handoff.
    """
    existing = await get_order(db, id)
    if existing and status_value(existing) != "in_transit":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Only an order that's out for delivery can be confirmed as delivered.",
        )
    try:
        order = await confirm_delivery(db, id, payload.pin)
    except ValueError as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    return order

@router.put("/{id}/dispatch", response_model=OrderResponse)
async def dispatch_admin_order(
    id: str,
    dispatch: DispatchUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Assign a courier to a delivery order — who's carrying it, and how to
    reach them. Pickup orders have nothing to dispatch.
    """
    existing = await get_order(db, id)
    if not existing:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Order not found")
    # Paid/being prepared, or already out (correcting the courier's details).
    # A cash-on-delivery order must be accepted (processing) first.
    if status_value(existing) not in ("paid", "processing", "in_transit"):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"A {status_value(existing).replace('_', ' ')} order can't be dispatched.",
        )
    try:
        order = await set_dispatch_info(db, id, dispatch)
    except ValueError as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))
    if order and status_value(order) != "in_transit":
        # Handing it to a courier is what puts it on the road.
        order = await update_order_status(db, id, "in_transit")
    return order
