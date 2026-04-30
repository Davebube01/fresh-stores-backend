from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.order import create_order, create_order_item, create_delivery
from app.crud.cart import get_cart
from app.schemas.order import OrderCreate

async def process_checkout(db: AsyncSession, order_in: OrderCreate, user_id: Optional[str] = None):
    # This service handles the complex logic of assembling an order from a cart or directly from items
    subtotal = 0.0
    items_to_create = []
    
    if order_in.cart_id:
        # Checkout from cart
        cart = await get_cart(db, order_in.cart_id)
        if not cart or not cart.items:
            raise ValueError("Cart is empty or not found")
        
        for item in cart.items:
            subtotal += item.product.price * item.quantity
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
            items_to_create.append({
                "product_id": item.product_id,
                "quantity": item.quantity,
                "price_at_time": product.price,
                "selected_option": item.selected_option
            })
    else:
        raise ValueError("No items provided for checkout")

    delivery_fee = order_in.delivery_info.deliveryFee if order_in.delivery_info else 0.0
    if getattr(order_in, "delivery_method", "delivery") == "pickup":
        delivery_fee = 0.0
        
    total_amount = subtotal + delivery_fee
    
    # 1. Create the order
    order = await create_order(
        db=db, 
        order_in=order_in, 
        user_id=user_id, 
        subtotal=subtotal, 
        delivery_fee=delivery_fee, 
        total_amount=total_amount
    )
    
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

    # Re-fetch order to get relationships loaded
    from app.crud.order import get_order
    return await get_order(db, order.id)
