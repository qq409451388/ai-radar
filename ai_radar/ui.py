"""Shared Streamlit UI helpers: formatting, common queries, layout."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import (
    COVERAGE_NONE,
    STATUS_ACTIVE,
)
from ai_radar.models import (
    ChangePoint,
    ChangePointSource,
    JobLog,
    KnowledgeCoverage,
    ProfileFact,
    ProfileSourceFile,
    SourceConfig,
    SourceItem,
    Topic,
    TopicSnapshot,
)
from ai_radar.services.scoring_service import ScoringService
from ai_radar.utils import utc_to_local


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return utc_to_local(dt).strftime("%Y-%m-%d %H:%M")


def fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return utc_to_local(dt).strftime("%Y-%m-%d")


def coverage_color(level: str) -> str:
    return {
        "NONE": "#e74c3c",
        "AWARE": "#f39c12",
        "UNDERSTOOD": "#3498db",
        "PRACTICED": "#27ae60",
    }.get(level, "#95a5a6")


def importance_label(importance: int) -> str:
    return {1: "普通", 3: "关注", 5: "重大"}.get(importance, str(importance))


def all_topics(session: Session) -> list[Topic]:
    return list(session.execute(select(Topic).order_by(Topic.id)).scalars())


def dashboard_rows(session: Session) -> list[dict[str, Any]]:
    """Return per-topic dashboard rows for the Dashboard page."""
    scoring = ScoringService(session)
    latest_snap = scoring.latest_snapshots()
    today_local_start_dt = None
    from ai_radar.utils import local_today

    today_utc = local_today()  # start of today in local tz, as UTC datetime

    rows = []
    topics = list(
        session.execute(
            select(Topic).where(Topic.enabled == True).order_by(Topic.id)  # noqa: E712
        ).scalars()
    )
    for t in topics:
        score_data = scoring.compute_topic_score(t.id)
        snap = latest_snap.get(t.id)
        delta = snap.score_delta if snap else 0.0

        # Count active change points
        cps = list(
            session.execute(
                select(ChangePoint).where(
                    ChangePoint.topic_id == t.id,
                    ChangePoint.status == STATUS_ACTIVE,
                )
            ).scalars()
        )
        total_weight = sum(cp.importance for cp in cps)

        # Uncovered important change points (importance >= 3, coverage NONE)
        uncovered_important = 0
        for cp in cps:
            cov = session.execute(
                select(KnowledgeCoverage)
                .where(KnowledgeCoverage.change_point_id == cp.id)
                .order_by(KnowledgeCoverage.assessed_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if (cov is None or cov.coverage_level == COVERAGE_NONE) and cp.importance >= 3:
                uncovered_important += 1

        # Today's new change points
        today_new = sum(
            1 for cp in cps if cp.first_seen_at and cp.first_seen_at >= today_utc
        )

        rows.append(
            {
                "topic": t,
                "score": score_data["score"],
                "delta": round(delta, 2),
                "total_weight": total_weight,
                "cp_count": len(cps),
                "uncovered_important": uncovered_important,
                "today_new": today_new,
            }
        )
    return rows


def today_change_points(session: Session) -> list[ChangePoint]:
    from ai_radar.utils import local_today

    today_utc = local_today()
    return list(
        session.execute(
            select(ChangePoint)
            .where(ChangePoint.first_seen_at >= today_utc)
            .order_by(ChangePoint.importance.desc(), ChangePoint.first_seen_at.desc())
        ).scalars()
    )


def latest_coverage(session: Session, change_point_id: int) -> KnowledgeCoverage | None:
    return session.execute(
        select(KnowledgeCoverage)
        .where(KnowledgeCoverage.change_point_id == change_point_id)
        .order_by(KnowledgeCoverage.assessed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def sources_for_change_point(session: Session, change_point_id: int) -> list[SourceItem]:
    links = list(
        session.execute(
            select(ChangePointSource).where(
                ChangePointSource.change_point_id == change_point_id
            )
        ).scalars()
    )
    items = []
    for link in links:
        item = session.get(SourceItem, link.source_item_id)
        if item is not None:
            items.append(item)
    return items


def profile_files(session: Session) -> list[ProfileSourceFile]:
    return list(
        session.execute(
            select(ProfileSourceFile).order_by(ProfileSourceFile.file_path)
        ).scalars()
    )


def facts_for_file(session: Session, source_file_id: int) -> list[ProfileFact]:
    return list(
        session.execute(
            select(ProfileFact)
            .where(ProfileFact.source_file_id == source_file_id)
            .order_by(ProfileFact.source_line_start)
        ).scalars()
    )


def recent_jobs(session: Session, limit: int = 30) -> list[JobLog]:
    from ai_radar.repositories.job_log import recent_jobs as _rj

    return _rj(session, limit=limit)
