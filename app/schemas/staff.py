from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.core.permissions import permissions_for, role_of
from app.schemas.user import _validate_password

StaffRole = Literal["owner", "manager", "cashier"]


class AdminUserResponse(BaseModel):
    """The signed-in admin, with what their role lets them do (drives the admin UI)."""
    id: str
    email: str
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    staff_role: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def role(self) -> str:
        return role_of(self)

    @computed_field
    @property
    def permissions(self) -> list[str]:
        return sorted(permissions_for(self))


class AdminAuthResponse(BaseModel):
    access_token: str
    token_type: str
    user: AdminUserResponse


class StaffMember(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    phone: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    last_signed_in_at: datetime | None = None


class RoleInfo(BaseModel):
    key: str
    label: str
    permissions: list[str]


class StaffList(BaseModel):
    staff: list[StaffMember]
    roles: list[RoleInfo]
    # permission -> what it lets someone do
    permissions: dict[str, str]


class StaffCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    role: StaffRole
    # A first password the owner hands over; the staff member changes it after signing in.
    password: str

    _password = field_validator("password")(lambda cls, v: _validate_password(v))


class StaffUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    role: StaffRole | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str

    _password = field_validator("password")(lambda cls, v: _validate_password(v))


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    _password = field_validator("new_password")(lambda cls, v: _validate_password(v))
