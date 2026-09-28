from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActivityEntry(BaseModel):
    id: str
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    entity_label: str | None = None
    summary: str
    changes: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActivityPage(BaseModel):
    items: list[ActivityEntry]
    total: int
