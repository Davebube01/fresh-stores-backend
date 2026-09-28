"""add store_settings and delivery_zones

Revision ID: d7a1e3c5b9f2
Revises: c4d8e2f1a9b3
Create Date: 2026-09-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a1e3c5b9f2'
down_revision: Union[str, None] = 'c4d8e2f1a9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'store_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('store_name', sa.String(), nullable=False),
        sa.Column('contact_email', sa.String(), nullable=True),
        sa.Column('contact_phone', sa.String(), nullable=True),
        sa.Column('whatsapp_number', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('pickup_address', sa.String(), nullable=True),
        sa.Column('pickup_instructions', sa.String(), nullable=True),
        sa.Column('low_stock_threshold', sa.Float(), nullable=False, server_default='5'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    # Rows are seeded by the app on startup (app.core.delivery_zones), from
    # the same table of zones that used to be hardcoded.
    op.create_table(
        'delivery_zones',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('fee', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('delivery_zones')
    op.drop_table('store_settings')
