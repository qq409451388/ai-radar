"""APScheduler setup (section 十八).

A single BackgroundScheduler is created lazily and guarded so Streamlit reloads
do not start multiple schedulers. Each job is wrapped so a single task failure
cannot stop the scheduler.
"""
from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ai_radar.config import get_config

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    with _lock:
        if _scheduler is None:
            tz = get_config().timezone
            sched = BackgroundScheduler(timezone=tz)
            if get_config().scheduler_enabled:
                _register_jobs(sched)
            _scheduler = sched
    return _scheduler


def _register_jobs(sched: BackgroundScheduler) -> None:
    tz = get_config().timezone
    # 08:00 collect + analyze (analyze runs after collect within the wrapper).
    sched.add_job(
        _safe("daily_morning_pipeline"),
        CronTrigger(hour=8, minute=0, timezone=tz),
        id="daily_morning_pipeline",
        replace_existing=True,
        max_instances=1,
    )
    # 09:00 sync GitHub memory (which triggers fact re-extraction + re-assess).
    sched.add_job(
        _safe("sync_profile"),
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="sync_profile",
        replace_existing=True,
        max_instances=1,
    )
    # 23:00 assess new change points + save daily snapshot.
    sched.add_job(
        _safe("daily_evening_pipeline"),
        CronTrigger(hour=23, minute=0, timezone=tz),
        id="daily_evening_pipeline",
        replace_existing=True,
        max_instances=1,
    )


def _safe(name: str):
    def _run():
        try:
            from ai_radar import orchestrator

            fn = getattr(orchestrator, name)
            log.info("scheduler job %s started", name)
            fn()
            log.info("scheduler job %s finished", name)
        except Exception:
            log.exception("scheduler job %s failed", name)

    _run.__name__ = f"_safe_{name}"
    return _run


def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        log.info("scheduler started")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
