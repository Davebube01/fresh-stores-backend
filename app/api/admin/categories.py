from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache import clear_category_cache, clear_product_caches
from app.core.database import get_db
from app.crud.category import (
    CategoryConflict, get_admin_categories, get_category, create_category,
    update_category, delete_category, count_products_in,
)
from app.schemas.category import CategoryCreate, CategoryUpdate, AdminCategoryResponse
from app.services.activity_service import diff, log_activity, snapshot
from app.utils.dependencies import get_current_active_superuser

CATEGORY_FIELDS = ("name", "slug", "description", "is_active")

router = APIRouter()

# ── Admin: full CRUD ────────────────────────────────────────────────────────

@router.get("/categories", response_model=List[AdminCategoryResponse])
async def admin_list_categories(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """Every category (inactive ones too), with its product count."""
    return await get_admin_categories(db)

@router.post("/categories", response_model=AdminCategoryResponse, status_code=201)
async def admin_create_category(
    category_in: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    try:
        cat = await create_category(db, category_in)
    except CategoryConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    clear_category_cache()
    await log_activity(db, current_user, "category.created", "category", f"Added category {cat.name}",
                       entity_id=cat.id, entity_label=cat.name)
    # A new slug can pick up products that were filed under it already.
    return {**AdminCategoryResponse.model_validate(cat).model_dump(), "product_count": await count_products_in(db, cat.slug)}

@router.put("/categories/{category_id}", response_model=AdminCategoryResponse)
async def admin_update_category(
    category_id: str,
    category_in: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    before = await get_category(db, category_id)
    old_slug = before.slug if before else None
    old_values = snapshot(before, CATEGORY_FIELDS) if before else {}
    try:
        cat = await update_category(db, category_id, category_in)
    except CategoryConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    clear_category_cache()
    if cat.slug != old_slug:
        clear_product_caches()  # its products were re-filed under the new slug
    changes = diff(old_values, snapshot(cat, CATEGORY_FIELDS))
    if changes:
        await log_activity(db, current_user, "category.updated", "category",
                           f"Updated category {cat.name}: {', '.join(changes)}",
                           entity_id=cat.id, entity_label=cat.name, changes=changes)
    return {**AdminCategoryResponse.model_validate(cat).model_dump(), "product_count": await count_products_in(db, cat.slug)}

@router.delete("/categories/{category_id}")
async def admin_delete_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    existing = await get_category(db, category_id)
    try:
        deleted = await delete_category(db, category_id)
    except CategoryConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    clear_category_cache()
    await log_activity(db, current_user, "category.deleted", "category", f"Deleted category {existing.name}",
                       entity_id=category_id, entity_label=existing.name)
    return {"ok": True}
