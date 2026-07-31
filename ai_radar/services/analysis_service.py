"""Analysis service: runs the LLM over PENDING source items to create change points."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import (
    ANALYZE_FAILED,
    ANALYZE_IGNORED,
    ANALYZE_PENDING,
    ANALYZE_SUCCESS,
    VALID_IMPORTANCE,
)
from ai_radar.config import get_config
from ai_radar.llm.client import LlmClient, LlmError
from ai_radar.models import SourceConfig, SourceItem, Topic
from ai_radar.repositories.job_log import job_log
from ai_radar.services.dedup_service import DedupService
from ai_radar.utils import compact_text, sha256_hex, to_utc

log = logging.getLogger(__name__)

_IMPORTANCE_TO_INT = {1, 3, 5}


class AnalysisService:
    def __init__(self, session: Session, llm: LlmClient | None = None) -> None:
        self.session = session
        self.llm = llm or LlmClient(session)
        self.dedup = DedupService(session)

    def analyze_pending(
        self,
        limit: int | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        batch_size = limit or get_config().analyze_batch_size
        stmt = (
            select(SourceItem)
            .where(
                or_(
                    SourceItem.analyze_status == ANALYZE_PENDING,
                    and_(
                        SourceItem.analyze_status == ANALYZE_FAILED,
                        SourceItem.retry_count < 3,
                        or_(
                            SourceItem.next_retry_at.is_(None),
                            SourceItem.next_retry_at <= now,
                        ),
                    ),
                )
            )
            .order_by(
                SourceItem.published_at.desc().nullslast(),
                SourceItem.collected_at.desc(),
            )
            .limit(batch_size)
        )
        items = list(self.session.execute(stmt).scalars())
        if progress_callback:
            progress_callback(0, len(items), "已读取待分析队列")

        success = 0
        ignored = 0
        failed = 0
        new_cp = 0
        with job_log(self.session, "analyze_items") as jl:
            for index, item in enumerate(items, start=1):
                if progress_callback:
                    progress_callback(
                        index - 1,
                        len(items),
                        f"正在分析第 {index}/{len(items)} 条：{item.title[:48]}",
                    )
                jl.processed_count += 1
                try:
                    analysis = self.request_analysis(item)
                    outcome = self.complete_analysis(item, analysis)
                    ignored += outcome["ignored"]
                    success += outcome["success"]
                    new_cp += outcome["new_change_points"]
                except LlmError as exc:
                    self.fail_analysis(item, exc, now=now)
                    failed += 1
                    log.warning("analyze item %s failed: %s", item.id, exc)
                except Exception as exc:
                    self.fail_analysis(item, exc, now=now)
                    failed += 1
                    log.exception("analyze item %s errored", item.id)
                if progress_callback:
                    progress_callback(
                        index,
                        len(items),
                        f"已分析 {index}/{len(items)} 条",
                    )
            jl.success_count = success
            jl.failed_count = failed
            jl.message = f"analyzed {len(items)} items: {success} ok, {ignored} ignored, {failed} failed, {new_cp} new cp"
        return {
            "processed": len(items),
            "success": success,
            "ignored": ignored,
            "failed": failed,
            "new_change_points": new_cp,
            "batch_size": batch_size,
        }

    def requeue(self, source_item_id: int) -> dict:
        item = self.session.get(SourceItem, source_item_id)
        if item is None:
            raise ValueError(f"source_item {source_item_id} not found")
        item.analyze_status = ANALYZE_PENDING
        item.analyze_error = ""
        item.retry_count = 0
        item.next_retry_at = None
        return {"requeued": source_item_id}

    def archive_stale_pending(self, days: int = 180) -> dict:
        """Mark old backlog as ignored so the radar starts from a useful window."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        items = list(
            self.session.execute(
                select(SourceItem).where(
                    SourceItem.analyze_status == ANALYZE_PENDING,
                    SourceItem.published_at.is_not(None),
                    SourceItem.published_at < cutoff,
                )
            ).scalars()
        )
        for item in items:
            item.analyze_status = ANALYZE_IGNORED
            item.analyze_error = f"自动归档：早于 {days} 天的历史积压"
        return {"archived": len(items), "days": days}

    def request_analysis(self, item: SourceItem):
        """Run only the remote AI inference for an item.

        Persistence is intentionally separate so the orchestrator can execute
        independent requests concurrently, then apply results serially.
        """
        source = self.session.get(SourceConfig, item.source_config_id)
        source_name = source.name if source else "unknown"
        published = item.published_at.isoformat() if item.published_at else ""
        return self.llm.extract_change_points(
            {
                "source_name": source_name,
                "source_type": source.source_type if source else "",
                "title": item.title,
                "url": item.url,
                "published_at": published,
                "content": (item.raw_content or "")[:6000],
            }
        )

    def complete_analysis(self, item: SourceItem, analysis) -> dict:
        self._apply_display_copy(item, analysis)
        result = self._persist_analysis(item, analysis)
        if result is None:
            item.analyze_status = ANALYZE_IGNORED
            outcome = {
                "success": 0,
                "ignored": 1,
                "failed": 0,
                "new_change_points": 0,
            }
        else:
            item.analyze_status = ANALYZE_SUCCESS
            outcome = {
                "success": 1,
                "ignored": 0,
                "failed": 0,
                "new_change_points": 1,
            }
        item.analyze_error = ""
        item.next_retry_at = None
        item.last_analyzed_at = datetime.now(timezone.utc)
        item.updated_at = datetime.now(timezone.utc)
        return outcome

    def fail_analysis(
        self,
        item: SourceItem,
        exc: Exception,
        *,
        now: datetime | None = None,
    ) -> dict:
        failed_at = now or datetime.now(timezone.utc)
        item.analyze_status = ANALYZE_FAILED
        item.analyze_error = (
            str(exc)
            if isinstance(exc, LlmError)
            else f"{type(exc).__name__}: {exc}"
        )
        item.retry_count += 1
        item.next_retry_at = failed_at + timedelta(
            hours=min(24, 2 ** min(item.retry_count, 5))
        )
        item.last_analyzed_at = failed_at
        item.updated_at = failed_at
        return {
            "success": 0,
            "ignored": 0,
            "failed": 1,
            "new_change_points": 0,
        }

    def _analyze_one(self, item: SourceItem) -> dict | None:
        """Compatibility wrapper for callers that need one synchronous item."""
        analysis = self.request_analysis(item)
        self._apply_display_copy(item, analysis)
        return self._persist_analysis(item, analysis)

    def _persist_analysis(self, item: SourceItem, analysis) -> dict | None:
        source = self.session.get(SourceConfig, item.source_config_id)
        if not analysis.relevant:
            return None

        # Normalize importance: snap to nearest valid level.
        importance = analysis.importance
        if importance not in VALID_IMPORTANCE:
            importance = 3 if importance > 1 else 1

        topic_id = self._resolve_topic_id(analysis.topic, source)
        occurred_at = _parse_date(analysis.occurred_at) or item.published_at
        title = (
            item.display_title.strip()
            or analysis.title.strip()
            or item.title.strip()
            or f"资讯 #{item.id}"
        )
        summary = (
            item.display_summary.strip()
            or analysis.summary.strip()
            or (item.raw_content or "").strip()[:300]
            or title
        )
        event_key = analysis.event_key.strip()
        if not event_key:
            fingerprint = sha256_hex(
                f"{item.source_config_id}|{item.external_id}|{item.url}|{title}"
            )[:20]
            event_key = f"source-item.{fingerprint}"

        cp = self.dedup.find_or_create(
            event_key=event_key,
            title=title,
            summary=summary,
            why_it_matters=analysis.why_it_matters,
            importance=importance,
            signal_type=analysis.signal_type,
            topic_id=topic_id,
            occurred_at=to_utc(occurred_at),
            source_item_id=item.id,
            duplicate_keywords=analysis.duplicate_keywords or [],
        )
        return {"change_point_id": cp.id, "event_key": cp.event_key}

    def _apply_display_copy(self, item: SourceItem, analysis) -> None:
        language = get_config().content_language
        title = (
            analysis.title.strip()
            or item.display_title.strip()
            or item.title.strip()
            or f"资讯 #{item.id}"
        )
        summary = (
            analysis.summary.strip()
            or item.display_summary.strip()
            or (item.raw_content or "").strip()
            or title
        )
        item.display_title = compact_text(title, 80)
        item.display_summary = compact_text(summary, 300)
        item.display_language = language

    def _resolve_topic_id(self, topic_name: str, source: SourceConfig | None) -> int | None:
        if topic_name:
            topic = self.session.execute(
                select(Topic).where(Topic.name == topic_name, Topic.enabled == True)  # noqa: E712
            ).scalar_one_or_none()
            if topic is not None:
                return topic.id
        # Fall back to the source's default topic.
        return source.default_topic_id if source else None


def _parse_date(value: str | None):
    if not value:
        return None
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Try ISO as a last resort.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
