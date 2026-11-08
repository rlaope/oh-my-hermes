#!/usr/bin/env python3
"""omher bridge: the UI protocol (01-protocol.md) on a loopback WebSocket, backed by each Hermes
profile's own gateway through Hermes' ``connect_gateway``.

    python omher_bridge.py --port 0 --token <t> [--exit-on-stdin-eof] [--eager]
                           [--hermes-home DIR] [--hermes-root DIR]

Prints one line ``OMHER_BRIDGE_READY {"port": N}`` on stdout once listening; everything else goes
to stderr. Binds 127.0.0.1 only and refuses (403) any connection whose ``token`` query parameter
differs. Makes no model or network call of its own.

Boundary rules the code keeps:
* One gateway connection per profile, opened lazily (``--eager`` opens them all at start).
* The only session this bridge ever resumes, creates, submits to, interrupts or answers is the
  bot's main chat (the session titled ``Bot Chat``). Every other session is only listed or read
  (list / history), never attached.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VERSION = "0.1.0"
BOT_CHAT_TITLE = "Bot Chat"
LOCAL_SOURCES = frozenset({"tui", "cli", "local", "desktop", "acp", "api_server", "omher"})
REASONING_LEVELS = ["none", "low", "medium", "high", "xhigh"]
RUNNING_STATUSES = frozenset({"working", "streaming", "waiting", "starting"})
MAX_ELSEWHERE = 20
MAX_OPEN_MESSAGES = 200
PEEK_CHARS = 400
THINKING_MIN_GAP = 1.0
CONNECT_TIMEOUT = 60.0
OFFLINE_COOLDOWN = 10.0
def _default_hermes_root() -> Path:
    """The Hermes checkout whose venv runs this bridge (`<root>/venv/bin/python`), else ~/.hermes/hermes-agent."""
    exe = Path(sys.executable)
    for venv in (exe.parent.parent,):
        if venv.name in ("venv", ".venv") and (venv.parent / "hermes_cli").is_dir():
            return venv.parent
    return Path.home() / ".hermes" / "hermes-agent"


DEFAULT_HERMES_ROOT = _default_hermes_root()

log = logging.getLogger("omher.bridge")


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Reply:
    """An op result plus work to run after the reply frame has been written."""

    def __init__(self, result: dict, after=None):
        self.result = result
        self.after = after


def _named(exc: BaseException, name: str) -> bool:
    return any(c.__name__ == name for c in type(exc).__mro__)


def _snake(text: str) -> bool:
    return bool(text) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", text) is not None


# ---------------------------------------------------------------- profile discovery (files only)

def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # Hermes' own dependency; absent only outside its venv
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def discover_bots(home: Path) -> list[dict]:
    """Default profile + ``profiles/<name>/`` dirs holding a config.yaml, from disk only."""
    found = []
    dirs = [("default", home)]
    pdir = home / "profiles"
    if pdir.is_dir():
        dirs += [(d.name, d) for d in sorted(pdir.iterdir()) if (d / "config.yaml").is_file()]
    for name, path in dirs:
        cfg = _load_yaml(path / "config.yaml")
        meta = _load_yaml(path / "profile.yaml")
        model = cfg.get("model")
        if isinstance(model, dict):
            model_name, provider = str(model.get("default") or ""), str(model.get("provider") or "")
        else:
            model_name, provider = str(model or ""), ""
        display = str(meta.get("display_name") or "").strip() or ("Hermes" if name == "default" else name.capitalize())
        found.append({"name": name, "path": path, "is_default": name == "default", "display_name": display,
                      "model": model_name, "provider": provider,
                      "description": str(meta.get("description") or "").strip(),
                      "reasoning": str((cfg.get("agent") or {}).get("reasoning_effort") or "")
                      if isinstance(cfg.get("agent"), dict) else ""})
    return found


def read_routines(profile_dir: Path) -> list[dict]:
    try:
        data = json.loads((profile_dir / "cron" / "jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    out = []
    for j in jobs if isinstance(jobs, list) else []:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        sched = j.get("schedule_display")
        if not sched and isinstance(j.get("schedule"), dict):
            sched = j["schedule"].get("display") or j["schedule"].get("expr")
        out.append({"id": str(j["id"]), "name": str(j.get("name") or j["id"]), "schedule": str(sched or ""),
                    "next_run_at": j.get("next_run_at"), "last_run_at": j.get("last_run_at"),
                    "last_status": j.get("last_status"), "enabled": bool(j.get("enabled", True))})
    return out


def _to_ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return time.time()


# ---------------------------------------------------------------- transcript helpers

_AUTHOR_RE = re.compile(r"^\[(?P<author>[^\]|]+?)\s*\|[^\]]*\]\s*(?P<rest>.*)$", re.DOTALL)


def split_author(text: str) -> tuple[str | None, str]:
    """``[김희망 (Khope) | Slack user <@U0…>] hi`` -> (``김희망 (Khope)``, ``hi``)."""
    m = _AUTHOR_RE.match(text or "")
    if not m:
        return None, text
    return m.group("author").strip() or None, m.group("rest")


def _clip(text: str, n: int = PEEK_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _row_text(row: dict) -> str:
    for key in ("text", "content"):
        if isinstance(row.get(key), str) and row[key].strip():
            return row[key]
    return ""


def chat_messages(rows) -> list[dict]:
    out = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict) or row.get("role") not in ("user", "assistant"):
            continue
        if row.get("display_kind") == "hidden":
            continue
        text = _row_text(row)
        if not text:
            continue
        rid = row.get("row_id")
        out.append({"id": str(rid) if rid is not None else f"m{i}", "role": row["role"], "text": text,
                    "ts": float(row.get("timestamp") or 0.0)})
    return out[-MAX_OPEN_MESSAGES:]


# ---------------------------------------------------------------- one Hermes gateway connection

class Conn:
    """State for one bot (= one profile = one gateway connection)."""

    def __init__(self, bot: dict):
        self.bot = bot
        self.name = bot["name"]
        self.stack: AsyncExitStack | None = None
        self.client = None
        self.pump: asyncio.Task | None = None
        self.connecting = False
        self.lock = asyncio.Lock()
        self.failed_at = 0.0
        self.failed_msg = ""
        self.main_id: str | None = None        # runtime id of the main chat
        self.main_stored: str | None = None
        self.generation = None
        self.in_turn = False
        self.last_thinking = -1e9
        self.last_elsewhere_emit = -1e9
        self.elsewhere_sig = None
        self.prompts: dict[str, int | None] = {}  # open prompt_id -> execution_generation

    @property
    def connected(self) -> bool:
        return self.client is not None

    @property
    def main_ids(self) -> set[str]:
        return {i for i in (self.main_id, self.main_stored) if i}

    async def call(self, method: str, **params):
        if self.client is None:
            raise BridgeError("bot_offline", f"{self.name} is offline")
        return await self.client.rpc(method, **params)


class Bridge:
    def __init__(self, *, token: str, hermes_home: Path | None = None, gateway_factory=None, eager: bool = False,
                 clock=time.monotonic, poll_s: float = 30.0, elsewhere_poll_s: float = 20.0):
        self.token = token
        self.home = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
        self.gateway_factory = gateway_factory or self._default_connect
        self.eager = eager
        self.clock = clock
        self.poll_s = poll_s
        self.elsewhere_poll_s = elsewhere_poll_s
        self.conns: dict[str, Conn] = {}
        self.clients: set = set()
        self.server = None
        self.port = 0
        self._env_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._routine_state: dict[str, dict] = {}
        self.ops = {
            "hello": self.op_hello, "bots.list": self.op_bots_list, "chat.open": self.op_chat_open,
            "chat.send": self.op_chat_send, "chat.interrupt": self.op_chat_interrupt,
            "approval.respond": self.op_approval_respond, "clarify.respond": self.op_clarify_respond,
            "elsewhere.list": self.op_elsewhere_list, "elsewhere.peek": self.op_elsewhere_peek,
            "routines.list": self.op_routines_list, "models.options": self.op_models_options,
            "chat.set_model": self.op_set_model,
        }

    # ------------------------------------------------------------ lifecycle

    async def start(self, host: str = "127.0.0.1", port: int = 0, *, watch: bool = True) -> int:
        from websockets.asyncio.server import serve
        self.server = await serve(self._handler, host, port, process_request=self._process_request,
                                  max_size=4 * 1024 * 1024)
        self.port = self.server.sockets[0].getsockname()[1]
        if watch:
            self._spawn(self._watch())
        if self.eager:
            for bot in discover_bots(self.home):
                self._spawn(self._eager_connect(bot["name"]))
        return self.port

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            for ws in list(self.clients):
                with contextlib.suppress(Exception):
                    await ws.close()
            with contextlib.suppress(Exception):
                await self.server.wait_closed()
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(BaseException):
                await t
        for conn in list(self.conns.values()):
            await self._drop(conn, emit=False)

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def _eager_connect(self, name: str) -> None:
        with contextlib.suppress(Exception):
            await self._conn(name)

    # ------------------------------------------------------------ websocket side

    def _process_request(self, connection, request):
        token = parse_qs(urlsplit(request.path).query).get("token", [""])[0]
        if not hmac.compare_digest(token.encode(), self.token.encode()):
            return connection.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
        return None

    async def _handler(self, ws) -> None:
        self.clients.add(ws)
        try:
            async for raw in ws:
                self._spawn(self._handle_frame(ws, raw))
        except Exception:
            pass
        finally:
            self.clients.discard(ws)

    async def _send(self, ws, obj: dict) -> None:
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(obj, ensure_ascii=False))

    async def emit(self, event: str, bot: str, **fields) -> None:
        frame = {"event": event, "bot": bot, **fields}
        for ws in list(self.clients):
            await self._send(ws, frame)

    async def _handle_frame(self, ws, raw) -> None:
        rid = None
        try:
            try:
                frame = json.loads(raw)
            except ValueError:
                raise BridgeError("bad_request", "frame is not JSON")
            if isinstance(frame, dict) and isinstance(frame.get("id"), str):
                rid = frame["id"]
            if not isinstance(frame, dict) or rid is None or not isinstance(frame.get("op"), str):
                raise BridgeError("bad_request", "need string id and op")
            fn = self.ops.get(frame["op"])
            if fn is None:
                raise BridgeError("unknown_op", f"no such op: {frame['op']}")
            out = await fn(frame)
            after = None
            if isinstance(out, Reply):
                out, after = out.result, out.after
            await self._send(ws, {"id": rid, "ok": True, "result": out})
            if after is not None:
                await after()
        except BridgeError as e:
            await self._send(ws, {"id": rid, "ok": False, "error": {"code": e.code, "message": e.message}})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # never crash on one request
            code, msg = self._classify(e)
            if code != "gateway_error" or not _named(e, "GatewayRPCError"):
                log.warning("op failed: %r", e)
            await self._send(ws, {"id": rid, "ok": False, "error": {"code": code, "message": msg}})

    def _classify(self, exc: Exception) -> tuple[str, str]:
        if _named(exc, "GatewayRPCError"):
            reason = str(exc)
            return (reason if _snake(reason) else "gateway_error"), reason or "request failed"
        if _named(exc, "GatewayClientError"):
            return "bot_offline", str(exc) or "gateway unavailable"
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return "timeout", "the gateway did not answer in time"
        return "internal", f"{type(exc).__name__}: {exc}"

    # ------------------------------------------------------------ connections

    async def _default_connect(self, stack: AsyncExitStack, home: Path):
        from hermes_cli.gateway_client import connect_gateway
        async with self._env_lock:  # connect_gateway reads HERMES_HOME when it is entered
            os.environ["HERMES_HOME"] = str(home)
            return await stack.enter_async_context(connect_gateway())

    def _bot(self, name) -> dict:
        if not isinstance(name, str) or not name:
            raise BridgeError("bad_request", "missing bot")
        for b in discover_bots(self.home):
            if b["name"] == name:
                return b
        raise BridgeError("unknown_bot", f"no bot named {name}")

    async def _conn(self, name) -> Conn:
        bot = self._bot(name)
        conn = self.conns.get(name)
        if conn is None:
            conn = self.conns[name] = Conn(bot)
        conn.bot = bot
        if conn.connected:
            return conn
        async with conn.lock:
            if conn.connected:
                return conn
            if self.clock() - conn.failed_at < OFFLINE_COOLDOWN and conn.failed_msg:
                raise BridgeError("bot_offline", conn.failed_msg)
            conn.connecting = True
            stack = AsyncExitStack()
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    client = await self.gateway_factory(stack, bot["path"])
            except asyncio.CancelledError:
                with contextlib.suppress(BaseException):
                    await stack.aclose()
                raise
            except Exception as e:
                with contextlib.suppress(BaseException):
                    await stack.aclose()
                conn.failed_at = self.clock()
                conn.failed_msg = f"{name} is offline: {str(e) or type(e).__name__}"
                conn.connecting = False
                await self.emit("bot.status", name, status="offline", running=False)
                raise BridgeError("bot_offline", conn.failed_msg)
            conn.stack, conn.client, conn.connecting, conn.failed_msg = stack, client, False, ""
            conn.pump = self._spawn(self._pump(conn))
        await self.emit("bot.status", name, status="online", running=conn.in_turn)
        return conn

    async def _drop(self, conn: Conn, *, emit: bool = True, reason: str = "") -> None:
        was_turn = conn.in_turn
        pump, stack = conn.pump, conn.stack
        conn.client = conn.stack = conn.pump = None
        conn.in_turn = False
        conn.main_id = conn.main_stored = conn.generation = None
        conn.prompts.clear()
        if pump is not None and pump is not asyncio.current_task():
            pump.cancel()
            with contextlib.suppress(BaseException):
                await pump
        if stack is not None:
            with contextlib.suppress(BaseException):
                await stack.aclose()
        if emit:
            if was_turn:
                await self.emit("turn.end", conn.name, outcome="error", error=reason or "gateway disconnected")
            conn.failed_at, conn.failed_msg = self.clock(), reason or f"{conn.name} is offline"
            await self.emit("bot.status", conn.name, status="offline", running=False)

    async def _call(self, conn: Conn, method: str, **params):
        """RPC with connection-loss handling: a dead gateway turns the bot offline."""
        try:
            return await conn.call(method, **params)
        except BridgeError:
            raise
        except Exception as e:
            if _named(e, "GatewayClientError") and not _named(e, "GatewayRPCError"):
                await self._drop(conn, reason=str(e))
                raise BridgeError("bot_offline", f"{conn.name} lost its gateway: {e}")
            raise

    # ------------------------------------------------------------ gateway events -> UI events

    async def _pump(self, conn: Conn) -> None:
        events = conn.client.events
        try:
            while True:
                frame = await events.get()
                if isinstance(frame, BaseException):  # the client queues its own disconnect error
                    await self._drop(conn, reason=str(frame))
                    return
                try:
                    await self._on_frame(conn, frame)
                except Exception:
                    log.exception("event handling failed")
        except asyncio.CancelledError:
            raise

    async def _on_frame(self, conn: Conn, frame) -> None:
        if not isinstance(frame, dict) or frame.get("method") != "event":
            return
        params = frame.get("params")
        if not isinstance(params, dict):
            return
        typ, sid = params.get("type"), params.get("session_id")
        payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
        if typ == "sessions.changed":
            return await self._elsewhere_changed(conn)
        if sid and sid in conn.main_ids:
            return await self._main_event(conn, typ, params, payload)
        if typ in ("message.start", "message.complete"):  # someone else's session moved
            await self._elsewhere_changed(conn)

    async def _elsewhere_changed(self, conn: Conn) -> None:
        now = self.clock()
        if now - conn.last_elsewhere_emit >= 1.0:
            conn.last_elsewhere_emit = now
            await self.emit("elsewhere.update", conn.name)

    async def _begin_turn(self, conn: Conn) -> None:
        if not conn.in_turn:
            conn.in_turn = True
            await self.emit("turn.start", conn.name)
            await self.emit("bot.status", conn.name, status="online", running=True)

    async def _end_turn(self, conn: Conn, outcome: str, error: str | None = None) -> None:
        conn.in_turn = False
        conn.prompts.clear()
        fields = {"outcome": outcome}
        if error:
            fields["error"] = error
        await self.emit("turn.end", conn.name, **fields)
        await self.emit("bot.status", conn.name, status="online", running=False)

    async def _main_event(self, conn: Conn, typ: str, params: dict, p: dict) -> None:
        name = conn.name
        if params.get("execution_generation") is not None:
            conn.generation = params["execution_generation"]
        if typ == "message.start":
            await self._begin_turn(conn)
        elif typ == "status.update":
            text = p.get("text")
            if isinstance(text, str) and text.strip():
                await self.emit("status", name, text=text.strip())
        elif typ in ("thinking.delta", "reasoning.delta"):
            now = self.clock()
            if now - conn.last_thinking >= THINKING_MIN_GAP:
                conn.last_thinking = now
                await self.emit("thinking", name)
        elif typ == "tool.start":
            await self._begin_turn(conn)
            tool_id = str(p.get("tool_id") or p.get("tool_call_id") or "")
            tool = str(p.get("name") or p.get("tool_name") or "tool")
            context = p.get("context") if isinstance(p.get("context"), str) else ""
            await self.emit("tool.start", name, tool_id=tool_id, name=tool, detail=context[:160])
            if tool in ("skill_view", "skill_use"):
                args = p.get("args") if isinstance(p.get("args"), dict) else {}
                skill = str(args.get("name") or context).strip()
                if skill:
                    await self.emit("skill", name, name=skill)
        elif typ == "tool.complete":
            dur = p.get("duration_s")
            await self.emit("tool.end", name, tool_id=str(p.get("tool_id") or p.get("tool_call_id") or ""),
                            name=str(p.get("name") or p.get("tool_name") or "tool"),
                            ok=not p.get("is_error"), ms=int(round(dur * 1000)) if isinstance(dur, (int, float)) else 0)
        elif typ == "message.delta":
            text = p.get("text")
            if isinstance(text, str) and text:
                await self._begin_turn(conn)
                await self.emit("delta", name, text=text)
        elif typ == "message.complete":
            text = p.get("text") if isinstance(p.get("text"), str) else ""
            turn = p.get("persisted_turn") if isinstance(p.get("persisted_turn"), dict) else {}
            mid = turn.get("final_assistant_row_id") or p.get("admission_id") or uuid.uuid4().hex
            status = p.get("status")
            if text.strip():
                await self.emit("message", name, id=str(mid), text=text)
            if status == "interrupted":
                await self._end_turn(conn, "interrupted")
            elif status == "error":
                await self._end_turn(conn, "error", str(p.get("error") or p.get("failure_reason") or "turn failed"))
            else:
                await self._end_turn(conn, "done")
        elif typ == "error":
            if conn.in_turn:
                await self._end_turn(conn, "error", str(p.get("message") or "error"))
        elif typ == "approval.request":
            pid = str(p.get("prompt_id") or p.get("request_id") or "")
            if pid:
                conn.prompts[pid] = p.get("execution_generation", params.get("execution_generation"))
                await self._emit_approval(conn, pid, p)
        elif typ == "clarify.request":
            pid = str(p.get("prompt_id") or p.get("request_id") or "")
            if pid:
                conn.prompts[pid] = p.get("execution_generation", params.get("execution_generation"))
                await self._emit_clarify(conn, pid, p)

    async def _emit_approval(self, conn: Conn, pid: str, p: dict) -> None:
        choices = [c for c in (p.get("choices") or ["once", "deny"]) if c in ("once", "session", "always", "deny")]
        await self.emit("approval.request", conn.name, request_id=pid,
                        title=str(p.get("description") or "Allow this command?"),
                        command=str(p.get("command") or ""), choices=choices or ["once", "deny"])

    async def _emit_clarify(self, conn: Conn, pid: str, p: dict) -> None:
        fields = {"request_id": pid, "question": str(p.get("question") or "")}
        if p.get("choices"):
            fields["choices"] = [str(c) for c in p["choices"]]
        await self.emit("clarify.request", conn.name, **fields)

    # ------------------------------------------------------------ main chat

    async def _ensure_main(self, conn: Conn) -> dict:
        """Find (or create) the bot's ``Bot Chat`` and attach to it. Returns the session snapshot."""
        rows = (await self._call(conn, "session.list", title=BOT_CHAT_TITLE, include_hidden=True, limit=5)).get("sessions") or []
        if rows:
            stored = rows[0].get("resolved_id") or rows[0]["id"]
            snap = await self._call(conn, "session.resume", session_id=stored)
            snap.setdefault("stored_session_id", stored)
        else:
            snap = await self._call(conn, "session.create", title=BOT_CHAT_TITLE, hidden=True, follow_profile_config=True)
            try:  # materialise the row now, like Hermes' own desktop, so a second open finds it
                await self._call(conn, "session.title", session_id=snap["session_id"], title=BOT_CHAT_TITLE)
            except Exception as e:
                if _named(e, "GatewayClientError") and not _named(e, "GatewayRPCError"):
                    raise
                log.debug("session.title after create failed: %s", e)
        conn.main_id = snap["session_id"]
        conn.main_stored = snap.get("stored_session_id") or conn.main_id
        if snap.get("execution_generation") is not None:
            conn.generation = snap["execution_generation"]
        return snap

    async def _main(self, conn: Conn) -> str:
        if not conn.main_id:
            await self._ensure_main(conn)
        return conn.main_id

    async def op_chat_open(self, p) -> Reply:
        conn = await self._conn(p.get("bot"))
        snap = await self._ensure_main(conn)
        info = snap.get("info") if isinstance(snap.get("info"), dict) else {}
        bot = conn.bot
        running = bool(snap.get("running") if snap.get("running") is not None else info.get("running"))
        conn.in_turn = running
        result = {"session_id": conn.main_id, "messages": chat_messages(snap.get("messages")), "running": running,
                  "model": str(info.get("model") or bot["model"]), "provider": str(info.get("provider") or bot["provider"]),
                  "reasoning": str(info.get("reasoning_effort") or bot["reasoning"])}
        prompts = [x for x in (snap.get("prompts") or []) if isinstance(x, dict) and x.get("prompt_id")]

        async def replay():  # prompts still waiting on the person
            for x in prompts:
                pid = str(x["prompt_id"])
                conn.prompts[pid] = x.get("execution_generation")
                await (self._emit_clarify if x.get("kind") == "clarify" else self._emit_approval)(conn, pid, x)
        return Reply(result, replay if prompts else None)

    async def op_chat_send(self, p) -> dict:
        text = p.get("text")
        if not isinstance(text, str) or not text.strip():
            raise BridgeError("bad_request", "missing text")
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)
        input_id = str(uuid.uuid4())
        await self._submit(conn, main, text, input_id)
        return {"input_id": input_id}

    async def _submit(self, conn: Conn, main_id: str, text: str, input_id: str):
        # The single place a turn is sent. It takes the main chat id and nothing else.
        return await self._call(conn, "prompt.submit", session_id=main_id, text=text, input_id=input_id)

    async def _generation(self, conn: Conn, main: str):
        if conn.generation is None:
            snap = await self._call(conn, "session.resume", session_id=main)
            conn.generation = snap.get("execution_generation")
        return conn.generation if conn.generation is not None else 0

    async def op_chat_interrupt(self, p) -> dict:
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)
        await self._call(conn, "session.interrupt", session_id=main, execution_generation=await self._generation(conn, main))
        return {}

    async def op_approval_respond(self, p) -> dict:
        choice, rid = p.get("choice"), p.get("request_id")
        if choice not in ("once", "session", "always", "deny") or not isinstance(rid, str) or not rid:
            raise BridgeError("bad_request", "need request_id and choice once|session|always|deny")
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)
        gen = conn.prompts.pop(rid, None)
        await self._call(conn, "approval.respond", session_id=main, prompt_id=rid, choice=choice,
                         execution_generation=gen if gen is not None else await self._generation(conn, main))
        return {}

    async def op_clarify_respond(self, p) -> dict:
        answer, rid = p.get("answer"), p.get("request_id")
        if not isinstance(answer, str) or not isinstance(rid, str) or not rid:
            raise BridgeError("bad_request", "need request_id and answer")
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)
        gen = conn.prompts.pop(rid, None)
        await self._call(conn, "clarify.respond", session_id=main, prompt_id=rid, answer=answer,
                         execution_generation=gen if gen is not None else await self._generation(conn, main))
        return {}

    # ------------------------------------------------------------ models

    async def op_models_options(self, p) -> dict:
        conn = await self._conn(p.get("bot"))
        res = await self._call(conn, "model.options")
        providers = []
        for pr in res.get("providers") or []:
            models = [m if isinstance(m, str) else str(m.get("id") or m.get("name") or "") for m in pr.get("models") or []]
            providers.append({"slug": str(pr.get("slug") or ""), "name": str(pr.get("name") or pr.get("slug") or ""),
                              "models": [m for m in models if m]})
        reasoning = conn.bot["reasoning"]
        if conn.main_id:
            with contextlib.suppress(Exception):
                snap = await self._call(conn, "session.resume", session_id=conn.main_id)
                reasoning = str((snap.get("info") or {}).get("reasoning_effort") or reasoning)
        return {"providers": providers,
                "current": {"model": str(res.get("model") or conn.bot["model"]),
                            "provider": str(res.get("provider") or conn.bot["provider"]), "reasoning": reasoning},
                "reasoning_levels": list(REASONING_LEVELS)}

    async def op_set_model(self, p) -> dict:
        model, provider, reasoning = p.get("model"), p.get("provider"), p.get("reasoning")
        for k, v in (("model", model), ("provider", provider), ("reasoning", reasoning)):
            if v is not None and (not isinstance(v, str) or not v.strip()):
                raise BridgeError("bad_request", f"{k} must be a non-empty string")
        if model is None and reasoning is None:
            raise BridgeError("bad_request", "need model or reasoning")
        if provider is not None and model is None:
            raise BridgeError("bad_request", "provider needs a model")
        if reasoning is not None and reasoning not in REASONING_LEVELS:
            raise BridgeError("bad_request", f"unknown reasoning level {reasoning}")
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)

        async def mutate(operation: str, payload: dict):
            snap = await self._call(conn, "session.resume", session_id=main)  # fresh revision + generation
            return await self._call(conn, "session.mutate", session_id=main, request_id=uuid.uuid4().hex,
                                    expected_revision=snap.get("revision", 0),
                                    expected_generation=snap.get("execution_generation", 0),
                                    operation=operation, payload=payload) or {}
        if model is not None:
            res = await mutate("model", {"model": model, **({"provider": provider} if provider else {})})
            if res.get("status") == "confirmation_required":
                raise BridgeError("confirmation_required", str(res.get("confirm_message") or "this model needs a confirmation"))
        if reasoning is not None:
            await mutate("reasoning", {"effort": reasoning})
        snap = await self._call(conn, "session.resume", session_id=main)
        info = snap.get("info") or {}
        return {"model": str(info.get("model") or ""), "provider": str(info.get("provider") or conn.bot["provider"]),
                "reasoning": str(info.get("reasoning_effort") or "")}

    # ------------------------------------------------------------ bots / hello / routines

    async def op_hello(self, p) -> dict:
        hermes = {"home": str(self.home)}
        with contextlib.suppress(Exception):
            import hermes_cli
            hermes["version"] = str(hermes_cli.__version__)
        return {"bridge": "real", "version": VERSION, "hermes": hermes}

    async def op_bots_list(self, p) -> dict:
        live = {}
        for conn in self.conns.values():
            if conn.connected:
                with contextlib.suppress(Exception):
                    res = await conn.call("profiles.list", include_sessions=False)
                    live = {r.get("name"): r for r in res.get("profiles") or [] if isinstance(r, dict)}
                break
        bots = []
        for b in discover_bots(self.home):
            conn = self.conns.get(b["name"])
            row = live.get(b["name"]) or {}
            status = "online" if conn and conn.connected else "starting" if conn and conn.connecting else "offline"
            bots.append({"name": b["name"], "display_name": str(row.get("display_name") or b["display_name"]),
                         "is_default": b["is_default"], "model": str(row.get("model") or b["model"]),
                         "provider": str(row.get("provider") or b["provider"]),
                         "description": str(row.get("description") or b["description"]),
                         "status": status, "running": bool(conn and conn.in_turn)})
        return {"bots": bots}

    async def op_routines_list(self, p) -> dict:
        return {"routines": read_routines(self._bot(p.get("bot"))["path"])}

    def poll_routines(self) -> list[tuple[str, dict]]:
        """Compare each profile's cron/jobs.json to the last look; returns (bot, job) for each new run."""
        ran = []
        for b in discover_bots(self.home):
            path = b["path"] / "cron" / "jobs.json"
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                continue
            st = self._routine_state.get(b["name"])
            if st is not None and st["mtime"] == mtime:
                continue
            jobs = read_routines(b["path"])
            last = {j["id"]: j["last_run_at"] for j in jobs}
            if st is not None:
                ran += [(b["name"], j) for j in jobs if j["last_run_at"] and st["last"].get(j["id"]) != j["last_run_at"]]
            self._routine_state[b["name"]] = {"mtime": mtime, "last": last}
        return ran

    async def poll_routines_once(self) -> int:
        ran = self.poll_routines()
        for bot, j in ran:
            await self.emit("routine.ran", bot, routine_id=j["id"], name=j["name"],
                            status=str(j["last_status"] or "ok"), ts=_to_ts(j["last_run_at"]))
        return len(ran)

    async def poll_elsewhere_once(self) -> None:
        for conn in list(self.conns.values()):
            if not conn.connected:
                continue
            try:
                sig = [(a["id"], a["running"], a["message_count"]) for a in await self._elsewhere(conn)]
            except Exception:
                continue
            if conn.elsewhere_sig is not None and sig != conn.elsewhere_sig:
                await self.emit("elsewhere.update", conn.name)
            conn.elsewhere_sig = sig

    async def _watch(self) -> None:
        self.poll_routines()  # baseline: nothing that already ran is announced
        last_else = self.clock()
        while True:
            await asyncio.sleep(self.poll_s)
            with contextlib.suppress(Exception):
                await self.poll_routines_once()
            if self.clock() - last_else >= self.elsewhere_poll_s:
                last_else = self.clock()
                with contextlib.suppress(Exception):
                    await self.poll_elsewhere_once()

    # ------------------------------------------------------------ elsewhere (read only)

    async def _list(self, conn: Conn, **params) -> list[dict]:
        try:
            res = await self._call(conn, "session.list", **params)
        except Exception as e:
            if "scope" in params and _named(e, "GatewayRPCError"):  # a gateway without scope
                params.pop("scope")
                res = await self._call(conn, "session.list", **params)
            else:
                raise
        return [r for r in res.get("sessions") or [] if isinstance(r, dict) and r.get("id")]

    async def _elsewhere(self, conn: Conn) -> list[dict]:
        stored, live, active = await asyncio.gather(
            self._list(conn, limit=60, scope="stored"), self._list(conn, limit=60),
            self._call(conn, "session.active_list"), return_exceptions=True)
        if isinstance(stored, BaseException):
            raise stored
        live = [] if isinstance(live, BaseException) else live
        active = [] if isinstance(active, BaseException) else [r for r in active.get("sessions") or [] if isinstance(r, dict)]
        merged: dict[str, dict] = {}
        for r in stored + live:
            m = merged.setdefault(r["id"], {})
            m.update({k: v for k, v in r.items() if v is not None})
            m["running"] = bool(m.get("running")) or bool(r.get("running"))
        for r in active:
            if r.get("id"):
                m = merged.setdefault(r["id"], {})
                for k in ("title", "source", "started_at", "message_count"):
                    m.setdefault(k, r.get(k))
                m["last_active"] = r.get("last_active") or m.get("last_active")
                m["running"] = bool(m.get("running")) or r.get("status") in ("streaming",)
        out = []
        for sid, r in merged.items():
            source = str(r.get("source") or "").lower()
            title = str(r.get("title") or "").strip()
            if source in LOCAL_SOURCES or sid in conn.main_ids or title == BOT_CHAT_TITLE:
                continue
            started = float(r.get("started_at") or 0.0)
            out.append({"id": sid, "source": source, "title": title,
                        "label": title or f"{source.capitalize() or 'Other'} session", "started_at": started,
                        "last_active": float(r.get("last_active") or started),
                        "message_count": int(r.get("message_count") or 0), "running": bool(r.get("running"))})
        out.sort(key=lambda a: a["last_active"], reverse=True)
        return out[:MAX_ELSEWHERE]

    async def op_elsewhere_list(self, p) -> dict:
        conn = await self._conn(p.get("bot"))
        return {"sessions": await self._elsewhere(conn)}

    async def op_elsewhere_peek(self, p) -> dict:
        sid = p.get("session_id")
        if not isinstance(sid, str) or not sid:
            raise BridgeError("bad_request", "missing session_id")
        limit = p.get("limit", 4)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise BridgeError("bad_request", "limit must be 1..50")
        conn = await self._conn(p.get("bot"))
        res = await self._call(conn, "session.history", session_id=sid)  # read only: never resumed
        rows = []
        for r in res.get("messages") or []:
            if not isinstance(r, dict) or r.get("role") not in ("user", "assistant") or r.get("display_kind") == "hidden":
                continue
            text = _row_text(r)
            if not text.strip():
                continue
            author, text = split_author(text) if r["role"] == "user" else (None, text)
            m = {"role": r["role"], "text": _clip(text), "ts": float(r.get("timestamp") or 0.0)}
            if author:
                m["author"] = author
            rows.append(m)
        return {"messages": rows[-limit:], "total": len(rows)}


