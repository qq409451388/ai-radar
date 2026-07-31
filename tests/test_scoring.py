"""Tests for the scoring algorithm (section 二十: 1, 2, 3, 9, 12)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from ai_radar.bootstrap import (
    COVERAGE_AWARE,
    COVERAGE_COEFFICIENTS,
    COVERAGE_NONE,
    COVERAGE_PRACTICED,
    COVERAGE_UNDERSTOOD,
    STATUS_ACTIVE,
    STATUS_DEPRECATED,
    seed_default_data,
)
from ai_radar.models import (
    ChangePoint,
    KnowledgeCoverage,
    Topic,
    TopicSnapshot,
)
from ai_radar.services.scoring_service import ScoringService
from ai_radar.utils import local_today


def _make_topic(session, name="测试领域") -> Topic:
    t = Topic(name=name, description="t")
    session.add(t)
    session.flush()
    return t


def _make_cp(session, topic_id, event_key, importance=3, status=STATUS_ACTIVE):
    cp = ChangePoint(
        topic_id=topic_id,
        event_key=event_key,
        title=event_key,
        summary="",
        importance=importance,
        status=status,
    )
    session.add(cp)
    session.flush()
    return cp


def _set_coverage(session, cp_id, level, confidence=1.0):
    cov = KnowledgeCoverage(
        change_point_id=cp_id,
        coverage_level=level,
        coverage_coefficient=COVERAGE_COEFFICIENTS[level],
        confidence=confidence,
        rationale="test",
        matched_fact_ids_json="[]",
    )
    session.add(cov)
    session.flush()


def test_scoring_formula_correct(session):
    """Test 1: score = Σ(imp×coeff)/Σ(imp)×100 (section 八 example)."""
    topic = _make_topic(session)
    a = _make_cp(session, topic.id, "a", importance=5)
    b = _make_cp(session, topic.id, "b", importance=3)
    c = _make_cp(session, topic.id, "c", importance=3)
    _set_coverage(session, a.id, COVERAGE_PRACTICED)
    _set_coverage(session, b.id, COVERAGE_UNDERSTOOD)
    _set_coverage(session, c.id, COVERAGE_NONE)

    score = ScoringService(session).compute_topic_score(topic.id)
    expected = (5 * 1.00 + 3 * 0.65 + 3 * 0) / (5 + 3 + 3) * 100
    assert score["score"] == round(expected, 2)
    assert score["total_weight"] == 11
    assert score["change_point_count"] == 3


def test_new_change_point_drops_score(session):
    """Test 2: adding a change point with no facts lowers the score."""
    topic = _make_topic(session)
    a = _make_cp(session, topic.id, "a", importance=5)
    _set_coverage(session, a.id, COVERAGE_PRACTICED)
    svc = ScoringService(session)
    before = svc.compute_topic_score(topic.id)["score"]
    assert before == 100.0

    b = _make_cp(session, topic.id, "b", importance=5)  # no coverage → NONE
    after = svc.compute_topic_score(topic.id)["score"]
    assert after < before
    assert after == 50.0  # (5*1 + 5*0)/10


def test_deprecated_change_point_excluded(session):
    """Test 3: DEPRECATED change points are excluded from scoring."""
    topic = _make_topic(session)
    a = _make_cp(session, topic.id, "a", importance=5)
    b = _make_cp(session, topic.id, "b", importance=5, status=STATUS_DEPRECATED)
    _set_coverage(session, a.id, COVERAGE_PRACTICED)
    _set_coverage(session, b.id, COVERAGE_NONE)
    score = ScoringService(session).compute_topic_score(topic.id)
    assert score["change_point_count"] == 1
    assert score["score"] == 100.0


@pytest.mark.parametrize(
    "level,coeff",
    [
        (COVERAGE_NONE, 0.00),
        (COVERAGE_AWARE, 0.25),
        (COVERAGE_UNDERSTOOD, 0.65),
        (COVERAGE_PRACTICED, 1.00),
    ],
)
def test_coverage_coefficients(session, level, coeff):
    """Test 9: coverage coefficients are fixed per level."""
    assert COVERAGE_COEFFICIENTS[level] == coeff
    topic = _make_topic(session, name=f"领域-{level}")
    cp = _make_cp(session, topic.id, f"cp-{level}", importance=3)
    _set_coverage(session, cp.id, level)
    score = ScoringService(session).compute_topic_score(topic.id)
    assert score["score"] == round(coeff * 100, 2)


def test_snapshot_delta_computed_correctly(session):
    """Test 12: snapshot score_delta = today - previous day."""
    topic = _make_topic(session)
    cp = _make_cp(session, topic.id, "cp", importance=5)
    _set_coverage(session, cp.id, COVERAGE_PRACTICED)

    svc = ScoringService(session)

    # Simulate a previous-day snapshot at 100.
    yesterday = local_today() - timedelta(days=1)
    prev = TopicSnapshot(
        topic_id=topic.id,
        snapshot_date=yesterday,
        score=100.0,
        score_delta=0.0,
        total_weight=5,
        covered_weight=5,
    )
    session.add(prev)
    session.flush()

    # Add an uncovered change point so today's score drops.
    cp2 = _make_cp(session, topic.id, "cp2", importance=5)
    # No coverage → NONE coefficient.

    svc.save_snapshot()
    snap = session.execute(
        select(TopicSnapshot).where(
            TopicSnapshot.topic_id == topic.id,
            TopicSnapshot.snapshot_date == local_today(),
        )
    ).scalar_one()
    # today score = (5*1 + 5*0)/10*100 = 50; delta = 50 - 100 = -50
    assert snap.score == 50.0
    assert snap.score_delta == -50.0
