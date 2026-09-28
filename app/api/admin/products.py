from __future__ import annotations

import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
import cloudinary.uploader
from app.core import cloudinary_client
from app.core.cache import clear_product_caches
from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.crud.product import create_product, update_product, get_product, get_admin_products, adjust_stock, get_stock_movements
from app.schemas.product import AdminProductResponse, ProductCreate, ProductUpdate, StockAdjustmentRequest, StockMovementResponse
from app.core.product_options import normalize_weight_options
from app.services.activity_service import diff, log_activity, snapshot
from app.services.settings_service import get_low_stock_threshold
from app.services.stock_alerts import effective_threshold
from app.utils.dependencies import get_current_active_superuser
from sqlalchemy.future import select

router = APIRouter()

# Fields worth recording when a product is edited.
TRACKED = ("name", "price", "cost_price", "weight_options", "parts", "category", "is_active",
           "low_stock_threshold", "description", "image_url")
FIELD_NAMES = {"cost_price": "cost price", "weight_options": "sizes", "parts": "cuts", "is_active": "visibility",
               "low_stock_threshold": "low-stock alert", "image_url": "image"}

def _product_snapshot(product) -> dict:
    values = snapshot(product, TRACKED)
    # Older rows store sizes as bare labels; compare in the saved form so the
    # first save after the upgrade isn't logged as a size change.
    values["weight_options"] = normalize_weight_options(values["weight_options"], product.price)
    return values

async def _with_threshold(db: AsyncSession, products):
    """Set effective_low_stock_threshold (own value, else the store default) for the response."""
    default = await get_low_stock_threshold(db)
    for product in products if isinstance(products, list) else [products]:
        if product is not None:
            product.effective_low_stock_threshold = effective_threshold(product, default)
    return products

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # matches the "up to 10MB" copy already shown in the admin UI

@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    current_user = Depends(get_current_active_superuser)
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, detail="Invalid file type. Only images allowed.")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, detail="Image too large. Maximum size is 10MB.")

    if not cloudinary_client.configured:
        raise HTTPException(500, detail="Image storage is not configured")

    try:
        # cloudinary's SDK is synchronous (blocking network I/O) — run it off
        # the event loop so one upload doesn't stall every other request.
        result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            contents,
            folder="meat-store/products",
            resource_type="image",
        )
    except Exception as e:
        raise HTTPException(502, detail=f"Image upload failed: {e}")

    return {"imageUrl": result["secure_url"]}

@router.get("/products", response_model=List[AdminProductResponse])
async def read_admin_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    return await _with_threshold(db, list(await get_admin_products(db, skip=skip, limit=limit, search=search)))

@router.get("/products/{product_id}", response_model=AdminProductResponse)
async def read_admin_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    product = await get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return await _with_threshold(db, product)

@router.post("/products", response_model=AdminProductResponse)
async def create_new_product(
    product_in: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    product = await create_product(db, product_in)
    clear_product_caches()
    await log_activity(db, current_user, "product.created", "product", f"Added product {product.name}",
                       entity_id=product.id, entity_label=product.name)
    return await _with_threshold(db, await get_product(db, product.id))

@router.put("/products/{product_id}", response_model=AdminProductResponse)
async def update_existing_product(
    product_id: str,
    product_in: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    existing = await get_product(db, product_id)
    before = _product_snapshot(existing) if existing else {}
    product = await update_product(db, product_id, product_in)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    clear_product_caches()
    changes = diff(before, _product_snapshot(product))
    if changes:
        fields = ", ".join(FIELD_NAMES.get(f, f) for f in changes)
        await log_activity(db, current_user, "product.updated", "product", f"Updated {product.name}: {fields}",
                           entity_id=product.id, entity_label=product.name, changes=changes)
    return await _with_threshold(db, await get_product(db, product_id))

@router.post("/products/{product_id}/stock", response_model=AdminProductResponse)
async def adjust_product_stock(
    product_id: str,
    adjustment: StockAdjustmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """
    Manually add or correct a product's stock, logging who did it and why.
    Separate from the general product edit form so every stock change here
    carries an accountable reason instead of silently overwriting a number.
    """
    if adjustment.change == 0:
        raise HTTPException(status_code=400, detail="change must be non-zero")

    product = await adjust_stock(
        db, product_id, adjustment.change,
        admin_id=current_user.id, reason=adjustment.reason, note=adjustment.note
    )
    if product is None:
        raise HTTPException(status_code=400, detail="Product not found, or adjustment would take stock below zero")

    clear_product_caches()
    change = adjustment.change
    verb = f"Added {change:g} to" if change > 0 else f"Removed {-change:g} from"
    note = f" — {adjustment.note}" if adjustment.note else ""
    await log_activity(
        db, current_user, "stock.adjusted", "product", f"{verb} {product.name} stock ({adjustment.reason}){note}",
        entity_id=product.id, entity_label=product.name,
        changes={"stock": {"from": product.stock_quantity - change, "to": product.stock_quantity}},
    )
    return await _with_threshold(db, await get_product(db, product_id))

@router.get("/products/{product_id}/stock-movements", response_model=List[StockMovementResponse])
async def read_product_stock_movements(
    product_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    product = await get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return await get_stock_movements(db, product_id, skip=skip, limit=limit)

@router.delete("/products/{product_id}")
async def delete_existing_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    # Let's add delete product to DB
    from app.crud.product import delete_product
    existing = await get_product(db, product_id)
    try:
        deleted = await delete_product(db, product_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")

    clear_product_caches()
    await log_activity(db, current_user, "product.deleted", "product", f"Deleted product {existing.name}",
                       entity_id=product_id, entity_label=existing.name)
    return {"ok": True}
