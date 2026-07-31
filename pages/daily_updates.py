"""今日动态 page: change points seen today / last 24h (section 十七.2)."""
from __future__ import annotations

from datetime import timedelta, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import or_, select

from ai_radar.database import session_scope
from ai_radar.models import ChangePoint, ChangePointSource, SourceItem
from ai_radar.ui import (
    coverage_color,
    fmt_date,
    fmt_dt,
    importance_label,
    latest_coverage,
    sources_for_change_point,
    today_change_points,
)
from ai_radar.utils import utc_to_local


def render() -> None:
    st.header("📅 今日动态")
    window = st.radio(
        "时间范围", ["今天", "最近24小时"], horizontal=True, key="daily_window"
    )
    with session_scope() as session:
        if window == "今天":
            cps = today_change_points(session)
        else:
            from ai_radar.utils import local_today

            start = local_today() - timedelta(days=1)
            cps = list(
                session.execute(
                    select(ChangePoint)
                    .where(ChangePoint.first_seen_at >= start)
                    .order_by(ChangePoint.importance.desc(), ChangePoint.first_seen_at.desc())
                ).scalars()
            )
        if not cps:
            st.info("当前时间范围内没有新增知识变化点。")
            return
        st.caption(f"共 {len(cps)} 个知识变化点")
        for cp in cps:
            with st.container(border=True):
                cols = st.columns([4, 1, 1, 1])
                cols[0].markdown(f"#### {cp.title}")
                cols[1].markdown(f"**{importance_label(cp.importance)}**")
                topic_name = cp.topic.name if cp.topic else "—"
                cols[2].caption(topic_name)
                cols[3].caption(fmt_date(cp.first_seen_at))
                st.write(cp.summary or "（无摘要）")
                if cp.why_it_matters:
                    st.info(f"为什么重要：{cp.why_it_matters}")
                cov = latest_coverage(session, cp.id)
                if cov:
                    color = coverage_color(cov.coverage_level)
                    st.markdown(
                        f"<span style='color:{color}'>覆盖：{cov.coverage_level} "
                        f"({cov.coverage_coefficient:.2f})</span> · 置信度 {cov.confidence:.2f}",
                        unsafe_allow_html=True,
                    )
                    if cov.rationale:
                        st.caption(cov.rationale)
                else:
                    st.caption("覆盖：尚未评估")
                items = sources_for_change_point(session, cp.id)
                if items:
                    st.caption("官方来源：")
                    for it in items[:5]:
                        st.markdown(f"- [{it.title or it.url}]({it.url})")
                if cp.event_key:
                    st.caption(f"event_key: `{cp.event_key}`")


render()
