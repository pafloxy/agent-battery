"""OS paths and bounded subprocess transport, independent of any provider or UI.

Example: python3 -m agent_battery --demo
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Any

MAX_FRAME = 2 * 1024 * 1024


def cache_root(env: dict[str, str], platform: str | None = None) -> Path:
    """Choose the OS cache root. Example: cache_root({}, 'darwin')."""
    platform = sys.platform if platform is None else platform
    if env.get("XDG_CACHE_HOME"):
        return Path(env["XDG_CACHE_HOME"]).expanduser()
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    if platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path.home() / ".cache"


class ProcessError(Exception):
    """Sanitized transport failure. Example: raise ProcessError('Provider exited.')."""


class JsonLineProcess:
    """Bounded JSON-line transport using a reader thread on Unix and Windows.

    Example: client = JsonLineProcess(['codex', 'app-server'], dict(os.environ), '.')
    Always call client.close() in a finally block.
    """

    def __init__(self, argv: list[str], env: dict[str, str], cwd: str, timeout: float = 25):
        """Launch one process. Example: JsonLineProcess(['tool'], {}, '.', 5)."""
        self.deadline = time.monotonic() + timeout
        self.frames: queue.Queue[bytes | None | ProcessError] = queue.Queue(maxsize=16)
        self.stopped = threading.Event()
        try:
            self.process = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env, cwd=cwd,
                start_new_session=os.name == "posix", bufsize=0,
            )
        except OSError as exc:
            raise ProcessError("Cannot launch provider executable. Check its configured path.") from exc
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _enqueue(self, value: bytes | None | ProcessError) -> None:
        """Bound queued output during shutdown. Example: self._enqueue(None)."""
        while not self.stopped.is_set():
            try:
                self.frames.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read(self) -> None:
        """Read bounded frames without Unix-only selectors. Example: self._read()."""
        try:
            assert self.process.stdout is not None
            buffer = bytearray()
            while not self.stopped.is_set():
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    self._enqueue(None)
                    return
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, buffer = buffer.partition(b"\n")
                    if len(line) > MAX_FRAME:
                        self._enqueue(ProcessError("Provider returned an unexpectedly large response."))
                        return
                    self._enqueue(bytes(line))
                if len(buffer) > MAX_FRAME:
                    self._enqueue(ProcessError("Provider returned an unexpectedly large response."))
                    return
        except (OSError, ValueError):
            self._enqueue(None)

    def send(self, message: dict[str, Any]) -> None:
        """Send one JSON object. Example: client.send({'method': 'initialized'})."""
        try:
            assert self.process.stdin is not None
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ProcessError("Provider process stopped before accepting a request.") from exc

    def receive(self) -> dict[str, Any]:
        """Read an object within the overall deadline. Example: reply = client.receive()."""
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessError("Quota refresh timed out. Check provider login and connection.")
            try:
                frame = self.frames.get(timeout=remaining)
            except queue.Empty as exc:
                raise ProcessError("Quota refresh timed out. Check provider login and connection.") from exc
            if frame is None:
                raise ProcessError("Provider exited before replying. Check its version and configuration.")
            if isinstance(frame, ProcessError):
                raise frame
            try:
                value = json.loads(frame)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(value, dict):
                return value

    def close(self) -> None:
        """Stop the child and release pipes. Example: client.close()."""
        self.stopped.set()
        if self.process.stdin:
            with contextlib.suppress(OSError):
                self.process.stdin.close()
        with contextlib.suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(self.process.pid, signal.SIGTERM)
            elif self.process.poll() is None:
                self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
            self.process.wait(timeout=1)
        self.reader.join(timeout=1)
        if self.process.stdout:
            self.process.stdout.close()
