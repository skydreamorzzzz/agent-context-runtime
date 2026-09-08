"""Task-specific Linux isolation for executing the submitted add implementation."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_OUTPUT_LIMIT = 64 * 1024
_READY = b"ACR_SANDBOX_READY\n"


class IsolationUnavailable(RuntimeError):
    """Raised when the required Linux namespace boundary cannot be started."""


@dataclass(frozen=True)
class IsolatedExecution:
    """Bounded evidence returned by one isolated submission process."""

    status: str
    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool


def _sandbox_command(workspace: Path, script: str) -> list[str]:
    """Build the fixed Linux namespace boundary with a read-only workspace."""

    required = (
        Path("/usr/bin/unshare"),
        Path("/usr/bin/bwrap"),
        Path("/usr/bin/python3.12"),
        Path("/usr/lib"),
        Path("/lib"),
        Path("/lib64"),
    )
    if any(not path.exists() for path in required):
        raise IsolationUnavailable("linux namespace execution capability is unavailable")
    return [
        "/usr/bin/unshare",
        "--user",
        "--map-root-user",
        "--mount",
        "--pid",
        "--fork",
        "--net",
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--share-net",
        "--dir",
        "/usr",
        "--dir",
        "/usr/bin",
        "--ro-bind",
        "/usr/bin/python3.12",
        "/usr/bin/python3.12",
        "--ro-bind",
        "/usr/lib",
        "/usr/lib",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--ro-bind",
        str(workspace),
        "/workspace",
        "--chdir",
        "/workspace",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--cap-drop",
        "ALL",
        "/usr/bin/python3.12",
        "-I",
        "-B",
        "-c",
        f'import os; os.write(2, {_READY!r})\n{script}',
    ]


def _append_bounded(target: bytearray, chunk: bytes, limit: int) -> bool:
    remaining = max(limit - len(target), 0)
    target.extend(chunk[:remaining])
    return len(chunk) > remaining


def run_isolated_python(
    workspace: Path,
    script: str,
    *,
    stdin: bytes = b"",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> IsolatedExecution:
    """Run Python with no host environment, host paths, or network namespace.

    Pipes are continuously drained while only ``output_limit`` bytes per stream
    are retained.  A timeout kills the complete namespace launcher process group.
    """

    resolved = workspace.resolve(strict=True)
    if not resolved.is_dir() or timeout_seconds <= 0 or output_limit <= 0:
        raise ValueError("isolated execution arguments are invalid")
    command = _sandbox_command(resolved, script)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={},
            start_new_session=True,
        )
    except OSError as error:
        raise IsolationUnavailable("linux namespace execution could not start") from error
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    try:
        process.stdin.write(stdin)
        process.stdin.close()
    except BrokenPipeError:
        pass

    selector = selectors.DefaultSelector()
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    truncated = {process.stdout: False, process.stderr: False}
    for stream in streams:
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    cleanup_deadline: float | None = None
    timed_out = False
    while process.poll() is None or selector.get_map():
        now = time.monotonic()
        if now >= deadline and not timed_out:
            timed_out = True
            cleanup_deadline = now + 0.5
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if cleanup_deadline is not None and now >= cleanup_deadline:
            for key in list(selector.get_map().values()):
                selector.unregister(key.fileobj)
                key.fileobj.close()
            break
        active_deadline = cleanup_deadline if cleanup_deadline is not None else deadline
        wait_seconds = max(min(active_deadline - now, 0.05), 0)
        ready = selector.select(wait_seconds) if selector.get_map() else ()
        if not selector.get_map() and wait_seconds:
            time.sleep(wait_seconds)
        for key, _ in ready:
            stream = key.fileobj
            try:
                chunk = os.read(stream.fileno(), 8192)
            except BlockingIOError:
                continue
            if not chunk:
                selector.unregister(stream)
                stream.close()
                continue
            truncated[stream] |= _append_bounded(streams[stream], chunk, output_limit)
    returncode = process.poll()
    if returncode is None:
        try:
            returncode = process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                returncode = process.wait(timeout=0.2)
            except subprocess.TimeoutExpired as error:
                raise IsolationUnavailable(
                    "isolated execution could not be terminated"
                ) from error
    stderr = bytes(streams[process.stderr])
    if not stderr.startswith(_READY):
        raise IsolationUnavailable("linux namespace execution boundary failed")
    stderr = stderr.removeprefix(_READY)
    return IsolatedExecution(
        status="timeout" if timed_out else "completed",
        returncode=returncode,
        stdout=bytes(streams[process.stdout]),
        stderr=stderr,
        stdout_truncated=truncated[process.stdout],
        stderr_truncated=truncated[process.stderr],
    )
