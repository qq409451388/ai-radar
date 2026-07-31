from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_knowledge_list_is_paginated_and_opens_one_item(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import ChangePoint, Topic

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        with session_scope() as session:
            topic = Topic(name="Coding Agent")
            session.add(topic)
            session.flush()
            points = [
                ChangePoint(
                    topic_id=topic.id,
                    event_key=f"change-{index}",
                    title=f"知识变化 {index}",
                    summary=f"详情 {index}",
                    signal_type="CAPABILITY",
                    importance=5 if index == 0 else 3,
                    status="ACTIVE",
                )
                for index in range(25)
            ]
            session.add_all(points)
            session.flush()
            first_id = points[0].id

        app = AppTest.from_file("pages/knowledge.py", default_timeout=10).run()

        assert not app.exception
        headings = [
            item.value
            for item in app.markdown
            if "knowledge-list-heading" in item.value
        ]
        assert len(headings) == 20
        assert app.segmented_control(key="knowledge_signal_group").value == (
            "CAPABILITY"
        )

        app.button(key=f"toggle_knowledge_change_{first_id}").click().run()

        assert not app.exception
        assert any(
            "详情 0" in str(item.value)
            for item in app.markdown
        )
        assert len(
            [
                button
                for button in app.button
                if str(button.key).startswith("toggle_knowledge_change_")
                and button.label == "收起"
            ]
        ) == 1
    finally:
        reset_config()
        database.reset_engine()
