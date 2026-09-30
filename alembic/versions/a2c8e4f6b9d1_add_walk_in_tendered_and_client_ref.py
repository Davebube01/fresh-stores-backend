"""add orders.cash_tendered and orders.client_ref

Revision ID: a2c8e4f6b9d1
Revises: f1a7c3e9d5b2
Create Date: 2026-09-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2c8e4f6b9d1'
down_revision: Union[str, None] = 'f1a7c3e9d5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('cash_tendered', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column('client_ref', sa.String(), nullable=True))
    op.create_index('ix_orders_client_ref', 'orders', ['client_ref'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_orders_client_ref', table_name='orders')
    op.drop_column('orders', 'client_ref')
    op.drop_column('orders', 'cash_tendered')
