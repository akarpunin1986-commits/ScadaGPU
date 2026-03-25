"""add_gas_prices

Revision ID: k5d6e7f8g9h0
Revises: j4c5d6e7f8g9
Create Date: 2026-03-04 14:00:00.000000

Gas price tracking per site for Economics view.
Stores effective_from + price_per_m3 to calculate cost per kWh
over time with changing gas tariffs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'k5d6e7f8g9h0'
down_revision: Union[str, None] = 'j4c5d6e7f8g9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'gas_prices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('site_id', sa.Integer(),
                  sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('price_per_m3', sa.Float(), nullable=False),
        sa.Column('note', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('site_id', 'effective_from',
                            name='uq_gas_price_site_date'),
    )


def downgrade() -> None:
    op.drop_table('gas_prices')
