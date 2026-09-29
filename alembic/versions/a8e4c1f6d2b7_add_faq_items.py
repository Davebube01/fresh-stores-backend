"""add faq_items

Revision ID: a8e4c1f6d2b7
Revises: f7d3b9e2c5a1
Create Date: 2026-09-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8e4c1f6d2b7'
down_revision: Union[str, None] = 'f7d3b9e2c5a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Empty on purpose: the storefront shows built-in defaults until the
    # store saves its own list (see app/services/faq_service.py).
    op.create_table(
        'faq_items',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('section', sa.String(), nullable=False, server_default='ordering'),
        sa.Column('question', sa.String(), nullable=False),
        sa.Column('answer', sa.String(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('faq_items')
