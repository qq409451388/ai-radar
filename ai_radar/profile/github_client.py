"""Read-only GitHub Contents API client for the private memory repository.

This client ONLY reads. It never creates, modifies or deletes files (section 四).
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Iterator

import httpx

from ai_radar.config import ProfileConfig, get_config
from ai_radar.utils import sha256_hex

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class RemoteFile:
    path: str
    sha: str
    content: str
    content_hash: str


class GithubContentsClient:
    """Recursive read-only client over a GitHub repository tree."""

    def __init__(self, profile: ProfileConfig | None = None) -> None:
        self.profile = profile or get_config().profile
        if not self.profile.repo:
            raise ValueError("PROFILE_GITHUB_REPO is not configured")
        self._timeout = get_config().http_timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-radar/0.1",
        }
        token = self.profile.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def list_markdown_files(self) -> Iterator[RemoteFile]:
        """Recursively list all .md files under the configured path prefix."""
        prefix = (self.profile.path_prefix or "").strip("/")
        yield from self._walk(self.profile.repo, self.profile.ref, prefix)

    def _walk(self, repo: str, ref: str, path: str) -> Iterator[RemoteFile]:
        url = f"{GITHUB_API}/repos/{repo}/contents/{path}" if path else f"{GITHUB_API}/repos/{repo}/contents"
        params = {"ref": ref}
        try:
            resp = httpx.get(url, headers=self._headers(), params=params, timeout=self._timeout)
        except Exception as exc:  # pragma: no cover - network specific
            raise RuntimeError(f"GitHub contents request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            raise PermissionError(
                f"GitHub API denied access (HTTP {resp.status_code}); check the token scopes"
            )
        if resp.status_code == 404:
            raise FileNotFoundError(f"GitHub path not found: {repo}:{ref}:{path or '/'}")
        if resp.status_code != 200:
            raise RuntimeError(
                f"GitHub contents request failed (HTTP {resp.status_code}): {resp.text[:200]}"
            )

        entries = resp.json()
        # A single file is returned as an object instead of a list.
        if isinstance(entries, dict):
            entries = [entries]

        for entry in entries or []:
            entry_type = entry.get("type")
            entry_path = entry.get("path", "")
            if entry_type == "file" and entry_path.endswith(".md"):
                file_obj = self._fetch_file(entry)
                if file_obj is not None:
                    yield file_obj
            elif entry_type == "dir":
                yield from self._walk(repo, ref, entry_path)

    def _fetch_file(self, entry: dict) -> RemoteFile | None:
        path = entry.get("path", "")
        sha = entry.get("sha", "")
        # Prefer the embedded content if present to avoid a second request.
        encoded = entry.get("content")
        if encoded is None:
            # Fetch the file explicitly.
            url = entry.get("url") or f"{GITHUB_API}/repos/{self.profile.repo}/contents/{path}"
            params = {"ref": self.profile.ref}
            try:
                resp = httpx.get(url, headers=self._headers(), params=params, timeout=self._timeout)
            except Exception as exc:  # pragma: no cover
                log.warning("GithubContentsClient: fetch %s failed: %s", path, exc)
                return None
            if resp.status_code != 200:
                log.warning("GithubContentsClient: fetch %s HTTP %s", path, resp.status_code)
                return None
            data = resp.json()
            encoded = data.get("content", "")
            sha = data.get("sha", sha)
        try:
            content = base64.b64decode(encoded).decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("GithubContentsClient: decode %s failed: %s", path, exc)
            return None
        return RemoteFile(
            path=path,
            sha=sha,
            content=content,
            content_hash=sha256_hex(content),
        )
