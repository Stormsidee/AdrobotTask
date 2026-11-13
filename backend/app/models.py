from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(96), unique=True)
    country: Mapped[str] = mapped_column(String(2))
    domain_id: Mapped[int]
    group_id: Mapped[int]
    source_id: Mapped[int]


class StreamOffer(Base):
    __tablename__ = "stream_offers"

    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), primary_key=True)
    offer_id: Mapped[int] = mapped_column(primary_key=True)
    share: Mapped[int] = mapped_column(default=1)


class DailyStat(Base):
    __tablename__ = "daily_stats"

    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), primary_key=True)
    offer_id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    clicks: Mapped[int]
    conversions: Mapped[int]
