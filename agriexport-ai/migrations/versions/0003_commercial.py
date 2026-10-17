"""Tenant-scoped quotation, evidence and decision storage, including PostgreSQL RLS."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = (
    "export_cost_quotes",
    "evidence_documents",
    "policy_rules",
    "country_risk_indicators",
    "market_events",
    "commercial_decisions",
    "audit_logs",
)


def private_table(name: str, *columns) -> None:
    """Frozen shared migration columns; never import mutable ORM definitions."""
    constraints = []
    if name in {"export_cost_quotes", "evidence_documents"}:
        constraints.append(
            sa.UniqueConstraint("record_id", "tenant_id", name=f"uq_{name}_record_tenant")
        )
    if name in {"policy_rules", "country_risk_indicators", "market_events"}:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["document_id", "tenant_id"],
                ["evidence_documents.record_id", "evidence_documents.tenant_id"],
                name=f"fk_{name}_document_tenant",
            )
        )
    if name == "commercial_decisions":
        constraints.append(
            sa.ForeignKeyConstraint(
                ["quote_id", "tenant_id"],
                ["export_cost_quotes.record_id", "export_cost_quotes.tenant_id"],
                name=f"fk_{name}_quote_tenant",
            )
        )
    if name == "market_events":
        constraints.append(
            sa.UniqueConstraint("tenant_id", "event_key", name="uq_market_events_tenant_event")
        )
    op.create_table(
        name,
        sa.Column("record_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        *columns,
        *constraints,
    )
    op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
    op.create_index(f"ix_{name}_created_at", name, ["created_at"])


def upgrade() -> None:
    """Create private tables and fail-closed tenant policies on PostgreSQL."""
    private_table(
        "export_cost_quotes",
        sa.Column(
            "product_id", sa.String(80), sa.ForeignKey("products.product_id"), nullable=False
        ),
        sa.Column(
            "destination", sa.String(3), sa.ForeignKey("countries.country_code"), nullable=False
        ),
    )
    private_table(
        "evidence_documents",
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("text_content", sa.Text, nullable=False),
    )
    private_table(
        "policy_rules",
        sa.Column(
            "product_id", sa.String(80), sa.ForeignKey("products.product_id"), nullable=False
        ),
        sa.Column(
            "country_code", sa.String(3), sa.ForeignKey("countries.country_code"), nullable=False
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            nullable=False,
        ),
        sa.Column("rule_key", sa.String(80), nullable=False),
    )
    private_table(
        "country_risk_indicators",
        sa.Column(
            "country_code", sa.String(3), sa.ForeignKey("countries.country_code"), nullable=False
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            nullable=False,
        ),
    )
    private_table(
        "market_events",
        sa.Column(
            "document_id",
            sa.String(64),
            nullable=False,
        ),
        sa.Column("event_key", sa.String(64), nullable=False),
    )
    private_table(
        "commercial_decisions",
        sa.Column("quote_id", sa.String(64), nullable=False),
        sa.Column("prediction_id", sa.String(64), sa.ForeignKey("predictions.prediction_id")),
    )
    private_table(
        "audit_logs",
        sa.Column("actor_id", sa.String(80), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))''')


def downgrade() -> None:
    """Explicit isolated/test rollback only."""
    for table in reversed(TABLES):
        op.drop_table(table)
