"""add delivery_method to orders

Revision ID: b1c3d5e7f9a2
Revises: a7b255c5d8b1
Create Date: 2026-04-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c3d5e7f9a2'
down_revision: Union[str, None] = 'a7b255c5d8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add delivery_method column with a default of 'delivery' for existing rows
    op.add_column(
        'orders',
        sa.Column(
            'delivery_method',
            sa.String(),
            nullable=False,
            server_default='delivery'
        )
    )
    op.create_index(op.f('ix_orders_delivery_method'), 'orders', ['delivery_method'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_orders_delivery_method'), table_name='orders')
    op.drop_column('orders', 'delivery_method')
