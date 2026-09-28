from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.walk_in import SalesDay, VoidSaleRequest, WalkInSaleCreate, WalkInSaleRow
from app.services.walk_in_service import WAT, create_walk_in_sale, get_sale, sales_for_day, void_sale
from app.services.activity_service import log_activity
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=SalesDay)
async def list_sales(
    day: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Walk-in sales for one day (Abuja time, default today) with a cash-up summary."""
    return await sales_for_day(db, day or datetime.now(timezone.utc).astimezone(WAT).date())


@router.post("", response_model=WalkInSaleRow, status_code=201)
async def create_sale(
    sale: WalkInSaleCreate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    try:
        created = await create_walk_in_sale(db, sale, admin_id=current_admin.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ref = f"#{created['id'][:8].upper()}"
    await log_activity(db, current_admin, "sale.created", "sale",
                       f"Rang up sale {ref} for ₦{created['total_amount']:,.0f} ({sale.payment_method})",
                       entity_id=created["id"], entity_label=ref)
    return created


@router.get("/{sale_id}", response_model=WalkInSaleRow)
async def read_sale(
    sale_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    sale = await get_sale(db, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


@router.post("/{sale_id}/void", response_model=WalkInSaleRow)
async def void(
    sale_id: str,
    payload: VoidSaleRequest,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    try:
        sale = await void_sale(db, sale_id, payload.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    ref = f"#{sale_id[:8].upper()}"
    await log_activity(db, current_admin, "sale.voided", "sale",
                       f"Voided sale {ref} (₦{sale['total_amount']:,.0f}): {payload.reason.strip()}",
                       entity_id=sale_id, entity_label=ref)
    return sale