# ---------------------------------------------------------------- entry point

def _watch_stdin(loop, stop: asyncio.Event) -> None:
    def run():
        try:
            while os.read(0, 4096):
                pass
        except OSError:
            pass
        loop.call_soon_threadsafe(stop.set)
    threading.Thread(target=run, daemon=True, name="stdin-eof").start()


async def amain(args) -> int:
    bridge = Bridge(token=args.token, hermes_home=Path(args.hermes_home) if args.hermes_home else None, eager=args.eager)
    port = await bridge.start("127.0.0.1", args.port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    if args.exit_on_stdin_eof:
        _watch_stdin(loop, stop)
    print("OMHER_BRIDGE_READY " + json.dumps({"port": port}), flush=True)
    await stop.wait()
    await bridge.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="omher local bridge")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--token", default=os.environ.get("OMHER_BRIDGE_TOKEN", ""))
    ap.add_argument("--hermes-home", default="")
    ap.add_argument("--hermes-root", default="")
    ap.add_argument("--eager", action="store_true")
    ap.add_argument("--exit-on-stdin-eof", action="store_true")
    args = ap.parse_args(argv)
    if not args.token:
        ap.error("--token is required")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="omher-bridge %(levelname)s %(message)s")
    root = Path(args.hermes_root) if args.hermes_root else DEFAULT_HERMES_ROOT
    ensure_hermes_on_path(root)
    return asyncio.run(amain(args))


def ensure_hermes_on_path(root: Path, path: list | None = None) -> None:
    """Put the Hermes checkout on sys.path even when `hermes_cli` already imports.

    Hermes' venv installs `hermes_cli` as a package but not its top-level helper modules
    (`hermes_dir_acl`, `hermes_constants`, …) that starting a gateway imports. Checking only
    `import hermes_cli` therefore passed and every profile whose gateway was not already
    running failed with `No module named 'hermes_dir_acl'`.
    """
    path = sys.path if path is None else path
    if root.is_dir() and str(root) not in path:
        path.insert(0, str(root))


if __name__ == "__main__":
    sys.exit(main())
