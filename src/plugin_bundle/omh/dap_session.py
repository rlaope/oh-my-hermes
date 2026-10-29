"""Session state and action logic for the opt-in `debug_python` tool (toolset `omh-dap`).

Pure over an injectable client factory: nothing here spawns a process, so every action
is unit-testable with a fake client. The real factory (`dap_client.DapClient`) is
passed in by the tool module. One session per Hermes ``task_id`` lives in a
module-level ``SessionManager``, so parallel gateway sessions never cross.

Handshake order (verified live against debugpy 1.8.22): ``initialize`` -> ``launch``
(response not awaited yet) -> event ``initialized`` -> ``setBreakpoints`` per file ->
``configurationDone`` -> ``launch`` response -> event ``stopped`` (or ``exited``).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, NoReturn

from .dap_client import DapError
from .lsp_nav import LspNavError, inside, resolve_path

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 180
IDLE_TIMEOUT = 600.0
OUTPUT_RING = 64 * 1024
OUTPUT_TAIL = 2000
MAX_FRAMES = 8
MAX_LOCALS = 40
REPR_CAP = 200
RESULT_CAP = 2000
_EXIT_GRACE = 5.0
_ENV_KEYS = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR",
             "LANG", "LC_ALL", "LC_CTYPE", "PATHEXT", "COMSPEC", "WINDIR")
_HIDDEN_VARIABLES = frozenset({"special variables", "function variables", "class variables",
                               "protected variables"})
_STEP_COMMANDS = {"continue": "continue", "step_over": "next", "step_in": "stepIn", "step_out": "stepOut"}

ClientFactory = Callable[[list[str], str, dict[str, str]], Any]


class SessionError(Exception):
    def __init__(self, code: str, hint: str, **extra: Any) -> None:
        super().__init__(hint)
        self.code, self.hint, self.extra = code, hint, extra


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _timeout(args: dict[str, Any]) -> int:
    value = args.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_TIMEOUT:
        raise SessionError("invalid_argument", f"timeout must be an integer from 1 to {MAX_TIMEOUT} seconds")
    return value


def _index(args: dict[str, Any], name: str = "frame") -> int:
    value = args.get(name, 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SessionError("invalid_argument", f"{name} must be a non-negative integer")
    return value


def _lines(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in value):
        raise SessionError("invalid_argument", f"{name} must be a list of 1-based line numbers")
    return value


def confine(path: Any, root: str) -> str:
    """Realpath of ``path`` inside ``root``; ``scope_mismatch`` for an escape (symlinks included)."""
    if not isinstance(path, str) or not path.strip():
        raise SessionError("invalid_argument", "path must be a non-empty string")
    try:
        resolved = resolve_path(path, root)
    except LspNavError as exc:
        raise SessionError("scope_mismatch", str(exc)) from None
    if not os.path.isfile(resolved):
        raise SessionError("invalid_argument", f"{path} is not a file under the workspace root {root}")
    return resolved


def adapter_env(root: str, environ: dict[str, str] | None = None) -> dict[str, str]:
    """A minimal environment for the adapter: OS essentials plus ``PYTHONPATH=<root>/src`` when it exists."""
    source = os.environ if environ is None else environ
    env = {key: source[key] for key in _ENV_KEYS if key in source}
    src = os.path.join(root, "src")
    if os.path.isdir(src):
        env["PYTHONPATH"] = src
    return env


class Session:
    """One live debug adapter plus what the model has seen of it."""

    def __init__(self, client: Any, root: str, timeout: int) -> None:
        self.client = client
        self.root = root
        self.timeout = timeout
        self.thread_id: int | None = None
        self.stopped = False
        self.breakpoints: dict[str, tuple[list[int], str | None]] = {}
        self.launch_breakpoints: list[dict[str, Any]] = []
        self.output = ""
        self.last_used = time.monotonic()
        self.lock = threading.Lock()

    # ---- helpers -----------------------------------------------------------

    def collect_output(self) -> None:
        text = self.client.drain_output()
        if text:
            self.output = (self.output + text)[-OUTPUT_RING:]

    def rel(self, path: Any) -> str | None:
        if not isinstance(path, str) or not path:
            return None
        real = os.path.realpath(path)
        return os.path.relpath(real, self.root) if inside(real, self.root) else real

    def frame_view(self, frame: dict[str, Any]) -> dict[str, Any]:
        source = frame.get("source") or {}
        return {"function": frame.get("name"), "path": self.rel(source.get("path")), "line": frame.get("line")}

    def frames(self, levels: int) -> list[dict[str, Any]]:
        if self.thread_id is None:
            return []
        body = self.client.request("stackTrace", {"threadId": self.thread_id, "startFrame": 0, "levels": levels})
        return list(body.get("stackFrames") or [])

    def frame_at(self, index: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        frames = self.frames(max(MAX_FRAMES, index + 1))
        if index >= len(frames):
            raise SessionError("invalid_argument", f"frame {index} does not exist; the stack has {len(frames)} frames")
        return frames[index], frames

    def require_stopped(self) -> None:
        if not self.stopped:
            raise SessionError("not_stopped", "the program is running; wait with continue or terminate")

    def set_file_breakpoints(self, path: str, lines: list[int], condition: str | None) -> list[dict[str, Any]]:
        entries = [{"line": line, **({"condition": condition} if condition else {})} for line in lines]
        body = self.client.request("setBreakpoints", {"source": {"path": path}, "breakpoints": entries})
        if lines:
            self.breakpoints[path] = (lines, condition)
        else:
            self.breakpoints.pop(path, None)
        reported = list(body.get("breakpoints") or [])
        return [{"line": (reported[i].get("line") if i < len(reported) else None) or line,
                 "verified": bool(reported[i].get("verified")) if i < len(reported) else False}
                for i, line in enumerate(lines)]

    def wait_stop(self, timeout: float) -> dict[str, Any]:
        """The next stop or exit as a reply dict; marks the session ended on exit."""
        event = self.client.wait_event(("stopped", "exited", "terminated"), timeout)
        name = event.get("event")
        body = event.get("body") or {}
        if name == "stopped":
            self.stopped = True
            self.thread_id = body.get("threadId", self.thread_id)
            frames = self.frames(1)
            stop = {"reason": body.get("reason")}
            stop.update(self.frame_view(frames[0]) if frames else {"function": None, "path": None, "line": None})
            if body.get("text"):
                stop["text"] = _cap(str(body["text"]), REPR_CAP)
            self.collect_output()
            return {"ok": True, "stopped": stop}
        exit_code = body.get("exitCode") if name == "exited" else None
        if name == "exited":
            try:
                self.client.wait_event(("terminated",), _EXIT_GRACE)
            except DapError:
                pass  # the exit code is already known; terminated only flushes output
        self.stopped = False
        self.collect_output()
        return {"ok": True, "exited": True, "exit_code": exit_code, "output_tail": self.output[-OUTPUT_TAIL:]}

    def close(self) -> str:
        try:
            self.collect_output()
        finally:
            self.client.close()
        return self.output[-OUTPUT_TAIL:]


class SessionManager:
    """Sessions keyed by Hermes ``task_id``; idle sessions are closed on the next call."""

    def __init__(self, factory: ClientFactory, idle_timeout: float = IDLE_TIMEOUT,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.factory = factory
        self.idle_timeout = idle_timeout
        self.clock = clock
        self._sessions: dict[str, Session] = {}
        self._launching: set[str] = set()  # keys reserved by a launch still spawning/handshaking
        self._lock = threading.Lock()

    def _expire(self, key: str) -> bool:
        session = self._sessions.get(key)
        if session is None or self.clock() - session.last_used <= self.idle_timeout:
            return False
        self._sessions.pop(key, None)
        session.close()
        return True

    def _take(self, key: str) -> Session:
        with self._lock:
            expired = self._expire(key)
            session = self._sessions.get(key)
        if session is None:
            hint = "no debug session; start one with action=launch"
            if expired:
                hint = "the debug session was idle for over 10 minutes and was closed; launch again"
            raise SessionError("no_session", hint)
        return session

    def _drop(self, key: str, session: Session) -> None:
        with self._lock:
            if self._sessions.get(key) is session:
                self._sessions.pop(key, None)

    def run(self, key: str, action: str, args: dict[str, Any], root: str) -> dict[str, Any]:
        if action == "launch":
            return self.launch(key, args, root)
        session = self._take(key)
        with session.lock:
            try:
                reply = self._act(session, action, args)
            except DapError as exc:
                if exc.code == "adapter_error" and session.client.alive():
                    raise SessionError("adapter_error", exc.message) from None
                self._fail_running(key, session, exc, {})
            finally:
                session.last_used = self.clock()
            if reply.get("exited") or action == "terminate":
                self._drop(key, session)
                if action != "terminate":
                    session.close()
            return reply

    def _act(self, session: Session, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action in _STEP_COMMANDS:
            timeout = _timeout({"timeout": args.get("timeout", session.timeout)})
            if action == "continue" and not session.stopped:
                return session.wait_stop(timeout)  # still running from a timed-out wait: wait again
            session.require_stopped()
            session.client.discard_events(("stopped", "continued"))
            session.client.request(_STEP_COMMANDS[action], {"threadId": session.thread_id})
            session.stopped = False
            return session.wait_stop(timeout)
        if action == "set_breakpoints":
            session.require_stopped()
            path = confine(args.get("path"), session.root)
            lines = _lines(args.get("lines"), "lines")
            condition = args.get("condition")
            if condition is not None and not isinstance(condition, str):
                raise SessionError("invalid_argument", "condition must be a string expression")
            return {"ok": True, "path": session.rel(path),
                    "breakpoints": session.set_file_breakpoints(path, lines, condition or None)}
        if action == "inspect":
            session.require_stopped()
            frame, frames = session.frame_at(_index(args))
            return {"ok": True, "frames": [session.frame_view(f) for f in frames[:MAX_FRAMES]],
                    "frame": _index(args), **self._locals(session, frame)}
        if action == "evaluate":
            session.require_stopped()
            expression = args.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                raise SessionError("invalid_argument", "expression must be a non-empty string")
            frame, _ = session.frame_at(_index(args))
            try:
                body = session.client.request("evaluate", {"expression": expression, "frameId": frame.get("id"),
                                                            "context": "watch"})
            except DapError as exc:
                if not exc.message.startswith("SyntaxError"):
                    raise
                # A statement (`import m; m.X`, `x = 1`) is not an expression; say how to get a value back
                # instead of a bare SyntaxError the model retries with variations.
                raise SessionError("not_an_expression", f"{exc.message}. evaluate takes one Python expression, "
                                   "not statements: use __import__('pkg.mod', fromlist=['X']).X to read a "
                                   "module value, or inspect for locals") from None
            return {"ok": True, "result": _cap(str(body.get("result", "")), RESULT_CAP),
                    **({"type": body["type"]} if body.get("type") else {})}
        if action == "terminate":
            return {"ok": True, "terminated": True, "output_tail": session.close()}
        raise SessionError("invalid_argument", f"unknown action {action!r}")

    def _locals(self, session: Session, frame: dict[str, Any]) -> dict[str, Any]:
        scopes = list((session.client.request("scopes", {"frameId": frame.get("id")}) or {}).get("scopes") or [])
        if not scopes:
            return {"locals": {}}
        scope = next((s for s in scopes if str(s.get("name", "")).lower().startswith("local")), scopes[0])
        body = session.client.request("variables", {"variablesReference": scope.get("variablesReference")})
        names = [v for v in body.get("variables") or [] if v.get("name") not in _HIDDEN_VARIABLES]
        out: dict[str, Any] = {"locals": {str(v.get("name")): _cap(str(v.get("value", "")), REPR_CAP) for v in names[:MAX_LOCALS]}}
        if len(names) > MAX_LOCALS:
            out["locals_omitted"] = len(names) - MAX_LOCALS
        return out

    # ---- launch ------------------------------------------------------------

    def launch(self, key: str, args: dict[str, Any], root: str) -> dict[str, Any]:
        with self._lock:
            self._expire(key)
            if key in self._sessions or key in self._launching:
                raise SessionError("session_active", "a debug session is already live; call action=terminate first")
            # Reserve the key before spawning: two parallel launches on one task must not both start an
            # adapter, or the first is orphaned when the second overwrites it.
            self._launching.add(key)
        try:
            return self._launch_reserved(key, args, root)
        finally:
            with self._lock:
                self._launching.discard(key)

    def _launch_reserved(self, key: str, args: dict[str, Any], root: str) -> dict[str, Any]:
        python = args.get("python")
        if not isinstance(python, str) or not python.strip():
            raise SessionError("invalid_argument", "python (the interpreter path to debug with) is required")
        python = os.path.abspath(python)
        if not os.path.isfile(python) or not os.access(python, os.X_OK):
            raise SessionError("invalid_argument", f"python {python} is not an executable file")
        program, module = args.get("program"), args.get("module")
        if program is not None and module is not None:
            raise SessionError("invalid_argument", "pass module or program, not both")
        target: dict[str, Any]
        if program is not None:
            target = {"program": confine(program, root)}
        else:
            module = "pytest" if module is None else module
            if not isinstance(module, str) or not all(part.isidentifier() for part in module.split(".")):
                raise SessionError("invalid_argument", "module must be a dotted Python module name")
            target = {"module": module}
        prog_args = args.get("args", [])
        if not isinstance(prog_args, list) or not all(isinstance(a, str) for a in prog_args):
            raise SessionError("invalid_argument", "args must be a list of strings")
        breakpoints = args.get("breakpoints", [])
        if not isinstance(breakpoints, list) or not all(isinstance(b, dict) for b in breakpoints):
            raise SessionError("invalid_argument", "breakpoints must be a list of {path, line, condition?}")
        planned: dict[str, tuple[list[int], str | None]] = {}
        for item in breakpoints:
            path = confine(item.get("path"), root)
            line = _lines([item.get("line")], "breakpoint line")[0]
            condition = item.get("condition")
            if condition is not None and not isinstance(condition, str):
                raise SessionError("invalid_argument", "a breakpoint condition must be a string expression")
            lines, prior = planned.get(path, ([], None))
            planned[path] = (lines + [line], condition or prior)
        timeout = _timeout(args)
        env = adapter_env(root)
        try:
            client = self.factory([python, "-m", "debugpy.adapter"], root, env)
        except DapError as exc:
            raise SessionError("adapter_unavailable", f"{exc.message}; debugpy must be importable by it: "
                                                      f"{python} -m pip install debugpy") from None
        session = Session(client, root, timeout)
        started = False
        try:
            self._handshake(session, python, target, prog_args, planned, env)
            started = True
        except DapError as exc:
            tail = client.stderr_tail()
            if exc.code == "adapter_exited" or (exc.code == "timeout" and not client.alive()):
                hint = f"the debug adapter did not start; is debugpy installed? run: {python} -m pip install debugpy"
                raise SessionError("adapter_unavailable", hint, stderr_tail=tail) from None
            raise SessionError(exc.code, exc.message, stderr_tail=tail) from None
        finally:
            if not started:
                session.close()  # never leave an adapter behind a failed launch (close is idempotent)
        with self._lock:
            self._sessions[key] = session
        session.last_used = self.clock()
        extra = {"breakpoints": session.launch_breakpoints} if planned else {}
        with session.lock:
            try:
                reply = session.wait_stop(session.timeout)
            except DapError as exc:
                self._fail_running(key, session, exc, extra)
            finally:
                session.last_used = self.clock()
        if reply.get("exited"):
            self._drop(key, session)
            session.close()
        reply.update(extra)
        return reply

    def _fail_running(self, key: str, session: Session, exc: DapError, extra: dict[str, Any]) -> NoReturn:
        """Raise the classified error for a failed call on a started session."""
        if exc.code == "timeout" and session.client.alive():
            raise SessionError("timeout", "the program is still running and has not stopped; call continue to "
                               "keep waiting (optionally with a larger timeout) or terminate", **extra) from None
        self._drop(key, session)
        tail = session.close()
        if exc.code == "adapter_error":
            raise SessionError("adapter_error", exc.message, **extra) from None
        raise SessionError("adapter_error", f"the debug adapter exited: {exc.message}", output_tail=tail,
                           **extra) from None

    def _handshake(self, session: Session, python: str, target: dict[str, Any], prog_args: list[str],
                   planned: dict[str, tuple[list[int], str | None]], env: dict[str, str]) -> None:
        client = session.client
        client.request("initialize", {"adapterID": "debugpy", "clientID": "omh", "clientName": "omh debug_python",
                                      "linesStartAt1": True, "columnsStartAt1": True, "pathFormat": "path"})
        launch_env = {"PYTHONPATH": env["PYTHONPATH"]} if "PYTHONPATH" in env else {}
        launch_seq = client.send("launch", {**target, "args": prog_args, "cwd": session.root, "python": [python],
                                            "env": launch_env, "console": "internalConsole", "justMyCode": True,
                                            "stopOnEntry": False})
        client.wait_event(("initialized",), session.timeout)
        for path, (lines, condition) in planned.items():
            for row in session.set_file_breakpoints(path, lines, condition):
                session.launch_breakpoints.append({"path": session.rel(path), **row})
        client.request("configurationDone", {})
        client.wait_response(launch_seq, session.timeout)


__all__ = [
    "DEFAULT_TIMEOUT", "IDLE_TIMEOUT", "MAX_FRAMES", "MAX_LOCALS", "MAX_TIMEOUT", "OUTPUT_RING", "OUTPUT_TAIL",
    "REPR_CAP", "RESULT_CAP", "Session", "SessionError", "SessionManager", "adapter_env", "confine",
]
