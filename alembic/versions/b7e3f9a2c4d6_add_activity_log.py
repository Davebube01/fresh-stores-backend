"""add admin activity log

Revision ID: b7e3f9a2c4d6
Revises: a4d2c6e8f0b1
Create Date: 2026-09-28 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e3f9a2c4d6'
down_revision: Union[str, None] = 'a4d2c6e8f0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'activity_log',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('actor_name', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('entity_label', sa.String(), nullable=True),
        sa.Column('summary', sa.String(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in ('actor_id', 'action', 'entity_type', 'entity_id', 'created_at'):
        op.create_index(f'ix_activity_log_{column}', 'activity_log', [column])


def downgrade() -> None:
    for column in ('actor_id', 'action', 'entity_type', 'entity_id', 'created_at'):
        op.drop_index(f'ix_activity_log_{column}', table_name='activity_log')
    op.drop_table('activity_log')
