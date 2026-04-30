from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.crud.product import create_product, update_product, get_product, get_admin_products
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.utils.dependencies import get_current_active_superuser
from sqlalchemy.future import select
import os
import shutil
import uuid

router = APIRouter()

@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    # current_user = Depends(get_current_active_superuser)
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, detail="Invalid file type. Only images allowed.")
        
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join("uploads", filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Return the relative URL depending on server setup, handling local vs deployed scenarios
    return {"imageUrl": f"/uploads/{filename}"}

@router.get("/products", response_model=List[ProductResponse])
async def read_admin_products(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    return await get_admin_products(db, skip=skip, limit=limit, search=search)

@router.get("/products/{product_id}", response_model=ProductResponse)
async def read_admin_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    product = await get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.post("/products", response_model=ProductResponse)
async def create_new_product(
    product_in: ProductCreate, 
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    return await create_product(db, product_in)

@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_existing_product(
    product_id: str, 
    product_in: ProductUpdate, 
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    product = await update_product(db, product_id, product_in)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.delete("/products/{product_id}")
async def delete_existing_product(
    product_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    # Let's add delete product to DB
    from app.crud.product import delete_product
    deleted = await delete_product(db, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
        
    return {"ok": True}
