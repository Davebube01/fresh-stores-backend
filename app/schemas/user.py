import re
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from datetime import datetime

# Nigerian mobile numbers: 0803..., +234803..., or 234803... — network prefix
# 7/8/9 followed by 0/1, then 8 more digits.
_NG_PHONE = re.compile(r"^(?:\+?234|0)([789][01]\d{8})$")

# bcrypt silently ignores/errors past 72 bytes, so cap it rather than let a
# long password get truncated without the user knowing.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8


def normalize_ng_phone(value: str) -> str:
    """Returns the local 11-digit form (0803 123 4567 -> 08031234567)."""
    cleaned = re.sub(r"[\s\-()]", "", value)
    match = _NG_PHONE.match(cleaned)
    if not match:
        raise ValueError("Enter a valid Nigerian phone number, e.g. 0803 123 4567")
    return "0" + match.group(1)


def _validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long")
    return value


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None
    address: str | None = None
    avatar_url: str | None = None

class UserCreate(UserBase):
    password: str

class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str
    password: str

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Enter your full name")
        return v

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        return normalize_ng_phone(v)

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password(v)

class UserLogin(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.strip().lower()

class UserResponse(UserBase):
    id: str
    is_active: bool
    is_superuser: bool
    email_verified: bool = False
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
    
class Token(BaseModel):
    access_token: str
    token_type: str

class AuthResponse(Token):
    user: UserResponse

class VerifyEmailRequest(BaseModel):
    token: str

class TokenData(BaseModel):
    email: str | None = None
