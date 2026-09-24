from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache import make_cache_key, product_detail_cache, product_list_cache
from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.crud.product import get_products, get_product
from app.schemas.product import ProductResponse

router = APIRouter()

@router.get("/", response_model=List[ProductResponse])
async def read_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    cache_key = make_cache_key("list", skip, limit, search)
    cached = product_list_cache.get(cache_key)
    if cached is not None:
        return cached

    products = await get_products(db, skip=skip, limit=limit, search=search)
    response = [ProductResponse.model_validate(p) for p in products]
    product_list_cache[cache_key] = response
    return response

@router.get("/{product_id}", response_model=ProductResponse)
async def read_product(product_id: str, db: AsyncSession = Depends(get_db)):
    cached = product_detail_cache.get(product_id)
    if cached is not None:
        return cached

    product = await get_product(db, product_id=product_id)
    if product is None or not getattr(product, "is_active", True):
        raise HTTPException(status_code=404, detail="Product not found")

    response = ProductResponse.model_validate(product)
    product_detail_cache[product_id] = response
    return response
