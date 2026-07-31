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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from ai_radar.bootstrap import (
    ANALYZE_FAILED,
    ANALYZE_IGNORED,
    ANALYZE_PENDING,
    ANALYZE_SUCCESS,
)
from ai_radar.config import get_config
from ai_radar.database import session_scope
from ai_radar.llm.client import LlmClient
from ai_radar.models import (
    ChangePoint,
    JobLog,
    KnowledgeCoverage,
    ProfileSourceFile,
    SourceConfig,
    SourceItem,
)
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


def test_source(source_config_id: int) -> dict:
    with session_scope() as session:
        return CollectionService(session).test_source(source_config_id)


def test_all_sources(
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Probe every configured source concurrently and persist results safely."""
    with session_scope() as session:
        sources = list(
            session.execute(
                select(SourceConfig.id, SourceConfig.name).order_by(
                    SourceConfig.name
                )
            )
        )
    total = len(sources)
    if progress_callback:
        progress_callback(0, total, "准备测试全部资讯源")

    aggregate = {
        "total": total,
        "passed": 0,
        "failed": 0,
        "results": [],
        "concurrency": min(get_config().ai_concurrency, total) if total else 0,
    }
    names = {source_id: name for source_id, name in sources}
    workers = max(1, min(get_config().ai_concurrency, total or 1))
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="ai-radar-source-test",
    ) as executor:
        futures = {
            executor.submit(_probe_source, source_id): source_id
            for source_id, _name in sources
        }
        for future in as_completed(futures):
            source_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "source_config_id": source_id,
                    "source": names[source_id],
                    "status": "FAILED",
                    "items_seen": 0,
                    "sample_titles": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            with session_scope() as session:
                CollectionService(session).apply_source_test_result(
                    source_id,
                    result,
                )
            aggregate["results"].append(result)
            if result["status"] == "PASSED":
                aggregate["passed"] += 1
            else:
                aggregate["failed"] += 1
            completed = aggregate["passed"] + aggregate["failed"]
            if progress_callback:
                progress_callback(
                    completed,
                    total,
                    f"已测试 {completed}/{total}：{names[source_id]}",
                )
    aggregate["results"].sort(key=lambda item: item["source"].casefold())
    return aggregate


def _probe_source(source_config_id: int) -> dict:
    with session_scope() as session:
        return CollectionService(session).probe_source(source_config_id)


def analyze_pending_items(
    limit: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Analyze one queue batch with concurrent remote AI requests.

    Each worker owns its SQLAlchemy session. Results are applied one by one so
    change-point deduplication stays deterministic even when multiple sources
    describe the same event.
    """
    batch_size = limit or get_config().analyze_batch_size
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        rows = list(
            session.execute(
                select(SourceItem.id, SourceItem.title)
                .where(_analyzable_item_filter(now))
                .order_by(
                    SourceItem.published_at.desc().nullslast(),
                    SourceItem.collected_at.desc(),
                )
                .limit(batch_size)
            )
        )
    total = len(rows)
    if progress_callback:
        progress_callback(0, total, f"准备并行分析 {total} 条资讯")

    aggregate = {
        "processed": 0,
        "success": 0,
        "ignored": 0,
        "failed": 0,
        "new_change_points": 0,
        "batch_size": batch_size,
        "concurrency": min(get_config().ai_concurrency, total) if total else 0,
    }
    titles = {item_id: title for item_id, title in rows}
    workers = max(1, min(get_config().ai_concurrency, total or 1))
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="ai-radar-analysis",
    ) as executor:
        futures = {
            executor.submit(_request_item_analysis, item_id): item_id
            for item_id, _title in rows
        }
        for future in as_completed(futures):
            item_id = futures[future]
            try:
                analysis = future.result()
                with session_scope() as session:
                    item = session.get(SourceItem, item_id)
                    if item is None:
                        raise ValueError(f"source_item {item_id} not found")
                    outcome = AnalysisService(
                        session, LlmClient(session)
                    ).complete_analysis(item, analysis)
            except Exception as exc:
                log.warning("analyze item %s failed: %s", item_id, exc)
                with session_scope() as session:
                    item = session.get(SourceItem, item_id)
                    if item is None:
                        continue
                    outcome = AnalysisService(
                        session, LlmClient(session)
                    ).fail_analysis(item, exc)
            aggregate["processed"] += 1
            for key in ("success", "ignored", "failed", "new_change_points"):
                aggregate[key] += int(outcome.get(key, 0) or 0)
            if progress_callback:
                title = (titles.get(item_id) or f"资讯 #{item_id}")[:42]
                progress_callback(
                    aggregate["processed"],
                    total,
                    f"已完成 {aggregate['processed']}/{total}：{title}",
                )

    with session_scope() as session:
        session.add(
            JobLog(
                job_type="analyze_items",
                status="SUCCESS" if not aggregate["failed"] else "PARTIAL",
                started_at=now,
                finished_at=datetime.now(timezone.utc),
                processed_count=aggregate["processed"],
                success_count=aggregate["success"],
                failed_count=aggregate["failed"],
                message=(
                    f"并行分析 {aggregate['processed']} 条："
                    f"{aggregate['success']} 成功，"
                    f"{aggregate['ignored']} 忽略，"
                    f"{aggregate['failed']} 失败"
                ),
            )
        )
    return aggregate


