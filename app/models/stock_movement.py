import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class StockMovement(Base):
    """
    One row per change to a product's stock_quantity — the audit trail the
    raw number on Product doesn't give you. Written by the same atomic
    UPDATE that changes the stock, via RETURNING, so the before/after
    snapshot here always matches what actually landed even under
    concurrent writers.
    """
    __tablename__ = "stock_movements"

    id = Column(String, primary_key=True, default=generate_uuid)
    product_id = Column(String, ForeignKey("products.id"), nullable=False, index=True)

    # Positive for stock added, negative for stock removed.
    change = Column(Float, nullable=False)
    previous_quantity = Column(Float, nullable=False)
    new_quantity = Column(Float, nullable=False)

    # "order_placed" | "order_cancelled" | "restock" | "correction"
    reason = Column(String, nullable=False)
    note = Column(String, nullable=True)

    # Populated for order-driven movements; null for manual admin changes.
    order_id = Column(String, ForeignKey("orders.id"), nullable=True)
    # Populated for manual admin changes; null for order-driven movements.
    admin_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
