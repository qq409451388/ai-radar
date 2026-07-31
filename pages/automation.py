"""Automation, source management, jobs, and token observability."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import Integer, func, select

from ai_radar import orchestrator
from ai_radar.config import get_config
from ai_radar.database import session_scope
from ai_radar.models import (
    JobLog,
    LlmResponseCache,
    LlmUsageLog,
    ProfileSourceFile,
    SourceConfig,
    SourceItem,
    Topic,
)
from ai_radar.scheduler import get_scheduler
from ai_radar.ui import fmt_dt


def _run_action(label: str, fn, *, primary: bool = False) -> None:
    if st.button(
        label,
        type="primary" if primary else "secondary",
        width="stretch",
        key=f"action_{label}",
    ):
        with st.spinner(f"正在执行：{label}…"):
            result = fn()
        st.success(f"完成：{result}")
        st.rerun()


def render() -> None:
    cfg = get_config()
    st.markdown('<div class="page-kicker">Automation & settings</div>', unsafe_allow_html=True)
    st.title("自动化与设置")
    st.markdown(
        '<div class="page-subtitle">查看流水线健康度、Token 使用和资讯源；高级操作集中在这里。</div>',
        unsafe_allow_html=True,
    )

    pipeline_tab, sources_tab, usage_tab, config_tab = st.tabs(
        ["任务流水线", "资讯源", "Token 与缓存", "配置状态"]
    )
    with pipeline_tab:
        _render_pipeline()
    with sources_tab:
        _render_sources()
    with usage_tab:
        _render_usage()
    with config_tab:
        _render_config(cfg)


def _render_pipeline() -> None:
    st.markdown("### 手动运行")
    cols = st.columns(5)
    with cols[0]:
        _run_action("采集资讯", orchestrator.collect_all_sources, primary=True)
    with cols[1]:
        _run_action("分析下一批", orchestrator.analyze_pending_items)
    with cols[2]:
        _run_action("同步记忆", orchestrator.sync_profile)
    with cols[3]:
        _run_action("评估新知识点", orchestrator.assess_new_change_points)
    with cols[4]:
        _run_action("保存今日快照", orchestrator.save_snapshot)

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
        jobs = list(
            session.execute(
                select(JobLog).order_by(JobLog.id.desc()).limit(50)
            ).scalars()
        )
    metrics = st.columns(4)
    metrics[0].metric("待分析", counts.get("PENDING", 0))
    metrics[1].metric("分析失败", counts.get("FAILED", 0))
    metrics[2].metric("记忆抽取失败", extraction_failed)
    metrics[3].metric(
        "最近任务",
        jobs[0].status if jobs else "无",
        jobs[0].job_type if jobs else None,
    )

    st.markdown("### 定时计划")
    scheduler_rows = []
    for job in get_scheduler().get_jobs():
        scheduler_rows.append(
            {
                "任务": job.id,
                "下次执行": fmt_dt(getattr(job, "next_run_time", None)),
                "计划": str(job.trigger),
            }
        )
    if scheduler_rows:
        st.dataframe(
            pd.DataFrame(scheduler_rows),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "当前是进程内调度：Streamlit 持续运行时生效。应用关闭期间不会执行，"
            "重新打开后可在首页点“运行今日更新”补跑。"
        )
    else:
        st.warning("调度器未启用。")

    st.markdown("### 最近任务")
    if jobs:
        data = [
            {
                "任务": job.job_type,
                "状态": job.status,
                "开始": fmt_dt(job.started_at),
                "耗时": _duration(job.started_at, job.finished_at),
                "处理": job.processed_count,
                "成功": job.success_count,
                "失败": job.failed_count,
                "结果": job.message,
            }
            for job in jobs
        ]
        st.dataframe(pd.DataFrame(data), width="stretch", hide_index=True)


def _render_sources() -> None:
    with session_scope() as session:
        topics = list(session.execute(select(Topic).order_by(Topic.id)).scalars())
        sources = list(
            session.execute(select(SourceConfig).order_by(SourceConfig.name)).scalars()
        )
        topic_names = {topic.id: topic.name for topic in topics}

        st.markdown("### 新增来源")
        with st.form("new_source", border=True):
            cols = st.columns([1.2, 1, 2, 1.5])
            name = cols[0].text_input("名称")
            source_type = cols[1].selectbox(
                "类型", ["RSS", "GITHUB_RELEASE"]
            )
            url = cols[2].text_input("URL")
            repository = cols[3].text_input("owner/repo（可选）")
            topic_id = st.selectbox(
                "默认领域",
                [topic.id for topic in topics],
                format_func=lambda value: topic_names[value],
            )
            if st.form_submit_button("添加来源"):
                if not name.strip() or not url.strip():
                    st.error("名称和 URL 必填")
                else:
                    session.add(
                        SourceConfig(
                            name=name.strip(),
                            source_type=source_type,
                            url=url.strip(),
                            repository=repository.strip(),
                            enabled=True,
                            default_topic_id=topic_id,
                        )
                    )
                    st.success("来源已添加。")

        st.markdown("### 已配置来源")
        for source in sources:
            with st.container(border=True):
                cols = st.columns([2, 1.2, 1.3, 1, 1])
                cols[0].markdown(f"**{source.name}**")
                cols[0].caption(source.url)
                cols[1].caption(source.source_type)
                cols[2].caption(topic_names.get(source.default_topic_id, "未分类"))
                cols[3].caption(f"采集 {fmt_dt(source.last_collected_at)}")
                enabled = cols[4].toggle(
                    "启用",
                    value=source.enabled,
                    key=f"source_enabled_{source.id}",
                )
                if enabled != source.enabled:
                    source.enabled = enabled
                if source.last_error:
                    st.error(source.last_error)


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
        "供应商返回 usage 时记录真实 Token；未返回时按字符数估算并标记。"
        "缓存命中不会再次请求模型。"
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
        st.info("新版本启用后产生的 LLM 调用会在这里记录。")


def _render_config(cfg) -> None:
    st.page_link(
        "pages/setup.py",
        label="编辑平台配置",
        icon="🔐",
    )
    rows = [
        ("配置文件", str(cfg.config_path), cfg.config_exists),
        ("数据库", cfg.db_path, True),
        ("时区", cfg.timezone, True),
        ("调度器", "已启用" if cfg.scheduler_enabled else "已关闭", cfg.scheduler_enabled),
        ("LLM 地址", "已配置" if cfg.llm.base_url else "未配置", bool(cfg.llm.base_url)),
        ("LLM Key", "已配置" if cfg.llm.api_key else "未配置", bool(cfg.llm.api_key)),
        ("LLM 模型", cfg.llm.model, bool(cfg.llm.model)),
        ("记忆仓库", cfg.profile.repo or "未配置", bool(cfg.profile.repo)),
        ("记忆 Token", "已配置" if cfg.profile.token else "未配置", bool(cfg.profile.token)),
        ("分析批次", str(cfg.analyze_batch_size), True),
        ("当前评分窗口", f"{cfg.score_window_days} 天", True),
        ("单次最多候选事实", str(cfg.max_assessment_facts), True),
    ]
    for label, value, ok in rows:
        cols = st.columns([1.2, 3, 1])
        cols[0].markdown(f"**{label}**")
        cols[1].write(value)
        cols[2].write("✅" if ok else "⚠️")
        st.divider()
    st.caption(
        "敏感值只显示是否配置，不会显示 Token 原文。"
        "页面保存后会自动重新加载配置。"
    )


def _duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "—"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60}m {seconds % 60}s" if seconds >= 60 else f"{seconds}s"


render()
