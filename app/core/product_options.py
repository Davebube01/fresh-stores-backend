"""
Size ("weight option") pricing.

Each product's `weight_options` is a list of
    {"label": "2kg", "price": 17000, "stock_units": 2}
where `price` is what one of that option costs and `stock_units` is how much
of the product's `stock_quantity` it uses up. Stock is counted in whatever
unit the product is stocked in — kg for per-kg cuts, pieces for whole goats —
so a per-kg product with 24 in stock can sell twelve "2kg" options.

Older rows stored bare labels (["1kg", "2kg"]) that all cost `product.price`
and each took 1 off stock. `normalize_weight_options` upgrades those on read
by scaling from the first option's weight (so "2kg" after "1kg" is double
price and double stock), and falls back to price × 1 when the labels can't be
compared (e.g. "Full", "1 piece").
"""
from __future__ import annotations

import re
from typing import Any, Optional

# "1kg", "2.5 kg", "500g", "3kg mix" → grams. Anything else (e.g. "Full",
# "1 piece") has no comparable weight.
_WEIGHT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)

# The storefront joins size and cut into one display string, e.g. "2kg · Hind leg".
OPTION_SEPARATOR = " · "


def parse_grams(label: str) -> Optional[float]:
    match = _WEIGHT_RE.match(label)
    if not match:
        return None
    amount = float(match.group(1))
    return amount * 1000 if match.group(2).lower() == "kg" else amount


def normalize_weight_options(raw: Any, base_price: float) -> list[dict]:
    """Return weight options as dicts, upgrading legacy bare-string labels."""
    if not raw:
        return []
    base_grams = None
    first = raw[0]
    if isinstance(first, str):
        base_grams = parse_grams(first)

    options = []
    for opt in raw:
        if isinstance(opt, str):
            grams = parse_grams(opt)
            ratio = grams / base_grams if grams and base_grams else 1.0
            options.append({"label": opt, "price": round(base_price * ratio, 2), "stock_units": ratio})
        elif isinstance(opt, dict):
            options.append(opt)
        else:
            # Already a validated model (e.g. WeightOption) — pass through.
            options.append(opt.model_dump() if hasattr(opt, "model_dump") else opt)
    return options


def split_selected_option(product: Any, selected_option: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Recover (size, cut) from a legacy "2kg · Hind leg" display string."""
    if not selected_option:
        return None, None
    if not product.weight_options:
        # No sizes, so the whole label is the cut.
        return None, selected_option
    pieces = selected_option.split(OPTION_SEPARATOR, 1)
    return pieces[0], (pieces[1] if len(pieces) > 1 else None)


def resolve_line(
    product: Any,
    weight_label: Optional[str],
    part: Optional[str],
) -> tuple[float, float, Optional[str]]:
    """
    Price one order line from the product's own options.

    Returns (unit_price, stock_units, display_option). Raises ValueError with
    a customer-facing message if the chosen size or cut isn't one the product
    offers — never falls back to a client-supplied price.
    """
    options = normalize_weight_options(product.weight_options, product.price)
    unit_price = product.price
    stock_units = 1.0
    chosen_label = None

    if options:
        if not weight_label:
            raise ValueError(f"Choose a size for {product.name}")
        match = next((o for o in options if o["label"] == weight_label), None)
        if match is None:
            raise ValueError(f"{weight_label} isn't available for {product.name}")
        unit_price = float(match["price"])
        stock_units = float(match["stock_units"])
        chosen_label = match["label"]

    chosen_part = None
    parts = product.parts or []
    if parts:
        if not part:
            raise ValueError(f"Choose a cut for {product.name}")
        if part not in parts:
            raise ValueError(f"{part} isn't available for {product.name}")
        chosen_part = part

    display = OPTION_SEPARATOR.join(p for p in (chosen_label, chosen_part) if p) or None
    return unit_price, stock_units, display
