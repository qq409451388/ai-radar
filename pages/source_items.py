"""原始资讯 page: 浏览采集到的所有 source_item（section 十七 补充）.

采集到的资讯不会自动消失，全部保存在 source_item 表中。本页面用于
查看采集结果、筛选状态、检查为何某条资讯没有形成知识变化点。
"""
from __future__ import annotations

import streamlit as st
from sqlalchemy import or_, select

from ai_radar.database import session_scope
from ai_radar.models import ChangePointSource, SourceConfig, SourceItem
from ai_radar.ui import fmt_dt

STATUS_LABEL = {
    "PENDING": "⏳ 待分析",
    "SUCCESS": "✅ 已形成知识点",
    "IGNORED": "🚫 已过滤",
    "FAILED": "❌ 分析失败",
}


def render() -> None:
    st.header("📰 原始资讯")
    st.caption("采集到的全部资讯。状态说明：⏳ 待分析 / ✅ 已形成知识变化点 / 🚫 被 LLM 过滤（融资、跑分、八卦等）/ ❌ 分析失败")

    with session_scope() as session:
        sources = list(session.execute(select(SourceConfig).order_by(SourceConfig.id)).scalars())
        src_map = {s.id: s.name for s in sources}

        # ---- 顶部统计 ----
        total = session.execute(select(SourceItem)).scalars().all()
        by_status: dict[str, int] = {}
        for it in total:
            by_status[it.analyze_status] = by_status.get(it.analyze_status, 0) + 1
        cols = st.columns(5)
        cols[0].metric("总数", len(total))
        cols[1].metric("待分析", by_status.get("PENDING", 0))
        cols[2].metric("已形成知识点", by_status.get("SUCCESS", 0))
        cols[3].metric("已过滤", by_status.get("IGNORED", 0))
        cols[4].metric("失败", by_status.get("FAILED", 0))

        st.divider()

        # ---- 筛选 ----
        cols = st.columns(4)
        sel_source = cols[0].selectbox(
            "来源",
            ["全部"] + list(src_map.keys()),
            format_func=lambda i: "全部" if i == "全部" else src_map.get(i, str(i)),
        )
        sel_status = cols[1].selectbox(
            "状态",
            ["全部", "PENDING", "SUCCESS", "IGNORED", "FAILED"],
            format_func=lambda s: "全部" if s == "全部" else STATUS_LABEL.get(s, s),
        )
        keyword = cols[2].text_input("关键词（标题/内容）")
        limit = cols[3].slider("最多显示", 50, 500, 200, step=50)

        stmt = select(SourceItem).order_by(SourceItem.collected_at.desc())
        if sel_source != "全部":
            stmt = stmt.where(SourceItem.source_config_id == sel_source)
        if sel_status != "全部":
            stmt = stmt.where(SourceItem.analyze_status == sel_status)
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(or_(SourceItem.title.ilike(kw), SourceItem.raw_content.ilike(kw)))
        stmt = stmt.limit(limit)

        items = list(session.execute(stmt).scalars())

        st.subheader(f"显示 {len(items)} 条（按采集时间倒序）")

        # 预加载这些 item 是否已关联到 change_point
        linked_cp: dict[int, int] = {}
        if items:
            item_ids = [it.id for it in items]
            rows = session.execute(
                select(ChangePointSource.source_item_id, ChangePointSource.change_point_id)
                .where(ChangePointSource.source_item_id.in_(item_ids))
            ).all()
            for sid, cpid in rows:
                linked_cp[sid] = cpid

        for it in items:
            label = it.title or it.url or f"#{it.id}"
            status_badge = STATUS_LABEL.get(it.analyze_status, it.analyze_status)
            cp_link = linked_cp.get(it.id)
            cp_hint = f" · 🔗 知识点 #{cp_link}" if cp_link else ""
            with st.expander(f"{status_badge} · {label}{cp_hint}"):
                cols = st.columns([3, 2, 2])
                cols[0].caption(f"来源: {src_map.get(it.source_config_id, '?')}")
                cols[1].caption(f"发布: {fmt_dt(it.published_at)}")
                cols[2].caption(f"采集: {fmt_dt(it.collected_at)}")
                if it.url:
                    st.markdown(f"链接: [{it.url}]({it.url})")
                if it.author:
                    st.caption(f"作者: {it.author}")
                if it.raw_content:
                    st.text_area(
                        "正文",
                        value=it.raw_content[:4000],
                        height=240,
                        disabled=True,
                        key=f"rc_{it.id}",
                    )
                if it.analyze_status == "FAILED" and it.analyze_error:
                    st.error(f"分析失败原因: {it.analyze_error}")
                if it.analyze_status == "IGNORED":
                    st.caption("该资讯被 LLM 判定为融资/跑分/八卦/营销软文等，未形成知识变化点。")
                if cp_link:
                    st.info(f"已关联到知识变化点 #{cp_link}（在「知识变化点」页可查看）")


render()
