from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.settings import (
    AdminSettingsResponse, DeliveryZoneOut, DeliveryZonesUpdate, StoreDetails,
)
from app.services.settings_service import (
    ZoneError, get_store_settings, list_zones, payment_status, replace_zones, update_store_settings,
)
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=AdminSettingsResponse)
async def get_admin_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Store details, delivery zones and payment connection status."""
    return {
        "store": StoreDetails.model_validate(await get_store_settings(db)),
        "zones": await list_zones(db),
        "payments": payment_status(str(request.base_url)),
    }


@router.put("/store", response_model=StoreDetails)
async def put_store_details(
    details: StoreDetails,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    return StoreDetails.model_validate(await update_store_settings(db, details))


@router.put("/zones", response_model=list[DeliveryZoneOut])
async def put_delivery_zones(
    update: DeliveryZonesUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Replace the zone list (order = display order). Checkout uses the new fees immediately."""
    try:
        return await replace_zones(db, update)
    except ZoneError as e:
        raise HTTPException(status_code=400, detail=str(e))
