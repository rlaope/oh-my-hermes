"""The OMH TUI's child process, one at a time: Hermes' gateway, spoken to over stdio JSON-RPC.

`gateway_spawn` turns the environment Hermes' launcher handed the frontend into
the child's argv, working directory and environment. It never picks an
interpreter: the child runs on exactly `HERMES_PYTHON` with the launcher's own
import path, because another Python cannot load Hermes' compiled dependencies.
The child is `attach/gateway_attach.py`, which reaches the profile's shared
gateway as Hermes' own Ink TUI does where this Hermes can, and runs Hermes'
stdio entry where it cannot; this client sees the stdio entry's protocol from
either.

`GatewayClient` owns the child. A reader thread turns each stdout line into an
inbound item; a second thread drains stderr into a bounded in-memory tail, since
a full pipe would block the gateway mid-write. Inbound items wait in memory
until `poll` takes them, except the answer to a blocking `call`, which goes
straight to its caller. `wake_fd` is a pipe that is readable while an item
waits for `poll`, so the TUI's loop can select on it next to its input and
sleep until either has something. Nothing here writes a frame to disk or to a
log.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import IO, Any

from . import gateway_contract as contract

# The child, run by path on Hermes' interpreter: it attaches to the profile's shared gateway where this Hermes
# has that, else it runs Hermes' stdio entry (`tui_gateway.entry`) in its own process. Either way it speaks the
# stdio entry's protocol to this client. Never imported here: it imports Hermes, and this interpreter cannot.
GATEWAY_SCRIPT = Path(__file__).resolve().parent / "attach" / "gateway_attach.py"
READY_EVENT = "gateway.ready"
# The frontend shim hands the launcher's PYTHONPATH over under this name, so the
# OMH interpreter itself never imports from Hermes' tree.
GATEWAY_PYTHONPATH_ENV = "OMH_TUI_GATEWAY_PYTHONPATH"
# Names the shim and `omh` use to talk to the frontend; the gateway has no use for them.
INTERNAL_ENV_PREFIX = "OMH_TUI_"
# The herdr pane id stays with the TUI, which reports the pane's state itself (`herdr.py`). Where the gateway runs,
# herdr's own Hermes plugin (gated on `HERDR_ENV=1` and this id) would report a `herdr:hermes` session for the
# pane, after which herdr refuses the TUI's reports; a gateway daemon started from here also outlives the pane.
# Only the id goes, as herdr drops it for its own popups: herdr's CLI and skill still work in the gateway.
HERDR_PANE_ENV = "HERDR_PANE_ID"
REQUIRED_ENV = ("HERMES_PYTHON", "HERMES_PYTHON_SRC_ROOT")

STDERR_TAIL_LINES = 200
STDERR_LINE_CHARS = 2000
PREVIEW_CHARS = 200
# How long the reader waits for an exit code once stdout has closed.
EXIT_CODE_WAIT_SECONDS = 2.0
# How long `close` waits after a kill, and for each reader thread to reach end of file.
REAP_WAIT_SECONDS = 5.0
READER_JOIN_SECONDS = 1.0
# A child `start` gives up on (it never became ready, or refused the capabilities) has no session to save: its close
# waits this long after stdin closes, and as long again after terminate, before the kill.
UNREADY_CLOSE_GRACE_SECONDS = 0.5
# How often a blocking wait given a `cancel` asks it.
CANCEL_POLL_SECONDS = 0.1
# What the attach child exits with when the gateway is not answering yet: one restarting or starting (Hermes'
# `starting` / `draining` verdicts), or a refused, missing or silent control socket or WebSocket. EX_UNAVAILABLE.
# `gateway_attach.NOT_READY_EXIT` is the same number: that file imports nothing of `omh`.
GATEWAY_NOT_READY_EXIT = 69


class GatewayUnavailable(RuntimeError):
    """The gateway could not be started, or is gone. `stderr_tail` is what it printed last; `returncode` is the
    child's exit code when it exited before `gateway.ready`, else None."""

    def __init__(self, message: str, stderr_tail: tuple[str, ...] = (), returncode: int | None = None) -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail
        self.returncode = returncode

    @property
    def not_ready(self) -> bool:
        """Whether the attach child said the gateway is there but not answering yet (`GATEWAY_NOT_READY_EXIT`)."""
        return self.returncode == GATEWAY_NOT_READY_EXIT


