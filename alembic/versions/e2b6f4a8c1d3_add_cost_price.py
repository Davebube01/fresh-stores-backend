"""add cost price to products and order items

Revision ID: e2b6f4a8c1d3
Revises: d7a1e3c5b9f2
Create Date: 2026-09-28 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b6f4a8c1d3'
down_revision: Union[str, None] = 'd7a1e3c5b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Both nullable: costs were never recorded, and inventing them would make
    # profit look real when it isn't. The dashboard falls back to the current
    # cost for older orders once the admin enters one.
    op.add_column('products', sa.Column('cost_price', sa.Float(), nullable=True))
    op.add_column('order_items', sa.Column('cost_at_time', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('order_items', 'cost_at_time')
    op.drop_column('products', 'cost_price')
