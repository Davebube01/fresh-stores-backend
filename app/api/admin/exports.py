from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.activity_service import log_activity
from app.core.permissions import can
from app.models.activity import ActivityLog
from app.services.export_service import (
    DATASET_PERMISSIONS, DATED, HEADERS, WAT, Dataset, build_export, count_rows, filename,
)
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

LABELS = {
    "orders": "orders", "sale_lines": "sale lines", "products": "products", "customers": "customers",
    "stock_movements": "stock movements", "activity": "activity log",
}


@router.get("")
async def list_exports(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """
    The exports this person may download, how many rows each would have for
    the range, and its columns; plus the store's last few downloads.
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="The start date is after the end date")
    datasets = []
    for key in DATASET_PERMISSIONS:
        if not can(current_admin, DATASET_PERMISSIONS[key]):
            continue
        dated = key in DATED
        datasets.append({
            "key": key,
            "dated": dated,
            "rows": await count_rows(db, key, date_from if dated else None, date_to if dated else None),
            "columns": HEADERS[key],
        })
    recent = []
    if can(current_admin, "activity.view"):
        rows = (await db.execute(
            select(ActivityLog).where(ActivityLog.action == "export.downloaded")
            .order_by(ActivityLog.created_at.desc()).limit(8)
        )).scalars().all()
        recent = [{"summary": r.summary, "file": r.entity_label, "by": r.actor_name, "at": r.created_at} for r in rows]
    return {"datasets": datasets, "recent": recent}


@router.get("/{dataset}.csv")
async def export_csv(
    dataset: Dataset,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    # Activity only: the same filters as the Activity page.
    entity_type: Optional[str] = Query(None, max_length=20),
    actor_id: Optional[str] = Query(None, max_length=64),
    q: Optional[str] = Query(None, max_length=100),
    flagged: bool = False,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """
    Download a dataset as CSV. orders, sale_lines, stock_movements and
    activity take an optional date range (Abuja days, inclusive).
    """
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="The start date is after the end date")
    if not can(current_admin, DATASET_PERMISSIONS[dataset]):
        raise HTTPException(status_code=403, detail="Your role doesn't allow this export. Ask the store owner.")
    activity_filters = {"entity_type": entity_type, "actor_id": actor_id, "q": q, "flagged": flagged}
    body = await build_export(db, dataset, date_from, date_to, activity_filters if dataset == "activity" else None)
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
