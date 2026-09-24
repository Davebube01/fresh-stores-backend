from __future__ import annotations

from typing import List
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

router = APIRouter()

@router.get("/", response_model=List[OrderResponse])
async def get_admin_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Get all orders for admin management.
    """
    query = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.delivery)
    ).order_by(Order.created_at.desc()).offset(skip).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{id}", response_model=OrderResponse)
async def get_admin_order(
    id: str,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser)
):
    """
    Get detailed order information.
    """
    order = await get_order(db, id)
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
    try:
        order = await set_dispatch_info(db, id, dispatch)
    except ValueError as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))

    if not order:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    return order
