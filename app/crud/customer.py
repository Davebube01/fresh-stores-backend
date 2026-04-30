from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.user import User
from app.models.order import Order
from app.schemas.customer import CustomerResponse

async def get_admin_customers(db: AsyncSession):
    # Fetch all non-superuser users
    query = select(User).where(User.is_superuser == False)
    result = await db.execute(query)
    users = result.scalars().all()
    
    customers = []
    for user in users:
        # Get orders count and total spent for successful orders
        # (Assuming for now anything not 'cancelled' counts)
        order_query = select(
            func.count(Order.id).label("ordersCount"),
            func.sum(Order.total_amount).label("totalSpent")
        ).where(
            Order.user_id == user.id,
            Order.status != "cancelled"
        )
        order_result = await db.execute(order_query)
        stats = order_result.first()
        
        customers.append({
            "id": user.id,
            "name": user.full_name or user.email.split("@")[0],
            "email": user.email,
            "phone": user.phone,
            "avatar": user.avatar_url,
            "address": user.address,
            "joinDate": user.created_at,
            "ordersCount": stats.ordersCount or 0,
            "totalSpent": float(stats.totalSpent or 0.0),
            "status": "active" if user.is_active else "inactive"
        })
    
    return customers

async def get_admin_customer_by_id(db: AsyncSession, customer_id: str):
    query = select(User).where(User.id == customer_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        return None
        
    order_query = select(
        func.count(Order.id).label("ordersCount"),
        func.sum(Order.total_amount).label("totalSpent")
    ).where(
        Order.user_id == user.id,
        Order.status != "cancelled"
    )
    order_result = await db.execute(order_query)
    stats = order_result.first()
    
    # Get recent orders
    recent_orders_query = select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(10)
    recent_orders_result = await db.execute(recent_orders_query)
    recent_orders = recent_orders_result.scalars().all()
    
    return {
        "id": user.id,
        "name": user.full_name or user.email.split("@")[0],
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar_url,
        "address": user.address,
        "joinDate": user.created_at,
        "ordersCount": stats.ordersCount or 0,
        "totalSpent": float(stats.totalSpent or 0.0),
        "status": "active" if user.is_active else "inactive",
        "orders": recent_orders
    }
