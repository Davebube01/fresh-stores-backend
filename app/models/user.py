import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, false
from app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    # For admin (is_superuser) accounts: "owner" | "manager" | "cashier".
    # See app/core/permissions.py. Null on an admin account means owner.
    staff_role = Column(String, nullable=True)
    # Set once the user proves they own the address (link in the verification
    # email). Guest orders are only attached to an account after this.
    email_verified = Column(Boolean, nullable=False, default=False, server_default=false())
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    # Staff only: the password is one an owner set (new account or reset) and
    # the staff member hasn't replaced it yet. The admin nags until they do.
    password_is_temporary = Column(Boolean, nullable=False, default=False, server_default=false())
    # Set when the customer deleted their account. The row stays (past orders
    # point at it) but every personal detail on it has been wiped.
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
