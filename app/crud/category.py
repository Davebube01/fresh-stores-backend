from __future__ import annotations

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, update
from sqlalchemy.future import select
from app.models.category import Category
from app.models.product import Product
from app.schemas.category import CategoryCreate, CategoryUpdate


class CategoryConflict(ValueError):
    """A name/slug clash, or a delete that would orphan products."""

async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[Category]:
    result = await db.execute(select(Category).where(Category.is_active == True).offset(skip).limit(limit))
    return result.scalars().all()

async def get_all_categories(db: AsyncSession) -> List[Category]:
    result = await db.execute(select(Category))
    return result.scalars().all()

async def get_admin_categories(db: AsyncSession) -> List[dict]:
    """Every category, with how many products are filed under it (by slug)."""
    counts = (
        select(Product.category.label("slug"), func.count(Product.id).label("n"))
        .group_by(Product.category)
        .subquery()
    )
    result = await db.execute(
        select(Category, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.slug == Category.slug)
        .order_by(Category.name.asc())
    )
    rows = []
    for cat, n in result.all():
        row = {c.name: getattr(cat, c.name) for c in Category.__table__.columns}
        row["product_count"] = int(n)
        rows.append(row)
    return rows

async def count_products_in(db: AsyncSession, slug: str) -> int:
    return (await db.execute(select(func.count(Product.id)).where(Product.category == slug))).scalar_one()

async def _ensure_unique(db: AsyncSession, name: Optional[str], slug: Optional[str], exclude_id: Optional[str] = None) -> None:
    conds = []
    if name is not None:
        conds.append(func.lower(Category.name) == name.lower())
    if slug is not None:
        conds.append(Category.slug == slug)
    if not conds:
        return
    query = select(Category).where(or_(*conds))
    if exclude_id:
        query = query.where(Category.id != exclude_id)
    clash = (await db.execute(query)).scalars().first()
    if clash:
        field = "slug" if slug is not None and clash.slug == slug else "name"
        raise CategoryConflict(f"A category with this {field} already exists ({clash.name})")

async def get_category(db: AsyncSession, category_id: str) -> Optional[Category]:
    result = await db.execute(select(Category).where(Category.id == category_id))
    return result.scalars().first()

async def get_category_by_slug(db: AsyncSession, slug: str) -> Optional[Category]:
    result = await db.execute(select(Category).where(Category.slug == slug))
    return result.scalars().first()

async def create_category(db: AsyncSession, category: CategoryCreate) -> Category:
    await _ensure_unique(db, category.name, category.slug)
    db_cat = Category(**category.model_dump())
    db.add(db_cat)
    await db.commit()
    await db.refresh(db_cat)
    return db_cat

async def update_category(db: AsyncSession, category_id: str, category_update: CategoryUpdate) -> Optional[Category]:
    db_cat = await get_category(db, category_id)
    if not db_cat:
        return None
    update_data = category_update.model_dump(exclude_unset=True)
    await _ensure_unique(db, update_data.get("name"), update_data.get("slug"), exclude_id=category_id)

    old_slug = db_cat.slug
    for key, value in update_data.items():
        setattr(db_cat, key, value)
    # Products point at their category by slug: move them along with it, in
    # the same transaction, so a rename never strands them.
    if db_cat.slug != old_slug:
        await db.execute(update(Product).where(Product.category == old_slug).values(category=db_cat.slug))
    await db.commit()
    await db.refresh(db_cat)
    return db_cat

async def delete_category(db: AsyncSession, category_id: str) -> bool:
    db_cat = await get_category(db, category_id)
    if not db_cat:
        return False
    in_use = await count_products_in(db, db_cat.slug)
    if in_use:
        raise CategoryConflict(
            f"{db_cat.name} still has {in_use} product{'s' if in_use != 1 else ''}. "
            "Move them to another category first, or deactivate the category instead."
        )
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
