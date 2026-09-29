from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    # Emails are stored lowercase (see RegisterRequest), so normalize here too
    # — otherwise "Name@x.com" at login wouldn't match "name@x.com" on file.
    result = await db.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalars().first()

async def get_user(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()

async def create_user(db: AsyncSession, user: UserCreate) -> User:
    hashed_password = get_password_hash(user.password)
    db_user = User(
        email=user.email,
        hashed_password=hashed_password,
        full_name=user.full_name,
        phone=user.phone,
        address=user.address,
        avatar_url=user.avatar_url
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def seed_admin_user(db: AsyncSession) -> Optional[User]:
    """
    Create the first owner account, once, from ADMIN_EMAIL / ADMIN_PASSWORD.

    Only runs while the store has no staff account at all, so it can't
    recreate or reset an account later (e.g. after the owner changes the
    email or password). There is deliberately no built-in default password.
    """
    import logging
    from app.core.config import settings

    log = logging.getLogger("seed")
    if (await db.execute(select(User.id).where(User.is_superuser == True).limit(1))).first():  # noqa: E712
        return None
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        log.warning(
            "No admin account exists yet. Set ADMIN_EMAIL and ADMIN_PASSWORD and restart "
            "to create the first owner (only used while no admin exists)."
        )
        return None

    db_user = User(
        email=settings.ADMIN_EMAIL.strip().lower(),
        hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
        full_name=settings.ADMIN_NAME,
        is_active=True,
        is_superuser=True,
        staff_role="owner",
        email_verified=True,
    )
    db.add(db_user)
    await db.commit()
    log.info("Created the first owner account, %s. Change its password after signing in.", db_user.email)
    return db_user
