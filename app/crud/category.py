from __future__ import annotations

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate

async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Category]:
    result = await db.execute(select(Category).where(Category.is_active == True).offset(skip).limit(limit))
    return result.scalars().all()

async def get_all_categories(db: AsyncSession) -> List[Category]:
    result = await db.execute(select(Category))
    return result.scalars().all()

async def get_category(db: AsyncSession, category_id: str) -> Optional[Category]:
    result = await db.execute(select(Category).where(Category.id == category_id))
    return result.scalars().first()

async def get_category_by_slug(db: AsyncSession, slug: str) -> Optional[Category]:
    result = await db.execute(select(Category).where(Category.slug == slug))
    return result.scalars().first()

async def create_category(db: AsyncSession, category: CategoryCreate) -> Category:
    db_cat = Category(**category.model_dump())
    db.add(db_cat)
    await db.commit()
    await db.refresh(db_cat)
    return db_cat

async def update_category(db: AsyncSession, category_id: str, category_update: CategoryUpdate) -> Optional[Category]:
    db_cat = await get_category(db, category_id)
    if db_cat:
        update_data = category_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_cat, key, value)
        await db.commit()
        await db.refresh(db_cat)
    return db_cat

async def delete_category(db: AsyncSession, category_id: str) -> bool:
    db_cat = await get_category(db, category_id)
    if not db_cat:
        return False
    await db.delete(db_cat)
    await db.commit()
    return True

async def seed_default_categories(db: AsyncSession):
    """Seed default categories if none exist."""
    result = await db.execute(select(Category))
    if result.scalars().first():
        return  # already has categories
    
    defaults = [
        {"name": "Goat Meat", "slug": "goat-meat", "description": "Fresh goat meat cuts and whole goat"},
        {"name": "Goat Parts", "slug": "goat-parts", "description": "Specific cuts: legs, ribs, head, organs"},
        {"name": "Per Kg", "slug": "per-kg", "description": "Sold by weight"},
        {"name": "Bundles", "slug": "bundles", "description": "Mixed bundles and meal-ready packs"},
        {"name": "Vegetables", "slug": "vegetables", "description": "Fresh vegetables and accompaniments"},
    ]
    for cat_data in defaults:
        db.add(Category(**cat_data))
    await db.commit()
