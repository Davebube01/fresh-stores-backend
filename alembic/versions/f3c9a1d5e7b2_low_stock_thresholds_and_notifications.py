"""per-product low-stock thresholds and admin notifications

Revision ID: f3c9a1d5e7b2
Revises: e2b6f4a8c1d3
Create Date: 2026-09-28 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c9a1d5e7b2'
down_revision: Union[str, None] = 'e2b6f4a8c1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Null = use the store-wide default from settings.
    op.add_column('products', sa.Column('low_stock_threshold', sa.Float(), nullable=True))
    op.create_table(
        'admin_notifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('link', sa.String(), nullable=True),
        sa.Column('product_id', sa.String(), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_admin_notifications_kind', 'admin_notifications', ['kind'])
    op.create_index('ix_admin_notifications_product_id', 'admin_notifications', ['product_id'])
    op.create_index('ix_admin_notifications_created_at', 'admin_notifications', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_admin_notifications_created_at', table_name='admin_notifications')
    op.drop_index('ix_admin_notifications_product_id', table_name='admin_notifications')
    op.drop_index('ix_admin_notifications_kind', table_name='admin_notifications')
    op.drop_table('admin_notifications')
    op.drop_column('products', 'low_stock_threshold')
