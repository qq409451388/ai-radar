from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_inbox_tabs_use_distinct_change_range_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database
    from ai_radar.config import reset_config

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        app = AppTest.from_file("pages/inbox.py", default_timeout=10).run()

        assert not app.exception
        assert [control.key for control in app.segmented_control] == [
            "inbox_change_range_design",
            "inbox_change_range_all",
        ]
    finally:
        reset_config()
        database.reset_engine()
