from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.security import generate_refresh_token, hash_token
from app.models.refresh_token import RefreshToken

# Two tabs can present the same cookie at nearly the same moment (both wake up
# with an expired access token). The second arrives just after the first has
# rotated it. A token *rotated* this recently is treated as that harmless
# race, not as theft — anything older than this is a replay and burns the
# family. (Tokens revoked by logout or by this very check are never allowed.)
ROTATION_GRACE = timedelta(seconds=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def issue_refresh_token(
    db: AsyncSession,
    user_id: str,
    realm: str,
    *,
    persistent: bool,
    expires_at: datetime,
    family_id: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[str, RefreshToken]:
    plain, hashed = generate_refresh_token()
    row = RefreshToken(
        user_id=user_id,
        token_hash=hashed,
        family_id=family_id or str(uuid.uuid4()),
        realm=realm,
        persistent=persistent,
        expires_at=expires_at,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(row)
    # Housekeeping: occasionally drop long-dead rows so the table doesn't grow
    # forever. Randomized (about 1 in 50 issues) so it isn't a scan per request.
    if random.random() < 0.02:
        await db.execute(delete(RefreshToken).where(RefreshToken.expires_at < _now() - timedelta(days=7)))
    await db.commit()
    await db.refresh(row)
    return plain, row


async def _revoke_family(db: AsyncSession, family_id: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()


async def rotate_refresh_token(
    db: AsyncSession, plain: str, realm: str, user_agent: Optional[str] = None
) -> Optional[tuple[str, RefreshToken]]:
    """
    Exchanges a valid refresh token for a fresh one (same family, same
    absolute expiry — a session can't be extended forever by refreshing).
    Returns None if the token is unknown, expired, for another realm, or a
    replay of an already-rotated token (which also revokes the whole family).
    """
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(plain)))
    row = result.scalars().first()
    if row is None or row.realm != realm:
        return None

    now = _now()
    if row.expires_at <= now or row.revoked_at is not None:
        return None

    if row.rotated_at is None:
        row.rotated_at = now
        await db.commit()
    elif now - row.rotated_at > ROTATION_GRACE:
        # An already-used token coming back after the race window: someone
        # is replaying a copy. Kill every token in the chain.
        await _revoke_family(db, row.family_id)
        return None
    # else: the concurrent-tab race described at ROTATION_GRACE — allowed.

    return await issue_refresh_token(
        db,
        row.user_id,
        realm,
        persistent=row.persistent,
        expires_at=row.expires_at,
        family_id=row.family_id,
        user_agent=user_agent,
    )


async def revoke_session(db: AsyncSession, plain: str, realm: str) -> None:
    """Logout: kills this token and every token rotated from it."""
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(plain)))
    row = result.scalars().first()
    if row is not None and row.realm == realm:
        await _revoke_family(db, row.family_id)


async def revoke_all_user_sessions(db: AsyncSession, user_id: str, realm: Optional[str] = None) -> None:
    query = update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    if realm:
        query = query.where(RefreshToken.realm == realm)
    await db.execute(query.values(revoked_at=_now()))
    await db.commit()
