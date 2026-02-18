"""add_device_timeout_fields

Revision ID: a3f8c1d29e47
Revises: 2d71b0f4423b
Create Date: 2026-02-17 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c1d29e47'
down_revision: Union[str, None] = '2d71b0f4423b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devices', sa.Column('poll_interval', sa.Float(), nullable=True))
    op.add_column('devices', sa.Column('modbus_timeout', sa.Float(), nullable=True))
    op.add_column('devices', sa.Column('retry_delay', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('devices', 'retry_delay')
    op.drop_column('devices', 'modbus_timeout')
    op.drop_column('devices', 'poll_interval')
