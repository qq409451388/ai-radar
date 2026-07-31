"""Persistent LLM cache and usage ledger."""
from __future__ import annotations

from sqlalchemy import func, select

from ai_radar.llm.client import LlmClient
from ai_radar.models import LlmResponseCache, LlmUsageLog


def test_structured_response_is_cached(session, monkeypatch):
    first = LlmClient(session)
    calls = {"count": 0}

    def fake_chat(prompt):
        calls["count"] += 1
        return (
            '{"facts":[{"fact_key":"k","fact_text":"实现过工具",'
            '"topic":"MCP / Tools / Skills","occurred_at":null,'
            '"evidence_type":"IMPLEMENTATION","source_heading":"h",'
            '"source_line_start":1,"source_line_end":1}]}',
            {"prompt_tokens": 120, "completion_tokens": 40},
        )

    monkeypatch.setattr(first, "_chat", fake_chat)
    result1 = first.extract_profile_facts("memory.md", "# memory")
    assert result1.facts[0].fact_key == "k"

    second = LlmClient(session)

    def should_not_call(prompt):  # pragma: no cover - assertion path
        raise AssertionError("cache miss")

    monkeypatch.setattr(second, "_chat", should_not_call)
    result2 = second.extract_profile_facts("memory.md", "# memory")
    assert result2.facts[0].fact_key == "k"
    assert calls["count"] == 1
    assert session.scalar(select(func.count(LlmResponseCache.id))) == 1
    usage = list(session.execute(select(LlmUsageLog)).scalars())
    assert len(usage) == 2
    assert usage[1].cache_hit is True
