"""AI Radar Streamlit shell with task-oriented navigation."""
from __future__ import annotations

import logging

import streamlit as st
from sqlalchemy import func, select

from ai_radar.bootstrap import seed_default_data
from ai_radar.config import get_config
from ai_radar.database import init_db, session_scope
from ai_radar.models import ProfileSourceFile, SourceItem
from ai_radar.pipeline_ui import (
    render_pipeline_launcher,
    render_pipeline_progress,
)
from ai_radar.pipeline_runner import (
    get_active_pipeline_snapshot,
    recover_interrupted_runs,
)
from ai_radar.scheduler import start_scheduler
from ai_radar.theme import inject_app_styles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

st.set_page_config(
    page_title="AI Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.dialog("更新中心", width="large")
def render_update_center() -> None:
    render_pipeline_launcher()
    st.divider()
    render_pipeline_progress()


def ensure_initialized() -> None:
    # Additive schema upgrades must run even when Streamlit preserves browser
    # session state across a code reload.
    init_db()
    if st.session_state.get("_initialized"):
        return
    recover_interrupted_runs()
    with session_scope() as session:
        seed_default_data(session)
    st.session_state["_initialized"] = True


def maybe_start_scheduler() -> None:
    if st.session_state.get("_scheduler_started"):
        return
    cfg = get_config()
    if not cfg.config_exists or not cfg.is_ready:
        return
    try:
        start_scheduler()
        st.session_state["_scheduler_started"] = True
    except Exception as exc:  # pragma: no cover - runtime environment specific
        st.session_state["_scheduler_error"] = str(exc)


def render_sidebar_status() -> None:
    cfg = get_config()
    with session_scope() as session:
        pending = session.scalar(
            select(func.count(SourceItem.id)).where(
                SourceItem.analyze_status == "PENDING"
            )
        ) or 0
        profile = session.execute(
            select(ProfileSourceFile).order_by(
                ProfileSourceFile.last_success_at.desc()
            ).limit(1)
        ).scalar_one_or_none()

    with st.sidebar:
        st.markdown(
            """
            <div class="radar-brand">
              <div class="radar-brand-mark">◉</div>
              <div>
                <div class="radar-brand-title">AI Radar</div>
                <div class="radar-brand-subtitle">个人 AI 工程情报系统</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="sidebar-label">运行状态</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="sidebar-status">
              <div><span class="status-dot {'warn' if pending else 'ok'}"></span>待处理资讯 <b>{pending}</b></div>
              <div><span class="status-dot {'ok' if profile and profile.extraction_status == 'SUCCESS' else 'warn'}"></span>记忆抽取 <b>{profile.extraction_status if profile else '未同步'}</b></div>
              <div><span class="status-dot {'ok' if cfg.llm.api_key else 'bad'}"></span>模型 <b>{cfg.llm.model}</b></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_sidebar_pipeline_status()
        if st.session_state.get("_scheduler_error"):
            st.caption(f"调度器异常：{st.session_state['_scheduler_error']}")
        st.caption(f"近 {cfg.score_window_days} 天作为当前跟进窗口")


def render_sidebar_pipeline_status() -> None:
    snapshot = get_active_pipeline_snapshot()
    if snapshot is None:
        label = "↻ 运行 / 重跑更新"
        help_text = "采集资讯、调用 AI 分析并刷新知识进展"
    else:
        current = next(
            (
                step
                for step in snapshot["steps"]
                if step["key"] == snapshot["current_step"]
            ),
            None,
        )
        current_label = current["label"] if current else "正在准备"
        percent = int(snapshot["progress"] * 100)
        label = f"↻ 更新进行中 · {percent}%"
        help_text = f"{current_label}，点击查看每一步进度"
    if st.button(
        label,
        width="stretch",
        key="sidebar_update_center",
        help=help_text,
    ):
        render_update_center()
    st.caption(help_text)


ensure_initialized()
maybe_start_scheduler()
inject_app_styles()

cfg = get_config()
needs_setup = not cfg.config_exists or not cfg.is_ready
if needs_setup:
    with st.sidebar:
        st.markdown(
            """
            <div class="radar-brand">
              <div class="radar-brand-mark">◉</div>
              <div>
                <div class="radar-brand-title">AI Radar</div>
                <div class="radar-brand-subtitle">个人 AI 工程情报系统</div>
              </div>
            </div>
            <div class="setup-sidebar-note">
              <b>首次设置</b>
              <span>完成模型和记忆仓库连接后，即可进入今日雷达。</span>
              <small>🔒 密钥只保存在本机</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    render_sidebar_status()

home_page = st.Page(
    "pages/home.py",
    title="今日雷达",
    icon="📡",
    default=not needs_setup,
)
setup_page = st.Page(
    "pages/setup.py",
    title="平台配置",
    icon="🔐",
    default=needs_setup,
)
if needs_setup:
    # Keep home registered for the wizard's final programmatic redirect, but
    # hide all navigation until required configuration has been saved.
    navigation = st.navigation([setup_page, home_page], position="hidden")
else:
    navigation = st.navigation(
        {
            "雷达": [
                home_page,
                st.Page("pages/inbox.py", title="情报收件箱", icon="📨"),
                st.Page("pages/sources.py", title="资讯源", icon="🗞️"),
                st.Page("pages/knowledge.py", title="知识地图", icon="🧭"),
                st.Page("pages/progress.py", title="我的进展", icon="📈"),
            ],
            "系统": [
                setup_page,
                st.Page("pages/automation.py", title="自动化与设置", icon="⚙️"),
            ],
        }
    )
navigation.run()
