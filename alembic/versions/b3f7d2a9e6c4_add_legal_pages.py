"""add legal_pages

Revision ID: b3f7d2a9e6c4
Revises: a8e4c1f6d2b7
Create Date: 2026-09-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7d2a9e6c4'
down_revision: Union[str, None] = 'a8e4c1f6d2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Empty on purpose: the storefront shows the built-in text until the
    # store saves its own (see app/services/legal_service.py).
    op.create_table(
        'legal_pages',
        sa.Column('slug', sa.String(), primary_key=True),
        sa.Column('body', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_by', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('legal_pages')
