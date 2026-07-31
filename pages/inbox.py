"""Unified intelligence inbox for collected items and distilled changes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from math import ceil

import streamlit as st
from sqlalchemy import func, or_, select

from ai_radar import orchestrator
from ai_radar.bootstrap import (
    DESIGN_SIGNAL_TYPES,
    SOURCE_TYPE_COMMUNITY,
    source_kind_label,
)
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
from ai_radar.utils import compact_text

STATUS_LABEL = {
    "PENDING": "待分析",
    "SUCCESS": "已形成知识点",
    "IGNORED": "已过滤/归档",
    "FAILED": "分析失败",
}
SOURCE_TONE = {
    "RSS": "rss",
    "WEB_PAGE": "web",
    "GITHUB_RELEASE": "release",
    "GITHUB_COMMIT": "commit",
    "COMMUNITY": "community",
}
PAGE_SIZE = 20


def render() -> None:
    cfg = get_config()
    query_view = st.query_params.get("view", "design")
    if query_view not in {"design", "changes", "queue", "done"}:
        query_view = "design"
    query_period = st.query_params.get("period")
    query_topic = _query_int("topic")
    query_source = _query_int("source")
    query_signals = [
        value
        for value in st.query_params.get("signals", "").split(",")
        if value
        in {"STANDARD", "ARCHITECTURE", "CONCEPT", "CAPABILITY", "RELEASE"}
    ]
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
        design_count = session.scalar(
            select(func.count(ChangePoint.id)).where(
                ChangePoint.status == "ACTIVE",
                ChangePoint.signal_type.in_(DESIGN_SIGNAL_TYPES),
            )
        ) or 0
        change_count = session.scalar(
            select(func.count(ChangePoint.id)).where(
                ChangePoint.status == "ACTIVE"
            )
        ) or 0
        oldest_pending = session.scalar(
            select(func.min(SourceItem.published_at)).where(
                SourceItem.analyze_status == "PENDING"
            )
        )

    st.markdown(
        '<div class="inbox-brief">'
        f'<span><strong>{counts.get("PENDING", 0)}</strong> 待分析</span>'
        f'<span><strong>{counts.get("SUCCESS", 0)}</strong> 已形成知识</span>'
        f'<span><strong>{counts.get("IGNORED", 0)}</strong> 已归档</span>'
        f'<span class="{"has-error" if counts.get("FAILED", 0) else ""}">'
        f'<strong>{counts.get("FAILED", 0)}</strong> 分析失败</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    active_pipeline = get_active_pipeline_snapshot()
    action_cols = st.columns([1.35, 4.65], vertical_alignment="center")
    if action_cols[0].button(
        "更新情报",
        type="primary",
        width="stretch",
        disabled=active_pipeline is not None,
    ):
        enqueue_pipeline("INTELLIGENCE")
        st.toast("情报更新已在后台启动", icon="🚀")
        st.rerun()
    if active_pipeline:
        action_cols[1].caption(
            f"{active_pipeline['pipeline_label']}正在后台运行；切换页面不会中断。"
        )
    else:
        action_cols[1].caption(
            f"每次自动处理全部积压（并发 {cfg.ai_concurrency}）"
            f" · 最老待处理资讯：{fmt_dt(oldest_pending)}"
        )

    view_labels = {
        "design": f"设计信号 {design_count}",
        "changes": f"全部变化 {change_count}",
        "queue": f"待处理 {counts.get('PENDING', 0)}",
        "done": (
            "已处理 "
            f"{counts.get('SUCCESS', 0) + counts.get('IGNORED', 0) + counts.get('FAILED', 0)}"
        ),
    }
    view_signature = st.session_state.get("_inbox_view_query")
    if view_signature != query_view:
        st.session_state["_inbox_view_query"] = query_view
        st.session_state["inbox_view"] = query_view
    selected_view = st.segmented_control(
        "查看内容",
        list(view_labels),
        format_func=lambda value: view_labels[value],
        required=True,
        key="inbox_view",
        label_visibility="collapsed",
        width="stretch",
    )

    if selected_view == "design":
        _render_changes(
            design_only=True,
            query_period=query_period,
            query_topic=query_topic,
            query_source=query_source,
            query_signals=query_signals,
        )
    elif selected_view == "changes":
        _render_changes(
            query_period=query_period,
            query_topic=query_topic,
            query_source=query_source,
            query_signals=query_signals,
        )
    elif selected_view == "queue":
        _render_items(statuses=["PENDING"], query_source=query_source)
    else:
        _render_items(
            statuses=["SUCCESS", "IGNORED", "FAILED"],
            query_source=query_source,
        )


def _render_changes(
    design_only: bool = False,
    *,
    query_period: str | None = None,
    query_topic: int | None = None,
    query_source: int | None = None,
    query_signals: list[str] | None = None,
) -> None:
    view_key = "design" if design_only else "all"
    with session_scope() as session:
        topics = list(session.execute(select(Topic).order_by(Topic.id)).scalars())
        topic_names = {topic.id: topic.name for topic in topics}
        configured_sources = list(
            session.execute(select(SourceConfig).order_by(SourceConfig.name)).scalars()
        )
        source_names = {
            source.id: source.name for source in configured_sources
        }
        source_types = {
            source.id: source.source_type for source in configured_sources
        }
        source_options = [None] + [source.id for source in configured_sources]
        topic_options = [None] + [topic.id for topic in topics]
        signal_options = [
            "STANDARD",
            "ARCHITECTURE",
            "CONCEPT",
            "CAPABILITY",
            "RELEASE",
        ]
        default_range = {
            "7d": "7 天",
            "30d": "30 天",
        }.get(query_period, "30 天")
        state_signature = (
            query_period,
            query_topic,
            query_source,
            tuple(query_signals or []),
        )
        signature_key = f"_inbox_query_signature_{view_key}"
        if st.session_state.get(signature_key) != state_signature:
            st.session_state[signature_key] = state_signature
            st.session_state[f"inbox_change_range_{view_key}"] = default_range
            st.session_state[f"inbox_change_topic_{view_key}"] = (
                query_topic if query_topic in topic_options else None
            )
            st.session_state[f"inbox_change_source_{view_key}"] = (
                query_source if query_source in source_options else None
            )
            st.session_state[f"inbox_change_signals_{view_key}"] = [
                value
                for value in (query_signals or [])
                if value in signal_options
            ]

        primary_filters = st.columns([1.1, 1.35, 1.55])
        range_label = primary_filters[0].segmented_control(
            "时间范围",
            ["7 天", "30 天", "全部"],
            key=f"inbox_change_range_{view_key}",
        )
        selected_topic = primary_filters[1].selectbox(
            "领域",
            topic_options,
            format_func=lambda value: "全部领域"
            if value is None
            else topic_names[value],
            key=f"inbox_change_topic_{view_key}",
        )
        selected_source = primary_filters[2].selectbox(
            "资讯源",
            source_options,
            format_func=lambda value: "全部资讯源"
            if value is None
            else (
                f"{source_kind_label(source_types[value])} · "
                f"{source_names[value]}"
            ),
            key=f"inbox_change_source_{view_key}",
        )
        selected_signals = st.multiselect(
            "信号类型",
            signal_options,
            format_func=signal_type_label,
            placeholder="全部类型",
            key=f"inbox_change_signals_{view_key}",
        )
        days = {"7 天": 7, "30 天": 30}.get(range_label)
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
        if selected_topic is not None:
            stmt = stmt.where(ChangePoint.topic_id == selected_topic)
        if selected_source is not None:
            stmt = stmt.where(
                ChangePoint.id.in_(
                    select(ChangePointSource.change_point_id)
                    .join(
                        SourceItem,
                        SourceItem.id == ChangePointSource.source_item_id,
                    )
                    .where(SourceItem.source_config_id == selected_source)
                )
            )
        if selected_signals:
            stmt = stmt.where(ChangePoint.signal_type.in_(selected_signals))

        filter_signature = (
            range_label,
            selected_topic,
            selected_source,
            tuple(selected_signals),
        )
        page_key = f"inbox_change_page_{view_key}"
        _reset_page_on_filter_change(
            page_key,
            filter_signature,
        )
        total = int(
            session.scalar(
                select(func.count()).select_from(
                    stmt.order_by(None).subquery()
                )
            )
            or 0
        )
        page = _pagination(total, page_key)
        cps = list(
            session.execute(
                stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
            ).scalars()
        )
        cps.sort(key=signal_sort_key, reverse=True)
        if not cps:
            st.info("当前筛选下没有知识变化。可以调整时间或信号类型。")
            return
        for cp in cps:
            cov = latest_coverage(session, cp.id)
            level = cov.coverage_level if cov else "NONE"
            sources = sources_for_change_point(session, cp.id)
            source_name, source_tone, source_kind, extra_sources = _primary_source(
                sources,
                source_names,
                source_types,
            )
            is_open = st.session_state.get("_inbox_open_change_id") == cp.id
            with st.container(
                border=True,
                key=f"inbox_change_card_{cp.id}",
            ):
                title_col, action_col = st.columns(
                    [5.2, .8],
                    vertical_alignment="center",
                )
                title_col.markdown(
                    _item_heading(
                        cp.title or f"知识变化 #{cp.id}",
                        source_name,
                        source_tone,
                        (
                            f"{signal_type_label(cp.signal_type)} · "
                            f"{topic_names.get(cp.topic_id, '未分类')} · "
                            f"{fmt_dt(cp.first_seen_at)}"
                        ),
                        status_text=f"重要度 {cp.importance}",
                        status_class=(
                            "priority" if cp.importance >= 5 else "processed"
                        ),
                        source_kind=source_kind,
                        extra_sources=extra_sources,
                    ),
                    unsafe_allow_html=True,
                )
                if action_col.button(
                    "收起" if is_open else "查看",
                    key=f"toggle_change_{cp.id}",
                    width="stretch",
                ):
                    if is_open:
                        st.session_state.pop("_inbox_open_change_id", None)
                    else:
                        st.session_state["_inbox_open_change_id"] = cp.id
                    st.rerun()
                if not is_open:
                    continue

                st.markdown(
                    '<div class="inbox-detail-divider"></div>',
                    unsafe_allow_html=True,
                )
                st.write(compact_text(cp.summary or "暂无摘要", 300))
                if cp.why_it_matters:
                    st.info(cp.why_it_matters, icon="💡")
                st.caption(
                    f"与你的关系：{level} · "
                    f"建议下一步：{signal_action_hint(cp.signal_type)}"
                )
                source_config_ids = {
                    item.source_config_id for item in sources
                }
                official_count = sum(
                    1
                    for source_id in source_config_ids
                    if source_types.get(source_id) != SOURCE_TYPE_COMMUNITY
                )
                community_count = len(source_config_ids) - official_count
                if official_count >= 2:
                    st.success(
                        f"已有 {official_count} 个官方来源共同确认这个变化。"
                    )
                elif official_count and community_count:
                    st.info(
                        f"已有官方信息，并有 {community_count} 个社区来源参与讨论。"
                    )
                elif community_count:
                    st.warning(
                        f"来自 {community_count} 个社区讨论源，仍需官方信息确认。"
                    )
                if sources:
                    st.markdown(
                        " · ".join(
                            f"[{item.display_title or item.title or '查看来源'}]({item.url})"
                            for item in sources[:4]
                        )
                    )


def _render_items(
    statuses: list[str],
    *,
    query_source: int | None = None,
) -> None:
    view_key = "queue" if statuses == ["PENDING"] else "done"
    with session_scope() as session:
        sources = list(
            session.execute(select(SourceConfig).order_by(SourceConfig.name)).scalars()
        )
        source_names = {source.id: source.name for source in sources}
        source_types = {source.id: source.source_type for source in sources}
        source_options = [None] + [source.id for source in sources]
        status_counts = dict(
            session.execute(
                select(
                    SourceItem.analyze_status,
                    func.count(SourceItem.id),
                )
                .where(SourceItem.analyze_status.in_(statuses))
                .group_by(SourceItem.analyze_status)
            ).all()
        )

        if len(statuses) > 1:
            status_labels = {
                status: f"{STATUS_LABEL[status]} {status_counts.get(status, 0)}"
                for status in statuses
            }
            selected_status = st.segmented_control(
                "处理状态",
                statuses,
                default=statuses[0],
                required=True,
                format_func=lambda value: status_labels[value],
                key="inbox_done_status",
                label_visibility="collapsed",
                width="stretch",
            )
        else:
            selected_status = statuses[0]
            archive_col, note_col = st.columns(
                [1.25, 4.75],
                vertical_alignment="center",
            )
            if archive_col.button(
                "归档 180 天前积压",
                key="archive_stale_inbox",
                width="stretch",
            ):
                result = orchestrator.archive_stale_pending(180)
                st.toast(
                    f"已归档 {result['archived']} 条历史积压",
                    icon="✅",
                )
                st.rerun()
            note_col.caption(
                "归档只改变处理状态，不删除原始资讯。"
            )

        source_query_key = f"_inbox_item_source_query_{view_key}"
        if st.session_state.get(source_query_key) != query_source:
            st.session_state[source_query_key] = query_source
            st.session_state[f"inbox_source_{view_key}"] = (
                query_source if query_source in source_options else None
            )

        filter_cols = st.columns([1.5, 3.5])
        selected_source = filter_cols[0].selectbox(
            "来源",
            source_options,
            format_func=lambda value: "全部来源"
            if value is None
            else (
                f"{source_kind_label(source_types[value])} · "
                f"{source_names[value]}"
            ),
            key=f"inbox_source_{view_key}",
        )
        keyword = filter_cols[1].text_input(
            "搜索标题或正文",
            key=f"inbox_keyword_{view_key}",
            placeholder="输入关键词",
        )
        stmt = (
            select(SourceItem)
            .where(SourceItem.analyze_status == selected_status)
            .order_by(
                SourceItem.published_at.desc().nullslast(),
                SourceItem.collected_at.desc(),
            )
        )
        if selected_source is not None:
            stmt = stmt.where(SourceItem.source_config_id == selected_source)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    SourceItem.title.ilike(like),
                    SourceItem.display_title.ilike(like),
                    SourceItem.display_summary.ilike(like),
                    SourceItem.raw_content.ilike(like),
                )
            )

        filter_signature = (
            selected_status,
            selected_source,
            keyword.strip(),
        )
        page_key = f"inbox_item_page_{view_key}"
        _reset_page_on_filter_change(page_key, filter_signature)
        total = int(
            session.scalar(
                select(func.count()).select_from(
                    stmt.order_by(None).subquery()
                )
            )
            or 0
        )
        page = _pagination(total, page_key)
        items = list(
            session.execute(
                stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
            ).scalars()
        )
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

    if not items:
        empty_copy = (
            "没有等待分析的资讯。运行更新后，新内容会出现在这里。"
            if selected_status == "PENDING"
            else f"当前没有{STATUS_LABEL[selected_status]}的资讯。"
        )
        st.info(empty_copy)
        return

    for item in items:
        source_name = source_names.get(item.source_config_id, "未知来源")
        source_type = source_types.get(item.source_config_id, "")
        source_tone = SOURCE_TONE.get(
            source_type,
            "neutral",
        )
        is_open = st.session_state.get("_inbox_open_item_id") == item.id
        with st.container(
            border=True,
            key=f"inbox_item_card_{item.id}",
        ):
            title_col, action_col = st.columns(
                [5.2, .8],
                vertical_alignment="center",
            )
            meta = f"发布 {fmt_dt(item.published_at)}"
            if item.retry_count:
                meta += f" · 已重试 {item.retry_count} 次"
            title_col.markdown(
                _item_heading(
                    item.display_title
                    or item.title
                    or item.url
                    or f"资讯 #{item.id}",
                    source_name,
                    source_tone,
                    meta,
                    status_text=STATUS_LABEL[item.analyze_status],
                    status_class=_status_class(item.analyze_status),
                    source_kind=source_kind_label(source_type),
                ),
                unsafe_allow_html=True,
            )
            if action_col.button(
                "收起" if is_open else "查看",
                key=f"toggle_item_{item.id}",
                width="stretch",
            ):
                if is_open:
                    st.session_state.pop("_inbox_open_item_id", None)
                else:
                    st.session_state["_inbox_open_item_id"] = item.id
                st.rerun()
            if not is_open:
                continue

            st.markdown(
                '<div class="inbox-detail-divider"></div>',
                unsafe_allow_html=True,
            )
            if item.url:
                st.markdown(f"[打开来源]({item.url})")
            display_summary = (
                item.display_summary
                or (item.raw_content or "")[:300]
            )
            if display_summary:
                st.write(display_summary[:300])
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


def _item_heading(
    title: str,
    source_name: str,
    source_tone: str,
    meta: str,
    *,
    status_text: str,
    status_class: str,
    source_kind: str,
    extra_sources: int = 0,
) -> str:
    source_suffix = f" +{extra_sources}" if extra_sources else ""
    return (
        '<div class="inbox-list-heading">'
        '<div class="inbox-list-meta">'
        f'<span class="inbox-status {escape(status_class)}">'
        f"{escape(status_text)}</span>"
        f"<span>{escape(meta)}</span>"
        "</div>"
        '<div class="inbox-list-title">'
        f"{escape(compact_text(title, 80))} "
        f'<span class="inbox-source-kind {"community" if source_kind == "社区讨论" else "official"}">'
        f"{escape(source_kind)}</span>"
        f'<span class="inbox-source-inline {escape(source_tone)}">'
        f"· {escape(source_name)}{source_suffix}</span>"
        "</div>"
        "</div>"
    )


def _primary_source(
    items: list[SourceItem],
    source_names: dict[int, str],
    source_types: dict[int, str],
) -> tuple[str, str, str, int]:
    source_ids = list(
        dict.fromkeys(item.source_config_id for item in items)
    )
    if not source_ids:
        return "来源待补充", "neutral", "来源未知", 0
    source_id = source_ids[0]
    source_type = source_types.get(source_id, "")
    return (
        source_names.get(source_id, "未知来源"),
        SOURCE_TONE.get(source_type, "neutral"),
        source_kind_label(source_type),
        max(0, len(source_ids) - 1),
    )


def _status_class(status: str) -> str:
    return {
        "PENDING": "pending",
        "SUCCESS": "processed",
        "IGNORED": "archived",
        "FAILED": "failed",
    }.get(status, "neutral")


def _reset_page_on_filter_change(
    page_key: str,
    signature: tuple,
) -> None:
    signature_key = f"_{page_key}_filter"
    if st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[page_key] = 1


def _pagination(total: int, page_key: str) -> int:
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = min(
        total_pages,
        max(1, int(st.session_state.get(page_key, 1))),
    )
    st.session_state[page_key] = page
    start = (page - 1) * PAGE_SIZE + 1 if total else 0
    end = min(page * PAGE_SIZE, total)
    info_col, previous_col, next_col = st.columns(
        [4.8, .8, .8],
        vertical_alignment="center",
    )
    info_col.caption(
        f"共 {total} 条 · 当前 {start}–{end}"
        if total
        else "当前没有内容"
    )
    if previous_col.button(
        "上一页",
        key=f"{page_key}_previous",
        width="stretch",
        disabled=page <= 1,
    ):
        st.session_state[page_key] = page - 1
        st.rerun()
    if next_col.button(
        "下一页",
        key=f"{page_key}_next",
        width="stretch",
        disabled=page >= total_pages,
    ):
        st.session_state[page_key] = page + 1
        st.rerun()
    return page


def _query_int(key: str) -> int | None:
    try:
        return int(st.query_params.get(key, ""))
    except (TypeError, ValueError):
        return None


render()
