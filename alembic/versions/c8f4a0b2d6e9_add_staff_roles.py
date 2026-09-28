"""add staff roles

Revision ID: c8f4a0b2d6e9
Revises: b7e3f9a2c4d6
Create Date: 2026-09-28 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f4a0b2d6e9'
down_revision: Union[str, None] = 'b7e3f9a2c4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('staff_role', sa.String(), nullable=True))
    # Every admin so far had full access: keep it that way.
    op.execute("UPDATE users SET staff_role = 'owner' WHERE is_superuser")


def downgrade() -> None:
    op.drop_column('users', 'staff_role')
