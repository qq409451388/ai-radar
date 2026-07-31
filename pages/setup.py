"""First-run platform configuration wizard."""
from __future__ import annotations

import streamlit as st

from ai_radar import database
from ai_radar.config import get_config, reset_config, save_user_config
from ai_radar.scheduler import shutdown_scheduler


def render() -> None:
    cfg = get_config()
    st.markdown('<div class="page-kicker">First-run setup</div>', unsafe_allow_html=True)
    st.title("连接你的 AI Radar")
    st.markdown(
        '<div class="page-subtitle">密钥保存在操作系统用户配置目录，不再依赖项目内的 .env。</div>',
        unsafe_allow_html=True,
    )

    if cfg.legacy_env_detected:
        st.info(
            "检测到项目中的旧 `.env`。已有值已在本次页面中读取；"
            "直接保存即可迁移到新的用户配置文件，旧文件不会被自动删除。"
        )
    elif cfg.config_exists:
        st.success(f"当前配置文件：`{cfg.config_path}`")
    else:
        st.warning(f"首次保存将创建：`{cfg.config_path}`")

    with st.form("platform_setup", border=False):
        st.markdown("### 1. AI 模型")
        st.caption("支持任何 OpenAI-compatible `/chat/completions` API。")
        llm_cols = st.columns([2.2, 1.2])
        base_url = llm_cols[0].text_input(
            "API Base URL",
            value=cfg.llm.base_url,
            placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        model = llm_cols[1].text_input(
            "模型",
            value=cfg.llm.model,
            placeholder="qwen-plus",
        )
        api_key = st.text_input(
            "AI API Key",
            value="",
            type="password",
            placeholder="已配置，留空保持不变"
            if cfg.llm.api_key
            else "请输入 API Key",
            help="只写入本机用户配置文件，不显示在日志和页面状态中。",
        )

        st.markdown("### 2. GitHub 记忆仓库")
        st.caption(
            "同一个 Fine-grained Token 用于读取私有记忆仓库和提高 GitHub Release 限额。"
        )
        gh_cols = st.columns([1.5, 1, 1])
        repo = gh_cols[0].text_input(
            "私有仓库",
            value=cfg.profile.repo,
            placeholder="owner/private-memory",
        )
        ref = gh_cols[1].text_input("分支", value=cfg.profile.ref or "main")
        path_prefix = gh_cols[2].text_input(
            "目录前缀（可选）", value=cfg.profile.path_prefix
        )
        github_token = st.text_input(
            "GitHub Token",
            value="",
            type="password",
            placeholder="已配置，留空保持不变"
            if cfg.profile.token
            else "Fine-grained read-only token",
            help="建议仅授予目标私有仓库 Contents: Read-only 权限。",
        )

        with st.expander("运行偏好"):
            pref_cols = st.columns(3)
            batch_size = pref_cols[0].number_input(
                "每批分析资讯",
                min_value=1,
                max_value=200,
                value=cfg.analyze_batch_size,
            )
            score_days = pref_cols[1].number_input(
                "近期评分窗口（天）",
                min_value=7,
                max_value=365,
                value=cfg.score_window_days,
            )
            fact_limit = pref_cols[2].number_input(
                "单次候选事实",
                min_value=5,
                max_value=100,
                value=cfg.max_assessment_facts,
            )
            pref_cols = st.columns(3)
            timezone_name = pref_cols[0].text_input(
                "时区", value=cfg.timezone
            )
            scheduler_enabled = pref_cols[1].toggle(
                "启用定时任务", value=cfg.scheduler_enabled
            )
            http_timeout = pref_cols[2].number_input(
                "HTTP 超时（秒）",
                min_value=5,
                max_value=300,
                value=cfg.http_timeout,
            )

        submitted = st.form_submit_button(
            "保存并进入雷达", type="primary", width="stretch"
        )
        if submitted:
            final_api_key = api_key.strip() or cfg.llm.api_key
            final_github_token = (
                github_token.strip() or cfg.profile.token or cfg.github.token
            )
            errors = []
            if not base_url.strip():
                errors.append("API Base URL")
            if not model.strip():
                errors.append("模型")
            if not final_api_key:
                errors.append("AI API Key")
            if not repo.strip() or "/" not in repo:
                errors.append("有效的 GitHub owner/repo")
            if not final_github_token:
                errors.append("GitHub Token")
            if errors:
                st.error("请补充：" + "、".join(errors))
            else:
                data = cfg.as_user_dict(
                    llm_api_key=final_api_key,
                    github_token=final_github_token,
                )
                data["llm"].update(
                    {
                        "base_url": base_url.strip().rstrip("/"),
                        "model": model.strip(),
                    }
                )
                data["profile"].update(
                    {
                        "repo": repo.strip(),
                        "ref": ref.strip() or "main",
                        "path_prefix": path_prefix.strip(),
                    }
                )
                data["app"].update(
                    {
                        "timezone": timezone_name.strip(),
                        "scheduler_enabled": scheduler_enabled,
                        "http_timeout": int(http_timeout),
                        "analyze_batch_size": int(batch_size),
                        "score_window_days": int(score_days),
                        "max_assessment_facts": int(fact_limit),
                    }
                )
                target = save_user_config(data)
                shutdown_scheduler()
                reset_config()
                database.reset_engine()
                st.session_state["_initialized"] = False
                st.session_state["_scheduler_started"] = False
                st.success(f"配置已保存到 {target}")
                st.switch_page("pages/home.py")

    st.caption(
        "优先级：进程环境变量 > 用户 config.yaml > 旧 .env（仅迁移兼容）> 默认值。"
    )


render()
