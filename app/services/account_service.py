"""Customer self-service: profile, password and saved addresses."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import hashlib
from datetime import timedelta

from jose import JWTError, jwt

from app.core.config import settings
from app.core.delivery_zones import DELIVERY_ZONES, ZONE_NAMES
from app.core.security import get_password_hash, hash_token, verify_password
from app.models.address import SavedAddress
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.account import AddressIn, PasswordChange, ProfileUpdate
from app.services.auth_service import CUSTOMER

MAX_ADDRESSES = 10


class AccountError(ValueError):
    pass


async def update_profile(db: AsyncSession, user: User, body: ProfileUpdate) -> User:
    user.full_name = body.full_name
    user.phone = body.phone
    await db.commit()
    await db.refresh(user)
    return user


async def _current_family(db: AsyncSession, request: Request, user: User) -> Optional[str]:
    """The refresh-token family of the session making this request, if any.
    (The customer refresh cookie is only sent to /api/v1/auth/*, so callers
    must live under that path.)"""
    plain = request.cookies.get(CUSTOMER.cookie)
    if not plain:
        return None
    current = (await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(plain), RefreshToken.user_id == user.id)
    )).scalar_one_or_none()
    return current.family_id if current else None


async def sign_out_other_sessions(db: AsyncSession, request: Request, user: User) -> int:
    """End every customer session for this user except the one making the request."""
    keep = await _current_family(db, request, user)
    query = update(RefreshToken).where(
        RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None), RefreshToken.realm == CUSTOMER.name,
    )
    if keep:
        query = query.where(RefreshToken.family_id != keep)
    result = await db.execute(query.values(revoked_at=datetime.now(timezone.utc)))
    await db.commit()
    return result.rowcount or 0


async def change_password(db: AsyncSession, request: Request, user: User, body: PasswordChange) -> int:
    """
    Change the password and sign out every other session (a stolen session
    shouldn't survive a password change). Returns how many were ended.
    """
    if not verify_password(body.current_password, user.hashed_password):
        raise AccountError("Your current password isn't right.")
    if verify_password(body.new_password, user.hashed_password):
        raise AccountError("Your new password must be different from the current one.")
    user.hashed_password = get_password_hash(body.new_password)
    await db.flush()
    return await sign_out_other_sessions(db, request, user)


# ── Password reset ───────────────────────────────────────────────────────

RESET_MINUTES = 60
RESET_PURPOSE = "reset_password"


def _password_fingerprint(user: User) -> str:
    # Changes whenever the password does, so a reset link dies the moment it
    # (or any other password change) is used.
    return hashlib.sha256(user.hashed_password.encode()).hexdigest()[:16]


def create_reset_token(user: User) -> str:
    return jwt.encode(
        {
            "sub": user.email,
            "type": RESET_PURPOSE,
            "pwd": _password_fingerprint(user),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=RESET_MINUTES),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


async def reset_password(db: AsyncSession, token: str, new_password: str) -> User:
    """Set a new password from a reset link. Signs out every session."""
    invalid = AccountError("This reset link is invalid or has expired. Ask for a new one.")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise invalid
    if payload.get("type") != RESET_PURPOSE or not payload.get("sub"):
        raise invalid
    user = (await db.execute(select(User).where(User.email == payload["sub"]))).scalar_one_or_none()
    if user is None or not user.is_active or payload.get("pwd") != _password_fingerprint(user):
        raise invalid

    user.hashed_password = get_password_hash(new_password)
    if not user.email_verified:
        # Using the link proves they hold the mailbox.
        user.email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return user


# ── Addresses ────────────────────────────────────────────────────────────

def address_out(a: SavedAddress) -> dict:
    zone = DELIVERY_ZONES.get(a.zone_id)
    return {
        "id": a.id,
        "label": a.label,
        "zone_id": a.zone_id,
        "zone_name": ZONE_NAMES.get(a.zone_id, a.zone_id),
        "zone_fee": float(zone["fee"]) if zone else None,
        "address": a.address,
        "apartment": a.apartment,
        "landmark": a.landmark,
        "instructions": a.instructions,
        "is_default": a.is_default,
        "created_at": a.created_at,
    }


async def list_addresses(db: AsyncSession, user: User) -> list[SavedAddress]:
    return (await db.execute(
        select(SavedAddress)
        .where(SavedAddress.user_id == user.id)
        .order_by(SavedAddress.is_default.desc(), SavedAddress.created_at.asc())
    )).scalars().all()


async def _get(db: AsyncSession, user: User, address_id: str) -> Optional[SavedAddress]:
    return (await db.execute(
        select(SavedAddress).where(SavedAddress.id == address_id, SavedAddress.user_id == user.id)
    )).scalar_one_or_none()


def _check_zone(zone_id: str) -> None:
    if zone_id not in DELIVERY_ZONES:
        raise AccountError("We don't deliver to that area right now. Choose another one.")


async def _make_default(db: AsyncSession, user: User, keep_id: str) -> None:
    await db.execute(
        update(SavedAddress)
        .where(SavedAddress.user_id == user.id, SavedAddress.id != keep_id)
        .values(is_default=False)
    )


async def add_address(db: AsyncSession, user: User, body: AddressIn) -> SavedAddress:
    _check_zone(body.zone_id)
    existing = await list_addresses(db, user)
    if len(existing) >= MAX_ADDRESSES:
        raise AccountError(f"You can save up to {MAX_ADDRESSES} addresses. Remove one first.")
    row = SavedAddress(user_id=user.id, **body.model_dump())
    row.is_default = body.is_default or not existing  # the first one is the default
    db.add(row)
    await db.flush()
    if row.is_default:
        await _make_default(db, user, row.id)
    await db.commit()
    await db.refresh(row)
    return row


async def update_address(db: AsyncSession, user: User, address_id: str, body: AddressIn) -> Optional[SavedAddress]:
    row = await _get(db, user, address_id)
    if row is None:
        return None
    if body.zone_id != row.zone_id:
        _check_zone(body.zone_id)
    was_default = row.is_default
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.is_default = body.is_default or was_default  # un-defaulting happens by picking another
    if row.is_default:
        await _make_default(db, user, row.id)
    await db.commit()
    await db.refresh(row)
    return row


async def set_default(db: AsyncSession, user: User, address_id: str) -> Optional[SavedAddress]:
    row = await _get(db, user, address_id)
    if row is None:
        return None
    row.is_default = True
    await _make_default(db, user, row.id)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_address(db: AsyncSession, user: User, address_id: str) -> bool:
    row = await _get(db, user, address_id)
    if row is None:
        return False
    was_default = row.is_default
    await db.delete(row)
    await db.flush()
    if was_default:
        # Keep one default while any address remains.
        nxt = (await db.execute(
            select(SavedAddress).where(SavedAddress.user_id == user.id).order_by(SavedAddress.created_at.asc()).limit(1)
        )).scalar_one_or_none()
        if nxt:
            nxt.is_default = True
    await db.commit()
    return True
