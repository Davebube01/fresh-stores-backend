from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.crud.category import (
    get_categories, get_all_categories, create_category,
    update_category, delete_category
)
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

# ── Admin: full CRUD ────────────────────────────────────────────────────────

@router.get("/categories", response_model=List[CategoryResponse])
async def admin_list_categories(db: AsyncSession = Depends(get_db)):
    return await get_all_categories(db)

@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def admin_create_category(
    category_in: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    return await create_category(db, category_in)

@router.put("/categories/{category_id}", response_model=CategoryResponse)
async def admin_update_category(
    category_id: str,
    category_in: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    cat = await update_category(db, category_id, category_in)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return cat

@router.delete("/categories/{category_id}")
async def admin_delete_category(
    category_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    deleted = await delete_category(db, category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"ok": True}
