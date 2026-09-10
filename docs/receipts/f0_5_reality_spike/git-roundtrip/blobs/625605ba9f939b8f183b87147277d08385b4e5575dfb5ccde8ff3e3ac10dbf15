from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

RUN_ID = uuid.uuid4().hex


def write_marker(phase: str, exit_status: int | None = None) -> None:
    marker_root = os.environ.get("ACR_F05_VERIFIER_MARKER_DIR")
    if marker_root is None:
        return
    root = Path(marker_root)
    root.mkdir(parents=True, exist_ok=True)
    wall_time_ns = time.time_ns()
    marker = root / f"{wall_time_ns}-{phase}-{RUN_ID}.json"
    payload = {
        "exit_status": exit_status,
        "monotonic_ns": time.monotonic_ns(),
        "phase": phase,
        "pid": os.getpid(),
        "run_id": RUN_ID,
        "verifier": "pytest -q",
        "wall_time_ns": wall_time_ns,
    }
    marker.write_text(json.dumps(payload, sort_keys=True) + "\n")
    marker.chmod(0o444)


def pytest_sessionstart() -> None:
    write_marker("start")


def pytest_sessionfinish(exitstatus: int) -> None:
    write_marker("finish", exitstatus)
