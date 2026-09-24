from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.crud.refresh_token import issue_refresh_token, rotate_refresh_token, revoke_session
from app.crud.user import get_user
from app.models.user import User


@dataclass(frozen=True)
class Realm:
    name: str          # stored on the refresh token
    scope: str         # goes into the access token
    cookie: str
    path: str          # the cookie is only ever sent to this part of the API


CUSTOMER = Realm("customer", "customer", "refresh_token", f"{settings.API_V1_STR}/auth")
ADMIN = Realm("admin", "admin", "admin_refresh_token", "/admin/auth")


def _ttl(realm: Realm, remember: bool) -> timedelta:
    if realm is ADMIN:
        return timedelta(hours=settings.ADMIN_SESSION_HOURS)
    return timedelta(days=settings.REFRESH_TOKEN_DAYS) if remember else timedelta(hours=settings.REFRESH_SESSION_HOURS)


def set_refresh_cookie(response: Response, realm: Realm, token: str, persistent: bool, expires_at: datetime) -> None:
    max_age = None
    if persistent:
        max_age = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=realm.cookie,
        value=token,
        max_age=max_age,  # None -> a session cookie, gone when the browser closes
        httponly=True,    # not readable from JavaScript, so XSS can't steal it
        secure=settings.cookie_secure,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=realm.path,
    )


def clear_refresh_cookie(response: Response, realm: Realm) -> None:
    response.delete_cookie(
        key=realm.cookie,
        path=realm.path,
        domain=settings.COOKIE_DOMAIN,
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


async def start_session(
    db: AsyncSession, request: Request, response: Response, user: User, realm: Realm, remember: bool
) -> str:
    """Creates a refresh session (sets the cookie) and returns a fresh access token."""
    persistent = remember and realm is not ADMIN
    expires_at = datetime.now(timezone.utc) + _ttl(realm, remember)
    plain, _ = await issue_refresh_token(
        db,
        user.id,
        realm.name,
        persistent=persistent,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
    )
    set_refresh_cookie(response, realm, plain, persistent, expires_at)
    return create_access_token(user.email, scope=realm.scope)


async def refresh_session(
    db: AsyncSession, request: Request, response: Response, realm: Realm
) -> Optional[tuple[str, User]]:
    """Rotates the refresh cookie and returns (access token, user), or None if there's no valid session."""
    plain = request.cookies.get(realm.cookie)
    if not plain:
        return None

    rotated = await rotate_refresh_token(db, plain, realm.name, request.headers.get("user-agent"))
    if rotated is None:
        return None
    new_plain, row = rotated

    user = await get_user(db, row.user_id)
    if user is None or not user.is_active or (realm is ADMIN and not user.is_superuser):
        await revoke_session(db, new_plain, realm.name)
        return None

    set_refresh_cookie(response, realm, new_plain, row.persistent, row.expires_at)
    return create_access_token(user.email, scope=realm.scope), user


async def end_session(db: AsyncSession, request: Request, realm: Realm) -> None:
    plain = request.cookies.get(realm.cookie)
    if plain:
        await revoke_session(db, plain, realm.name)


def no_session_response(realm: Realm) -> JSONResponse:
    """401 that also tells the browser to drop a dead cookie."""
    response = JSONResponse(status_code=401, content={"detail": "Session expired. Please sign in again."})
    clear_refresh_cookie(response, realm)
    return response
