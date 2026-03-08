"""add sop_procedures table

Revision ID: n8g9h0i1j2k3
Revises: m7f8g9h0i1j2
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "n8g9h0i1j2k3"
down_revision = "m7f8g9h0i1j2"
branch_labels = None
depends_on = None

SEED_PROCEDURES = [
    {
        "alarm_code": "SHUTDOWN",
        "device_type": "generator",
        "root_cause": None,
        "severity": "critical",
        "version": 1,
        "description": "Emergency shutdown procedure for generator",
        "actions_json": [
            {
                "step": 1,
                "instruction": "Verify emergency shutdown cause on HMI panel",
                "ui_control": "devices/{device}/status/shutdown_reason",
                "expected_state": "SHUTDOWN_ACTIVE",
                "verification": "Shutdown reason displayed on HMI",
                "safety_note": "Do not reset until cause is identified",
            },
            {
                "step": 2,
                "instruction": "Check generator protection relay status",
                "ui_control": "devices/{device}/protection/relay_status",
                "expected_state": "TRIPPED",
                "verification": "Relay code matches shutdown cause",
                "safety_note": None,
            },
            {
                "step": 3,
                "instruction": "Verify fuel supply valve position — CLOSED",
                "ui_control": "devices/{device}/fuel/valve_position",
                "expected_state": "CLOSED",
                "verification": "Valve indicator shows CLOSED",
                "safety_note": "Ensure no fuel leaks before proceeding",
            },
            {
                "step": 4,
                "instruction": "Check coolant temperature below 60C",
                "ui_control": "devices/{device}/sensors/coolant_temp",
                "expected_state": "<60",
                "verification": "Temperature reading < 60C",
                "safety_note": "Wait for cooldown if temperature is above threshold",
            },
            {
                "step": 5,
                "instruction": "Reset protection relay and log incident",
                "ui_control": "devices/{device}/protection/reset",
                "expected_state": "READY",
                "verification": "Protection relay in READY state",
                "safety_note": "Obtain supervisor approval before reset",
            },
        ],
    },
    {
        "alarm_code": "TRIP_STOP",
        "device_type": "generator",
        "root_cause": None,
        "severity": "high",
        "version": 1,
        "description": "Generator trip stop — desynchronization recovery",
        "actions_json": [
            {
                "step": 1,
                "instruction": "Set generator synchronization mode to AUTO",
                "ui_control": "devices/{device}/controls/sync_mode",
                "expected_state": "AUTO",
                "verification": "Sync mode indicator shows AUTO",
                "safety_note": None,
            },
            {
                "step": 2,
                "instruction": "Verify phase angle difference < 5 degrees",
                "ui_control": "devices/{device}/sensors/phase_angle",
                "expected_state": "<5",
                "verification": "Phase angle delta displayed < 5 deg",
                "safety_note": "If delta > 10 deg, perform manual resynchronization",
            },
            {
                "step": 3,
                "instruction": "Verify generator voltage 400V +/-10V",
                "ui_control": "devices/{device}/sensors/voltage",
                "expected_state": "390-410",
                "verification": "Voltage within 390-410V range",
                "safety_note": None,
            },
            {
                "step": 4,
                "instruction": "Verify frequency 50Hz +/-0.5Hz",
                "ui_control": "devices/{device}/sensors/frequency",
                "expected_state": "49.5-50.5",
                "verification": "Frequency within 49.5-50.5Hz range",
                "safety_note": None,
            },
            {
                "step": 5,
                "instruction": "Close contactor K1",
                "ui_control": "devices/{device}/controls/contactor_k1",
                "expected_state": "CLOSED",
                "verification": "Contactor K1 status shows CLOSED",
                "safety_note": "Ensure all sync parameters are within limits before closing",
            },
        ],
    },
    {
        "alarm_code": "CONN_LOST",
        "device_type": "any",
        "root_cause": None,
        "severity": "high",
        "version": 1,
        "description": "Communication loss recovery procedure",
        "actions_json": [
            {
                "step": 1,
                "instruction": "Check network connectivity to device controller",
                "ui_control": "devices/{device}/network/status",
                "expected_state": "ONLINE",
                "verification": "Ping response from controller IP",
                "safety_note": None,
            },
            {
                "step": 2,
                "instruction": "Verify Modbus/TCP gateway status",
                "ui_control": "system/gateways/{gateway}/status",
                "expected_state": "CONNECTED",
                "verification": "Gateway shows active connections",
                "safety_note": None,
            },
            {
                "step": 3,
                "instruction": "Check last known device state in SCADA historian",
                "ui_control": "devices/{device}/historian/last_state",
                "expected_state": None,
                "verification": "Last state timestamp < 5 minutes ago",
                "safety_note": "If device was in critical state before disconnect, dispatch field operator",
            },
            {
                "step": 4,
                "instruction": "Attempt communication restart via gateway reset",
                "ui_control": "system/gateways/{gateway}/controls/restart",
                "expected_state": "RESTARTING",
                "verification": "Gateway reconnects within 30 seconds",
                "safety_note": "Only one restart attempt; escalate if unsuccessful",
            },
        ],
    },
    {
        "alarm_code": "BLOCK",
        "device_type": "any",
        "root_cause": None,
        "severity": "medium",
        "version": 1,
        "description": "Device block/interlock active",
        "actions_json": [
            {
                "step": 1,
                "instruction": "Identify active interlock condition on HMI",
                "ui_control": "devices/{device}/interlocks/active",
                "expected_state": None,
                "verification": "Interlock condition code identified",
                "safety_note": "Do not bypass interlocks without engineering approval",
            },
            {
                "step": 2,
                "instruction": "Verify prerequisite conditions for interlock release",
                "ui_control": "devices/{device}/interlocks/prerequisites",
                "expected_state": "ALL_MET",
                "verification": "All prerequisite indicators green",
                "safety_note": None,
            },
            {
                "step": 3,
                "instruction": "Release interlock and confirm device returns to READY",
                "ui_control": "devices/{device}/interlocks/release",
                "expected_state": "READY",
                "verification": "Device status shows READY, no active alarms",
                "safety_note": "Monitor device for 5 minutes after release",
            },
        ],
    },
    {
        "alarm_code": "MAINTENANCE_OVERDUE",
        "device_type": "any",
        "root_cause": None,
        "severity": "low",
        "version": 1,
        "description": "Scheduled maintenance overdue",
        "actions_json": [
            {
                "step": 1,
                "instruction": "Review maintenance schedule and identify overdue tasks",
                "ui_control": "maintenance/{device}/schedule",
                "expected_state": None,
                "verification": "Overdue task list retrieved",
                "safety_note": None,
            },
            {
                "step": 2,
                "instruction": "Create maintenance work order in CMMS",
                "ui_control": "cmms/work_orders/create",
                "expected_state": "CREATED",
                "verification": "Work order number assigned",
                "safety_note": None,
            },
            {
                "step": 3,
                "instruction": "Acknowledge alarm and set maintenance reminder for 24h",
                "ui_control": "devices/{device}/alarms/acknowledge",
                "expected_state": "ACKNOWLEDGED",
                "verification": "Alarm status shows ACKNOWLEDGED with reminder set",
                "safety_note": "Do not silence alarm without creating work order",
            },
        ],
    },
]


def upgrade() -> None:
    op.create_table(
        "sop_procedures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alarm_code", sa.String(64), nullable=False),
        sa.Column("device_type", sa.String(64), nullable=False),
        sa.Column("root_cause", sa.String(128), nullable=True),
        sa.Column("severity", sa.String(32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("actions_json", JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_sop_procedures_alarm_code", "sop_procedures", ["alarm_code"])
    op.create_index("ix_sop_procedures_device_type", "sop_procedures", ["device_type"])
    op.create_index("ix_sop_procedures_root_cause", "sop_procedures", ["root_cause"])
    op.create_index(
        "ix_sop_procedures_alarm_device_cause",
        "sop_procedures",
        ["alarm_code", "device_type", "root_cause"],
    )

    # Seed data
    sop_table = sa.table(
        "sop_procedures",
        sa.column("alarm_code", sa.String),
        sa.column("device_type", sa.String),
        sa.column("root_cause", sa.String),
        sa.column("severity", sa.String),
        sa.column("version", sa.Integer),
        sa.column("description", sa.Text),
        sa.column("actions_json", JSONB),
    )
    for proc in SEED_PROCEDURES:
        op.execute(sop_table.insert().values(**proc))


def downgrade() -> None:
    op.drop_index("ix_sop_procedures_alarm_device_cause", table_name="sop_procedures")
    op.drop_index("ix_sop_procedures_root_cause", table_name="sop_procedures")
    op.drop_index("ix_sop_procedures_device_type", table_name="sop_procedures")
    op.drop_index("ix_sop_procedures_alarm_code", table_name="sop_procedures")
    op.drop_table("sop_procedures")
