"""Real PostgreSQL integration, enabled only for an explicitly supplied isolated test DB."""

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.main import create_app
from src.database.models import Base
from src.database.repository import ingest, make_engine, seed, snapshot
from tests.test_foundation import NOW, synthetic_row

pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_TEST_URL"), reason="Isolated POSTGRES_TEST_URL not supplied"
)


def test_real_postgres_migration_temporal_rows_and_api(monkeypatch):
    url = os.environ["POSTGRES_TEST_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        with Session(engine) as session, session.begin():
            seed(session)
            assert ingest(session, [synthetic_row()], "SYNTHETIC.raw") == 1
            assert ingest(session, [synthetic_row()], "SYNTHETIC.raw") == 0
            rows = snapshot(session, NOW, include_synthetic=True)
            assert len(rows) == 1 and rows[0].published_at.tzinfo is not None
            assert rows[0].quantity == 2
            assert snapshot(session, NOW) == []
        client = TestClient(create_app(engine))
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/trade").json() == []
        response = client.get("/api/v1/trade?include_synthetic=true")
        assert response.status_code == 200 and response.json()[0]["synthetic"]
    finally:
        engine.dispose()
