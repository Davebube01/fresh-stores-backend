from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
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

async def seed_admin_user(db: AsyncSession):
    admin_email = "admin@meatstore.com"
    admin_password = "adminpassword123"
    
    result = await db.execute(select(User).where(User.email == admin_email))
    if not result.scalars().first():
        hashed_password = get_password_hash(admin_password)
        db_user = User(
            email=admin_email,
            hashed_password=hashed_password,
            full_name="System Administrator",
            is_active=True,
            is_superuser=True
        )
        db.add(db_user)
        await db.commit()

