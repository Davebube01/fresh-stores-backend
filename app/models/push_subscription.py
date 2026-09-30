import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class PushSubscription(Base):
    """
    One browser's Web Push subscription for one staff member. A staff member
    signed in on several devices has several rows. `endpoint` (the push
    service URL the browser generated) is unique — re-subscribing the same
    browser updates its row instead of creating a duplicate.
    """
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String, unique=True, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User")
