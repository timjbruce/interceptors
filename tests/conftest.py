"""Live-stack fixture for the end-to-end tests.

These tests exercise the real system over HTTP, so they need the whole stack
running: a local Temporal dev server, the JWT-authorized backend (:9000), the
worker (with its interceptors), and the web client (:8000).

The `stack` fixture reuses an already-running stack if it finds one; otherwise it
starts everything as subprocesses and tears them down at the end of the session.
If the `temporal` CLI is missing, or ports 8000/9000 are occupied by something
that is not our app, the e2e tests are skipped rather than failed.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
WEB = "http://localhost:8000"
BACKEND = "http://localhost:9000"


def _http_ok(url: str) -> bool:
    try:
        return httpx.get(url, timeout=1.5).status_code < 500
    except Exception:
        return False


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait(pred, timeout: float, what: str) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.5)
    raise RuntimeError(f"timed out after {timeout}s waiting for {what}")


def _spawn(*cmd) -> subprocess.Popen:
    return subprocess.Popen(
        cmd, cwd=REPO, env=os.environ.copy(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _worker_polling() -> bool:
    # The worker is ready once it registers as a poller on the task queue.
    r = subprocess.run(
        ["temporal", "task-queue", "describe", "--task-queue", "interceptor-samples", "-o", "json"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and '"identity"' in r.stdout


@pytest.fixture(scope="session")
def stack():
    # Reuse a stack that is already up (e.g. the dev is running the demo).
    if _http_ok(WEB + "/api/identities") and _http_ok(BACKEND + "/health"):
        yield
        return

    if shutil.which("temporal") is None:
        pytest.skip("temporal CLI not installed; e2e tests need the live stack")
    if _port_open(8000) or _port_open(9000):
        pytest.skip("ports 8000/9000 are busy but not our app; free them or run the stack yourself")

    procs: list[subprocess.Popen] = []
    try:
        if not _port_open(7233):
            procs.append(_spawn("temporal", "server", "start-dev", "--log-level", "error"))
            _wait(
                lambda: subprocess.run(
                    ["temporal", "operator", "cluster", "health"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                ).returncode == 0,
                40, "temporal server",
            )

        py = sys.executable
        procs.append(_spawn(py, "-m", "uvicorn", "backend.service:app", "--port", "9000"))
        procs.append(_spawn(py, "-m", "workflows.worker"))
        procs.append(_spawn(py, "-m", "uvicorn", "web.app:app", "--port", "8000"))

        _wait(lambda: _http_ok(BACKEND + "/health"), 40, "backend service")
        _wait(lambda: _http_ok(WEB + "/api/identities"), 40, "web client")
        _wait(_worker_polling, 40, "worker to start polling")
        yield
    finally:
        for p in reversed(procs):
            p.terminate()
        for p in reversed(procs):
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
