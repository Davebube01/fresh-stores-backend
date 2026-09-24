from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache import category_cache
from app.core.database import get_db
from app.crud.category import get_categories
from app.schemas.category import CategoryResponse

router = APIRouter()

_CACHE_KEY = "public_active_categories"

@router.get("", response_model=List[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Public endpoint — lists active categories for use in product filters/forms."""
    cached = category_cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    categories = await get_categories(db)
    response = [CategoryResponse.model_validate(c) for c in categories]
    category_cache[_CACHE_KEY] = response
    return response
