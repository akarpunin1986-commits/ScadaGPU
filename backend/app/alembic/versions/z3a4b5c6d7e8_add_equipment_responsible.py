"""add equipment_responsible table

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-03-22 17:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "z3a4b5c6d7e8"
down_revision = "y2z3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_responsible",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("equipment_code", sa.String(100), unique=True, nullable=False),
        sa.Column("equipment_name", sa.String(255), nullable=True),
        sa.Column("site_code", sa.String(20), nullable=True),
        sa.Column("responsible_bitrix_id", sa.Integer(), nullable=False),
        sa.Column("responsible_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("equipment_responsible")
