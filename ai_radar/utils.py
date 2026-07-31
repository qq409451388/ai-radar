"""Shared utilities: hashing, timezone conversion, JSON helpers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ai_radar.config import get_config


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def to_utc(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to UTC-aware. None passes through."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_to_local(dt: datetime | None, tz_name: str | None = None) -> datetime | None:
    """Convert a UTC datetime to the configured local timezone."""
    if dt is None:
        return None
    tz = ZoneInfo(tz_name or get_config().timezone)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def local_today(tz_name: str | None = None) -> datetime:
    """Return today's date at 00:00 in local time, as an aware UTC datetime."""
    tz = ZoneInfo(tz_name or get_config().timezone)
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def load_json(value: str | None, default=None):
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else []
