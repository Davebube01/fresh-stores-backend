"""
Staff accounts: admin users (is_superuser) with a role.

Guard rails: nobody can change their own role or deactivate themselves,
and there is always at least one active owner, so the store can never lock
itself out of staff management.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import OWNER, PERMISSIONS, ROLE_LABELS, ROLE_PERMISSIONS, ROLES, role_of
from app.core.security import get_password_hash
from app.crud.refresh_token import revoke_all_user_sessions
from app.services.auth_service import ADMIN
from app.models.activity import ActivityLog
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.staff import StaffCreate, StaffUpdate


class StaffError(ValueError):
    pass


def _member(user: User, last_signed_in_at=None, active_sessions: int = 0) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": role_of(user),
        "is_active": bool(user.is_active),
        "created_at": user.created_at,
        "last_signed_in_at": last_signed_in_at,
        "password_is_temporary": bool(user.password_is_temporary),
        "active_sessions": active_sessions,
    }


async def list_staff(db: AsyncSession) -> dict:
    last_sign_in = (
        select(ActivityLog.actor_id, func.max(ActivityLog.created_at).label("at"))
        .where(ActivityLog.action == "admin.signed_in")
        .group_by(ActivityLog.actor_id)
        .subquery()
    )
    sessions = (
        select(RefreshToken.user_id, func.count(func.distinct(RefreshToken.family_id)).label("n"))
        .where(RefreshToken.realm == ADMIN.name, RefreshToken.revoked_at.is_(None),
               RefreshToken.rotated_at.is_(None), RefreshToken.expires_at > datetime.now(timezone.utc))
        .group_by(RefreshToken.user_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(User, last_sign_in.c.at, sessions.c.n)
            .outerjoin(last_sign_in, last_sign_in.c.actor_id == User.id)
            .outerjoin(sessions, sessions.c.user_id == User.id)
            .where(User.is_superuser == True)  # noqa: E712
            .order_by(User.is_active.desc(), User.created_at)
        )
    ).all()
    return {
        "staff": [_member(u, at, n or 0) for u, at, n in rows],
        "roles": [{"key": r, "label": ROLE_LABELS[r], "permissions": sorted(ROLE_PERMISSIONS[r])} for r in ROLES],
        "permissions": PERMISSIONS,
    }


async def _active_owner_count(db: AsyncSession) -> int:
    owners = (
        await db.execute(select(User).where(User.is_superuser == True, User.is_active == True))  # noqa: E712
    ).scalars().all()
    return sum(1 for u in owners if role_of(u) == OWNER)


async def create_staff(db: AsyncSession, data: StaffCreate) -> dict:
    email = data.email.lower()
    if (await db.execute(select(User).where(func.lower(User.email) == email))).scalars().first():
        raise StaffError("There's already an account with that email")
    user = User(
        email=email,
        full_name=data.full_name.strip(),
        phone=(data.phone or "").strip() or None,
        hashed_password=get_password_hash(data.password),
        is_superuser=True,
        is_active=True,
        staff_role=data.role,
        # The owner vouches for the address; there's no verification email for staff.
        email_verified=True,
        password_is_temporary=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _member(user)


async def get_staff_user(db: AsyncSession, staff_id: str) -> Optional[User]:
    user = await db.get(User, staff_id)
    return user if user is not None and user.is_superuser else None


async def update_staff(db: AsyncSession, staff_id: str, data: StaffUpdate, acting: User) -> Optional[tuple[dict, dict]]:
    """Returns (member, changes) or None if not found. Raises StaffError for a refused change."""
    user = await get_staff_user(db, staff_id)
    if user is None:
        return None
    before = {"role": role_of(user), "is_active": bool(user.is_active), "full_name": user.full_name, "phone": user.phone}

    if user.id == acting.id and data.role is not None and data.role != role_of(user):
        raise StaffError("You can't change your own role")
    if user.id == acting.id and data.is_active is False:
        raise StaffError("You can't deactivate your own account")
    losing_owner = role_of(user) == OWNER and user.is_active and (
        (data.role is not None and data.role != OWNER) or data.is_active is False
    )
    if losing_owner and await _active_owner_count(db) <= 1:
        raise StaffError("The store needs at least one active owner")

    if data.full_name is not None:
        user.full_name = data.full_name.strip()
    if data.phone is not None:
        user.phone = data.phone.strip() or None
    if data.role is not None:
        user.staff_role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    await db.commit()
    if data.is_active is False:
        # Signed out everywhere, straight away.
        await revoke_all_user_sessions(db, user.id)
    await db.refresh(user)

    after = {"role": role_of(user), "is_active": bool(user.is_active), "full_name": user.full_name, "phone": user.phone}
    changes = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    return _member(user), changes


async def reset_staff_password(db: AsyncSession, staff_id: str, password: str) -> Optional[User]:
    user = await get_staff_user(db, staff_id)
    if user is None:
        return None
    user.hashed_password = get_password_hash(password)
    user.password_is_temporary = True
    await db.commit()
    await revoke_all_user_sessions(db, user.id)
    return user


async def sign_out_staff(db: AsyncSession, staff_id: str) -> Optional[User]:
    """End every admin session a staff member has (e.g. a lost phone), without deactivating them."""
    user = await get_staff_user(db, staff_id)
    if user is None:
        return None
    await revoke_all_user_sessions(db, user.id, realm=ADMIN.name)
    return user


async def change_own_password(db: AsyncSession, user: User, new_password: str) -> None:
    db_user = await db.get(User, user.id)
    db_user.hashed_password = get_password_hash(new_password)
    db_user.password_is_temporary = False
    await db.commit()
