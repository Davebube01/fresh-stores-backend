from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.order import Order, OrderItem
from app.schemas.order import OrderResponse
from app.utils.dependencies import get_current_active_superuser
from app.crud.order import get_order, update_order_status

router = APIRouter()

@router.get("/", response_model=List[OrderResponse])
async def get_admin_orders(
    skip: int = 0,
    limit: int = 100,
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
            status_code=status.HTTP_404_NOT_FOUND,
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
    valid_statuses = ["pending", "paid", "processing", "shipped", "delivered", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
        
    order = await update_order_status(db, id, status)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    return order
