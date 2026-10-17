"""Private append-only records; every repository query requires an explicit tenant."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models import Base


class PrivateRecord:
    """Common immutable identity, tenant ownership and availability metadata."""

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)


class ExportCostQuote(PrivateRecord, Base):
    __tablename__ = "export_cost_quotes"
    __table_args__ = (
        UniqueConstraint("record_id", "tenant_id", name="uq_export_cost_quotes_record_tenant"),
    )
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    destination: Mapped[str] = mapped_column(ForeignKey("countries.country_code"))


class EvidenceDocument(PrivateRecord, Base):
    __tablename__ = "evidence_documents"
    __table_args__ = (
        UniqueConstraint("record_id", "tenant_id", name="uq_evidence_documents_record_tenant"),
    )
    source_url: Mapped[str] = mapped_column(String(2048))
    content_sha256: Mapped[str] = mapped_column(String(64))
    text_content: Mapped[str] = mapped_column(Text)


class PolicyRule(PrivateRecord, Base):
    __tablename__ = "policy_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["evidence_documents.record_id", "evidence_documents.tenant_id"],
            name="fk_policy_rules_document_tenant",
        ),
    )
    product_id: Mapped[str] = mapped_column(ForeignKey("products.product_id"))
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.country_code"))
    document_id: Mapped[str] = mapped_column(String(64))
    rule_key: Mapped[str] = mapped_column(String(80))


class CountryRisk(PrivateRecord, Base):
    __tablename__ = "country_risk_indicators"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["evidence_documents.record_id", "evidence_documents.tenant_id"],
            name="fk_country_risk_indicators_document_tenant",
        ),
    )
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.country_code"))
    document_id: Mapped[str] = mapped_column(String(64))


class MarketEvent(PrivateRecord, Base):
    __tablename__ = "market_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["evidence_documents.record_id", "evidence_documents.tenant_id"],
            name="fk_market_events_document_tenant",
        ),
        UniqueConstraint("tenant_id", "event_key", name="uq_market_events_tenant_event"),
    )
    document_id: Mapped[str] = mapped_column(String(64))
    event_key: Mapped[str] = mapped_column(String(64))


class CommercialDecision(PrivateRecord, Base):
    __tablename__ = "commercial_decisions"
    __table_args__ = (
        UniqueConstraint("record_id", "tenant_id", name="uq_commercial_decisions_record_tenant"),
        ForeignKeyConstraint(
            ["quote_id", "tenant_id"],
            ["export_cost_quotes.record_id", "export_cost_quotes.tenant_id"],
            name="fk_commercial_decisions_quote_tenant",
        ),
    )
    quote_id: Mapped[str] = mapped_column(String(64))
    prediction_id: Mapped[str | None] = mapped_column(ForeignKey("predictions.prediction_id"))


class AuditLog(PrivateRecord, Base):
    __tablename__ = "audit_logs"
    actor_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(64))
