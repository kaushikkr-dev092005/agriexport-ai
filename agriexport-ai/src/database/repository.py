"""Idempotent ingestion and point-in-time revision selection."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session

from src.database.models import Base, Country, Product, RawArtifact, TradeObservation
from src.processing.hs_mapping import catalogue, validate_mapping
from src.processing.validation import TradeRow


def make_engine(url: str) -> Engine:
    """Create an explicit engine; SQLite is for local acceptance tests only."""
    engine = create_engine(url)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def seed(session: Session) -> None:
    """Seed classifications and the minimal verified M49 reference set."""
    for p in catalogue():
        existing = session.get(Product, p["product_id"])
        if existing:
            if (existing.hs_code, existing.hs_revision) != (p["hs_code"], p["hs_revision"]):
                raise ValueError("Existing product HS changed; reviewed migration required")
            existing.metadata_json = p
        else:
            session.add(
                Product(
                    **{
                        k: p[k]
                        for k in ("product_id", "hs_code", "hs_revision", "name", "category")
                    },
                    unit="tonne",
                    metadata_json=p,
                )
            )
    for code, name in [
        ("000", "World (aggregate)"),
        ("356", "India"),
        ("156", "China"),
        ("682", "Saudi Arabia"),
        ("840", "United States"),
        ("784", "United Arab Emirates"),
        ("826", "United Kingdom"),
        ("528", "Netherlands"),
        ("050", "Bangladesh"),
        ("144", "Sri Lanka"),
    ]:
        if not session.get(Country, code):
            session.add(Country(country_code=code, name=name))
    session.flush()


def ingest(session: Session, rows: list[TradeRow], artifact_path: str) -> int:
    """Validate the entire batch before writes; caller owns the transaction."""
    for row in rows:
        validate_mapping(row.product_id, row.hs_code, row.hs_revision)
        for country in (row.reporter, row.partner):
            if not session.get(Country, country):
                raise ValueError(f"Unverified M49 country: {country}; add reviewed reference first")
    inserted = 0
    for row in rows:
        if not session.get(RawArtifact, row.raw_sha256):
            session.add(
                RawArtifact(
                    sha256=row.raw_sha256,
                    source_url=row.source_url,
                    storage_path=artifact_path,
                    retrieved_at=row.retrieved_at,
                )
            )
            session.flush()
        identity = {
            k: str(getattr(row, k))
            for k in (
                "source_url",
                "product_id",
                "reporter",
                "partner",
                "period",
                "flow",
                "revision",
                "published_at",
            )
        }
        oid = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        if session.get(TradeObservation, oid):
            existing = session.get(TradeObservation, oid)
            if (
                existing.quantity != row.quantity_tonnes
                or existing.value != row.value
                or existing.currency != row.currency
                or existing.synthetic != row.synthetic
            ):
                raise ValueError("Conflicting immutable revision; supply a new revision")
            continue
        values = row.model_dump(exclude={"hs_code", "hs_revision", "quantity_unit"})
        values["quantity"] = row.quantity_tonnes
        session.add(TradeObservation(observation_id=oid, unit="tonne", **values))
        session.flush()
        inserted += 1
    return inserted


def snapshot(
    session: Session,
    as_of: datetime,
    product_id: str | None = None,
    partner: str | None = None,
    include_synthetic: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[TradeObservation]:
    """Pick latest available revision per source/series, then page deterministically.

    Separate sources are never silently summed; cross-source deduplication needs review.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    as_of = as_of.astimezone(UTC)
    query = select(TradeObservation).where(TradeObservation.published_at <= as_of)
    if not include_synthetic:
        query = query.where(TradeObservation.synthetic.is_(False))
    if product_id:
        query = query.where(TradeObservation.product_id == product_id)
    if partner:
        query = query.where(TradeObservation.partner == partner)
    filtered = query.subquery()
    ranked = select(
        filtered.c.observation_id,
        func.row_number()
        .over(
            partition_by=[
                filtered.c.source_url,
                filtered.c.product_id,
                filtered.c.reporter,
                filtered.c.partner,
                filtered.c.period,
                filtered.c.flow,
            ],
            order_by=[
                filtered.c.published_at.desc(),
                filtered.c.retrieved_at.desc(),
                filtered.c.revision.desc(),
            ],
        )
        .label("rank"),
    ).subquery()
    return list(
        session.scalars(
            select(TradeObservation)
            .join(ranked, TradeObservation.observation_id == ranked.c.observation_id)
            .where(ranked.c.rank == 1)
            .order_by(TradeObservation.period.desc(), TradeObservation.observation_id)
            .limit(limit)
            .offset(offset)
        )
    )


def init_local(engine: Engine) -> None:
    """Create a disposable local schema; production uses Alembic."""
    from src.database import (
        commercial_models,  # noqa: F401
        pilot_models,  # noqa: F401
    )

    # Older local schemas need a composite unique reference without rewriting records.
    if engine.dialect.name == "sqlite" and inspect(engine).has_table("commercial_decisions"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_local_decision_tenant ON commercial_decisions(record_id, tenant_id)"
                )
            )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        seed(session)
