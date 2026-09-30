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
    # Worth a second look (voids, cancellations, deletions, staff changes, exports).
    flagged: bool = False
    # Where its subject lives in the admin, if it still exists.
    link: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ActivityPage(BaseModel):
    items: list[ActivityEntry]
    total: int


class ActivityActor(BaseModel):
    id: str
    name: str
    count: int


class ActivitySummary(BaseModel):
    total: int
    flagged: int
    types: dict[str, int]
    actors: list[ActivityActor]
