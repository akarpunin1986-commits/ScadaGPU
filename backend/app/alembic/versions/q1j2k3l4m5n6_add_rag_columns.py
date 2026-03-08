"""Add RAG columns to ai_knowledge_chunks.

Revision ID: q1j2k3l4m5n6
Revises: p0i1j2k3l4m5
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "q1j2k3l4m5n6"
down_revision = "p0i1j2k3l4m5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_knowledge_chunks", sa.Column("embedded", sa.Boolean(), server_default="false"))
    op.add_column("ai_knowledge_chunks", sa.Column("embedded_at", sa.DateTime(), nullable=True))
    op.add_column("ai_knowledge_chunks", sa.Column("device_type", sa.String(50), nullable=True))
    op.add_column("ai_knowledge_chunks", sa.Column("document_type", sa.String(50), nullable=True))
    op.add_column("ai_knowledge_chunks", sa.Column("chroma_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_knowledge_chunks", "chroma_id")
    op.drop_column("ai_knowledge_chunks", "document_type")
    op.drop_column("ai_knowledge_chunks", "device_type")
    op.drop_column("ai_knowledge_chunks", "embedded_at")
    op.drop_column("ai_knowledge_chunks", "embedded")
