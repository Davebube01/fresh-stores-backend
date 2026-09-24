import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from app.core.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class RefreshToken(Base):
    """
    One row per issued refresh token. Only a SHA-256 of the token is stored,
    so a database leak doesn't hand out live sessions. Tokens rotate on every
    use; `family_id` ties a login's chain of rotated tokens together so a
    replayed (stolen) old token can revoke the whole chain.
    """
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    family_id = Column(String, nullable=False, index=True)

    # "customer" or "admin" — a cookie for one realm is useless in the other.
    realm = Column(String, nullable=False)
    # Whether the cookie outlives the browser session ("keep me signed in").
    persistent = Column(Boolean, nullable=False, default=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    # Set when this token was exchanged for its successor (normal use).
    rotated_at = Column(DateTime(timezone=True), nullable=True)
    # Set when the session was killed outright: logout, or a replayed token
    # burning the whole family. Never honoured again, not even briefly.
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user_agent = Column(String, nullable=True)
