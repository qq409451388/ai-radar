"""评分依据 page: per-change-point coverage rationale (section 十七.5)."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from ai_radar.database import session_scope
from ai_radar.models import ChangePoint, ProfileFact, ProfileSourceFile
from ai_radar.ui import coverage_color, fmt_dt, latest_coverage
from ai_radar.utils import load_json


def render() -> None:
    st.header("🔍 评分依据")
    with session_scope() as session:
        cps = list(
            session.execute(
                select(ChangePoint)
                .where(ChangePoint.status == "ACTIVE")
                .order_by(ChangePoint.importance.desc(), ChangePoint.id)
            ).scalars()
        )
        if not cps:
            st.info("尚无活跃知识变化点。")
            return
        for cp in cps:
            with st.expander(f"{cp.title}  ·  {cp.event_key}"):
                cov = latest_coverage(session, cp.id)
                if cov is None:
                    st.warning("尚未评估覆盖")
                    continue
                color = coverage_color(cov.coverage_level)
                st.markdown(
                    f"覆盖等级：<span style='color:{color}'>{cov.coverage_level}</span> "
                    f"（系数 {cov.coverage_coefficient:.2f}） · 置信度 {cov.confidence:.2f}",
                    unsafe_allow_html=True,
                )
                st.caption(f"评估时间：{fmt_dt(cov.assessed_at)} · 模型：{cov.model_name or '—'}")
                if cov.rationale:
                    st.write(cov.rationale)

                matched_ids = load_json(cov.matched_fact_ids_json, default=[])
                st.subheader("匹配到的个人事实")
                if not matched_ids:
                    st.caption("无匹配事实（知识缺口）")
                else:
                    for fid in matched_ids:
                        fact = session.get(ProfileFact, int(fid))
                        if fact is None:
                            st.caption(f"· （已删除）id={fid}")
                            continue
                        sf = session.get(ProfileSourceFile, fact.source_file_id)
                        st.markdown(f"- {fact.fact_text}")
                        st.caption(
                            f"文件：{sf.file_path if sf else '—'} · 行号 {fact.source_line_start}-"
                            f"{fact.source_line_end} · 类型 {fact.evidence_type}"
                        )


render()
