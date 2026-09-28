from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.delivery_zones import DELIVERY_ZONES, load_delivery_zones

router = APIRouter()

@router.get("/zones")
async def list_delivery_zones(db: AsyncSession = Depends(get_db)):
    """
    Public: delivery zones with their estimated fee. The customer pays this
    directly to the courier, in cash, on delivery — it is never charged online.
    """
    # Checkout calls this before placing an order, so refreshing here keeps
    # this process's fee lookup in step with admin edits.
    await load_delivery_zones(db)
    return [
        {"id": zone_id, "name": zone["name"], "estimated_fee": zone["fee"]}
        for zone_id, zone in DELIVERY_ZONES.items()
    ]
