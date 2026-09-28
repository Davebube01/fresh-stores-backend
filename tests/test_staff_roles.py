import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.cache import clear_product_caches
from app.core.limiter import limiter
from app.core.permissions import ROUTE_PERMISSIONS
from app.core.security import get_password_hash
from app.main import app
from app.models.product import Product
from app.models.user import User
from app.utils.dependencies import get_current_active_superuser


@pytest.fixture(autouse=True)
def _fresh():
    clear_product_caches()
    limiter.reset()
    yield
    clear_product_caches()
    app.dependency_overrides.pop(get_current_active_superuser, None)


def act_as(role: str | None, user_id: str = "u-1"):
    app.dependency_overrides[get_current_active_superuser] = lambda: User(
        id=user_id, email=f"{role}@test.com", full_name=f"{role} person", hashed_password="x",
        is_superuser=True, is_active=True, staff_role=role,
    )


@pytest_asyncio.fixture
async def product(session_factory):
    async with session_factory() as db:
        db.add(Product(id="head", name="Goat Head", slug="goat-head", price=4500, category="goat-parts",
                       stock_quantity=10, cost_price=3000))
        await db.commit()


def _admin_routes():
    """(method, full path) for every admin route, whether or not this FastAPI version nests included routers."""
    from app.api.admin.api import admin_router
    for route in admin_router.routes:
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            yield method, "/admin" + route.path


def test_every_admin_route_has_a_permission():
    missing = [f"{m} {p}" for m, p in _admin_routes()
               if not p.startswith("/admin/auth") and (m, p) not in ROUTE_PERMISSIONS]
    assert missing == []


def test_specific_paths_win_over_parameters():
    from app.core.permissions import permission_for
    assert permission_for("GET", "/admin/orders/summary") == "orders.view"
    assert permission_for("POST", "/admin/sales/abc-123/void") == "sales.void"
    assert permission_for("GET", "/admin/exports/orders.csv") == "exports"
    assert permission_for("GET", "/admin/nope") is None


@pytest.mark.asyncio
async def test_cashier_can_sell_but_not_see_money_or_void(client: AsyncClient, product):
    act_as("cashier")
    sale = await client.post("/admin/sales", json={"payment_method": "cash", "items": [{"product_id": "head"}]})
    assert sale.status_code == 201
    assert (await client.get(f"/admin/sales/{sale.json()['id']}")).status_code == 200
    assert (await client.get("/admin/orders/")).status_code == 200

    listed = (await client.get("/admin/products")).json()
    assert listed[0]["cost_price"] is None  # hidden, not just absent from the UI
    assert (await client.get("/admin/products/head")).json()["cost_price"] is None

    denied = [
        ("POST", f"/admin/sales/{sale.json()['id']}/void", {"reason": "Oops"}),
        ("GET", "/admin/dashboard", None),
        ("GET", "/admin/exports/orders.csv", None),
        ("POST", "/admin/products/head/stock", {"change": 5, "reason": "restock"}),
        ("PUT", "/admin/products/head", {"price": 1}),
        ("GET", "/admin/staff", None),
        ("GET", "/admin/activity", None),
        ("GET", "/admin/settings", None),
        ("GET", "/admin/customers", None),
    ]
    for method, path, body in denied:
        res = await client.request(method, path, json=body)
        assert res.status_code == 403, (method, path)
        assert res.json()["detail"] == "Your role doesn't allow this. Ask the store owner."


@pytest.mark.asyncio
async def test_manager_runs_the_shop_but_not_staff_or_settings(client: AsyncClient, product):
    act_as("manager")
    sale = (await client.post("/admin/sales", json={"payment_method": "pos", "items": [{"product_id": "head"}]})).json()
    assert (await client.post(f"/admin/sales/{sale['id']}/void", json={"reason": "Returned"})).status_code == 200
    assert (await client.get("/admin/products/head")).json()["cost_price"] == 3000
    assert (await client.get("/admin/dashboard")).status_code == 200
    assert (await client.get("/admin/staff")).status_code == 403
    assert (await client.get("/admin/settings")).status_code == 403


@pytest.mark.asyncio
async def test_old_admin_accounts_are_owners(client: AsyncClient):
    act_as(None)
    assert (await client.get("/admin/staff")).status_code == 200


