from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(20), unique=True)  # "MKZ", "YKZ"
    network: Mapped[str] = mapped_column(String(20))  # "192.168.97.x"
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)

    devices = relationship("Device", back_populates="site", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Site {self.code} ({self.name})>"
