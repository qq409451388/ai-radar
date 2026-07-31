"""GitHub memory repository synchronization service (section 四 / 十六).

Read-only sync: fetches .md files via the Contents API, records SHA/content
hashes, and only triggers fact re-extraction when a file actually changes.
On sync failure the previous facts are preserved (section 四 requirement).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.config import get_config
from ai_radar.models import ProfileSourceFile
from ai_radar.profile.github_client import GithubContentsClient, RemoteFile
from ai_radar.repositories.job_log import job_log

log = logging.getLogger(__name__)


class ProfileSyncService:
    def __init__(self, session: Session, client: GithubContentsClient | None = None) -> None:
        self.session = session
        self.client = client

    def sync(self) -> dict:
        config = get_config().profile
        if not config.repo:
            return {"error": "PROFILE_GITHUB_REPO not configured", "synced": 0, "changed": 0}

        with job_log(self.session, "sync_profile") as jl:
            try:
                client = self.client or GithubContentsClient(config)
                remote_files = list(client.list_markdown_files())
            except Exception as exc:
                jl.status = "FAILED"
                jl.failed_count = 1
                jl.message = f"sync failed: {exc}"
                # Preserve previous data — do NOT touch existing rows on failure.
                return {"error": str(exc), "synced": 0, "changed": 0}

            seen_paths: set[str] = {f.path for f in remote_files}
            changed_files: list[tuple[ProfileSourceFile, RemoteFile]] = []

            for remote in remote_files:
                row = self.session.execute(
                    select(ProfileSourceFile).where(
                        ProfileSourceFile.repository == config.repo,
                        ProfileSourceFile.file_path == remote.path,
                    )
                ).scalar_one_or_none()

                now = datetime.now(timezone.utc)
                if row is None:
                    row = ProfileSourceFile(
                        repository=config.repo,
                        ref=config.ref,
                        file_path=remote.path,
                        github_sha=remote.sha,
                        content_hash=remote.content_hash,
                        extracted_content_hash="",
                        last_fetched_at=now,
                        last_success_at=now,
                        sync_status="SUCCESS",
                        sync_error="",
                        extraction_status="PENDING",
                        extraction_error="",
                    )
                    self.session.add(row)
                    self.session.flush()
                    changed_files.append((row, remote))
                else:
                    row.last_fetched_at = now
                    row.ref = config.ref
                    if row.github_sha == remote.sha and row.content_hash == remote.content_hash:
                        # Unchanged — refresh success timestamp only.
                        row.last_success_at = now
                        row.sync_status = "SUCCESS"
                        row.sync_error = ""
                        if (
                            row.extraction_status != "SUCCESS"
                            or row.extracted_content_hash != remote.content_hash
                        ):
                            row.extraction_status = "PENDING"
                            changed_files.append((row, remote))
                    else:
                        row.github_sha = remote.sha
                        row.content_hash = remote.content_hash
                        row.last_success_at = now
                        row.sync_status = "SUCCESS"
                        row.sync_error = ""
                        row.extraction_status = "PENDING"
                        row.extraction_error = ""
                        changed_files.append((row, remote))

            # Mark files that disappeared from the repo as FAILED-stale so the
            # page can surface them, but keep their existing facts.
            stale = self.session.execute(
                select(ProfileSourceFile).where(
                    ProfileSourceFile.repository == config.repo,
                )
            ).scalars()
            for row in stale:
                if row.file_path not in seen_paths and row.sync_status == "SUCCESS":
                    row.sync_status = "FAILED"
                    row.sync_error = "file no longer exists in remote repository"
                    row.last_fetched_at = datetime.now(timezone.utc)

            jl.success_count = len(remote_files)
            jl.processed_count = len(remote_files)
            jl.message = f"synced {len(remote_files)} files, {len(changed_files)} changed"
        return {
            "synced": len(remote_files),
            "changed": len(changed_files),
            "changed_files": changed_files,
        }

    def last_success_time(self) -> datetime | None:
        stmt = (
            select(ProfileSourceFile.last_success_at)
            .where(ProfileSourceFile.sync_status == "SUCCESS")
            .order_by(ProfileSourceFile.last_success_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar()

    def last_error(self) -> str:
        stmt = (
            select(ProfileSourceFile.sync_error)
            .where(ProfileSourceFile.sync_status == "FAILED")
            .order_by(ProfileSourceFile.last_fetched_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar() or ""
