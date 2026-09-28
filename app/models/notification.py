import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class AdminNotification(Base):
    """
    Something the admin should look at, shown under the bell in the admin
    header. Written in the same transaction as the change that caused it, so
    a rolled-back checkout never leaves a stray alert behind.
    """
    __tablename__ = "admin_notifications"

    id = Column(String, primary_key=True, default=generate_uuid)
    # "low_stock" | "out_of_stock"
    kind = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    body = Column(String, nullable=True)
    # Admin page to open, e.g. "/admin/products/goat-leg".
    link = Column(String, nullable=True)
    # Not a foreign key: alerts shouldn't stop a product being deleted.
    product_id = Column(String, nullable=True, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
