"""add about page fields to store_settings

Revision ID: e4c2a8f6b1d9
Revises: d9b5e1f3a7c2
Create Date: 2026-09-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4c2a8f6b1d9'
down_revision: Union[str, None] = 'd9b5e1f3a7c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('store_settings', sa.Column('about_headline', sa.String(), nullable=True))
    op.add_column('store_settings', sa.Column('about_story', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('store_settings', 'about_story')
    op.drop_column('store_settings', 'about_headline')
