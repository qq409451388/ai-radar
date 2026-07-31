"""Knowledge map: change points, evidence, and coverage transitions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from math import ceil

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
KNOWLEDGE_PAGE_SIZE = 20


def render() -> None:
    st.markdown('<div class="page-kicker">Knowledge map</div>', unsafe_allow_html=True)
    st.title("知识地图")
    st.markdown(
        '<div class="page-subtitle">每个分数都能追溯到知识变化、个人事实和覆盖历史。</div>',
        unsafe_allow_html=True,
    )

    target_id = _query_int("change_point")
    query_topic = _query_int("topic")
    query_signals = [
        value
        for value in st.query_params.get("signals", "").split(",")
        if value in {group[0] for group in SIGNAL_GROUPS}
    ]
    query_coverage = st.query_params.get("coverage")
    query_importance = _query_int("importance_min")
    query_period = st.query_params.get("period")
    query_keyword = st.query_params.get("q", "")

    reassess_id: int | None = None
    with session_scope() as session:
        topics = list(
            session.execute(select(Topic).order_by(Topic.id)).scalars()
        )
        topic_names = {topic.id: topic.name for topic in topics}

        topic_options = [None] + [topic.id for topic in topics]
        level_options = [
            None,
            "GAP",
            "NONE",
            "AWARE",
            "UNDERSTOOD",
            "PRACTICED",
        ]
        importance_options = [None, 5, 3, 1]
        signal_options = [group[0] for group in SIGNAL_GROUPS]
        period_options = [None, "7d", "30d"]
        query_signature = (
            target_id,
            query_topic,
            tuple(query_signals),
            query_coverage,
            query_importance,
            query_period,
            query_keyword,
        )
        if st.session_state.get("_knowledge_query_signature") != query_signature:
            st.session_state["_knowledge_query_signature"] = query_signature
            st.session_state["knowledge_topic"] = (
                query_topic if query_topic in topic_options else None
            )
            st.session_state["knowledge_level"] = (
                query_coverage if query_coverage in level_options else None
            )
            st.session_state["knowledge_importance"] = (
                query_importance
                if query_importance in importance_options
                else None
            )
            st.session_state["knowledge_signals"] = query_signals
            st.session_state["knowledge_period"] = (
                query_period if query_period in period_options else None
            )
            st.session_state["knowledge_keyword"] = query_keyword

        filters = st.columns([1.15, 1.2, 1, 1.6, 1, 1.7])
        selected_topic = filters[0].selectbox(
            "领域",
            topic_options,
            format_func=lambda value: "全部领域"
            if value is None
            else topic_names[value],
            key="knowledge_topic",
        )
        selected_level = filters[1].selectbox(
            "当前覆盖",
            level_options,
            format_func=lambda value: "全部等级"
            if value is None
            else "重要知识缺口"
            if value == "GAP"
            else LEVEL_LABEL[value],
            key="knowledge_level",
        )
        selected_importance = filters[2].selectbox(
            "最低重要度",
            importance_options,
            format_func=lambda value: "全部" if value is None else str(value),
            key="knowledge_importance",
        )
        selected_signals = filters[3].multiselect(
            "信号类型",
            signal_options,
            format_func=signal_type_label,
            placeholder="全部类型",
            key="knowledge_signals",
        )
        selected_period = filters[4].selectbox(
            "发现时间",
            period_options,
            format_func=lambda value: {
                None: "全部时间",
                "7d": "近 7 天",
                "30d": "近 30 天",
            }[value],
            key="knowledge_period",
        )
        keyword = filters[5].text_input(
            "搜索知识变化",
            key="knowledge_keyword",
        )
        if target_id is None:
            _sync_filter_query(
                selected_topic=selected_topic,
                selected_level=selected_level,
                selected_importance=selected_importance,
                selected_signals=selected_signals,
                selected_period=selected_period,
                keyword=keyword,
            )

        stmt = select(ChangePoint).where(ChangePoint.status == "ACTIVE")
        if target_id is not None:
            stmt = stmt.where(ChangePoint.id == target_id)
        elif selected_topic is not None:
            stmt = stmt.where(ChangePoint.topic_id == selected_topic)
        if selected_importance is not None:
            stmt = stmt.where(ChangePoint.importance >= selected_importance)
        if selected_signals:
            stmt = stmt.where(ChangePoint.signal_type.in_(selected_signals))
        if selected_period:
            days = 7 if selected_period == "7d" else 30
            stmt = stmt.where(
                ChangePoint.first_seen_at
                >= datetime.now(timezone.utc) - timedelta(days=days)
            )
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
        if selected_level == "GAP":
            cps = [
                cp
                for cp in cps
                if cp.importance >= 3
                and (
                    (cov := latest_coverage(session, cp.id)) is None
                    or cov.coverage_level in ("NONE", "AWARE")
                )
            ]
        elif selected_level is not None:
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

        st.markdown(
            '<div class="knowledge-brief">'
            f'<span><strong>{len(cps)}</strong> 当前变化</span>'
            f'<span><strong>{level_counts["NONE"]}</strong> 未覆盖</span>'
            f'<span><strong>{level_counts["AWARE"]}</strong> 已关注</span>'
            f'<span><strong>{level_counts["UNDERSTOOD"]}</strong> 已理解</span>'
            f'<span><strong>{level_counts["PRACTICED"]}</strong> 已实践</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        if target_id is not None:
            target_cols = st.columns([3, 1])
            target_cols[0].info("正在查看首页选中的知识点。")
            target_cols[1].page_link(
                "pages/knowledge.py",
                label="返回全部知识变化",
                width="stretch",
            )
        if not cps:
            st.info("没有符合条件的知识点。可以先去“情报收件箱”分析一批资讯。")
        if cps:
            grouped = {
                signal_type: [
                    cp for cp in cps if cp.signal_type == signal_type
                ]
                for signal_type, _, _ in SIGNAL_GROUPS
            }
            visible_groups = [
                group
                for group in SIGNAL_GROUPS
                if grouped[group[0]]
            ]
            group_labels = {
                signal_type: f"{label} {len(grouped[signal_type])}"
                for signal_type, label, _description in visible_groups
            }
            group_options = [group[0] for group in visible_groups]
            group_filter_signature = (
                target_id,
                selected_topic,
                selected_level,
                selected_importance,
                tuple(selected_signals),
                selected_period,
                keyword,
            )
            preferred_group = (
                cps[0].signal_type
                if cps[0].signal_type in group_options
                else group_options[0]
            )
            if (
                st.session_state.get("_knowledge_group_filter_signature")
                != group_filter_signature
                or st.session_state.get("knowledge_signal_group")
                not in group_options
            ):
                st.session_state["_knowledge_group_filter_signature"] = (
                    group_filter_signature
                )
                st.session_state["knowledge_signal_group"] = preferred_group
            selected_group = st.segmented_control(
                "知识类型",
                group_options,
                format_func=lambda value: group_labels[value],
                required=True,
                key="knowledge_signal_group",
                label_visibility="collapsed",
                width="stretch",
            )
            description = next(
                group[2]
                for group in visible_groups
                if group[0] == selected_group
            )
            st.markdown(
                f'<div class="signal-group-intro">{escape(description)}</div>',
                unsafe_allow_html=True,
            )

            group_items = grouped[selected_group]
            page_signature = (
                group_filter_signature,
                selected_group,
                tuple(cp.id for cp in group_items),
            )
            if (
                st.session_state.get("_knowledge_page_signature")
                != page_signature
            ):
                st.session_state["_knowledge_page_signature"] = page_signature
                st.session_state["knowledge_page"] = 1
            page = _knowledge_pagination(len(group_items))
            page_items = group_items[
                (page - 1) * KNOWLEDGE_PAGE_SIZE:
                page * KNOWLEDGE_PAGE_SIZE
            ]

            items_by_topic: dict[str, list[ChangePoint]] = {}
            for cp in page_items:
                topic_name = topic_names.get(cp.topic_id, "未分类")
                items_by_topic.setdefault(topic_name, []).append(cp)

            for topic_name, topic_items in items_by_topic.items():
                st.markdown(
                    f"""
                    <div class="signal-topic-heading">
                      <span>{escape(topic_name)}</span>
                      <small>本页 {len(topic_items)} 条</small>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                for cp in topic_items:
                    selected_id = _render_change_point(
                        session,
                        cp,
                        topic_names,
                        expanded=cp.id == target_id,
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
    *,
    expanded: bool = False,
) -> int | None:
    cov = latest_coverage(session, cp.id)
    level = cov.coverage_level if cov else "NONE"
    is_open = (
        expanded
        or st.session_state.get("_knowledge_open_change_id") == cp.id
    )
    with st.container(
        border=True,
        key=f"knowledge_change_card_{cp.id}",
    ):
        heading_col, action_col = st.columns(
            [5.2, .8],
            vertical_alignment="center",
        )
        importance_class = (
            "critical"
            if cp.importance >= 5
            else "important"
            if cp.importance >= 3
            else "normal"
        )
        heading_col.markdown(
            '<div class="knowledge-list-heading">'
            '<div class="knowledge-list-meta">'
            f'<span class="knowledge-importance {importance_class}">'
            f"重要度 {cp.importance}</span>"
            f"<span>{escape(signal_type_label(cp.signal_type))}</span>"
            f"<span>{escape(topic_names.get(cp.topic_id, '未分类'))}</span>"
            f"<span>发现 {escape(fmt_dt(cp.first_seen_at))}</span>"
            "</div>"
            '<div class="knowledge-list-title">'
            f"{escape(cp.title)}"
            f'<span class="knowledge-level {level.lower()}">'
            f"{escape(LEVEL_LABEL[level])}</span>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        if expanded:
            action_col.caption("已展开")
        elif action_col.button(
            "收起" if is_open else "查看",
            key=f"toggle_knowledge_change_{cp.id}",
            width="stretch",
        ):
            if is_open:
                st.session_state.pop("_knowledge_open_change_id", None)
            else:
                st.session_state["_knowledge_open_change_id"] = cp.id
            st.rerun()
        if not is_open:
            return None

        st.markdown(
            '<div class="knowledge-detail-divider"></div>',
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
                return cp.id

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
                if cp.followup_snoozed_until:
                    st.caption(
                        "首页提醒已暂时隐藏至 "
                        f"{fmt_dt(cp.followup_snoozed_until)}"
                    )
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
                save = st.form_submit_button("保存调整")
                restore = (
                    st.form_submit_button("恢复首页提醒")
                    if cp.followup_snoozed_until
                    else False
                )
                if save:
                    cp.importance = new_importance
                    cp.signal_type = new_signal_type
                    cp.status = new_status
                    st.success("已保存。该调整会影响后续评分。")
                if restore:
                    cp.followup_snoozed_until = None
                    st.success("已恢复，该知识点可以重新进入今日重点。")
        st.caption(f"event_key · {escape(cp.event_key)}")
    return None


def _knowledge_pagination(total: int) -> int:
    total_pages = max(1, ceil(total / KNOWLEDGE_PAGE_SIZE))
    page = min(
        total_pages,
        max(1, int(st.session_state.get("knowledge_page", 1))),
    )
    st.session_state["knowledge_page"] = page
    start = (page - 1) * KNOWLEDGE_PAGE_SIZE + 1
    end = min(page * KNOWLEDGE_PAGE_SIZE, total)
    info_col, previous_col, next_col = st.columns(
        [4.8, .8, .8],
        vertical_alignment="center",
    )
    info_col.caption(f"共 {total} 条 · 当前 {start}–{end}")
    if previous_col.button(
        "上一页",
        key="knowledge_previous_page",
        width="stretch",
        disabled=page <= 1,
    ):
        st.session_state["knowledge_page"] = page - 1
        st.session_state.pop("_knowledge_open_change_id", None)
        st.rerun()
    if next_col.button(
        "下一页",
        key="knowledge_next_page",
        width="stretch",
        disabled=page >= total_pages,
    ):
        st.session_state["knowledge_page"] = page + 1
        st.session_state.pop("_knowledge_open_change_id", None)
        st.rerun()
    return page


def _query_int(key: str) -> int | None:
    try:
        return int(st.query_params.get(key, ""))
    except (TypeError, ValueError):
        return None


def _sync_filter_query(
    *,
    selected_topic: int | None,
    selected_level: str | None,
    selected_importance: int | None,
    selected_signals: list[str],
    selected_period: str | None,
    keyword: str,
) -> None:
    managed_keys = {
        "topic",
        "coverage",
        "importance_min",
        "signals",
        "period",
        "q",
    }
    desired = {
        key: value
        for key, value in {
            "topic": str(selected_topic) if selected_topic is not None else "",
            "coverage": selected_level or "",
            "importance_min": str(selected_importance)
            if selected_importance is not None
            else "",
            "signals": ",".join(selected_signals),
            "period": selected_period or "",
            "q": keyword.strip(),
        }.items()
        if value
    }
    current = {
        key: st.query_params.get(key)
        for key in managed_keys
        if st.query_params.get(key) not in (None, "")
    }
    if current == desired:
        return
    preserved = {
        key: value
        for key, value in st.query_params.to_dict().items()
        if key not in managed_keys and key != "change_point"
    }
    st.query_params.from_dict({**preserved, **desired})
    st.session_state["_knowledge_query_signature"] = (
        None,
        selected_topic,
        tuple(selected_signals),
        selected_level,
        selected_importance,
        selected_period,
        keyword.strip(),
    )


render()
