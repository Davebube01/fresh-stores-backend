from __future__ import annotations

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from app.models.product import Product
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

async def create_product(db: AsyncSession, product: ProductCreate) -> Product:
    db_product = Product(**product.model_dump())
    db.add(db_product)
    await db.commit()
    await db.refresh(db_product)
    return db_product

async def update_product(db: AsyncSession, product_id: str, product_update: ProductUpdate) -> Optional[Product]:
    db_product = await get_product(db, product_id)
    if db_product:
        update_data = product_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_product, key, value)
        await db.commit()
        await db.refresh(db_product)
    return db_product

async def delete_product(db: AsyncSession, product_id: str) -> bool:
    db_product = await get_product(db, product_id)
    if not db_product:
        return False
    await db.delete(db_product)
    await db.commit()
    return True
