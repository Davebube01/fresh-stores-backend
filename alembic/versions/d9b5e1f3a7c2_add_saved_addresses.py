"""add saved_addresses

Revision ID: d9b5e1f3a7c2
Revises: c8f4a0b2d6e9
Create Date: 2026-09-28 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9b5e1f3a7c2'
down_revision: Union[str, None] = 'c8f4a0b2d6e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'saved_addresses',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('zone_id', sa.String(), nullable=False),
        sa.Column('address', sa.String(), nullable=False),
        sa.Column('apartment', sa.String(), nullable=True),
        sa.Column('landmark', sa.String(), nullable=True),
        sa.Column('instructions', sa.String(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_saved_addresses_user_id', 'saved_addresses', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_saved_addresses_user_id', table_name='saved_addresses')
    op.drop_table('saved_addresses')
