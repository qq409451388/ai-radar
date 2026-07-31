"""Profile fact extraction service (section 十四 / 十六).

Extracts objective facts from synced Markdown files via the LLM. Only re-runs
when a file's content has changed. Facts that disappear are marked inactive
(not physically deleted). Dedup is performed on (source_file_id, fact_key) and
text similarity.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import EVIDENCE_TYPES
from ai_radar.llm.client import LlmClient, LlmError
from ai_radar.models import ProfileFact, ProfileSourceFile, Topic
from ai_radar.repositories.job_log import job_log

log = logging.getLogger(__name__)

FACT_TEXT_SIMILARITY = 0.85


class FactService:
    def __init__(
        self,
        session: Session,
        llm: LlmClient | None = None,
        client=None,
    ) -> None:
        self.session = session
        self.llm = llm or LlmClient(session)
        self._client = client  # optional injected GithubContentsClient for re-fetch

    def extract_all(self, force: bool = False) -> dict:
        stmt = select(ProfileSourceFile).where(ProfileSourceFile.sync_status == "SUCCESS")
        files = list(self.session.execute(stmt).scalars())
        total = 0
        with job_log(self.session, "extract_facts") as jl:
            for f in files:
                jl.processed_count += 1
                try:
                    self._extract_for_file(f, force=force)
                    jl.success_count += 1
                    total += 1
                except LlmError as exc:
                    jl.failed_count += 1
                    log.warning("extract facts for %s failed: %s", f.file_path, exc)
                except Exception as exc:
                    jl.failed_count += 1
                    log.exception("extract facts for %s errored", f.file_path)
            jl.message = f"processed {len(files)} files, {total} ok"
        return {"files": len(files), "ok": total}

    def extract_for_file(self, source_file_id: int, force: bool = False) -> dict:
        f = self.session.get(ProfileSourceFile, source_file_id)
        if f is None:
            raise ValueError(f"profile_source_file {source_file_id} not found")
        affected = self._extract_for_file(f, force=force)
        return {"file": f.file_path, "affected_topic_ids": sorted(affected)}

    def extract_with_content(
        self, source_file_id: int, content: str, content_hash: str, force: bool = False
    ) -> dict:
        """Extract facts using content already fetched by the sync service.

        Skips the LLM call when content_hash matches the stored hash and
        force=False (section 十六).
        """
        f = self.session.get(ProfileSourceFile, source_file_id)
        if f is None:
            raise ValueError(f"profile_source_file {source_file_id} not found")
        affected = self._extract_for_file(
            f, force=force, content=content, content_hash=content_hash
        )
        return {"file": f.file_path, "affected_topic_ids": sorted(affected)}

    def _extract_for_file(
        self,
        f: ProfileSourceFile,
        force: bool = False,
        content: str | None = None,
        content_hash: str | None = None,
    ) -> set[int]:
        if not f.content_hash and content_hash is None:
            return set()

        if content is None:
            # Re-fetch current content via the read-only GitHub client.
            from ai_radar.profile.github_client import GithubContentsClient
            from ai_radar.config import get_config

            cfg = get_config().profile
            try:
                client = self._client or GithubContentsClient(cfg)
                remote = next(
                    (rf for rf in client.list_markdown_files() if rf.path == f.file_path),
                    None,
                )
            except Exception as exc:
                log.warning("re-fetch %s failed: %s", f.file_path, exc)
                f.extraction_status = "FAILED"
                f.extraction_error = str(exc)
                return set()
            if remote is None:
                affected = self._mark_all_inactive(f.id)
                f.extraction_status = "FAILED"
                f.extraction_error = "file no longer exists in remote repository"
                return affected
            content = remote.content
            content_hash = remote.content_hash
            f.github_sha = remote.sha

        if content_hash is None:
            from ai_radar.utils import sha256_hex

            content_hash = sha256_hex(content or "")

        # SHA-skip: do not re-extract when content unchanged.
        if (
            not force
            and f.extracted_content_hash
            and content_hash == f.extracted_content_hash
            and f.extraction_status == "SUCCESS"
        ):
            return set()

        f.content_hash = content_hash
        f.extraction_status = "PENDING"
        f.extraction_error = ""
        markdown = content or ""
        existing_facts = list(
            self.session.execute(
                select(ProfileFact).where(ProfileFact.source_file_id == f.id)
            ).scalars()
        )
        affected_topic_ids = {fact.topic_id for fact in existing_facts if fact.topic_id}

        try:
            extraction = self.llm.extract_profile_facts(f.file_path, markdown)
        except LlmError as exc:
            # Keep existing facts on extraction failure (section 十六).
            f.extraction_status = "FAILED"
            f.extraction_error = str(exc)
            raise

        new_keys: set[str] = set()
        for item in extraction.facts:
            fact_key = item.fact_key or _derive_key(item)
            if not fact_key:
                continue
            if item.evidence_type not in EVIDENCE_TYPES:
                continue
            new_keys.add(fact_key)
            topic_id = self._resolve_topic_id(item.topic, item.fact_text)
            if topic_id:
                affected_topic_ids.add(topic_id)
            occurred_at = _parse_date(item.occurred_at)
            self._upsert_fact(
                existing_facts=existing_facts,
                source_file_id=f.id,
                fact_key=fact_key,
                fact_text=item.fact_text,
                topic_id=topic_id,
                occurred_at=occurred_at,
                evidence_type=item.evidence_type,
                source_heading=item.source_heading,
                source_line_start=item.source_line_start,
                source_line_end=item.source_line_end,
            )

        # Mark facts no longer present as inactive.
        for fact in existing_facts:
            if fact.fact_key not in new_keys and fact.active:
                fact.active = False
        f.extracted_content_hash = content_hash
        f.extraction_status = "SUCCESS"
        f.extraction_error = ""
        f.last_extracted_at = datetime.now(timezone.utc)
        self.session.flush()
        return affected_topic_ids

    def _upsert_fact(self, **kw) -> None:
        existing_facts: list[ProfileFact] = kw["existing_facts"]
        fact_key = kw["fact_key"]
        source_file_id = kw["source_file_id"]
        topic_id = kw["topic_id"]
        fact_text = kw["fact_text"]

        match = None
        for f in existing_facts:
            if f.fact_key == fact_key:
                match = f
                break
            # Text-similarity dedup
            if f.fact_text and SequenceMatcher(None, f.fact_text.lower(), fact_text.lower()).ratio() >= FACT_TEXT_SIMILARITY:
                match = f
                break

        if match is None:
            match = ProfileFact(source_file_id=source_file_id, fact_key=fact_key)
            self.session.add(match)
            existing_facts.append(match)
        match.fact_text = fact_text
        match.topic_id = topic_id
        match.occurred_at = kw["occurred_at"]
        match.evidence_type = kw["evidence_type"]
        match.source_heading = kw["source_heading"]
        match.source_line_start = kw["source_line_start"]
        match.source_line_end = kw["source_line_end"]
        match.active = True
        match.extracted_at = datetime.now(timezone.utc)

    def _mark_all_inactive(self, source_file_id: int) -> set[int]:
        facts = list(
            self.session.execute(
                select(ProfileFact).where(
                    ProfileFact.source_file_id == source_file_id,
                    ProfileFact.active == True,  # noqa: E712
                )
            ).scalars()
        )
        for f in facts:
            f.active = False
        return {f.topic_id for f in facts if f.topic_id}

    def _resolve_topic_id(
        self, topic_name: str | None, fact_text: str = ""
    ) -> int | None:
        topics = list(self.session.execute(select(Topic).where(Topic.enabled == True)).scalars())  # noqa: E712
        if topic_name:
            exact = next((topic for topic in topics if topic.name == topic_name), None)
            if exact:
                return exact.id
            fuzzy = max(
                topics,
                key=lambda topic: SequenceMatcher(
                    None, topic.name.lower(), topic_name.lower()
                ).ratio(),
                default=None,
            )
            if fuzzy and SequenceMatcher(
                None, fuzzy.name.lower(), topic_name.lower()
            ).ratio() >= 0.55:
                return fuzzy.id

        text = f"{topic_name or ''} {fact_text}".lower()
        keyword_groups = [
            ("MCP / Tools / Skills", ("mcp", "tool", "skill", "工具")),
            ("Coding Agent 与 CLI", ("codex", "claude code", "cli", "编码代理")),
            ("Java AI 生态", ("spring ai", "langchain4j", "java")),
            ("Memory / 个人知识库", ("memory", "记忆", "知识库")),
            ("AI 安全、评测与可观测性", ("评测", "安全", "观测", "guardrail")),
            ("模型能力与模型路由", ("模型", "路由", "token", "上下文")),
            ("企业 AI 落地", ("生产", "企业", "rag", "落地")),
            ("Agent 架构与编排", ("agent", "代理", "编排", "多 agent")),
        ]
        for name, keywords in keyword_groups:
            if any(keyword in text for keyword in keywords):
                match = next((topic for topic in topics if topic.name == name), None)
                if match:
                    return match.id
        return None


def _derive_key(item) -> str | None:
    text = (item.fact_text or "").strip().lower().replace(" ", "-")[:60]
    return text or None


def _parse_date(value: str | None):
    if not value:
        return None
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
