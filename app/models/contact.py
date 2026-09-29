import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class ContactMessage(Base):
    """A message sent from the storefront's Contact page."""
    __tablename__ = "contact_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    # "order" | "delivery" | "bulk" | "feedback" | "other"
    topic = Column(String, nullable=False, default="other")
    order_ref = Column(String, nullable=True)
    message = Column(String, nullable=False)
    # Set when a signed-in customer sent it.
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # "new" | "handled"
    status = Column(String, nullable=False, default="new", index=True)
    handled_at = Column(DateTime(timezone=True), nullable=True)
    handled_by = Column(String, nullable=True)  # admin's name, for the record
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    replies = relationship(
        "ContactReply", back_populates="message", order_by="ContactReply.sent_at",
        cascade="all, delete-orphan", lazy="selectin",
    )


class ContactReply(Base):
    """A reply the store emailed from the admin inbox."""
    __tablename__ = "contact_replies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String, ForeignKey("contact_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    body = Column(String, nullable=False)
    sent_by = Column(String, nullable=True)  # admin's name, for the record
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    message = relationship("ContactMessage", back_populates="replies")
