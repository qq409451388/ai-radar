"""Personal progress and evidence ledger."""
from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from ai_radar import orchestrator
from ai_radar.database import session_scope
from ai_radar.models import (
    ChangePoint,
    KnowledgeCoverage,
    ProfileFact,
    ProfileSourceFile,
    Topic,
)
from ai_radar.services.scoring_service import ScoringService
from ai_radar.ui import fmt_dt

EVIDENCE_LABEL = {
    "DISCUSSION": "讨论",
    "RESEARCH": "研究",
    "DESIGN": "设计",
    "DEMO": "Demo",
    "IMPLEMENTATION": "实现",
    "PRODUCTION": "生产",
    "DECISION": "决策",
}


def render() -> None:
    query_topic = _query_int("topic")
    st.markdown('<div class="page-kicker">Personal progress</div>', unsafe_allow_html=True)
    st.title("我的进展")
    st.markdown(
        '<div class="page-subtitle">GPT 交流不是阅读记录，而是转化为可验证的研究、设计和实践证据。</div>',
        unsafe_allow_html=True,
    )

    top_cols = st.columns([1.15, 3])
    if top_cols[0].button("同步最新 GPT 记忆", type="primary", width="stretch"):
        with st.spinner("正在读取 GitHub、抽取增量事实并关联知识变化…"):
            result = orchestrator.sync_profile()
        if result.get("error"):
            st.error(result["error"])
        else:
            st.success(
                f"同步 {result['synced']} 个文件，变化 {result['changed']} 个，"
                f"成功抽取 {result.get('extracted', 0)} 个。"
            )
            st.rerun()
    top_cols[1].caption(
        "只有 Markdown 内容发生变化或上次抽取失败时才调用模型；"
        "成功内容会按 hash 缓存。"
    )

    with session_scope() as session:
        topics = list(session.execute(select(Topic).order_by(Topic.id)).scalars())
        topic_names = {topic.id: topic.name for topic in topics}
        topic_health = ScoringService(session).compute_all_topic_health()
        facts = list(
            session.execute(
                select(ProfileFact)
                .where(ProfileFact.active == True)  # noqa: E712
                .order_by(ProfileFact.extracted_at.desc())
            ).scalars()
        )
        files = list(
            session.execute(
                select(ProfileSourceFile).order_by(ProfileSourceFile.file_path)
            ).scalars()
        )
        practiced = sum(
            1
            for fact in facts
            if fact.evidence_type in ("DEMO", "IMPLEMENTATION", "PRODUCTION")
        )
        strong = sum(
            1
            for fact in facts
            if fact.evidence_type
            in ("RESEARCH", "DESIGN", "DECISION", "DEMO", "IMPLEMENTATION", "PRODUCTION")
        )
        unclassified = sum(1 for fact in facts if fact.topic_id is None)
        transitions = list(
            session.execute(
                select(KnowledgeCoverage, ChangePoint)
                .join(ChangePoint, ChangePoint.id == KnowledgeCoverage.change_point_id)
                .order_by(KnowledgeCoverage.assessed_at.desc())
                .limit(40)
            ).all()
        )

        metrics = st.columns(4)
        metrics[0].metric("有效个人事实", len(facts))
        metrics[1].metric("研究及以上证据", strong)
        metrics[2].metric("实践证据", practiced)
        metrics[3].metric("待归类事实", unclassified)

        overview_tab, evidence_tab, files_tab = st.tabs(
            ["进展概览", "事实证据", "同步文件"]
        )
        with overview_tab:
            st.markdown("### 领域温度")
            st.caption("完整领域评分与知识缺口集中在这里查看。")
            visible_topics = (
                [topic for topic in topics if topic.id == query_topic]
                if query_topic in topic_names
                else topics
            )
            if query_topic in topic_names:
                focus_cols = st.columns([3, 1])
                focus_cols[0].info(
                    f"正在查看首页提示的领域：{topic_names[query_topic]}"
                )
                focus_cols[1].page_link(
                    "pages/progress.py",
                    label="查看全部领域",
                    width="stretch",
                )
            for topic in visible_topics:
                item = topic_health[topic.id]
                label_col, value_col = st.columns([3, 1])
                label_col.markdown(f"**{topic.name}**")
                value_col.markdown(f"**{item['score']:.0f}%**")
                st.progress(item["score"] / 100)
                st.caption(
                    f"{item['change_point_count']} 个变化 · "
                    f"{item['important_gap_count']} 个重要缺口 · "
                    f"实践率 {item['practiced_rate']:.0f}%"
                )

            st.divider()
            left, right = st.columns([1.15, 1])
            with left:
                st.markdown("### 领域证据分布")
                counts = Counter(
                    topic_names.get(fact.topic_id, "待归类") for fact in facts
                )
                if counts:
                    data = pd.DataFrame(
                        [
                            {"领域": name, "事实数": count}
                            for name, count in counts.most_common()
                        ]
                    )
                    st.bar_chart(data.set_index("领域"), horizontal=True)
                else:
                    st.info("还没有事实记录。先同步 GPT 记忆。")
            with right:
                st.markdown("### 最近覆盖变化")
                if not transitions:
                    st.caption("尚无覆盖评估记录")
                for cov, cp in transitions[:10]:
                    st.markdown(f"**{cp.title[:42]}**")
                    st.caption(
                        f"{cov.coverage_level} · {cov.trigger_type} · "
                        f"{fmt_dt(cov.assessed_at)}"
                    )

        with evidence_tab:
            filter_cols = st.columns([1.4, 1.4, 2])
            selected_topic = filter_cols[0].selectbox(
                "领域",
                [None] + [topic.id for topic in topics],
                format_func=lambda value: "全部领域"
                if value is None
                else topic_names[value],
            )
            selected_evidence = filter_cols[1].selectbox(
                "证据类型",
                [None] + list(EVIDENCE_LABEL),
                format_func=lambda value: "全部类型"
                if value is None
                else EVIDENCE_LABEL[value],
            )
            keyword = filter_cols[2].text_input("搜索事实")
            filtered = [
                fact
                for fact in facts
                if (selected_topic is None or fact.topic_id == selected_topic)
                and (
                    selected_evidence is None
                    or fact.evidence_type == selected_evidence
                )
                and (
                    not keyword
                    or keyword.lower() in fact.fact_text.lower()
                    or keyword.lower() in fact.fact_key.lower()
                )
            ]
            st.caption(f"显示 {len(filtered)} 条")
            for fact in filtered[:100]:
                with st.expander(
                    f"{EVIDENCE_LABEL.get(fact.evidence_type, fact.evidence_type)} · "
                    f"{fact.fact_text[:56]}"
                ):
                    st.write(fact.fact_text)
                    source_file = session.get(
                        ProfileSourceFile, fact.source_file_id
                    )
                    st.caption(
                        f"{topic_names.get(fact.topic_id, '待归类')} · "
                        f"{source_file.file_path if source_file else '未知文件'}:"
                        f"{fact.source_line_start}-{fact.source_line_end} · "
                        f"抽取 {fmt_dt(fact.extracted_at)}"
                    )

        with files_tab:
            if not files:
                st.info("尚未同步 GitHub 记忆仓库。")
            for source_file in files:
                with st.container(border=True):
                    cols = st.columns([2.5, 1, 1.3, 1.3])
                    cols[0].markdown(f"**{source_file.file_path}**")
                    cols[1].markdown(
                        "✅ 已抽取"
                        if source_file.extraction_status == "SUCCESS"
                        else "⚠️ 待处理"
                        if source_file.extraction_status == "PENDING"
                        else "❌ 失败"
                    )
                    cols[2].caption(
                        f"同步 {fmt_dt(source_file.last_success_at)}"
                    )
                    cols[3].caption(
                        f"抽取 {fmt_dt(source_file.last_extracted_at)}"
                    )
                    if source_file.extraction_error:
                        st.error(source_file.extraction_error)
                    file_fact_count = session.scalar(
                        select(func.count(ProfileFact.id)).where(
                            ProfileFact.source_file_id == source_file.id,
                            ProfileFact.active == True,  # noqa: E712
                        )
                    ) or 0
                    st.caption(
                        f"{file_fact_count} 条有效事实 · "
                        f"内容 hash {source_file.content_hash[:12]}…"
                    )


def _query_int(key: str) -> int | None:
    try:
        return int(st.query_params.get(key, ""))
    except (TypeError, ValueError):
        return None


render()
