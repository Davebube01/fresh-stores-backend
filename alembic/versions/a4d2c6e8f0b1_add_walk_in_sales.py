"""walk-in sales: order channel, served_by and discount

Revision ID: a4d2c6e8f0b1
Revises: f3c9a1d5e7b2
Create Date: 2026-09-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d2c6e8f0b1'
down_revision: Union[str, None] = 'f3c9a1d5e7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every existing order came through the storefront.
    op.add_column('orders', sa.Column('channel', sa.String(), nullable=False, server_default='online'))
    op.create_index('ix_orders_channel', 'orders', ['channel'])
    op.add_column('orders', sa.Column('served_by', sa.String(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('orders', sa.Column('discount_amount', sa.Float(), nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('discount_note', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'discount_note')
    op.drop_column('orders', 'discount_amount')
    op.drop_column('orders', 'served_by')
    op.drop_index('ix_orders_channel', table_name='orders')
    op.drop_column('orders', 'channel')
