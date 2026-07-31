"""系统任务 page: trigger jobs and view logs (section 十七.7)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.ui import fmt_dt, recent_jobs


def _run(label: str, fn) -> None:
    if st.button(label, key=f"btn_{label}"):
        with st.spinner(f"执行中：{label}…"):
            try:
                result = fn()
                st.success(f"完成：{result}")
            except Exception as exc:
                st.error(f"失败：{exc}")


def render() -> None:
    st.header("⚙️ 系统任务")
    st.caption("每个任务都会写入 job_log。LLM 相关任务需要配置 LLM_API_KEY。")

    cols = st.columns(2)
    with cols[0]:
        st.subheader("采集与分析")
        _run("立即采集全部资讯", orchestrator.collect_all_sources)
        _run("分析待处理资讯", orchestrator.analyze_pending_items)

    with cols[1]:
        st.subheader("记忆与覆盖")
        _run("同步 GitHub 记忆", orchestrator.sync_profile)
        _run("重新抽取个人事实", lambda: orchestrator.extract_facts(force=True))

    cols = st.columns(2)
    with cols[0]:
        st.subheader("评估")
        _run("仅评估新增知识变化点", orchestrator.assess_new_change_points)
        _run("重新评估全部知识变化点", orchestrator.assess_all_change_points)
    with cols[1]:
        st.subheader("评分")
        _run("重新计算评分", orchestrator.rescore)
        _run("保存今日快照", orchestrator.save_snapshot)

    st.divider()
    st.subheader("任务日志")
    with session_scope() as session:
        jobs = recent_jobs(session, limit=50)
        if jobs:
            data = [
                {
                    "任务": j.job_type,
                    "状态": j.status,
                    "开始": fmt_dt(j.started_at),
                    "结束": fmt_dt(j.finished_at),
                    "处理": j.processed_count,
                    "成功": j.success_count,
                    "失败": j.failed_count,
                    "信息": j.message,
                }
                for j in jobs
            ]
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.caption("暂无任务记录")


render()
