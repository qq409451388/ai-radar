from __future__ import annotations

import threading
import time

from ai_radar import pipeline_runner


def _wait_for_terminal(run_id: int, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = pipeline_runner.get_pipeline_snapshot(run_id)
        if snapshot and snapshot["status"] not in pipeline_runner.ACTIVE_STATUSES:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"pipeline {run_id} did not finish")


def _install_success_handlers(monkeypatch, calls: list[str]) -> None:
    for step_key in pipeline_runner.STEP_HANDLERS:
        def handler(callback, key=step_key):
            calls.append(key)
            callback(0, 1, f"running {key}")
            callback(1, 1, f"finished {key}")
            return {"processed": 1, "success": 1, "failed": 0}

        monkeypatch.setitem(pipeline_runner.STEP_HANDLERS, step_key, handler)


def test_background_pipeline_runs_connected_steps(session, monkeypatch):
    calls: list[str] = []
    _install_success_handlers(monkeypatch, calls)

    run_id, created = pipeline_runner.enqueue_pipeline("FULL_UPDATE")
    snapshot = _wait_for_terminal(run_id)

    assert created is True
    assert calls == ["collect", "analyze", "sync", "assess", "snapshot"]
    assert snapshot["status"] == "SUCCESS"
    assert snapshot["progress"] == 1.0
    assert [step["status"] for step in snapshot["steps"]] == ["SUCCESS"] * 5


def test_pipeline_failure_stops_and_marks_remaining_steps(session, monkeypatch):
    calls: list[str] = []
    _install_success_handlers(monkeypatch, calls)

    def fail_analysis(callback):
        calls.append("analyze")
        callback(0, 1, "model request")
        raise RuntimeError("provider unavailable")

    monkeypatch.setitem(
        pipeline_runner.STEP_HANDLERS,
        "analyze",
        fail_analysis,
    )

    run_id, _ = pipeline_runner.enqueue_pipeline("FULL_UPDATE")
    snapshot = _wait_for_terminal(run_id)

    assert calls == ["collect", "analyze"]
    assert snapshot["status"] == "FAILED"
    assert "provider unavailable" in snapshot["error"]
    assert [step["status"] for step in snapshot["steps"]] == [
        "SUCCESS",
        "FAILED",
        "SKIPPED",
        "SKIPPED",
        "SKIPPED",
    ]


def test_second_manual_run_reuses_active_pipeline(session, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    _install_success_handlers(monkeypatch, calls)

    def blocking_collect(callback):
        calls.append("collect")
        callback(0, 1, "waiting")
        started.set()
        assert release.wait(2.0)
        callback(1, 1, "finished")
        return {"processed": 1, "success": 1, "failed": 0}

    monkeypatch.setitem(
        pipeline_runner.STEP_HANDLERS,
        "collect",
        blocking_collect,
    )

    first_id, first_created = pipeline_runner.enqueue_pipeline("INTELLIGENCE")
    assert started.wait(1.0)
    second_id, second_created = pipeline_runner.enqueue_pipeline("MEMORY")
    release.set()
    _wait_for_terminal(first_id)

    assert first_created is True
    assert second_created is False
    assert second_id == first_id
