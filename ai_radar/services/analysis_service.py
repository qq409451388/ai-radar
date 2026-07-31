"""Analysis service: runs the LLM over PENDING source items to create change points."""
from __future__ import annotations

import logging
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
from ai_radar.utils import to_utc

log = logging.getLogger(__name__)

_IMPORTANCE_TO_INT = {1, 3, 5}


class AnalysisService:
    def __init__(self, session: Session, llm: LlmClient | None = None) -> None:
        self.session = session
        self.llm = llm or LlmClient(session)
        self.dedup = DedupService(session)

    def analyze_pending(self, limit: int | None = None) -> dict:
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

        success = 0
        ignored = 0
        failed = 0
        new_cp = 0
        with job_log(self.session, "analyze_items") as jl:
            for item in items:
                jl.processed_count += 1
                try:
                    result = self._analyze_one(item)
                    if result is None:
                        item.analyze_status = ANALYZE_IGNORED
                        ignored += 1
                    else:
                        item.analyze_status = ANALYZE_SUCCESS
                        success += 1
                        new_cp += 1
                    item.analyze_error = ""
                    item.next_retry_at = None
                except LlmError as exc:
                    item.analyze_status = ANALYZE_FAILED
                    item.analyze_error = str(exc)
                    item.retry_count += 1
                    item.next_retry_at = now + timedelta(
                        hours=min(24, 2 ** min(item.retry_count, 5))
                    )
                    failed += 1
                    log.warning("analyze item %s failed: %s", item.id, exc)
                except Exception as exc:
                    item.analyze_status = ANALYZE_FAILED
                    item.analyze_error = f"{type(exc).__name__}: {exc}"
                    item.retry_count += 1
                    item.next_retry_at = now + timedelta(
                        hours=min(24, 2 ** min(item.retry_count, 5))
                    )
                    failed += 1
                    log.exception("analyze item %s errored", item.id)
                item.last_analyzed_at = datetime.now(timezone.utc)
                item.updated_at = datetime.now(timezone.utc)
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

    def _analyze_one(self, item: SourceItem) -> dict | None:
        source = self.session.get(SourceConfig, item.source_config_id)
        source_name = source.name if source else "unknown"
        published = item.published_at.isoformat() if item.published_at else ""
        analysis = self.llm.extract_change_points(
            {
                "source_name": source_name,
                "title": item.title,
                "url": item.url,
                "published_at": published,
                "content": (item.raw_content or "")[:6000],
            }
        )

        if not analysis.relevant:
            return None

        # Normalize importance: snap to nearest valid level.
        importance = analysis.importance
        if importance not in VALID_IMPORTANCE:
            importance = 3 if importance > 1 else 1

        topic_id = self._resolve_topic_id(analysis.topic, source)
        occurred_at = _parse_date(analysis.occurred_at) or item.published_at

        cp = self.dedup.find_or_create(
            event_key=analysis.event_key,
            title=analysis.title,
            summary=analysis.summary,
            why_it_matters=analysis.why_it_matters,
            importance=importance,
            topic_id=topic_id,
            occurred_at=to_utc(occurred_at),
            source_item_id=item.id,
            duplicate_keywords=analysis.duplicate_keywords or [],
        )
        return {"change_point_id": cp.id, "event_key": cp.event_key}

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