class GatewayCallError(RuntimeError):
    """The gateway answered a call with a JSON-RPC error."""

    def __init__(self, method: str, code: object, message: str) -> None:
        super().__init__(f"{method} failed ({code}): {message}")
        self.method = method
        self.code = code
        self.message = message

    @property
    def drift(self) -> bool:
        """Whether the error means this Hermes no longer speaks the contract the TUI was built for."""
        return contract.is_drift_error({"code": self.code})


class GatewayCancelled(RuntimeError):
    """A blocking wait (`start`, `call`) that its caller's `cancel` ended: the person left while it waited."""


class GatewayTimeout(RuntimeError):
    """A call got no answer within its deadline. Not a `TimeoutError`, so no `except OSError` swallows it."""

    def __init__(self, method: str, timeout: float) -> None:
        super().__init__(f"{method} got no answer within {timeout:g}s")
        self.method = method
        self.timeout = timeout


@dataclass(frozen=True)
class GatewaySpawn:
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]


@dataclass(frozen=True)
class Event:
    type: str
    session_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class ServerRequest:
    id: str
    method: str
    params: dict[str, Any]


@dataclass(frozen=True)
class Response:
    id: int
    result: dict[str, Any] | None
    error: dict[str, Any] | None


@dataclass(frozen=True)
class ProtocolError:
    """A stdout line that is not a frame this client understands. Kept in memory only."""

    preview: str


@dataclass(frozen=True)
class GatewayExited:
    returncode: int | None


Inbound = Event | ServerRequest | Response | ProtocolError | GatewayExited


def gateway_spawn(env: Mapping[str, str]) -> GatewaySpawn:
    """The gateway's argv, cwd and environment, from the environment the launcher handed the frontend."""
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise GatewayUnavailable(f"the Hermes launcher did not provide {', '.join(missing)}")
    python = env["HERMES_PYTHON"]
    src_root = env["HERMES_PYTHON_SRC_ROOT"]
    child = {
        name: value
        for name, value in env.items()
        if name not in (*contract.STRIPPED_GATEWAY_ENV, HERDR_PANE_ENV) and not name.startswith(INTERNAL_ENV_PREFIX)
    }
    launcher_path = env.get(GATEWAY_PYTHONPATH_ENV, "")
    child["PYTHONPATH"] = src_root + os.pathsep + launcher_path if launcher_path else src_root
    return GatewaySpawn(
        argv=(python, str(GATEWAY_SCRIPT)),
        cwd=env.get("HERMES_CWD") or src_root,
        env=child,
    )


def attach_refused(env: Mapping[str, str]) -> bool:
    """Whether the launcher asked the frontend to attach to a gateway it already runs.

    The OMH TUI never attaches to a session another runtime owns, so the caller
    exits and names `hermes` instead of spawning.
    """
    return bool(env.get(contract.ATTACH_ENV, "").strip())  # blank is unset, as Hermes and Ink read it


def _protocol_error(line: str) -> ProtocolError:
    return ProtocolError(preview=line[:PREVIEW_CHARS])


def _parse_frame(line: str) -> Inbound:
    """One stdout line as an inbound item; anything that is not a gateway frame is a `ProtocolError`."""
    try:
        frame = json.loads(line)
    except ValueError:
        return _protocol_error(line)
    if not isinstance(frame, dict):
        return _protocol_error(line)
    method = frame.get("method")
    params = frame.get("params", {})
    if method == "event" and isinstance(params, dict) and isinstance(params.get("type"), str):
        session_id = params.get("session_id")
        payload = params.get("payload", {})
        return Event(
            type=params["type"],
            session_id=session_id if isinstance(session_id, str) else None,
            payload=payload if isinstance(payload, dict) else {},
        )
    request_id = frame.get("id")
    if isinstance(method, str) and isinstance(request_id, str) and isinstance(params, dict):
        return ServerRequest(id=request_id, method=method, params=params)
    result = frame.get("result")
    error = frame.get("error")
    is_answer = ("result" in frame) != ("error" in frame)
    shapes_ok = isinstance(result, dict | None) and isinstance(error, dict | None)
    if method is None and type(request_id) is int and is_answer and shapes_ok:
        return Response(id=request_id, result=result, error=error)
    return _protocol_error(line)


