from __future__ import annotations

from pathlib import Path

import pytest

from ai_radar import launcher


def test_recognizes_new_absolute_ai_radar_command(monkeypatch):
    command = (
        f'python -m streamlit run "{launcher.APP_PATH}" '
        "--server.headless true --server.port 8501"
    )
    monkeypatch.setattr(launcher, "_process_command", lambda _pid: command)

    assert launcher._is_ai_radar_process(1234) is True


def test_legacy_relative_command_must_have_project_cwd(monkeypatch):
    monkeypatch.setattr(
        launcher,
        "_process_command",
        lambda _pid: "python -m streamlit run app.py --server.headless true",
    )
    monkeypatch.setattr(
        launcher,
        "_process_cwd",
        lambda _pid: launcher.PROJECT_ROOT,
    )
    assert launcher._is_ai_radar_process(1234) is True

    monkeypatch.setattr(
        launcher,
        "_process_cwd",
        lambda _pid: Path("/tmp/a-different-project"),
    )
    assert launcher._is_ai_radar_process(1234) is False


def test_stops_only_recognized_previous_instance(monkeypatch):
    stopped: list[int] = []
    monkeypatch.setattr(launcher, "_read_pid_file", lambda: 111)
    monkeypatch.setattr(launcher, "_listener_pids", lambda _port: {111, 222})
    monkeypatch.setattr(launcher, "_pid_exists", lambda _pid: True)
    monkeypatch.setattr(
        launcher,
        "_is_ai_radar_process",
        lambda pid: pid == 111,
    )
    monkeypatch.setattr(launcher, "_terminate_process", stopped.append)
    monkeypatch.setattr(
        launcher,
        "_wait_until_stopped",
        lambda _pid, timeout: True,
    )

    launcher._stop_previous_instance()

    assert stopped == [111]


def test_refuses_to_change_port_when_another_program_uses_8501(monkeypatch):
    monkeypatch.setattr(launcher, "_port_is_open", lambda _port: True)
    monkeypatch.setattr(launcher, "_listener_pids", lambda _port: {999})

    with pytest.raises(RuntimeError, match="will not silently start"):
        launcher._ensure_port_available()
