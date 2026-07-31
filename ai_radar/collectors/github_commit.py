"""GitHub commit collector for watched specification and documentation paths."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from ai_radar.collectors.base import CollectedItem
from ai_radar.config import get_config
from ai_radar.utils import to_utc

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
MAX_COMMITS = 12
MAX_PATCH_CHARS = 8_000


class GitHubCommitCollector:
    def __init__(self, name: str, repository: str, path_filter: str = "") -> None:
        self.name = name
        self.repository = repository.strip().strip("/")
        self.path_filter = path_filter.strip().strip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-radar/0.1",
        }
        token = get_config().github.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def collect(self):
        timeout = get_config().http_timeout
        params: dict[str, str | int] = {"per_page": MAX_COMMITS}
        if self.path_filter:
            params["path"] = self.path_filter
        try:
            response = httpx.get(
                f"{GITHUB_API}/repos/{self.repository}/commits",
                headers=self._headers(),
                params=params,
                timeout=timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            commits = response.json()
        except Exception as exc:  # pragma: no cover - network specific
            log.warning("GitHubCommit[%s] list error: %s", self.repository, exc)
            return

        for row in commits or []:
            sha = str(row.get("sha") or "")
            if not sha:
                continue
            commit = row.get("commit") or {}
            message = str(commit.get("message") or "").strip()
            author_data = commit.get("author") or {}
            content = message
            try:
                detail = httpx.get(
                    f"{GITHUB_API}/repos/{self.repository}/commits/{sha}",
                    headers=self._headers(),
                    timeout=timeout,
                    follow_redirects=True,
                )
                detail.raise_for_status()
                files = detail.json().get("files") or []
                patches: list[str] = []
                for file in files:
                    filename = str(file.get("filename") or "")
                    if self.path_filter and not filename.startswith(self.path_filter):
                        continue
                    patch = str(file.get("patch") or "")
                    patches.append(
                        f"文件：{filename}\n状态：{file.get('status', '')}\n{patch}"
                    )
                if patches:
                    content = f"{message}\n\n" + "\n\n".join(patches)
            except Exception as exc:  # pragma: no cover - network specific
                log.warning(
                    "GitHubCommit[%s] detail %s failed: %s",
                    self.repository,
                    sha[:10],
                    exc,
                )

            yield CollectedItem(
                external_id=sha,
                title=message.splitlines()[0][:512] if message else sha[:12],
                url=str(row.get("html_url") or ""),
                author=str(author_data.get("name") or ""),
                published_at=to_utc(_parse_iso(author_data.get("date"))),
                content=content[:MAX_PATCH_CHARS],
            )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
