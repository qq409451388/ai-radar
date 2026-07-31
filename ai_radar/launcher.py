"""Start exactly one AI Radar Streamlit process on the fixed local port."""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = PROJECT_ROOT / "app.py"
PID_FILE = PROJECT_ROOT / ".ai-radar.pid"
HOST = "localhost"
PORT = 8501


def main() -> int:
    _stop_previous_instance()
    _ensure_port_available()

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.headless",
        "true",
        "--server.port",
        str(PORT),
    ]
    print(f">>> Starting AI Radar at http://{HOST}:{PORT}", flush=True)
    child = subprocess.Popen(command, cwd=PROJECT_ROOT)
    PID_FILE.write_text(str(child.pid), encoding="utf-8")

    def forward_signal(signum, _frame) -> None:  # type: ignore[no-untyped-def]
        if child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGINT, forward_signal)
    signal.signal(signal.SIGTERM, forward_signal)
    try:
        return child.wait()
    finally:
        _remove_pid_file(child.pid)


def _stop_previous_instance() -> None:
    candidates: set[int] = set()
    saved_pid = _read_pid_file()
    if saved_pid:
        candidates.add(saved_pid)
    candidates.update(_listener_pids(PORT))

    for pid in candidates:
        if pid == os.getpid() or not _pid_exists(pid):
            continue
        if not _is_ai_radar_process(pid):
            continue
        print(f">>> Stopping previous AI Radar process ({pid})", flush=True)
        _terminate_process(pid)
        if not _wait_until_stopped(pid, timeout=8.0):
            raise RuntimeError(
                f"previous AI Radar process {pid} did not stop; "
                "stop it manually and run the launcher again"
            )
    if saved_pid and not _pid_exists(saved_pid):
        _remove_pid_file(saved_pid)


def _ensure_port_available() -> None:
    if not _port_is_open(PORT):
        return
    pids = sorted(_listener_pids(PORT))
    owner = f" (PID {', '.join(map(str, pids))})" if pids else ""
    raise RuntimeError(
        f"port {PORT} is already used by another program{owner}. "
        f"AI Radar will not silently start on a different port."
    )


def _read_pid_file() -> int | None:
    try:
        value = PID_FILE.read_text(encoding="utf-8").strip()
        return int(value) if value else None
    except (FileNotFoundError, OSError, ValueError):
        return None


def _remove_pid_file(expected_pid: int) -> None:
    try:
        if _read_pid_file() == expected_pid:
            PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _is_ai_radar_process(pid: int) -> bool:
    command = _process_command(pid)
    normalized = command.replace("\\", "/").lower()
    absolute_app = str(APP_PATH).replace("\\", "/").lower()
    if (
        "streamlit" in normalized
        and "run" in normalized
        and absolute_app in normalized
    ):
        return True

    # Compatibility with versions launched before the absolute app path and
    # PID file were introduced.
    if "streamlit" not in normalized or "run app.py" not in normalized:
        return False
    cwd = _process_cwd(pid)
    return cwd is not None and cwd.resolve() == PROJECT_ROOT.resolve()


def _process_command(pid: int) -> str:
    if os.name == "nt":
        script = (
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    return result.stdout.strip()


def _process_cwd(pid: int) -> Path | None:
    proc_cwd = Path(f"/proc/{pid}/cwd")
    if proc_cwd.exists():
        try:
            return proc_cwd.resolve()
        except OSError:
            return None
    if shutil.which("lsof"):
        result = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            if line.startswith("n"):
                return Path(line[1:])
    return None


def _listener_pids(port: int) -> set[int]:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            columns = line.split()
            if (
                len(columns) >= 5
                and columns[1].endswith(f":{port}")
                and columns[3].upper() == "LISTENING"
                and columns[4].isdigit()
            ):
                pids.add(int(columns[4]))
        return pids

    if shutil.which("lsof"):
        result = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            int(line)
            for line in result.stdout.splitlines()
            if line.strip().isdigit()
        }
    if shutil.which("fuser"):
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            int(value)
            for value in result.stdout.split()
            if value.isdigit()
        }
    return set()


def _terminate_process(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        os.kill(pid, signal.SIGTERM)


def _wait_until_stopped(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(0.1)
    return not _pid_exists(pid)


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    raise SystemExit(main())
