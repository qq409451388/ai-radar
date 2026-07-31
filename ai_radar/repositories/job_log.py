"""Job execution logger helper (section 七.10)."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.models import JobLog

log = logging.getLogger(__name__)


@contextmanager
def job_log(session: Session, job_type: str) -> Iterator[JobLog]:
    """Context manager that records a JobLog row for a job run."""
    record = JobLog(
        job_type=job_type,
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
        processed_count=0,
        success_count=0,
        failed_count=0,
        message="",
    )
    session.add(record)
    session.flush()
    try:
        yield record
        if record.status == "RUNNING":
            record.status = "SUCCESS"
    except Exception as exc:
        record.status = "FAILED"
        record.message = f"{type(exc).__name__}: {exc}"
        log.exception("Job %s failed", job_type)
        raise
    finally:
        record.finished_at = datetime.now(timezone.utc)
        session.flush()


def recent_jobs(session: Session, limit: int = 50) -> list[JobLog]:
    stmt = select(JobLog).order_by(JobLog.id.desc()).limit(limit)
    return list(session.execute(stmt).scalars())
