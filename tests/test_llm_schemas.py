"""Tolerance rules for common structured-output variations."""
from __future__ import annotations

import pytest

from ai_radar.llm.schemas import ChangePointAnalysis


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
