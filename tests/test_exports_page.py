from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.main import app
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.services.export_service import _cell
from app.utils.dependencies import get_current_active_superuser


def act_as(role: str):
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id=role, email=f"{role}@x.com", full_name=role.title(), is_superuser=True, staff_role=role)


@pytest_asyncio.fixture
async def data(session_factory):
    async with session_factory() as db:
        db.add_all([
            Product(id="leg", name="=HYPERLINK(\"http://evil\")", slug="goat-leg", price=18000, category="goat-parts",
                    stock_quantity=4, cost_price=12000),
            User(id="gone", email="deleted-gone@deleted.invalid", full_name="Deleted customer", hashed_password="x",
                 is_active=False, deleted_at=datetime.now(timezone.utc)),
            User(id="amaka", email="amaka@example.com", full_name="@Amaka", hashed_password="x"),
        ])
        o = Order(id="o-gone", user_id="gone", status=OrderStatus.DELIVERED, total_amount=18000, subtotal=18000)
        o.items.append(OrderItem(product_id="leg", quantity=1, price_at_time=18000))
        db.add(o)
        await db.commit()
    yield
    app.dependency_overrides.pop(get_current_active_superuser, None)


def test_cells_that_would_run_as_formulas_are_neutralised():
    assert _cell("=SUM(A1)") == "'=SUM(A1)"
    assert _cell("+2348031234567") == "+2348031234567"  # a plain number stays a number
    assert _cell("-2") == "-2" and _cell("@Amaka") == "'@Amaka" and _cell("-risky") == "'-risky"
    assert _cell("Goat Leg") == "Goat Leg" and _cell(5) == 5


@pytest.mark.asyncio
async def test_csv_has_no_live_formulas_or_deleted_emails(client: AsyncClient, data):
    act_as("owner")
    products = (await client.get("/admin/exports/products.csv")).text
    assert "'=HYPERLINK" in products and ',=HYPERLINK' not in products
    customers = (await client.get("/admin/exports/customers.csv")).text
    assert "'@Amaka" in customers and "deleted.invalid" not in customers
    orders = (await client.get("/admin/exports/orders.csv")).text
    assert "Deleted customer" in orders and "deleted.invalid" not in orders


@pytest.mark.asyncio
async def test_catalogue_counts_and_role_limits(client: AsyncClient, data):
    act_as("owner")
    listing = (await client.get("/admin/exports")).json()
    rows = {d["key"]: d["rows"] for d in listing["datasets"]}
    assert rows == {"orders": 1, "sale_lines": 1, "stock_movements": 0, "activity": 0, "products": 1, "customers": 1}
    assert next(d for d in listing["datasets"] if d["key"] == "orders")["columns"][:2] == ["Date", "Order"]
    assert (await client.get("/admin/exports", params={"date_from": "2020-01-01", "date_to": "2020-01-31"})).json()["datasets"][0]["rows"] == 0

    # Download shows up under recent downloads.
    await client.get("/admin/exports/products.csv")
    recent = (await client.get("/admin/exports")).json()["recent"]
    assert recent and recent[0]["by"] == "Owner" and recent[0]["file"].startswith("products-")

    # A manager may export (it's in their role) and sees everything they can see in the admin.
    act_as("manager")
    assert {d["key"] for d in (await client.get("/admin/exports")).json()["datasets"]} == set(rows)
    # Cashiers can't export at all.
    act_as("cashier")
    assert (await client.get("/admin/exports")).status_code == 403
    assert (await client.get("/admin/exports/customers.csv")).status_code == 403
