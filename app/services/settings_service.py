from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_config
from app.core.delivery_zones import load_delivery_zones
from app.models.delivery import Delivery
from app.models.settings import DeliveryZone, StoreSettings
from app.schemas.settings import DeliveryZonesUpdate, StoreDetails

DEFAULT_LOW_STOCK_THRESHOLD = 5.0


async def get_store_settings(db: AsyncSession) -> StoreSettings:
    """The single settings row, created with defaults the first time it's asked for."""
    row = await db.get(StoreSettings, 1)
    if row is None:
        row = StoreSettings(id=1, store_name="Everything Fresh", low_stock_threshold=DEFAULT_LOW_STOCK_THRESHOLD)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def get_low_stock_threshold(db: AsyncSession) -> float:
    row = await db.get(StoreSettings, 1)
    return float(row.low_stock_threshold) if row is not None else DEFAULT_LOW_STOCK_THRESHOLD


async def update_store_settings(db: AsyncSession, details: StoreDetails) -> StoreSettings:
    row = await get_store_settings(db)
    for key, value in details.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def list_zones(db: AsyncSession) -> list[dict]:
    await load_delivery_zones(db)  # seeds the table on first use
    counts = dict(
        (await db.execute(select(Delivery.delivery_zone, func.count(Delivery.id)).group_by(Delivery.delivery_zone))).all()
    )
    rows = (await db.execute(select(DeliveryZone).order_by(DeliveryZone.sort_order, DeliveryZone.name))).scalars().all()
    return [
        {"id": z.id, "name": z.name, "fee": z.fee, "is_active": z.is_active, "sort_order": z.sort_order, "orders_count": counts.get(z.id, 0)}
        for z in rows
    ]


class ZoneError(ValueError):
    pass


def _slugify(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "zone"


async def replace_zones(db: AsyncSession, update: DeliveryZonesUpdate) -> list[dict]:
    """
    Save the zone list as edited in admin. Existing zones keep their id
    (orders reference it); new ones get an id from their name. Zones missing
    from the list are switched off rather than deleted, for the same reason.
    """
    await load_delivery_zones(db)
    existing = {z.id: z for z in (await db.execute(select(DeliveryZone))).scalars().all()}

    names = [z.name.lower() for z in update.zones]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ZoneError(f"Each zone needs a different name ({', '.join(sorted(dupes))} is used twice)")
    if not any(z.is_active for z in update.zones):
        raise ZoneError("Keep at least one zone active, or customers can't choose delivery at checkout")

    seen: set[str] = set()
    for i, z in enumerate(update.zones):
        zone_id = z.id if z.id in existing else (z.id or _slugify(z.name))
        base, n = zone_id, 2
        while zone_id in seen or (zone_id in existing and z.id != zone_id):
            zone_id = f"{base}-{n}"
            n += 1
        seen.add(zone_id)

        row = existing.get(zone_id)
        if row is None:
            row = DeliveryZone(id=zone_id)
            db.add(row)
        row.name, row.fee, row.is_active, row.sort_order = z.name, z.fee, z.is_active, i

    for zone_id, row in existing.items():
        if zone_id not in seen:
            row.is_active = False
            row.sort_order = len(update.zones) + row.sort_order

    await db.commit()
    return await list_zones(db)


def payment_status(base_url: str) -> dict:
    secret = app_config.PAYSTACK_SECRET_KEY or ""
    public = app_config.PAYSTACK_PUBLIC_KEY or ""
    mode = "live" if secret.startswith("sk_live_") else "test" if secret.startswith("sk_test_") else None
    return {
        "provider": "paystack",
        "configured": bool(secret),
        "mode": mode,
        "public_key_hint": f"{public[:8]}…{public[-4:]}" if len(public) > 12 else None,
        "webhook_url": f"{base_url.rstrip('/')}{app_config.API_V1_STR}/payments/webhook",
    }
