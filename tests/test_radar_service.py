from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_home_prioritizes_recent_changes_and_limits_historical_gaps(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AI_RADAR_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AI_RADAR_DB_PATH", str(tmp_path / "radar.db"))
    monkeypatch.setenv("AI_RADAR_SCHEDULER_ENABLED", "false")

    from ai_radar import database
    from ai_radar.config import reset_config
    from ai_radar.database import session_scope
    from ai_radar.models import (
        ChangePoint,
        ChangePointSource,
        KnowledgeCoverage,
        SourceConfig,
        SourceItem,
        Topic,
    )
    from ai_radar.services.radar_service import RadarService

    reset_config()
    database.reset_engine()
    database.init_db()
    now = datetime(2026, 7, 31, 4, tzinfo=timezone.utc)
    today_start = datetime(2026, 7, 30, 16, tzinfo=timezone.utc)
    try:
        with session_scope() as session:
            topic = Topic(name="MCP / Tools / Skills")
            source = SourceConfig(
                name="official",
                source_type="RSS",
                url="https://example.com/feed",
                enabled=True,
            )
            session.add_all([topic, source])
            session.flush()

            today = _change_point(
                topic.id,
                "today",
                "STANDARD",
                3,
                datetime(2026, 7, 30, 18, tzinfo=timezone.utc),
            )
            recent = _change_point(
                topic.id,
                "recent",
                "RELEASE",
                5,
                now - timedelta(days=2),
            )
            snoozed = _change_point(
                topic.id,
                "snoozed",
                "ARCHITECTURE",
                5,
                datetime(2026, 7, 30, 20, tzinfo=timezone.utc),
            )
            snoozed.followup_snoozed_until = now + timedelta(days=7)
            historical_one = _change_point(
                topic.id,
                "historical-one",
                "CONCEPT",
                5,
                now - timedelta(days=16),
            )
            historical_two = _change_point(
                topic.id,
                "historical-two",
                "CAPABILITY",
                3,
                now - timedelta(days=21),
            )
            old_gap = _change_point(
                topic.id,
                "old-gap",
                "STANDARD",
                5,
                now - timedelta(days=60),
            )
            session.add_all(
                [
                    today,
                    recent,
                    snoozed,
                    historical_one,
                    historical_two,
                    old_gap,
                ]
            )
            session.flush()
            session.add(
                KnowledgeCoverage(
                    change_point_id=recent.id,
                    coverage_level="NONE",
                )
            )
            first_source = SourceItem(
                source_config_id=source.id,
                external_id="primary",
                title="Primary specification",
                url="https://example.com/spec",
                content_hash="source-1",
                analyze_status="SUCCESS",
                published_at=now - timedelta(days=1),
            )
            newer_without_url = SourceItem(
                source_config_id=source.id,
                external_id="secondary",
                title="Secondary",
                url="",
                content_hash="source-2",
                analyze_status="SUCCESS",
                published_at=now,
            )
            session.add_all([first_source, newer_without_url])
            session.flush()
            session.add_all(
                [
                    ChangePointSource(
                        change_point_id=today.id,
                        source_item_id=first_source.id,
                    ),
                    ChangePointSource(
                        change_point_id=today.id,
                        source_item_id=newer_without_url.id,
                    ),
                ]
            )

        with session_scope() as session:
            data = RadarService(
                session,
                now=now,
                today_start=today_start,
            ).load_home()

        assert data.today_count == 2
        assert data.recent_priority_count == 2
        assert data.important_gap_count == 6
        focus_ids = [item.title for item in data.focus_items]
        assert set(focus_ids[:2]) == {"today", "recent"}
        assert set(focus_ids[2:]) == {"historical-one", "historical-two"}
        assert "snoozed" not in focus_ids
        assert "old-gap" not in focus_ids
        assert sum(
            item.is_historical_supplement for item in data.focus_items
        ) == 2
        today_item = next(
            item for item in data.focus_items if item.title == "today"
        )
        assert today_item.primary_source_url == "https://example.com/spec"
        assert today_item.source_count == 1
        assert today_item.official_source_count == 1
        assert today_item.primary_source_kind == "OFFICIAL"
        recent_item = next(item for item in data.focus_items if item.title == "recent")
        assert recent_item.relation == "尚未覆盖"
        assert recent_item.primary_source_url == ""
    finally:
        reset_config()
        database.reset_engine()


def _change_point(
    topic_id: int,
    title: str,
    signal_type: str,
    importance: int,
    first_seen_at: datetime,
):
    from ai_radar.models import ChangePoint

    return ChangePoint(
        topic_id=topic_id,
        event_key=f"event-{title}",
        title=title,
        summary=f"{title} summary",
        signal_type=signal_type,
        importance=importance,
        first_seen_at=first_seen_at,
        occurred_at=first_seen_at,
        status="ACTIVE",
    )
