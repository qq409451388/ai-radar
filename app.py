"""AI Radar Streamlit shell with task-oriented navigation."""
from __future__ import annotations

import logging

import streamlit as st
from sqlalchemy import func, select

from ai_radar.bootstrap import seed_default_data
from ai_radar.config import get_config
from ai_radar.database import init_db, session_scope
from ai_radar.models import ProfileSourceFile, SourceItem
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


def ensure_initialized() -> None:
    if st.session_state.get("_initialized"):
        return
    init_db()
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
        if st.session_state.get("_scheduler_error"):
            st.caption(f"调度器异常：{st.session_state['_scheduler_error']}")
        st.caption(f"近 {cfg.score_window_days} 天作为当前跟进窗口")


ensure_initialized()
maybe_start_scheduler()
inject_app_styles()
render_sidebar_status()

cfg = get_config()
needs_setup = not cfg.config_exists or not cfg.is_ready
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
navigation = st.navigation(
    {
        "雷达": [
            home_page,
            st.Page("pages/inbox.py", title="情报收件箱", icon="📨"),
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