def _request_item_analysis(source_item_id: int):
    with session_scope() as session:
        item = session.get(SourceItem, source_item_id)
        if item is None:
            raise ValueError(f"source_item {source_item_id} not found")
        return AnalysisService(
            session,
            LlmClient(independent_persistence=True),
        ).request_analysis(item)


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

        def batch_progress(
            current: int,
            _batch_total: int,
            _message: str,
        ) -> None:
            if progress_callback:
                overall_current = min(total, processed_before + current)
                progress_callback(
                    overall_current,
                    total,
                    f"正在处理第 {aggregate['batches'] + 1} 批"
                    f"（每批最多 {size} 条），"
                    f"累计完成 {overall_current}/{total} 条",
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
                    _analyzable_item_filter(now)
                )
            )
            or 0
        )


def _analyzable_item_filter(now: datetime):
    retry_ready = or_(
        SourceItem.next_retry_at.is_(None),
        SourceItem.next_retry_at <= now,
    )
    return or_(
        SourceItem.analyze_status == ANALYZE_PENDING,
        and_(
            SourceItem.analyze_status == ANALYZE_FAILED,
            SourceItem.retry_count < 3,
            retry_ready,
        ),
        and_(
            SourceItem.analyze_status.in_(
                [ANALYZE_SUCCESS, ANALYZE_IGNORED]
            ),
            SourceItem.display_language != get_config().content_language,
            SourceItem.retry_count < 3,
            retry_ready,
        ),
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
        workers = max(1, min(get_config().ai_concurrency, len(changed)))
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="ai-radar-profile",
        ) as executor:
            futures = {
                executor.submit(
                    _request_profile_file_extraction_worker,
                    row.id,
                    remote.content,
                ): (row.id, row.file_path, remote.content_hash)
                for row, remote in changed
            }
            for future in as_completed(futures):
                row_id, file_path, content_hash = futures[future]
                try:
                    extraction = future.result()
                    with session_scope() as session:
                        extracted_result = FactService(
                            session,
                            LlmClient(session),
                        ).apply_extraction_with_content(
                            row_id,
                            content_hash,
                            extraction,
                        )
                    affected_topic_ids.update(
                        extracted_result.get("affected_topic_ids", [])
                    )
                    extracted += 1
                except Exception as exc:
                    log.warning("re-extract %s failed: %s", file_path, exc)
                    extraction_failed += 1
                    with session_scope() as session:
                        failed_row = session.get(ProfileSourceFile, row_id)
                        if failed_row is not None:
                            failed_row.extraction_status = "FAILED"
                            failed_row.extraction_error = (
                                f"{type(exc).__name__}: {exc}"
                            )
                completed = extracted + extraction_failed
                if progress_callback:
                    file_progress = 20 + int(55 * completed / len(changed))
                    progress_callback(
                        file_progress,
                        100,
                        f"已抽取 {completed}/{len(changed)} 个记忆文件",
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
                    change_point_ids = list(
                        session.scalars(
                            select(ChangePoint.id).where(
                                ChangePoint.status == "ACTIVE",
                                ChangePoint.topic_id.in_(affected_topic_ids),
                            )
                        )
                    )
                assessment = _assess_change_points_concurrently(
                    change_point_ids,
                    trigger_type="PROFILE_CHANGED",
                    job_type="assess_profile_changed",
                    progress_callback=assessment_progress,
                )
                assessment_failed = int(assessment.get("failed", 0) or 0)
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


def _request_profile_file_extraction_worker(
    profile_file_id: int,
    content: str,
):
    with session_scope() as session:
        return FactService(
            session,
            LlmClient(independent_persistence=True),
        ).request_extraction_with_content(
            profile_file_id,
            content,
        )


def extract_facts(force: bool = False) -> dict:
    with session_scope() as session:
        return FactService(session, LlmClient(session)).extract_all(force=force)


def assess_new_change_points(
    progress_callback: ProgressCallback | None = None,
) -> dict:
    with session_scope() as session:
        candidate_ids = list(
            session.scalars(
                select(ChangePoint.id)
                .outerjoin(
                    KnowledgeCoverage,
                    KnowledgeCoverage.change_point_id == ChangePoint.id,
                )
                .where(
                    ChangePoint.status == "ACTIVE",
                    KnowledgeCoverage.id.is_(None),
                )
                .order_by(ChangePoint.first_seen_at.desc())
            )
        )
    return _assess_change_points_concurrently(
        candidate_ids,
        trigger_type="NEW_CHANGE_POINT",
        job_type="assess_new_change_points",
        progress_callback=progress_callback,
    )


def assess_all_change_points(
    progress_callback: ProgressCallback | None = None,
) -> dict:
    with session_scope() as session:
        candidate_ids = list(
            session.scalars(
                select(ChangePoint.id).where(ChangePoint.status == "ACTIVE")
            )
        )
    return _assess_change_points_concurrently(
        candidate_ids,
        trigger_type="MANUAL",
        job_type="assess_all_change_points",
        progress_callback=progress_callback,
    )


def _assess_change_points_concurrently(
    change_point_ids: list[int],
    *,
    trigger_type: str,
    job_type: str,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    total = len(change_point_ids)
    started_at = datetime.now(timezone.utc)
    if progress_callback:
        progress_callback(0, total, f"准备并行评估 {total} 个知识点")
    assessed = 0
    failed = 0
    workers = max(1, min(get_config().ai_concurrency, total or 1))
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="ai-radar-coverage",
    ) as executor:
        futures = {
            executor.submit(
                _assess_change_point_worker,
                change_point_id,
                trigger_type,
            ): change_point_id
            for change_point_id in change_point_ids
        }
        for future in as_completed(futures):
            change_point_id = futures[future]
            try:
                coverage = future.result()
                with session_scope() as session:
                    session.add(coverage)
                assessed += 1
            except Exception as exc:
                failed += 1
                log.warning("assess cp %s failed: %s", change_point_id, exc)
            completed = assessed + failed
            if progress_callback:
                progress_callback(
                    completed,
                    total,
                    f"已完成 {completed}/{total} 个知识点评估",
                )

    with session_scope() as session:
        session.add(
            JobLog(
                job_type=job_type,
                status="SUCCESS" if not failed else "PARTIAL",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                processed_count=total,
                success_count=assessed,
                failed_count=failed,
                message=(
                    f"并行评估 {total} 个知识点："
                    f"{assessed} 成功，{failed} 失败"
                ),
            )
        )
    return {
        "candidates": total,
        "total": total,
        "assessed": assessed,
        "failed": failed,
        "concurrency": min(get_config().ai_concurrency, total) if total else 0,
    }


def _assess_change_point_worker(
    change_point_id: int,
    trigger_type: str,
) -> KnowledgeCoverage:
    with session_scope() as session:
        return CoverageService(
            session,
            LlmClient(independent_persistence=True),
        ).compute_one(
            change_point_id,
            trigger_type=trigger_type,
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


def snooze_change_point(change_point_id: int, days: int = 7) -> dict:
    with session_scope() as session:
        change_point = session.get(ChangePoint, change_point_id)
        if change_point is None:
            raise ValueError(f"change_point {change_point_id} not found")
        change_point.followup_snoozed_until = datetime.now(timezone.utc) + timedelta(
            days=days
        )
        return {
            "change_point_id": change_point_id,
            "snoozed_until": change_point.followup_snoozed_until,
        }


def unsnooze_change_point(change_point_id: int) -> dict:
    with session_scope() as session:
        change_point = session.get(ChangePoint, change_point_id)
        if change_point is None:
            raise ValueError(f"change_point {change_point_id} not found")
        change_point.followup_snoozed_until = None
        return {"change_point_id": change_point_id, "snoozed_until": None}


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
