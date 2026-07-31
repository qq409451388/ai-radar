"""Tests for profile fact extraction & coverage validation
(section 二十: 7, 8, 10, 11).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from ai_radar.bootstrap import (
    COVERAGE_NONE,
    COVERAGE_PRACTICED,
    COVERAGE_COEFFICIENTS,
    seed_default_data,
)
from ai_radar.llm.schemas import CoverageAssessment, ProfileFactExtraction, ProfileFactItem
from ai_radar.models import (
    ChangePoint,
    KnowledgeCoverage,
    ProfileFact,
    ProfileSourceFile,
    Topic,
)
from ai_radar.profile.fact_service import FactService
from ai_radar.profile.github_client import RemoteFile
from ai_radar.profile.sync_service import ProfileSyncService
from ai_radar.services.coverage_service import CoverageService


def _remote(path="mem.md", sha="sha1", content="# title\n- a fact"):
    from ai_radar.utils import sha256_hex

    return RemoteFile(path=path, sha=sha, content=content, content_hash=sha256_hex(content))


# --- Test 7: SHA unchanged → no re-extraction ---

def test_sha_unchanged_no_reextract(session, monkeypatch):
    seed_default_data(session)
    from ai_radar.config import ProfileConfig, get_config

    profile = ProfileConfig(
        repo="o/mem",
        ref="main",
        path_prefix="",
        token="",
    )
    monkeypatch.setattr(get_config(), "profile", profile, raising=False)

    calls = {"extract": 0}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def list_markdown_files(self):
            yield _remote()

    class FakeLlm:
        def extract_profile_facts(self, file_path, markdown):
            calls["extract"] += 1
            return ProfileFactExtraction(
                facts=[
                    ProfileFactItem(
                        fact_key="k1",
                        fact_text="a fact",
                        topic="MCP / Tools / Skills",
                        evidence_type="DISCUSSION",
                        source_heading="title",
                        source_line_start=2,
                        source_line_end=2,
                    )
                ]
            )

    svc = ProfileSyncService(session, client=FakeClient())  # type: ignore[arg-type]
    result = svc.sync()
    f = list(session.execute(select(ProfileSourceFile)).scalars())[0]

    fact_svc = FactService(session, FakeLlm(), client=FakeClient())  # type: ignore[arg-type]
    # First explicit extraction populates facts + records content_hash.
    fact_svc.extract_for_file(f.id, force=True)
    assert calls["extract"] == 1

    # Re-extract without force: content_hash unchanged → LLM NOT called again.
    fact_svc.extract_for_file(f.id, force=False)
    assert calls["extract"] == 1  # still only one extraction


# --- Test 8: facts persisted to DB ---

def test_facts_persisted(session, monkeypatch):
    seed_default_data(session)
    from ai_radar.config import ProfileConfig, get_config

    profile = ProfileConfig(repo="o/mem", ref="main", path_prefix="", token="")
    monkeypatch.setattr(get_config(), "profile", profile, raising=False)

    class FakeClient:
        def list_markdown_files(self):
            yield _remote()

    class FakeLlm:
        def extract_profile_facts(self, file_path, markdown):
            return ProfileFactExtraction(
                facts=[
                    ProfileFactItem(
                        fact_key="design-x",
                        fact_text="设计过 X",
                        topic="MCP / Tools / Skills",
                        evidence_type="DESIGN",
                        source_heading="## MCP",
                        source_line_start=3,
                        source_line_end=3,
                    )
                ]
            )

    ProfileSyncService(session, client=FakeClient()).sync()  # type: ignore[arg-type]
    f = list(session.execute(select(ProfileSourceFile)).scalars())[0]
    FactService(session, FakeLlm(), client=FakeClient()).extract_for_file(f.id, force=True)  # type: ignore[arg-type]

    facts = list(
        session.execute(
            select(ProfileFact).where(ProfileFact.source_file_id == f.id, ProfileFact.active == True)  # noqa: E712
        ).scalars()
    )
    assert len(facts) == 1
    assert facts[0].fact_key == "design-x"
    assert facts[0].evidence_type == "DESIGN"


# --- Test 10: matched_fact_keys non-existent are rejected ---

def test_matched_fact_keys_nonexistent_rejected(session, monkeypatch):
    seed_default_data(session)
    from ai_radar.config import ProfileConfig, get_config

    monkeypatch.setattr(get_config(), "profile", ProfileConfig("o/mem", "main", "", ""), raising=False)

    topic = session.execute(select(Topic).where(Topic.name == "MCP / Tools / Skills")).scalar_one()
    cp = ChangePoint(
        topic_id=topic.id,
        event_key="mcp.x",
        title="t",
        summary="s",
        why_it_matters="w",
        importance=3,
        status="ACTIVE",
    )
    session.add(cp)
    session.flush()

    # Provide one real fact
    sf = ProfileSourceFile(repository="o/mem", ref="main", file_path="m.md", sync_status="SUCCESS")
    session.add(sf)
    session.flush()
    fact = ProfileFact(
        source_file_id=sf.id,
        fact_key="real-fact",
        fact_text="real",
        topic_id=topic.id,
        evidence_type="DISCUSSION",
        active=True,
    )
    session.add(fact)
    session.flush()

    class FakeLlm:
        model = "fake"

        def assess_coverage(self, payload):
            # Model hallucinates a key that does not exist.
            return CoverageAssessment(
                coverage_level="UNDERSTOOD",
                coverage_coefficient=0.65,
                confidence=0.5,
                rationale="ok",
                matched_fact_keys=["real-fact", "does-not-exist"],
            )

    cov = CoverageService(session, FakeLlm()).assess_one(cp.id)  # type: ignore[arg-type]
    from ai_radar.utils import load_json

    matched = load_json(cov.matched_fact_ids_json)
    # The non-existent key is dropped, only the real fact id is kept.
    assert "does-not-exist" not in matched
    assert fact.id in matched


# --- Test 11: profile sync failure preserves previous facts ---

def test_sync_failure_preserves_facts(session, monkeypatch):
    seed_default_data(session)
    from ai_radar.config import ProfileConfig, get_config

    monkeypatch.setattr(get_config(), "profile", ProfileConfig("o/mem", "main", "", ""), raising=False)

    class GoodClient:
        def list_markdown_files(self):
            yield _remote()

    class BadClient:
        def list_markdown_files(self):
            raise RuntimeError("network down")

    class FakeLlm:
        def extract_profile_facts(self, file_path, markdown):
            return ProfileFactExtraction(
                facts=[
                    ProfileFactItem(
                        fact_key="k1",
                        fact_text="fact",
                        topic="MCP / Tools / Skills",
                        evidence_type="DISCUSSION",
                        source_heading="h",
                        source_line_start=1,
                        source_line_end=1,
                    )
                ]
            )

    # First sync succeeds.
    ProfileSyncService(session, client=GoodClient()).sync()  # type: ignore[arg-type]
    f = list(session.execute(select(ProfileSourceFile)).scalars())[0]
    FactService(session, FakeLlm(), client=GoodClient()).extract_for_file(f.id, force=True)  # type: ignore[arg-type]
    before = list(session.execute(select(ProfileFact)).scalars())
    assert len(before) == 1

    # Second sync fails — must not delete existing facts.
    ProfileSyncService(session, client=BadClient()).sync()  # type: ignore[arg-type]
    after = list(session.execute(select(ProfileFact)).scalars())
    assert len(after) == 1
    assert after[0].fact_key == "k1"


def test_failed_extraction_is_retried_on_unchanged_remote(session, monkeypatch):
    """Fetched hash and extracted hash must advance independently."""
    seed_default_data(session)
    from ai_radar.config import ProfileConfig, get_config

    monkeypatch.setattr(
        get_config(), "profile", ProfileConfig("o/mem", "main", "", ""), raising=False
    )

    class FakeClient:
        def list_markdown_files(self):
            yield _remote()

    first = ProfileSyncService(session, client=FakeClient()).sync()  # type: ignore[arg-type]
    row = list(session.execute(select(ProfileSourceFile)).scalars())[0]
    assert len(first["changed_files"]) == 1
    assert row.extraction_status == "PENDING"

    # Simulate an LLM failure after the file was fetched.
    row.extraction_status = "FAILED"
    row.extraction_error = "model timeout"
    row.extracted_content_hash = ""
    session.flush()

    second = ProfileSyncService(session, client=FakeClient()).sync()  # type: ignore[arg-type]
    assert len(second["changed_files"]) == 1
    assert second["changed_files"][0][0].id == row.id


def test_coverage_history_and_evidence_cap(session):
    seed_default_data(session)
    topic = session.execute(
        select(Topic).where(Topic.name == "MCP / Tools / Skills")
    ).scalar_one()
    cp = ChangePoint(
        topic_id=topic.id,
        event_key="mcp.history",
        title="MCP change",
        summary="new protocol",
        why_it_matters="important",
        importance=3,
        status="ACTIVE",
    )
    session.add(cp)
    sf = ProfileSourceFile(
        repository="o/mem",
        ref="main",
        file_path="m.md",
        sync_status="SUCCESS",
        extraction_status="SUCCESS",
    )
    session.add(sf)
    session.flush()
    fact = ProfileFact(
        source_file_id=sf.id,
        fact_key="discussion-only",
        fact_text="讨论过 MCP 协议",
        topic_id=topic.id,
        evidence_type="DISCUSSION",
        active=True,
    )
    session.add(fact)
    session.flush()

    class FakeLlm:
        model = "fake"

        def assess_coverage(self, payload):
            return CoverageAssessment(
                coverage_level="PRACTICED",
                coverage_coefficient=1.0,
                confidence=0.8,
                rationale="claimed practiced",
                matched_fact_keys=["discussion-only"],
            )

    service = CoverageService(session, FakeLlm())  # type: ignore[arg-type]
    first = service.assess_one(cp.id)
    second = service.assess_one(cp.id)
    assert first.coverage_level == "AWARE"
    assert second.coverage_level == "AWARE"
    history = list(
        session.execute(
            select(KnowledgeCoverage).where(
                KnowledgeCoverage.change_point_id == cp.id
            )
        ).scalars()
    )
    assert len(history) == 2
