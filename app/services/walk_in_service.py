"""
Walk-in (counter) sales.

A walk-in sale is an Order with channel="walk_in": rung up by an admin,
paid on the spot and handed over, so it's created already delivered with
paid_at set. That way revenue, profit, top products, stock movements and
low-stock alerts all treat it like any other paid order, with no second
set of numbers to keep in sync.

Lines are priced on the server exactly like checkout (the chosen size's
price), or, for a weighed line, at the product's price per unit of stock
times the amount off the scale.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import clear_product_caches
from app.core.product_options import normalize_weight_options, resolve_line
from app.crud.product import decrement_stock, restore_stock
from app.models.order import DeliveryMethod, Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.schemas.walk_in import WalkInItem, WalkInSaleCreate
from app.services.admin_orders_service import to_row

WAT = timezone(timedelta(hours=1))
WALK_IN = "walk_in"


def price_per_stock_unit(product: Product) -> float:
    """What one unit of stock sells for: the best per-unit rate among its sizes, else its price."""
    options = normalize_weight_options(product.weight_options, product.price)
    if not options:
        return float(product.price)
    return min(float(o["price"]) / float(o["stock_units"]) for o in options)


def _amount_label(product: Product, amount: float) -> str:
    unit = "kg" if product.category == "per-kg" else " units" if amount != 1 else " unit"
    return f"{amount:g}{unit} (weighed)"


def _price_line(product: Product, item: WalkInItem) -> dict:
    if item.amount is not None:
        unit_price = round(price_per_stock_unit(product) * item.amount, 2)
        stock_units = item.amount
        display = _amount_label(product, item.amount)
        if item.part:
            if item.part not in (product.parts or []):
                raise ValueError(f"{item.part} isn't available for {product.name}")
            display = f"{display} · {item.part}"
    else:
        unit_price, stock_units, display = resolve_line(product, item.weight_option, item.part)
    cost = product.cost_price * stock_units if product.cost_price is not None else None
    return {
        "product_id": product.id,
        "quantity": item.quantity,
        "price_at_time": unit_price,
        "selected_option": display,
        "stock_units": stock_units,
        "cost_at_time": cost,
    }


def _options():
    return (
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.delivery),
        selectinload(Order.user),
    )


async def _sale_row(db: AsyncSession, order: Order) -> dict:
    row = to_row(order)
    served = await db.get(User, order.served_by) if order.served_by else None
    row["served_by_name"] = (served.full_name or served.email.split("@")[0]) if served else None
    return row


async def get_sale(db: AsyncSession, sale_id: str) -> Optional[dict]:
    order = (
        await db.execute(select(Order).options(*_options()).where(Order.id == sale_id, Order.channel == WALK_IN))
    ).scalar_one_or_none()
    return await _sale_row(db, order) if order else None


async def create_walk_in_sale(db: AsyncSession, sale: WalkInSaleCreate, admin_id: str) -> dict:
    """Price, reserve stock and record the sale in one transaction. Raises ValueError for bad input."""
    lines = []
    for item in sale.items:
        product = await db.get(Product, item.product_id)
        if product is None or not product.is_active:
            raise ValueError("One of these products is no longer available")
        lines.append((product, _price_line(product, item)))

    subtotal = round(sum(line["price_at_time"] * line["quantity"] for _, line in lines), 2)
    if sale.discount_amount > subtotal:
        raise ValueError("The discount can't be more than the sale total")
    if sale.discount_amount and not (sale.discount_note or "").strip():
        raise ValueError("Say why the discount was given")

    now = datetime.now(timezone.utc)
    guest = {k: v for k, v in {
        "fullName": (sale.customer_name or "").strip() or None,
        "phone": (sale.customer_phone or "").strip() or None,
    }.items() if v}
    order = Order(
        channel=WALK_IN,
        status=OrderStatus.DELIVERED,
        delivery_method=DeliveryMethod.PICKUP,
        payment_method=sale.payment_method,
        guest_info=guest or None,
        subtotal=subtotal,
        delivery_fee=0.0,
        discount_amount=sale.discount_amount,
        discount_note=(sale.discount_note or "").strip() or None,
        total_amount=round(subtotal - sale.discount_amount, 2),
        paid_at=now,
        served_by=admin_id,
    )
    db.add(order)
    try:
        await db.flush()
        for product, line in lines:
            if not await decrement_stock(db, product.id, line["quantity"] * line["stock_units"], order_id=order.id):
                raise ValueError(f"{product.name} doesn't have enough stock for this sale")
            db.add(OrderItem(order_id=order.id, **line))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    clear_product_caches()
    return await get_sale(db, order.id)


async def void_sale(db: AsyncSession, sale_id: str, reason: str) -> Optional[dict]:
    """Void a walk-in sale (e.g. rung up by mistake or refunded) and put its stock back."""
    order = (
        await db.execute(select(Order).options(*_options()).where(Order.id == sale_id, Order.channel == WALK_IN))
    ).scalar_one_or_none()
    if order is None:
        return None
    result = await db.execute(
        update(Order)
        .where(Order.id == sale_id, Order.status == OrderStatus.DELIVERED)
        .values(
            status=OrderStatus.CANCELLED.value,
            cancellation_reason=reason.strip()[:300],
            cancelled_by="admin",
            cancelled_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise ValueError("This sale has already been voided")
    for item in order.items:
        await restore_stock(db, item.product_id, item.quantity * (item.stock_units or 1), order_id=order.id)
    await db.commit()
    clear_product_caches()
    db.expire_all()
    return await get_sale(db, sale_id)


async def sales_for_day(db: AsyncSession, day: date) -> dict:
    start = datetime.combine(day, time.min, WAT).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    orders = (
        await db.execute(
            select(Order)
            .options(*_options())
            .where(Order.channel == WALK_IN, Order.created_at >= start, Order.created_at < end)
            .order_by(Order.created_at.desc())
        )
    ).scalars().all()

    by_method = {"cash": 0.0, "transfer": 0.0, "pos": 0.0}
    total = voided_total = 0.0
    count = voided = 0
    for o in orders:
        amount = float(o.total_amount or 0)
        if o.status == OrderStatus.CANCELLED:
            voided += 1
            voided_total += amount
            continue
        count += 1
        total += amount
        by_method[o.payment_method] = by_method.get(o.payment_method, 0.0) + amount

    return {
        "date": day,
        "summary": {
            "count": count,
            "total": total,
            "by_payment_method": by_method,
            "voided_count": voided,
            "voided_total": voided_total,
        },
        "sales": [await _sale_row(db, o) for o in orders],
    }
