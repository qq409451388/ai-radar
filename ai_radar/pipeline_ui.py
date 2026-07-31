"""Reusable consumer-facing controls for manual pipeline runs."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

import streamlit as st

from ai_radar.pipeline_runner import (
    ACTIVE_STATUSES,
    PIPELINES,
    enqueue_pipeline,
    get_active_pipeline_snapshot,
    get_pipeline_snapshot,
)
from ai_radar.ui import fmt_dt


STATUS_LABELS = {
    "QUEUED": "准备中",
    "RUNNING": "进行中",
    "SUCCESS": "已完成",
    "PARTIAL": "部分完成",
    "FAILED": "运行失败",
    "INTERRUPTED": "已中断",
    "SKIPPED": "已跳过",
    "PENDING": "等待中",
}


def render_pipeline_launcher() -> None:
    st.markdown(
        '<div class="update-center-intro">'
        "<strong>现在更新 AI Radar</strong>"
        "<span>选择范围后任务会在后台运行，关闭这个窗口不会中断。</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    labels = [definition.label for definition in PIPELINES.values()]
    selected_label = st.segmented_control(
        "更新范围",
        labels,
        default=labels[0],
        key="update_center_pipeline_type",
        label_visibility="collapsed",
    ) or labels[0]
    selected = next(
        definition
        for definition in PIPELINES.values()
        if definition.label == selected_label
    )
    st.caption(selected.description)

    active = get_active_pipeline_snapshot()
    if st.button(
        f"开始{selected.label}",
        type="primary",
        width="stretch",
        disabled=active is not None,
        key="update_center_start",
    ):
        run_id, created = enqueue_pipeline(selected.key)
        if created:
            st.toast(f"{selected.label}已开始", icon="🚀")
        else:
            st.toast(f"更新 #{run_id} 已在进行中", icon="⏳")
        st.rerun()
    if active:
        st.caption("当前已有更新任务运行中，完成后才能再次启动。")


@st.fragment(run_every=1.0)
def render_pipeline_progress(*, show_empty: bool = True) -> None:
    snapshot = get_pipeline_snapshot()
    if snapshot is None:
        if show_empty:
            st.info("还没有运行记录。选择更新范围后即可开始。")
        return

    status = snapshot["status"]
    active = status in ACTIVE_STATUSES
    status_class = {
        "SUCCESS": "success",
        "PARTIAL": "partial",
        "FAILED": "failed",
        "INTERRUPTED": "failed",
        "RUNNING": "running",
        "QUEUED": "running",
    }.get(status, "")
    current_step = next(
        (
            step
            for step in snapshot["steps"]
            if step["key"] == snapshot["current_step"]
        ),
        None,
    )
    elapsed_end = datetime.now(timezone.utc) if active else snapshot["finished_at"]
    elapsed = _duration(snapshot["started_at"], elapsed_end)
    running_dot = (
        '<span class="pipeline-running-dot" aria-hidden="true"></span>'
        if active
        else ""
    )
    # Keep this as a single unindented HTML string. Indented multiline markup
    # can be interpreted as a Markdown code block during fragment refreshes,
    # which exposes the literal <span> tags to the user.
    run_head_html = (
        '<div class="pipeline-run-head"><div>'
        f"{running_dot}"
        f'<span class="pipeline-run-title">'
        f"{escape(snapshot['pipeline_label'])}</span>"
        f'<span class="pipeline-status {status_class}">'
        f"{escape(STATUS_LABELS.get(status, status))}</span>"
        "</div>"
        f'<div class="pipeline-run-meta">#{snapshot["id"]} · '
        f"{escape(fmt_dt(snapshot['started_at']))} · {escape(elapsed)}</div>"
        "</div>"
    )
    st.markdown(run_head_html, unsafe_allow_html=True)
    progress = min(1.0, max(0.0, snapshot["progress"]))
    st.progress(
        progress,
        text=(
            f"{int(progress * 100)}% · "
            f"{current_step['label'] if current_step else STATUS_LABELS.get(status, status)}"
        ),
    )
    _render_stepper(snapshot["steps"])

    live = snapshot.get("live", {})
    message = live.get("message") or (
        current_step["message"] if current_step else ""
    )
    if active:
        current = live.get("current", 0)
        total = live.get("total", 0)
        detail = f" · {current}/{total}" if total else ""
        st.caption(f"{message or '正在处理'}{detail} · 进度会自动刷新")
    elif status == "SUCCESS":
        analyze_result = snapshot["result"].get("analyze_all", {})
        if analyze_result:
            st.success(
                "完整更新已完成：处理 "
                f"{analyze_result.get('processed', 0)} 条，"
                f"剩余待分析 {analyze_result.get('remaining_pending', 0)} 条。"
            )
        else:
            st.success("本次更新已完成。")
    elif status == "PARTIAL":
        st.warning("更新已完成，但有少量项目失败。可在步骤中查看。")
    elif status in ("FAILED", "INTERRUPTED"):
        st.error(snapshot["error"] or message or "更新未完成。")

    with st.expander("每一步都在做什么", expanded=True):
        _render_step_details(snapshot)


def _render_step_details(snapshot: dict) -> None:
    definition = PIPELINES.get(snapshot["pipeline_type"])
    descriptions = (
        {step.key: step.description for step in definition.steps}
        if definition
        else {}
    )
    for step in snapshot["steps"]:
        status = step["status"]
        progress = min(1.0, max(0.0, step["progress"]))
        icon = {
            "SUCCESS": "✓",
            "PARTIAL": "!",
            "RUNNING": "↻",
            "FAILED": "×",
            "INTERRUPTED": "■",
            "SKIPPED": "–",
            "PENDING": "·",
        }.get(status, "·")
        with st.container(border=True):
            heading, timing = st.columns([4, 1])
            heading.markdown(
                f'<div class="pipeline-detail-title">'
                f'<span class="pipeline-detail-icon {status.lower()}">{escape(icon)}</span>'
                f"<span><strong>{escape(step['label'])}</strong>"
                f"<small>{escape(descriptions.get(step['key'], ''))}</small></span>"
                "</div>",
                unsafe_allow_html=True,
            )
            timing.caption(
                STATUS_LABELS.get(status, status)
                + " · "
                + _duration(step["started_at"], step["finished_at"])
            )
            text = step["message"] or (
                "等待前一步完成" if status == "PENDING" else STATUS_LABELS.get(status, status)
            )
            counts = []
            if step["processed"]:
                counts.append(f"处理 {step['processed']}")
            if step["failed"]:
                counts.append(f"失败 {step['failed']}")
            if counts:
                text = f"{text} · {' / '.join(counts)}"
            st.progress(progress, text=text)


def _render_stepper(steps: list[dict]) -> None:
    icon_by_status = {
        "SUCCESS": "✓",
        "PARTIAL": "!",
        "RUNNING": "↻",
        "FAILED": "×",
        "INTERRUPTED": "■",
        "SKIPPED": "–",
    }
    parts: list[str] = ['<div class="pipeline-stepper">']
    for index, step in enumerate(steps, start=1):
        if index > 1:
            previous = steps[index - 2]["status"]
            connector_class = "done" if previous in ("SUCCESS", "PARTIAL") else ""
            parts.append(f'<div class="pipeline-connector {connector_class}"></div>')
        status = step["status"].lower()
        icon = (
            str(index)
            if step["status"] == "PENDING"
            else icon_by_status.get(step["status"], str(index))
        )
        parts.append(
            f'<div class="pipeline-step {escape(status)}">'
            f'<div class="pipeline-step-dot">{escape(icon)}</div>'
            f'<div class="pipeline-step-label">{escape(step["label"])}</div>'
            "</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "刚刚"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    seconds = max(0, int((end - start).total_seconds()))
    if seconds >= 60:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds} 秒"
