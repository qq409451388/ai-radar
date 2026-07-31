"""知识变化点 page: filter, inspect, edit, deprecate, merge (section 十七.3)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import or_, select

from ai_radar.bootstrap import STATUS_ACTIVE, STATUS_DEPRECATED
from ai_radar.database import session_scope
from ai_radar.models import ChangePoint, ChangePointSource, SourceItem, Topic
from ai_radar.services.dedup_service import DedupService
from ai_radar.ui import (
    coverage_color,
    fmt_date,
    importance_label,
    latest_coverage,
    sources_for_change_point,
)


def render() -> None:
    st.header("🧩 知识变化点")
    with session_scope() as session:
        topics = list(session.execute(select(Topic).order_by(Topic.id)).scalars())
        topic_options = {t.id: t.name for t in topics}

        cols = st.columns(5)
        topic_filter = cols[0].selectbox("领域", ["全部"] + list(topic_options.values()))
        importance_filter = cols[1].selectbox("重要度", ["全部", "5", "3", "1"])
        coverage_filter = cols[2].selectbox(
            "覆盖等级", ["全部", "NONE", "AWARE", "UNDERSTOOD", "PRACTICED"]
        )
        status_filter = cols[3].selectbox(
            "状态", [STATUS_ACTIVE, STATUS_DEPRECATED, "全部"], index=0
        )
        keyword = cols[4].text_input("关键词搜索")

        stmt = select(ChangePoint)
        if topic_filter != "全部":
            stmt = stmt.join(Topic, Topic.id == ChangePoint.topic_id).where(Topic.name == topic_filter)
        if importance_filter != "全部":
            stmt = stmt.where(ChangePoint.importance == int(importance_filter))
        if status_filter != "全部":
            stmt = stmt.where(ChangePoint.status == status_filter)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ChangePoint.title.ilike(like),
                    ChangePoint.summary.ilike(like),
                    ChangePoint.event_key.ilike(like),
                )
            )
        stmt = stmt.order_by(ChangePoint.importance.desc(), ChangePoint.last_seen_at.desc())
        cps = list(session.execute(stmt).scalars())

        # Coverage filter
        if coverage_filter != "全部":
            filtered = []
            for cp in cps:
                cov = latest_coverage(session, cp.id)
                level = cov.coverage_level if cov else "NONE"
                if level == coverage_filter:
                    filtered.append(cp)
            cps = filtered

        st.caption(f"共 {len(cps)} 个知识点")

        for cp in cps:
            with st.expander(
                f"[{importance_label(cp.importance)}] {cp.title}  ·  {topic_options.get(cp.topic_id, '—')}"
            ):
                cols = st.columns([2, 2, 1])
                cols[0].caption(f"event_key: `{cp.event_key}`")
                cols[1].caption(f"状态: {cp.status}")
                cols[2].caption(f"首次发现: {fmt_date(cp.first_seen_at)}")
                st.write(cp.summary or "（无摘要）")
                if cp.why_it_matters:
                    st.info(cp.why_it_matters)

                cov = latest_coverage(session, cp.id)
                if cov:
                    color = coverage_color(cov.coverage_level)
                    st.markdown(
                        f"<span style='color:{color}'>覆盖：{cov.coverage_level} "
                        f"({cov.coverage_coefficient:.2f}) · 置信度 {cov.confidence:.2f}</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("覆盖：尚未评估")

                items = sources_for_change_point(session, cp.id)
                if items:
                    st.caption(f"关联资讯（{len(items)}）")
                    for it in items[:5]:
                        st.markdown(f"- [{it.title or it.url}]({it.url})")

                st.divider()
                with st.form(f"edit_cp_{cp.id}"):
                    new_title = st.text_input("标题", cp.title, key=f"t{cp.id}")
                    new_summary = st.text_area("摘要", cp.summary, key=f"s{cp.id}", height=120)
                    topic_ids = [t.id for t in topics]
                    default_idx = topic_ids.index(cp.topic_id) if cp.topic_id in topic_ids else 0
                    new_topic_id = st.selectbox(
                        "领域",
                        topic_ids,
                        format_func=lambda i: topic_options[i],
                        index=default_idx,
                        key=f"tp{cp.id}",
                    )
                    new_importance = st.select_slider(
                        "重要度", options=[1, 3, 5], value=cp.importance, key=f"im{cp.id}"
                    )
                    new_status = st.selectbox(
                        "状态",
                        [STATUS_ACTIVE, STATUS_DEPRECATED],
                        index=0 if cp.status == STATUS_ACTIVE else 1,
                        key=f"st{cp.id}",
                    )
                    submitted = st.form_submit_button("保存")
                    if submitted:
                        cp.title = new_title
                        cp.summary = new_summary
                        cp.topic_id = new_topic_id
                        cp.importance = new_importance
                        cp.status = new_status
                        st.success("已保存")

                with st.form(f"merge_cp_{cp.id}"):
                    other_ids = [o.id for o in cps if o.id != cp.id]
                    other_labels = {
                        o.id: f"{o.title[:30]} ({o.event_key})" for o in cps if o.id != cp.id
                    }
                    if other_ids:
                        target_id = st.selectbox(
                            "合并到（目标胜出）",
                            other_ids,
                            format_func=lambda i: other_labels[i],
                            key=f"mg{cp.id}",
                        )
                        if st.form_submit_button("合并"):
                            DedupService(session).merge(source_id=cp.id, target_id=target_id)
                            st.success("已合并")


render()
