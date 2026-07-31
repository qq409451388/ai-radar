"""Tests for collectors, dedup, profile sync (section 二十: 4,5,6,7,11)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from ai_radar.bootstrap import (
    SOURCE_TYPE_GITHUB_COMMIT,
    SOURCE_TYPE_GITHUB_RELEASE,
    SOURCE_TYPE_RSS,
    SOURCE_TYPE_WEB_PAGE,
)
from ai_radar.collectors.base import CollectedItem
from ai_radar.collectors.github_commit import GitHubCommitCollector
from ai_radar.collectors.github_release import GitHubReleaseCollector
from ai_radar.collectors.rss import RSSCollector
from ai_radar.collectors.web_page import WebPageCollector
from ai_radar.models import (
    ChangePoint,
    ChangePointSource,
    ProfileFact,
    ProfileSourceFile,
    SourceConfig,
    SourceItem,
)
from ai_radar.llm.schemas import ChangePointAnalysis
from ai_radar.services.analysis_service import AnalysisService
from ai_radar.services.collection_service import CollectionService
from ai_radar.services.dedup_service import DedupService


def _make_source(session, source_type=SOURCE_TYPE_RSS, url="https://x/feed") -> SourceConfig:
    sc = SourceConfig(
        name="t",
        source_type=source_type,
        url=url,
        repository="",
        enabled=True,
    )
    session.add(sc)
    session.flush()
    return sc


def _item(external_id="1", title="t", content="c"):
    return CollectedItem(
        external_id=external_id,
        title=title,
        url=f"https://x/{external_id}",
        author="a",
        published_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        content=content,
    )


# --- Test 4: RSS dedup ---

def test_rss_collector_dedup_via_service(session):
    sc = _make_source(session)
    svc = CollectionService(session)

    with patch.object(RSSCollector, "collect", return_value=[_item("1", "A", "c1")]):
        result = svc._collect_one(sc)
    assert result[0] == 1  # new

    # Same item again → not re-inserted.
    with patch.object(RSSCollector, "collect", return_value=[_item("1", "A", "c1")]):
        result = svc._collect_one(sc)
    assert result[0] == 0  # no new

    items = list(session.execute(select(SourceItem)).scalars())
    assert len(items) == 1


def test_rss_collector_external_id_is_dedup_key(session):
    sc = _make_source(session)
    svc = CollectionService(session)
    # Same external_id, different title → still deduped (not re-analyzed).
    with patch.object(RSSCollector, "collect", return_value=[_item("1", "first")]):
        svc._collect_one(sc)
    with patch.object(RSSCollector, "collect", return_value=[_item("1", "second")]):
        svc._collect_one(sc)
    items = list(session.execute(select(SourceItem)).scalars())
    assert len(items) == 1
    # Title is NOT overwritten on identical content_hash; but content differs
    # here so it updates. Verify analyze_status stays PENDING (not re-analyzed).
    assert items[0].analyze_status == "PENDING"


def test_source_must_pass_connection_test_before_enable(session):
    source = SourceConfig(
        name="new source",
        source_type=SOURCE_TYPE_RSS,
        url="https://x/new-feed",
        enabled=False,
        test_status="UNTESTED",
    )
    session.add(source)
    session.flush()

    with patch.object(RSSCollector, "collect", return_value=[_item("preview")]):
        result = CollectionService(session).test_source(source.id)

    assert result["status"] == "PASSED"
    assert result["items_seen"] == 1
    assert source.test_status == "PASSED"
    assert source.last_tested_at is not None
    assert source.enabled is False
    assert session.scalar(select(SourceItem.id)) is None


def test_failed_source_test_disables_source(session):
    source = SourceConfig(
        name="broken source",
        source_type=SOURCE_TYPE_RSS,
        url="https://x/broken-feed",
        enabled=True,
        test_status="PASSED",
    )
    session.add(source)
    session.flush()

    with patch.object(RSSCollector, "collect", side_effect=RuntimeError("offline")):
        result = CollectionService(session).test_source(source.id)

    assert result["status"] == "FAILED"
    assert source.test_status == "FAILED"
    assert source.enabled is False
    assert "offline" in source.last_error


# --- Test 5: GitHub Release dedup ---

def test_github_release_dedup(session):
    sc = SourceConfig(
        name="gh",
        source_type=SOURCE_TYPE_GITHUB_RELEASE,
        url="https://github.com/o/r",
        repository="o/r",
        enabled=True,
    )
    session.add(sc)
    session.flush()
    svc = CollectionService(session)

    fake_release = CollectedItem(
        external_id="123",
        title="v1.0.0",
        url="https://github.com/o/r/releases/tag/v1.0.0",
        author="o",
        published_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        content="release notes",
    )
    with patch.object(GitHubReleaseCollector, "collect", return_value=[fake_release]):
        new1, _ = svc._collect_one(sc)
    with patch.object(GitHubReleaseCollector, "collect", return_value=[fake_release]):
        new2, _ = svc._collect_one(sc)
    assert new1 == 1 and new2 == 0
    items = list(session.execute(select(SourceItem)).scalars())
    assert len(items) == 1


@pytest.mark.parametrize(
    ("source_type", "collector_cls", "path_filter"),
    [
        (SOURCE_TYPE_WEB_PAGE, WebPageCollector, "/engineering/"),
        (SOURCE_TYPE_GITHUB_COMMIT, GitHubCommitCollector, "spec"),
    ],
)
def test_design_source_types_are_routed(
    session,
    source_type,
    collector_cls,
    path_filter,
):
    source = SourceConfig(
        name="design",
        source_type=source_type,
        url="https://github.com/o/r",
        repository="o/r",
        path_filter=path_filter,
        enabled=True,
    )
    session.add(source)
    session.flush()

    with patch.object(collector_cls, "collect", return_value=[_item("design-1")]):
        new, seen = CollectionService(session)._collect_one(source)

    assert (new, seen) == (1, 1)


# --- Test 6: event_key merge ---

def test_event_key_merge(session):
    topic = __import__("ai_radar.models", fromlist=["Topic"]).Topic(name="领域")
    session.add(topic)
    session.flush()
    sc = _make_source(session)
    item1 = SourceItem(
        source_config_id=sc.id,
        external_id="i1",
        title="A",
        url="",
        author="",
        raw_content="",
        content_hash="h1",
        analyze_status="PENDING",
    )
    session.add(item1)
    session.flush()
    item2 = SourceItem(
        source_config_id=sc.id,
        external_id="i2",
        title="B",
        url="",
        author="",
        raw_content="",
        content_hash="h2",
        analyze_status="PENDING",
    )
    session.add(item2)
    session.flush()

    dedup = DedupService(session)
    cp1 = dedup.find_or_create(
        event_key="mcp.protocol.auth",
        title="MCP auth",
        summary="s1",
        why_it_matters="w",
        importance=3,
        topic_id=topic.id,
        occurred_at=None,
        source_item_id=item1.id,
        duplicate_keywords=["mcp"],
    )
    cp2 = dedup.find_or_create(
        event_key="mcp.protocol.auth",
        title="MCP auth update",
        summary="s2",
        why_it_matters="",
        importance=5,
        signal_type="STANDARD",
        topic_id=topic.id,
        occurred_at=None,
        source_item_id=item2.id,
        duplicate_keywords=["mcp"],
    )
    assert cp1.id == cp2.id  # merged into the same change point
    assert cp2.importance == 5  # importance promoted
    assert cp2.signal_type == "STANDARD"
    links = list(
        session.execute(
            select(ChangePointSource).where(ChangePointSource.change_point_id == cp2.id)
        ).scalars()
    )
    assert {l.source_item_id for l in links} == {item1.id, item2.id}


def test_dedup_handles_sqlite_naive_and_aware_datetimes(session):
    """SQLite reloads timestamps without tzinfo; dedup must normalize them."""
    topic = __import__("ai_radar.models", fromlist=["Topic"]).Topic(name="时区测试")
    session.add(topic)
    source = _make_source(session, url="https://x/time-feed")
    existing_item = SourceItem(
        source_config_id=source.id,
        external_id="time-1",
        title="Timezone event",
        raw_content="",
        content_hash="time-h1",
        analyze_status="SUCCESS",
    )
    session.add(existing_item)
    session.flush()
    existing = ChangePoint(
        topic_id=topic.id,
        event_key="time.old",
        title="Timezone event",
        summary="same event",
        importance=3,
        occurred_at=datetime(2026, 7, 1),  # naive, as SQLite returns it
        status="ACTIVE",
    )
    session.add(existing)
    session.flush()

    incoming_item = SourceItem(
        source_config_id=source.id,
        external_id="time-2",
        title="Timezone event",
        raw_content="",
        content_hash="time-h2",
        analyze_status="PENDING",
    )
    session.add(incoming_item)
    session.flush()

    merged = DedupService(session).find_or_create(
        event_key="time.new",
        title="Timezone event",
        summary="same event, another source",
        why_it_matters="",
        importance=3,
        topic_id=topic.id,
        occurred_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
        source_item_id=incoming_item.id,
        duplicate_keywords=[],
    )
    assert merged.id == existing.id


def test_analysis_fills_missing_relevant_fields(session):
    topic = __import__("ai_radar.models", fromlist=["Topic"]).Topic(name="回退领域")
    session.add(topic)
    source = _make_source(session, url="https://x/fallback-feed")
    source.default_topic_id = topic.id
    item = SourceItem(
        source_config_id=source.id,
        external_id="fallback-1",
        title="Original source title",
        url="https://x/fallback-1",
        raw_content="Original source summary",
        content_hash="fallback-h1",
        analyze_status="PENDING",
    )
    session.add(item)
    session.flush()

    class SparseLlm:
        def extract_change_points(self, payload):
            return ChangePointAnalysis(relevant=True, importance=0)

    result = AnalysisService(session, SparseLlm())._analyze_one(item)  # type: ignore[arg-type]
    cp = session.get(ChangePoint, result["change_point_id"])
    assert cp is not None
    assert cp.title == "Original source title"
    assert cp.summary == "Original source summary"
    assert cp.event_key.startswith("source-item.")
    assert cp.importance == 1
    assert cp.signal_type == "RELEASE"
    assert cp.topic_id == topic.id
