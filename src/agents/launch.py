"""Start the evaluation agent as its own process.

The web request does not evaluate. It only launches `python -m src.agents`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PID_FILE = PROJECT_ROOT / "data" / "evaluation.pid"


def evaluation_running(pid_file: Path = PID_FILE) -> bool:
    pid = _read_pid(pid_file)
    if pid is None:
        return False
    if _alive(pid):
        return True
    _clear(pid_file)
    return False


def start_evaluation(
    job_id: str | None = None,
    *,
    pid_file: Path = PID_FILE,
    popen=subprocess.Popen,
) -> tuple[bool, str]:
    """Launch one agent process. Refuse when a previous launch is still alive."""
    if evaluation_running(pid_file):
        return False, "An evaluation is already running."
    command = [sys.executable, "-m", "src.agents"]
    if job_id:
        command.extend(["--job-id", job_id])
    kwargs: dict = {"cwd": str(PROJECT_ROOT), "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    process = popen(command, **kwargs)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(process.pid), encoding="utf-8")
    if job_id:
        return True, "Evaluation started for this job. It runs in its own window."
    return True, "Evaluation started for every application that has no assessment yet. It runs in its own window."


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _clear(pid_file: Path) -> None:
    try:
        pid_file.unlink()
    except OSError:
        return


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
