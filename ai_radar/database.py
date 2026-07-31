"""SQLAlchemy declarative base and database session management."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ai_radar.config import get_config


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _build_engine() -> Engine:
    config = get_config()
    engine = create_engine(
        config.db_url,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        # Enable foreign keys + WAL for better concurrency on SQLite.
        # busy_timeout: writers wait up to 10s for the lock instead of failing
        # immediately with "database is locked" (Streamlit + scheduler threads).
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            future=True,
            expire_on_commit=False,
        )
    return _SessionLocal


def reset_engine() -> None:
    """Reset the engine/session cache (used by tests that swap DB paths)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def init_db() -> None:
    """Create tables and apply small additive migrations.

    The project intentionally stays migration-tool free for now.  All upgrades
    are additive so an existing personal database can be opened safely.
    """
    import ai_radar.models  # noqa: F401 — ensure models are imported

    engine = get_engine()
    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)


def _apply_additive_migrations(engine: Engine) -> None:
    additions: dict[str, dict[str, str]] = {
        "source_item": {
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "next_retry_at": "DATETIME",
            "last_analyzed_at": "DATETIME",
        },
        "profile_source_file": {
            "extracted_content_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "extraction_status": "VARCHAR(16) NOT NULL DEFAULT 'PENDING'",
            "extraction_error": "TEXT NOT NULL DEFAULT ''",
            "last_extracted_at": "DATETIME",
        },
        "knowledge_coverage": {
            "trigger_type": "VARCHAR(32) NOT NULL DEFAULT 'SCHEDULED'",
            "assessment_fingerprint": "VARCHAR(64) NOT NULL DEFAULT ''",
        },
        "topic_snapshot": {
            "recent_score": "FLOAT NOT NULL DEFAULT 0",
            "important_gap_count": "INTEGER NOT NULL DEFAULT 0",
            "practiced_rate": "FLOAT NOT NULL DEFAULT 0",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name, columns in additions.items():
            existing = {c["name"] for c in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    conn.execute(
                        text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl}')
                    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager that yields a Session and commits/rolls back on exit."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Return a raw Session (caller manages commit/close)."""
    return get_sessionmaker()()
