import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ZONE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _blank_to_none(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class StoreDetails(BaseModel):
    store_name: str = Field(min_length=2, max_length=80)
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=30)
    whatsapp_number: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=200)
    pickup_address: str | None = Field(default=None, max_length=200)
    pickup_instructions: str | None = Field(default=None, max_length=500)
    low_stock_threshold: float = Field(default=5, ge=0, le=10000)

    model_config = ConfigDict(from_attributes=True)

    @field_validator(
        "contact_email", "contact_phone", "whatsapp_number", "address",
        "pickup_address", "pickup_instructions", mode="before",
    )
    @classmethod
    def _blank(cls, v):
        return _blank_to_none(v)

    @field_validator("store_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()


class PublicStoreInfo(BaseModel):
    """What the storefront may show: contact and pickup details, nothing internal."""
    store_name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    whatsapp_number: str | None = None
    address: str | None = None
    pickup_address: str | None = None
    pickup_instructions: str | None = None


class DeliveryZoneOut(BaseModel):
    id: str
    name: str
    fee: float
    is_active: bool
    sort_order: int
    orders_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class DeliveryZoneIn(BaseModel):
    # Only used when creating; an existing zone's id never changes because
    # past orders reference it.
    id: str | None = Field(default=None, min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=80)
    fee: float = Field(ge=0, le=1_000_000)
    is_active: bool = True

    @field_validator("id")
    @classmethod
    def _id(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not ZONE_ID_RE.match(v):
            raise ValueError("Zone ID can only use lower-case letters, numbers and single hyphens")
        return v

    @field_validator("name")
    @classmethod
    def _zname(cls, v: str) -> str:
        return v.strip()


class DeliveryZonesUpdate(BaseModel):
    """The full list, in display order. Zones left out are switched off, not deleted."""
    zones: list[DeliveryZoneIn] = Field(min_length=1, max_length=100)


class PaymentStatus(BaseModel):
    provider: str = "paystack"
    configured: bool
    mode: str | None = None  # "test" | "live" | None when not configured
    public_key_hint: str | None = None  # e.g. "pk_live_…a1b2"
    webhook_url: str


class AdminSettingsResponse(BaseModel):
    store: StoreDetails
    zones: list[DeliveryZoneOut]
    payments: PaymentStatus
