"""Planned fixed costs per site/year/month.

Stores monthly planned overhead costs (oil, parts, salary, leasing, etc.)
Used by the Economics module to calculate full cost per kWh.
"""
from __future__ import annotations

from sqlalchemy import Integer, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class PlannedCost(TimestampMixin, Base):
    __tablename__ = "planned_costs"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "year", "month", "category",
            name="uq_planned_cost_site_year_month_cat",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE")
    )
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1-12
    category: Mapped[str] = mapped_column(String(50))
    category_name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float, default=0)
