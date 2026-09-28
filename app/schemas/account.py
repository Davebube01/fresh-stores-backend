from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.user import _validate_password, normalize_ng_phone


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    phone: str | None = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Enter your full name")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return normalize_ng_phone(v)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new(cls, v: str) -> str:
        return _validate_password(v)


class AddressIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    zone_id: str = Field(min_length=1, max_length=60)
    address: str = Field(min_length=5, max_length=200)
    apartment: str | None = Field(default=None, max_length=80)
    landmark: str | None = Field(default=None, max_length=120)
    instructions: str | None = Field(default=None, max_length=160)
    is_default: bool = False

    @field_validator("label", "address")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("apartment", "landmark", "instructions")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class AddressOut(AddressIn):
    id: str
    zone_name: str | None = None
    # Current estimated courier fee for the zone; null if the zone was switched off.
    zone_fee: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
