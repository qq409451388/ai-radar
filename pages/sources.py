"""Dedicated information-source management page."""
from __future__ import annotations

from html import escape

import streamlit as st
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.models import SourceConfig, Topic
from ai_radar.services.source_service import SourceService
from ai_radar.ui import fmt_dt


TYPE_LABELS = {
    "RSS": "RSS 订阅",
    "WEB_PAGE": "网页",
    "GITHUB_RELEASE": "GitHub 版本",
    "GITHUB_COMMIT": "GitHub 文档变更",
}
TEST_LABELS = {
    "PASSED": ("连接正常", "success"),
    "FAILED": ("连接异常", "failed"),
    "UNTESTED": ("待测试", "pending"),
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

    heading_col, action_col = st.columns(
        [4, 1.15],
        vertical_alignment="bottom",
    )
    heading_col.markdown("### 已配置来源")
    heading_col.caption(
        f"共 {len(sources)} 个来源 · 展开单项可测试、启停或打开原站"
    )
    test_all = action_col.button(
        "测试全部来源",
        key="test_all_sources",
        width="stretch",
        disabled=not sources,
    )

    if not sources:
        st.info("还没有资讯源。请先从上方添加一个。")
        return

    if test_all:
        progress = st.progress(0, text="准备测试全部资讯源")

        def update_progress(done: int, total: int, message: str) -> None:
            ratio = done / total if total else 1.0
            progress.progress(ratio, text=message)

        result = orchestrator.test_all_sources(
            progress_callback=update_progress,
        )
        progress.empty()
        st.session_state["_all_source_test_result"] = result
        st.rerun()

    all_result = st.session_state.pop("_all_source_test_result", None)
    if all_result:
        if all_result["failed"]:
            failed_names = [
                item["source"]
                for item in all_result["results"]
                if item["status"] == "FAILED"
            ]
            preview = "、".join(failed_names[:3])
            suffix = "等" if len(failed_names) > 3 else ""
            st.warning(
                f"测试完成：{all_result['passed']} 个正常，"
                f"{all_result['failed']} 个异常（{preview}{suffix}）。"
            )
        else:
            st.success(f"全部 {all_result['passed']} 个来源连接正常。")

    for source in sources:
        test_status = source.test_status or "UNTESTED"
        status_text, status_class = TEST_LABELS.get(
            test_status,
            TEST_LABELS["UNTESTED"],
        )
        collection_status, state_icon, state_class = _source_state(source)
        summary = (
            f"{source.name}　·　"
            f"{TYPE_LABELS.get(source.source_type, source.source_type)}　·　"
            f"{topic_names.get(source.default_topic_id, '自动分配')}　·　"
            f"{collection_status}"
        )
        with st.expander(
            summary,
            expanded=False,
            key=f"source_details_{state_class}_{source.id}",
            icon=state_icon,
            type="compact",
        ):
            st.markdown(
                '<div class="source-detail-meta">'
                "<div><span>连接状态</span>"
                f'<strong class="{status_class}">{escape(status_text)}</strong></div>'
                "<div><span>最近测试</span>"
                f"<strong>{escape(fmt_dt(source.last_tested_at))}</strong></div>"
                "<div><span>最近采集</span>"
                f"<strong>{escape(fmt_dt(source.last_collected_at))}</strong></div>"
                "</div>",
                unsafe_allow_html=True,
            )
            link_markup = escape(source.url)
            if source.url.startswith(("https://", "http://")):
                link_markup = (
                    f'<a href="{escape(source.url, quote=True)}" target="_blank">'
                    f"{escape(source.url)}</a>"
                )
            st.markdown(
                f'<div class="source-detail-url">{link_markup}</div>',
                unsafe_allow_html=True,
            )
            if source.path_filter:
                st.markdown(
                    '<div class="source-detail-scope">'
                    f"只关注：{escape(source.path_filter)}"
                    "</div>",
                    unsafe_allow_html=True,
                )

            editing = st.session_state.get("_source_edit_id") == source.id
            deleting = st.session_state.get("_source_delete_id") == source.id
            if editing:
                _render_edit_source(source, topics, topic_names)
            elif deleting:
                _render_delete_source(source)
            else:
                _render_source_actions(source, test_status)


def _source_state(source: SourceConfig) -> tuple[str, str, str]:
    test_status = source.test_status or "UNTESTED"
    if test_status == "FAILED":
        return "连接异常", "❌", "failed"
    if test_status != "PASSED":
        return "待测试", "⚪", "untested"
    if source.enabled:
        return "采集中", "✅", "collecting"
    return "已停用", "⛔", "stopped"


def _render_source_actions(source: SourceConfig, test_status: str) -> None:
    test_col, enable_col, link_col, edit_col, delete_col = st.columns(
        [1.15, 1.25, 1.1, .82, .82],
        vertical_alignment="center",
    )
    if test_col.button(
        "重新测试",
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
    if edit_col.button(
        "编辑",
        key=f"edit_source_{source.id}",
        width="stretch",
    ):
        st.session_state["_source_edit_id"] = source.id
        st.session_state.pop("_source_delete_id", None)
        st.rerun()
    if delete_col.button(
        "删除",
        key=f"delete_source_{source.id}",
        width="stretch",
    ):
        st.session_state["_source_delete_id"] = source.id
        st.session_state.pop("_source_edit_id", None)
        st.rerun()

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


def _render_edit_source(
    source: SourceConfig,
    topics: list[Topic],
    topic_names: dict[int, str],
) -> None:
    with st.container(
        border=True,
        key=f"source_edit_panel_{source.id}",
    ):
        st.markdown("**编辑来源**")
        st.caption("修改连接地址、类型或关注范围后，需要重新测试才能开启采集。")
        with st.form(f"edit_source_form_{source.id}", border=False):
            cols = st.columns(2)
            name = cols[0].text_input("来源名称", value=source.name)
            source_types = list(TYPE_LABELS)
            type_index = (
                source_types.index(source.source_type)
                if source.source_type in source_types
                else 0
            )
            source_type = cols[1].selectbox(
                "来源类型",
                source_types,
                index=type_index,
                format_func=lambda value: TYPE_LABELS[value],
            )
            url = st.text_input("URL", value=source.url)
            config_cols = st.columns(2)
            repository = config_cols[0].text_input(
                "GitHub 仓库（可选）",
                value=source.repository or "",
                help="GitHub 类型可填写；留空时会尝试从 URL 识别。",
            )
            path_filter = config_cols[1].text_input(
                "只关注这些路径（可选）",
                value=source.path_filter or "",
            )
            topic_options = [None, *[topic.id for topic in topics]]
            topic_index = (
                topic_options.index(source.default_topic_id)
                if source.default_topic_id in topic_options
                else 0
            )
            topic_id = st.selectbox(
                "归入领域",
                topic_options,
                index=topic_index,
                format_func=lambda value: (
                    "自动分配（推荐）"
                    if value is None
                    else topic_names[value]
                ),
            )
            save_col, cancel_col = st.columns([1.4, 1])
            saved = save_col.form_submit_button(
                "保存修改",
                type="primary",
                width="stretch",
            )
            cancelled = cancel_col.form_submit_button(
                "取消",
                width="stretch",
            )

        if cancelled:
            st.session_state.pop("_source_edit_id", None)
            st.rerun()
        if saved:
            if not name.strip() or not url.strip():
                st.error("请填写来源名称和 URL。")
                return
            try:
                with session_scope() as session:
                    result = SourceService(session).update(
                        source.id,
                        name=name.strip(),
                        source_type=source_type,
                        url=url.strip(),
                        repository=repository.strip(),
                        path_filter=path_filter.strip(),
                        default_topic_id=topic_id,
                    )
                st.session_state.pop("_source_edit_id", None)
                if result["connection_changed"]:
                    st.toast("修改已保存，请重新测试连接", icon="✅")
                else:
                    st.toast("修改已保存", icon="✅")
                st.rerun()
            except IntegrityError:
                st.error("这个类型和 URL 已经被其他来源使用。")


def _render_delete_source(source: SourceConfig) -> None:
    with session_scope() as session:
        item_count = SourceService(session).item_count(source.id)
    with st.container(
        border=True,
        key=f"source_delete_panel_{source.id}",
    ):
        st.markdown("**确认删除这个来源？**")
        st.caption(
            f"将删除“{source.name}”和它采集的 {item_count} 条原始资讯及证据关联。"
            "已经形成的知识变化点和个人进度会保留。此操作无法撤销。"
        )
        confirm_col, cancel_col = st.columns([1.15, 1])
        confirmed = confirm_col.button(
            "确认删除",
            key=f"confirm_delete_source_{source.id}",
            width="stretch",
        )
        cancelled = cancel_col.button(
            "取消",
            key=f"cancel_delete_source_{source.id}",
            width="stretch",
        )
        if cancelled:
            st.session_state.pop("_source_delete_id", None)
            st.rerun()
        if confirmed:
            with session_scope() as session:
                result = SourceService(session).delete(source.id)
            st.session_state.pop("_source_delete_id", None)
            st.session_state.pop(f"source_enabled_{source.id}", None)
            st.session_state.pop(f"source_test_result_{source.id}", None)
            st.toast(
                f"“{result['source']}”已删除，"
                f"同时清理 {result['deleted_items']} 条原始资讯",
                icon="🗑️",
            )
            st.rerun()


render()
