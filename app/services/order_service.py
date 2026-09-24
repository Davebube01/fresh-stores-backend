from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.cache import clear_product_caches
from app.core.delivery_zones import get_zone_fee
from app.crud.order import create_order, create_order_item, create_delivery
from app.crud.cart import get_cart
from app.schemas.order import OrderCreate

async def process_checkout(db: AsyncSession, order_in: OrderCreate, user_id: Optional[str] = None):
    # This service handles the complex logic of assembling an order from a cart or directly from items
    subtotal = 0.0
    items_to_create = []
    product_names: dict[str, str] = {}

    if order_in.cart_id:
        # Checkout from cart
        cart = await get_cart(db, order_in.cart_id)
        if not cart or not cart.items:
            raise ValueError("Cart is empty or not found")

        for item in cart.items:
            subtotal += item.product.price * item.quantity
            product_names[item.product_id] = item.product.name
            items_to_create.append({
                "product_id": item.product_id,
                "quantity": item.quantity,
                "price_at_time": item.product.price,
                "selected_option": item.selected_option
            })
    elif order_in.items:
        # Checkout directly with items
        from app.crud.product import get_product
        for item in order_in.items:
            product = await get_product(db, item.product_id)
            if not product:
                raise ValueError(f"Product {item.product_id} not found")
            subtotal += product.price * item.quantity
            product_names[item.product_id] = product.name
            items_to_create.append({
                "product_id": item.product_id,
                "quantity": item.quantity,
                "price_at_time": product.price,
                "selected_option": item.selected_option
            })
    else:
        raise ValueError("No items provided for checkout")

    # Delivery fee is an ESTIMATE only, looked up server-side from the zone
    # the customer picked — never trust the client-sent value, and never
    # charge it online. The courier is paid in cash, directly, on delivery.
    delivery_fee = 0.0
    if getattr(order_in, "delivery_method", "delivery") != "pickup" and order_in.delivery_info:
        delivery_fee = get_zone_fee(order_in.delivery_info.deliveryZone)

    # What's actually charged online is the product total only.
    total_amount = subtotal

    # 1. Create the order first so its id exists for the stock movements
    # reserved below to reference — that's what lets the restock-history
    # audit trail point back to the order that caused each decrement.
    order = await create_order(
        db=db,
        order_in=order_in,
        user_id=user_id,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total_amount=total_amount
    )

    # Reserve stock atomically now that the order exists. Each decrement
    # only succeeds if enough stock remains at that exact moment, so this
    # is safe under concurrent checkouts racing for the same last unit.
    # Nothing here is committed yet, so a failure partway through rolls
    # back cleanly — no compensating "give it back" logic needed for the
    # items already decremented in this same loop.
    from app.crud.product import decrement_stock
    for item_data in items_to_create:
        reserved = await decrement_stock(db, item_data["product_id"], item_data["quantity"], order_id=order.id)
        if not reserved:
            await db.rollback()
            # The order row itself was already committed above (before we
            # knew stock would run out), so it has to be explicitly removed
            # here too — otherwise a failed checkout leaves an orphaned,
            # item-less "pending" order behind.
            await db.delete(order)
            await db.commit()
            name = product_names.get(item_data["product_id"], item_data["product_id"])
            raise ValueError(f"{name} doesn't have enough stock for this order")

    # 2. Create order items
    for item_data in items_to_create:
        await create_order_item(db=db, order_id=order.id, **item_data)
        
    # 3. Create delivery info if present
    if order_in.delivery_info and getattr(order_in, "delivery_method", "delivery") != "pickup":
        delivery_data = order_in.delivery_info.model_dump()
        # Some mapping might be needed if frontend schema differs from delivery model
        mapped_delivery_data = {
            "address": delivery_data.get("address"),
            "apartment": delivery_data.get("apartment"),
            "city": delivery_data.get("city"),
            "state": delivery_data.get("state"),
            "landmark": delivery_data.get("landmark"),
            "zip_code": delivery_data.get("zipCode"),
            "instructions": delivery_data.get("instructions"),
            "delivery_zone": delivery_data.get("deliveryZone"),
            "delivery_date": delivery_data.get("deliveryDate"),
            "time_slot": delivery_data.get("timeSlot")
        }
        await create_delivery(db=db, order_id=order.id, delivery_info=mapped_delivery_data)
        
    # Optional: Clear the cart if cart_id was provided
    if order_in.cart_id:
        from app.crud.cart import get_cart
        cart = await get_cart(db, order_in.cart_id)
        if cart:
            for item in cart.items:
                await db.delete(item)
            await db.commit()

    # Stock changed — the public product cache would otherwise keep serving
    # a now-inaccurate stock level for up to its TTL.
    clear_product_caches()

    # Re-fetch order to get relationships loaded
    from app.crud.order import get_order
    return await get_order(db, order.id)
