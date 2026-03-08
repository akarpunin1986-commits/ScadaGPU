"""add cause column to agent_incidents

Revision ID: m7f8g9h0i1j2
Revises: l6e7f8g9h0i1
Create Date: 2026-03-08 18:00:00.000000

Adds 'cause' column to store parsed root cause from LLM analysis.
Enables agent memory — past incident causes are used as context for new analyses.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm7f8g9h0i1j2'
down_revision: Union[str, None] = 'l6e7f8g9h0i1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'agent_incidents',
        sa.Column('cause', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('agent_incidents', 'cause')
