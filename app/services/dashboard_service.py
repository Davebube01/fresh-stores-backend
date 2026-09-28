"""
Numbers for the admin dashboard.

Definitions (kept in one place so the cards and the chart always agree):
- Revenue / orders count money actually taken: online orders with `paid_at`
  set (bucketed by when they were paid), plus cash-on-delivery orders once
  delivered (bucketed by their last update, i.e. the delivery). Cancelled
  orders never count. `total_amount` is the item subtotal — the delivery
  fee is paid to the courier in cash and never reaches us.
- "Awaiting dispatch" = paid/processing, plus COD orders still pending (COD
  is unpaid by design, so "pending" there means accepted and waiting to go).
- "Today", day buckets and delivery slots use Abuja time (WAT, UTC+1, no DST).
- The previous period is the same length immediately before the current one,
  so "today" compares against yesterday up to the same time of day.
- Gross profit = item revenue minus what those items cost us. Each order
  item's cost is the cost snapshotted at checkout; older items without one
  use the product's current cost. Items with no cost at all are left out of
  profit (not counted as free), and `profit_coverage` says what share of
  revenue profit covers.

Aggregation is done in Python over the orders in the two periods. That is a
few hundred rows at this store's scale; move it into SQL GROUP BYs if it ever
becomes thousands per month.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.delivery_zones import zone_name
from app.models.delivery import Delivery
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.services.settings_service import get_low_stock_threshold
from app.services.stock_alerts import effective_threshold, threshold_expr

WAT = timezone(timedelta(hours=1))

RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}
# The chart needs more than one point to be useful, so "today" still charts a week.
SERIES_DAYS = {"today": 7, "7d": 7, "30d": 30}

AWAITING_DISPATCH = (OrderStatus.PAID, OrderStatus.PROCESSING)
UNPAID = (OrderStatus.PENDING, OrderStatus.AWAITING_VERIFICATION)
COD = "cod"
STATUS_ORDER = [s.value for s in OrderStatus]


def _status(order: Order) -> str:
    return order.status.value if isinstance(order.status, OrderStatus) else str(order.status)


def _needs_dispatch(order: Order) -> bool:
    return order.status in AWAITING_DISPATCH or (order.status == OrderStatus.PENDING and order.payment_method == COD)


def _as_utc(dt: datetime | None) -> datetime | None:
    # SQLite hands timezone-aware columns back naive; they were written as UTC.
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _item_cost(item: OrderItem) -> float | None:
    """What one unit of this line cost us, or None if we don't know."""
    if item.cost_at_time is not None:
        return float(item.cost_at_time)
    product = item.product
    if product is not None and product.cost_price is not None:
        return float(product.cost_price) * float(item.stock_units or 1)
    return None


def _item_profit(item: OrderItem) -> float | None:
    cost = _item_cost(item)
    if cost is None:
        return None
    return item.quantity * (float(item.price_at_time or 0) - cost)


def _customer_name(order: Order) -> str:
    if order.user is not None:
        return order.user.full_name or order.user.email.split("@")[0]
    guest = order.guest_info or {}
    return guest.get("fullName") or guest.get("email") or "Guest"


def _zone_name(zone_id: str | None) -> str | None:
    return zone_name(zone_id)


def _order_row(order: Order) -> dict:
    delivery = order.delivery
    method = order.delivery_method
    return {
        "id": order.id,
        "customer_name": _customer_name(order),
        "status": _status(order),
        "delivery_method": method.value if hasattr(method, "value") else method,
        "delivery_zone": _zone_name(delivery.delivery_zone) if delivery else None,
        "time_slot": delivery.time_slot if delivery else None,
        "total_amount": float(order.total_amount or 0),
        "items_count": sum(i.quantity for i in order.items),
        "created_at": order.created_at,
    }


