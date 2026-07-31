"""Operational history, schedules, token usage, and configuration health."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import Integer, func, select

from ai_radar.config import get_config
from ai_radar.database import session_scope
from ai_radar.models import (
    JobLog,
    LlmResponseCache,
    LlmUsageLog,
    ProfileSourceFile,
    SourceItem,
)
from ai_radar.scheduler import get_scheduler
from ai_radar.ui import fmt_dt


SCHEDULE_COPY = {
    "daily_morning_pipeline": {
        "name": "获取今天的新资讯",
        "time": "每天 08:00",
        "description": "从已开启的资讯源获取内容，并完成第一轮 AI 分析。",
    },
    "sync_profile": {
        "name": "同步我的知识记录",
        "time": "每天 09:00",
        "description": "读取记忆仓库的新内容，更新与你有关的知识证据。",
    },
    "daily_evening_pipeline": {
        "name": "整理今天的知识进展",
        "time": "每天 23:00",
        "description": "评估新变化与个人记录的关系，并保存今日进展。",
    },
}


def render() -> None:
    cfg = get_config()
    st.markdown('<div class="page-kicker">Operations</div>', unsafe_allow_html=True)
    st.title("自动化与设置")
    st.markdown(
        '<div class="page-subtitle">'
        "这里保留运行结果和系统健康度。需要立即重跑时，请使用左侧醒目的“数据更新中心”。"
        "</div>",
        unsafe_allow_html=True,
    )

    jobs_tab, usage_tab, config_tab = st.tabs(
        ["运行记录", "Token 与缓存", "配置状态"]
    )
    with jobs_tab:
        _render_operations()
    with usage_tab:
        _render_usage()
    with config_tab:
        _render_config(cfg)


def _render_operations() -> None:
    with session_scope() as session:
        counts = dict(
            session.execute(
                select(SourceItem.analyze_status, func.count(SourceItem.id)).group_by(
                    SourceItem.analyze_status
                )
            ).all()
        )
        extraction_failed = session.scalar(
            select(func.count(ProfileSourceFile.id)).where(
                ProfileSourceFile.extraction_status == "FAILED"
            )
        ) or 0
        # Keep this intentionally bounded: the page is an operational glance,
        # not an unbounded audit log.
        jobs = list(
            session.execute(
                select(JobLog).order_by(JobLog.id.desc()).limit(20)
            ).scalars()
        )

    st.markdown("### 当前处理状态")
    metrics = st.columns(4)
    metrics[0].metric("待分析", counts.get("PENDING", 0))
    metrics[1].metric("分析失败", counts.get("FAILED", 0))
    metrics[2].metric("记忆抽取失败", extraction_failed)
    metrics[3].metric(
        "最近一次任务",
        _job_status_label(jobs[0].status) if jobs else "还没有",
        _job_type_label(jobs[0].job_type) if jobs else None,
    )
    st.caption("需要完整处理积压时，请点击左侧栏“数据更新中心”，再选择完整更新。")

    st.markdown("### 自动更新计划")
    scheduled = {
        job.id: job for job in get_scheduler().get_jobs()
    }
    if scheduled:
        for job_id, copy in SCHEDULE_COPY.items():
            job = scheduled.get(job_id)
            if job is None:
                continue
            with st.container(border=True):
                title_col, time_col = st.columns([3, 1])
                title_col.markdown(f"**{copy['name']}**")
                title_col.caption(copy["description"])
                time_col.markdown(f"**{copy['time']}**")
                time_col.caption(
                    f"下次：{fmt_dt(getattr(job, 'next_run_time', None))}"
                )
        st.caption(
            "自动更新只在 AI Radar 保持运行时执行。错过计划后，可从左侧数据更新中心手动补跑。"
        )
    else:
        st.info("自动更新目前已关闭；手动更新仍可正常使用。")

    st.markdown("### 最近 20 条任务")
    if jobs:
        data = [
            {
                "任务": _job_type_label(job.job_type),
                "状态": _job_status_label(job.status),
                "开始时间": fmt_dt(job.started_at),
                "耗时": _duration(job.started_at, job.finished_at),
                "处理": job.processed_count,
                "成功": job.success_count,
                "失败": job.failed_count,
                "说明": job.message,
            }
            for job in jobs
        ]
        st.dataframe(pd.DataFrame(data), width="stretch", hide_index=True)
    else:
        st.info("还没有任务记录。")


def _render_usage() -> None:
    day_cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    month_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    with session_scope() as session:
        today = session.execute(
            select(
                func.coalesce(func.sum(LlmUsageLog.input_tokens), 0),
                func.coalesce(func.sum(LlmUsageLog.output_tokens), 0),
                func.count(LlmUsageLog.id),
                func.coalesce(func.sum(func.cast(LlmUsageLog.cache_hit, Integer)), 0),
            ).where(LlmUsageLog.created_at >= day_cutoff)
        ).one()
        month = session.execute(
            select(
                func.coalesce(func.sum(LlmUsageLog.input_tokens), 0),
                func.coalesce(func.sum(LlmUsageLog.output_tokens), 0),
                func.count(LlmUsageLog.id),
            ).where(LlmUsageLog.created_at >= month_cutoff)
        ).one()
        cache_entries = session.scalar(select(func.count(LlmResponseCache.id))) or 0
        by_operation = session.execute(
            select(
                LlmUsageLog.operation,
                func.sum(LlmUsageLog.input_tokens),
                func.sum(LlmUsageLog.output_tokens),
                func.count(LlmUsageLog.id),
                func.sum(func.cast(LlmUsageLog.cache_hit, Integer)),
            )
            .where(LlmUsageLog.created_at >= month_cutoff)
            .group_by(LlmUsageLog.operation)
        ).all()

    metrics = st.columns(4)
    metrics[0].metric("24 小时 Input", f"{today[0]:,}")
    metrics[1].metric("24 小时 Output", f"{today[1]:,}")
    metrics[2].metric("30 天总 Token", f"{month[0] + month[1]:,}")
    metrics[3].metric("缓存条目", cache_entries)
    st.caption(
        "供应商返回 usage 时记录真实 Token；未返回时按字符数估算。缓存命中不会再次请求模型。"
    )
    if by_operation:
        data = pd.DataFrame(
            [
                {
                    "操作": row[0],
                    "Input": row[1] or 0,
                    "Output": row[2] or 0,
                    "调用/命中": row[3],
                    "缓存命中": row[4] or 0,
                }
                for row in by_operation
            ]
        )
        st.dataframe(data, width="stretch", hide_index=True)
    else:
        st.info("产生 AI 调用后，这里会显示用量。")


def _render_config(cfg) -> None:
    if st.button("🔐 编辑平台配置"):
        st.switch_page("pages/setup.py")
    rows = [
        ("配置文件", str(cfg.config_path), cfg.config_exists),
        ("数据库", cfg.db_path, True),
        ("时区", cfg.timezone, True),
        ("自动更新", "已开启" if cfg.scheduler_enabled else "已关闭", cfg.scheduler_enabled),
        ("AI 服务地址", "已配置" if cfg.llm.base_url else "未配置", bool(cfg.llm.base_url)),
        ("AI 密钥", "已配置" if cfg.llm.api_key else "未配置", bool(cfg.llm.api_key)),
        ("AI 模型", cfg.llm.model, bool(cfg.llm.model)),
        ("同时 AI 请求数", str(cfg.ai_concurrency), True),
        ("记忆仓库", cfg.profile.repo or "未配置", bool(cfg.profile.repo)),
        ("记忆访问权限", "已配置" if cfg.profile.token else "未配置", bool(cfg.profile.token)),
        ("每批分析量", str(cfg.analyze_batch_size), True),
        ("近期评分范围", f"{cfg.score_window_days} 天", True),
        ("单次候选事实", str(cfg.max_assessment_facts), True),
    ]
    for label, value, ok in rows:
        cols = st.columns([1.2, 3, 1])
        cols[0].markdown(f"**{label}**")
        cols[1].write(value)
        cols[2].write("✅" if ok else "⚠️")
        st.divider()
    st.caption("敏感值只显示是否配置，不会显示密钥原文。")


def _job_status_label(status: str) -> str:
    return {
        "RUNNING": "进行中",
        "SUCCESS": "已完成",
        "PARTIAL": "部分完成",
        "FAILED": "失败",
    }.get(status, status)


def _job_type_label(job_type: str) -> str:
    return {
        "collect_sources": "采集资讯",
        "analyze_items": "AI 分析",
        "assess_new_change_points": "评估新知识点",
        "assess_all_change_points": "重新评估全部知识点",
        "assess_profile_changed": "同步个人知识关系",
        "sync_profile": "同步个人记录",
        "save_snapshot": "保存今日进展",
    }.get(job_type, job_type.replace("_", " "))


def _duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "—"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60} 分 {seconds % 60} 秒" if seconds >= 60 else f"{seconds} 秒"


render()
