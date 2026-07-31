"""First-run configuration wizard and post-setup settings editor."""
from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import Any

import streamlit as st

from ai_radar import database
from ai_radar.config import (
    CONTENT_LANGUAGE_LABELS,
    AppConfig,
    get_config,
    reset_config,
    save_user_config,
)
from ai_radar.scheduler import shutdown_scheduler
from ai_radar.setup_wizard import (
    CUSTOM_PROVIDER,
    PROVIDER_PRESETS,
    build_user_config,
    infer_provider,
    validate_llm,
    validate_profile,
    validate_timezone,
)

WIZARD_PREFIX = "_setup_wizard_"
WIDGET_PREFIX = "_setup_field_"
WIZARD_STEPS = (
    ("1", "AI 模型"),
    ("2", "记忆仓库"),
    ("3", "运行偏好"),
    ("4", "检查保存"),
)


def render() -> None:
    cfg = get_config()
    if not cfg.config_exists or not cfg.is_ready:
        _render_first_run_wizard(cfg)
    else:
        _render_editor(cfg)


def _render_first_run_wizard(cfg: AppConfig) -> None:
    _initialize_wizard_state(cfg)
    step = max(
        0,
        min(
            int(st.session_state[f"{WIZARD_PREFIX}step"]),
            len(WIZARD_STEPS) - 1,
        ),
    )

    st.markdown(
        """
        <div class="setup-hero">
          <div class="setup-hero-badge">AI RADAR · 首次设置</div>
          <div class="setup-hero-title">用几分钟连接你的个人 AI 雷达</div>
          <div class="setup-hero-copy">
            跟着 4 步完成模型和 GitHub 记忆仓库配置。所有密钥只保存在本机，
            AI Radar 对记忆仓库仅做只读访问。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_stepper(step)

    if cfg.legacy_env_detected:
        st.info(
            "检测到旧 `.env`，已有内容已自动带入。走完向导并保存后会迁移到用户配置文件。"
        )

    renderers: tuple[Callable[[AppConfig], None], ...] = (
        _render_llm_step,
        _render_github_step,
        _render_preferences_step,
        _render_review_step,
    )
    renderers[step](cfg)


def _initialize_wizard_state(cfg: AppConfig) -> None:
    # Streamlit normally removes widget-backed keys when their step is hidden.
    # Reassigning them at the start of a run detaches them from that cleanup so
    # Back/Next navigation never loses values that the user already entered.
    for key in list(st.session_state):
        if key.startswith(WIDGET_PREFIX):
            st.session_state[key] = st.session_state[key]

    initial_provider = infer_provider(cfg.llm.base_url)
    if not cfg.llm.base_url:
        initial_provider = "阿里云百炼"
    preset = PROVIDER_PRESETS.get(initial_provider)
    defaults: dict[str, Any] = {
        "provider": initial_provider,
        "base_url": cfg.llm.base_url or (preset.base_url if preset else ""),
        "model": cfg.llm.model or (preset.model if preset else ""),
        "api_key": "",
        "repo": cfg.profile.repo,
        "ref": cfg.profile.ref or "main",
        "path_prefix": cfg.profile.path_prefix,
        "github_token": "",
        "timezone": cfg.timezone,
        "scheduler_enabled": cfg.scheduler_enabled,
        "http_timeout": cfg.http_timeout,
        "analyze_batch_size": cfg.analyze_batch_size,
        "ai_concurrency": cfg.ai_concurrency,
        "score_window_days": cfg.score_window_days,
        "max_assessment_facts": cfg.max_assessment_facts,
        "content_language": cfg.content_language,
    }
    st.session_state.setdefault(f"{WIZARD_PREFIX}step", 0)
    st.session_state.setdefault(f"{WIZARD_PREFIX}values", defaults)


def _render_stepper(active_step: int) -> None:
    parts = ['<div class="setup-stepper">']
    for index, (number, label) in enumerate(WIZARD_STEPS):
        state = "active" if index == active_step else "done" if index < active_step else ""
        parts.append(
            f'<div class="setup-step {state}">'
            f'<span class="setup-step-number">{number}</span>'
            f'<span class="setup-step-label">{label}</span></div>'
        )
        if index < len(WIZARD_STEPS) - 1:
            connector_state = "done" if index < active_step else ""
            parts.append(f'<div class="setup-step-line {connector_state}"></div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _render_llm_step(cfg: AppConfig) -> None:
    st.markdown("## 连接 AI 模型")
    st.caption("AI Radar 用模型把资讯整理成知识变化点。你需要一个支持 OpenAI Chat Completions 的 API。")

    guide, fields = st.columns([1, 1.45], gap="large")
    with guide:
        st.markdown(
            """
            <div class="setup-guide-card">
              <div class="setup-guide-eyebrow">怎么填</div>
              <div class="setup-guide-title">先从服务商获取 API Key</div>
              <ol>
                <li>选择你正在使用的模型服务。</li>
                <li>打开官方说明并创建 API Key。</li>
                <li>复制 Key，回到右侧粘贴。</li>
                <li>确认 Base URL 和模型 ID 与你的套餐一致。</li>
              </ol>
              <div class="setup-guide-note">
                Base URL 填到 <code>/v1</code> 即可，不要追加
                <code>/chat/completions</code>。
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        provider = _state("provider")
        preset = PROVIDER_PRESETS.get(provider)
        if preset:
            st.info(preset.description)
            st.link_button(
                "打开官方 API Key 指南",
                preset.guide_url,
                icon="↗",
                width="stretch",
            )
        else:
            st.info("请从你的服务商文档中复制 OpenAI-compatible Base URL 和模型 ID。")

    with fields:
        st.selectbox(
            "模型服务",
            [*PROVIDER_PRESETS, CUSTOM_PROVIDER],
            key=_field_key("provider"),
            on_change=_apply_provider_preset,
            help="选择预设会自动填写推荐的 Base URL 和模型 ID，仍可手动修改。",
        )
        st.text_input(
            "API Base URL",
            key=_field_key("base_url"),
            placeholder="https://example.com/v1",
            help="OpenAI-compatible API 根地址，不包含 /chat/completions。",
        )
        st.text_input(
            "模型 ID",
            key=_field_key("model"),
            placeholder="qwen-plus",
            help="填写服务商控制台或模型文档中的准确模型 ID。",
        )
        st.text_input(
            "AI API Key",
            key=_field_key("api_key"),
            type="password",
            placeholder="已检测到现有 Key，留空沿用"
            if cfg.llm.api_key
            else "粘贴 API Key",
            help="保存到操作系统用户配置目录，不会写进项目代码或日志。",
        )
        if cfg.llm.api_key:
            st.caption("✓ 已检测到现有 API Key；不重新填写也可以继续。")

    _render_next_button(
        lambda: validate_llm(
            _state("base_url"),
            _state("model"),
            has_api_key=bool(_state("api_key").strip() or cfg.llm.api_key),
        )
    )


def _apply_provider_preset() -> None:
    provider = str(st.session_state[_field_key("provider")])
    preset = PROVIDER_PRESETS.get(provider)
    if preset:
        st.session_state[_field_key("base_url")] = preset.base_url
        st.session_state[_field_key("model")] = preset.model
        values = _saved_values()
        values["provider"] = provider
        values["base_url"] = preset.base_url
        values["model"] = preset.model


def _render_github_step(cfg: AppConfig) -> None:
    st.markdown("## 连接 GitHub 记忆仓库")
    st.caption("AI Radar 从你的 Markdown 记录中提取已研究、设计和实践过的内容，用于判断知识覆盖。")

    guide, fields = st.columns([1, 1.45], gap="large")
    with guide:
        st.markdown(
            """
            <div class="setup-guide-card">
              <div class="setup-guide-eyebrow">推荐做法</div>
              <div class="setup-guide-title">准备一个只放个人记录的私有仓库</div>
              <ol>
                <li>创建或选择一个 GitHub 私有仓库。</li>
                <li>至少放入一个 <code>.md</code> 文件。</li>
                <li>创建 Fine-grained personal access token。</li>
                <li>Repository access 只选择这个仓库。</li>
                <li>Repository permissions 只开启 <b>Contents: Read-only</b>。</li>
              </ol>
              <div class="setup-guide-note">
                应用只调用 GitHub Contents API 读取文件，不会修改或删除仓库内容。
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        links = st.columns(2)
        links[0].link_button(
            "新建私有仓库",
            "https://github.com/new?visibility=private",
            width="stretch",
        )
        links[1].link_button(
            "创建只读 Token",
            "https://github.com/settings/personal-access-tokens/new",
            width="stretch",
        )
        st.link_button(
            "查看 GitHub Token 官方说明",
            "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
            icon="↗",
            width="stretch",
        )

    with fields:
        st.text_input(
            "仓库",
            key=_field_key("repo"),
            placeholder="你的用户名/仓库名",
            help="例如 `octocat/ai-memory`，不要粘贴完整 GitHub URL。",
        )
        repo_cols = st.columns([1, 1.4])
        repo_cols[0].text_input(
            "分支",
            key=_field_key("ref"),
            placeholder="main",
        )
        repo_cols[1].text_input(
            "Markdown 目录（可选）",
            key=_field_key("path_prefix"),
            placeholder="memory/notes",
            help="留空会读取仓库内所有 Markdown；填写后只读取这个目录。",
        )
        st.text_input(
            "GitHub Token",
            key=_field_key("github_token"),
            type="password",
            placeholder="已检测到现有 Token，留空沿用"
            if cfg.profile.token
            else "粘贴 Fine-grained Token",
            help="建议设置有效期，并只授予目标仓库 Contents: Read-only。",
        )
        if cfg.profile.token:
            st.caption("✓ 已检测到现有 GitHub Token；不重新填写也可以继续。")

    _render_back_next_buttons(
        lambda: validate_profile(
            _state("repo"),
            _state("ref"),
            has_token=bool(
                _state("github_token").strip()
                or cfg.profile.token
                or cfg.github.token
            ),
        )
    )


def _render_preferences_step(_cfg: AppConfig) -> None:
    st.markdown("## 选择运行偏好")
    st.caption("这些默认值适合个人使用，可以先直接继续，之后随时在“自动化与设置”中修改。")

    with st.container(border=True):
        st.markdown("#### 时间与自动更新")
        cols = st.columns([1.35, 1.15, 1])
        cols[0].text_input(
            "时区",
            key=_field_key("timezone"),
            help="用于定时任务和页面时间显示，例如 Asia/Shanghai。",
        )
        cols[1].selectbox(
            "资讯展示语言",
            list(CONTENT_LANGUAGE_LABELS),
            format_func=lambda value: CONTENT_LANGUAGE_LABELS[value],
            key=_field_key("content_language"),
            help="外文资讯会在 AI 分析时翻译成这里选择的语言。",
        )
        cols[2].toggle(
            "启用定时更新",
            key=_field_key("scheduler_enabled"),
            help="每天自动采集资讯、同步记忆并更新评分。",
        )
        st.caption("开启后默认在每天 08:00、09:00 和 23:00 执行相应任务。")

    with st.container(border=True):
        st.markdown("#### 分析范围")
        cols = st.columns(3)
        cols[0].number_input(
            "每批分析资讯",
            min_value=1,
            max_value=200,
            key=_field_key("analyze_batch_size"),
            help="越大更新越完整，但单次耗时和 Token 用量也越高。",
        )
        cols[1].number_input(
            "近期评分窗口（天）",
            min_value=7,
            max_value=365,
            key=_field_key("score_window_days"),
            help="只用这段时间内的知识变化计算当前跟进分。",
        )
        cols[2].number_input(
            "单次候选事实",
            min_value=5,
            max_value=100,
            key=_field_key("max_assessment_facts"),
            help="每个知识点最多交给模型匹配多少条个人事实。",
        )
        with st.expander("高级设置"):
            advanced = st.columns(2)
            advanced[0].number_input(
                "同时进行的 AI 请求",
                min_value=1,
                max_value=8,
                key=_field_key("ai_concurrency"),
                help="流水线会并行处理多个独立知识点。个人使用推荐 4。",
            )
            advanced[1].number_input(
                "外部请求超时（秒）",
                min_value=5,
                max_value=300,
                key=_field_key("http_timeout"),
            )

    _render_back_next_buttons(lambda: validate_timezone(_state("timezone")))


def _render_review_step(cfg: AppConfig) -> None:
    st.markdown("## 检查配置并开始使用")
    st.caption("确认下面的信息无误。密钥原文不会在此处显示。")

    llm_ok = bool(_state("api_key").strip() or cfg.llm.api_key)
    github_ok = bool(
        _state("github_token").strip() or cfg.profile.token or cfg.github.token
    )
    rows = (
        ("AI 服务", _state("provider"), True),
        ("API 地址", _state("base_url"), True),
        ("模型", _state("model"), True),
        ("AI API Key", "已填写" if llm_ok else "未填写", llm_ok),
        ("记忆仓库", _state("repo"), True),
        ("分支 / 目录", f"{_state('ref')} / {_state('path_prefix') or '整个仓库'}", True),
        ("GitHub Token", "已填写" if github_ok else "未填写", github_ok),
        ("时区", _state("timezone"), True),
        (
            "资讯展示语言",
            CONTENT_LANGUAGE_LABELS.get(
                _state("content_language"),
                _state("content_language"),
            ),
            True,
        ),
        (
            "自动更新",
            "已启用" if _state_value("scheduler_enabled") else "暂不启用",
            True,
        ),
    )
    with st.container(border=True):
        for label, value, ok in rows:
            safe_label = escape(str(label))
            safe_value = escape(str(value))
            st.markdown(
                f"""
                <div class="setup-review-row">
                  <span class="setup-review-label">{safe_label}</span>
                  <span class="setup-review-value">{safe_value}</span>
                  <span class="setup-review-status">{'✓' if ok else '!'}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown(
        f"""
        <div class="setup-security-note">
          <b>🔒 只保存在这台电脑</b><br>
          配置将写入 <code>{escape(str(cfg.config_path))}</code>。AI Radar 不会在页面、日志或仓库中显示密钥原文。
        </div>
        """,
        unsafe_allow_html=True,
    )

    back, save = st.columns([1, 2.2])
    if back.button("← 返回修改", width="stretch"):
        _go_to_step(2)
    if save.button(
        "保存配置并进入 AI Radar",
        type="primary",
        icon="✅",
        width="stretch",
    ):
        all_errors = [
            *validate_llm(
                _state("base_url"),
                _state("model"),
                has_api_key=llm_ok,
            ),
            *validate_profile(
                _state("repo"),
                _state("ref"),
                has_token=github_ok,
            ),
            *validate_timezone(_state("timezone")),
        ]
        if all_errors:
            _show_errors(all_errors)
            return
        try:
            target = _persist(cfg, _wizard_values())
        except (OSError, TypeError, ValueError) as exc:
            st.error(f"配置保存失败：{exc}")
            return
        st.success(f"配置已保存到 {target}")
        _clear_wizard_state()
        st.switch_page("pages/home.py")


def _render_editor(cfg: AppConfig) -> None:
    st.markdown('<div class="page-kicker">Platform settings</div>', unsafe_allow_html=True)
    st.title("平台配置")
    st.markdown(
        '<div class="page-subtitle">更新模型、记忆仓库和运行偏好。留空密钥字段会保留现有值。</div>',
        unsafe_allow_html=True,
    )
    st.success(f"当前配置文件：`{cfg.config_path}`")

    with st.form("platform_settings", border=False):
        st.markdown("### AI 模型")
        llm_cols = st.columns([2.2, 1.2])
        base_url = llm_cols[0].text_input("API Base URL", value=cfg.llm.base_url)
        model = llm_cols[1].text_input("模型", value=cfg.llm.model)
        api_key = st.text_input(
            "AI API Key",
            type="password",
            placeholder="已配置，留空保持不变" if cfg.llm.api_key else "请输入 API Key",
        )

        st.markdown("### GitHub 记忆仓库")
        gh_cols = st.columns([1.5, 1, 1])
        repo = gh_cols[0].text_input("私有仓库", value=cfg.profile.repo)
        ref = gh_cols[1].text_input("分支", value=cfg.profile.ref or "main")
        path_prefix = gh_cols[2].text_input(
            "目录前缀（可选）",
            value=cfg.profile.path_prefix,
        )
        github_token = st.text_input(
            "GitHub Token",
            type="password",
            placeholder="已配置，留空保持不变"
            if cfg.profile.token
            else "Fine-grained read-only token",
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
            pref_cols = st.columns(5)
            timezone_name = pref_cols[0].text_input("时区", value=cfg.timezone)
            content_language = pref_cols[1].selectbox(
                "资讯展示语言",
                list(CONTENT_LANGUAGE_LABELS),
                index=list(CONTENT_LANGUAGE_LABELS).index(
                    cfg.content_language
                ),
                format_func=lambda value: CONTENT_LANGUAGE_LABELS[value],
            )
            scheduler_enabled = pref_cols[2].toggle(
                "启用定时任务",
                value=cfg.scheduler_enabled,
            )
            ai_concurrency = pref_cols[3].number_input(
                "AI 并发请求",
                min_value=1,
                max_value=8,
                value=cfg.ai_concurrency,
            )
            http_timeout = pref_cols[4].number_input(
                "HTTP 超时（秒）",
                min_value=5,
                max_value=300,
                value=cfg.http_timeout,
            )

        submitted = st.form_submit_button(
            "保存配置",
            type="primary",
            width="stretch",
        )
        if submitted:
            values = {
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
                "repo": repo,
                "ref": ref,
                "path_prefix": path_prefix,
                "github_token": github_token,
                "timezone": timezone_name,
                "content_language": content_language,
                "scheduler_enabled": scheduler_enabled,
                "http_timeout": http_timeout,
                "analyze_batch_size": batch_size,
                "ai_concurrency": ai_concurrency,
                "score_window_days": score_days,
                "max_assessment_facts": fact_limit,
            }
            errors = [
                *validate_llm(
                    base_url,
                    model,
                    has_api_key=bool(api_key.strip() or cfg.llm.api_key),
                ),
                *validate_profile(
                    repo,
                    ref,
                    has_token=bool(
                        github_token.strip()
                        or cfg.profile.token
                        or cfg.github.token
                    ),
                ),
                *validate_timezone(timezone_name),
            ]
            if errors:
                _show_errors(errors)
            else:
                try:
                    target = _persist(cfg, values)
                except (OSError, TypeError, ValueError) as exc:
                    st.error(f"配置保存失败：{exc}")
                else:
                    st.success(f"配置已保存到 {target}")

    st.caption("敏感值只保存在操作系统用户配置目录，不会显示在页面状态或日志中。")


def _render_next_button(validate: Callable[[], list[str]]) -> None:
    _, button_col = st.columns([1, 1])
    if button_col.button("下一步：连接记忆仓库 →", type="primary", width="stretch"):
        errors = validate()
        if errors:
            _show_errors(errors)
        else:
            _go_to_step(1)


def _render_back_next_buttons(validate: Callable[[], list[str]]) -> None:
    step = int(st.session_state[f"{WIZARD_PREFIX}step"])
    back, next_button = st.columns([1, 2])
    if back.button("← 上一步", key=f"wizard_back_{step}", width="stretch"):
        _go_to_step(step - 1)
    label = "下一步：运行偏好 →" if step == 1 else "下一步：检查配置 →"
    if next_button.button(
        label,
        key=f"wizard_next_{step}",
        type="primary",
        width="stretch",
    ):
        errors = validate()
        if errors:
            _show_errors(errors)
        else:
            _go_to_step(step + 1)


def _show_errors(errors: list[str]) -> None:
    for error in errors:
        st.error(error, icon="⚠️")


def _go_to_step(step: int) -> None:
    _sync_visible_fields()
    st.session_state[f"{WIZARD_PREFIX}step"] = max(
        0,
        min(step, len(WIZARD_STEPS) - 1),
    )
    st.rerun()


def _state(name: str) -> str:
    return str(_state_value(name))


def _state_value(name: str) -> Any:
    field_key = f"{WIDGET_PREFIX}{name}"
    if field_key in st.session_state:
        return st.session_state[field_key]
    return _saved_values()[name]


def _field_key(name: str) -> str:
    key = f"{WIDGET_PREFIX}{name}"
    if key not in st.session_state:
        st.session_state[key] = _saved_values()[name]
    return key


def _saved_values() -> dict[str, Any]:
    return st.session_state[f"{WIZARD_PREFIX}values"]


def _sync_visible_fields() -> None:
    values = _saved_values()
    for name in tuple(values):
        key = f"{WIDGET_PREFIX}{name}"
        if key in st.session_state:
            values[name] = st.session_state[key]


def _wizard_values() -> dict[str, Any]:
    names = (
        "base_url",
        "model",
        "api_key",
        "repo",
        "ref",
        "path_prefix",
        "github_token",
        "timezone",
        "scheduler_enabled",
        "http_timeout",
        "analyze_batch_size",
        "ai_concurrency",
        "score_window_days",
        "max_assessment_facts",
        "content_language",
    )
    _sync_visible_fields()
    values = _saved_values()
    return {name: values[name] for name in names}


def _persist(cfg: AppConfig, values: dict[str, Any]) -> Any:
    target = save_user_config(build_user_config(cfg, values))
    shutdown_scheduler()
    reset_config()
    database.reset_engine()
    st.session_state["_initialized"] = False
    st.session_state["_scheduler_started"] = False
    return target


def _clear_wizard_state() -> None:
    for key in list(st.session_state):
        if key.startswith(WIZARD_PREFIX) or key.startswith(WIDGET_PREFIX):
            del st.session_state[key]


render()
