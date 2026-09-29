from fastapi import APIRouter, Depends

from app.core.permissions import enforce_route_permission
from app.api.admin import products, categories, auth, customers, orders, dashboard, inventory, settings, notifications, sales, activity, exports, staff, messages, faqs, pages

admin_router = APIRouter()

# Role check for everything below sign-in (see app/core/permissions.py).
guarded = [Depends(enforce_route_permission)]
admin_router.include_router(auth.router, prefix="/auth", tags=["admin-auth"])
admin_router.include_router(dashboard.router, prefix="/dashboard", tags=["admin-dashboard"], dependencies=guarded)
admin_router.include_router(inventory.router, prefix="/inventory", tags=["admin-inventory"], dependencies=guarded)
admin_router.include_router(notifications.router, prefix="/notifications", tags=["admin-notifications"], dependencies=guarded)
admin_router.include_router(sales.router, prefix="/sales", tags=["admin-sales"], dependencies=guarded)
admin_router.include_router(activity.router, prefix="/activity", tags=["admin-activity"], dependencies=guarded)
admin_router.include_router(exports.router, prefix="/exports", tags=["admin-exports"], dependencies=guarded)
admin_router.include_router(staff.router, prefix="/staff", tags=["admin-staff"], dependencies=guarded)
admin_router.include_router(messages.router, prefix="/messages", tags=["admin-messages"], dependencies=guarded)
admin_router.include_router(faqs.router, prefix="/faqs", tags=["admin-faqs"], dependencies=guarded)
admin_router.include_router(pages.router, prefix="/pages", tags=["admin-pages"], dependencies=guarded)
admin_router.include_router(settings.router, prefix="/settings", tags=["admin-settings"], dependencies=guarded)
admin_router.include_router(products.router, tags=["admin-products"], dependencies=guarded)
admin_router.include_router(categories.router, tags=["admin-categories"], dependencies=guarded)
admin_router.include_router(customers.router, prefix="/customers", tags=["admin-customers"], dependencies=guarded)
admin_router.include_router(orders.router, prefix="/orders", tags=["admin-orders"], dependencies=guarded)
