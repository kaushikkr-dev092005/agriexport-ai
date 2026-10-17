"""Tenant-bound transactions, append-only writes and audit records."""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from apps.api.auth import Principal
from src.database.commercial_models import AuditLog


@contextmanager
def tenant_session(engine: Engine, principal: Principal):
    """Set transaction-local RLS context and retain application filters on every read."""
    with Session(engine) as session, session.begin():
        if engine.dialect.name == "postgresql":
            session.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": principal.tenant_id},
            )
        yield session


def owned(session: Session, model, record_id: str, principal: Principal):
    """Return None for missing and cross-tenant records alike."""
    return session.scalar(
        select(model).where(model.record_id == record_id, model.tenant_id == principal.tenant_id)
    )


def records(session: Session, model, principal: Principal, limit: int = 200) -> list:
    """Private list reads never use an unscoped session.get or accept a request tenant ID."""
    return list(
        session.scalars(
            select(model)
            .where(model.tenant_id == principal.tenant_id)
            .order_by(model.created_at.desc())
            .limit(limit)
        )
    )


def append_record(
    session: Session,
    model,
    principal: Principal,
    payload: dict,
    action: str,
    synthetic: bool = False,
    **columns,
):
    """Commit record and success audit together, or neither."""
    now = datetime.now(UTC)
    record = model(
        record_id=uuid.uuid4().hex,
        tenant_id=principal.tenant_id,
        created_at=now,
        payload=payload,
        synthetic=synthetic,
        **columns,
    )
    session.add(record)
    session.add(
        AuditLog(
            record_id=uuid.uuid4().hex,
            tenant_id=principal.tenant_id,
            created_at=now,
            actor_id=principal.actor_id,
            action=action,
            entity_id=record.record_id,
            payload={"outcome": "success"},
            synthetic=synthetic,
        )
    )
    session.flush()
    return record