class GatewayClient:
    """Spawns the gateway, speaks its JSON-RPC, and reaps it."""

    def __init__(
        self,
        spawn: GatewaySpawn,
        *,
        popen: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        first_id: int = 1,
    ) -> None:
        """`first_id` is the first request id this client sends: a client that replaces one whose calls are still
        waiting starts past their ids, so no answer to it is ever read as an answer to them."""
        self._spawn = spawn
        self._popen = subprocess.Popen if popen is None else popen  # read now: an import-time default would keep a patch
        self._clock = clock
        self._process: Any = None
        self._readers: list[tuple[threading.Thread, IO[bytes]]] = []
        self._inbox_ready = threading.Condition()
        self._inbox: deque[Inbound] = deque()
        self._awaited: set[int] = set()  # ids a blocking `call` is waiting on
        self._polled: set[int] = set()  # ids whose answer goes to `poll`
        self._answers: dict[int, Response] = {}
        self._exited = False
        self._next_id = first_id
        self._write_lock = threading.Lock()
        self._stderr_lock = threading.Lock()
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._wake: tuple[int, int] | None = None  # (read end, write end) once `wake_fd` was asked for
        self.capabilities: dict[str, Any] = {}

    def start(self, ready_timeout: float = 60.0, cancel: Callable[[], bool] | None = None) -> Event:
        """Spawn the gateway, wait for `gateway.ready`, and declare `client.capabilities`.

        Any way the gateway fails to come up -- it cannot be spawned, exits, or
        stays silent past `ready_timeout` -- raises `GatewayUnavailable` with its
        stderr tail, after the child is reaped. A drift answer to
        `client.capabilities` raises `GatewayCallError`, also after reaping.
        `cancel`, asked every `CANCEL_POLL_SECONDS` while it waits (under the
        client's lock, so it must not call the client), ends the wait with
        `GatewayCancelled` once it says True, after reaping as well. A child it
        gives up on is closed with `UNREADY_CLOSE_GRACE_SECONDS`.
        """
        if self._process is not None:
            raise RuntimeError("the gateway client was already started")
        try:
            self._process = self._popen(
                list(self._spawn.argv),
                cwd=self._spawn.cwd,
                env=self._spawn.env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise GatewayUnavailable(f"could not start {self._spawn.argv[0]}: {error}") from error
        self._start_thread("omh-tui-gateway-stdout", self._read_stdout, self._process.stdout)
        self._start_thread("omh-tui-gateway-stderr", self._drain_stderr, self._process.stderr)
        deadline = self._clock() + ready_timeout
        try:
            ready = self._take_ready(deadline, ready_timeout, cancel)
            remaining = max(deadline - self._clock(), 0.0)
            self.capabilities = self.call(
                "client.capabilities", {"server_requests": True}, timeout=remaining, cancel=cancel
            )
        except (GatewayUnavailable, GatewayTimeout) as error:
            self.close(grace=UNREADY_CLOSE_GRACE_SECONDS, terminate_grace=UNREADY_CLOSE_GRACE_SECONDS)
            # Read the tail after reaping: only then has the drain thread seen every line.
            returncode = error.returncode if isinstance(error, GatewayUnavailable) else None
            raise GatewayUnavailable(str(error), tuple(self.stderr_tail()), returncode) from None
        except (GatewayCallError, GatewayCancelled):
            self.close(grace=UNREADY_CLOSE_GRACE_SECONDS, terminate_grace=UNREADY_CLOSE_GRACE_SECONDS)
            raise
        return ready

    def request(self, method: str, params: dict[str, Any]) -> int:
        """Send a call without waiting; its `Response` arrives through `poll`."""
        return self._send_call(method, params, self._polled)

    def forget(self, request_id: int) -> None:
        """Stop waiting for a `request`'s answer: if it still comes, it is dropped like an answer to nothing asked."""
        with self._inbox_ready:
            self._polled.discard(request_id)

    def call(
        self, method: str, params: dict[str, Any], timeout: float = 30.0, cancel: Callable[[], bool] | None = None
    ) -> dict[str, Any]:
        """Send a call and wait for its answer; every other inbound item stays queued for `poll`.

        `cancel` is asked as `start` asks it, and ends the wait with
        `GatewayCancelled` (or with what it raised); an answer that still
        comes is then dropped.
        """
        request_id = self._send_call(method, params, self._awaited)
        deadline = self._clock() + timeout
        response: Response | None = None
        with self._inbox_ready:
            try:
                while request_id not in self._answers and not self._exited:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        break
                    if cancel is not None and cancel():
                        raise GatewayCancelled(f"{method} was left waiting")
                    self._inbox_ready.wait(min(remaining, CANCEL_POLL_SECONDS) if cancel is not None else remaining)
                response = self._answers.pop(request_id, None)
            finally:  # however the wait ends, a later answer to it is dropped (`_deliver`)
                self._awaited.discard(request_id)
        if response is None and self._exited:
            raise self._unavailable(f"the gateway exited while {method} was waiting for an answer")
        if response is None:
            raise GatewayTimeout(method, timeout)
        if response.error is not None:
            raise GatewayCallError(method, response.error.get("code"), str(response.error.get("message", "")))
        return response.result or {}

    def respond(self, request_id: str, frame: dict[str, Any]) -> None:
        """Answer a server request; `frame` is `{"result": ...}` or `{"error": ...}`."""
        if set(frame) not in ({"result"}, {"error"}):
            raise ValueError(f"a server-request answer carries exactly one of result or error, not {sorted(frame)}")
        self._write({"jsonrpc": "2.0", "id": request_id, **frame})

    def wake_fd(self) -> int:
        """A descriptor that is readable while an item waits for `poll`; `poll` empties it. POSIX only.

        The pipe is made on the first call, and is readable at once if items
        are already queued.
        """
        with self._inbox_ready:
            if self._wake is None:
                read_end, write_end = os.pipe()
                os.set_blocking(read_end, False)
                os.set_blocking(write_end, False)
                self._wake = (read_end, write_end)
                if self._inbox:
                    self._signal_wake()
            return self._wake[0]

    def wake(self) -> None:
        """Make `wake_fd` readable from any thread, for news that is not an item (a new HUD snapshot).

        `poll` empties it as it does for an item. Nothing happens before
        `wake_fd` was first asked for or after `close`.
        """
        with self._inbox_ready:
            self._signal_wake()

    def poll(self, timeout: float = 0.0) -> list[Inbound]:
        """Every queued inbound item, waiting up to `timeout` for the first one."""
        deadline = self._clock() + timeout
        self._drain_wake()  # first: an item queued after this wakes the next select, which costs one empty poll
        with self._inbox_ready:
            while not self._inbox:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return []
                self._inbox_ready.wait(remaining)
            items = list(self._inbox)
            self._inbox.clear()
        return items

    def stderr_tail(self) -> list[str]:
        """The last lines the gateway wrote to stderr, held in memory only."""
        with self._stderr_lock:
            return list(self._stderr)

    def close(self, grace: float = 3.0, terminate_grace: float | None = None) -> int | None:
        """Close stdin, wait `grace`, terminate, wait `terminate_grace` (default `grace`), kill.

        Never raises; returns the exit code seen. The gateway can take more
        than 10 s to exit after stdin closes, so the escalation is required,
        not defensive.
        """
        process = self._process
        if process is None:
            return None
        try:
            process.stdin.close()
        except OSError:
            pass
        code = _wait(process, grace)
        if code is None:
            _signal(process.terminate)
            code = _wait(process, grace if terminate_grace is None else terminate_grace)
        if code is None:
            _signal(process.kill)
            code = _wait(process, REAP_WAIT_SECONDS)
        for thread, stream in self._readers:
            thread.join(READER_JOIN_SECONDS)
            if not thread.is_alive():  # a pipe still held open (say, by a grandchild) is left to its thread
                stream.close()
        with self._inbox_ready:  # a reader still alive writes the wake pipe under this lock: none can after it
            wake, self._wake = self._wake, None
        for descriptor in wake or ():
            os.close(descriptor)
        return code

    def _start_thread(self, name: str, target: Callable[[IO[bytes]], None], stream: IO[bytes]) -> None:
        thread = threading.Thread(target=target, args=(stream,), name=name, daemon=True)
        self._readers.append((thread, stream))
        thread.start()

    def _take_ready(self, deadline: float, ready_timeout: float, cancel: Callable[[], bool] | None = None) -> Event:
        """Take `gateway.ready` out of the queue; whatever arrived before it stays queued for `poll`. `cancel` as
        in `start`."""
        with self._inbox_ready:
            while True:
                ready = next((item for item in self._inbox if _is_ready(item)), None)
                if ready is not None:
                    self._inbox.remove(ready)
                    return ready
                exited = next((item for item in self._inbox if isinstance(item, GatewayExited)), None)
                if exited is not None:
                    raise GatewayUnavailable(
                        f"the gateway exited with code {exited.returncode} before {READY_EVENT}",
                        returncode=exited.returncode,
                    )
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise GatewayUnavailable(f"the gateway sent no {READY_EVENT} within {ready_timeout:g}s")
                if cancel is not None and cancel():
                    raise GatewayCancelled(f"the wait for {READY_EVENT} was left")
                self._inbox_ready.wait(min(remaining, CANCEL_POLL_SECONDS) if cancel is not None else remaining)

    def _send_call(self, method: str, params: dict[str, Any], waiting: set[int]) -> int:
        problem = contract.call_problem(method, params)
        if problem:
            raise ValueError(problem)
        with self._inbox_ready:
            request_id = self._next_id
            self._next_id += 1
            waiting.add(request_id)
        try:
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        except GatewayUnavailable:
            with self._inbox_ready:
                waiting.discard(request_id)
            raise
        return request_id

    def _write(self, frame: dict[str, Any]) -> None:
        if self._process is None:
            raise GatewayUnavailable("the gateway was not started")
        data = (json.dumps(frame) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                self._process.stdin.write(data)
                self._process.stdin.flush()
        except (OSError, ValueError) as error:  # ValueError: stdin already closed by `close`
            raise self._unavailable(f"the gateway stopped reading its input ({error})") from error

    def _unavailable(self, message: str) -> GatewayUnavailable:
        """The error for a gateway that is gone, with its exit code once its exit has been seen."""
        with self._inbox_ready:  # reentrant: a caller may already hold it
            exited = next((item for item in self._inbox if isinstance(item, GatewayExited)), None)
        return GatewayUnavailable(message, tuple(self.stderr_tail()), exited.returncode if exited else None)

    def _read_stdout(self, stream: IO[bytes]) -> None:
        try:
            for raw in stream:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self._deliver(_parse_frame(line))
        except (OSError, ValueError):  # the pipe was torn down under the reader
            pass
        self._deliver(GatewayExited(_wait(self._process, EXIT_CODE_WAIT_SECONDS)))

    def _drain_stderr(self, stream: IO[bytes]) -> None:
        try:
            for raw in stream:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")[:STDERR_LINE_CHARS]
                with self._stderr_lock:
                    self._stderr.append(line)
        except (OSError, ValueError):
            pass

    def _deliver(self, item: Inbound) -> None:
        with self._inbox_ready:
            if isinstance(item, Response):
                if item.id in self._awaited:
                    self._answers[item.id] = item
                elif item.id in self._polled:
                    self._polled.discard(item.id)
                    self._inbox.append(item)
                    self._signal_wake()
                else:
                    return  # an answer to nothing this client asked, or to a call that timed out
            else:
                if isinstance(item, GatewayExited):
                    self._exited = True
                self._inbox.append(item)
                self._signal_wake()
            self._inbox_ready.notify_all()

    def _signal_wake(self) -> None:
        """Make the wake pipe readable; called with `_inbox_ready` held. A full pipe is readable already."""
        if self._wake is not None:
            try:
                os.write(self._wake[1], b"\0")
            except BlockingIOError:
                pass

    def _drain_wake(self) -> None:
        with self._inbox_ready:
            wake = self._wake
            if wake is None:
                return
            try:
                while os.read(wake[0], 4096):
                    pass
            except BlockingIOError:
                pass


def _is_ready(item: Inbound) -> bool:
    return isinstance(item, Event) and item.type == READY_EVENT


def _wait(process: Any, timeout: float) -> int | None:
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def _signal(send: Callable[[], None]) -> None:
    try:
        send()
    except OSError:  # it exited between the wait and the signal
        pass
