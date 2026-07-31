"""Coverage assessment service (section 十五 / 十六).

Asks the LLM how well a user's personal facts cover a change point, validates
that matched_fact_keys actually exist, and persists a KnowledgeCoverage row.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_radar.bootstrap import COVERAGE_COEFFICIENTS, COVERAGE_NONE, STATUS_ACTIVE
from ai_radar.config import get_config
from ai_radar.llm.client import LlmClient, LlmError
from ai_radar.models import (
    ChangePoint,
    KnowledgeCoverage,
    ProfileFact,
    ProfileSourceFile,
    Topic,
)
from ai_radar.repositories.job_log import job_log
from ai_radar.utils import dump_json, sha256_hex

log = logging.getLogger(__name__)

_LEVEL_RANK = {"NONE": 0, "AWARE": 1, "UNDERSTOOD": 2, "PRACTICED": 3}
_RANK_LEVEL = {v: k for k, v in _LEVEL_RANK.items()}
_EVIDENCE_CAP = {
    "DISCUSSION": "AWARE",
    "RESEARCH": "UNDERSTOOD",
    "DESIGN": "UNDERSTOOD",
    "DECISION": "UNDERSTOOD",
    "DEMO": "PRACTICED",
    "IMPLEMENTATION": "PRACTICED",
    "PRODUCTION": "PRACTICED",
}


class CoverageService:
    def __init__(self, session: Session, llm: LlmClient | None = None) -> None:
        self.session = session
        self.llm = llm or LlmClient(session)

    def assess_all(
        self,
        force: bool = False,
        topic_ids: set[int] | None = None,
        trigger_type: str = "SCHEDULED",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        stmt = select(ChangePoint).where(ChangePoint.status == STATUS_ACTIVE)
        if topic_ids is not None:
            if not topic_ids:
                return {"total": 0, "assessed": 0}
            stmt = stmt.where(ChangePoint.topic_id.in_(topic_ids))
        cps = list(self.session.execute(stmt).scalars())
        assessed = 0
        failed = 0
        if progress_callback:
            progress_callback(0, len(cps), "已读取待评估知识点")
        with job_log(self.session, "assess_all_change_points") as jl:
            for index, cp in enumerate(cps, start=1):
                if progress_callback:
                    progress_callback(
                        index - 1,
                        len(cps),
                        f"正在评估第 {index}/{len(cps)} 个知识点：{cp.title[:42]}",
                    )
                jl.processed_count += 1
                if not force and self._has_recent_coverage(cp.id):
                    if progress_callback:
                        progress_callback(
                            index,
                            len(cps),
                            f"已检查 {index}/{len(cps)} 个知识点",
                        )
                    continue
                try:
                    self._assess_one(cp, trigger_type=trigger_type)
                    assessed += 1
                    jl.success_count += 1
                except LlmError as exc:
                    jl.failed_count += 1
                    failed += 1
                    log.warning("assess cp %s failed: %s", cp.id, exc)
                except Exception:
                    jl.failed_count += 1
                    failed += 1
                    log.exception("assess cp %s errored", cp.id)
                if progress_callback:
                    progress_callback(
                        index,
                        len(cps),
                        f"已评估 {index}/{len(cps)} 个知识点",
                    )
            jl.message = f"assessed {assessed} of {len(cps)} change points"
        return {"total": len(cps), "assessed": assessed, "failed": failed}

    def assess_topics(
        self,
        topic_ids: set[int],
        trigger_type: str = "PROFILE_CHANGED",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        return self.assess_all(
            force=True,
            topic_ids=topic_ids,
            trigger_type=trigger_type,
            progress_callback=progress_callback,
        )

    def assess_new(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        """Assess only change points that have no coverage row yet."""
        stmt = select(ChangePoint).where(ChangePoint.status == STATUS_ACTIVE)
        cps = list(self.session.execute(stmt).scalars())
        new_cps = [cp for cp in cps if not self._has_any_coverage(cp.id)]
        assessed = 0
        failed = 0
        if progress_callback:
            progress_callback(0, len(new_cps), "已读取尚未评估的知识点")
        with job_log(self.session, "assess_new_change_points") as jl:
            for index, cp in enumerate(new_cps, start=1):
                if progress_callback:
                    progress_callback(
                        index - 1,
                        len(new_cps),
                        f"正在评估第 {index}/{len(new_cps)} 个知识点：{cp.title[:42]}",
                    )
                jl.processed_count += 1
                try:
                    self._assess_one(cp, trigger_type="NEW_CHANGE_POINT")
                    assessed += 1
                    jl.success_count += 1
                except LlmError as exc:
                    jl.failed_count += 1
                    failed += 1
                    log.warning("assess new cp %s failed: %s", cp.id, exc)
                except Exception:
                    jl.failed_count += 1
                    failed += 1
                    log.exception("assess new cp %s errored", cp.id)
                if progress_callback:
                    progress_callback(
                        index,
                        len(new_cps),
                        f"已评估 {index}/{len(new_cps)} 个知识点",
                    )
            jl.message = f"assessed {assessed} new change points of {len(new_cps)} candidates"
        return {
            "candidates": len(new_cps),
            "assessed": assessed,
            "failed": failed,
        }

    def assess_one(self, change_point_id: int) -> KnowledgeCoverage:
        cp = self.session.get(ChangePoint, change_point_id)
        if cp is None:
            raise ValueError(f"change_point {change_point_id} not found")
        return self._assess_one(cp, trigger_type="MANUAL")

    def _has_recent_coverage(self, change_point_id: int) -> bool:
        existing = self.session.execute(
            select(KnowledgeCoverage).where(
                KnowledgeCoverage.change_point_id == change_point_id
            )
        ).scalars().all()
        return any(existing)

    def _has_any_coverage(self, change_point_id: int) -> bool:
        return self._has_recent_coverage(change_point_id)

    def _assess_one(
        self, cp: ChangePoint, trigger_type: str = "SCHEDULED"
    ) -> KnowledgeCoverage:
        facts = self._rank_candidate_facts(cp, self._facts_for_topic(cp.topic_id))
        facts_block = self._render_facts(facts)
        topic_name = self._topic_name(cp.topic_id) or ""
        occurred_at = cp.occurred_at.isoformat() if cp.occurred_at else ""
        fingerprint = self._assessment_fingerprint(cp, facts)

        if not facts:
            # No facts → NONE, no LLM call needed (section 十五).
            coverage = KnowledgeCoverage(
                change_point_id=cp.id,
                coverage_level=COVERAGE_NONE,
                coverage_coefficient=COVERAGE_COEFFICIENTS[COVERAGE_NONE],
                confidence=1.0,
                rationale="该领域下没有任何个人事实，判定为未覆盖。",
                matched_fact_ids_json="[]",
                assessed_at=datetime.now(timezone.utc),
                model_name="rule:none-facts",
                trigger_type=trigger_type,
                assessment_fingerprint=fingerprint,
            )
            self._persist(cp.id, coverage)
            return coverage

        try:
            result = self.llm.assess_coverage(
                {
                    "title": cp.title,
                    "summary": cp.summary,
                    "why_it_matters": cp.why_it_matters,
                    "topic": topic_name,
                    "occurred_at": occurred_at,
                    "facts_block": facts_block,
                }
            )
        except LlmError:
            raise

        # Validate matched_fact_keys exist (section 十五).
        fact_by_key = {f.fact_key: f for f in facts}
        fact_by_key.update({str(f.id): f for f in facts})
        matched_facts = []
        seen_ids: set[int] = set()
        for key in result.matched_fact_keys:
            fact = fact_by_key.get(key)
            if fact is not None and fact.id not in seen_ids:
                matched_facts.append(fact)
                seen_ids.add(fact.id)
        matched_ids = [f.id for f in matched_facts]

        requested_level = result.coverage_level
        level = requested_level
        rule_note = ""
        if requested_level != COVERAGE_NONE and not matched_facts:
            level = COVERAGE_NONE
            rule_note = "模型未提供可验证的事实证据，已按规则降为 NONE。"
        elif matched_facts:
            max_cap_rank = max(
                _LEVEL_RANK[_EVIDENCE_CAP.get(f.evidence_type, "AWARE")]
                for f in matched_facts
            )
            if _LEVEL_RANK[level] > max_cap_rank:
                level = _RANK_LEVEL[max_cap_rank]
                rule_note = (
                    f"依据证据类型，覆盖等级由 {requested_level} 校准为 {level}。"
                )
        rationale = result.rationale
        if rule_note:
            rationale = f"{rationale}\n{rule_note}".strip()

        coverage = KnowledgeCoverage(
            change_point_id=cp.id,
            coverage_level=level,
            coverage_coefficient=COVERAGE_COEFFICIENTS[level],
            confidence=result.confidence,
            rationale=rationale,
            matched_fact_ids_json=dump_json(matched_ids),
            assessed_at=datetime.now(timezone.utc),
            model_name=self.llm.model,
            trigger_type=trigger_type,
            assessment_fingerprint=fingerprint,
        )
        self._persist(cp.id, coverage)
        return coverage

    def _persist(self, change_point_id: int, coverage: KnowledgeCoverage) -> None:
        # Append-only history: transitions are a core product signal.
        self.session.add(coverage)
        self.session.flush()

    def _facts_for_topic(self, topic_id: int | None) -> list[ProfileFact]:
        if topic_id is None:
            return []
        return list(
            self.session.execute(
                select(ProfileFact)
                .join(ProfileSourceFile, ProfileSourceFile.id == ProfileFact.source_file_id)
                .where(
                    ProfileFact.topic_id == topic_id,
                    ProfileFact.active == True,  # noqa: E712
                    ProfileSourceFile.sync_status == "SUCCESS",
                )
            ).scalars()
        )

    def _render_facts(self, facts: list[ProfileFact]) -> str:
        if not facts:
            return "（暂无个人事实）"
        lines = []
        for f in facts:
            lines.append(
                f"- fact_key={f.fact_key} | 类型={f.evidence_type} | 事实={f.fact_text}"
            )
        return "\n".join(lines)

    def _rank_candidate_facts(
        self, cp: ChangePoint, facts: list[ProfileFact]
    ) -> list[ProfileFact]:
        limit = max(1, get_config().max_assessment_facts)
        if len(facts) <= limit:
            return facts
        change_text = f"{cp.title} {cp.summary} {cp.why_it_matters}".lower()
        change_terms = _terms(change_text)

        def score(fact: ProfileFact) -> tuple[float, float]:
            fact_text = fact.fact_text.lower()
            overlap = len(change_terms & _terms(fact_text))
            similarity = SequenceMatcher(None, change_text[:800], fact_text[:400]).ratio()
            evidence_bonus = _LEVEL_RANK[_EVIDENCE_CAP.get(fact.evidence_type, "AWARE")] * 0.08
            return (
                overlap * 1.5 + similarity + evidence_bonus,
                _timestamp(fact.occurred_at or fact.extracted_at),
            )

        return sorted(facts, key=score, reverse=True)[:limit]

    def _assessment_fingerprint(
        self, cp: ChangePoint, facts: list[ProfileFact]
    ) -> str:
        payload = {
            "cp": [cp.id, cp.title, cp.summary, cp.why_it_matters, cp.importance],
            "facts": [
                [f.id, f.fact_key, f.fact_text, f.evidence_type, f.active]
                for f in facts
            ],
            "model": getattr(self.llm, "model", ""),
        }
        return sha256_hex(dump_json(payload))

    def _topic_name(self, topic_id: int | None) -> str | None:
        if topic_id is None:
            return None
        t = self.session.get(Topic, topic_id)
        return t.name if t else None


def _terms(text: str) -> set[str]:
    latin = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9._+-]{1,}", text.lower())
        if len(token) > 1
    }
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    bigrams = {
        chunk[i : i + 2]
        for chunk in chinese
        for i in range(max(0, len(chunk) - 1))
    }
    return latin | bigrams


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
