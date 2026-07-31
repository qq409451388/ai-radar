"""Today-first aggregation and ranking for the AI Radar home page."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import (
    SOURCE_KIND_COMMUNITY,
    SOURCE_TYPE_COMMUNITY,
    STATUS_ACTIVE,
    source_kind,
)
from ai_radar.config import get_config
from ai_radar.models import (
    ChangePoint,
    ChangePointSource,
    KnowledgeCoverage,
    PipelineRun,
    SourceConfig,
    SourceItem,
    Topic,
    TopicSnapshot,
)
from ai_radar.ui import coverage_relation_label
from ai_radar.utils import local_today

IMPORTANCE_SCORE = {1: 10, 3: 30, 5: 50}
SIGNAL_SCORE = {
    "STANDARD": 20,
    "ARCHITECTURE": 18,
    "CONCEPT": 16,
    "CAPABILITY": 8,
    "RELEASE": 0,
}
COVERAGE_SCORE = {
    None: 12,
    "NONE": 18,
    "AWARE": 8,
    "UNDERSTOOD": 2,
    "PRACTICED": 0,
}
HIGH_PRIORITY_THRESHOLD = 60
RECENT_DAYS = 7
HISTORICAL_GAP_DAYS = 30
MAX_FOCUS_ITEMS = 5
MAX_HISTORICAL_SUPPLEMENTS = 2


@dataclass(frozen=True)
class FocusItem:
    change_point_id: int
    title: str
    summary: str
    topic_id: int | None
    topic_name: str
    signal_type: str
    importance: int
    relation: str
    coverage_level: str | None
    first_seen_at: datetime
    source_count: int
    official_source_count: int
    primary_source_url: str
    primary_source_title: str
    primary_source_kind: str
    priority_score: int
    is_today: bool
    is_recent: bool
    is_historical_supplement: bool = False


@dataclass(frozen=True)
class InterestEntry:
    label: str
    count: int
    query_params: dict[str, str]


@dataclass(frozen=True)
class TopicDecline:
    topic_id: int
    topic_name: str
    delta: float
    declining_count: int


@dataclass(frozen=True)
class RadarHomeData:
    today_count: int
    recent_priority_count: int
    important_gap_count: int
    score_window_days: int
    focus_items: list[FocusItem]
    interests: list[InterestEntry]
    last_update_at: datetime | None
    last_pipeline_status: str
    last_pipeline_error: str
    topic_decline: TopicDecline | None


class RadarService:
    def __init__(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        today_start: datetime | None = None,
    ) -> None:
        self.session = session
        self.now = _as_utc(now or datetime.now(timezone.utc))
        self.cfg = get_config()
        self.today_start = _as_utc(
            today_start or local_today(self.cfg.timezone)
        )
        self.today_end = self.today_start + timedelta(days=1)
        self.recent_cutoff = self.now - timedelta(days=RECENT_DAYS)
        self.score_cutoff = self.now - timedelta(days=self.cfg.score_window_days)
        self.historical_cutoff = self.now - timedelta(days=HISTORICAL_GAP_DAYS)

    def load_home(self) -> RadarHomeData:
        topics = list(
            self.session.execute(
                select(Topic).where(Topic.enabled == True).order_by(Topic.id)  # noqa: E712
            ).scalars()
        )
        topic_names = {topic.id: topic.name for topic in topics}
        change_points = list(
            self.session.execute(
                select(ChangePoint).where(
                    ChangePoint.status == STATUS_ACTIVE,
                    or_(
                        ChangePoint.first_seen_at >= self.score_cutoff,
                        ChangePoint.occurred_at >= self.score_cutoff,
                    ),
                )
            ).scalars()
        )
        coverage_by_cp = self._latest_coverages(change_points)
        sources_by_cp = self._sources(change_points)

        today_count = sum(
            1
            for cp in change_points
            if self.today_start
            <= _as_utc(cp.first_seen_at)
            < self.today_end
        )
        gaps = [
            cp
            for cp in change_points
            if _as_utc(cp.occurred_at or cp.first_seen_at) >= self.score_cutoff
            and _is_gap(cp, coverage_by_cp.get(cp.id))
        ]
        recent = [
            cp
            for cp in change_points
            if _as_utc(cp.first_seen_at) >= self.recent_cutoff
            and not _is_snoozed(cp, self.now)
        ]
        recent_items = [
            self._focus_item(
                cp,
                topic_names,
                coverage_by_cp.get(cp.id),
                sources_by_cp.get(cp.id, []),
            )
            for cp in recent
        ]
        recent_items.sort(key=_focus_sort_key, reverse=True)
        focus_items = recent_items[:MAX_FOCUS_ITEMS]

        if len(focus_items) < 3:
            supplement_limit = min(
                MAX_HISTORICAL_SUPPLEMENTS,
                MAX_FOCUS_ITEMS - len(focus_items),
            )
            historical_ids = {item.change_point_id for item in focus_items}
            historical = [
                cp
                for cp in gaps
                if cp.id not in historical_ids
                and self.historical_cutoff <= _as_utc(cp.first_seen_at)
                < self.recent_cutoff
                and not _is_snoozed(cp, self.now)
            ]
            historical_items = [
                self._focus_item(
                    cp,
                    topic_names,
                    coverage_by_cp.get(cp.id),
                    sources_by_cp.get(cp.id, []),
                    historical=True,
                )
                for cp in historical
            ]
            historical_items.sort(key=_focus_sort_key, reverse=True)
            focus_items.extend(historical_items[:supplement_limit])

        recent_priority_count = sum(
            1
            for item in recent_items
            if item.priority_score >= HIGH_PRIORITY_THRESHOLD
        )
        interests = self._interest_entries(
            change_points,
            topics,
            gaps,
        )
        last_run = self.session.execute(
            select(PipelineRun)
            .where(PipelineRun.pipeline_type == "FULL_UPDATE")
            .order_by(PipelineRun.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        return RadarHomeData(
            today_count=today_count,
            recent_priority_count=recent_priority_count,
            important_gap_count=len(gaps),
            score_window_days=self.cfg.score_window_days,
            focus_items=focus_items,
            interests=interests,
            last_update_at=last_run.finished_at if last_run else None,
            last_pipeline_status=last_run.status if last_run else "",
            last_pipeline_error=last_run.error if last_run else "",
            topic_decline=self._topic_decline(topic_names),
        )

    def _focus_item(
        self,
        cp: ChangePoint,
        topic_names: dict[int, str],
        coverage: KnowledgeCoverage | None,
        sources: list[SourceItem],
        *,
        historical: bool = False,
    ) -> FocusItem:
        level = coverage.coverage_level if coverage else None
        source_configs = {
            item.source_config_id: self.session.get(
                SourceConfig,
                item.source_config_id,
            )
            for item in sources
        }
        source_count = len(source_configs)
        official_source_count = sum(
            1
            for config in source_configs.values()
            if config is not None
            and config.source_type != SOURCE_TYPE_COMMUNITY
        )
        primary = next(
            (
                item
                for item in sources
                if item.url
                and (
                    config := source_configs.get(item.source_config_id)
                ) is not None
                and config.source_type != SOURCE_TYPE_COMMUNITY
            ),
            None,
        ) or next((item for item in sources if item.url), None)
        primary_config = (
            source_configs.get(primary.source_config_id)
            if primary
            else None
        )
        primary_kind = source_kind(
            primary_config.source_type if primary_config else ""
        )
        return FocusItem(
            change_point_id=cp.id,
            title=cp.title,
            summary=cp.summary,
            topic_id=cp.topic_id,
            topic_name=topic_names.get(cp.topic_id, "未分类"),
            signal_type=cp.signal_type,
            importance=cp.importance,
            relation=coverage_relation_label(coverage),
            coverage_level=level,
            first_seen_at=cp.first_seen_at,
            source_count=source_count,
            official_source_count=official_source_count,
            primary_source_url=primary.url if primary else "",
            primary_source_title=(
                primary.display_title
                or primary.title
                or (
                    "打开社区讨论"
                    if primary_kind == SOURCE_KIND_COMMUNITY
                    else "打开官方来源"
                )
            )
            if primary
            else "",
            primary_source_kind=primary_kind,
            priority_score=_priority_score(
                cp,
                level,
                official_source_count,
                self.now,
            ),
            is_today=self.today_start
            <= _as_utc(cp.first_seen_at)
            < self.today_end,
            is_recent=_as_utc(cp.first_seen_at) >= self.recent_cutoff,
            is_historical_supplement=historical,
        )

    def _latest_coverages(
        self,
        change_points: list[ChangePoint],
    ) -> dict[int, KnowledgeCoverage]:
        ids = [cp.id for cp in change_points]
        if not ids:
            return {}
        rows = list(
            self.session.execute(
                select(KnowledgeCoverage)
                .where(KnowledgeCoverage.change_point_id.in_(ids))
                .order_by(
                    KnowledgeCoverage.change_point_id,
                    KnowledgeCoverage.assessed_at.desc(),
                    KnowledgeCoverage.id.desc(),
                )
            ).scalars()
        )
        latest: dict[int, KnowledgeCoverage] = {}
        for row in rows:
            latest.setdefault(row.change_point_id, row)
        return latest

    def _sources(
        self,
        change_points: list[ChangePoint],
    ) -> dict[int, list[SourceItem]]:
        ids = [cp.id for cp in change_points]
        if not ids:
            return {}
        rows = self.session.execute(
            select(ChangePointSource.change_point_id, SourceItem)
            .join(SourceItem, SourceItem.id == ChangePointSource.source_item_id)
            .where(ChangePointSource.change_point_id.in_(ids))
            .order_by(
                ChangePointSource.change_point_id,
                SourceItem.published_at.desc().nullslast(),
                SourceItem.id,
            )
        ).all()
        result: dict[int, list[SourceItem]] = {}
        for change_point_id, source in rows:
            result.setdefault(change_point_id, []).append(source)
        return result

    def _interest_entries(
        self,
        change_points: list[ChangePoint],
        topics: list[Topic],
        gaps: list[ChangePoint],
    ) -> list[InterestEntry]:
        recent = [
            cp
            for cp in change_points
            if _as_utc(cp.first_seen_at) >= self.recent_cutoff
        ]
        entries = [
            InterestEntry(
                label="新概念与架构",
                count=sum(
                    1
                    for cp in recent
                    if cp.signal_type in ("CONCEPT", "ARCHITECTURE")
                ),
                query_params={
                    "signals": "CONCEPT,ARCHITECTURE",
                    "period": "7d",
                },
            )
        ]
        topic_counts = {
            topic.id: sum(1 for cp in recent if cp.topic_id == topic.id)
            for topic in topics
        }
        top_topics = sorted(
            (topic for topic in topics if topic_counts[topic.id]),
            key=lambda topic: (topic_counts[topic.id], -topic.id),
            reverse=True,
        )[:3]
        entries.extend(
            InterestEntry(
                label=topic.name,
                count=topic_counts[topic.id],
                query_params={"topic": str(topic.id), "period": "7d"},
            )
            for topic in top_topics
        )
        entries.append(
            InterestEntry(
                label="我的重要知识缺口",
                count=len(gaps),
                query_params={
                    "coverage": "GAP",
                    "importance_min": "3",
                },
            )
        )
        return entries

    def _topic_decline(
        self,
        topic_names: dict[int, str],
    ) -> TopicDecline | None:
        rows = list(
            self.session.execute(
                select(TopicSnapshot).order_by(
                    TopicSnapshot.topic_id,
                    TopicSnapshot.snapshot_date.desc(),
                    TopicSnapshot.id.desc(),
                )
            ).scalars()
        )
        latest: dict[int, TopicSnapshot] = {}
        for row in rows:
            latest.setdefault(row.topic_id, row)
        declining = [row for row in latest.values() if row.score_delta < 0]
        if not declining:
            return None
        worst = min(declining, key=lambda row: row.score_delta)
        return TopicDecline(
            topic_id=worst.topic_id,
            topic_name=topic_names.get(worst.topic_id, "未分类"),
            delta=worst.score_delta,
            declining_count=len(declining),
        )


def _priority_score(
    cp: ChangePoint,
    coverage_level: str | None,
    official_source_count: int,
    now: datetime,
) -> int:
    age = now - _as_utc(cp.first_seen_at)
    if age <= timedelta(days=1):
        freshness = 10
    elif age <= timedelta(days=3):
        freshness = 6
    elif age <= timedelta(days=7):
        freshness = 3
    else:
        freshness = 0
    confirmation = (
        8
        if official_source_count >= 3
        else 5
        if official_source_count >= 2
        else 0
    )
    return (
        IMPORTANCE_SCORE.get(cp.importance, 0)
        + SIGNAL_SCORE.get(cp.signal_type, 0)
        + COVERAGE_SCORE.get(coverage_level, 0)
        + freshness
        + confirmation
    )


def _focus_sort_key(item: FocusItem) -> tuple[int, int, int, datetime]:
    return (
        item.priority_score,
        item.importance,
        item.source_count,
        _as_utc(item.first_seen_at),
    )


def _is_gap(
    cp: ChangePoint,
    coverage: KnowledgeCoverage | None,
) -> bool:
    level = coverage.coverage_level if coverage else None
    return cp.importance >= 3 and level in (None, "NONE", "AWARE")


def _is_snoozed(cp: ChangePoint, now: datetime) -> bool:
    return bool(
        cp.followup_snoozed_until
        and _as_utc(cp.followup_snoozed_until) > now
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
