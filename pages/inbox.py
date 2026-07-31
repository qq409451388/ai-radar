"""Unified intelligence inbox for collected items and distilled changes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy import func, or_, select

from ai_radar import orchestrator
from ai_radar.bootstrap import DESIGN_SIGNAL_TYPES
from ai_radar.config import get_config
from ai_radar.database import session_scope
from ai_radar.models import (
    ChangePoint,
    ChangePointSource,
    SourceConfig,
    SourceItem,
    Topic,
)
from ai_radar.pipeline_runner import enqueue_pipeline, get_active_pipeline_snapshot
from ai_radar.ui import (
    fmt_dt,
    latest_coverage,
    signal_action_hint,
    signal_sort_key,
    signal_type_label,
    sources_for_change_point,
)

STATUS_LABEL = {
    "PENDING": "待分析",
    "SUCCESS": "已形成知识点",
    "IGNORED": "已过滤/归档",
    "FAILED": "分析失败",
}


def render() -> None:
    cfg = get_config()
    st.markdown('<div class="page-kicker">Intelligence inbox</div>', unsafe_allow_html=True)
    st.title("情报收件箱")
    st.markdown(
        '<div class="page-subtitle">先处理值得看的变化；原始资讯留在后台，可追溯但不打扰。</div>',
        unsafe_allow_html=True,
    )

    with session_scope() as session:
        counts = dict(
            session.execute(
                select(SourceItem.analyze_status, func.count(SourceItem.id)).group_by(
                    SourceItem.analyze_status
                )
            ).all()
        )
        source_count = session.scalar(
            select(func.count(SourceConfig.id)).where(SourceConfig.enabled == True)  # noqa: E712
        ) or 0
        design_count = session.scalar(
            select(func.count(ChangePoint.id)).where(
                ChangePoint.status == "ACTIVE",
                ChangePoint.signal_type.in_(DESIGN_SIGNAL_TYPES),
            )
        ) or 0
        oldest_pending = session.scalar(
            select(func.min(SourceItem.published_at)).where(
                SourceItem.analyze_status == "PENDING"
            )
        )

    cols = st.columns(4)
    cols[0].metric("待分析", counts.get("PENDING", 0))
    cols[1].metric("设计信号", design_count)
    cols[2].metric("自动过滤", counts.get("IGNORED", 0))
    cols[3].metric("启用来源", source_count)

    active_pipeline = get_active_pipeline_snapshot()
    action_cols = st.columns([1.5, 1.2, 3.1])
    if action_cols[0].button(
        f"后台更新情报（每批 {cfg.analyze_batch_size}）",
        type="primary",
        width="stretch",
        disabled=active_pipeline is not None,
    ):
        enqueue_pipeline("INTELLIGENCE")
        st.toast("情报更新已在后台启动", icon="🚀")
        st.rerun()
    if action_cols[1].button("归档 180 天前积压", width="stretch"):
        result = orchestrator.archive_stale_pending(180)
        st.success(f"已归档 {result['archived']} 条历史积压，可在“已处理”中查看。")
        st.rerun()
    if active_pipeline:
        action_cols[2].caption(
            f"{active_pipeline['pipeline_label']}正在后台运行；切换页面不会中断。"
        )
    else:
        action_cols[2].caption(
            f"最老待处理资讯：{fmt_dt(oldest_pending)}。"
            "归档只改变处理状态，不删除原始数据。"
        )

    tab_design, tab_changes, tab_queue, tab_done = st.tabs(
        [
            f"设计信号 · {design_count}",
            "全部变化",
            f"待处理队列 · {counts.get('PENDING', 0)}",
            "已处理与失败",
        ]
    )

    with tab_design:
        _render_changes(design_only=True)
    with tab_changes:
        _render_changes()
    with tab_queue:
        _render_items(statuses=["PENDING"])
    with tab_done:
        _render_items(statuses=["SUCCESS", "IGNORED", "FAILED"])


def _render_changes(design_only: bool = False) -> None:
    range_label = st.segmented_control(
        "时间范围",
        ["7 天", "30 天", "全部"],
        default="30 天",
        key="inbox_change_range",
    )
    days = {"7 天": 7, "30 天": 30}.get(range_label)
    with session_scope() as session:
        stmt = (
            select(ChangePoint)
            .where(ChangePoint.status == "ACTIVE")
            .order_by(ChangePoint.importance.desc(), ChangePoint.first_seen_at.desc())
        )
        if days:
            date_column = (
                ChangePoint.last_seen_at
                if design_only
                else ChangePoint.first_seen_at
            )
            stmt = stmt.where(
                date_column >= datetime.now(timezone.utc) - timedelta(days=days)
            )
        if design_only:
            stmt = stmt.where(ChangePoint.signal_type.in_(DESIGN_SIGNAL_TYPES))
        cps = list(session.execute(stmt).scalars())
        cps.sort(key=signal_sort_key, reverse=True)
        topic_names = {
            topic.id: topic.name
            for topic in session.execute(select(Topic)).scalars()
        }
        if not cps:
            st.info("这个时间范围内还没有提炼出知识变化。先运行一批分析。")
            return
        for cp in cps:
            cov = latest_coverage(session, cp.id)
            level = cov.coverage_level if cov else "NONE"
            with st.container(border=True):
                title_col, meta_col = st.columns([4, 1.2])
                title_col.markdown(f"### {cp.title}")
                meta_col.markdown(
                    f"`{signal_type_label(cp.signal_type)}`  \n"
                    f"`重要度 {cp.importance}`  \n"
                    f"`{level}`"
                )
                st.caption(
                    f"{topic_names.get(cp.topic_id, '未分类')} · "
                    f"首次发现 {fmt_dt(cp.first_seen_at)}"
                )
                st.write(cp.summary or "暂无摘要")
                if cp.why_it_matters:
                    st.info(cp.why_it_matters, icon="💡")
                st.caption(f"建议下一步：{signal_action_hint(cp.signal_type)}")
                sources = sources_for_change_point(session, cp.id)
                if len(sources) >= 2:
                    st.success(f"已有 {len(sources)} 个来源共同确认这个变化。")
                if sources:
                    st.markdown(
                        " · ".join(
                            f"[{item.title or '官方来源'}]({item.url})"
                            for item in sources[:4]
                        )
                    )


def _render_items(statuses: list[str]) -> None:
    with session_scope() as session:
        sources = list(
            session.execute(select(SourceConfig).order_by(SourceConfig.name)).scalars()
        )
        source_names = {source.id: source.name for source in sources}
        filter_cols = st.columns([1.5, 1.2, 2.3])
        selected_source = filter_cols[0].selectbox(
            "来源",
            [None] + [source.id for source in sources],
            format_func=lambda value: "全部来源"
            if value is None
            else source_names[value],
            key=f"source_{'_'.join(statuses)}",
        )
        selected_status = filter_cols[1].selectbox(
            "状态",
            statuses,
            format_func=lambda value: STATUS_LABEL[value],
            key=f"status_{'_'.join(statuses)}",
        )
        keyword = filter_cols[2].text_input(
            "搜索标题或正文", key=f"keyword_{'_'.join(statuses)}"
        )
        stmt = (
            select(SourceItem)
            .where(SourceItem.analyze_status == selected_status)
            .order_by(
                SourceItem.published_at.desc().nullslast(),
                SourceItem.collected_at.desc(),
            )
            .limit(100)
        )
        if selected_source is not None:
            stmt = stmt.where(SourceItem.source_config_id == selected_source)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    SourceItem.title.ilike(like),
                    SourceItem.raw_content.ilike(like),
                )
            )
        items = list(session.execute(stmt).scalars())
        links = {}
        if items:
            links = dict(
                session.execute(
                    select(
                        ChangePointSource.source_item_id,
                        ChangePointSource.change_point_id,
                    ).where(
                        ChangePointSource.source_item_id.in_(
                            [item.id for item in items]
                        )
                    )
                ).all()
            )

    st.caption(f"显示最近 {len(items)} 条")
    for item in items:
        with st.expander(
            f"{STATUS_LABEL[item.analyze_status]} · {item.title or item.url or f'#{item.id}'}"
        ):
            st.caption(
                f"{source_names.get(item.source_config_id, '未知来源')} · "
                f"发布 {fmt_dt(item.published_at)} · "
                f"重试 {item.retry_count} 次"
            )
            if item.url:
                st.markdown(f"[打开官方来源]({item.url})")
            if item.raw_content:
                st.write(item.raw_content[:1800])
            if item.analyze_error:
                if item.analyze_status == "FAILED":
                    st.error(item.analyze_error)
                else:
                    st.caption(item.analyze_error)
            if links.get(item.id):
                st.success(f"已关联知识变化点 #{links[item.id]}")
            if item.analyze_status in ("FAILED", "IGNORED"):
                if st.button("重新加入分析队列", key=f"requeue_{item.id}"):
                    orchestrator.requeue_source_item(item.id)
                    st.rerun()


render()
