"""Scoring service: computes topic understanding scores and daily snapshots
(section 八).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import COVERAGE_NONE, COVERAGE_COEFFICIENTS, STATUS_ACTIVE
from ai_radar.config import get_config
from ai_radar.models import (
    ChangePoint,
    KnowledgeCoverage,
    Topic,
    TopicSnapshot,
)
from ai_radar.repositories.job_log import job_log
from ai_radar.utils import local_today, to_utc, utc_to_local

log = logging.getLogger(__name__)


class ScoringService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------- scoring ----------

    def compute_topic_score(self, topic_id: int) -> dict:
        """Return score + weights for a single topic (no DB write)."""
        cps = list(
            self.session.execute(
                select(ChangePoint).where(
                    ChangePoint.topic_id == topic_id,
                    ChangePoint.status == STATUS_ACTIVE,
                )
            ).scalars()
        )
        return self._score_from_change_points(cps)

    def compute_all_topic_scores(self) -> dict[int, dict]:
        result: dict[int, dict] = {}
        topics = list(
            self.session.execute(
                select(Topic).where(Topic.enabled == True)  # noqa: E712
            ).scalars()
        )
        for t in topics:
            result[t.id] = self.compute_topic_score(t.id)
        return result

    def compute_topic_health(
        self, topic_id: int, window_days: int | None = None
    ) -> dict:
        """Return actionable recent metrics alongside the lifetime score."""
        window = window_days or get_config().score_window_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=window)
        cps = list(
            self.session.execute(
                select(ChangePoint).where(
                    ChangePoint.topic_id == topic_id,
                    ChangePoint.status == STATUS_ACTIVE,
                )
            ).scalars()
        )
        recent_cps = [
            cp for cp in cps if _as_utc(cp.occurred_at or cp.first_seen_at) >= cutoff
        ]
        recent = self._score_from_change_points(recent_cps)
        lifetime = self._score_from_change_points(cps)
        important_gaps = 0
        practiced = 0
        followed = 0
        delays: list[float] = []
        for cp in recent_cps:
            cov = self._latest_coverage(cp.id)
            level = cov.coverage_level if cov else COVERAGE_NONE
            if cp.importance >= 3 and level == COVERAGE_NONE:
                important_gaps += 1
            if level == "PRACTICED":
                practiced += 1
            if level != COVERAGE_NONE:
                followed += 1
                first = self.session.execute(
                    select(KnowledgeCoverage)
                    .where(
                        KnowledgeCoverage.change_point_id == cp.id,
                        KnowledgeCoverage.coverage_level != COVERAGE_NONE,
                    )
                    .order_by(KnowledgeCoverage.assessed_at)
                    .limit(1)
                ).scalar_one_or_none()
                if first:
                    delay = (
                        _as_utc(first.assessed_at) - _as_utc(cp.first_seen_at)
                    ).total_seconds() / 86400
                    delays.append(max(0.0, delay))
        count = len(recent_cps)
        return {
            "score": recent["score"],
            "lifetime_score": lifetime["score"],
            "window_days": window,
            "change_point_count": count,
            "important_gap_count": important_gaps,
            "followed_count": followed,
            "practiced_rate": round(practiced / count * 100, 1) if count else 0.0,
            "average_followup_days": round(sum(delays) / len(delays), 1)
            if delays
            else None,
            "total_weight": recent["total_weight"],
        }

    def compute_all_topic_health(self) -> dict[int, dict]:
        topics = list(
            self.session.execute(
                select(Topic).where(Topic.enabled == True)  # noqa: E712
            ).scalars()
        )
        return {topic.id: self.compute_topic_health(topic.id) for topic in topics}

    def _score_from_change_points(self, cps: list[ChangePoint]) -> dict:
        total_weight = 0
        covered_weight = 0.0
        for cp in cps:
            coeff = self._latest_coefficient(cp.id)
            total_weight += cp.importance
            covered_weight += cp.importance * coeff
        score = (covered_weight / total_weight * 100.0) if total_weight else 0.0
        return {
            "score": round(score, 2),
            "total_weight": total_weight,
            "covered_weight": round(covered_weight, 2),
            "change_point_count": len(cps),
        }

    def _latest_coefficient(self, change_point_id: int) -> float:
        cov = self._latest_coverage(change_point_id)
        if cov is None:
            # No assessment yet → NONE coefficient (section 八).
            return COVERAGE_COEFFICIENTS[COVERAGE_NONE]
        return cov.coverage_coefficient

    def _latest_coverage(self, change_point_id: int) -> KnowledgeCoverage | None:
        return self.session.execute(
            select(KnowledgeCoverage)
            .where(KnowledgeCoverage.change_point_id == change_point_id)
            .order_by(KnowledgeCoverage.assessed_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    # ---------- snapshots ----------

    def save_snapshot(self) -> dict:
        """Save today's snapshot for every topic, computing delta vs previous."""
        today_local_start = local_today(get_config().timezone)
        scores = self.compute_all_topic_scores()
        health = self.compute_all_topic_health()
        saved = 0
        with job_log(self.session, "snapshot") as jl:
            for topic_id, score_data in scores.items():
                prev = self._previous_snapshot(topic_id, before=today_local_start)
                prev_score = prev.score if prev else 0.0
                delta = round(score_data["score"] - prev_score, 2)

                # Replace any snapshot for this (topic, date).
                existing = self.session.execute(
                    select(TopicSnapshot).where(
                        TopicSnapshot.topic_id == topic_id,
                        TopicSnapshot.snapshot_date == today_local_start,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    snap = TopicSnapshot(
                        topic_id=topic_id,
                        snapshot_date=today_local_start,
                        score=score_data["score"],
                        score_delta=delta,
                        total_weight=score_data["total_weight"],
                        covered_weight=int(round(score_data["covered_weight"])),
                        recent_score=health[topic_id]["score"],
                        important_gap_count=health[topic_id]["important_gap_count"],
                        practiced_rate=health[topic_id]["practiced_rate"],
                    )
                    self.session.add(snap)
                else:
                    existing.score = score_data["score"]
                    existing.score_delta = delta
                    existing.total_weight = score_data["total_weight"]
                    existing.covered_weight = int(round(score_data["covered_weight"]))
                    existing.recent_score = health[topic_id]["score"]
                    existing.important_gap_count = health[topic_id]["important_gap_count"]
                    existing.practiced_rate = health[topic_id]["practiced_rate"]
                saved += 1
            jl.success_count = saved
            jl.message = f"saved {saved} topic snapshots for {today_local_start.isoformat()}"
        return {"saved": saved}

    def _previous_snapshot(self, topic_id: int, before: datetime) -> TopicSnapshot | None:
        return self.session.execute(
            select(TopicSnapshot)
            .where(
                TopicSnapshot.topic_id == topic_id,
                TopicSnapshot.snapshot_date < before,
            )
            .order_by(TopicSnapshot.snapshot_date.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest_snapshots(self) -> dict[int, TopicSnapshot]:
        """Return the most recent snapshot per topic."""
        rows = list(self.session.execute(select(TopicSnapshot)).scalars())
        latest: dict[int, TopicSnapshot] = {}
        for snap in rows:
            cur = latest.get(snap.topic_id)
            if cur is None or snap.snapshot_date > cur.snapshot_date:
                latest[snap.topic_id] = snap
        return latest

    def rescore(self) -> dict:
        """Recompute scores without saving a snapshot."""
        scores = self.compute_all_topic_scores()
        return {tid: data["score"] for tid, data in scores.items()}


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
