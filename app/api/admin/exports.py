from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.activity_service import log_activity
from app.services.export_service import DATED, WAT, Dataset, build_export, filename
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

LABELS = {
    "orders": "orders", "sale_lines": "sale lines", "products": "products", "customers": "customers",
    "stock_movements": "stock movements", "activity": "activity log",
}


@router.get("/{dataset}.csv")
async def export_csv(
    dataset: Dataset,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """
    Download a dataset as CSV. orders, sale_lines, stock_movements and
    activity take an optional date range (Abuja days, inclusive).
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="The start date is after the end date")
    body = await build_export(db, dataset, date_from, date_to)
    name = filename(dataset, date_from, date_to, datetime.now(timezone.utc).astimezone(WAT).date())

    span = ""
    if dataset in DATED and (date_from or date_to):
        span = f" ({date_from or '…'} to {date_to or '…'})"
    await log_activity(db, current_admin, "export.downloaded", "admin", f"Exported {LABELS[dataset]}{span} as CSV",
                       entity_label=name)
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
