from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.notification import NotificationList
from app.services.stock_alerts import list_notifications, mark_read
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=NotificationList)
async def get_notifications(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Unread first (newest first), then recent read ones; plus the unread count for the bell."""
    return await list_notifications(db, limit=limit)


@router.post("/read-all")
async def read_all_notifications(
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    return {"marked": await mark_read(db)}


@router.post("/{notification_id}/read")
async def read_notification(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    if not await mark_read(db, notification_id):
        raise HTTPException(status_code=404, detail="Notification not found or already read")
    return {"marked": 1}
