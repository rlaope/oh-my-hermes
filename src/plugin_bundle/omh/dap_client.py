"""Stdio Debug Adapter Protocol client for the opt-in `debug_python` tool (toolset `omh-dap`).

Spawns ``<interpreter> -m debugpy.adapter`` with ``shell=False`` and speaks DAP over its
stdin/stdout (``Content-Length`` framing both ways). One reader thread parses messages onto
a queue; the caller's thread drains that queue, matching responses by ``request_seq`` and
buffering the events it waits for, so a ``stopped`` that arrives before anyone waits is
kept. Reverse requests (``runInTerminal``, ``startDebugging``) are answered with an error
response instead of being left to hang the adapter. A second thread drains stderr into a
small ring so a dying adapter can say why.

No socket, no asyncio: debugpy's own socket use happens inside the child processes. This
is the only `omh-dap` module that imports `subprocess`; it is reached only from an explicit
`debug_python` tool call.
"""

from __future__ import annotations

import itertools
import json
import queue
import subprocess
import threading
import time
from collections import deque
from typing import Any, Sequence

REQUEST_TIMEOUT = 30.0
CLOSE_WAIT = 2.0
_STDERR_RING = 8192
# Events a caller waits for; anything else (thread, module, process, ...) is dropped.
_KEPT_EVENTS = frozenset({"initialized", "stopped", "continued", "exited", "terminated"})
_EOF = object()


