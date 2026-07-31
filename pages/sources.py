"""资讯源管理 page: CRUD + manual collection (section 十七.6)."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from ai_radar.bootstrap import SOURCE_TYPE_GITHUB_RELEASE, SOURCE_TYPE_RSS
from ai_radar.database import session_scope
from ai_radar.models import SourceConfig, Topic
from ai_radar.orchestrator import collect_one_source
from ai_radar.ui import fmt_dt


def render() -> None:
    st.header("📡 资讯源管理")
    with session_scope() as session:
        sources = list(session.execute(select(SourceConfig).order_by(SourceConfig.id)).scalars())
        topics = list(session.execute(select(Topic).order_by(Topic.id)).scalars())
        topic_options = {t.id: t.name for t in topics}

        st.subheader("新增资讯源")
        with st.form("add_source"):
            cols = st.columns(4)
            name = cols[0].text_input("名称")
            source_type = cols[1].selectbox("类型", [SOURCE_TYPE_RSS, SOURCE_TYPE_GITHUB_RELEASE])
            url = cols[2].text_input("URL")
            repository = cols[3].text_input("仓库（owner/repo，仅 GitHub Release）")
            cols = st.columns(3)
            enabled = cols[0].checkbox("启用", value=True)
            default_topic = cols[1].selectbox(
                "默认领域",
                list(topic_options.keys()),
                format_func=lambda i: topic_options[i],
            )
            if st.form_submit_button("创建"):
                if not name or not url:
                    st.error("名称和 URL 必填")
                else:
                    sc = SourceConfig(
                        name=name,
                        source_type=source_type,
                        url=url,
                        repository=repository,
                        enabled=enabled,
                        default_topic_id=default_topic,
                    )
                    session.add(sc)
                    st.success("已创建，请刷新页面")

        st.divider()
        st.subheader("现有资讯源")
        for sc in sources:
            with st.expander(f"{sc.name} ({sc.source_type})"):
                cols = st.columns([2, 3, 1])
                cols[0].caption(f"URL: {sc.url}")
                cols[1].caption(f"仓库: {sc.repository or '—'}")
                cols[2].caption(f"启用: {sc.enabled}")
                st.caption(
                    f"默认领域: {topic_options.get(sc.default_topic_id, '—')} · "
                    f"最后采集: {fmt_dt(sc.last_collected_at)}"
                )
                if sc.last_error:
                    st.error(f"采集异常：{sc.last_error}")
                cols = st.columns([1, 1])
                if cols[0].button("手动采集", key=f"col_{sc.id}"):
                    result = collect_one_source(sc.id)
                    st.success(f"采集完成：新增 {result['new']}，已存在 {result['seen']}")
                with st.form(f"edit_src_{sc.id}"):
                    new_name = st.text_input("名称", sc.name, key=f"n{sc.id}")
                    new_url = st.text_input("URL", sc.url, key=f"u{sc.id}")
                    new_repo = st.text_input("仓库", sc.repository or "", key=f"r{sc.id}")
                    new_enabled = st.checkbox("启用", value=sc.enabled, key=f"e{sc.id}")
                    new_topic = st.selectbox(
                        "默认领域",
                        list(topic_options.keys()),
                        format_func=lambda i: topic_options[i],
                        index=list(topic_options.keys()).index(sc.default_topic_id) if sc.default_topic_id else 0,
                        key=f"t{sc.id}",
                    )
                    if st.form_submit_button("保存"):
                        sc.name = new_name
                        sc.url = new_url
                        sc.repository = new_repo
                        sc.enabled = new_enabled
                        sc.default_topic_id = new_topic
                        st.success("已保存")


render()
