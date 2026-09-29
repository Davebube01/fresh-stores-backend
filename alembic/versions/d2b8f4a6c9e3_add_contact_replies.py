"""add contact_replies

Revision ID: d2b8f4a6c9e3
Revises: c6a2e8d4f1b9
Create Date: 2026-09-29 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b8f4a6c9e3'
down_revision: Union[str, None] = 'c6a2e8d4f1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contact_replies',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('message_id', sa.String(), sa.ForeignKey('contact_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('body', sa.String(), nullable=False),
        sa.Column('sent_by', sa.String(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_contact_replies_message_id', 'contact_replies', ['message_id'])


def downgrade() -> None:
    op.drop_index('ix_contact_replies_message_id', table_name='contact_replies')
    op.drop_table('contact_replies')
