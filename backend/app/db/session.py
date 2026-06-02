"""Engine and session factory.

A single SQLite file under the data directory backs the MVP. ``init_db`` creates
all tables (Alembic will own migrations once the schema stabilizes). WAL mode is
enabled for better concurrent read/write behavior with the background trading
loop and the API serving reads.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import get_logger
from app.db.base import Base

logger = get_logger("db")

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(data_dir: Path) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "trader.db"
    _engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    logger.info("database engine initialized at %s", db_path)
    return _engine


def init_db(data_dir: Path) -> None:
    """Create the engine (if needed) and all tables."""
    # Import models so they are registered on the metadata before create_all.
    from app.db import models  # noqa: F401

    engine = init_engine(data_dir)
    Base.metadata.create_all(engine)
    logger.info("database tables ensured (%d tables)", len(Base.metadata.tables))


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("database not initialized; call init_db() first")
    return _SessionLocal()
