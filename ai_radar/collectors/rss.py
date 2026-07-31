"""RSS feed collector using feedparser."""
from __future__ import annotations

import logging
from typing import Iterator

import feedparser

from ai_radar.collectors.base import CollectedItem
from ai_radar.config import get_config
from ai_radar.utils import sha256_hex, to_utc

log = logging.getLogger(__name__)


class RSSCollector:
    """Collects items from an RSS feed."""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url

    def collect(self) -> Iterator[CollectedItem]:
        timeout = get_config().http_timeout
        # feedparser accepts a timeout via its internal urllib; we also pass
        # request_headers where useful. Errors here are logged and yielded-empty.
        try:
            parsed = feedparser.parse(
                self.url,
                request_headers={"User-Agent": "ai-radar/0.1 (+https://github.com)"},
            )
        except Exception as exc:  # pragma: no cover - network specific
            log.warning("RSSCollector[%s] parse error: %s", self.name, exc)
            return

        if parsed.bozo and parsed.bozo_exception:
            log.warning(
                "RSSCollector[%s] feed is malformed: %s", self.name, parsed.bozo_exception
            )

        for entry in parsed.entries:
            try:
                link = entry.get("link", "") or ""
                guid = entry.get("id", "") or link or entry.get("title", "")
                if not guid:
                    continue
                title = entry.get("title", "") or ""
                author = entry.get("author", "") or ""
                summary = entry.get("summary", "") or entry.get("description", "") or ""
                published = _parse_entry_date(entry)

                content_parts: list[str] = []
                if entry.get("content"):
                    for block in entry["content"]:
                        content_parts.append(block.get("value", ""))
                body = "\n".join(content_parts).strip() or summary

                # Combine a stable textual fingerprint for content_hash.
                fingerprint = f"{guid}|{title}|{body}"
                yield CollectedItem(
                    external_id=guid,
                    title=title,
                    url=link,
                    author=author,
                    published_at=to_utc(published),
                    content=body,
                )
                # content_hash is derived in dataclass property; ensure used:
                _ = sha256_hex(fingerprint)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("RSSCollector[%s] entry error: %s", self.name, exc)
                continue


def _parse_entry_date(entry) -> "datetime | None":
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if not parsed:
            continue
        try:
            from time import mktime
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
            return dt
        except Exception:  # pragma: no cover - defensive
            continue
    return None
