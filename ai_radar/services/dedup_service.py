"""Change-point deduplication and merge logic (section 十三).

Uses difflib + keyword intersection + time windows. No vector DB.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import STATUS_ACTIVE
from ai_radar.bootstrap import SIGNAL_PRIORITY
from ai_radar.models import ChangePoint, ChangePointSource, SourceItem
from ai_radar.utils import to_utc

log = logging.getLogger(__name__)

TITLE_SIMILARITY_THRESHOLD = 0.72
TIME_WINDOW_DAYS = 14
KEYWORD_OVERLAP_MIN = 1


class DedupService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_or_create(
        self,
        event_key: str,
        title: str,
        summary: str,
        why_it_matters: str,
        importance: int,
        topic_id: int | None,
        occurred_at: datetime | None,
        source_item_id: int,
        duplicate_keywords: list[str],
        signal_type: str = "RELEASE",
    ) -> ChangePoint:
        """Return an existing ACTIVE change point for this event, or create one.

        Dedup order (section 十三):
          1. event_key exact match → merge.
          2. else find a candidate by title similarity / keyword overlap /
             topic / time window and merge into it.
          3. otherwise create a new change point.
        """
        existing = self._find_by_event_key(event_key)
        if existing is None:
            existing = self._find_candidate(
                title=title,
                keywords=set(k.lower() for k in duplicate_keywords),
                topic_id=topic_id,
                occurred_at=occurred_at,
            )

        if existing is None:
            cp = ChangePoint(
                topic_id=topic_id,
                event_key=event_key,
                title=title,
                summary=summary,
                why_it_matters=why_it_matters,
                importance=importance,
                signal_type=signal_type,
                occurred_at=occurred_at,
                status=STATUS_ACTIVE,
            )
            self.session.add(cp)
            self.session.flush()
            existing = cp
        else:
            # Merge: keep the highest importance, refresh last_seen, accumulate
            # summary text if the new one is meaningfully different.
            if importance > existing.importance:
                existing.importance = importance
            if SIGNAL_PRIORITY.get(signal_type, 0) > SIGNAL_PRIORITY.get(
                existing.signal_type,
                0,
            ):
                existing.signal_type = signal_type
            if title and not existing.title:
                existing.title = title
            if why_it_matters and not existing.why_it_matters:
                existing.why_it_matters = why_it_matters
            if summary and summary not in existing.summary:
                existing.summary = (existing.summary + "\n" + summary).strip() if existing.summary else summary
            existing.last_seen_at = datetime.now(timezone.utc)
            if topic_id and not existing.topic_id:
                existing.topic_id = topic_id

        self._link_source(existing.id, source_item_id)
        return existing

    def _find_by_event_key(self, event_key: str) -> ChangePoint | None:
        if not event_key:
            return None
        return self.session.execute(
            select(ChangePoint).where(
                ChangePoint.event_key == event_key,
                ChangePoint.status == STATUS_ACTIVE,
            )
        ).scalar_one_or_none()

    def _find_candidate(
        self,
        title: str,
        keywords: set[str],
        topic_id: int | None,
        occurred_at: datetime | None,
    ) -> ChangePoint | None:
        stmt = select(ChangePoint).where(ChangePoint.status == STATUS_ACTIVE)
        # Narrow by topic when available to keep the candidate set small.
        if topic_id is not None:
            stmt = stmt.where(ChangePoint.topic_id == topic_id)
        candidates = list(self.session.execute(stmt).scalars())
        best: ChangePoint | None = None
        best_score = 0.0
        now = datetime.now(timezone.utc)
        for cp in candidates:
            score = 0.0
            # Title similarity
            sim = SequenceMatcher(None, _norm(title), _norm(cp.title)).ratio()
            if sim >= TITLE_SIMILARITY_THRESHOLD:
                score += sim
            # Keyword overlap
            cp_keywords = {k.lower() for k in _extract_keywords_from_cp(cp)}
            overlap = keywords & cp_keywords
            if len(overlap) >= KEYWORD_OVERLAP_MIN:
                score += 0.3 * len(overlap)
            # Time proximity
            # SQLite returns naive datetimes even when UTC-aware values were
            # originally inserted. Normalize both sides before subtraction.
            cp_time = to_utc(cp.occurred_at or cp.first_seen_at)
            ref_time = to_utc(occurred_at or now)
            if (
                cp_time is not None
                and ref_time is not None
                and abs((ref_time - cp_time).days) <= TIME_WINDOW_DAYS
            ):
                score += 0.1
            if score > best_score and score >= 0.72:
                best = cp
                best_score = score
        return best

    def _link_source(self, change_point_id: int, source_item_id: int) -> bool:
        existing = self.session.execute(
            select(ChangePointSource).where(
                ChangePointSource.change_point_id == change_point_id,
                ChangePointSource.source_item_id == source_item_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        self.session.add(
            ChangePointSource(
                change_point_id=change_point_id,
                source_item_id=source_item_id,
            )
        )
        self.session.flush()
        return True

    def merge(self, source_id: int, target_id: int) -> ChangePoint:
        """Merge source change point INTO target (target wins)."""
        if source_id == target_id:
            raise ValueError("cannot merge a change point into itself")
        source = self.session.get(ChangePoint, source_id)
        target = self.session.get(ChangePoint, target_id)
        if source is None or target is None:
            raise ValueError("source or target change point not found")

        # Re-link all source_item links to the target.
        links = list(
            self.session.execute(
                select(ChangePointSource).where(ChangePointSource.change_point_id == source_id)
            ).scalars()
        )
        for link in links:
            already = self.session.execute(
                select(ChangePointSource).where(
                    ChangePointSource.change_point_id == target_id,
                    ChangePointSource.source_item_id == link.source_item_id,
                )
            ).scalar_one_or_none()
            if already is None:
                link.change_point_id = target_id
            else:
                self.session.delete(link)

        # Promote importance / fill missing fields on target.
        if source.importance > target.importance:
            target.importance = source.importance
        if SIGNAL_PRIORITY.get(source.signal_type, 0) > SIGNAL_PRIORITY.get(
            target.signal_type,
            0,
        ):
            target.signal_type = source.signal_type
        for attr in ("title", "summary", "why_it_matters"):
            src_val = getattr(source, attr) or ""
            tgt_val = getattr(target, attr) or ""
            if src_val and src_val not in tgt_val:
                setattr(target, attr, (tgt_val + "\n" + src_val).strip() if tgt_val else src_val)
        target.last_seen_at = datetime.now(timezone.utc)

        # Deprecate the source (do not physically delete — preserves history).
        source.status = "DEPRECATED"
        self.session.flush()
        return target


def _norm(text: str) -> str:
    return (text or "").lower().strip()


def _extract_keywords_from_cp(cp: ChangePoint) -> list[str]:
    """Heuristic: split title into tokens, drop common stopwords."""
    stopwords = {"the", "a", "an", "of", "and", "for", "to", "in", "on", "with", "is", "新增", "更新"}
    tokens = []
    raw = (cp.title or "") + " " + (cp.summary or "")
    for chunk in raw.replace(",", " ").replace(".", " ").replace("/", " ").split():
        token = chunk.strip().lower()
        if token and token not in stopwords and len(token) > 1:
            tokens.append(token)
    return tokens
