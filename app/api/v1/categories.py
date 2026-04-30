from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.crud.category import get_categories
from app.schemas.category import CategoryResponse

router = APIRouter()

@router.get("", response_model=List[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Public endpoint — lists active categories for use in product filters/forms."""
    return await get_categories(db)
