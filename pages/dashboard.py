"""Dashboard page: per-topic understanding scores (section 十七.1)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_radar.database import session_scope
from ai_radar.profile.sync_service import ProfileSyncService
from ai_radar.ui import dashboard_rows, fmt_dt, recent_jobs


def render() -> None:
    st.header("📊 Dashboard")

    with session_scope() as session:
        rows = dashboard_rows(session)
        last_sync = ProfileSyncService(session).last_success_time()
        last_error = ProfileSyncService(session).last_error()
        jobs = recent_jobs(session, limit=5)

    if not rows:
        st.info("尚未初始化领域数据，请检查 config/default_sources.yaml 并重启。")
        return

    st.subheader("领域了解度")
    for r in rows:
        topic = r["topic"]
        score = r["score"]
        delta = r["delta"]
        col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
        with col1:
            st.markdown(f"**{topic.name}**")
            st.caption(topic.description or "")
        with col2:
            arrow = "→"
            if delta < 0:
                arrow = f"↓{abs(delta):.1f}"
            elif delta > 0:
                arrow = f"↑{delta:.1f}"
            st.metric("了解度", f"{score:.0f}%", delta)
        with col3:
            st.progress(int(min(max(score, 0), 100)) / 100.0)
        with col4:
            st.caption(
                f"知识点权重 {r['total_weight']}  ·  未覆盖重要 {r['uncovered_important']}  ·  今日新增 {r['today_new']}"
            )
        st.divider()

    cols = st.columns(2)
    with cols[0]:
        st.subheader("最近 GitHub 记忆同步")
        if last_error:
            st.error(f"同步异常：{last_error}")
        st.write(f"最后一次成功时间：{fmt_dt(last_sync)}")
    with cols[1]:
        st.subheader("最近任务执行")
        if jobs:
            data = [
                {
                    "任务": j.job_type,
                    "状态": j.status,
                    "开始": fmt_dt(j.started_at),
                    "结果": j.message,
                }
                for j in jobs
            ]
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.caption("暂无任务记录")


render()