def _local_delivery_date(raw: str | None) -> date | None:
    """Checkout stores the browser's `Date.toISOString()` (UTC); read it in WAT."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:  # a bare "YYYY-MM-DD" means that calendar day
        return parsed.date()
    return parsed.astimezone(WAT).date()


def _slot_bounds(slot: str, day: date) -> tuple[datetime, datetime] | None:
    """'14:00 - 15:00' on `day` -> (start, end) in WAT."""
    try:
        start_s, end_s = [p.strip() for p in slot.split("-")]
        start = datetime.combine(day, time.fromisoformat(start_s), WAT)
        end = datetime.combine(day, time.fromisoformat(end_s), WAT)
    except ValueError:
        return None
    return start, end


def _order_options():
    return (
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.delivery),
        selectinload(Order.user),
    )


async def get_dashboard(db: AsyncSession, range_key: str, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(WAT)
    today = now.date()
    today_start = datetime.combine(today, time.min, WAT)

    # Current period [start, now) and the equal-length period before it.
    start = today_start - timedelta(days=RANGE_DAYS[range_key] - 1)
    prev_start = start - (now - start)

    # Chart buckets: SERIES_DAYS whole days ending today, compared with the
    # same number of days before that.
    series_days = SERIES_DAYS[range_key]
    series_start = today_start - timedelta(days=series_days - 1)
    series_prev_start = series_start - timedelta(days=series_days)

    fetch_from = min(prev_start, series_prev_start).astimezone(timezone.utc)

    paid = (
        await db.execute(
            select(Order)
            .options(*_order_options())
            .where(
                Order.status != OrderStatus.CANCELLED,
                or_(
                    and_(Order.paid_at.isnot(None), Order.paid_at >= fetch_from),
                    and_(
                        Order.paid_at.is_(None),
                        Order.payment_method == COD,
                        Order.status == OrderStatus.DELIVERED,
                        Order.updated_at >= fetch_from,
                    ),
                ),
            )
        )
    ).scalars().all()

    # --- KPIs + top products ---------------------------------------------
    revenue = revenue_prev = 0.0
    orders = orders_prev = 0
    profit = profit_prev = 0.0
    costed_revenue = costed_revenue_prev = 0.0
    by_product: dict[str, dict] = {}
    day_revenue: dict[date, float] = defaultdict(float)
    day_orders: dict[date, int] = defaultdict(int)

    for order in paid:
        paid_at = _as_utc(order.paid_at or order.updated_at).astimezone(WAT)
        amount = float(order.total_amount or 0)
        day_revenue[paid_at.date()] += amount
        day_orders[paid_at.date()] += 1

        if start <= paid_at <= now:
            revenue += amount
            orders += 1
            for item in order.items:
                item_profit = _item_profit(item)
                if item_profit is not None:
                    profit += item_profit
                    costed_revenue += item.quantity * float(item.price_at_time or 0)
                row = by_product.setdefault(item.product_id, {
                    "product_id": item.product_id,
                    "name": item.product.name if item.product else "Deleted product",
                    "slug": item.product.slug if item.product else None,
                    "image_url": item.product.image_url if item.product else None,
                    "units": 0,
                    "revenue": 0.0,
                    "profit": None,
                })
                row["units"] += item.quantity
                row["revenue"] += item.quantity * float(item.price_at_time or 0)
                if item_profit is not None:
                    row["profit"] = (row["profit"] or 0.0) + item_profit
        elif prev_start <= paid_at < start:
            revenue_prev += amount
            orders_prev += 1
            for item in order.items:
                item_profit = _item_profit(item)
                if item_profit is not None:
                    profit_prev += item_profit
                    costed_revenue_prev += item.quantity * float(item.price_at_time or 0)

    revenue_series = []
    for i in range(series_days):
        d = series_start.date() + timedelta(days=i)
        prev_d = d - timedelta(days=series_days)
        revenue_series.append({
            "date": d,
            "revenue": day_revenue.get(d, 0.0),
            "orders": day_orders.get(d, 0),
            "revenue_prev": day_revenue.get(prev_d, 0.0),
        })

    top_products = sorted(by_product.values(), key=lambda r: (-r["units"], -r["revenue"]))[:5]

    # --- Status breakdown (every order placed in the period) -------------
    placed = (
        await db.execute(
            select(Order.status).where(Order.created_at >= start.astimezone(timezone.utc))
        )
    ).scalars().all()
    counts: dict[str, int] = defaultdict(int)
    for s in placed:
        counts[s.value if isinstance(s, OrderStatus) else str(s)] += 1
    status_breakdown = [{"status": s, "count": counts[s]} for s in STATUS_ORDER if counts.get(s)]

    # --- Awaiting dispatch + today's delivery slots ----------------------
    waiting = (
        await db.execute(
            select(Order)
            .options(*_order_options())
            .where(
                or_(
                    Order.status.in_(AWAITING_DISPATCH),
                    and_(Order.status == OrderStatus.PENDING, Order.payment_method == COD),
                )
            )
        )
    ).scalars().all()

    def slot_ended(order: Order) -> bool:
        d = order.delivery
        if d is None:
            return False
        day = _local_delivery_date(d.delivery_date)
        if day is None:
            return False
        if day < today:
            return True
        if day > today or not d.time_slot:
            return False
        bounds = _slot_bounds(d.time_slot, day)
        return bounds is not None and now >= bounds[1]

    awaiting_dispatch = len(waiting)
    overdue_dispatch = sum(1 for o in waiting if slot_ended(o))

    # delivery_date is a UTC ISO string, so a WAT day can start on the
    # previous UTC date: match both prefixes, then filter exactly in Python.
    date_prefixes = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    todays = (
        await db.execute(
            select(Order)
            .options(*_order_options())
            .join(Delivery, Delivery.order_id == Order.id)
            .where(
                or_(*[Delivery.delivery_date.like(f"{p}%") for p in date_prefixes]),
                Order.status != OrderStatus.CANCELLED,
                # Unpaid online checkouts aren't real deliveries yet; COD ones are.
                or_(Order.status.notin_(UNPAID), Order.payment_method == COD),
            )
        )
    ).scalars().all()

    slots: dict[str, list[Order]] = defaultdict(list)
    for order in todays:
        if _local_delivery_date(order.delivery.delivery_date) == today:
            slots[order.delivery.time_slot or "Any time"].append(order)

    todays_deliveries = []
    for slot in sorted(slots):
        group = slots[slot]
        bounds = _slot_bounds(slot, today)
        pending = any(_needs_dispatch(o) for o in group)
        if bounds is None:
            state = "upcoming"
        elif now >= bounds[1]:
            state = "overdue" if pending else "done"
        elif now >= bounds[0]:
            state = "now"
        else:
            state = "upcoming"
        todays_deliveries.append({
            "time_slot": slot,
            "state": state,
            "orders": [_order_row(o) for o in sorted(group, key=lambda o: o.created_at)],
        })

    # --- Stock -----------------------------------------------------------
    low_stock_threshold = await get_low_stock_threshold(db)
    low_rows = (
        await db.execute(
            select(Product)
            .where(Product.is_active == True, Product.stock_quantity <= threshold_expr(low_stock_threshold))  # noqa: E712
            .order_by(Product.stock_quantity.asc(), Product.name.asc())
        )
    ).scalars().all()

    # --- Recent orders ---------------------------------------------------
    recent = (
        await db.execute(
            select(Order).options(*_order_options()).order_by(Order.created_at.desc()).limit(6)
        )
    ).scalars().all()

    aov = revenue / orders if orders else 0.0
    aov_prev = revenue_prev / orders_prev if orders_prev else 0.0

    return {
        "range": range_key,
        "generated_at": now,
        "low_stock_threshold": low_stock_threshold,
        "kpis": {
            "revenue": revenue,
            "revenue_prev": revenue_prev,
            "orders": orders,
            "orders_prev": orders_prev,
            "avg_order_value": aov,
            "avg_order_value_prev": aov_prev,
            # Profit figures are null when no sold item had a known cost.
            "gross_profit": profit if costed_revenue else None,
            "gross_profit_prev": profit_prev if costed_revenue_prev else None,
            "profit_margin": profit / costed_revenue if costed_revenue else None,
            # Share of revenue whose cost is known (1.0 = profit is complete).
            "profit_coverage": costed_revenue / revenue if revenue else None,
            "awaiting_dispatch": awaiting_dispatch,
            "overdue_dispatch": overdue_dispatch,
        },
        "revenue_series": revenue_series,
        "status_breakdown": status_breakdown,
        "todays_deliveries": todays_deliveries,
        "low_stock": [
            {"id": p.id, "name": p.name, "slug": p.slug, "image_url": p.image_url, "stock_quantity": float(p.stock_quantity or 0),
             "low_stock_threshold": effective_threshold(p, low_stock_threshold)}
            for p in low_rows[:5]
        ],
        "low_stock_count": sum(1 for p in low_rows if (p.stock_quantity or 0) > 0),
        "out_of_stock_count": sum(1 for p in low_rows if (p.stock_quantity or 0) <= 0),
        "top_products": top_products,
        "recent_orders": [_order_row(o) for o in recent],
    }