class DapError(Exception):
    """A classified failure: ``code`` is `timeout`, `adapter_error`, `adapter_exited` or `adapter_unavailable`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def encode(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def read_message(stream: Any) -> dict[str, Any] | None:
    """One framed message from a binary stream; None at EOF."""
    length = None
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            if length is None:
                continue  # stray blank line before a header
            break
        name, _, value = line.decode("ascii", "replace").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            return None
        body += chunk
    return json.loads(body.decode("utf-8"))


class DapClient:
    """A running debug adapter. Construct with the argv to spawn; ``close()`` is idempotent."""

    def __init__(self, argv: Sequence[str], cwd: str, env: dict[str, str],
                 request_timeout: float = REQUEST_TIMEOUT) -> None:
        self.request_timeout = request_timeout
        try:
            self._proc = subprocess.Popen(
                list(argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=cwd, env=env, shell=False,
            )
        except OSError as exc:
            raise DapError("adapter_unavailable", f"cannot start {argv[0]}: {exc}") from None
        self._seq = itertools.count(1)
        self._write_lock = threading.Lock()
        self._inbox: queue.Queue[Any] = queue.Queue()
        self._responses: dict[int, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._output: list[str] = []
        self._stderr: deque[bytes] = deque()
        self._stderr_size = 0
        self._eof = False
        self._closed = False
        threading.Thread(target=self._read_stdout, name="omh-dap-reader", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="omh-dap-stderr", daemon=True).start()

    # ---- threads -----------------------------------------------------------

    def _read_stdout(self) -> None:
        stream = self._proc.stdout
        while True:
            try:
                message = read_message(stream)
            except (OSError, ValueError):
                message = None
            if message is None:
                self._inbox.put(_EOF)
                return
            if message.get("type") == "request":
                self._refuse_reverse_request(message)
                continue
            self._inbox.put(message)

    def _refuse_reverse_request(self, message: dict[str, Any]) -> None:
        reply = {
            "type": "response", "request_seq": message.get("seq"), "command": message.get("command"),
            "success": False, "message": "not supported by omh debug_python",
        }
        try:
            self._write(reply)
        except (OSError, ValueError):
            pass  # adapter already gone; the reader sees EOF next

    def _read_stderr(self) -> None:
        stream = self._proc.stderr
        while True:
            try:
                chunk = stream.read1(4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            self._stderr.append(chunk)
            self._stderr_size += len(chunk)
            while self._stderr_size > _STDERR_RING and len(self._stderr) > 1:
                self._stderr_size -= len(self._stderr.popleft())

    # ---- io ----------------------------------------------------------------

    def _write(self, message: dict[str, Any]) -> None:
        with self._write_lock:
            message["seq"] = next(self._seq)
            self._proc.stdin.write(encode(message))
            self._proc.stdin.flush()

    def send(self, command: str, arguments: dict[str, Any] | None = None) -> int:
        message: dict[str, Any] = {"type": "request", "command": command}
        if arguments is not None:
            message["arguments"] = arguments
        try:
            self._write(message)
        except (OSError, ValueError) as exc:
            raise DapError("adapter_exited", f"cannot write to the adapter: {exc}") from None
        return int(message["seq"])

    def _sort(self, message: Any) -> None:
        if message is _EOF:
            self._eof = True
            return
        kind = message.get("type")
        if kind == "response":
            self._responses[int(message.get("request_seq", -1))] = message
        elif kind == "event":
            name = message.get("event")
            if name == "output":
                body = message.get("body") or {}
                if body.get("category") != "telemetry":
                    self._output.append(str(body.get("output", "")))
            elif name in _KEPT_EVENTS:
                self._events.append(message)

    def _pump(self, deadline: float, what: str) -> None:
        if self._eof:
            raise DapError("adapter_exited", f"the adapter exited while waiting for {what}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DapError("timeout", f"no {what} within the time limit")
        try:
            self._sort(self._inbox.get(timeout=remaining))
        except queue.Empty:
            raise DapError("timeout", f"no {what} within the time limit") from None

    def _drain_nowait(self) -> None:
        while True:
            try:
                self._sort(self._inbox.get_nowait())
            except queue.Empty:
                return

    def wait_response(self, seq: int, timeout: float | None = None) -> dict[str, Any]:
        """The body of the response to ``seq``; ``adapter_error`` when the adapter refused it."""
        deadline = time.monotonic() + (self.request_timeout if timeout is None else timeout)
        while seq not in self._responses:
            self._pump(deadline, f"response to request {seq}")
        message = self._responses.pop(seq)
        if not message.get("success", False):
            body = message.get("body") or {}
            detail = (body.get("error") or {}).get("format") or message.get("message") or "request failed"
            raise DapError("adapter_error", str(detail))
        return message.get("body") or {}

    def request(self, command: str, arguments: dict[str, Any] | None = None,
                timeout: float | None = None) -> dict[str, Any]:
        return self.wait_response(self.send(command, arguments), timeout)

    def wait_event(self, names: Sequence[str], timeout: float) -> dict[str, Any]:
        """Pop the first buffered event named in ``names``, waiting up to ``timeout`` s."""
        deadline = time.monotonic() + timeout
        wanted = set(names)
        while True:
            for index, event in enumerate(self._events):
                if event.get("event") in wanted:
                    return self._events.pop(index)
            self._pump(deadline, "/".join(sorted(wanted)) + " event")

    def discard_events(self, names: Sequence[str]) -> None:
        self._drain_nowait()
        self._events = [e for e in self._events if e.get("event") not in set(names)]

    def drain_output(self) -> str:
        """Program output received since the last drain."""
        self._drain_nowait()
        text, self._output = "".join(self._output), []
        return text

    def alive(self) -> bool:
        return self._proc.poll() is None

    def stderr_tail(self, limit: int = 2000) -> str:
        return b"".join(self._stderr).decode("utf-8", "replace")[-limit:]

    def close(self) -> None:
        """Disconnect (terminating the debuggee) if alive, wait ``CLOSE_WAIT`` s, then kill."""
        if self._closed:
            return
        self._closed = True
        if self.alive() and not self._eof:
            try:
                self.wait_response(self.send("disconnect", {"terminateDebuggee": True}), CLOSE_WAIT)
            except DapError:
                pass  # closing anyway; the kill below is the bound
        try:
            self._proc.wait(CLOSE_WAIT)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            try:
                self._proc.wait(CLOSE_WAIT)
            except subprocess.TimeoutExpired:
                pass  # unkillable child: nothing more this process can do
        for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass


__all__ = ["CLOSE_WAIT", "REQUEST_TIMEOUT", "DapClient", "DapError", "encode", "read_message"]
