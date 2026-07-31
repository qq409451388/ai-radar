"""Knowledge map: change points, evidence, and coverage transitions."""
from __future__ import annotations

from html import escape

import streamlit as st
from sqlalchemy import or_, select

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.models import (
    ChangePoint,
    KnowledgeCoverage,
    ProfileFact,
    ProfileSourceFile,
    Topic,
)
from ai_radar.ui import fmt_dt, latest_coverage, sources_for_change_point
from ai_radar.utils import load_json

LEVEL_LABEL = {
    "NONE": "未覆盖",
    "AWARE": "已关注",
    "UNDERSTOOD": "已理解",
    "PRACTICED": "已实践",
}


def render() -> None:
    st.markdown('<div class="page-kicker">Knowledge map</div>', unsafe_allow_html=True)
    st.title("知识地图")
    st.markdown(
        '<div class="page-subtitle">每个分数都能追溯到知识变化、个人事实和覆盖历史。</div>',
        unsafe_allow_html=True,
    )

    reassess_id: int | None = None
    with session_scope() as session:
        topics = list(
            session.execute(select(Topic).order_by(Topic.id)).scalars()
        )
        topic_names = {topic.id: topic.name for topic in topics}

        filters = st.columns([1.3, 1.2, 1, 2.1])
        selected_topic = filters[0].selectbox(
            "领域",
            [None] + [topic.id for topic in topics],
            format_func=lambda value: "全部领域"
            if value is None
            else topic_names[value],
        )
        selected_level = filters[1].selectbox(
            "当前覆盖",
            [None, "NONE", "AWARE", "UNDERSTOOD", "PRACTICED"],
            format_func=lambda value: "全部等级"
            if value is None
            else LEVEL_LABEL[value],
        )
        selected_importance = filters[2].selectbox(
            "重要度",
            [None, 5, 3, 1],
            format_func=lambda value: "全部" if value is None else str(value),
        )
        keyword = filters[3].text_input("搜索知识变化")

        stmt = select(ChangePoint).where(ChangePoint.status == "ACTIVE")
        if selected_topic is not None:
            stmt = stmt.where(ChangePoint.topic_id == selected_topic)
        if selected_importance is not None:
            stmt = stmt.where(ChangePoint.importance == selected_importance)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ChangePoint.title.ilike(like),
                    ChangePoint.summary.ilike(like),
                    ChangePoint.event_key.ilike(like),
                )
            )
        cps = list(
            session.execute(
                stmt.order_by(
                    ChangePoint.importance.desc(),
                    ChangePoint.last_seen_at.desc(),
                )
            ).scalars()
        )
        if selected_level is not None:
            cps = [
                cp
                for cp in cps
                if (
                    (cov := latest_coverage(session, cp.id))
                    and cov.coverage_level == selected_level
                )
                or (
                    selected_level == "NONE"
                    and latest_coverage(session, cp.id) is None
                )
            ]

        level_counts = {level: 0 for level in LEVEL_LABEL}
        for cp in cps:
            cov = latest_coverage(session, cp.id)
            level_counts[cov.coverage_level if cov else "NONE"] += 1

        metrics = st.columns(4)
        for col, level in zip(metrics, LEVEL_LABEL):
            col.metric(LEVEL_LABEL[level], level_counts[level])

        st.caption(f"当前筛选下共 {len(cps)} 个活跃知识变化点")
        if not cps:
            st.info("没有符合条件的知识点。可以先去“情报收件箱”分析一批资讯。")

        for cp in cps:
            cov = latest_coverage(session, cp.id)
            level = cov.coverage_level if cov else "NONE"
            with st.expander(
                f"{'●' if cp.importance == 5 else '◆' if cp.importance == 3 else '·'} "
                f"{cp.title} · {LEVEL_LABEL[level]}"
            ):
                meta_cols = st.columns([2.4, 1, 1, 1])
                meta_cols[0].caption(topic_names.get(cp.topic_id, "未分类"))
                meta_cols[1].caption(f"重要度 {cp.importance}")
                meta_cols[2].caption(f"发现 {fmt_dt(cp.first_seen_at)}")
                meta_cols[3].markdown(
                    f'<span class="pill {level.lower()}">{LEVEL_LABEL[level]}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown("#### 发生了什么")
                st.write(cp.summary or "暂无摘要")
                if cp.why_it_matters:
                    st.info(cp.why_it_matters, icon="💡")

                evidence_tab, history_tab, source_tab, manage_tab = st.tabs(
                    ["当前判断", "进展历史", "官方来源", "管理"]
                )
                with evidence_tab:
                    if cov is None:
                        st.warning("尚未评估。完成记忆同步后可手动评估。")
                    else:
                        st.markdown(
                            f"**{LEVEL_LABEL[cov.coverage_level]}** · "
                            f"置信度 {cov.confidence:.0%} · "
                            f"评估模型 {cov.model_name or '规则'}"
                        )
                        st.write(cov.rationale or "暂无判断说明")
                        matched_ids = load_json(cov.matched_fact_ids_json, [])
                        if matched_ids:
                            st.markdown("**匹配到的个人事实**")
                            for fact_id in matched_ids:
                                fact = session.get(ProfileFact, int(fact_id))
                                if not fact:
                                    continue
                                source_file = session.get(
                                    ProfileSourceFile, fact.source_file_id
                                )
                                st.markdown(f"- {fact.fact_text}")
                                st.caption(
                                    f"{fact.evidence_type} · "
                                    f"{source_file.file_path if source_file else '未知文件'}:"
                                    f"{fact.source_line_start}-{fact.source_line_end}"
                                )
                        else:
                            st.caption("没有可验证的个人事实，因此不会计入覆盖分数。")
                    if st.button(
                        "用最新记忆重新评估",
                        key=f"assess_cp_{cp.id}",
                        width="content",
                    ):
                        reassess_id = cp.id

                with history_tab:
                    history = list(
                        session.execute(
                            select(KnowledgeCoverage)
                            .where(KnowledgeCoverage.change_point_id == cp.id)
                            .order_by(KnowledgeCoverage.assessed_at.desc())
                        ).scalars()
                    )
                    if not history:
                        st.caption("尚无评估历史")
                    for row in history:
                        st.markdown(
                            f"**{LEVEL_LABEL[row.coverage_level]}** · "
                            f"{fmt_dt(row.assessed_at)}"
                        )
                        st.caption(
                            f"触发：{row.trigger_type} · 置信度 {row.confidence:.0%}"
                        )

                with source_tab:
                    sources = sources_for_change_point(session, cp.id)
                    for item in sources:
                        st.markdown(f"- [{item.title or item.url}]({item.url})")
                        st.caption(
                            f"发布 {fmt_dt(item.published_at)} · {item.author or '官方'}"
                        )
                    if not sources:
                        st.caption("暂无关联来源")

                with manage_tab:
                    with st.form(f"manage_cp_{cp.id}"):
                        new_importance = st.select_slider(
                            "重要度", options=[1, 3, 5], value=cp.importance
                        )
                        new_status = st.selectbox(
                            "状态",
                            ["ACTIVE", "DEPRECATED"],
                            index=0 if cp.status == "ACTIVE" else 1,
                        )
                        if st.form_submit_button("保存调整"):
                            cp.importance = new_importance
                            cp.status = new_status
                            st.success("已保存。该调整会影响后续评分。")
                st.caption(f"event_key · {escape(cp.event_key)}")

    if reassess_id is not None:
        with st.spinner("正在用最新个人事实重新评估…"):
            result = orchestrator.assess_change_point(reassess_id)
        st.success(f"评估完成：{LEVEL_LABEL[result['coverage_level']]}")
        st.rerun()


render()
