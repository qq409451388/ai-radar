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
        [data-testid="stDialog"] {
          align-items:center !important;
          padding:12px !important;
          overflow:hidden !important;
        }
        [data-testid="stDialog"] > div {
          max-height:calc(100dvh - 24px) !important;
          margin:0 !important;
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
        .setup-hero {
          padding:1.55rem 1.7rem; border:1px solid #dfe2ff; border-radius:1.15rem;
          background:linear-gradient(135deg, #f0f0ff 0%, #fff 58%, #eef8f6 100%);
          box-shadow:0 10px 35px rgba(43,49,104,.06); margin-bottom:1.4rem;
        }
        .setup-hero-badge {
          color:var(--radar-accent); font-size:.68rem; font-weight:800;
          letter-spacing:.13em; margin-bottom:.45rem;
        }
        .setup-hero-title {
          color:var(--radar-ink); font-size:1.72rem; line-height:1.2;
          font-weight:780; letter-spacing:-.035em;
        }
        .setup-hero-copy {
          color:var(--radar-muted); max-width:48rem; font-size:.88rem;
          line-height:1.65; margin-top:.65rem;
        }
        .setup-stepper {
          display:flex; align-items:center; max-width:56rem; margin:0 auto 2rem;
          padding:.25rem .4rem;
        }
        .setup-step { display:flex; align-items:center; gap:.42rem; color:#98a2b3; }
        .setup-step-number {
          display:grid; place-items:center; width:1.75rem; height:1.75rem;
          border:1.5px solid #d8dce5; border-radius:99px; background:white;
          font-size:.72rem; font-weight:800;
        }
        .setup-step-label { font-size:.72rem; font-weight:700; white-space:nowrap; }
        .setup-step.active { color:var(--radar-accent); }
        .setup-step.active .setup-step-number {
          color:white; border-color:var(--radar-accent); background:var(--radar-accent);
          box-shadow:0 0 0 4px rgba(91,91,214,.1);
        }
        .setup-step.done { color:var(--radar-good); }
        .setup-step.done .setup-step-number {
          color:white; border-color:var(--radar-good); background:var(--radar-good);
        }
        .setup-step-line { height:1.5px; flex:1; min-width:1.2rem; background:#dfe2e8; margin:0 .55rem; }
        .setup-step-line.done { background:var(--radar-good); }
        .setup-guide-card {
          background:white; border:1px solid var(--radar-line); border-radius:1rem;
          padding:1.15rem 1.2rem; margin-bottom:.75rem;
        }
        .setup-guide-eyebrow {
          color:var(--radar-accent); font-size:.66rem; font-weight:800;
          letter-spacing:.1em; text-transform:uppercase;
        }
        .setup-guide-title { font-weight:750; font-size:1rem; margin:.3rem 0 .65rem; }
        .setup-guide-card ol { padding-left:1.2rem; margin:.4rem 0; }
        .setup-guide-card li { color:var(--radar-muted); font-size:.8rem; line-height:1.55; margin:.34rem 0; }
        .setup-guide-note {
          color:#4b5565; background:var(--radar-soft); border-radius:.65rem;
          padding:.65rem .7rem; font-size:.73rem; line-height:1.5; margin-top:.8rem;
        }
        .setup-review-row {
          display:grid; grid-template-columns:9rem 1fr 1.5rem; align-items:center;
          gap:.7rem; min-height:2.55rem; border-bottom:1px solid #eff1f5;
        }
        .setup-review-row:last-child { border-bottom:0; }
        .setup-review-label { color:var(--radar-muted); font-size:.76rem; font-weight:650; }
        .setup-review-value { color:var(--radar-ink); font-size:.8rem; overflow-wrap:anywhere; }
        .setup-review-status { color:var(--radar-good); font-weight:800; text-align:right; }
        .setup-security-note {
          color:#42685d; background:#eaf7f2; border:1px solid #d2eee4;
          border-radius:.8rem; padding:.8rem .9rem; font-size:.74rem;
          line-height:1.55; margin:.8rem 0 1rem; overflow-wrap:anywhere;
        }
        .setup-sidebar-note {
          display:flex; flex-direction:column; gap:.45rem; padding:.9rem;
          border:1px solid #dfe2ff; border-radius:.85rem; background:var(--radar-accent-soft);
        }
        .setup-sidebar-note b { color:var(--radar-ink); font-size:.82rem; }
        .setup-sidebar-note span { color:var(--radar-muted); font-size:.73rem; line-height:1.5; }
        .setup-sidebar-note small { color:var(--radar-good); font-weight:650; }
        .today-summary {
          max-width:56rem; color:#364153; font-size:1.08rem; line-height:1.75;
          text-wrap:pretty; margin:-.35rem 0 1rem;
        }
        .today-summary strong {
          color:var(--radar-ink); font-variant-numeric:tabular-nums;
        }
        .focus-title {
          color:var(--radar-ink); font-size:1rem; line-height:1.45;
          font-weight:750; overflow-wrap:anywhere; text-wrap:pretty;
        }
        .focus-relation {
          width:max-content; margin-left:auto; color:#4b4bb8;
          background:var(--radar-accent-soft); border-radius:99px;
          padding:.24rem .58rem; font-size:.7rem; font-weight:720;
        }
        .focus-summary {
          color:var(--radar-muted); font-size:.8rem; line-height:1.6;
          display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
          overflow:hidden; overflow-wrap:anywhere; margin:.2rem 0 .7rem;
        }
        .interest-count {
          color:var(--radar-muted); font-size:.74rem; text-align:right;
          font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap;
        }
        .today-empty {
          display:flex; flex-direction:column; gap:.4rem;
          border:1px dashed #cfd4df; border-radius:.95rem; padding:1.15rem 1.2rem;
          color:var(--radar-muted); background:rgba(255,255,255,.62);
          margin:.75rem 0;
        }
        .today-empty strong { color:var(--radar-ink); }
        .today-empty span { font-size:.8rem; line-height:1.55; }
        .section-heading { font-size:1.05rem; font-weight:720; margin:1.8rem 0 .2rem; }
        .section-caption { color:var(--radar-muted); font-size:.78rem; margin-bottom:.8rem; }
        .pipeline-choice-note {
          color:var(--radar-muted); font-size:.8rem; margin:-.2rem 0 .9rem;
        }
        .pipeline-empty {
          border:1px dashed #cfd4df; border-radius:.95rem; padding:1.2rem;
          color:var(--radar-muted); background:rgba(255,255,255,.55); margin:.8rem 0 1.25rem;
        }
        .pipeline-run-head {
          display:flex; align-items:flex-start; justify-content:space-between; gap:1rem;
          margin:1.1rem 0 .65rem;
        }
        .pipeline-run-title { font-weight:750; color:var(--radar-ink); margin-right:.55rem; }
        .pipeline-run-meta { color:var(--radar-muted); font-size:.72rem; padding-top:.18rem; }
        .update-center-intro {
          display:flex; flex-direction:column; gap:.28rem; padding:.9rem 1rem;
          border:1px solid #dfe2ff; border-radius:.9rem;
          background:linear-gradient(135deg, #f0f0ff, #fafaff);
        }
        .update-center-intro strong { color:var(--radar-ink); font-size:1rem; }
        .update-center-intro span { color:var(--radar-muted); font-size:.76rem; }
        .pipeline-running-dot {
          display:inline-block; width:.55rem; height:.55rem; margin-right:.42rem;
          border-radius:99px; background:var(--radar-accent);
          animation:pipeline-pulse 1.25s ease-in-out infinite;
        }
        .pipeline-status {
          display:inline-block; border-radius:99px; padding:.16rem .5rem;
          font-size:.68rem; font-weight:700; color:var(--radar-muted); background:#eef0f4;
        }
        .pipeline-status.running { color:#4b4bb8; background:var(--radar-accent-soft); }
        .pipeline-status.success { color:var(--radar-good); background:#e5f6ef; }
        .pipeline-status.partial { color:#9c640d; background:#fff3dc; }
        .pipeline-status.failed { color:var(--radar-bad); background:#fdeaea; }
        .pipeline-stepper {
          display:flex; align-items:flex-start; width:100%; padding:.8rem .15rem 1rem;
          overflow-x:auto;
        }
        .pipeline-step {
          flex:0 0 7rem; display:flex; flex-direction:column; align-items:center;
          text-align:center; color:#98a2b3;
        }
        .pipeline-step-dot {
          display:grid; place-items:center; width:2rem; height:2rem; border-radius:99px;
          border:2px solid #d7dbe4; background:white; font-size:.78rem; font-weight:800;
          position:relative; z-index:2;
        }
        .pipeline-step-label { margin-top:.42rem; font-size:.72rem; font-weight:650; }
        .pipeline-connector {
          flex:1 0 1.5rem; height:2px; margin:.98rem -.55rem 0;
          background:#dfe2e8; min-width:1.5rem;
        }
        .pipeline-connector.done { background:var(--radar-good); }
        .pipeline-step.success, .pipeline-step.partial { color:var(--radar-good); }
        .pipeline-step.success .pipeline-step-dot {
          color:white; background:var(--radar-good); border-color:var(--radar-good);
        }
        .pipeline-step.partial { color:var(--radar-warn); }
        .pipeline-step.partial .pipeline-step-dot {
          color:white; background:var(--radar-warn); border-color:var(--radar-warn);
        }
        .pipeline-step.running { color:var(--radar-accent); }
        .pipeline-step.running .pipeline-step-dot {
          color:var(--radar-accent); border-color:var(--radar-accent);
          background:var(--radar-accent-soft); box-shadow:0 0 0 5px rgba(91,91,214,.09);
          animation:pipeline-turn 1.4s linear infinite;
        }
        .pipeline-step.failed, .pipeline-step.interrupted { color:var(--radar-bad); }
        .pipeline-step.failed .pipeline-step-dot,
        .pipeline-step.interrupted .pipeline-step-dot {
          color:white; background:var(--radar-bad); border-color:var(--radar-bad);
        }
        .pipeline-step.skipped { color:#b0b5bf; }
        .pipeline-sidebar {
          padding:.72rem .82rem; border:1px solid #dfe2ff; border-radius:.8rem;
          background:var(--radar-accent-soft); margin:.65rem 0;
        }
        .pipeline-sidebar-title {
          display:flex; justify-content:space-between; gap:.5rem; font-size:.76rem;
          color:var(--radar-ink); font-weight:700; margin-bottom:.3rem;
        }
        .pipeline-sidebar-detail { color:var(--radar-muted); font-size:.68rem; }
        .pipeline-detail-title {
          display:flex; align-items:center; gap:.68rem; min-height:2.2rem;
        }
        .pipeline-detail-title span:last-child {
          display:flex; flex-direction:column; gap:.12rem;
        }
        .pipeline-detail-title small {
          color:var(--radar-muted); font-size:.69rem; line-height:1.35;
        }
        .pipeline-detail-icon {
          display:grid; place-items:center; flex:0 0 1.75rem;
          width:1.75rem; height:1.75rem; border-radius:99px;
          color:#7d8594; background:#f0f2f5; font-weight:800;
        }
        .pipeline-detail-icon.success { color:white; background:var(--radar-good); }
        .pipeline-detail-icon.partial { color:white; background:var(--radar-warn); }
        .pipeline-detail-icon.failed,
        .pipeline-detail-icon.interrupted { color:white; background:var(--radar-bad); }
        .pipeline-detail-icon.running {
          color:var(--radar-accent); background:var(--radar-accent-soft);
          animation:pipeline-turn 1.4s linear infinite;
        }
        .source-type {
          display:inline-block; color:#4b4bb8; background:var(--radar-accent-soft);
          border-radius:99px; padding:.14rem .46rem; font-size:.66rem;
          font-weight:700; margin-left:.35rem;
        }
        .source-test-status {
          display:inline-block; width:100%; text-align:center; border-radius:99px;
          padding:.2rem .45rem; font-size:.68rem; font-weight:720;
          color:#667085; background:#f0f2f5;
        }
        .source-test-status.success { color:var(--radar-good); background:#e5f6ef; }
        .source-test-status.failed { color:var(--radar-bad); background:#fdeaea; }
        .source-test-status.pending { color:#8a6116; background:#fff3dc; }
        [class*="st-key-source_details_"] {
          margin-bottom:.58rem;
        }
        [class*="st-key-source_details_"] div[data-testid="stExpander"] {
          border:1px solid var(--radar-line); border-radius:.92rem;
          background:rgba(255,255,255,.92);
          box-shadow:0 1px 2px rgba(23,32,51,.025);
          transition:border-color .18s ease, box-shadow .18s ease,
                     transform .18s ease;
        }
        [class*="st-key-source_details_"] div[data-testid="stExpander"]:hover {
          border-color:#d7daeb; box-shadow:0 6px 20px rgba(23,32,51,.055);
          transform:translateY(-1px);
        }
        [class*="st-key-source_details_"] summary {
          min-height:3.35rem; padding:.15rem .9rem;
          color:var(--radar-ink); font-size:.82rem; font-weight:670;
          letter-spacing:-.008em;
        }
        [class*="st-key-source_details_"] summary:hover {
          color:var(--radar-accent);
        }
        [class*="st-key-source_details_"] [data-testid="stExpanderDetails"] {
          padding:.1rem 1rem 1rem;
          border-top:1px solid #f0f1f5;
        }
        .source-detail-meta {
          display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
          gap:.6rem; margin:.8rem 0 .68rem;
        }
        .source-detail-meta > div {
          display:flex; flex-direction:column; gap:.18rem;
          min-width:0; padding:.62rem .7rem; border-radius:.68rem;
          background:var(--radar-soft);
        }
        .source-detail-meta span {
          color:#98a2b3; font-size:.65rem; font-weight:650;
        }
        .source-detail-meta strong {
          color:var(--radar-ink); font-size:.75rem; font-weight:680;
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .source-detail-meta strong.success { color:var(--radar-good); }
        .source-detail-meta strong.failed { color:var(--radar-bad); }
        .source-detail-meta strong.pending { color:#986710; }
        .source-detail-url {
          margin:.2rem 0 .35rem; color:var(--radar-muted); font-size:.72rem;
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .source-detail-url a {
          color:#596174; text-decoration:none;
        }
        .source-detail-url a:hover {
          color:var(--radar-accent); text-decoration:underline;
        }
        .source-detail-scope {
          width:max-content; max-width:100%; margin:0 0 .55rem;
          padding:.18rem .48rem; border-radius:99px;
          color:#596174; background:#eef0f5; font-size:.66rem;
          overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
        }
        .signal-group-intro {
          color:var(--radar-muted); background:var(--radar-soft);
          border-left:3px solid var(--radar-accent); border-radius:.45rem;
          padding:.68rem .8rem; font-size:.76rem; line-height:1.55;
          margin:.7rem 0 1rem;
        }
        .signal-topic-heading {
          display:flex; align-items:center; justify-content:space-between;
          color:var(--radar-ink); font-size:.86rem; font-weight:740;
          padding:.9rem .15rem .42rem; margin-top:.3rem;
          border-bottom:1px solid var(--radar-line);
        }
        .signal-topic-heading small {
          color:var(--radar-muted); font-size:.67rem; font-weight:650;
          background:var(--radar-soft); border-radius:99px; padding:.15rem .45rem;
        }
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
        [data-testid="stSidebar"] .stButton > button {
          color:#4444b2; background:var(--radar-accent-soft);
          border-color:#d9dcff; box-shadow:0 6px 18px rgba(91,91,214,.08);
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] { gap:.35rem; }
        [data-testid="stTabs"] button {
          border-radius:.65rem .65rem 0 0; font-weight:650;
        }
        @keyframes pipeline-pulse {
          0%, 100% { opacity:.45; transform:scale(.82); }
          50% { opacity:1; transform:scale(1.08); }
        }
        @keyframes pipeline-turn {
          from { transform:rotate(0deg); }
          to { transform:rotate(360deg); }
        }
        @media (prefers-reduced-motion: reduce) {
          .pipeline-running-dot,
          .pipeline-step.running .pipeline-step-dot,
          .pipeline-detail-icon.running { animation:none; }
        }
        @media (max-width: 800px) {
          [data-testid="stMainBlockContainer"] { padding:1.2rem .9rem 3rem; }
          h1 { font-size:1.7rem !important; }
          .pipeline-run-head { display:block; }
          .pipeline-run-meta { margin-top:.3rem; }
          .pipeline-step { flex-basis:5.7rem; }
          .setup-hero { padding:1.2rem; }
          .setup-hero-title { font-size:1.35rem; }
          .setup-step-label { display:none; }
          .setup-step-line { margin:0 .35rem; }
          .setup-review-row { grid-template-columns:6rem 1fr 1rem; }
          .source-detail-meta { grid-template-columns:1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
