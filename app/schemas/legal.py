from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LegalSlug = Literal["terms", "privacy"]


class LegalPageOut(BaseModel):
    slug: LegalSlug
    title: str
    # Formatted text: "## " headings, "- " bullets, blank lines between paragraphs.
    body: str
    updated_at: datetime
    is_default: bool


class LegalPageAdmin(LegalPageOut):
    updated_by: str | None = None
    # The default text, with {placeholders}, for "reset to default".
    default_body: str


class LegalPageUpdate(BaseModel):
    body: str = Field(min_length=200, max_length=40000)
