import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class ActivityLog(Base):
    """
    Who did what in the admin, and when: product and price edits, stock
    adjustments, order actions, counter sales, settings changes, sign-ins.
    Append-only; nothing updates or deletes these rows.
    """
    __tablename__ = "activity_log"

    id = Column(String, primary_key=True, default=generate_uuid)
    actor_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    # Snapshotted so the log still reads right if the account is renamed.
    actor_name = Column(String, nullable=True)
    # e.g. "product.updated", "order.cancelled", "sale.voided"
    action = Column(String, nullable=False, index=True)
    # "product" | "category" | "order" | "sale" | "settings" | "admin"
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=True, index=True)
    entity_label = Column(String, nullable=True)
    summary = Column(String, nullable=False)
    # For edits: {"field": {"from": old, "to": new}, ...}
    changes = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
