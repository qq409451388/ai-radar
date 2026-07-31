"""Process-local background runner for user-triggered pipelines.

Pipeline state is persisted in SQLite so every Streamlit page can display the
same run. Fine-grained progress stays in process memory to avoid competing for
SQLite's write lock while a long service transaction is active.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.models import PipelineRun, PipelineStep

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("QUEUED", "RUNNING")
TERMINAL_STATUSES = ("SUCCESS", "PARTIAL", "FAILED", "INTERRUPTED")


@dataclass(frozen=True)
class StepDefinition:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class PipelineDefinition:
    key: str
    label: str
    description: str
    steps: tuple[StepDefinition, ...]


_COLLECT = StepDefinition("collect", "采集资讯", "从已启用来源拉取最新条目")
_ANALYZE = StepDefinition("analyze", "AI 分析", "分析下一批待处理资讯并去重")
_ANALYZE_ALL = StepDefinition(
    "analyze_all",
    "AI 分析",
    "自动分批处理全部待处理资讯并去重",
)
_SYNC = StepDefinition("sync", "同步记忆", "同步 GPT 记录并抽取个人知识证据")
_ASSESS = StepDefinition("assess", "关联评估", "评估知识变化与个人记录的覆盖关系")
_SNAPSHOT = StepDefinition("snapshot", "更新快照", "重新计算并保存今日进展")

PIPELINES: dict[str, PipelineDefinition] = {
    "FULL_UPDATE": PipelineDefinition(
        key="FULL_UPDATE",
        label="完整更新",
        description="采集并分批处理全部资讯，再更新记忆和知识进展。",
        steps=(_COLLECT, _ANALYZE_ALL, _SYNC, _ASSESS, _SNAPSHOT),
    ),
    "INTELLIGENCE": PipelineDefinition(
        key="INTELLIGENCE",
        label="仅更新情报",
        description="不访问个人记忆仓库，只更新资讯和已有知识覆盖。",
        steps=(_COLLECT, _ANALYZE, _ASSESS, _SNAPSHOT),
    ),
    "MEMORY": PipelineDefinition(
        key="MEMORY",
        label="仅同步记忆",
        description="同步 GPT 记录，并刷新受影响领域的进展快照。",
        steps=(_SYNC, _SNAPSHOT),
    ),
}

ProgressCallback = Callable[[int, int, str], None]
StepHandler = Callable[[ProgressCallback], dict[str, Any]]

_state_lock = threading.RLock()
_active_run_ids: set[int] = set()
_live_progress: dict[int, dict[str, Any]] = {}


def _collect_handler(callback: ProgressCallback) -> dict[str, Any]:
    return orchestrator.collect_all_sources(progress_callback=callback)


def _analyze_handler(callback: ProgressCallback) -> dict[str, Any]:
    return orchestrator.analyze_pending_items(progress_callback=callback)


def _analyze_all_handler(callback: ProgressCallback) -> dict[str, Any]:
    return orchestrator.analyze_all_pending_items(progress_callback=callback)


def _sync_handler(callback: ProgressCallback) -> dict[str, Any]:
    return orchestrator.sync_profile(progress_callback=callback)


def _assess_handler(callback: ProgressCallback) -> dict[str, Any]:
    return orchestrator.assess_new_change_points(progress_callback=callback)


def _snapshot_handler(callback: ProgressCallback) -> dict[str, Any]:
    callback(0, 1, "正在计算领域得分")
    result = orchestrator.save_snapshot()
    callback(1, 1, "今日进展快照已更新")
    return result


STEP_HANDLERS: dict[str, StepHandler] = {
    "collect": _collect_handler,
    "analyze": _analyze_handler,
    "analyze_all": _analyze_all_handler,
    "sync": _sync_handler,
    "assess": _assess_handler,
    "snapshot": _snapshot_handler,
}


def recover_interrupted_runs() -> int:
    """Mark work left by a previous app process as interrupted."""
    now = datetime.now(timezone.utc)
    recovered = 0
    with _state_lock, session_scope() as session:
        runs = list(
            session.execute(
                select(PipelineRun).where(PipelineRun.status.in_(ACTIVE_STATUSES))
            ).scalars()
        )
        for run in runs:
            if run.id in _active_run_ids:
                continue
            run.status = "INTERRUPTED"
            run.finished_at = now
            run.heartbeat_at = now
            run.error = "应用进程在任务完成前已停止，请重新运行。"
            for step in run.steps:
                if step.status == "RUNNING":
                    step.status = "INTERRUPTED"
                    step.finished_at = now
                    step.message = run.error
                elif step.status == "PENDING":
                    step.status = "SKIPPED"
                    step.finished_at = now
                    step.message = "因应用进程停止而跳过"
            recovered += 1
    return recovered


def enqueue_pipeline(pipeline_type: str) -> tuple[int, bool]:
    """Create and start a pipeline, or return the currently active run."""
    definition = PIPELINES.get(pipeline_type)
    if definition is None:
        raise ValueError(f"unknown pipeline type: {pipeline_type}")

    with _state_lock:
        _recover_stale_active_runs()
        with session_scope() as session:
            active = session.execute(
                select(PipelineRun)
                .where(PipelineRun.status.in_(ACTIVE_STATUSES))
                .order_by(PipelineRun.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if active is not None:
                return active.id, False

            run = PipelineRun(
                pipeline_type=pipeline_type,
                status="QUEUED",
                current_step="",
                progress=0.0,
            )
            session.add(run)
            session.flush()
            for position, step in enumerate(definition.steps, start=1):
                session.add(
                    PipelineStep(
                        run_id=run.id,
                        step_key=step.key,
                        label=step.label,
                        position=position,
                        status="PENDING",
                    )
                )
            session.flush()
            run_id = run.id

        _active_run_ids.add(run_id)
        _live_progress[run_id] = {
            "status": "QUEUED",
            "step_key": "",
            "step_progress": 0.0,
            "overall_progress": 0.0,
            "current": 0,
            "total": 0,
            "message": "任务已进入队列",
            "heartbeat_at": datetime.now(timezone.utc),
        }
        try:
            thread = threading.Thread(
                target=_execute_pipeline,
                args=(run_id,),
                name=f"ai-radar-pipeline-{run_id}",
                daemon=True,
            )
            thread.start()
        except Exception:
            _active_run_ids.discard(run_id)
            _live_progress.pop(run_id, None)
            _mark_start_failure(run_id)
            raise
        return run_id, True


def get_pipeline_snapshot(run_id: int | None = None) -> dict[str, Any] | None:
    """Return detached, render-ready state merged with live progress."""
    with session_scope() as session:
        stmt = select(PipelineRun).options(selectinload(PipelineRun.steps))
        if run_id is None:
            stmt = stmt.order_by(PipelineRun.id.desc()).limit(1)
        else:
            stmt = stmt.where(PipelineRun.id == run_id)
        run = session.execute(stmt).scalar_one_or_none()
        if run is None:
            return None
        snapshot = {
            "id": run.id,
            "pipeline_type": run.pipeline_type,
            "pipeline_label": PIPELINES.get(
                run.pipeline_type,
                PipelineDefinition(run.pipeline_type, run.pipeline_type, "", ()),
            ).label,
            "status": run.status,
            "current_step": run.current_step,
            "progress": float(run.progress or 0.0),
            "requested_at": run.requested_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "heartbeat_at": run.heartbeat_at,
            "error": run.error,
            "result": _load_json(run.result_json),
            "steps": [
                {
                    "key": step.step_key,
                    "label": step.label,
                    "position": step.position,
                    "status": step.status,
                    "progress": float(step.progress or 0.0),
                    "processed": step.processed_count,
                    "success": step.success_count,
                    "failed": step.failed_count,
                    "message": step.message,
                    "result": _load_json(step.result_json),
                    "started_at": step.started_at,
                    "finished_at": step.finished_at,
                }
                for step in run.steps
            ],
        }

    with _state_lock:
        live = dict(_live_progress.get(snapshot["id"], {}))
    if live:
        snapshot["status"] = live.get("status", snapshot["status"])
        snapshot["current_step"] = live.get(
            "step_key", snapshot["current_step"]
        )
        snapshot["progress"] = live.get(
            "overall_progress", snapshot["progress"]
        )
        snapshot["heartbeat_at"] = live.get(
            "heartbeat_at", snapshot["heartbeat_at"]
        )
        snapshot["live"] = live
        for step in snapshot["steps"]:
            if (
                live.get("status") in ACTIVE_STATUSES
                and step["key"] == live.get("step_key")
            ):
                step["status"] = "RUNNING"
                step["progress"] = live.get("step_progress", step["progress"])
                step["message"] = live.get("message", step["message"])
    return snapshot


def get_active_pipeline_snapshot() -> dict[str, Any] | None:
    snapshot = get_pipeline_snapshot()
    if snapshot and snapshot["status"] in ACTIVE_STATUSES:
        return snapshot
    return None


def _recover_stale_active_runs() -> None:
    """Locked variant used immediately before creating a new run."""
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        runs = list(
            session.execute(
                select(PipelineRun).where(PipelineRun.status.in_(ACTIVE_STATUSES))
            ).scalars()
        )
        for run in runs:
            if run.id in _active_run_ids:
                continue
            run.status = "INTERRUPTED"
            run.finished_at = now
            run.heartbeat_at = now
            run.error = "上一次运行所属的应用进程已停止，请重新运行。"
            for step in run.steps:
                if step.status == "RUNNING":
                    step.status = "INTERRUPTED"
                    step.message = run.error
                    step.finished_at = now
                elif step.status == "PENDING":
                    step.status = "SKIPPED"
                    step.message = "因上一次运行中断而跳过"
                    step.finished_at = now


def _execute_pipeline(run_id: int) -> None:
    results: dict[str, Any] = {}
    try:
        with session_scope() as session:
            run = session.get(PipelineRun, run_id)
            if run is None:
                return
            run.status = "RUNNING"
            run.started_at = datetime.now(timezone.utc)
            run.heartbeat_at = run.started_at
            pipeline_type = run.pipeline_type

        definition = PIPELINES[pipeline_type]
        any_partial = False
        for index, step_definition in enumerate(definition.steps):
            _start_step(run_id, step_definition.key)
            callback = _make_progress_callback(
                run_id,
                step_definition.key,
                index,
                len(definition.steps),
            )
            try:
                result = STEP_HANDLERS[step_definition.key](callback)
            except Exception as exc:
                _fail_pipeline(
                    run_id,
                    step_definition.key,
                    index,
                    len(definition.steps),
                    exc,
                )
                return

            failed_count = _failed_count(result)
            step_status = "PARTIAL" if failed_count else "SUCCESS"
            any_partial = any_partial or bool(failed_count)
            results[step_definition.key] = result
            _finish_step(
                run_id,
                step_definition.key,
                index,
                len(definition.steps),
                result,
                step_status,
            )

        now = datetime.now(timezone.utc)
        final_status = "PARTIAL" if any_partial else "SUCCESS"
        with session_scope() as session:
            run = session.get(PipelineRun, run_id)
            if run is not None:
                run.status = final_status
                run.current_step = ""
                run.progress = 1.0
                run.finished_at = now
                run.heartbeat_at = now
                run.result_json = _dump_json(results)
        _set_live(
            run_id,
            status=final_status,
            step_key="",
            step_progress=1.0,
            overall_progress=1.0,
            current=1,
            total=1,
            message="流水线已完成",
        )
    except Exception as exc:  # pragma: no cover - last-resort guard
        log.exception("pipeline run %s crashed", run_id)
        _fail_pipeline(run_id, "", 0, 1, exc)
    finally:
        with _state_lock:
            _active_run_ids.discard(run_id)


def _make_progress_callback(
    run_id: int,
    step_key: str,
    step_index: int,
    step_count: int,
) -> ProgressCallback:
    def update(current: int, total: int, message: str) -> None:
        ratio = min(1.0, max(0.0, current / total if total else 1.0))
        _set_live(
            run_id,
            status="RUNNING",
            step_key=step_key,
            step_progress=ratio,
            overall_progress=(step_index + ratio) / step_count,
            current=current,
            total=total,
            message=message,
        )

    return update


def _set_live(run_id: int, **values: Any) -> None:
    with _state_lock:
        state = _live_progress.setdefault(run_id, {})
        state.update(values)
        state["heartbeat_at"] = datetime.now(timezone.utc)


def _start_step(run_id: int, step_key: str) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        step = session.execute(
            select(PipelineStep).where(
                PipelineStep.run_id == run_id,
                PipelineStep.step_key == step_key,
            )
        ).scalar_one()
        if run is not None:
            run.status = "RUNNING"
            run.current_step = step_key
            run.heartbeat_at = now
        step.status = "RUNNING"
        step.started_at = now
        step.message = "步骤已开始"


def _finish_step(
    run_id: int,
    step_key: str,
    step_index: int,
    step_count: int,
    result: dict[str, Any],
    status: str,
) -> None:
    now = datetime.now(timezone.utc)
    processed, success, failed = _result_counts(result)
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        step = session.execute(
            select(PipelineStep).where(
                PipelineStep.run_id == run_id,
                PipelineStep.step_key == step_key,
            )
        ).scalar_one()
        step.status = status
        step.progress = 1.0
        step.processed_count = processed
        step.success_count = success
        step.failed_count = failed
        step.message = _result_message(result, status)
        step.result_json = _dump_json(result)
        step.finished_at = now
        if run is not None:
            run.progress = (step_index + 1) / step_count
            run.heartbeat_at = now
    _set_live(
        run_id,
        status="RUNNING",
        step_key=step_key,
        step_progress=1.0,
        overall_progress=(step_index + 1) / step_count,
        current=processed,
        total=processed,
        message=_result_message(result, status),
    )


def _fail_pipeline(
    run_id: int,
    step_key: str,
    step_index: int,
    step_count: int,
    exc: Exception,
) -> None:
    now = datetime.now(timezone.utc)
    error = f"{type(exc).__name__}: {exc}"[:4000]
    try:
        with session_scope() as session:
            run = session.get(PipelineRun, run_id)
            if run is None:
                return
            run.status = "FAILED"
            run.current_step = step_key
            run.progress = step_index / step_count
            run.finished_at = now
            run.heartbeat_at = now
            run.error = error
            for step in run.steps:
                if step.step_key == step_key:
                    step.status = "FAILED"
                    step.finished_at = now
                    step.message = error
                elif step.status == "PENDING":
                    step.status = "SKIPPED"
                    step.finished_at = now
                    step.message = "因前一步失败而跳过"
    finally:
        _set_live(
            run_id,
            status="FAILED",
            step_key=step_key,
            step_progress=0.0,
            overall_progress=step_index / step_count,
            current=0,
            total=0,
            message=error,
        )


def _mark_start_failure(run_id: int) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is not None:
            run.status = "FAILED"
            run.finished_at = now
            run.error = "后台任务线程启动失败"


def _result_counts(result: dict[str, Any]) -> tuple[int, int, int]:
    failed = _failed_count(result)
    processed = int(
        result.get(
            "processed",
            result.get(
                "sources",
                result.get(
                    "candidates",
                    result.get(
                        "synced",
                        result.get(
                            "extracted",
                            result.get("saved", result.get("snapshots", 0)),
                        ),
                    ),
                ),
            ),
        )
        or 0
    )
    success = int(
        result.get(
            "success",
            result.get(
                "assessed",
                result.get(
                    "synced",
                    result.get(
                        "saved",
                        result.get("new", max(0, processed - failed)),
                    ),
                ),
            ),
        )
        or 0
    )
    return processed, success, failed


def _failed_count(result: dict[str, Any]) -> int:
    failures = sum(
        int(result.get(key, 0) or 0)
        for key in (
            "failed",
            "failed_sources",
            "extraction_failed",
            "assessment_failed",
        )
    )
    if result.get("error") and not failures:
        failures = 1
    return failures


def _result_message(result: dict[str, Any], status: str) -> str:
    processed, success, failed = _result_counts(result)
    if "batches" in result:
        message = (
            f"完成 {int(result.get('batches', 0) or 0)} 批："
            f"处理 {processed} 条，"
            f"形成知识点 {int(result.get('new_change_points', 0) or 0)} 条，"
            f"自动过滤 {int(result.get('ignored', 0) or 0)} 条，"
            f"剩余待处理 {int(result.get('remaining_pending', 0) or 0)} 条"
        )
        if failed:
            return f"{message}，失败 {failed} 条"
        return message
    if status == "PARTIAL":
        return f"完成，但有 {failed} 项失败；已处理 {processed} 项"
    if processed:
        return f"完成：处理 {processed} 项，成功 {success} 项"
    return "完成：没有需要处理的项目"


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
