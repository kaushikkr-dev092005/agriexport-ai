"""Browser-test API: copies genuine local public data, adds only SYNTHETIC private credentials."""

import hashlib
import sqlite3
import tempfile
from pathlib import Path

from apps.api.auth import Credential
from apps.api.main import create_app as api_factory
from src.database.repository import init_local, make_engine


def create_app():
    """Never modify the operator's database or expose a production token to browser tests."""
    root = Path(__file__).resolve().parents[1]
    target = Path(tempfile.mkdtemp(prefix="SYNTHETIC-browser-")) / "test.db"
    source = root / "data/local.db"
    if source.exists():
        with (
            sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original,
            sqlite3.connect(target) as copy,
        ):
            original.backup(copy)
    engine = make_engine(f"sqlite:///{target.as_posix()}")
    init_local(engine)
    credentials = {
        hashlib.sha256(token.encode()).hexdigest(): Credential(
            tenant_id=tenant, actor_id=token, roles={"admin"}
        )
        for token, tenant in (
            ("SYNTHETIC-BROWSER-A", "SYNTHETIC-BROWSER-A"),
            ("SYNTHETIC-BROWSER-B", "SYNTHETIC-BROWSER-B"),
        )
    }
    return api_factory(engine, credentials)
