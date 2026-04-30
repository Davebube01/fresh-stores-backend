from __future__ import annotations

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderItem
from app.models.delivery import Delivery
from app.schemas.order import OrderCreate

async def get_order(db: AsyncSession, order_id: str) -> Optional[Order]:
    result = await db.execute(
        select(Order).options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.delivery)
        ).where(Order.id == order_id)
    )
    return result.scalars().first()

async def get_user_orders(db: AsyncSession, user_id: str, skip: int = 0, limit: int = 100) -> List[Order]:
    query = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.delivery)
    ).where(Order.user_id == user_id).order_by(Order.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

async def create_order(db: AsyncSession, order_in: OrderCreate, user_id: Optional[str] = None, subtotal: float = 0.0, delivery_fee: float = 0.0, total_amount: float = 0.0) -> Order:
    db_order = Order(
        user_id=user_id,
        guest_info=order_in.guest_info.model_dump() if order_in.guest_info else None,
        payment_method=order_in.payment_method,
        delivery_method=order_in.delivery_method,
        subtotal=subtotal,
        delivery_fee=delivery_fee if order_in.delivery_method != "pickup" else 0.0,
        total_amount=subtotal + (delivery_fee if order_in.delivery_method != "pickup" else 0.0),
        status="pending"
    )
    db.add(db_order)
    await db.commit()
    await db.refresh(db_order)
    return db_order

async def create_order_item(db: AsyncSession, order_id: str, product_id: str, quantity: int, price_at_time: float, selected_option: Optional[str] = None):
    db_item = OrderItem(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        price_at_time=price_at_time,
        selected_option=selected_option
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
    if db_order:
        db_order.status = status
        await db.commit()
        await db.refresh(db_order)
    return db_order
