"""Collection service: runs collectors and persists deduplicated source items."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import (
    SOURCE_TYPE_GITHUB_COMMIT,
    SOURCE_TYPE_GITHUB_RELEASE,
    SOURCE_TYPE_RSS,
    SOURCE_TYPE_WEB_PAGE,
)
from ai_radar.collectors.github_commit import GitHubCommitCollector
from ai_radar.collectors.github_release import GitHubReleaseCollector
from ai_radar.collectors.rss import RSSCollector
from ai_radar.collectors.web_page import WebPageCollector
from ai_radar.models import SourceConfig, SourceItem
from ai_radar.repositories.job_log import job_log
from ai_radar.utils import sha256_hex

log = logging.getLogger(__name__)


class CollectionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def collect_all(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        configs = list(
            self.session.execute(
                select(SourceConfig).where(SourceConfig.enabled == True)  # noqa: E712
            ).scalars()
        )
        total_new = 0
        total_seen = 0
        failed_sources = 0
        if progress_callback:
            progress_callback(0, len(configs), "准备采集已启用的资讯源")
        with job_log(self.session, "collect_sources") as jl:
            for index, cfg in enumerate(configs, start=1):
                if progress_callback:
                    progress_callback(
                        index - 1,
                        len(configs),
                        f"正在采集 {cfg.name}",
                    )
                try:
                    new, seen = self._collect_one(cfg)
                    total_new += new
                    total_seen += seen
                    cfg.last_error = ""
                except Exception as exc:
                    cfg.last_error = f"{type(exc).__name__}: {exc}"
                    failed_sources += 1
                    log.warning("collect source %s failed: %s", cfg.name, exc)
                cfg.last_collected_at = datetime.now(timezone.utc)
                jl.processed_count += 1
                if progress_callback:
                    progress_callback(
                        index,
                        len(configs),
                        f"已完成 {index}/{len(configs)} 个资讯源",
                    )
            jl.success_count = total_new
            jl.failed_count = failed_sources
            jl.message = f"collected {total_new} new / {total_seen} seen from {len(configs)} sources"
        return {
            "new": total_new,
            "seen": total_seen,
            "sources": len(configs),
            "failed_sources": failed_sources,
        }

    def collect_one(self, source_config_id: int) -> dict:
        cfg = self.session.get(SourceConfig, source_config_id)
        if cfg is None:
            raise ValueError(f"source_config {source_config_id} not found")
        new, seen = self._collect_one(cfg)
        cfg.last_collected_at = datetime.now(timezone.utc)
        cfg.last_error = ""
        return {"new": new, "seen": seen, "source": cfg.name}

    def _collect_one(self, cfg: SourceConfig) -> tuple[int, int]:
        if cfg.source_type == SOURCE_TYPE_RSS:
            collector = RSSCollector(cfg.name, cfg.url)
        elif cfg.source_type == SOURCE_TYPE_WEB_PAGE:
            collector = WebPageCollector(cfg.name, cfg.url, cfg.path_filter)
        elif cfg.source_type == SOURCE_TYPE_GITHUB_RELEASE:
            repo = cfg.repository or _repo_from_url(cfg.url)
            collector = GitHubReleaseCollector(cfg.name, repo)
        elif cfg.source_type == SOURCE_TYPE_GITHUB_COMMIT:
            repo = cfg.repository or _repo_from_url(cfg.url)
            collector = GitHubCommitCollector(
                cfg.name,
                repo,
                cfg.path_filter,
            )
        else:
            log.warning("unknown source_type %s for %s", cfg.source_type, cfg.name)
            return 0, 0

        new = 0
        seen = 0
        for item in collector.collect():
            seen += 1
            if self._upsert_item(cfg.id, item):
                new += 1
        return new, seen

    def _upsert_item(self, source_config_id: int, item) -> bool:
        """Insert a new item if not already present. Returns True if inserted."""
        external_id = item.external_id
        existing = self.session.execute(
            select(SourceItem).where(
                SourceItem.source_config_id == source_config_id,
                SourceItem.external_id == external_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Update content_hash/published only if changed; never re-analyze the
            # same item (section 七.3).
            new_hash = item.content_hash
            if existing.content_hash != new_hash:
                existing.content_hash = new_hash
                existing.raw_content = item.content
                existing.title = item.title
                existing.url = item.url
                existing.author = item.author
                existing.published_at = item.published_at
                # Updated release notes/news may contain materially new facts.
                existing.analyze_status = "PENDING"
                existing.analyze_error = ""
                existing.retry_count = 0
                existing.next_retry_at = None
            return False

        new_item = SourceItem(
            source_config_id=source_config_id,
            external_id=external_id,
            title=item.title,
            url=item.url,
            author=item.author,
            published_at=item.published_at,
            raw_content=item.content,
            content_hash=item.content_hash or sha256_hex(item.content),
            analyze_status="PENDING",
        )
        self.session.add(new_item)
        self.session.flush()
        return True


def _repo_from_url(url: str) -> str:
    """Extract owner/repo from a github URL like https://github.com/openai/codex."""
    url = url.strip().rstrip("/")
    if url.startswith("https://github.com/"):
        return url[len("https://github.com/"):]
    return url
