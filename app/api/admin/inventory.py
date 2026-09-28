from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.schemas.inventory import InventoryResponse
from app.services.inventory_service import get_inventory
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

MovementReason = Literal["initial_stock", "order_placed", "order_cancelled", "restock", "correction"]


@router.get("", response_model=InventoryResponse)
async def get_admin_inventory(
    reason: Optional[MovementReason] = None,
    product_id: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """
    Stock summary, products that need restocking (with recent sales pace),
    and the store-wide stock movement log, optionally filtered.
    Restocking itself goes through POST /admin/products/{id}/stock so every
    change stays audited.
    """
    return await get_inventory(db, reason=reason, product_id=product_id, skip=skip, limit=limit)
