"""
CSV exports for the admin: orders, sale lines (with cost and profit),
products, customers, stock movements and the activity log.

Files are UTF-8 with a byte-order mark so Excel shows ₦ and names
correctly; money is plain numbers (no currency sign) so it sums; dates are
Abuja time.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.delivery_zones import zone_name
from app.crud.customer import get_admin_customers
from app.models.activity import ActivityLog
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.stock_movement import StockMovement
from app.models.user import User
from app.services.dashboard_service import _item_cost
from app.services.settings_service import get_low_stock_threshold
from app.services.stock_alerts import effective_threshold

WAT = timezone(timedelta(hours=1))

Dataset = Literal["orders", "sale_lines", "products", "customers", "stock_movements", "activity"]
# Datasets that take a date range (the rest are a snapshot of now).
DATED = {"orders", "sale_lines", "stock_movements", "activity"}

# Besides "exports", what a role needs to download each one: exports mustn't
# become a side door to data the role can't see in the admin.
DATASET_PERMISSIONS: dict[str, str] = {
    "orders": "orders.view",
    "sale_lines": "costs.view",
    "stock_movements": "inventory.view",
    "activity": "activity.view",
    "products": "costs.view",
    "customers": "customers.view",
}

HEADERS: dict[str, list[str]] = {
    "orders": ["Date", "Order", "Channel", "Status", "Customer", "Email", "Phone", "Delivery method", "Zone",
               "Payment method", "Paid at", "Items", "Subtotal", "Discount", "Delivery fee (paid to courier)",
               "Total", "Cancellation reason"],
    "sale_lines": ["Date", "Order", "Channel", "Status", "Product", "Size / cut", "Quantity", "Stock used",
                   "Unit price", "Line total", "Unit cost", "Line cost", "Line profit"],
    "products": ["Product", "Slug", "Category", "Active", "Price", "Sizes", "Cuts", "Cost price (per stock unit)",
                 "In stock", "Low-stock alert at", "Stock value at cost", "Stock value at price"],
    "customers": ["Name", "Email", "Phone", "Status", "Email verified", "Joined", "Orders", "Paid orders",
                  "Total spent", "Last order"],
    "stock_movements": ["Date", "Product", "Change", "Before", "After", "Reason", "Note", "Order", "By"],
    "activity": ["Date", "Who", "Action", "What", "Summary", "Flagged"],
}

_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _cell(value):
    """
    Text that a spreadsheet would run as a formula (=, +, -, @ at the start)
    gets a leading apostrophe. Names, notes and messages come from customers
    and staff, so a CSV must never carry a live formula. Plain numbers
    (e.g. a stock change of -2) are left alone.
    """
    if isinstance(value, str) and value and value[0] in "=+-@\t\r" and not _NUMBER.match(value):
        return "'" + value
    return value


def _when(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:  # SQLite hands these back naive; they were written as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WAT).strftime("%Y-%m-%d %H:%M")


def _money(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.2f}"


def _num(value: Optional[float]) -> str:
    return "" if value is None else f"{value:g}"


def _ref(order_id: Optional[str]) -> str:
    return f"#{order_id[:8].upper()}" if order_id else ""


def _value(v) -> str:
    return getattr(v, "value", v) or ""


def to_csv(header: list[str], rows: Iterable[list]) -> str:
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([_cell(v) for v in row] for row in rows)
    return buf.getvalue()


def _range(date_from: Optional[date], date_to: Optional[date]):
    start = datetime.combine(date_from, time.min, WAT).astimezone(timezone.utc) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, WAT).astimezone(timezone.utc) if date_to else None
    return start, end


def _in_range(column, start, end) -> list:
    return [c for c in (column >= start if start else None, column < end if end else None) if c is not None]


def _customer(order: Order) -> tuple[str, str, str]:
    guest = order.guest_info or {}
    if order.user is not None and order.user.deleted_at is not None:
        return "Deleted customer", "", ""  # they asked for their details to go
    if order.user is not None:
        return order.user.full_name or "", order.user.email or "", order.user.phone or guest.get("phone") or ""
    return guest.get("fullName") or "", guest.get("email") or "", guest.get("phone") or ""


async def _orders(db: AsyncSession, start, end) -> list[Order]:
    return (
        await db.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.delivery),
                     selectinload(Order.user))
            .where(*_in_range(Order.created_at, start, end))
            .order_by(Order.created_at)
        )
    ).scalars().all()


async def export_orders(db: AsyncSession, start, end) -> str:
    header = HEADERS["orders"]
    rows = []
    for o in await _orders(db, start, end):
        name, email, phone = _customer(o)
        rows.append([
            _when(o.created_at), _ref(o.id), "Walk-in" if o.channel == "walk_in" else "Online", _value(o.status),
            name, email, phone, _value(o.delivery_method),
            zone_name(o.delivery.delivery_zone) if o.delivery else "", o.payment_method or "", _when(o.paid_at),
            sum(i.quantity for i in o.items), _money(o.subtotal), _money(o.discount_amount or 0),
            _money(o.delivery_fee), _money(o.total_amount), o.cancellation_reason or "",
        ])
    return to_csv(header, rows)


async def export_sale_lines(db: AsyncSession, start, end) -> str:
    header = HEADERS["sale_lines"]
    rows = []
    for o in await _orders(db, start, end):
        for i in o.items:
            cost = _item_cost(i)
            line_total = i.quantity * float(i.price_at_time or 0)
            line_cost = cost * i.quantity if cost is not None else None
            rows.append([
                _when(o.created_at), _ref(o.id), "Walk-in" if o.channel == "walk_in" else "Online", _value(o.status),
                i.product.name if i.product else "Deleted product", i.selected_option or "", i.quantity,
                _num(i.quantity * float(i.stock_units or 1)), _money(i.price_at_time), _money(line_total),
                _money(cost), _money(line_cost), _money(line_total - line_cost if line_cost is not None else None),
            ])
    return to_csv(header, rows)


async def export_products(db: AsyncSession) -> str:
    default = await get_low_stock_threshold(db)
    header = HEADERS["products"]
    products = (await db.execute(select(Product).order_by(Product.name))).scalars().all()
    rows = []
    for p in products:
        stock = max(float(p.stock_quantity or 0), 0)
        sizes = "; ".join(
            f"{o['label']} ₦{o['price']:g}" if isinstance(o, dict) else str(o) for o in (p.weight_options or [])
        )
        rows.append([
            p.name, p.slug, p.category, "Yes" if p.is_active else "No", _money(p.price), sizes,
            "; ".join(p.parts or []), _money(p.cost_price), _num(stock), _num(effective_threshold(p, default)),
            _money(stock * p.cost_price) if p.cost_price is not None else "", _money(stock * float(p.price or 0)),
        ])
    return to_csv(header, rows)


async def export_customers(db: AsyncSession) -> str:
    header = HEADERS["customers"]
    customers = await get_admin_customers(db, limit=100_000)
    rows = [[
        c["name"], c["email"], c["phone"] or "", c["status"], "Yes" if c["email_verified"] else "No",
        _when(c["joinDate"]), c["ordersCount"], c["paid_orders"], _money(c["totalSpent"]), _when(c["last_order_at"]),
    ] for c in customers]
    return to_csv(header, rows)


async def export_stock_movements(db: AsyncSession, start, end) -> str:
    header = HEADERS["stock_movements"]
    result = await db.execute(
        select(StockMovement, Product.name, User.full_name, User.email)
        .join(Product, Product.id == StockMovement.product_id)
        .outerjoin(User, User.id == StockMovement.admin_id)
        .where(*_in_range(StockMovement.created_at, start, end))
        .order_by(StockMovement.created_at)
    )
    rows = [[
        _when(m.created_at), name, _num(m.change), _num(m.previous_quantity), _num(m.new_quantity),
        m.reason.replace("_", " "), m.note or "", _ref(m.order_id), admin_name or admin_email or "",
    ] for m, name, admin_name, admin_email in result.all()]
    return to_csv(header, rows)


async def export_activity(db: AsyncSession, start, end, filters: Optional[dict] = None) -> str:
    from app.services.activity_service import FLAGGED_ACTIONS, _filters

    f = filters or {}
    extra = _filters(f.get("entity_type"), None, f.get("actor_id"), f.get("q"), None, None, bool(f.get("flagged")))
    header = HEADERS["activity"]
    entries = (
        await db.execute(
            select(ActivityLog).where(*_in_range(ActivityLog.created_at, start, end), *extra).order_by(ActivityLog.created_at)
        )
    ).scalars().all()
    rows = [
        [_when(a.created_at), a.actor_name or "", a.action, a.entity_label or "", a.summary,
         "yes" if a.action in FLAGGED_ACTIONS else ""]
        for a in entries
    ]
    return to_csv(header, rows)


async def build_export(
    db: AsyncSession, dataset: Dataset, date_from: Optional[date], date_to: Optional[date],
    activity_filters: Optional[dict] = None,
) -> str:
    start, end = _range(date_from, date_to)
    if dataset == "orders":
        return await export_orders(db, start, end)
    if dataset == "sale_lines":
        return await export_sale_lines(db, start, end)
    if dataset == "products":
        return await export_products(db)
    if dataset == "customers":
        return await export_customers(db)
    if dataset == "stock_movements":
        return await export_stock_movements(db, start, end)
    return await export_activity(db, start, end, activity_filters)


def filename(dataset: Dataset, date_from: Optional[date], date_to: Optional[date], today: date) -> str:
    name = dataset.replace("_", "-")
    if dataset not in DATED:
        return f"{name}-{today.isoformat()}.csv"
    if date_from and date_to:
        span = date_from.isoformat() if date_from == date_to else f"{date_from.isoformat()}-to-{date_to.isoformat()}"
    elif date_from:
        span = f"from-{date_from.isoformat()}"
    elif date_to:
        span = f"to-{date_to.isoformat()}"
    else:
        span = "all-time"
    return f"{name}-{span}.csv"


async def count_rows(db: AsyncSession, dataset: Dataset, date_from: Optional[date], date_to: Optional[date]) -> int:
    """How many rows the export would have, without building it."""
    start, end = _range(date_from, date_to)
    if dataset == "orders":
        q = select(func.count(Order.id)).where(*_in_range(Order.created_at, start, end))
    elif dataset == "sale_lines":
        q = select(func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id).where(*_in_range(Order.created_at, start, end))
    elif dataset == "stock_movements":
        q = (select(func.count(StockMovement.id)).join(Product, Product.id == StockMovement.product_id)
             .where(*_in_range(StockMovement.created_at, start, end)))
    elif dataset == "activity":
        q = select(func.count(ActivityLog.id)).where(*_in_range(ActivityLog.created_at, start, end))
    elif dataset == "products":
        q = select(func.count(Product.id))
    else:
        q = select(func.count(User.id)).where(User.is_superuser == False, User.deleted_at.is_(None))  # noqa: E712
    return (await db.execute(q)).scalar_one()
