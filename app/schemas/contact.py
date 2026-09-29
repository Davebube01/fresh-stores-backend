from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Topic = Literal["order", "delivery", "bulk", "feedback", "other"]
TOPIC_LABELS = {
    "order": "An order",
    "delivery": "Delivery",
    "bulk": "Bulk or event order",
    "feedback": "Feedback",
    "other": "Something else",
}


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    topic: Topic = "other"
    order_ref: str | None = Field(default=None, max_length=64)
    message: str = Field(min_length=10, max_length=3000)
    # Honeypot: hidden from people, filled in by bots. Anything here = drop it.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("name", "message")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone", "order_ref")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class ContactReplyOut(BaseModel):
    id: str
    body: str
    sent_by: str | None = None
    sent_at: datetime

    model_config = {"from_attributes": True}


class ContactOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    topic: str
    order_ref: str | None = None
    message: str
    user_id: str | None = None
    status: str
    handled_at: datetime | None = None
    handled_by: str | None = None
    created_at: datetime
    replies: list[ContactReplyOut] = []
    # The order the customer mentioned, when order_ref matches one.
    order_id: str | None = None

    model_config = {"from_attributes": True}


class ContactReplyIn(BaseModel):
    body: str = Field(min_length=2, max_length=5000)
    # Replying usually settles it; untick to keep it in New.
    mark_handled: bool = True

    @field_validator("body")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ContactStatusUpdate(BaseModel):
    status: Literal["new", "handled"]


class ContactInbox(BaseModel):
    messages: list[ContactOut]
    new_count: int
    handled_count: int
