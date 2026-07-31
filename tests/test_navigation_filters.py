from __future__ import annotations

import yaml
from streamlit.testing.v1 import AppTest


def test_knowledge_deep_link_opens_selected_change_point(
    tmp_path,
    monkeypatch,
):
    _configure_ready_app(tmp_path, monkeypatch)

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import ChangePoint, Topic
    from ai_radar.scheduler import shutdown_scheduler

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        with session_scope() as session:
            topic = Topic(name="MCP / Tools / Skills")
            session.add(topic)
            session.flush()
            change_point = ChangePoint(
                topic_id=topic.id,
                event_key="deep-link",
                title="MCP authentication",
                summary="Authentication specification changed.",
                signal_type="STANDARD",
                importance=5,
                status="ACTIVE",
            )
            session.add(change_point)
            session.flush()
            change_point_id = change_point.id

        app = AppTest.from_file("app.py", default_timeout=10).run()
        app.query_params = {"change_point": str(change_point_id)}
        app.switch_page("pages/knowledge.py").run()

        assert not app.exception
        assert len(app.expander) == 1
        assert "MCP authentication" in app.expander[0].label
        assert app.expander[0].proto.expanded is True
        assert any(
            "正在查看首页选中的知识点" in str(item.value)
            for item in app.info
        )

        app.query_params = {
            "signals": "STANDARD,ARCHITECTURE",
            "period": "7d",
        }
        app.switch_page("pages/knowledge.py").run()
        assert not app.exception
        assert app.multiselect(key="knowledge_signals").value == [
            "STANDARD",
            "ARCHITECTURE",
        ]
        assert app.selectbox(key="knowledge_period").value == "7d"
    finally:
        shutdown_scheduler()
        reset_config()
        database.reset_engine()


def test_inbox_deep_link_applies_period_topic_and_signal_filters(
    tmp_path,
    monkeypatch,
):
    _configure_ready_app(tmp_path, monkeypatch)

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import Topic
    from ai_radar.scheduler import shutdown_scheduler

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        with session_scope() as session:
            topic = Topic(name="Java AI 生态")
            session.add(topic)
            session.flush()
            topic_id = topic.id

        app = AppTest.from_file("app.py", default_timeout=10).run()
        app.query_params = {
            "view": "changes",
            "period": "7d",
            "topic": str(topic_id),
            "signals": "STANDARD",
        }
        app.switch_page("pages/inbox.py").run()

        assert not app.exception
        assert app.segmented_control(key="inbox_change_range_all").value == "7 天"
        assert app.selectbox(key="inbox_change_topic_all").value == topic_id
        assert app.multiselect(key="inbox_change_signals_all").value == [
            "STANDARD"
        ]
    finally:
        shutdown_scheduler()
        reset_config()
        database.reset_engine()


def _configure_ready_app(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")
    (config_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "llm": {
                    "base_url": "https://example.com/v1",
                    "api_key": "test-key",
                    "model": "test-model",
                },
                "github": {"token": "test-token"},
                "profile": {
                    "repo": "owner/memory",
                    "ref": "main",
                    "token": "test-token",
                },
                "app": {
                    "db_path": str(tmp_path / "radar.db"),
                    "scheduler_enabled": False,
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
