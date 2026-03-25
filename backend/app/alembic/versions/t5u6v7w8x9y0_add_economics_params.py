"""add planned_costs and grid_prices tables

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-03-16 14:00:00.000000

Adds:
- planned_costs table (monthly overhead costs per site)
- grid_prices table (grid electricity tariff history per site)
- Seed data: МКЗ planned costs 2026, grid prices for both sites
"""

from alembic import op
import sqlalchemy as sa

revision = "t5u6v7w8x9y0"
down_revision = "s4t5u6v7w8x9"
branch_labels = None
depends_on = None

# ─── Seed data from TZ ───

PLANNED_COSTS_MKZ_2026 = [
    ("oil",         "Масло",                         [33400]*12),
    ("parts",       "Запчасти, антифриз и пр.",       [59000]*12),
    ("service",     "Обслуживание стор. организации",  [25350]*12),
    ("salary",      "Зарплата персоналу",              [23000]*12),
    ("payroll_tax", "Отчисления от ФОТ",               [5750]*12),
    ("overhaul",    "Капремонт",                       [0,0,0,0,0,0,0,0,1000000,0,1000000,0]),
    ("insurance",   "Страхование ГПУ",                 [0,0,0,0,32760,0,0,0,0,0,0,0]),
    ("leasing",     "Лизинг/Амортизация",              [315564]*12),
]


def upgrade() -> None:
    # ── planned_costs ──
    op.create_table(
        "planned_costs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("category_name", sa.String(200), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "year", "month", "category", name="uq_planned_cost_site_year_month_cat"),
    )
    op.create_index("idx_planned_costs_lookup", "planned_costs", ["site_id", "year", "month"])

    # ── grid_prices ──
    op.create_table(
        "grid_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("price_per_kwh", sa.Float(), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "effective_from", name="uq_grid_price_site_date"),
    )
    op.create_index("idx_grid_prices_lookup", "grid_prices", ["site_id", sa.text("effective_from DESC")])

    # ── Seed: planned_costs МКЗ 2026 ──
    planned_costs = sa.table(
        "planned_costs",
        sa.column("site_id", sa.Integer),
        sa.column("year", sa.Integer),
        sa.column("month", sa.Integer),
        sa.column("category", sa.String),
        sa.column("category_name", sa.String),
        sa.column("amount", sa.Float),
    )
    rows = []
    for site_id in (3, 5):
        for cat, cat_name, months in PLANNED_COSTS_MKZ_2026:
            for m_idx, amount in enumerate(months, 1):
                rows.append({
                    "site_id": site_id,
                    "year": 2026,
                    "month": m_idx,
                    "category": cat,
                    "category_name": cat_name,
                    "amount": float(amount) if site_id == 3 else 0.0,
                })
    op.bulk_insert(planned_costs, rows)

    # ── Seed: grid_prices ──
    grid_prices = sa.table(
        "grid_prices",
        sa.column("site_id", sa.Integer),
        sa.column("effective_from", sa.Date),
        sa.column("price_per_kwh", sa.Float),
        sa.column("note", sa.String),
    )
    from datetime import date
    grid_rows = [
        {"site_id": 3, "effective_from": date(2026, 1, 1), "price_per_kwh": 6.42,  "note": "1 полугодие 2026"},
        {"site_id": 3, "effective_from": date(2026, 7, 1), "price_per_kwh": 7.062, "note": "2 полугодие 2026"},
        {"site_id": 5, "effective_from": date(2026, 1, 1), "price_per_kwh": 6.42,  "note": "1 полугодие 2026"},
        {"site_id": 5, "effective_from": date(2026, 7, 1), "price_per_kwh": 7.062, "note": "2 полугодие 2026"},
    ]
    op.bulk_insert(grid_prices, grid_rows)


def downgrade() -> None:
    op.drop_index("idx_grid_prices_lookup", table_name="grid_prices")
    op.drop_table("grid_prices")
    op.drop_index("idx_planned_costs_lookup", table_name="planned_costs")
    op.drop_table("planned_costs")
