"""
Check a browser-side cart against the live catalogue before checkout.

The storefront keeps the cart in localStorage, so it can go stale: prices
change, products sell out or are switched off, sizes get removed. This
re-prices every line the same way checkout does (resolve_line) and says what
changed, so the cart page can fix it up front instead of checkout failing.
"""
from __future__ import annotations

import math
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.product_options import resolve_line
from app.models.product import Product

router = APIRouter()


class CartCheckLine(BaseModel):
    key: str = Field(max_length=200)  # the client's own line id, echoed back
    product_id: str
    weight_option: Optional[str] = None
    part: Optional[str] = None
    quantity: int = Field(ge=1, le=100)
    # The price the cart is showing, to report changes against.
    unit_price: Optional[float] = None


class CartCheckRequest(BaseModel):
    items: list[CartCheckLine] = Field(max_length=100)


LineStatus = Literal["ok", "price_changed", "reduced", "out_of_stock", "unavailable"]


class CartCheckResult(BaseModel):
    key: str
    status: LineStatus
    unit_price: Optional[float] = None
    # Most of this line that can be bought now, given earlier lines of the
    # same product (they share its stock). 0 when none.
    max_quantity: int
    name: Optional[str] = None
    image_url: Optional[str] = None
    slug: Optional[str] = None
    message: Optional[str] = None


class CartCheckResponse(BaseModel):
    lines: list[CartCheckResult]


@router.post("/check", response_model=CartCheckResponse)
async def check_cart(body: CartCheckRequest, db: AsyncSession = Depends(get_db)):
    ids = {line.product_id for line in body.items}
    products = {
        p.id: p for p in (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars().all()
    } if ids else {}

    # Stock left per product as we walk the lines in order.
    remaining = {pid: max(float(p.stock_quantity or 0), 0.0) for pid, p in products.items()}
    results: list[CartCheckResult] = []

    for line in body.items:
        product = products.get(line.product_id)
        if product is None or not product.is_active:
            results.append(CartCheckResult(
                key=line.key, status="unavailable", max_quantity=0,
                name=product.name if product else None,
                message="This item is no longer sold.",
            ))
            continue

        base = {"name": product.name, "image_url": product.image_url, "slug": product.slug}
        try:
            unit_price, stock_units, _ = resolve_line(product, line.weight_option, line.part)
        except ValueError as e:
            results.append(CartCheckResult(key=line.key, status="unavailable", max_quantity=0, message=str(e), **base))
            continue

        per_unit = stock_units or 1.0
        can_have = math.floor(remaining[product.id] / per_unit + 1e-9)
        take = min(line.quantity, can_have)
        remaining[product.id] -= take * per_unit

        if can_have <= 0:
            status, message = "out_of_stock", "Sold out right now."
        elif take < line.quantity:
            status, message = "reduced", f"Only {can_have} left, so we've lowered the quantity."
        elif line.unit_price is not None and abs(line.unit_price - unit_price) >= 0.01:
            status = "price_changed"
            message = f"Price changed from ₦{line.unit_price:,.0f} to ₦{unit_price:,.0f}."
        else:
            status, message = "ok", None

        results.append(CartCheckResult(
            key=line.key, status=status, unit_price=unit_price, max_quantity=max(can_have, 0), message=message, **base,
        ))

    return {"lines": results}
