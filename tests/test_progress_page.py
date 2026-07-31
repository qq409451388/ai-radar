from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_progress_moves_evidence_chart_and_uses_paginated_fact_list(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import ProfileFact, ProfileSourceFile, Topic

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        with session_scope() as session:
            topic = Topic(name="很长的领域名称 / MCP Tools Skills")
            source_file = ProfileSourceFile(
                repository="owner/memory",
                ref="main",
                file_path="notes/evidence.md",
            )
            session.add_all([topic, source_file])
            session.flush()
            facts = [
                ProfileFact(
                    source_file_id=source_file.id,
                    fact_key=f"fact-{index}",
                    fact_text=f"设计并验证了第 {index} 个方案",
                    topic_id=topic.id,
                    evidence_type="DESIGN",
                    source_line_start=index + 1,
                    source_line_end=index + 1,
                )
                for index in range(25)
            ]
            session.add_all(facts)
            session.flush()

        app = AppTest.from_file("pages/progress.py", default_timeout=10).run()

        assert not app.exception
        assert [tab.label for tab in app.tabs] == [
            "进展概览",
            "事实证据",
            "同步文件",
            "最近覆盖变化",
        ]
        assert any(
            "领域证据分布" in str(item.value)
            for item in app.markdown
        )
        headings = [
            item.value
            for item in app.markdown
            if "progress-list-heading" in item.value
        ]
        assert len(headings) == 20

        first_toggle = next(
            button
            for button in app.button
            if str(button.key).startswith("toggle_progress_fact_")
        )
        first_toggle.click().run()

        assert not app.exception
        assert len(
            [
                button
                for button in app.button
                if str(button.key).startswith("toggle_progress_fact_")
                and button.label == "收起"
            ]
        ) == 1
    finally:
        reset_config()
        database.reset_engine()
