from __future__ import annotations

import yaml
from sqlalchemy import select
from streamlit.testing.v1 import AppTest


def test_home_is_a_simple_today_first_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
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

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import (
        ChangePoint,
        ChangePointSource,
        SourceConfig,
        SourceItem,
        Topic,
    )
    from ai_radar.scheduler import shutdown_scheduler

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        app = AppTest.from_file("app.py", default_timeout=10).run()

        assert not app.exception
        rendered = " ".join(
            str(element.value)
            for element in [*app.markdown, *app.caption, *app.info]
        )
        assert "今日重点" in rendered
        assert "按兴趣继续看" in rendered
        assert "今天没有需要优先处理的新变化" in rendered
        assert "新设计信号" not in rendered
        assert "优先跟进" not in rendered
        assert "领域温度" not in rendered
        assert "情报收件箱" not in rendered
        assert len(app.metric) == 0

        with session_scope() as session:
            topic = session.execute(
                select(Topic).where(Topic.name == "MCP / Tools / Skills")
            ).scalar_one()
            source = SourceConfig(
                name="official",
                source_type="RSS",
                url="https://example.test/feed",
                enabled=True,
            )
            session.add(source)
            session.flush()
            change_point = ChangePoint(
                topic_id=topic.id,
                event_key="home-focus",
                title="MCP authentication specification",
                summary="Remote MCP authentication has a new specification.",
                signal_type="STANDARD",
                importance=5,
                status="ACTIVE",
            )
            session.add(change_point)
            session.flush()
            source_item = SourceItem(
                source_config_id=source.id,
                external_id="spec",
                title="Official specification",
                url="https://example.com/spec",
                content_hash="spec-hash",
                analyze_status="SUCCESS",
            )
            session.add(source_item)
            session.flush()
            session.add(
                ChangePointSource(
                    change_point_id=change_point.id,
                    source_item_id=source_item.id,
                )
            )

        app.run()
        assert not app.exception
        assert any(
            "MCP authentication specification" in str(item.value)
            for item in app.markdown
        )
        snooze = next(
            button for button in app.button if button.label == "忽略 7 天"
        )
        snooze.click().run()
        assert not app.exception
        with session_scope() as session:
            stored = session.execute(
                select(ChangePoint).where(
                    ChangePoint.event_key == "home-focus"
                )
            ).scalar_one()
            assert stored.followup_snoozed_until is not None
    finally:
        shutdown_scheduler()
        reset_config()
        database.reset_engine()
