"""add till_counts

Revision ID: f1a7c3e9d5b2
Revises: e5c9a3f7b2d8
Create Date: 2026-09-29 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a7c3e9d5b2'
down_revision: Union[str, None] = 'e5c9a3f7b2d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'till_counts',
        sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('opening_float', sa.Float(), nullable=False, server_default='0'),
        sa.Column('counted_cash', sa.Float(), nullable=False),
        sa.Column('expected_cash', sa.Float(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('counted_by_id', sa.String(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('counted_by', sa.String(), nullable=True),
        sa.Column('counted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('till_counts')
