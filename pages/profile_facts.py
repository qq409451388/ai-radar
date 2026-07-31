"""个人事实 page: GitHub file sync status + extracted facts (section 十七.4)."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from ai_radar.database import session_scope
from ai_radar.models import ProfileFact, ProfileSourceFile, Topic
from ai_radar.ui import fmt_dt, profile_files


def render() -> None:
    st.header("📂 个人事实")
    with session_scope() as session:
        files = profile_files(session)
        if not files:
            st.info("尚未同步任何 GitHub 记忆文件。请在「系统任务」页面执行「同步 GitHub 记忆」。")
            return

        cols = st.columns([3, 2, 2, 2, 3])
        cols[0].markdown("**文件路径**")
        cols[1].markdown("**同步状态**")
        cols[2].markdown("**最后成功**")
        cols[3].markdown("**事实数**")
        cols[4].markdown("**错误**")
        for f in files:
            facts = list(
                session.execute(
                    select(ProfileFact).where(
                        ProfileFact.source_file_id == f.id, ProfileFact.active == True  # noqa: E712
                    )
                ).scalars()
            )
            cols = st.columns([3, 2, 2, 2, 3])
            cols[0].write(f.file_path)
            color = "#27ae60" if f.sync_status == "SUCCESS" else "#e74c3c"
            cols[1].markdown(f"<span style='color:{color}'>{f.sync_status}</span>", unsafe_allow_html=True)
            cols[2].write(fmt_dt(f.last_success_at))
            cols[3].write(len(facts))
            cols[4].caption(f.sync_error or "—")
            st.markdown("---")

            for fact in facts:
                topic = fact.topic.name if fact.topic else "—"
                with st.expander(
                    f"[{fact.evidence_type}] {fact.fact_text[:40]}…  ·  {topic}"
                ):
                    st.write(fact.fact_text)
                    cols2 = st.columns(4)
                    cols2[0].caption(f"fact_key: `{fact.fact_key}`")
                    cols2[1].caption(f"来源标题: {fact.source_heading or '—'}")
                    cols2[2].caption(f"行号: {fact.source_line_start}-{fact.source_line_end}")
                    cols2[3].caption(f"抽取时间: {fmt_dt(fact.extracted_at)}")
                    st.caption(f"sha: `{f.github_sha[:12]}…`")


render()
