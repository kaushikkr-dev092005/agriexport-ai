"""Portable SQLAlchemy models; PostgreSQL is the production target."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Migration metadata root."""


class Product(Base):
    """Broad product classification; legal detail explicitly unverified."""

    __tablename__ = "products"
    product_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    hs_code: Mapped[str] = mapped_column(String(8))
    hs_revision: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(16), default="tonne")
    metadata_json: Mapped[dict] = mapped_column(JSON)


class Country(Base):
    """UN M49 identifiers stored as strings, including leading zeroes."""

    __tablename__ = "countries"
    country_code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class RawArtifact(Base):
    """Content-addressed source artifact manifest."""

    __tablename__ = "raw_artifacts"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(2048))
    storage_path: Mapped[str] = mapped_column(String(2048))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradeObservation(Base):
    """Immutable observations; multiple revisions coexist."""

    __tablename__ = "trade_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_url",
            "product_id",
            "reporter",
            "partner",
            "period",
            "flow",
            "revision",
            "published_at",
        ),
    )
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"), index=True)
    reporter: Mapped[str] = mapped_column(ForeignKey("countries.country_code"))
    partner: Mapped[str] = mapped_column(ForeignKey("countries.country_code"), index=True)
    period: Mapped[date] = mapped_column(Date)
    event_date: Mapped[date] = mapped_column(Date)
    flow: Mapped[str] = mapped_column(String(1))
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 6))
    unit: Mapped[str] = mapped_column(String(16), default="tonne")
    value: Mapped[Decimal] = mapped_column(Numeric(28, 6))
    currency: Mapped[str] = mapped_column(String(3))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(String(2048))
    raw_sha256: Mapped[str] = mapped_column(ForeignKey("raw_artifacts.sha256"))
    availability_basis: Mapped[str] = mapped_column(String(32))
    publication_evidence_url: Mapped[str | None] = mapped_column(String(2048))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class Prediction(Base):
    """Immutable baseline/context run; unknown weekly demand/margins stay SQL NULL."""

    __tablename__ = "predictions"
    __table_args__ = (CheckConstraint("horizon_days IN (7, 14, 28)", name="supported_horizon"),)
    prediction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    destination: Mapped[str] = mapped_column(ForeignKey("countries.country_code"))
    horizon_days: Mapped[int] = mapped_column(Integer)
    forecast_origin: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    demand_forecast: Mapped[Decimal | None] = mapped_column(Numeric(28, 6))
    margin_forecast: Mapped[Decimal | None] = mapped_column(Numeric(28, 6))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    model_version: Mapped[str] = mapped_column(String(100))
    input_snapshot_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
