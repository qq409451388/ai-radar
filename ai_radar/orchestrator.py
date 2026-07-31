"""Orchestrator: thin facade exposing the system-job actions used by the
scheduler and the Streamlit "系统任务" page (section 十七.7).

Each method opens its own DB session so it can be called from background
threads without sharing Streamlit's session lifecycle. Long-running LLM jobs
are split into multiple short transactions so they do not hold SQLite write
locks for minutes (which caused "database is locked" under concurrency).
"""
from __future__ import annotations

import logging

from ai_radar.database import session_scope
from ai_radar.llm.client import LlmClient
from ai_radar.models import ProfileSourceFile
from ai_radar.profile.fact_service import FactService
from ai_radar.profile.sync_service import ProfileSyncService
from ai_radar.services.analysis_service import AnalysisService
from ai_radar.services.collection_service import CollectionService
from ai_radar.services.coverage_service import CoverageService
from ai_radar.services.dedup_service import DedupService
from ai_radar.services.scoring_service import ScoringService

log = logging.getLogger(__name__)


def collect_all_sources() -> dict:
    with session_scope() as session:
        return CollectionService(session).collect_all()


def collect_one_source(source_config_id: int) -> dict:
    with session_scope() as session:
        return CollectionService(session).collect_one(source_config_id)


def analyze_pending_items(limit: int | None = None) -> dict:
    """Analyze PENDING items.

    Runs inside a single session; the busy_timeout pragma on the SQLite
    connection lets concurrent writers (e.g. Streamlit UI) wait instead of
    failing immediately with "database is locked".
    """
    with session_scope() as session:
        return AnalysisService(session, LlmClient(session)).analyze_pending(limit=limit)


def sync_profile() -> dict:
    """Sync GitHub memory in short transactions; LLM calls happen outside
    any held write lock.
    """
    # Step 1: sync file list (short write tx).
    with session_scope() as session:
        svc = ProfileSyncService(session)
        result = svc.sync()
        changed = result.pop("changed_files", [])

    # Step 2: re-extract facts for each changed file (one short tx per file).
    affected_topic_ids: set[int] = set()
    extracted = 0
    extraction_failed = 0
    if changed:
        for row, remote in changed:
            try:
                with session_scope() as session:
                    extracted_result = FactService(
                        session, LlmClient(session)
                    ).extract_with_content(
                        row.id, remote.content, remote.content_hash, force=True
                    )
                    affected_topic_ids.update(
                        extracted_result.get("affected_topic_ids", [])
                    )
                    extracted += 1
            except Exception as exc:
                log.warning("re-extract %s failed: %s", row.file_path, exc)
                extraction_failed += 1
                with session_scope() as session:
                    failed_row = session.get(ProfileSourceFile, row.id)
                    if failed_row is not None:
                        failed_row.extraction_status = "FAILED"
                        failed_row.extraction_error = f"{type(exc).__name__}: {exc}"

        # Step 3: only re-assess topics touched by changed facts.
        if affected_topic_ids:
            try:
                with session_scope() as session:
                    CoverageService(
                        session, LlmClient(session)
                    ).assess_topics(affected_topic_ids)
            except Exception as exc:
                log.warning("re-assess after profile sync failed: %s", exc)
    result["extracted"] = extracted
    result["extraction_failed"] = extraction_failed
    result["affected_topics"] = len(affected_topic_ids)
    return result


def extract_facts(force: bool = False) -> dict:
    with session_scope() as session:
        return FactService(session, LlmClient(session)).extract_all(force=force)


def assess_new_change_points() -> dict:
    with session_scope() as session:
        return CoverageService(session, LlmClient(session)).assess_new()


def assess_all_change_points() -> dict:
    with session_scope() as session:
        return CoverageService(session, LlmClient(session)).assess_all(
            force=True, trigger_type="MANUAL"
        )


def assess_change_point(change_point_id: int) -> dict:
    with session_scope() as session:
        coverage = CoverageService(session, LlmClient(session)).assess_one(
            change_point_id
        )
        return {
            "change_point_id": change_point_id,
            "coverage_level": coverage.coverage_level,
        }


def requeue_source_item(source_item_id: int) -> dict:
    with session_scope() as session:
        return AnalysisService(session, LlmClient(session)).requeue(source_item_id)


def archive_stale_pending(days: int = 180) -> dict:
    with session_scope() as session:
        return AnalysisService(session, LlmClient(session)).archive_stale_pending(days)


def rescore() -> dict:
    with session_scope() as session:
        return ScoringService(session).rescore()


def save_snapshot() -> dict:
    with session_scope() as session:
        return ScoringService(session).save_snapshot()


def merge_change_points(source_id: int, target_id: int) -> dict:
    with session_scope() as session:
        target = DedupService(session).merge(source_id, target_id)
        return {"merged_into": target.id, "event_key": target.event_key}


def daily_morning_pipeline() -> dict:
    """08:00 pipeline: collect → analyze → (assessment deferred)."""
    collect = collect_all_sources()
    analyze = analyze_pending_items()
    return {"collect": collect, "analyze": analyze}


def daily_evening_pipeline() -> dict:
    """23:00 pipeline: assess new → rescore → snapshot."""
    assess_new_change_points()
    snapshot = save_snapshot()
    return {"snapshot": snapshot}


def run_now_pipeline(limit: int | None = None) -> dict:
    """Safe one-click pipeline used by the redesigned home page."""
    collect = collect_all_sources()
    analyze = analyze_pending_items(limit=limit)
    profile = sync_profile()
    assess = assess_new_change_points()
    snapshot = save_snapshot()
    return {
        "collect": collect,
        "analyze": analyze,
        "profile": profile,
        "assess": assess,
        "snapshot": snapshot,
    }
