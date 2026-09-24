import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Union
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Verified against when the email doesn't exist, so a login for an unknown
# account takes as long as one for a real account (no user enumeration by
# response time).
_DUMMY_HASH = pwd_context.hash("not-a-real-password")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def burn_password_check(plain_password: str) -> None:
    pwd_context.verify(plain_password, _DUMMY_HASH)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, Any],
    *,
    scope: str = "customer",
    expires_delta: timedelta = None,
) -> str:
    """
    `scope` keeps the two audiences apart: "customer" tokens work on the
    storefront API, "admin" tokens only on /admin — so a superuser's normal
    shopping login can never act as an admin session.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    claims = {"sub": str(subject), "scope": scope, "type": "access", "iat": now, "exp": expire}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jose.JWTError if invalid/expired."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    """Returns (plaintext for the cookie, sha256 hash for the database)."""
    plain = secrets.token_urlsafe(48)
    return plain, hash_token(plain)


def create_email_token(email: str, purpose: str, hours: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=hours)
    return jwt.encode(
        {"sub": email, "type": purpose, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_email_token(token: str, purpose: str) -> str:
    """Returns the email. Raises jose.JWTError (or ValueError) if invalid/expired/wrong purpose."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if payload.get("type") != purpose or not payload.get("sub"):
        raise ValueError("wrong token purpose")
    return payload["sub"]
