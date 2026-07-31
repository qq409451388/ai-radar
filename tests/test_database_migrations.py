from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from ai_radar.database import _apply_additive_migrations


def test_signal_columns_are_added_to_existing_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE source_config "
                "(id INTEGER PRIMARY KEY, name VARCHAR(128))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE change_point "
                "(id INTEGER PRIMARY KEY, title VARCHAR(512))"
            )
        )
        connection.execute(
            text("CREATE TABLE source_item (id INTEGER PRIMARY KEY)")
        )
        connection.execute(
            text("CREATE TABLE profile_source_file (id INTEGER PRIMARY KEY)")
        )
        connection.execute(
            text("CREATE TABLE knowledge_coverage (id INTEGER PRIMARY KEY)")
        )
        connection.execute(
            text("CREATE TABLE topic_snapshot (id INTEGER PRIMARY KEY)")
        )

    _apply_additive_migrations(engine)

    inspector = inspect(engine)
    source_columns = {
        column["name"] for column in inspector.get_columns("source_config")
    }
    change_columns = {
        column["name"] for column in inspector.get_columns("change_point")
    }
    item_columns = {
        column["name"] for column in inspector.get_columns("source_item")
    }
    assert "path_filter" in source_columns
    assert "test_status" in source_columns
    assert "last_tested_at" in source_columns
    assert "signal_type" in change_columns
    assert "followup_snoozed_until" in change_columns
    assert {
        "display_title",
        "display_summary",
        "display_language",
    }.issubset(item_columns)
