from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.dashboard import DashboardRange, DashboardResponse
from app.services.dashboard_service import get_dashboard
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=DashboardResponse)
async def get_admin_dashboard(
    range: DashboardRange = Query("today"),
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """
    KPIs, revenue chart, status mix, today's delivery slots, low stock,
    top products and recent orders for the admin home screen.
    """
    return await get_dashboard(db, range)
