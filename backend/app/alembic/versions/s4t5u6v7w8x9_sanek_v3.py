"""sanek_v3 — equipment_units, learning_insights, model extensions

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-03-14 12:00:00.000000

Adds:
- equipment_units table (GPU grouping)
- learning_insights table (self-learning)
- devices: unit_id, role_in_unit, instance_notes
- device_type_registry: purpose, manufacturer_info, operating_principles, typical_issues, maintenance_notes
- sites: grid_price_kwh
- sanek_feedback: session_id, message_index, correct_answer, context, feedback_detail
- sanek_pattern_stats: last_context
- sop_procedures: source
- sanek_actions: outcome_analysis
"""
from alembic import op
import sqlalchemy as sa


revision = 's4t5u6v7w8x9'
down_revision = 'r3s4t5u6v7w8'
branch_labels = None
depends_on = None


def upgrade():
    # 1. equipment_units
    op.create_table('equipment_units',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('site_id', sa.Integer(), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=False, unique=True),
        sa.Column('unit_type', sa.String(50), nullable=False),
        sa.Column('manufacturer', sa.String(200)),
        sa.Column('model', sa.String(200)),
        sa.Column('total_power_kw', sa.Float()),
        sa.Column('description', sa.Text()),
        sa.Column('purpose', sa.Text()),
        sa.Column('components', sa.JSON(), server_default='{}'),
        sa.Column('infrastructure', sa.JSON(), server_default='{}'),
        sa.Column('documentation', sa.JSON(), server_default='[]'),
        sa.Column('responsible_person', sa.String(200)),
        sa.Column('responsible_contact', sa.String(200)),
        sa.Column('commissioning_date', sa.Date()),
        sa.Column('last_overhaul_date', sa.Date()),
        sa.Column('notes', sa.Text()),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # 2. learning_insights — НОВАЯ
    op.create_table('learning_insights',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('insight_type', sa.String(50), nullable=False),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('alarm_code', sa.String(100)),
        sa.Column('device_type', sa.String(50)),
        sa.Column('content', sa.JSON(), server_default='{}'),
        sa.Column('confidence', sa.Float(), server_default='0.5'),
        sa.Column('sample_size', sa.Integer(), server_default='0'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_learning_insights_type_alarm', 'learning_insights', ['insight_type', 'alarm_code'])

    # 3. devices += unit_id, role_in_unit, instance_notes
    op.add_column('devices', sa.Column('unit_id', sa.Integer(), sa.ForeignKey('equipment_units.id', ondelete='SET NULL')))
    op.add_column('devices', sa.Column('role_in_unit', sa.String(100)))
    op.add_column('devices', sa.Column('instance_notes', sa.Text()))

    # 4. device_type_registry += purpose, manufacturer_info, operating_principles, typical_issues, maintenance_notes
    op.add_column('device_type_registry', sa.Column('purpose', sa.Text()))
    op.add_column('device_type_registry', sa.Column('manufacturer_info', sa.JSON(), server_default='{}'))
    op.add_column('device_type_registry', sa.Column('operating_principles', sa.Text()))
    op.add_column('device_type_registry', sa.Column('typical_issues', sa.JSON(), server_default='[]'))
    op.add_column('device_type_registry', sa.Column('maintenance_notes', sa.Text()))

    # 5. sites += grid_price_kwh
    op.add_column('sites', sa.Column('grid_price_kwh', sa.Float(), server_default='8.0'))

    # 6. sanek_feedback += session_id, message_index, correct_answer, context, feedback_detail
    try:
        op.add_column('sanek_feedback', sa.Column('session_id', sa.String(50)))
        op.add_column('sanek_feedback', sa.Column('message_index', sa.Integer()))
        op.add_column('sanek_feedback', sa.Column('correct_answer', sa.Text()))
        op.add_column('sanek_feedback', sa.Column('context', sa.JSON(), server_default='{}'))
        op.add_column('sanek_feedback', sa.Column('feedback_detail', sa.String(50)))
    except Exception:
        pass

    # 7. sanek_pattern_stats += last_context
    try:
        op.add_column('sanek_pattern_stats', sa.Column('last_context', sa.JSON(), server_default='{}'))
    except Exception:
        pass

    # 8. sop_procedures += source
    try:
        op.add_column('sop_procedures', sa.Column('source', sa.String(50)))
    except Exception:
        pass

    # 9. sanek_actions += outcome_analysis
    try:
        op.add_column('sanek_actions', sa.Column('outcome_analysis', sa.JSON()))
    except Exception:
        pass


def downgrade():
    try: op.drop_column('sanek_actions', 'outcome_analysis')
    except Exception: pass
    for col in ('source',):
        try: op.drop_column('sop_procedures', col)
        except Exception: pass
    for col in ('last_context',):
        try: op.drop_column('sanek_pattern_stats', col)
        except Exception: pass
    for col in ('feedback_detail', 'context', 'correct_answer', 'message_index', 'session_id'):
        try: op.drop_column('sanek_feedback', col)
        except Exception: pass
    op.drop_column('sites', 'grid_price_kwh')
    for col in ('maintenance_notes','typical_issues','operating_principles','manufacturer_info','purpose'):
        op.drop_column('device_type_registry', col)
    for col in ('instance_notes','role_in_unit','unit_id'):
        op.drop_column('devices', col)
    op.drop_table('learning_insights')
    op.drop_table('equipment_units')
