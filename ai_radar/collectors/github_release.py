"""GitHub Release collector using the GitHub REST API."""
from __future__ import annotations

import logging
from typing import Iterator

import httpx

from ai_radar.collectors.base import CollectedItem
from ai_radar.config import get_config
from ai_radar.utils import to_utc

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubReleaseCollector:
    """Collects releases for a repository via /repos/{owner}/{repo}/releases."""

    def __init__(self, name: str, repository: str) -> None:
        self.name = name
        self.repository = repository.strip().strip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-radar/0.1",
        }
        token = get_config().github.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def collect(self) -> Iterator[CollectedItem]:
        url = f"{GITHUB_API}/repos/{self.repository}/releases"
        timeout = get_config().http_timeout
        params = {"per_page": 30}
        try:
            resp = httpx.get(
                url, headers=self._headers(), params=params, timeout=timeout, follow_redirects=True
            )
            if resp.status_code == 404:
                log.warning("GitHubRelease[%s] repo not found", self.repository)
                return
            if resp.status_code in (403, 429):
                log.warning(
                    "GitHubRelease[%s] rate limited (HTTP %s)", self.repository, resp.status_code
                )
                return
            resp.raise_for_status()
            releases = resp.json()
        except Exception as exc:  # pragma: no cover - network specific
            log.warning("GitHubRelease[%s] fetch error: %s", self.repository, exc)
            return

        for rel in releases or []:
            try:
                tag = rel.get("tag_name", "") or ""
                name = rel.get("name", "") or tag
                html_url = rel.get("html_url", "") or ""
                body = rel.get("body", "") or ""
                release_id = str(rel.get("id", "")) or f"{self.repository}:{tag}"
                published = rel.get("published_at")
                yield CollectedItem(
                    external_id=release_id,
                    title=f"{name} ({tag})" if tag and tag not in name else name,
                    url=html_url,
                    author=(rel.get("author", {}) or {}).get("login", ""),
                    published_at=to_utc(_parse_iso(published)),
                    content=body,
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("GitHubRelease[%s] entry error: %s", self.repository, exc)
                continue


def _parse_iso(value: str | None):
    if not value:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
