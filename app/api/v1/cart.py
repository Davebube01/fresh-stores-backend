from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.crud.cart import get_cart, get_cart_by_session, create_cart, add_cart_item, update_cart_item, remove_cart_item
from app.schemas.cart import CartResponse, CartItemCreate, CartItemUpdate, CartItemResponse
from app.models.user import User
from app.utils.dependencies import get_current_user
import uuid

router = APIRouter()

async def get_or_create_cart(
    response: Response,
    db: AsyncSession,
    session_id: Optional[str] = Cookie(None),
    current_user: Optional[User] = None
):
    if current_user:
        # Just creating a new cart if not exists, but ideally user has one active cart
        # Simplified: one active cart per user or session
        from app.crud.cart import get_cart_by_user
        cart = await get_cart_by_user(db, current_user.id)
        if not cart:
            cart = await create_cart(db, user_id=current_user.id)
        return cart

    # Guest user
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(key="session_id", value=session_id, httponly=True)
    
    cart = await get_cart_by_session(db, session_id)
    if not cart:
        cart = await create_cart(db, session_id=session_id)
    return cart

@router.get("/", response_model=CartResponse)
async def read_cart(
    response: Response,
    session_id: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
    # Let's make user optional for this endpoint
    # current_user = Depends(get_current_user) # we can't strict inject it, otherwise guests fail
):
    # For now, relying strictly on session for simplicity if no user
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(key="session_id", value=session_id, httponly=True)
        cart = await create_cart(db, session_id=session_id)
        return cart
        
    cart = await get_cart_by_session(db, session_id)
    if not cart:
        cart = await create_cart(db, session_id=session_id)
    return cart

@router.post("/items", response_model=CartItemResponse)
async def add_item_to_cart(
    item_in: CartItemCreate,
    response: Response,
    session_id: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db)
):
    cart = await get_or_create_cart(response, db, session_id)
    return await add_cart_item(db, cart.id, item_in)

@router.patch("/items/{item_id}", response_model=CartItemResponse)
async def update_item_quantity(
    item_id: str,
    item_update: CartItemUpdate,
    db: AsyncSession = Depends(get_db)
):
    item = await update_cart_item(db, item_id, item_update.quantity)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found or removed")
    return item

@router.delete("/items/{item_id}")
async def remove_item_from_cart(item_id: str, db: AsyncSession = Depends(get_db)):
    await remove_cart_item(db, item_id)
    return {"ok": True}
