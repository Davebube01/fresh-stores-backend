"""
Staff roles and what each may do in the admin.

Every admin endpoint is mapped to one permission in ROUTE_PERMISSIONS, and
`enforce_route_permission` checks it for every request under /admin (except
sign-in itself). An endpoint that isn't in the table is refused to everyone
but the owner, so a new route can't quietly become open to cashiers; a test
fails if any admin route is missing from the table.

Change who can do what by editing ROLE_PERMISSIONS.
"""
from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request

from app.models.user import User
from app.utils.dependencies import get_current_active_superuser

OWNER, MANAGER, CASHIER = "owner", "manager", "cashier"
ROLES = (OWNER, MANAGER, CASHIER)

ROLE_LABELS = {OWNER: "Owner", MANAGER: "Manager", CASHIER: "Cashier"}

# Every permission, with what it lets someone do (shown on the Staff page).
PERMISSIONS: dict[str, str] = {
    "dashboard": "See the dashboard (revenue and profit)",
    "products.view": "See products and stock levels",
    "products.edit": "Add, edit and delete products and categories",
    "stock.adjust": "Restock and correct stock",
    "costs.view": "See cost prices and profit",
    "inventory.view": "See the inventory overview and stock log",
    "orders.view": "See online orders",
    "orders.manage": "Move orders along, dispatch and confirm delivery",
    "orders.cancel": "Cancel online orders",
    "sales.create": "Ring up walk-in sales",
    "sales.view": "See walk-in sales and receipts",
    "sales.void": "Void walk-in sales",
    "customers.view": "See customers",
    "customers.manage": "Deactivate and reactivate customers",
    "exports": "Download CSV exports",
    "activity.view": "See the activity log",
    "settings.manage": "Change store details, delivery zones, payments, the FAQ and legal pages",
    "staff.manage": "Add staff and change their roles",
    "notifications": "See low-stock alerts",
    "messages": "Read and answer messages from the Contact page",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    OWNER: set(PERMISSIONS),
    MANAGER: set(PERMISSIONS) - {"settings.manage", "staff.manage"},
    CASHIER: {
        "products.view", "orders.view", "orders.manage", "sales.create", "sales.view", "notifications",
    },
}

# (method, route path) -> permission. Paths are the route templates.
ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    ("GET", "/admin/dashboard"): "dashboard",
    ("GET", "/admin/inventory"): "inventory.view",
    ("GET", "/admin/messages"): "messages",
    ("GET", "/admin/messages/{message_id}"): "messages",
    ("PATCH", "/admin/messages/{message_id}"): "messages",
    ("POST", "/admin/messages/{message_id}/reply"): "messages",
    ("DELETE", "/admin/messages/{message_id}"): "messages",
    ("GET", "/admin/notifications"): "notifications",
    ("POST", "/admin/notifications/read-all"): "notifications",
    ("POST", "/admin/notifications/{notification_id}/read"): "notifications",
    ("GET", "/admin/push/public-key"): "notifications",
    ("POST", "/admin/push/subscribe"): "notifications",
    ("POST", "/admin/push/unsubscribe"): "notifications",
    ("GET", "/admin/sales"): "sales.view",
    ("POST", "/admin/sales"): "sales.create",
    ("GET", "/admin/sales/{sale_id}"): "sales.view",
    ("POST", "/admin/sales/{sale_id}/void"): "sales.void",
    ("PUT", "/admin/sales/till/{day}"): "sales.create",
    ("GET", "/admin/activity"): "activity.view",
    ("GET", "/admin/activity/summary"): "activity.view",
    ("GET", "/admin/exports"): "exports",
    ("GET", "/admin/exports/{dataset}.csv"): "exports",
    ("GET", "/admin/settings"): "settings.manage",
    ("PUT", "/admin/settings/store"): "settings.manage",
    ("PUT", "/admin/settings/zones"): "settings.manage",
    ("GET", "/admin/faqs"): "settings.manage",
    ("PUT", "/admin/faqs"): "settings.manage",
    ("GET", "/admin/pages/{slug}"): "settings.manage",
    ("PUT", "/admin/pages/{slug}"): "settings.manage",
    ("POST", "/admin/upload"): "products.edit",
    ("GET", "/admin/products"): "products.view",
    ("GET", "/admin/products/{product_id}"): "products.view",
    ("POST", "/admin/products"): "products.edit",
    ("PUT", "/admin/products/{product_id}"): "products.edit",
    ("DELETE", "/admin/products/{product_id}"): "products.edit",
    ("POST", "/admin/products/{product_id}/stock"): "stock.adjust",
    ("GET", "/admin/products/{product_id}/stock-movements"): "inventory.view",
    ("GET", "/admin/categories"): "products.view",
    ("POST", "/admin/categories"): "products.edit",
    ("PUT", "/admin/categories/{category_id}"): "products.edit",
    ("DELETE", "/admin/categories/{category_id}"): "products.edit",
    ("GET", "/admin/customers"): "customers.view",
    ("GET", "/admin/customers/summary"): "customers.view",
    ("GET", "/admin/customers/{customer_id}"): "customers.view",
    ("PATCH", "/admin/customers/{customer_id}/status"): "customers.manage",
    ("GET", "/admin/orders/"): "orders.view",
    ("GET", "/admin/orders/summary"): "orders.view",
    ("GET", "/admin/orders/{id}"): "orders.view",
    ("PUT", "/admin/orders/{id}/status"): "orders.manage",
    ("PUT", "/admin/orders/{id}/cancel"): "orders.cancel",
    ("PUT", "/admin/orders/{id}/confirm-delivery"): "orders.manage",
    ("PUT", "/admin/orders/{id}/dispatch"): "orders.manage",
    ("GET", "/admin/staff"): "staff.manage",
    ("POST", "/admin/staff"): "staff.manage",
    ("PUT", "/admin/staff/{staff_id}"): "staff.manage",
    ("POST", "/admin/staff/{staff_id}/reset-password"): "staff.manage",
    ("POST", "/admin/staff/{staff_id}/sign-out"): "staff.manage",
}


def role_of(user: User) -> str:
    # Admin accounts from before roles existed are owners.
    return user.staff_role or OWNER


def permissions_for(user: User) -> set[str]:
    return ROLE_PERMISSIONS.get(role_of(user), set())


def can(user: User, permission: str) -> bool:
    return permission in permissions_for(user)


def _pattern(template: str) -> re.Pattern:
    parts = re.split(r"(\{[^}]+\})", template)
    return re.compile("".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts) + "$")


# Matched against the request URL itself, so the check doesn't depend on how a
# FastAPI version reports the matched route. Fewer path parameters = more
# specific ("/admin/orders/summary" before "/admin/orders/{id}").
_COMPILED = sorted(
    ((method, _pattern(path), permission, path.count("{")) for (method, path), permission in ROUTE_PERMISSIONS.items()),
    key=lambda row: row[3],
)


def permission_for(method: str, path: str) -> str | None:
    for m, pattern, permission, _ in _COMPILED:
        if m == method and pattern.match(path):
            return permission
    return None


async def enforce_route_permission(request: Request, admin: User = Depends(get_current_active_superuser)) -> User:
    path = request.url.path
    root = request.scope.get("root_path") or ""
    if root and path.startswith(root):
        path = path[len(root):]
    permission = permission_for(request.method, path)
    allowed = can(admin, permission) if permission else role_of(admin) == OWNER
    if not allowed:
        raise HTTPException(status_code=403, detail="Your role doesn't allow this. Ask the store owner.")
    return admin
