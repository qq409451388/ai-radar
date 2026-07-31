"""Pydantic schemas for LLM JSON outputs (section 十二 / 十四 / 十五)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# Valid enum-ish literals
ImportanceLiteral = Literal[1, 3, 5]
EvidenceLiteral = Literal[
    "DISCUSSION",
    "RESEARCH",
    "DESIGN",
    "DEMO",
    "IMPLEMENTATION",
    "PRODUCTION",
    "DECISION",
]
CoverageLiteral = Literal["NONE", "AWARE", "UNDERSTOOD", "PRACTICED"]


class ChangePointAnalysis(BaseModel):
    """Output of analyze_change_points for a single source item."""

    relevant: bool
    # Models commonly return only {"relevant": false, "event_key": ""} for
    # filtered items. Optional defaults make that valid without weakening the
    # relevant-item persistence rules in AnalysisService.
    topic: str = Field(default="", description="一级领域名称")
    event_key: str = Field(
        default="", description="事件键，例如 coding-agent.trae-work.agent-mode"
    )
    title: str = ""
    summary: str = ""
    why_it_matters: str = ""
    importance: ImportanceLiteral = 1
    occurred_at: str | None = Field(default=None, description="ISO date YYYY-MM-DD or null")
    duplicate_keywords: list[str] = Field(default_factory=list)

    @field_validator("importance", mode="before")
    @classmethod
    def _normalize_importance(cls, value):
        """Snap non-canonical model output (for example 0/2/4) to 1/3/5."""
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return 1
        if numeric <= 1:
            return 1
        if numeric <= 3:
            return 3
        return 5


class ProfileFactItem(BaseModel):
    fact_key: str
    fact_text: str
    topic: str
    occurred_at: str | None = None
    evidence_type: EvidenceLiteral = "DISCUSSION"
    source_heading: str = ""
    source_line_start: int
    source_line_end: int


class ProfileFactExtraction(BaseModel):
    facts: list[ProfileFactItem] = Field(default_factory=list)


class CoverageAssessment(BaseModel):
    coverage_level: CoverageLiteral
    coverage_coefficient: float
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    matched_fact_keys: list[str] = Field(default_factory=list)

    @field_validator("coverage_coefficient")
    @classmethod
    def _check_coefficient(cls, v: float, info) -> float:
        from ai_radar.bootstrap import COVERAGE_COEFFICIENTS

        level = info.data.get("coverage_level")
        if level in COVERAGE_COEFFICIENTS:
            expected = COVERAGE_COEFFICIENTS[level]
            # Allow tiny float drift; otherwise snap to the fixed value.
            if abs(v - expected) > 1e-6:
                # Snap to the canonical coefficient rather than rejecting outright
                # — the level is authoritative per section 十五.
                return expected
        return v
