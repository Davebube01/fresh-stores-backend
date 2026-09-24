from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models.user import User
from app.models.order import Order
from app.schemas.customer import CustomerResponse

async def get_admin_customers(db: AsyncSession, skip: int = 0, limit: int = 100):
    # Pre-aggregate order stats per user in one query, then LEFT JOIN it onto
    # users, instead of running a separate stats query per user (N+1).
    order_stats = (
        select(
            Order.user_id.label("user_id"),
            func.count(Order.id).label("orders_count"),
            func.sum(Order.total_amount).label("total_spent"),
        )
        .where(Order.status != "cancelled")
        .group_by(Order.user_id)
        .subquery()
    )

    query = (
        select(
            User,
            func.coalesce(order_stats.c.orders_count, 0).label("orders_count"),
            func.coalesce(order_stats.c.total_spent, 0.0).label("total_spent"),
        )
        .outerjoin(order_stats, order_stats.c.user_id == User.id)
        .where(User.is_superuser == False)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)

    customers = []
    for user, orders_count, total_spent in result.all():
        customers.append({
            "id": user.id,
            "name": user.full_name or user.email.split("@")[0],
            "email": user.email,
            "phone": user.phone,
            "avatar": user.avatar_url,
            "address": user.address,
            "joinDate": user.created_at,
            "ordersCount": orders_count or 0,
            "totalSpent": float(total_spent or 0.0),
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
    recent_orders_query = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(10)
    )
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
        "recent_orders": [
            {
                "id": o.id,
                "status": getattr(o.status, "value", o.status),
                "total_amount": o.total_amount,
                "created_at": o.created_at,
                "items": [{"id": i.id, "quantity": i.quantity} for i in o.items],
            }
            for o in recent_orders
        ],
    }
