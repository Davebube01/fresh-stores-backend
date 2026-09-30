from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import can
from app.models.order import Order
from app.schemas.walk_in import SalesDay, TillCountIn, TillCountOut, VoidSaleRequest, WalkInSaleCreate, WalkInSaleRow
from app.services.walk_in_service import WAT, count_till, create_walk_in_sale, get_sale, sales_for_day, void_sale
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
    return await sales_for_day(
        db, day or datetime.now(timezone.utc).astimezone(WAT).date(), with_profit=can(current_admin, "costs.view"),
    )


def _naira(v: float) -> str:
    return f"₦{v:,.0f}"


@router.put("/till/{day}", response_model=TillCountOut)
async def put_till_count(
    day: date,
    body: TillCountIn,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Cash up a day: what's in the till against the day's cash sales plus the float."""
    try:
        till = await count_till(db, day, body.opening_float, body.counted_cash, body.note, current_admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    diff = till["difference"]
    result = "balanced" if abs(diff) < 0.5 else f"{_naira(abs(diff))} {'short' if diff < 0 else 'over'}"
    label = f"{day.day} {day.strftime('%b')}"
    await log_activity(
        db, current_admin, "sale.till_counted" if abs(diff) < 0.5 else "sale.till_discrepancy", "sale",
        f"Cashed up {label}: counted {_naira(till['counted_cash'])}, expected {_naira(till['expected_cash'])} ({result})"
        + (f". {till['note']}" if till["note"] else ""),
        entity_label=f"Till {day.isoformat()}",
    )
    return till


@router.post("", response_model=WalkInSaleRow, status_code=201)
async def create_sale(
    sale: WalkInSaleCreate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    # A retry of a sale that already went through: return it, don't log it again.
    replay = bool(sale.client_ref) and (
        await db.execute(select(Order.id).where(Order.client_ref == sale.client_ref))
    ).scalar_one_or_none() is not None
    try:
        created = await create_walk_in_sale(db, sale, admin_id=current_admin.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if replay:
        return created
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
