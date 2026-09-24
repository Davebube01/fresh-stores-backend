from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.cart import Cart, CartItem
from app.schemas.cart import CartItemCreate

async def get_cart(db: AsyncSession, cart_id: str) -> Optional[Cart]:
    result = await db.execute(
        select(Cart).options(
            selectinload(Cart.items).selectinload(CartItem.product)
        ).where(Cart.id == cart_id)
    )
    return result.scalars().first()

async def get_cart_by_user(db: AsyncSession, user_id: str) -> Optional[Cart]:
    result = await db.execute(
        select(Cart).options(
            selectinload(Cart.items).selectinload(CartItem.product)
        ).where(Cart.user_id == user_id)
    )
    return result.scalars().first()

async def get_cart_by_session(db: AsyncSession, session_id: str) -> Optional[Cart]:
    result = await db.execute(
        select(Cart).options(
            selectinload(Cart.items).selectinload(CartItem.product)
        ).where(Cart.session_id == session_id)
    )
    return result.scalars().first()

async def create_cart(db: AsyncSession, user_id: Optional[str] = None, session_id: Optional[str] = None) -> Cart:
    db_cart = Cart(user_id=user_id, session_id=session_id)
    db.add(db_cart)
    await db.commit()
    await db.refresh(db_cart)
    # Refresh with relations loaded
    return await get_cart(db, db_cart.id)

async def add_cart_item(db: AsyncSession, cart_id: str, item: CartItemCreate) -> CartItem:
    # Check if item exists in cart already
    result = await db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart_id,
            CartItem.product_id == item.product_id,
            CartItem.selected_option == item.selected_option
        )
    )
    db_item = result.scalars().first()

    if db_item:
        db_item.quantity += item.quantity
    else:
        db_item = CartItem(
            cart_id=cart_id,
            product_id=item.product_id,
            quantity=item.quantity,
            selected_option=item.selected_option
        )
        db.add(db_item)

    await db.commit()

    # Re-fetch with the product relationship eager-loaded: CartItemResponse
    # requires `product`, and lazy-loading it after the session dependency
    # closes (during response serialization) raises MissingGreenlet.
    result = await db.execute(
        select(CartItem).options(selectinload(CartItem.product)).where(CartItem.id == db_item.id)
    )
    return result.scalars().one()

async def update_cart_item(db: AsyncSession, item_id: str, quantity: int) -> Optional[CartItem]:
    result = await db.execute(select(CartItem).where(CartItem.id == item_id))
    db_item = result.scalars().first()
    if not db_item:
        return None

    if quantity <= 0:
        await db.delete(db_item)
        await db.commit()
        return None

    db_item.quantity = quantity
    await db.commit()

    # Re-fetch with the product relationship eager-loaded (see add_cart_item).
    result = await db.execute(
        select(CartItem).options(selectinload(CartItem.product)).where(CartItem.id == item_id)
    )
    return result.scalars().one()

async def remove_cart_item(db: AsyncSession, item_id: str):
    result = await db.execute(select(CartItem).where(CartItem.id == item_id))
    db_item = result.scalars().first()
    if db_item:
        await db.delete(db_item)
        await db.commit()
