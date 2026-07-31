"""Orchestrator: thin facade exposing the system-job actions used by the
scheduler and the Streamlit "系统任务" page (section 十七.7).

Each method opens its own DB session so it can be called from background
threads without sharing Streamlit's session lifecycle. Long-running LLM jobs
are split into multiple short transactions so they do not hold SQLite write
locks for minutes (which caused "database is locked" under concurrency).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select

from ai_radar.bootstrap import ANALYZE_FAILED, ANALYZE_PENDING
from ai_radar.config import get_config
from ai_radar.database import session_scope
from ai_radar.llm.client import LlmClient
from ai_radar.models import ProfileSourceFile, SourceItem
from ai_radar.profile.fact_service import FactService
from ai_radar.profile.sync_service import ProfileSyncService
from ai_radar.services.analysis_service import AnalysisService
from ai_radar.services.collection_service import CollectionService
from ai_radar.services.coverage_service import CoverageService
from ai_radar.services.dedup_service import DedupService
from ai_radar.services.scoring_service import ScoringService

log = logging.getLogger(__name__)


ProgressCallback = Callable[[int, int, str], None]


def collect_all_sources(
    progress_callback: ProgressCallback | None = None,
) -> dict:
    with session_scope() as session:
        return CollectionService(session).collect_all(
            progress_callback=progress_callback
        )


def collect_one_source(source_config_id: int) -> dict:
    with session_scope() as session:
        return CollectionService(session).collect_one(source_config_id)


def analyze_pending_items(
    limit: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Analyze PENDING items.

    Runs inside a single session; the busy_timeout pragma on the SQLite
    connection lets concurrent writers (e.g. Streamlit UI) wait instead of
    failing immediately with "database is locked".
    """
    with session_scope() as session:
        return AnalysisService(session, LlmClient(session)).analyze_pending(
            limit=limit,
            progress_callback=progress_callback,
        )


def analyze_all_pending_items(
    batch_size: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Drain the current analyzable queue in independently committed batches."""
    size = batch_size or get_config().analyze_batch_size
    total = _count_analyzable_items()
    aggregate = {
        "processed": 0,
        "success": 0,
        "ignored": 0,
        "failed": 0,
        "new_change_points": 0,
        "batch_size": size,
        "batches": 0,
        "remaining_pending": 0,
    }
    if progress_callback:
        progress_callback(0, total, f"准备分批处理 {total} 条待分析资讯")

    while aggregate["processed"] < total:
        processed_before = aggregate["processed"]

        def batch_progress(current: int, _batch_total: int, message: str) -> None:
            if progress_callback:
                progress_callback(
                    min(total, processed_before + current),
                    total,
                    message,
                )

        result = analyze_pending_items(
            limit=size,
            progress_callback=batch_progress,
        )
        processed = int(result.get("processed", 0) or 0)
        if processed == 0:
            break
        aggregate["batches"] += 1
        for key in (
            "processed",
            "success",
            "ignored",
            "failed",
            "new_change_points",
        ):
            aggregate[key] += int(result.get(key, 0) or 0)

        if progress_callback:
            progress_callback(
                min(total, aggregate["processed"]),
                total,
                f"已完成第 {aggregate['batches']} 批，"
                f"累计处理 {aggregate['processed']}/{total} 条",
            )

    with session_scope() as session:
        aggregate["remaining_pending"] = int(
            session.scalar(
                select(func.count(SourceItem.id)).where(
                    SourceItem.analyze_status == ANALYZE_PENDING
                )
            )
            or 0
        )
    if progress_callback:
        progress_callback(
            total,
            total,
            f"全部批次完成，剩余待处理 {aggregate['remaining_pending']} 条",
        )
    return aggregate


def _count_analyzable_items() -> int:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count(SourceItem.id)).where(
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
            )
            or 0
        )


def sync_profile(progress_callback: ProgressCallback | None = None) -> dict:
    """Sync GitHub memory in short transactions; LLM calls happen outside
    any held write lock.
    """
    if progress_callback:
        progress_callback(0, 100, "正在读取 GitHub 记忆仓库")

    # Step 1: sync file list (short write tx).
    with session_scope() as session:
        svc = ProfileSyncService(session)
        result = svc.sync()
        changed = result.pop("changed_files", [])
    if progress_callback:
        progress_callback(
            20,
            100,
            f"仓库同步完成，{len(changed)} 个文件需要重新抽取",
        )

    # Step 2: re-extract facts for each changed file (one short tx per file).
    affected_topic_ids: set[int] = set()
    extracted = 0
    extraction_failed = 0
    assessment_failed = 0
    if changed:
        for index, (row, remote) in enumerate(changed, start=1):
            if progress_callback:
                file_progress = 20 + int(55 * (index - 1) / len(changed))
                progress_callback(
                    file_progress,
                    100,
                    f"正在抽取第 {index}/{len(changed)} 个记忆文件：{row.file_path}",
                )
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
            if progress_callback:
                file_progress = 20 + int(55 * index / len(changed))
                progress_callback(
                    file_progress,
                    100,
                    f"已抽取 {index}/{len(changed)} 个记忆文件",
                )

        # Step 3: only re-assess topics touched by changed facts.
        if affected_topic_ids:
            try:
                def assessment_progress(current: int, total: int, message: str) -> None:
                    if not progress_callback:
                        return
                    ratio = current / total if total else 1.0
                    progress_callback(
                        75 + int(25 * ratio),
                        100,
                        message,
                    )

                with session_scope() as session:
                    CoverageService(
                        session, LlmClient(session)
                    ).assess_topics(
                        affected_topic_ids,
                        progress_callback=assessment_progress,
                    )
            except Exception as exc:
                log.warning("re-assess after profile sync failed: %s", exc)
                assessment_failed = 1
    result["extracted"] = extracted
    result["extraction_failed"] = extraction_failed
    result["assessment_failed"] = assessment_failed
    result["affected_topics"] = len(affected_topic_ids)
    if progress_callback:
        progress_callback(100, 100, "记忆同步与关联评估完成")
    return result


def extract_facts(force: bool = False) -> dict:
    with session_scope() as session:
        return FactService(session, LlmClient(session)).extract_all(force=force)


def assess_new_change_points(
    progress_callback: ProgressCallback | None = None,
) -> dict:
    with session_scope() as session:
        return CoverageService(session, LlmClient(session)).assess_new(
            progress_callback=progress_callback
        )


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
