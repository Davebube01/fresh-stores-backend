"""add contact_messages

Revision ID: f7d3b9e2c5a1
Revises: e4c2a8f6b1d9
Create Date: 2026-09-29 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7d3b9e2c5a1'
down_revision: Union[str, None] = 'e4c2a8f6b1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contact_messages',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('topic', sa.String(), nullable=False, server_default='other'),
        sa.Column('order_ref', sa.String(), nullable=True),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='new'),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('handled_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_contact_messages_status', 'contact_messages', ['status'])
    op.create_index('ix_contact_messages_created_at', 'contact_messages', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_contact_messages_created_at', table_name='contact_messages')
    op.drop_index('ix_contact_messages_status', table_name='contact_messages')
    op.drop_table('contact_messages')