@pytest.mark.asyncio
async def test_owner_adds_staff_who_can_sign_in_with_their_role(client: AsyncClient, session_factory):
    act_as("owner", user_id="owner-1")
    res = await client.post("/admin/staff", json={
        "email": "Kemi@Shop.com", "full_name": "Kemi Ade", "role": "cashier", "password": "counter-2026",
    })
    assert res.status_code == 201, res.text
    kemi = res.json()
    assert (kemi["email"], kemi["role"], kemi["is_active"]) == ("kemi@shop.com", "cashier", True)
    dup = await client.post("/admin/staff", json={"email": "kemi@shop.com", "full_name": "Kem", "role": "manager",
                                                   "password": "whatever-123"})
    assert dup.status_code == 409
    app.dependency_overrides.pop(get_current_active_superuser)

    # Real sign-in: the new account gets a cashier's permissions.
    login = await client.post("/admin/auth/login", json={"email": "kemi@shop.com", "password": "counter-2026"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = (await client.get("/admin/auth/me", headers=headers)).json()
    assert me["role"] == "cashier"
    assert "sales.create" in me["permissions"] and "sales.void" not in me["permissions"]
    assert (await client.get("/admin/dashboard", headers=headers)).status_code == 403

    # They change the password the owner gave them.
    bad = await client.post("/admin/auth/change-password", headers=headers,
                            json={"current_password": "wrong-pass", "new_password": "my-own-pass-1"})
    assert bad.status_code == 400
    ok = await client.post("/admin/auth/change-password", headers=headers,
                           json={"current_password": "counter-2026", "new_password": "my-own-pass-1"})
    assert ok.status_code == 204
    assert (await client.post("/admin/auth/login", json={"email": "kemi@shop.com", "password": "my-own-pass-1"})).status_code == 200

    # Deactivated: can't sign in any more.
    act_as("owner", user_id="owner-1")
    assert (await client.put(f"/admin/staff/{kemi['id']}", json={"is_active": False})).json()["is_active"] is False
    app.dependency_overrides.pop(get_current_active_superuser)
    assert (await client.post("/admin/auth/login", json={"email": "kemi@shop.com", "password": "my-own-pass-1"})).status_code == 400

    # Owner resets it and reactivates.
    act_as("owner", user_id="owner-1")
    assert (await client.post(f"/admin/staff/{kemi['id']}/reset-password", json={"password": "fresh-start-9"})).status_code == 204
    await client.put(f"/admin/staff/{kemi['id']}", json={"is_active": True, "role": "manager"})
    app.dependency_overrides.pop(get_current_active_superuser)
    login = await client.post("/admin/auth/login", json={"email": "kemi@shop.com", "password": "fresh-start-9"})
    me = (await client.get("/admin/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})).json()
    assert me["role"] == "manager"


@pytest.mark.asyncio
async def test_owner_guard_rails(client: AsyncClient, session_factory):
    async with session_factory() as db:
        db.add_all([
            User(id="owner-1", email="o@test.com", hashed_password=get_password_hash("x" * 8), is_superuser=True,
                 staff_role="owner", full_name="Only Owner"),
            User(id="cust", email="c@test.com", hashed_password="x", is_superuser=False),
        ])
        await db.commit()
    act_as("owner", user_id="owner-1")

    own = await client.put("/admin/staff/owner-1", json={"role": "manager"})
    assert (own.status_code, own.json()["detail"]) == (400, "You can't change your own role")
    off = await client.put("/admin/staff/owner-1", json={"is_active": False})
    assert off.json()["detail"] == "You can't deactivate your own account"

    # Another owner trying to demote the only other owner... add one, then demote the first.
    second = (await client.post("/admin/staff", json={"email": "o2@test.com", "full_name": "Second", "role": "owner",
                                                      "password": "second-owner"})).json()
    act_as("owner", user_id=second["id"])
    assert (await client.put("/admin/staff/owner-1", json={"role": "manager"})).status_code == 200
    # Now owner-1 (a manager) is gone as an owner; the second can't be removed by anyone.
    act_as("owner", user_id="someone-else")
    last = await client.put(f"/admin/staff/{second['id']}", json={"is_active": False})
    assert (last.status_code, last.json()["detail"]) == (400, "The store needs at least one active owner")

    # Customers aren't staff.
    assert (await client.put("/admin/staff/cust", json={"role": "owner"})).status_code == 404
    staff = (await client.get("/admin/staff")).json()
    assert sorted(s["email"] for s in staff["staff"]) == ["o2@test.com", "o@test.com"]
    assert {r["key"] for r in staff["roles"]} == {"owner", "manager", "cashier"}
