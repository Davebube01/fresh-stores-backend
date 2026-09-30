"""add users.password_is_temporary

Revision ID: e5c9a3f7b2d8
Revises: d2b8f4a6c9e3
Create Date: 2026-09-29 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5c9a3f7b2d8'
down_revision: Union[str, None] = 'd2b8f4a6c9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing staff keep False: we can't know whether they changed theirs.
    op.add_column('users', sa.Column('password_is_temporary', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'password_is_temporary')
