"""Today-first command center."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

import streamlit as st
from sqlalchemy import func, select

from ai_radar.config import get_config
from ai_radar.database import session_scope
from ai_radar.models import (
    ChangePoint,
    JobLog,
    KnowledgeCoverage,
    ProfileSourceFile,
    SourceItem,
    Topic,
)
from ai_radar.pipeline_runner import (
    enqueue_pipeline,
    get_active_pipeline_snapshot,
)
from ai_radar.services.scoring_service import ScoringService
from ai_radar.ui import fmt_dt, latest_coverage


def _metric_card(label: str, value: str, detail: str, tone: str = "") -> None:
    st.markdown(
        f"""
        <div class="radar-card">
          <div class="card-label">{escape(label)}</div>
          <div class="card-value {tone}">{escape(value)}</div>
          <div class="card-detail">{escape(detail)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    cfg = get_config()
    st.markdown('<div class="page-kicker">Daily command center</div>', unsafe_allow_html=True)
    st.title("今天该关注什么")
    st.markdown(
        '<div class="page-subtitle">从最新变化、知识缺口和个人进展中，给出一份可以直接行动的清单。</div>',
        unsafe_allow_html=True,
    )

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=cfg.score_window_days)
    with session_scope() as session:
        pending = session.scalar(
            select(func.count(SourceItem.id)).where(
                SourceItem.analyze_status == "PENDING"
            )
        ) or 0
        failed = session.scalar(
            select(func.count(SourceItem.id)).where(
                SourceItem.analyze_status == "FAILED"
            )
        ) or 0
        recent_cps = list(
            session.execute(
                select(ChangePoint)
                .where(
                    ChangePoint.status == "ACTIVE",
                    ChangePoint.first_seen_at >= recent_cutoff,
                )
                .order_by(
                    ChangePoint.importance.desc(), ChangePoint.first_seen_at.desc()
                )
            ).scalars()
        )
        topics = list(
            session.execute(
                select(Topic).where(Topic.enabled == True).order_by(Topic.id)  # noqa: E712
            ).scalars()
        )
        health = ScoringService(session).compute_all_topic_health()
        topic_names = {topic.id: topic.name for topic in topics}
        gaps = []
        for cp in recent_cps:
            cov = latest_coverage(session, cp.id)
            if cp.importance >= 3 and (
                cov is None or cov.coverage_level in ("NONE", "AWARE")
            ):
                gaps.append(
                    {
                        "id": cp.id,
                        "title": cp.title,
                        "summary": cp.summary,
                        "importance": cp.importance,
                        "topic": topic_names.get(cp.topic_id, "未分类"),
                        "level": cov.coverage_level if cov else "NONE",
                        "first_seen": cp.first_seen_at,
                    }
                )
        profile = session.execute(
            select(ProfileSourceFile)
            .order_by(ProfileSourceFile.last_success_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        last_pipeline = session.execute(
            select(JobLog)
            .where(JobLog.job_type == "snapshot")
            .order_by(JobLog.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        total_recent_weight = sum(item["total_weight"] for item in health.values())
        weighted_score = (
            sum(item["score"] * item["total_weight"] for item in health.values())
            / total_recent_weight
            if total_recent_weight
            else 0.0
        )
        practiced_points = sum(
            1
            for cp in recent_cps
            if (
                (cov := latest_coverage(session, cp.id))
                and cov.coverage_level == "PRACTICED"
            )
        )

    active_pipeline = get_active_pipeline_snapshot()
    action_col, secondary_col, note_col = st.columns([1.25, 1, 2.6])
    with action_col:
        if st.button(
            "运行今日更新",
            type="primary",
            width="stretch",
            disabled=active_pipeline is not None,
        ):
            enqueue_pipeline("FULL_UPDATE")
            st.toast("完整更新已在后台启动", icon="🚀")
            st.rerun()
    with secondary_col:
        if st.button(
            "只同步 GPT 记忆",
            width="stretch",
            disabled=active_pipeline is not None,
        ):
            enqueue_pipeline("MEMORY")
            st.toast("记忆同步已在后台启动", icon="🚀")
            st.rerun()
    with note_col:
        if active_pipeline:
            st.caption(
                f"{active_pipeline['pipeline_label']}正在后台运行；"
                "切换页面不影响，侧边栏会持续显示进度。"
            )
        else:
            st.caption(
                f"每次最多分析 {cfg.analyze_batch_size} 条，避免一次耗尽 Token。"
                f"上次完整快照：{fmt_dt(last_pipeline.finished_at) if last_pipeline else '尚未生成'}"
            )

    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            f"近 {cfg.score_window_days} 天跟进覆盖",
            f"{weighted_score:.0f}%",
            f"{len(recent_cps)} 个有效知识变化点",
            "good" if weighted_score >= 65 else "warn",
        )
    with cols[1]:
        _metric_card(
            "优先知识缺口",
            str(len(gaps)),
            "重要度 ≥ 3，且尚未理解",
            "bad" if gaps else "good",
        )
    with cols[2]:
        _metric_card(
            "已实践变化点",
            str(practiced_points),
            "有 Demo、实现或生产证据",
            "good",
        )
    with cols[3]:
        profile_detail = (
            f"最后成功 {fmt_dt(profile.last_extracted_at or profile.last_success_at)}"
            if profile
            else "尚未连接记忆仓库"
        )
        _metric_card(
            "情报收件箱",
            str(pending),
            f"{failed} 条失败 · {profile_detail}",
            "warn" if pending else "good",
        )

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown('<div class="section-heading">优先跟进</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-caption">重要且尚未形成充分认知证据的变化，按优先级排序。</div>',
            unsafe_allow_html=True,
        )
        if not gaps:
            st.success("当前没有高优先级知识缺口。完成下一批情报分析后会自动更新。")
        for gap in gaps[:6]:
            level_class = gap["level"].lower()
            st.markdown(
                f"""
                <div class="priority-card {'critical' if gap['importance'] == 5 else 'watch'}">
                  <div class="priority-title">{escape(gap['title'])}</div>
                  <div class="priority-meta">
                    {escape(gap['topic'])} · 重要度 {gap['importance']} · {escape(fmt_dt(gap['first_seen']))}
                  </div>
                  <span class="pill {level_class}">{escape(gap['level'])}</span>
                  <span class="pill">建议：阅读来源并在 GPT 中形成研究或实践记录</span>
                  <div class="card-detail" style="margin-top:.65rem">{escape((gap['summary'] or '')[:180])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right:
        st.markdown('<div class="section-heading">领域温度</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="section-caption">以近 {cfg.score_window_days} 天变化为窗口，不再被多年历史稀释。</div>',
            unsafe_allow_html=True,
        )
        for topic in topics:
            item = health[topic.id]
            label_col, value_col = st.columns([3, 1])
            label_col.markdown(f"**{topic.name}**")
            value_col.markdown(f"**{item['score']:.0f}%**")
            st.progress(item["score"] / 100)
            st.caption(
                f"{item['change_point_count']} 个变化 · "
                f"{item['important_gap_count']} 个重要缺口 · "
                f"实践率 {item['practiced_rate']:.0f}%"
            )


render()
