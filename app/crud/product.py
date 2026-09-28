from __future__ import annotations

from typing import List, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, update
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.schemas.product import ProductCreate, ProductUpdate

async def get_product(db: AsyncSession, product_id: str) -> Optional[Product]:
    result = await db.execute(select(Product).where(Product.id == product_id))
    return result.scalars().first()

async def get_products(db: AsyncSession, skip: int = 0, limit: int = 100, search: Optional[str] = None) -> List[Product]:
    query = select(Product).where(Product.is_active == True)
    if search:
        query = query.where(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.description.ilike(f"%{search}%")
            )
        )
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

async def get_admin_products(db: AsyncSession, skip: int = 0, limit: int = 100, search: Optional[str] = None) -> List[Product]:
    query = select(Product)
    if search:
        query = query.where(
            or_(
                Product.name.ilike(f"%{search}%"),
                Product.description.ilike(f"%{search}%")
            )
        )
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

def _from_price(weight_options: list[dict]) -> Optional[float]:
    """A product with sizes is listed at its cheapest one ("from ₦X")."""
    return min(o["price"] for o in weight_options) if weight_options else None

async def create_product(db: AsyncSession, product: ProductCreate) -> Product:
    data = product.model_dump()
    data["price"] = _from_price(data["weight_options"]) or data["price"]
    db_product = Product(**data)
    db.add(db_product)
    await db.commit()
    await db.refresh(db_product)

    if db_product.stock_quantity:
        db.add(StockMovement(
            product_id=db_product.id,
            change=db_product.stock_quantity,
            previous_quantity=0,
            new_quantity=db_product.stock_quantity,
            reason="initial_stock",
        ))
        await db.commit()

    return db_product

async def update_product(db: AsyncSession, product_id: str, product_update: ProductUpdate) -> Optional[Product]:
    db_product = await get_product(db, product_id)
    if db_product:
        update_data = product_update.model_dump(exclude_unset=True)
        if update_data.get("weight_options"):
            update_data["price"] = _from_price(update_data["weight_options"])
        for key, value in update_data.items():
            setattr(db_product, key, value)
        await db.commit()
        await db.refresh(db_product)
    return db_product

async def _apply_stock_change(
    db: AsyncSession,
    product_id: str,
    delta: float,
    *,
    reason: str,
    order_id: Optional[str] = None,
    admin_id: Optional[str] = None,
    note: Optional[str] = None,
    require_sufficient: bool = False,
) -> Optional[StockMovement]:
    """
    Atomically applies `delta` (positive to add stock, negative to remove)
    and records the before/after snapshot as a StockMovement, in a single
    round trip via RETURNING — so the audit row always matches what
    actually landed even under concurrent writers, and there's no separate
    read that could race with another change.

    Does NOT commit; callers control the transaction. Returns None if the
    product doesn't exist, or if require_sufficient=True and applying delta
    would take stock below zero.
    """
    query = (
        update(Product)
        .where(Product.id == product_id)
        .values(stock_quantity=Product.stock_quantity + delta)
    )
    if require_sufficient:
        query = query.where(Product.stock_quantity + delta >= 0)
    query = query.returning(Product.stock_quantity)

    result = await db.execute(query)
    row = result.first()
    if row is None:
        return None

    new_quantity = row[0]
    movement = StockMovement(
        product_id=product_id,
        change=delta,
        previous_quantity=new_quantity - delta,
        new_quantity=new_quantity,
        reason=reason,
        order_id=order_id,
        admin_id=admin_id,
        note=note,
    )
    db.add(movement)
    return movement


async def decrement_stock(db: AsyncSession, product_id: str, quantity: float, *, order_id: str) -> bool:
    """
    Reserve stock for a newly placed order, refusing if there isn't enough.
    Does NOT commit; the caller controls the transaction so a failed item
    partway through a multi-item checkout can be rolled back cleanly.
    """
    movement = await _apply_stock_change(
        db, product_id, -quantity, reason="order_placed", order_id=order_id, require_sufficient=True
    )
    return movement is not None


async def restore_stock(db: AsyncSession, product_id: str, quantity: float, *, order_id: str) -> None:
    """Give stock back (order cancelled after it was reserved). Does not commit."""
    await _apply_stock_change(db, product_id, quantity, reason="order_cancelled", order_id=order_id)


async def adjust_stock(
    db: AsyncSession,
    product_id: str,
    delta: float,
    *,
    admin_id: str,
    reason: str,
    note: Optional[str] = None,
) -> Optional[Product]:
    """
    Manual admin stock change (restock or correction) — commits on its own
    since, unlike checkout/cancellation, it isn't part of a larger batch.
    Returns None if the product doesn't exist, or if a negative delta would
    take stock below zero.
    """
    movement = await _apply_stock_change(
        db, product_id, delta, reason=reason, admin_id=admin_id, note=note, require_sufficient=delta < 0
    )
    if movement is None:
        return None
    await db.commit()
    return await get_product(db, product_id)


async def get_stock_movements(
    db: AsyncSession, product_id: str, skip: int = 0, limit: int = 100
) -> List[StockMovement]:
    result = await db.execute(
        select(StockMovement)
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def delete_product(db: AsyncSession, product_id: str) -> bool:
    db_product = await get_product(db, product_id)
    if not db_product:
        return False
    await db.delete(db_product)
    try:
        await db.commit()
    except IntegrityError:
        # Product has order items and/or stock movements referencing it —
        # deleting it would either break past orders or silently erase the
        # stock audit trail, so it's kept (deactivate via is_active instead).
        await db.rollback()
        raise ValueError("Can't delete a product that has order or stock history. Deactivate it instead.")
    return True
