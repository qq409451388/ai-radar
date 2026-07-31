"""Tests for editing and deleting configured information sources."""
from __future__ import annotations

from sqlalchemy import func, select

from ai_radar.models import (
    ChangePoint,
    ChangePointSource,
    SourceConfig,
    SourceItem,
    Topic,
)
from ai_radar.services.source_service import SourceService, source_display_state


def _source(session) -> SourceConfig:
    source = SourceConfig(
        name="Original",
        source_type="RSS",
        url="https://example.com/feed",
        repository="",
        path_filter="",
        enabled=True,
        test_status="PASSED",
    )
    session.add(source)
    session.flush()
    return source


def test_source_list_states_use_visible_colored_icons(session):
    source = _source(session)
    assert source_display_state(source) == (
        "采集中",
        "✅",
        "collecting",
    )

    source.enabled = False
    assert source_display_state(source) == (
        "已停用",
        "⛔",
        "stopped",
    )

    source.test_status = "UNTESTED"
    assert source_display_state(source) == (
        "待测试",
        "⚪",
        "untested",
    )

    source.test_status = "FAILED"
    assert source_display_state(source) == (
        "连接异常",
        "❌",
        "failed",
    )


def test_editing_connection_fields_requires_a_new_test(session):
    source = _source(session)

    result = SourceService(session).update(
        source.id,
        name="Renamed",
        source_type="RSS",
        url="https://example.com/new-feed",
        repository="",
        path_filter="release",
        default_topic_id=None,
    )

    assert result["connection_changed"] is True
    assert source.name == "Renamed"
    assert source.enabled is False
    assert source.test_status == "UNTESTED"
    assert source.last_tested_at is None


def test_editing_name_or_topic_keeps_a_valid_source_enabled(session):
    source = _source(session)
    topic = Topic(name="Coding Agent")
    session.add(topic)
    session.flush()

    result = SourceService(session).update(
        source.id,
        name="Renamed",
        source_type=source.source_type,
        url=source.url,
        repository=source.repository,
        path_filter=source.path_filter,
        default_topic_id=topic.id,
    )

    assert result["connection_changed"] is False
    assert source.enabled is True
    assert source.test_status == "PASSED"
    assert source.default_topic_id == topic.id


def test_deleting_source_cleans_items_but_keeps_knowledge(session):
    source = _source(session)
    item = SourceItem(
        source_config_id=source.id,
        external_id="item-1",
        title="Release",
        url="https://example.com/release",
        author="",
        raw_content="content",
        content_hash="hash",
        analyze_status="SUCCESS",
    )
    point = ChangePoint(
        event_key="release.example",
        title="Release",
        summary="",
        why_it_matters="",
        importance=3,
    )
    session.add_all([item, point])
    session.flush()
    session.add(
        ChangePointSource(
            change_point_id=point.id,
            source_item_id=item.id,
        )
    )
    session.flush()

    result = SourceService(session).delete(source.id)

    assert result["deleted_items"] == 1
    assert session.scalar(select(func.count(SourceConfig.id))) == 0
    assert session.scalar(select(func.count(SourceItem.id))) == 0
    assert session.scalar(select(func.count(ChangePointSource.id))) == 0
    assert session.scalar(select(func.count(ChangePoint.id))) == 1
