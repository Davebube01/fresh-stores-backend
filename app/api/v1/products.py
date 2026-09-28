from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache import make_cache_key, product_detail_cache, product_list_cache
from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.crud.category import get_category_by_slug
from app.crud.product import get_products, get_product, get_active_product_by_slug, get_related_products
from app.schemas.product import ProductResponse, ProductDetailResponse

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

@router.get("/slug/{slug}", response_model=ProductDetailResponse)
async def read_product_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    """
    The storefront product page: the product, its category's name and a few
    related products. Replaces downloading the whole catalogue to find one.
    """
    cache_key = make_cache_key("slug", slug)
    cached = product_detail_cache.get(cache_key)
    if cached is not None:
        return cached

    product = await get_active_product_by_slug(db, slug)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    category = await get_category_by_slug(db, product.category)
    related = await get_related_products(db, product)
    response = ProductDetailResponse(
        product=ProductResponse.model_validate(product),
        category_name=category.name if category and category.is_active else None,
        related=[ProductResponse.model_validate(p) for p in related],
    )
    product_detail_cache[cache_key] = response
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
