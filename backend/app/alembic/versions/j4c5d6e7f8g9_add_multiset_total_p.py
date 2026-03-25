"""add_multiset_total_p

Revision ID: j4c5d6e7f8g9
Revises: i3b4c5d6e7f8
Create Date: 2026-03-04 12:00:00.000000

Add multiset_total_p column to metrics_data.
This is the HGM9560 SPR's software-calculated sum of all connected genset
powers — the correct source for "total generator power" in charts.
Previously charts used busbar_p which measures a different physical point.
Nullable — instant ADD COLUMN in PostgreSQL, no table rewrite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'j4c5d6e7f8g9'
down_revision: Union[str, None] = 'i3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('metrics_data', sa.Column('multiset_total_p', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('metrics_data', 'multiset_total_p')
