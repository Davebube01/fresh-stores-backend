from fastapi import APIRouter

from app.api.v1 import auth, products, cart, orders, payments, categories, delivery, store, cart_check, account

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(account.session_router, prefix="/auth", tags=["auth"])
api_router.include_router(account.router, prefix="/account", tags=["account"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
# Before cart.router so /cart/check isn't taken for a cart id.
api_router.include_router(cart_check.router, prefix="/cart", tags=["cart"])
api_router.include_router(cart.router, prefix="/cart", tags=["cart"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(delivery.router, prefix="/delivery", tags=["delivery"])
api_router.include_router(store.router, prefix="/store", tags=["store"])
