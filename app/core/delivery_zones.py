"""
Delivery zones -> estimated courier fee.

This is shown to the customer at checkout as an ESTIMATE. It is never
charged online: the courier is paid in cash, directly, on delivery. See
order_service.process_checkout, which looks fees up here rather than
trusting whatever value the client sends.

Zones live in the `delivery_zones` table (editable in admin Settings).
Checkout looks fees up synchronously, so this module keeps an in-process
copy of the active ones in DELIVERY_ZONES, refreshed from the database at
startup, whenever an admin edits zones, and whenever the storefront lists
them (which checkout does before every order). DEFAULT_ZONES only seeds an
empty table.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_ZONES: dict[str, dict[str, object]] = {
    "airport": {"name": "Airport", "fee": 15000.0},
    "apo-cedacrest": {"name": "Apo (Legislative Quarters Zone A/ Cedacrest)", "fee": 4000.0},
    "apo-mechanic": {"name": "Apo mechanic / Primary school / Nepa", "fee": 4500.0},
    "apo-resettlement": {"name": "Apo Resettlement / Shoprite / Extension", "fee": 5000.0},
    "kubwa": {"name": "Kubwa", "fee": 5500.0},
    "gwarinpa": {"name": "Gwarinpa", "fee": 3500.0},
    "wuse": {"name": "Wuse / Wuse 2", "fee": 2500.0},
    "maitama": {"name": "Maitama / Asokoro", "fee": 3000.0},
}

# Active zones only, in display order. Mutated in place so importers that
# hold a reference always see the current set.
DELIVERY_ZONES: dict[str, dict[str, object]] = {k: dict(v) for k, v in DEFAULT_ZONES.items()}
# Every zone's name, active or not, so old orders still show a readable area.
ZONE_NAMES: dict[str, str] = {k: str(v["name"]) for k, v in DEFAULT_ZONES.items()}


def get_zone_fee(zone_id: str) -> float:
    zone = DELIVERY_ZONES.get(zone_id)
    if zone is None:
        raise ValueError(f"Unknown delivery zone: {zone_id}")
    return float(zone["fee"])


def zone_name(zone_id: str | None) -> str | None:
    if not zone_id:
        return None
    return ZONE_NAMES.get(zone_id, zone_id)


async def load_delivery_zones(db: AsyncSession) -> None:
    """Seed the table on first run, then refresh the in-process copies from it."""
    from app.models.settings import DeliveryZone

    if (await db.execute(select(func.count(DeliveryZone.id)))).scalar_one() == 0:
        ordered = sorted(DEFAULT_ZONES.items(), key=lambda kv: float(kv[1]["fee"]))
        for i, (zone_id, z) in enumerate(ordered):
            db.add(DeliveryZone(id=zone_id, name=z["name"], fee=z["fee"], sort_order=i))
        await db.commit()

    rows = (
        await db.execute(select(DeliveryZone).order_by(DeliveryZone.sort_order, DeliveryZone.name))
    ).scalars().all()
    DELIVERY_ZONES.clear()
    DELIVERY_ZONES.update({z.id: {"name": z.name, "fee": float(z.fee)} for z in rows if z.is_active})
    ZONE_NAMES.clear()
    ZONE_NAMES.update({z.id: z.name for z in rows})
