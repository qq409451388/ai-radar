"""Official web-page collector with article-link discovery."""
from __future__ import annotations

import logging
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from ai_radar.collectors.base import CollectedItem
from ai_radar.config import get_config
from ai_radar.utils import sha256_hex, to_utc

log = logging.getLogger(__name__)

MAX_ARTICLES = 20
MAX_CONTENT_CHARS = 12_000


class WebPageCollector:
    """Collect an official page or the newest matching articles linked by it."""

    def __init__(self, name: str, url: str, path_filter: str = "") -> None:
        self.name = name
        self.url = url.strip()
        self.path_filter = path_filter.strip()

    def collect(self):
        headers = {"User-Agent": "ai-radar/0.1 (+official-source-monitor)"}
        timeout = get_config().http_timeout
        try:
            with httpx.Client(
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            ) as client:
                index_response = client.get(self.url)
                index_response.raise_for_status()
                index = _parse_html(index_response.text)
                links = _article_links(
                    self.url,
                    index.links,
                    self.path_filter,
                )
                targets = links[:MAX_ARTICLES] if links else [self.url]
                for target in targets:
                    try:
                        if target == self.url:
                            parsed = index
                        else:
                            response = client.get(target)
                            response.raise_for_status()
                            parsed = _parse_html(response.text)
                        content = parsed.text.strip()[:MAX_CONTENT_CHARS]
                        if not content:
                            continue
                        yield CollectedItem(
                            external_id=sha256_hex(target),
                            title=parsed.title or target,
                            url=target,
                            author=self.name,
                            published_at=to_utc(_parse_datetime(parsed.published_at)),
                            content=content,
                        )
                    except Exception as exc:  # pragma: no cover - network specific
                        log.warning("WebPage[%s] article %s failed: %s", self.name, target, exc)
        except Exception as exc:  # pragma: no cover - network specific
            log.warning("WebPage[%s] fetch error: %s", self.name, exc)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.published_at = ""
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self._title_depth = 0
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag == "time" and values.get("datetime") and not self.published_at:
            self.published_at = values["datetime"]
        if tag == "meta":
            key = values.get("property") or values.get("name") or ""
            if key.lower() in {
                "article:published_time",
                "date",
                "datepublished",
                "publish_date",
            }:
                self.published_at = values.get("content", self.published_at)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._skip_depth:
            return
        if self._title_depth:
            self.title = f"{self.title} {value}".strip()
        self.text_parts.append(value)


class _ParsedPage:
    def __init__(self, parser: _PageParser) -> None:
        self.title = parser.title
        self.published_at = parser.published_at
        self.links = parser.links
        self.text = "\n".join(parser.text_parts)


def _parse_html(html: str) -> _ParsedPage:
    parser = _PageParser()
    parser.feed(html)
    return _ParsedPage(parser)


def _article_links(index_url: str, links: list[str], path_filter: str) -> list[str]:
    index_host = urlparse(index_url).netloc.lower()
    seen: set[str] = set()
    results: list[str] = []
    for raw in links:
        absolute = urljoin(index_url, raw)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() != index_host:
            continue
        normalized = urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
        )
        if path_filter and path_filter not in parsed.path:
            continue
        if normalized.rstrip("/") == index_url.rstrip("/") or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
    return results


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return None
