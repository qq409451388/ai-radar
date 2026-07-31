from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_inbox_renders_only_the_selected_view(tmp_path, monkeypatch):
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
            "inbox_view",
            "inbox_change_range_design",
        ]

        app.segmented_control(key="inbox_view").set_value("changes").run()

        assert not app.exception
        assert [control.key for control in app.segmented_control] == [
            "inbox_view",
            "inbox_change_range_all",
        ]
    finally:
        reset_config()
        database.reset_engine()


def test_queue_is_paginated_and_shows_colored_source_title(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import SourceConfig, SourceItem

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        with session_scope() as session:
            source = SourceConfig(
                name="OpenAI Changelog",
                source_type="RSS",
                url="https://example.com/feed",
                enabled=True,
                test_status="PASSED",
            )
            session.add(source)
            session.flush()
            session.add_all(
                [
                    SourceItem(
                        source_config_id=source.id,
                        external_id=f"item-{index}",
                        title=f"English intelligence {index}",
                        display_title=f"中文情报 {index}",
                        display_summary="中文摘要",
                        display_language="zh-CN",
                        url=f"https://example.com/{index}",
                        raw_content="content",
                        content_hash=f"hash-{index}",
                        analyze_status="PENDING",
                    )
                    for index in range(25)
                ]
            )

        app = AppTest.from_file("pages/inbox.py", default_timeout=10)
        app.query_params = {"view": "queue"}
        app.run()

        assert not app.exception
        headings = [
            markdown.value
            for markdown in app.markdown
            if "inbox-list-heading" in markdown.value
        ]
        assert len(headings) == 20
        assert all("OpenAI Changelog" in heading for heading in headings)
        assert all("中文情报" in heading for heading in headings)
        assert all("English intelligence" not in heading for heading in headings)
        assert any("inbox-source-inline rss" in heading for heading in headings)
    finally:
        reset_config()
        database.reset_engine()
