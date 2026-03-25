"""Grid electricity price tracking per site.

Stores historical grid prices with effective dates.
Replaces the single sites.grid_price_kwh field.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class GridPrice(TimestampMixin, Base):
    __tablename__ = "grid_prices"
    __table_args__ = (
        UniqueConstraint("site_id", "effective_from", name="uq_grid_price_site_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE")
    )
    effective_from: Mapped[date] = mapped_column(Date)
    price_per_kwh: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200), default=None)
