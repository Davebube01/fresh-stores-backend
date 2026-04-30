from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.crud.product import get_products, get_product
from app.schemas.product import ProductResponse

router = APIRouter()

@router.get("/", response_model=List[ProductResponse])
async def read_products(
    skip: int = 0, limit: int = 100, search: Optional[str] = None, db: AsyncSession = Depends(get_db)
):
    products = await get_products(db, skip=skip, limit=limit, search=search)
    return products

@router.get("/{product_id}", response_model=ProductResponse)
async def read_product(product_id: str, db: AsyncSession = Depends(get_db)):
    product = await get_product(db, product_id=product_id)
    if product is None or not getattr(product, "is_active", True):
        raise HTTPException(status_code=404, detail="Product not found")
    return product
