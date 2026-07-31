"""Shared pytest fixtures: isolated in-memory SQLite per test."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Force a temp DB path BEFORE importing app modules.
_TMP = tempfile.mkdtemp(prefix="ai_radar_test_")
os.environ["AI_RADAR_DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ["AI_RADAR_CONFIG_DIR"] = str(Path(_TMP) / "config")
os.environ.setdefault("AI_RADAR_SCHEDULER_ENABLED", "false")


@pytest.fixture()
def session():
    """Yield a fresh, rolled-back session backed by a temp SQLite file."""
    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import init_db, session_scope

    reset_config()
    database.reset_engine()
    init_db()
    with session_scope() as s:
        yield s
        s.rollback()


@pytest.fixture()
def seeded_session(session):
    from ai_radar.bootstrap import seed_default_data

    seed_default_data(session)
    return session
