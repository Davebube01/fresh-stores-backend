"""add users.deleted_at

Revision ID: c6a2e8d4f1b9
Revises: b3f7d2a9e6c4
Create Date: 2026-09-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6a2e8d4f1b9'
down_revision: Union[str, None] = 'b3f7d2a9e6c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'deleted_at')
