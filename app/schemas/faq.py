from typing import Literal

from pydantic import BaseModel, Field, field_validator

Section = Literal["ordering", "delivery", "payment", "account"]
SECTION_LABELS = {
    "ordering": "Ordering",
    "delivery": "Delivery and pickup",
    "payment": "Payment",
    "account": "Your account",
}


class FaqOut(BaseModel):
    id: str | None = None  # None for the built-in defaults
    section: Section
    question: str
    answer: str
    is_published: bool = True

    model_config = {"from_attributes": True}


class FaqIn(BaseModel):
    id: str | None = None
    section: Section
    question: str = Field(min_length=5, max_length=200)
    answer: str = Field(min_length=5, max_length=2000)
    is_published: bool = True

    @field_validator("question", "answer")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class FaqUpdate(BaseModel):
    # In display order; position comes from the index. Hide a question
    # rather than deleting them all: an empty list would bring back the defaults.
    items: list[FaqIn] = Field(min_length=1, max_length=100)


class FaqAdminList(BaseModel):
    items: list[FaqOut]
    # True while the store hasn't saved its own list yet.
    is_default: bool
