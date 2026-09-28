from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.settings import (
    AdminSettingsResponse, DeliveryZoneOut, DeliveryZonesUpdate, StoreDetails,
)
from app.services.settings_service import (
    ZoneError, get_store_settings, list_zones, payment_status, replace_zones, update_store_settings,
)
from app.services.activity_service import diff, log_activity
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
    before = StoreDetails.model_validate(await get_store_settings(db)).model_dump()
    saved = StoreDetails.model_validate(await update_store_settings(db, details))
    changes = diff(before, saved.model_dump())
    if changes:
        await log_activity(db, current_admin, "settings.store_updated", "settings",
                           f"Updated store details: {', '.join(k.replace('_', ' ') for k in changes)}",
                           entity_label="Store details", changes=changes)
    return saved


@router.put("/zones", response_model=list[DeliveryZoneOut])
async def put_delivery_zones(
    update: DeliveryZonesUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Replace the zone list (order = display order). Checkout uses the new fees immediately."""
    before = {z["name"]: z["fee"] for z in await list_zones(db) if z["is_active"]}
    try:
        zones = await replace_zones(db, update)
    except ZoneError as e:
        raise HTTPException(status_code=400, detail=str(e))
    after = {z["name"] if isinstance(z, dict) else z.name: (z["fee"] if isinstance(z, dict) else z.fee)
             for z in zones if (z["is_active"] if isinstance(z, dict) else z.is_active)}
    changes = diff(before, after) | {k: {"from": v, "to": None} for k, v in before.items() if k not in after}
    if changes:
        await log_activity(db, current_admin, "settings.zones_updated", "settings",
                           f"Updated delivery zones: {', '.join(changes)}",
                           entity_label="Delivery zones", changes=changes)
    return zones
