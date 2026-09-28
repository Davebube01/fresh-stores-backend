"""add stock_units to order_items

Revision ID: c4d8e2f1a9b3
Revises: 8ee3461efbbf
Create Date: 2026-09-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d8e2f1a9b3'
down_revision: Union[str, None] = '8ee3461efbbf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every existing order took exactly 1 off stock per unit ordered, so 1 is
    # the true value for them — cancelling one still gives back what it took.
    op.add_column(
        'order_items',
        sa.Column('stock_units', sa.Float(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    op.drop_column('order_items', 'stock_units')
