from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: str
    kind: str
    title: str
    body: str | None = None
    link: str | None = None
    product_id: str | None = None
    read_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationList(BaseModel):
    unread_count: int
    items: list[NotificationResponse]
