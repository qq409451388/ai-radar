"""Today-first entry point for AI Radar."""
from __future__ import annotations

from html import escape

import streamlit as st

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.pipeline_runner import (
    enqueue_pipeline,
    get_active_pipeline_snapshot,
)
from ai_radar.services.radar_service import RadarService
from ai_radar.utils import compact_text
from ai_radar.ui import fmt_dt, signal_type_label


def render() -> None:
    st.markdown('<div class="page-kicker">Today</div>', unsafe_allow_html=True)
    st.title("今天该关注什么")

    with session_scope() as session:
        data = RadarService(session).load_home()
    active_pipeline = get_active_pipeline_snapshot()

    st.markdown(
        f"""
        <div class="today-summary">
          今日发现 <strong>{data.today_count}</strong> 个有效变化，
          近 7 天有 <strong>{data.recent_priority_count}</strong> 个值得重点关注；
          近 {data.score_window_days} 天仍有
          <strong>{data.important_gap_count}</strong> 个重要知识缺口。
        </div>
        """,
        unsafe_allow_html=True,
    )

    action_col, status_col = st.columns([1.2, 3.8], vertical_alignment="center")
    if action_col.button(
        "运行今日更新",
        type="primary",
        width="stretch",
        disabled=active_pipeline is not None,
    ):
        enqueue_pipeline("FULL_UPDATE")
        st.toast("完整更新已在后台启动", icon="🚀")
        st.rerun()
    if active_pipeline:
        status_col.caption(
            f"{active_pipeline['pipeline_label']}正在后台运行 · "
            "切换页面不会中断"
        )
    else:
        status_col.caption(
            f"最近完整更新：{fmt_dt(data.last_update_at)}"
        )

    if data.last_pipeline_status in ("FAILED", "INTERRUPTED"):
        st.error(
            "上次完整更新没有成功完成。"
            f"{data.last_pipeline_error or '请重新运行，或前往“自动化与设置”查看步骤详情。'}"
        )
    elif data.last_pipeline_status == "PARTIAL":
        st.warning(
            "上次完整更新有部分项目处理失败。"
            "请前往“自动化与设置”查看失败步骤并决定是否重试。"
        )

    st.markdown("## 今日重点")
    st.caption("优先展示今天和近 7 天的新变化；历史缺口只在重点不足时少量补充。")
    if not data.focus_items:
        _render_empty_state()
    else:
        for item in data.focus_items:
            _render_focus_item(item)

    st.markdown("## 按兴趣继续看")
    st.caption("分类数量来自近 7 天变化；知识缺口使用当前评分窗口。")
    interest_columns = st.columns(2)
    for index, entry in enumerate(data.interests):
        with interest_columns[index % 2]:
            with st.container(border=True):
                label_col, count_col = st.columns(
                    [4, 1],
                    vertical_alignment="center",
                )
                label_col.page_link(
                    "pages/knowledge.py",
                    label=entry.label,
                    query_params=entry.query_params,
                    width="stretch",
                )
                count_col.markdown(
                    f'<div class="interest-count">{entry.count} 条</div>',
                    unsafe_allow_html=True,
                )

    more_col, all_col, _ = st.columns([1.3, 1.3, 3])
    more_col.page_link(
        "pages/inbox.py",
        label="查看最近 7 天变化",
        query_params={"view": "changes", "period": "7d"},
        width="stretch",
    )
    all_col.page_link(
        "pages/knowledge.py",
        label="查看全部知识变化",
        width="stretch",
    )

    if data.topic_decline:
        decline = data.topic_decline
        if decline.declining_count == 1:
            label = f"近期下降最多：{decline.topic_name} {decline.delta:.0f}"
        else:
            label = (
                f"{decline.declining_count} 个领域近期覆盖率下降 · "
                f"{decline.topic_name} {decline.delta:.0f}"
            )
        st.page_link(
            "pages/progress.py",
            label=label,
            query_params={
                "view": "overview",
                "topic": str(decline.topic_id),
            },
            icon="📉",
        )


def _render_focus_item(item) -> None:
    with st.container(border=True):
        title_col, relation_col = st.columns(
            [4, 1.2],
            vertical_alignment="top",
        )
        title_col.markdown(
            f'<div class="focus-title">{escape(item.title)}</div>',
            unsafe_allow_html=True,
        )
        relation_col.markdown(
            f'<div class="focus-relation">{escape(item.relation)}</div>',
            unsafe_allow_html=True,
        )
        supplement = " · 历史缺口补充" if item.is_historical_supplement else ""
        st.caption(
            f"{signal_type_label(item.signal_type)} · {item.topic_name}"
            f"{supplement}"
        )
        st.markdown(
            f'<div class="focus-summary">{escape(compact_text(item.summary or "暂无摘要", 300))}</div>',
            unsafe_allow_html=True,
        )
        action_columns = st.columns([1, 1.15, 1, 3.5])
        action_columns[0].page_link(
            "pages/knowledge.py",
            label="查看详情",
            query_params={"change_point": str(item.change_point_id)},
            width="stretch",
        )
        if item.primary_source_url:
            action_columns[1].link_button(
                "官方来源",
                item.primary_source_url,
                width="stretch",
            )
        if action_columns[2].button(
            "忽略 7 天",
            key=f"snooze_home_{item.change_point_id}",
            type="tertiary",
            width="stretch",
        ):
            orchestrator.snooze_change_point(item.change_point_id, days=7)
            st.toast("已从今日重点隐藏 7 天，可在知识地图中恢复。")
            st.rerun()


def _render_empty_state() -> None:
    st.markdown(
        """
        <div class="today-empty">
          <strong>今天没有需要优先处理的新变化。</strong>
          <span>你可以运行今日更新，或继续查看最近变化和已有知识缺口。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    recent_col, gap_col, _ = st.columns([1.35, 1.35, 3])
    recent_col.page_link(
        "pages/inbox.py",
        label="查看最近 7 天变化",
        query_params={"view": "changes", "period": "7d"},
        width="stretch",
    )
    gap_col.page_link(
        "pages/knowledge.py",
        label="查看现有知识缺口",
        query_params={"coverage": "GAP", "importance_min": "3"},
        width="stretch",
    )


render()
