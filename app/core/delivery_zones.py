"""
Static delivery-zone -> estimated fee table.

This is shown to the customer at checkout as an ESTIMATE. It is never
charged online: the courier is paid in cash, directly, on delivery. See
order_service.process_checkout, which looks fees up here rather than
trusting whatever value the client sends.
"""

DELIVERY_ZONES: dict[str, dict[str, object]] = {
    "airport": {"name": "Airport", "fee": 15000.0},
    "apo-cedacrest": {"name": "Apo (Legislative Quarters Zone A/ Cedacrest)", "fee": 4000.0},
    "apo-mechanic": {"name": "Apo mechanic / Primary school / Nepa", "fee": 4500.0},
    "apo-resettlement": {"name": "Apo Resettlement / Shoprite / Extension", "fee": 5000.0},
    "kubwa": {"name": "Kubwa", "fee": 5500.0},
    "gwarinpa": {"name": "Gwarinpa", "fee": 3500.0},
    "wuse": {"name": "Wuse / Wuse 2", "fee": 2500.0},
    "maitama": {"name": "Maitama / Asokoro", "fee": 3000.0},
}


def get_zone_fee(zone_id: str) -> float:
    zone = DELIVERY_ZONES.get(zone_id)
    if zone is None:
        raise ValueError(f"Unknown delivery zone: {zone_id}")
    return float(zone["fee"])
