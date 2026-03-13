from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from agent.cancellation import OperationCancelledError, raise_if_cancelled


def _truncate(value: str, limit: int = 20000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def run_command(repo_root: Path, argv: list[str], timeout_seconds: int, cancel_event: Event | None = None) -> str:
    raise_if_cancelled(cancel_event)
    process = subprocess.Popen(
        argv,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = monotonic()
    stdout = ""
    stderr = ""

    while True:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            raise OperationCancelledError("Cancelled by user.")

        if monotonic() - started > timeout_seconds:
            process.kill()
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(argv, timeout_seconds, output=stdout, stderr=stderr)

        return_code = process.poll()
        if return_code is not None:
            stdout, stderr = process.communicate()
            break
        sleep(0.1)

    combined = (
        f"Exit code: {process.returncode}\n"
        f"STDOUT:\n{stdout.strip() or '(empty)'}\n\n"
        f"STDERR:\n{stderr.strip() or '(empty)'}"
    )
    return _truncate(combined)


def detect_test_command(repo_root: Path) -> list[str]:
    if (repo_root / "pytest.ini").exists() or (repo_root / "pyproject.toml").exists() or (repo_root / "tests").exists():
        return ["python", "-m", "pytest"]
    if (repo_root / "package.json").exists():
        return ["npm", "test"]
    if (repo_root / "Cargo.toml").exists():
        return ["cargo", "test"]
    if (repo_root / "go.mod").exists():
        return ["go", "test", "./..."]
    if any(repo_root.glob("*.sln")):
        return ["dotnet", "test"]
    raise RuntimeError("Could not detect a supported test command for this repository.")


def run_tests(repo_root: Path, timeout_seconds: int, cancel_event: Event | None = None) -> str:
    return run_command(repo_root, detect_test_command(repo_root), timeout_seconds, cancel_event=cancel_event)
