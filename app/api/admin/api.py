from fastapi import APIRouter
from app.api.admin import products, categories, auth, customers, orders, dashboard

admin_router = APIRouter()
admin_router.include_router(auth.router, prefix="/auth", tags=["admin-auth"])
admin_router.include_router(dashboard.router, prefix="/dashboard", tags=["admin-dashboard"])
admin_router.include_router(products.router, tags=["admin-products"])
admin_router.include_router(categories.router, tags=["admin-categories"])
admin_router.include_router(customers.router, prefix="/customers", tags=["admin-customers"])
admin_router.include_router(orders.router, prefix="/orders", tags=["admin-orders"])
