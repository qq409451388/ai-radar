"""Tolerance rules for common structured-output variations."""
from __future__ import annotations

import pytest

from ai_radar.llm.schemas import ChangePointAnalysis
from ai_radar.llm.prompts import render_analyze


def test_minimal_irrelevant_change_point_output_is_valid():
    result = ChangePointAnalysis.model_validate(
        {"relevant": False, "event_key": ""}
    )
    assert result.relevant is False
    assert result.topic == ""
    assert result.title == ""
    assert result.summary == ""
    assert result.importance == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 1), (1, 1), (2, 3), (3, 3), (4, 5), (8, 5), ("bad", 1)],
)
def test_importance_is_normalized(raw, expected):
    result = ChangePointAnalysis.model_validate(
        {"relevant": True, "importance": raw}
    )
    assert result.importance == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("standard", "STANDARD"),
        ("ARCHITECTURE", "ARCHITECTURE"),
        ("concept", "CONCEPT"),
        ("capability", "CAPABILITY"),
        ("release", "RELEASE"),
        ("marketing", "RELEASE"),
        (None, "RELEASE"),
    ],
)
def test_signal_type_is_normalized(raw, expected):
    result = ChangePointAnalysis.model_validate(
        {"relevant": True, "signal_type": raw}
    )
    assert result.signal_type == expected


def test_display_copy_is_compacted_and_capped():
    result = ChangePointAnalysis.model_validate(
        {
            "relevant": True,
            "title": "  中文   标题  ",
            "summary": "摘" * 400,
            "why_it_matters": "原因" * 200,
        }
    )

    assert result.title == "中文 标题"
    assert len(result.summary) == 300
    assert result.summary.endswith("…")
    assert len(result.why_it_matters) == 300


def test_analysis_prompt_requires_the_configured_display_language():
    prompt = render_analyze(
        source_name="OpenAI",
        source_type="RSS",
        source_kind="官方来源",
        title="English title",
        url="https://example.com",
        published_at="2026-07-31",
        content="English content",
        output_language="简体中文",
    )

    assert "title、summary、why_it_matters 都必须使用简体中文" in prompt
    assert "最多 300 个字符" in prompt
    assert "来源属性：官方来源" in prompt
    assert "社区讨论”只能作为早期线索" in prompt
