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
            selected_source = SourceConfig(
                name="OpenAI 官方更新",
                source_type="RSS",
                url="https://example.com/openai.xml",
            )
            other_source = SourceConfig(
                name="其他资讯源",
                source_type="RSS",
                url="https://example.com/other.xml",
            )
            session.add_all([selected_source, other_source])
            session.flush()
            selected_item = SourceItem(
                source_config_id=selected_source.id,
                external_id="selected-item",
                title="Selected source item",
                url="https://example.com/selected",
                content_hash="selected-source-hash",
                analyze_status="SUCCESS",
            )
            other_item = SourceItem(
                source_config_id=other_source.id,
                external_id="other-item",
                title="Other source item",
                url="https://example.com/other",
                content_hash="other-source-hash",
                analyze_status="SUCCESS",
            )
            other_change_point = ChangePoint(
                topic_id=topic.id,
                event_key="other-source-change",
                title="不应出现在来源筛选结果中",
                summary="This belongs to another source.",
                signal_type="STANDARD",
                importance=5,
                status="ACTIVE",
            )
            session.add_all([selected_item, other_item, other_change_point])
            session.flush()
            session.add_all(
                [
                    ChangePointSource(
                        change_point_id=change_point.id,
                        source_item_id=selected_item.id,
                    ),
                    ChangePointSource(
                        change_point_id=other_change_point.id,
                        source_item_id=other_item.id,
                    ),
                ]
            )
            selected_source_id = selected_source.id

        app = AppTest.from_file("app.py", default_timeout=10).run()
        app.query_params = {"change_point": str(change_point_id)}
        app.switch_page("pages/knowledge.py").run()

        assert not app.exception
        headings = [
            item.value
            for item in app.markdown
            if "knowledge-list-heading" in item.value
        ]
        assert len(headings) == 1
        assert "MCP authentication" in headings[0]
        assert any(
            "Authentication specification changed." in str(item.value)
            for item in app.markdown
        )
        assert any(
            "正在查看首页选中的知识点" in str(item.value)
            for item in app.info
        )

        app.query_params = {
            "signals": "STANDARD,ARCHITECTURE",
            "period": "7d",
            "source": str(selected_source_id),
        }
        app.switch_page("pages/knowledge.py").run()
        assert not app.exception
        assert app.selectbox(key="knowledge_source").value == selected_source_id
        assert app.multiselect(key="knowledge_signals").value == [
            "STANDARD",
            "ARCHITECTURE",
        ]
        assert app.selectbox(key="knowledge_period").value == "7d"
        filtered_headings = [
            item.value
            for item in app.markdown
            if "knowledge-list-heading" in item.value
        ]
        assert len(filtered_headings) == 1
        assert "MCP authentication" in filtered_headings[0]
        assert "不应出现在来源筛选结果中" not in filtered_headings[0]
    finally:
        shutdown_scheduler()
        reset_config()
        database.reset_engine()


def test_inbox_deep_link_applies_period_topic_source_and_signal_filters(
    tmp_path,
    monkeypatch,
):
    _configure_ready_app(tmp_path, monkeypatch)

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
        with session_scope() as session:
            topic = Topic(name="Java AI 生态")
            session.add(topic)
            session.flush()
            topic_id = topic.id
            selected_source = SourceConfig(
                name="Spring AI 官方更新",
                source_type="RSS",
                url="https://example.com/spring-ai.xml",
            )
            other_source = SourceConfig(
                name="其他 Java 来源",
                source_type="RSS",
                url="https://example.com/java.xml",
            )
            session.add_all([selected_source, other_source])
            session.flush()
            selected_item = SourceItem(
                source_config_id=selected_source.id,
                external_id="spring-selected",
                title="Spring selected source item",
                url="https://example.com/spring-selected",
                content_hash="spring-selected-hash",
                analyze_status="SUCCESS",
            )
            other_item = SourceItem(
                source_config_id=other_source.id,
                external_id="spring-other",
                title="Spring other source item",
                url="https://example.com/spring-other",
                content_hash="spring-other-hash",
                analyze_status="SUCCESS",
            )
            selected_change = ChangePoint(
                topic_id=topic.id,
                event_key="spring-selected-change",
                title="Spring AI 目标变化",
                summary="Selected source.",
                signal_type="STANDARD",
                importance=5,
                status="ACTIVE",
            )
            other_change = ChangePoint(
                topic_id=topic.id,
                event_key="spring-other-change",
                title="Spring AI 其他变化",
                summary="Other source.",
                signal_type="STANDARD",
                importance=5,
                status="ACTIVE",
            )
            session.add_all(
                [selected_item, other_item, selected_change, other_change]
            )
            session.flush()
            session.add_all(
                [
                    ChangePointSource(
                        change_point_id=selected_change.id,
                        source_item_id=selected_item.id,
                    ),
                    ChangePointSource(
                        change_point_id=other_change.id,
                        source_item_id=other_item.id,
                    ),
                ]
            )
            selected_source_id = selected_source.id

        app = AppTest.from_file("app.py", default_timeout=10).run()
        app.query_params = {
            "view": "changes",
            "period": "7d",
            "topic": str(topic_id),
            "source": str(selected_source_id),
            "signals": "STANDARD",
        }
        app.switch_page("pages/inbox.py").run()

        assert not app.exception
        assert app.segmented_control(key="inbox_change_range_all").value == "7 天"
        assert app.selectbox(key="inbox_change_topic_all").value == topic_id
        assert (
            app.selectbox(key="inbox_change_source_all").value
            == selected_source_id
        )
        assert app.multiselect(key="inbox_change_signals_all").value == [
            "STANDARD"
        ]
        headings = [
            item.value
            for item in app.markdown
            if "inbox-list-heading" in item.value
        ]
        assert len(headings) == 1
        assert "Spring AI 目标变化" in headings[0]
        assert "Spring AI 其他变化" not in headings[0]
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
