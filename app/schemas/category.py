import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime

# Products reference their category by slug, and it appears in storefront
# URLs, so keep it to lower-case words joined by single hyphens.
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _clean_slug(value: str) -> str:
    value = value.strip().lower()
    if not SLUG_RE.match(value):
        raise ValueError("Slug can only use lower-case letters, numbers and single hyphens (e.g. goat-parts)")
    return value


class CategoryBase(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    slug: str = Field(min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return _clean_slug(v)


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    slug: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else v

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        return _clean_slug(v) if v is not None else v


class CategoryResponse(CategoryBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    # Responses echo stored data; don't re-validate legacy slugs on the way out.
    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        return v


class AdminCategoryResponse(CategoryResponse):
    # How many products (active or not) are filed under this category.
    product_count: int = 0
