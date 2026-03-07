"""Gas price tracking per site.

Stores historical gas prices with effective dates.
Used by the Economics view to calculate cost per kWh.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class GasPrice(TimestampMixin, Base):
    __tablename__ = "gas_prices"
    __table_args__ = (
        UniqueConstraint("site_id", "effective_from", name="uq_gas_price_site_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE")
    )
    effective_from: Mapped[date] = mapped_column(Date)
    price_per_m3: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200), default=None)
