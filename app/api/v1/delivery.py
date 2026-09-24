from __future__ import annotations

from fastapi import APIRouter
from app.core.delivery_zones import DELIVERY_ZONES

router = APIRouter()

@router.get("/zones")
async def list_delivery_zones():
    """
    Public: delivery zones with their estimated fee. The customer pays this
    directly to the courier, in cash, on delivery — it is never charged online.
    """
    return [
        {"id": zone_id, "name": zone["name"], "estimated_fee": zone["fee"]}
        for zone_id, zone in DELIVERY_ZONES.items()
    ]
