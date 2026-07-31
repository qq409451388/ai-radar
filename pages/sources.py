"""Dedicated information-source management page."""
from __future__ import annotations

from html import escape

import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.models import SourceConfig, Topic
from ai_radar.ui import fmt_dt


TYPE_LABELS = {
    "RSS": "RSS 订阅",
    "WEB_PAGE": "网页",
    "GITHUB_RELEASE": "GitHub 版本",
    "GITHUB_COMMIT": "GitHub 文档变更",
}
TEST_LABELS = {
    "PASSED": ("可启用", "success"),
    "FAILED": ("测试失败", "failed"),
    "UNTESTED": ("等待测试", "pending"),
}


def render() -> None:
    st.markdown('<div class="page-kicker">Sources</div>', unsafe_allow_html=True)
    st.title("资讯源")
    st.markdown(
        '<div class="page-subtitle">'
        "管理 AI Radar 从哪里发现变化。新来源先测试，确认可访问后再启用。"
        "</div>",
        unsafe_allow_html=True,
    )

    _render_add_source()
    _render_sources()


def _load_data() -> tuple[list[Topic], list[SourceConfig]]:
    with session_scope() as session:
        topics = list(session.execute(select(Topic).order_by(Topic.id)).scalars())
        sources = list(
            session.execute(select(SourceConfig).order_by(SourceConfig.name)).scalars()
        )
    return topics, sources


def _render_add_source() -> None:
    topics, _sources = _load_data()
    topic_names = {topic.id: topic.name for topic in topics}
    created_name = st.session_state.pop("_source_created_name", "")
    if created_name:
        st.toast(f"“{created_name}”已创建，请在列表中测试连接", icon="✅")

    is_open = bool(st.session_state.get("_source_add_open", False))
    button_label = "收起新增表单" if is_open else "＋ 新增资讯源"
    if st.button(
        button_label,
        key="toggle_source_add_panel",
    ):
        st.session_state["_source_add_open"] = not is_open
        st.rerun()
    if not is_open:
        return

    with st.container(border=True):
        st.caption("保存后来源保持关闭；单点测试通过后，才可以开启自动采集。")
        with st.form("new_source", border=False, clear_on_submit=True):
            cols = st.columns([1.2, 1.2])
            name = cols[0].text_input("来源名称", placeholder="例如：OpenAI Changelog")
            source_type = cols[1].selectbox(
                "来源类型",
                list(TYPE_LABELS),
                format_func=lambda value: TYPE_LABELS[value],
            )
            url = st.text_input("URL", placeholder="https://...")
            github_cols = st.columns(2)
            repository = github_cols[0].text_input(
                "GitHub 仓库（可选）",
                placeholder="owner/repo",
                help="GitHub 类型可填写；留空时会尝试从 URL 识别。",
            )
            path_filter = github_cols[1].text_input(
                "只关注这些路径（可选）",
                placeholder="docs/ 或 /engineering/",
            )
            topic_id = st.selectbox(
                "归入领域",
                [None, *[topic.id for topic in topics]],
                index=0,
                format_func=lambda value: (
                    "自动分配（推荐）"
                    if value is None
                    else topic_names[value]
                ),
                help=(
                    "默认由 AI 根据每条资讯内容判断领域。"
                    "手动选择后，该领域只作为 AI 无法匹配时的兜底。"
                ),
            )
            submitted = st.form_submit_button(
                "保存并去测试",
                type="primary",
                width="stretch",
            )
        if submitted:
            if not name.strip() or not url.strip():
                st.error("请填写来源名称和 URL。")
            else:
                try:
                    with session_scope() as session:
                        session.add(
                            SourceConfig(
                                name=name.strip(),
                                source_type=source_type,
                                url=url.strip(),
                                repository=repository.strip(),
                                path_filter=path_filter.strip(),
                                enabled=False,
                                test_status="UNTESTED",
                                default_topic_id=topic_id,
                            )
                        )
                    st.session_state["_source_created_name"] = name.strip()
                    st.session_state["_source_add_open"] = False
                    st.rerun()
                except IntegrityError:
                    st.error("这个类型和 URL 已经存在。")


def _render_sources() -> None:
    topics, sources = _load_data()
    topic_names = {topic.id: topic.name for topic in topics}
    st.markdown("### 已配置来源")
    st.caption(f"共 {len(sources)} 个来源 · 只有测试通过的来源可以开启")
    if not sources:
        st.info("还没有资讯源。请先从上方添加一个。")
        return

    for source in sources:
        test_status = source.test_status or "UNTESTED"
        status_text, status_class = TEST_LABELS.get(
            test_status,
            TEST_LABELS["UNTESTED"],
        )
        collection_status = "自动采集中" if source.enabled else status_text
        summary = (
            f"{source.name} · "
            f"{TYPE_LABELS.get(source.source_type, source.source_type)} · "
            f"{topic_names.get(source.default_topic_id, '自动分配')} · "
            f"{collection_status}"
        )
        with st.expander(summary, expanded=False):
            title_col, status_col = st.columns([4, 1])
            title_col.markdown(
                f"**{escape(source.name)}**  "
                f'<span class="source-type">{escape(TYPE_LABELS.get(source.source_type, source.source_type))}</span>',
                unsafe_allow_html=True,
            )
            title_col.caption(
                f"{topic_names.get(source.default_topic_id, '自动分配')} · "
                f"最近采集 {fmt_dt(source.last_collected_at)}"
            )
            status_col.markdown(
                f'<span class="source-test-status {status_class}">{escape(status_text)}</span>',
                unsafe_allow_html=True,
            )
            st.caption(source.url)
            if source.path_filter:
                st.caption(f"关注范围：{source.path_filter}")

            test_col, enable_col, link_col = st.columns([1.2, 1.2, 2.6])
            if test_col.button(
                "测试连接",
                key=f"test_source_{source.id}",
                width="stretch",
            ):
                with st.spinner(f"正在测试 {source.name}…"):
                    result = orchestrator.test_source(source.id)
                st.session_state[f"source_test_result_{source.id}"] = result
                if result["status"] == "PASSED":
                    st.toast("测试通过，现在可以启用", icon="✅")
                else:
                    st.toast("测试失败，请检查配置", icon="⚠️")
                st.rerun()

            enabled = enable_col.toggle(
                "自动采集",
                value=source.enabled,
                key=f"source_enabled_{source.id}",
                disabled=test_status != "PASSED",
                help=(
                    "测试通过后可开启"
                    if test_status != "PASSED"
                    else "开启后会进入定时采集"
                ),
            )
            if enabled != source.enabled:
                with session_scope() as session:
                    current = session.get(SourceConfig, source.id)
                    if current is not None:
                        current.enabled = enabled
                st.toast("来源已开启" if enabled else "来源已关闭")
                st.rerun()
            if source.url.startswith(("https://", "http://")):
                link_col.link_button(
                    "打开来源",
                    source.url,
                    width="stretch",
                )

            result = st.session_state.pop(
                f"source_test_result_{source.id}",
                None,
            )
            if result:
                if result["status"] == "PASSED":
                    samples = result.get("sample_titles") or []
                    sample_text = f"；读取到：{samples[0]}" if samples else ""
                    st.success(f"连接正常{sample_text}")
                else:
                    st.error(result.get("error") or "无法访问该来源")
            elif source.last_error:
                st.error(source.last_error)


render()
