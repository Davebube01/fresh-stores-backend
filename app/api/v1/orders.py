from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.order import OrderCreate, OrderResponse
from app.crud.order import get_order, get_user_orders
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
            tracking_url = f"http://localhost:3000/order-tracking?id={order.id}"
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

@router.get("/track", response_model=OrderResponse)
async def track_public_order(
    email: str,
    order_number: str,
    db: AsyncSession = Depends(get_db)
):
    order = await get_order(db, order_number)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    is_authorized = False
    
    # Check registered user
    if order.user_id:
        from app.crud.user import get_user
        user = await get_user(db, order.user_id)
        if user and user.email.lower() == email.lower():
            is_authorized = True
            
    # Check guest
    elif order.guest_info:
        g_info = order.guest_info
        if isinstance(g_info, dict) and g_info.get("email", "").lower() == email.lower():
            is_authorized = True
            
    if not is_authorized:
        raise HTTPException(status_code=404, detail="Order not found or invalid credentials")
        
    return order

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.get("/me/orders", response_model=List[OrderResponse])
async def read_my_orders(
    skip: int = 0, limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    orders = await get_user_orders(db, current_user.id, skip=skip, limit=limit)
    return orders

from pydantic import BaseModel
class OrderStatusUpdate(BaseModel):
    status: str

@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    status_update: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    order = await get_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    order.status = status_update.status
    await db.commit()
    await db.refresh(order)
    return order

