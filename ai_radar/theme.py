"""Visual system shared by the redesigned Streamlit pages."""
from __future__ import annotations

import streamlit as st


def inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --radar-ink: #172033;
          --radar-muted: #667085;
          --radar-line: #e7eaf0;
          --radar-surface: #ffffff;
          --radar-soft: #f5f7fb;
          --radar-accent: #5b5bd6;
          --radar-accent-soft: #eeefff;
          --radar-good: #16856b;
          --radar-warn: #c27816;
          --radar-bad: #c44747;
        }
        .stApp { background: #f7f8fb; color: var(--radar-ink); }
        [data-testid="stHeader"] { background: rgba(247,248,251,.88); }
        [data-testid="stSidebar"] { border-right: 1px solid var(--radar-line); }
        [data-testid="stSidebar"] > div:first-child { background: #fbfbfd; }
        [data-testid="stMainBlockContainer"] {
          max-width: 1440px;
          padding-top: 2rem;
          padding-bottom: 4rem;
        }
        h1, h2, h3 { letter-spacing: -.025em; color: var(--radar-ink); }
        h1 { font-size: 2.15rem !important; }
        .radar-brand { display:flex; align-items:center; gap:.75rem; padding:.4rem 0 1.5rem; }
        .radar-brand-mark {
          display:grid; place-items:center; width:2.35rem; height:2.35rem;
          border-radius:.8rem; color:white; background:var(--radar-accent);
          font-size:1.25rem; box-shadow:0 8px 24px rgba(91,91,214,.22);
        }
        .radar-brand-title { font-weight:750; font-size:1.08rem; color:var(--radar-ink); }
        .radar-brand-subtitle { color:var(--radar-muted); font-size:.72rem; margin-top:.08rem; }
        .sidebar-label {
          color:#98a2b3; font-size:.68rem; font-weight:700; letter-spacing:.12em;
          text-transform:uppercase; margin:1.1rem 0 .45rem;
        }
        .sidebar-status {
          padding:.8rem .9rem; border:1px solid var(--radar-line);
          background:white; border-radius:.85rem; font-size:.78rem; color:var(--radar-muted);
        }
        .sidebar-status > div { display:flex; align-items:center; gap:.45rem; margin:.34rem 0; }
        .sidebar-status b { margin-left:auto; color:var(--radar-ink); font-weight:650; }
        .status-dot { width:.48rem; height:.48rem; border-radius:99px; background:#98a2b3; }
        .status-dot.ok { background:var(--radar-good); box-shadow:0 0 0 3px #e2f4ee; }
        .status-dot.warn { background:var(--radar-warn); box-shadow:0 0 0 3px #fff1da; }
        .status-dot.bad { background:var(--radar-bad); box-shadow:0 0 0 3px #fde8e8; }
        .page-kicker {
          color:var(--radar-accent); font-size:.72rem; font-weight:750;
          letter-spacing:.12em; text-transform:uppercase; margin-bottom:.35rem;
        }
        .page-subtitle { color:var(--radar-muted); margin-top:-.7rem; margin-bottom:1.5rem; }
        .radar-card {
          background:var(--radar-surface); border:1px solid var(--radar-line);
          border-radius:1rem; padding:1rem 1.1rem; min-height:100%;
          box-shadow:0 1px 2px rgba(16,24,40,.025);
        }
        .card-label { color:var(--radar-muted); font-size:.72rem; font-weight:650; }
        .card-value { color:var(--radar-ink); font-size:1.65rem; font-weight:750; margin:.25rem 0; }
        .card-detail { color:var(--radar-muted); font-size:.76rem; }
        .card-value.good { color:var(--radar-good); }
        .card-value.warn { color:var(--radar-warn); }
        .card-value.bad { color:var(--radar-bad); }
        .section-heading { font-size:1.05rem; font-weight:720; margin:1.8rem 0 .2rem; }
        .section-caption { color:var(--radar-muted); font-size:.78rem; margin-bottom:.8rem; }
        .priority-card {
          background:white; border:1px solid var(--radar-line); border-radius:.9rem;
          padding:1rem 1.05rem; margin:.55rem 0;
        }
        .priority-card.critical { border-left:4px solid var(--radar-bad); }
        .priority-card.watch { border-left:4px solid var(--radar-warn); }
        .priority-title { font-size:.94rem; font-weight:700; color:var(--radar-ink); }
        .priority-meta { color:var(--radar-muted); font-size:.72rem; margin:.3rem 0 .6rem; }
        .pill {
          display:inline-block; padding:.18rem .5rem; border-radius:99px;
          background:var(--radar-soft); color:var(--radar-muted); font-size:.68rem;
          font-weight:650; margin-right:.3rem;
        }
        .pill.none { background:#fff0f0; color:var(--radar-bad); }
        .pill.aware { background:#fff5df; color:#9c640d; }
        .pill.understood { background:#edf3ff; color:#3564b5; }
        .pill.practiced { background:#e8f7f1; color:var(--radar-good); }
        div[data-testid="stMetric"] {
          background:white; border:1px solid var(--radar-line); border-radius:.9rem;
          padding:.85rem 1rem;
        }
        div[data-testid="stExpander"] {
          background:white; border-color:var(--radar-line); border-radius:.85rem;
        }
        .stButton > button, .stDownloadButton > button {
          border-radius:.7rem; font-weight:650; min-height:2.5rem;
        }
        .stButton > button[kind="primary"] {
          background:var(--radar-accent); border-color:var(--radar-accent);
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] { gap:.35rem; }
        [data-testid="stTabs"] button {
          border-radius:.65rem .65rem 0 0; font-weight:650;
        }
        @media (max-width: 800px) {
          [data-testid="stMainBlockContainer"] { padding:1.2rem .9rem 3rem; }
          h1 { font-size:1.7rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
