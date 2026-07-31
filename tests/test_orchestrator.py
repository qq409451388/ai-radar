from __future__ import annotations

from sqlalchemy import func, select


def test_analyze_all_pending_items_drains_queue_in_batches(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database, orchestrator
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import SourceConfig, SourceItem
    from ai_radar.services.analysis_service import AnalysisService

    reset_config()
    database.reset_engine()
    database.init_db()
    try:
        with session_scope() as session:
            source = SourceConfig(
                name="test",
                source_type="RSS",
                url="https://example.com/feed",
                enabled=True,
            )
            session.add(source)
            session.flush()
            for index in range(5):
                session.add(
                    SourceItem(
                        source_config_id=source.id,
                        external_id=str(index),
                        title=f"item {index}",
                        content_hash=f"hash-{index}",
                        analyze_status="PENDING",
                    )
                )

        monkeypatch.setattr(
            AnalysisService,
            "request_analysis",
            lambda _service, _item: type(
                "Analysis",
                (),
                {"relevant": False},
            )(),
        )
        progress: list[tuple[int, int, str]] = []

        result = orchestrator.analyze_all_pending_items(
            batch_size=2,
            progress_callback=lambda current, total, message: progress.append(
                (current, total, message)
            ),
        )

        assert result == {
            "processed": 5,
            "success": 0,
            "ignored": 5,
            "failed": 0,
            "new_change_points": 0,
            "batch_size": 2,
            "batches": 3,
            "remaining_pending": 0,
        }
        assert progress[-1] == (5, 5, "全部批次完成，剩余待处理 0 条")
        with session_scope() as session:
            pending = session.scalar(
                select(func.count(SourceItem.id)).where(
                    SourceItem.analyze_status == "PENDING"
                )
            )
        assert pending == 0
    finally:
        reset_config()
        database.reset_engine()
