from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.schemas.activity import ActivityPage
from app.services.activity_service import list_activity
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

EntityType = Literal["product", "category", "order", "sale", "settings", "admin"]


@router.get("", response_model=ActivityPage)
async def get_activity(
    entity_type: Optional[EntityType] = None,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=100),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Admin actions, newest first, with optional filters and a total for paging."""
    return await list_activity(
        db, entity_type=entity_type, entity_id=entity_id, actor_id=actor_id, search=q,
        date_from=date_from, date_to=date_to, skip=skip, limit=limit,
    )
