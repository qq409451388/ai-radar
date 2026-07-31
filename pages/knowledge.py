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
from ai_radar.ui import (
    fmt_dt,
    latest_coverage,
    signal_sort_key,
    signal_type_label,
    sources_for_change_point,
)
from ai_radar.utils import load_json

LEVEL_LABEL = {
    "NONE": "未覆盖",
    "AWARE": "已关注",
    "UNDERSTOOD": "已理解",
    "PRACTICED": "已实践",
}

SIGNAL_GROUPS = [
    (
        "STANDARD",
        "标准 / 协议",
        "开放标准、协议与互操作规范。优先确认兼容性、采用范围和迁移影响。",
    ),
    (
        "ARCHITECTURE",
        "架构设计",
        "会改变系统组织方式的架构与设计模式。重点理解它解决的旧问题和核心机制。",
    ),
    (
        "CONCEPT",
        "新概念",
        "值得建立独立认知的新抽象、术语与方法论。先确认定义、边界和真实案例。",
    ),
    (
        "CAPABILITY",
        "新能力",
        "模型或产品获得的新能力。适合通过最小任务验证效果、限制和成本。",
    ),
    (
        "RELEASE",
        "版本动态",
        "常规发布、升级、修复和体验变化。保留追溯，但不与设计信号混排。",
    ),
]


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

        filters = st.columns([1.2, 1.1, 1, 1.25, 1.8])
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
        selected_signal = filters[3].selectbox(
            "信号类型",
            [None, "STANDARD", "ARCHITECTURE", "CONCEPT", "CAPABILITY", "RELEASE"],
            format_func=lambda value: "全部类型"
            if value is None
            else signal_type_label(value),
        )
        keyword = filters[4].text_input("搜索知识变化")

        stmt = select(ChangePoint).where(ChangePoint.status == "ACTIVE")
        if selected_topic is not None:
            stmt = stmt.where(ChangePoint.topic_id == selected_topic)
        if selected_importance is not None:
            stmt = stmt.where(ChangePoint.importance == selected_importance)
        if selected_signal is not None:
            stmt = stmt.where(ChangePoint.signal_type == selected_signal)
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
        cps.sort(key=signal_sort_key, reverse=True)
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

        st.caption(
            f"当前筛选 {len(cps)} 条活跃知识变化点 · "
            "已按信号类型分组，组内按领域归档"
        )
        if not cps:
            st.info("没有符合条件的知识点。可以先去“情报收件箱”分析一批资讯。")
        if cps:
            visible_groups = [
                group
                for group in SIGNAL_GROUPS
                if selected_signal is None or group[0] == selected_signal
            ]
            grouped = {
                signal_type: [
                    cp for cp in cps if cp.signal_type == signal_type
                ]
                for signal_type, _, _ in visible_groups
            }
            labels = [
                f"{label} · {len(grouped[signal_type])}"
                for signal_type, label, _ in visible_groups
            ]
            default_label = next(
                (
                    label
                    for label, (signal_type, _, _) in zip(labels, visible_groups)
                    if grouped[signal_type]
                ),
                labels[0],
            )
            group_tabs = st.tabs(
                labels,
                default=default_label,
                key="knowledge_signal_groups",
            )
            for tab, (signal_type, _, description) in zip(
                group_tabs,
                visible_groups,
            ):
                with tab:
                    group_items = grouped[signal_type]
                    st.markdown(
                        f'<div class="signal-group-intro">{escape(description)}</div>',
                        unsafe_allow_html=True,
                    )
                    if not group_items:
                        st.info("当前筛选条件下，这一类还没有知识变化点。")
                        continue

                    items_by_topic: dict[str, list[ChangePoint]] = {}
                    for cp in group_items:
                        topic_name = topic_names.get(cp.topic_id, "未分类")
                        items_by_topic.setdefault(topic_name, []).append(cp)

                    for topic_name, topic_items in items_by_topic.items():
                        st.markdown(
                            f"""
                            <div class="signal-topic-heading">
                              <span>{escape(topic_name)}</span>
                              <small>{len(topic_items)} 条</small>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        for cp in topic_items:
                            selected_id = _render_change_point(
                                session,
                                cp,
                                topic_names,
                            )
                            if selected_id is not None:
                                reassess_id = selected_id

    if reassess_id is not None:
        with st.spinner("正在用最新个人事实重新评估…"):
            result = orchestrator.assess_change_point(reassess_id)
        st.success(f"评估完成：{LEVEL_LABEL[result['coverage_level']]}")
        st.rerun()


def _render_change_point(
    session,
    cp: ChangePoint,
    topic_names: dict[int, str],
) -> int | None:
    cov = latest_coverage(session, cp.id)
    level = cov.coverage_level if cov else "NONE"
    selected_id: int | None = None
    with st.expander(
        f"{'●' if cp.importance == 5 else '◆' if cp.importance == 3 else '·'} "
        f"{cp.title} · {LEVEL_LABEL[level]}"
    ):
        meta_cols = st.columns([2.1, 1.1, 1, 1, 1])
        meta_cols[0].caption(topic_names.get(cp.topic_id, "未分类"))
        meta_cols[1].caption(signal_type_label(cp.signal_type))
        meta_cols[2].caption(f"重要度 {cp.importance}")
        meta_cols[3].caption(f"发现 {fmt_dt(cp.first_seen_at)}")
        meta_cols[4].markdown(
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
                            ProfileSourceFile,
                            fact.source_file_id,
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
                selected_id = cp.id

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
                    "重要度",
                    options=[1, 3, 5],
                    value=cp.importance,
                )
                signal_options = [
                    "STANDARD",
                    "ARCHITECTURE",
                    "CONCEPT",
                    "CAPABILITY",
                    "RELEASE",
                ]
                new_signal_type = st.selectbox(
                    "信号类型",
                    signal_options,
                    index=signal_options.index(cp.signal_type)
                    if cp.signal_type in signal_options
                    else len(signal_options) - 1,
                    format_func=signal_type_label,
                )
                new_status = st.selectbox(
                    "状态",
                    ["ACTIVE", "DEPRECATED"],
                    index=0 if cp.status == "ACTIVE" else 1,
                )
                if st.form_submit_button("保存调整"):
                    cp.importance = new_importance
                    cp.signal_type = new_signal_type
                    cp.status = new_status
                    st.success("已保存。该调整会影响后续评分。")
        st.caption(f"event_key · {escape(cp.event_key)}")
    return selected_id


render()
