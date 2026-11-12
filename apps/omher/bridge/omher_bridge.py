#!/usr/bin/env python3
"""omher bridge: the UI protocol (01-protocol.md) on a loopback WebSocket, backed by each Hermes
profile's own gateway through Hermes' ``connect_gateway``.

    python omher_bridge.py --port 0 --token <t> [--exit-on-stdin-eof] [--eager]
                           [--hermes-home DIR] [--hermes-root DIR]

Prints one line ``OMHER_BRIDGE_READY {"port": N}`` on stdout once listening; everything else goes
to stderr. Binds 127.0.0.1 only and refuses (403) any connection whose ``token`` query parameter
differs. Makes no model or network call of its own; the one outside read is a PR's state through the
person's own `gh` (``runs.prs``).

Boundary rules the code keeps:
* One gateway connection per profile, opened lazily (``--eager`` opens them all at start).
* The only sessions this bridge ever resumes, creates, submits to, interrupts or answers are the
  bot's main chat (the session titled ``Bot Chat``) and the folder chats it created itself for an
  oh-my-hermes SESSIONS entry (``folder.open``; closed with ``folder.close``). Every other session is
  only listed or read (list / history), never attached.
  Files the person attaches go to the main chat only.
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
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

VERSION = "0.2.5"
BOT_CHAT_TITLE = "Bot Chat"
FOLDER_CHAT_PREFIX = "omher · "
MAX_FOLDER_CHATS = 16
LOCAL_SOURCES = frozenset({"tui", "cli", "local", "desktop", "acp", "api_server", "omher"})
REASONING_LEVELS = ["none", "low", "medium", "high", "xhigh"]
RUNNING_STATUSES = frozenset({"working", "streaming", "waiting", "starting"})
MAX_ELSEWHERE = 20
MAX_OPEN_MESSAGES = 200
PEEK_CHARS = 400
THINKING_MIN_GAP = 1.0
CONNECT_TIMEOUT = 60.0
OFFLINE_COOLDOWN = 10.0
# chat.attach: one 100 MB file arrives base64'd in one frame; Hermes' own attach calls cap images (25 MB) and
# PDFs (50 MB) lower and say so. pdf.attach renders pages, so it gets more than the default RPC deadline.
ATTACH_B64_MAX = (100 * 1024 * 1024 + 2) // 3 * 4
UI_FRAME_MAX = ATTACH_B64_MAX + 64 * 1024
ATTACH_TIMEOUT = 180.0
# The only actions omher sends to Hermes' own `cron.manage` and `plugins.manage` (BOUNDARY rules 24 and 25).
CRON_ACTIONS = frozenset({"add", "pause", "resume", "remove"})
PLUGIN_ACTIONS = frozenset({"list", "toggle", "inspect", "install", "update", "remove"})
JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
PLUGIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")  # an installed plugin's name or key (`image_gen/fal`)
# A curated catalog entry's name: no `/` or `:`, so neither a Git URL nor `owner/repo` can pass as one.
CATALOG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
def default_hermes_home(environ=None, platform: str | None = None) -> Path:
    """Hermes' own default home: `HERMES_HOME`, else `~/.hermes`, or `%LOCALAPPDATA%\\hermes` on Windows
    (the same rule as Hermes' `hermes_constants`, kept here so the bridge needs no Hermes import to start)."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    explicit = (environ.get("HERMES_HOME") or "").strip()
    if explicit:
        return hermes_root_of(Path(os.path.expanduser(explicit)))
    if platform == "win32":
        local = (environ.get("LOCALAPPDATA") or "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "hermes"
    return Path.home() / ".hermes"


def hermes_root_of(home: Path) -> Path:
    """Hermes runs a profile with `HERMES_HOME=<root>/profiles/<name>`. omher shows every bot, so a home that is
    a profile dir (its parent is `profiles` and the root above holds its own config) resolves to that root."""
    parent = home.parent
    if parent.name == "profiles" and (parent.parent / "config.yaml").is_file():
        return parent.parent
    return home


def _default_hermes_root() -> Path:
    """The Hermes checkout whose venv runs this bridge (`<root>/venv/bin/python`, or `venv\\Scripts\\python.exe`
    on Windows), else `<Hermes home>/hermes-agent`."""
    exe = Path(sys.executable)
    for venv in (exe.parent.parent,):
        if venv.name in ("venv", ".venv") and (venv.parent / "hermes_cli").is_dir():
            return venv.parent
    return default_hermes_home() / "hermes-agent"


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

_YAML_CACHE: dict[str, tuple[int, int, dict]] = {}


def _load_yaml(path: Path) -> dict:
    """The parsed mapping in *path*, or {}. Parsed once per (path, mtime_ns, size): every op calls
    discover_bots on the event loop, and a full config.yaml parse costs ~5 ms with the pure-Python loader.
    The result is shared; callers that change it copy it first."""
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        _YAML_CACHE.pop(key, None)
        return {}
    hit = _YAML_CACHE.get(key)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        import yaml  # Hermes' own dependency; absent only outside its venv
        loader = getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=loader)  # noqa: S506 - a safe loader
        data = data if isinstance(data, dict) else {}
    except Exception:
        data = {}
    _YAML_CACHE[key] = (st.st_mtime_ns, st.st_size, data)
    return data


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


AVATAR_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
AVATAR_MAX = 2_000_000
NAME_MAX = 64


def read_avatar(profile_dir: Path) -> tuple[int | None, str | None]:
    """(revision, data URL) of the profile's avatar, the file Hermes keeps at ``assets/avatar.<ext>``
    (its desktop app reads the same one). (None, None) when the bot has no picture of its own."""
    import base64
    for ext, mime in AVATAR_TYPES.items():
        path = profile_dir / "assets" / f"avatar.{ext}"
        try:
            st = path.stat()
            if st.st_size > AVATAR_MAX:
                continue
            blob = path.read_bytes()
        except OSError:
            continue
        return st.st_mtime_ns, f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"
    return None, None


_AVATAR_MAGIC = {"png": [(0, 8, b"\x89PNG\r\n\x1a\n")], "jpg": [(0, 3, b"\xff\xd8\xff")],
                 "webp": [(0, 4, b"RIFF"), (8, 12, b"WEBP")]}


def write_avatar(profile_dir: Path, data: str | None) -> None:
    """``assets/avatar.<ext>`` exactly as Hermes' ``profiles.set_asset`` writes it (format sniffed,
    2 MB cap, one file, atomic), for when the bot's gateway is not running. ``None`` clears it."""
    import base64
    assets = profile_dir / "assets"
    if data is not None:
        m = re.match(r"^data:image/[a-z+.-]+;base64,(.*)$", data, re.DOTALL)
        try:
            blob = base64.b64decode(m.group(1) if m else "", validate=True)
        except ValueError:
            raise BridgeError("bad_request", "picture is not valid base64")
        if len(blob) > AVATAR_MAX:
            raise BridgeError("bad_request", "picture is larger than 2 MB")
        ext = next((e for e, mg in _AVATAR_MAGIC.items() if all(blob[a:b] == x for a, b, x in mg)), None)
        if ext is None:
            raise BridgeError("bad_request", "use a PNG, JPEG or WebP picture")
    for e in AVATAR_TYPES:
        with contextlib.suppress(FileNotFoundError):
            (assets / f"avatar.{e}").unlink()
    if data is None:
        return
    assets.mkdir(parents=True, exist_ok=True)
    tmp = assets / f"avatar.{ext}.tmp"
    tmp.write_bytes(blob)
    tmp.replace(assets / f"avatar.{ext}")


def avatar_rev(profile_dir: Path) -> int | None:
    for ext in AVATAR_TYPES:
        with contextlib.suppress(OSError):
            return (profile_dir / "assets" / f"avatar.{ext}").stat().st_mtime_ns
    return None


def clean_display_name(raw) -> str:
    if not isinstance(raw, str):
        raise BridgeError("bad_request", "name must be text")
    name = " ".join(raw.split())
    if len(name) > NAME_MAX:
        raise BridgeError("bad_request", f"name is too long ({len(name)} characters, max {NAME_MAX})")
    return name


def write_display_name(profile_dir: Path, name: str) -> None:
    """Set (or clear, with "") the profile's display name in ``profile.yaml``. Only the name apps show
    changes: the profile id, its folder and every session stay as they are. Uses Hermes' own writer when
    the bridge runs on Hermes' venv; the fallback writes the same key the same way."""
    try:
        from hermes_cli.profiles import write_profile_meta
        write_profile_meta(profile_dir, display_name=name)
        return
    except ImportError:
        pass  # Hermes' writer (or its lazy `utils` import) is not reachable: it failed before writing anything
    import yaml
    path = profile_dir / "profile.yaml"
    data = dict(_load_yaml(path))  # a copy: the parsed mapping is cached and shared
    if name:
        data["display_name"] = name
    else:
        data.pop("display_name", None)
    tmp = path.with_name(f".profile.yaml.{uuid.uuid4().hex}.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(path)


def ro_uri(db: Path) -> str:
    """A read-only SQLite URI for *db* on every platform. `Path.as_uri()` gives `file:///C:/...` on Windows
    and percent-escapes `?`, `#`, `%` and spaces, which a hand-built `file:{path}` mangles (a drive letter or
    a `#` in a folder name ended the path early)."""
    return Path(db).resolve().as_uri() + "?mode=ro"


# ---------------------------------------------------------------- side panel (read-only)

PANEL_RUNS = 40          # terminal runs shown in the Terminal tab
PANEL_WINDOW = 8000      # newest message rows scanned (keeps the read fast on a large state.db)
PANEL_OUT = 600          # chars of output kept per run (head and tail), clipped before the reply is encoded
DIFF_MAX = 60_000        # chars of patch sent to the UI
UNTRACKED_MAX = 200      # untracked entries listed in the Diff tab
GIT_TIMEOUT = 4.0
WORKTREES_TTL = 10.0     # seconds a scan of the bot's worktrees is reused by panel.diff
GIT_POOL = 4             # git status calls run at once during a scan
# The only git commands omher runs. All are reads; `--no-optional-locks` keeps `status` from writing the index.
# `version` and the one fixed `config --list` query (_FILTER_QUERY) only feed the hardening in _git.
GIT_READS = {("worktree", "list"), ("rev-parse",), ("status",), ("diff",), ("log",), ("version",), ("config",)}
# A repository's own config and attributes can name programs git runs during a read (core.fsmonitor, a
# filter's clean/process command, a diff textconv or external driver, gpg.program for signed commits,
# git inside a submodule). _git turns each of those off; see _hardened.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_FILTER_QUERY = ["config", "--list", "--null", "--name-only"]
_ATTR_SOURCE: list[bool] = []  # cached: does this git know --attr-source (git >= 2.40)?


def _json_obj(raw):
    try:
        v = json.loads(raw) if isinstance(raw, str) and raw else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def read_terminal_runs(profile_dir: Path, limit: int = PANEL_RUNS) -> list[dict]:
    """The bot's latest terminal commands with their output, newest first, from state.db (read-only):
    the command from the assistant's tool call, the output/exit code/cwd from the tool's result row."""
    import sqlite3
    db = profile_dir / "state.db"
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect(ro_uri(db), uri=True, timeout=1.0)
        try:
            top = con.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0
            lo = max(0, top - PANEL_WINDOW)
            results = con.execute(
                "SELECT m.tool_call_id, m.content, m.timestamp, m.session_id, s.source FROM messages m"
                " LEFT JOIN sessions s ON s.id = m.session_id"
                " WHERE m.id > ? AND m.role = 'tool' AND m.tool_name = 'terminal' ORDER BY m.id DESC LIMIT ?",
                (lo, limit)).fetchall()
            calls = con.execute(
                "SELECT tool_calls FROM messages WHERE id > ? AND role = 'assistant' AND tool_calls LIKE ?",
                (lo, '%"terminal"%')).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    commands: dict[str, dict] = {}
    for (raw,) in calls:
        try:
            items = json.loads(raw) if raw else []
        except ValueError:
            continue
        for c in items if isinstance(items, list) else []:
            fn = c.get("function") if isinstance(c, dict) else None
            if not isinstance(fn, dict) or fn.get("name") != "terminal":
                continue
            args = _json_obj(fn.get("arguments")) or {}
            for key in (c.get("id"), c.get("call_id")):
                if key:
                    commands[str(key)] = args
    runs = []
    for call_id, content, ts, sid, source in results:
        args = commands.get(str(call_id)) or {}
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        res = _json_obj(content) or {}
        out = res.get("output") if isinstance(res.get("output"), str) else (content if isinstance(content, str) else "")
        out = _head_tail(out.rstrip(), PANEL_OUT)
        cwd = res.get("cwd") or args.get("workdir") or ""
        runs.append({"id": str(call_id), "command": command.strip(), "ts": float(ts or 0.0), "output": out,
                     "exit_code": res.get("exit_code") if isinstance(res.get("exit_code"), int) else None,
                     "cwd": str(cwd) if isinstance(cwd, str) else "", "source": str(source or ""),
                     "session_id": str(sid or "")})
    return runs


def _head_tail(text: str, limit: int) -> str:
    """At most `limit` chars: the head and the tail (where a failure usually says why), joined by an ellipsis."""
    if len(text) <= limit:
        return text
    head = limit * 3 // 5
    return text[:head] + "\n…\n" + text[-(limit - head - 3):]


def _git(args: list[str], cwd: str | Path, timeout: float = GIT_TIMEOUT, hardened: list[str] | None = None) -> str | None:
    """Run one read-only git command; None on any failure. Only GIT_READS commands are allowed, and every
    call carries the flags that keep the repository's config from running programs (see _hardened; a
    caller making several reads of one folder in a row may pass its result once)."""
    head = tuple(args[:2]) if args[:1] == ["worktree"] else (args[0],)
    if head not in GIT_READS or (head == ("config",) and args != _FILTER_QUERY):
        raise ValueError(f"not a read-only git command: {args[:2]}")
    pre = ["--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.quotepath=off",
           "-c", "core.attributesFile=/dev/null"]  # Git for Windows maps /dev/null to NUL
    if head in (("status",), ("diff",), ("log",)):
        extra = _hardened(cwd, timeout) if hardened is None else hardened
        if extra is None:
            return None
        pre += extra
    if head in (("diff",), ("log",)):  # no diff driver, textconv or signature program, whatever the caller passed
        safe = ["--no-ext-diff", "--no-textconv"] + (["--no-show-signature"] if head == ("log",) else [])
        args = [args[0], *safe, *args[1:]]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(["git", *pre, *args], cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                           env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
                                "GIT_ATTR_NOSYSTEM": "1"}, **kw)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _hardened(cwd: str | Path, timeout: float) -> list[str] | None:
    """Extra global flags for a read that looks at file contents (status, diff, log): the in-tree
    .gitattributes ignored (--attr-source=<empty tree>, git >= 2.40), and every filter driver the
    repository's config defines emptied, which also covers drivers named from .git/info/attributes (which
    --attr-source leaves on) and from .gitattributes on an older git. None refuses the read: the drivers
    could not be listed, or one has a name `-c` cannot carry."""
    if not _ATTR_SOURCE:
        m = re.search(r"(\d+)\.(\d+)", _git(["version"], cwd, timeout) or "")
        _ATTR_SOURCE.append(bool(m) and (int(m.group(1)), int(m.group(2))) >= (2, 40))
    out = ["--attr-source=" + _EMPTY_TREE] if _ATTR_SOURCE[0] else []
    names = _git(_FILTER_QUERY, cwd, timeout)
    if names is None:
        return None
    drivers = {k[len("filter."):].rpartition(".")[0] for k in names.split("\0") if k.startswith("filter.")}
    for d in sorted(drivers):
        if not d or "=" in d or "\n" in d:
            return None
        out += ["-c", f"filter.{d}.clean=", "-c", f"filter.{d}.smudge=", "-c", f"filter.{d}.process=",
                "-c", f"filter.{d}.required=false"]
    return out


def _status_entries(status: str) -> list[tuple[str, str]]:
    """(XY, path) pairs from `git status --porcelain -z` (a rename's or copy's source entry skipped)."""
    out, parts, i = [], status.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        out.append((e[:2], e[3:]))
        if e[0] in "RC":
            i += 1
    return out


def _norm(path: str | Path) -> str:
    """One spelling per folder: symlinks resolved (macOS /var -> /private/var, a symlinked home), case
    folded where the OS ignores case."""
    return os.path.normcase(os.path.realpath(str(path)))


_WORKTREES: dict[str, tuple[float, list[dict]]] = {}  # profile dir -> (monotonic time, last scan)
_WORKTREES_LOCK = threading.Lock()


def cached_worktrees(profile_dir: Path, max_age: float = WORKTREES_TTL) -> list[dict]:
    """The bot's last worktree scan when it is under `max_age` seconds old, else a fresh scan."""
    with _WORKTREES_LOCK:
        hit = _WORKTREES.get(str(profile_dir))
    if hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    return read_worktrees(profile_dir)


def read_worktrees(profile_dir: Path, runs: list[dict] | None = None, max_repos: int = 6) -> list[dict]:
    """Git worktrees of the repositories the bot worked in, found from the folders its terminal runs used.
    Each: path, branch, head, dirty (changed files), last (newest run there), repo. Newest first.
    A scan from the bot's own runs is kept for cached_worktrees()."""
    scan = runs is None
    runs = read_terminal_runs(profile_dir, limit=400) if runs is None else runs
    seen_at: dict[str, float] = {}
    for r in runs:
        cwd = r.get("cwd") or ""
        if cwd:
            seen_at[cwd] = max(seen_at.get(cwd, 0.0), float(r.get("ts") or 0.0))
    seen_at = {c: t for c, t in seen_at.items() if os.path.isdir(c)}
    norm: dict[str, str] = {}

    def nm(path: str) -> str:
        if path not in norm:
            norm[path] = _norm(path)
        return norm[path]

    def under(cwd: str, wt: str) -> bool:
        """cwd is the worktree or a folder in it that is not inside a nested repository."""
        c, root = nm(cwd), nm(wt).rstrip(os.sep)
        if c == root:
            return True
        if not c.startswith(root + os.sep):
            return False
        d = c
        while d != root:
            if os.path.lexists(os.path.join(d, ".git")):
                return False
            d = os.path.dirname(d)
        return True

    repos: dict[str, dict] = {}
    for cwd, ts in sorted(seen_at.items(), key=lambda kv: -kv[1]):
        known = [w for rp in repos.values() for w in rp["worktrees"] if under(cwd, w["path"])]
        if known:
            # already inside a listed worktree: no rev-parse needed (the deepest one owns the folder)
            w = max(known, key=lambda w: len(nm(w["path"])))
            w["last"] = max(w["last"], ts)
            continue
        if len(repos) >= max_repos:
            continue
        common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
        if not common:
            continue
        key = _norm(common.strip())
        if key not in repos:
            listing = _git(["worktree", "list", "--porcelain"], cwd) or ""
            wts, cur = [], {}
            for line in listing.splitlines() + [""]:
                if not line.strip():
                    if cur.get("path"):
                        wts.append(cur)
                    cur = {}
                elif line.startswith("worktree "):
                    cur = {"path": line[9:], "branch": "", "head": "", "last": 0.0, "dirty": None}
                elif line.startswith("HEAD "):
                    cur["head"] = line[5:][:9]
                elif line.startswith("branch "):
                    cur["branch"] = line[7:].removeprefix("refs/heads/")
                elif line == "detached":
                    cur["branch"] = ""
            main = Path(common.strip()).parent
            repos[key] = {"repo": main.name, "worktrees": [w for w in wts if os.path.isdir(w["path"])]}
        owners = [w for w in repos[key]["worktrees"] if under(cwd, w["path"])]
        if owners:
            w = max(owners, key=lambda w: len(nm(w["path"])))
            w["last"] = max(w["last"], ts)
    out = [{**w, "repo": rp["repo"]} for rp in repos.values() for w in rp["worktrees"] if w["last"] > 0]
    out.sort(key=lambda w: -w["last"])
    out = out[:30]

    def dirty(w: dict) -> int | None:
        status = _git(["status", "--porcelain", "-z", "--ignore-submodules=all"], w["path"])
        return None if status is None else len(_status_entries(status))

    if out:
        with ThreadPoolExecutor(max_workers=min(GIT_POOL, len(out))) as pool:
            for w, n in zip(out, pool.map(dirty, out)):
                w["dirty"] = n
    if scan:
        with _WORKTREES_LOCK:
            _WORKTREES[str(profile_dir)] = (time.monotonic(), out)
    return out


_DIFF_FILE = re.compile(r'^diff --git (?:"a/.*"|a/.+?) (?:"b/(?P<q>.*)"|b/(?P<p>.+))$')
_DIFF_FLAGS = ["--no-color", "--ignore-submodules=all"]
_C_ESC = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", '"': '"', "\\": "\\"}


def _unquote(s: str) -> str:
    """Undo git's C-style quoting of a path (with core.quotepath=off only controls, quotes and backslashes)."""
    raw, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in "0123" and re.fullmatch(r"[0-7]{3}", s[i + 1:i + 4]):
                raw.append(int(s[i + 1:i + 4], 8))
                i += 4
                continue
            raw += _C_ESC.get(n, n).encode()
            i += 2
            continue
        raw += c.encode()
        i += 1
    return raw.decode("utf-8", "replace")


def read_diff(profile_dir: Path, path: str, runs: list[dict] | None = None) -> dict:
    """Uncommitted changes (vs HEAD) of one worktree the bot worked in, or its last commit when clean.
    Untracked files are listed by name (`untracked: true`, no content). `path` must be one of the bot's
    worktrees (the scan cached_worktrees() keeps, or one over `runs`); anything else is refused."""
    trees = cached_worktrees(profile_dir) if runs is None else read_worktrees(profile_dir, runs)
    w = next((t for t in trees if _norm(t["path"]) == _norm(path or "")), None)
    if not w and runs is None:  # a worktree newer than the kept scan
        w = next((t for t in read_worktrees(profile_dir) if _norm(t["path"]) == _norm(path or "")), None)
    if not w:
        raise BridgeError("not_found", "not a worktree this bot worked in")
    hard = _hardened(w["path"], GIT_TIMEOUT)
    if hard is None:
        raise BridgeError("unavailable", "git could not read this worktree")
    with ThreadPoolExecutor(max_workers=2) as pool:
        patch_f = pool.submit(_git, ["diff", "HEAD", *_DIFF_FLAGS], w["path"], 8.0, hard)
        status = _git(["status", "--porcelain", "-z", "--ignore-submodules=all"], w["path"], GIT_TIMEOUT, hard) or ""
        patch = patch_f.result()
    untracked = [p for xy, p in _status_entries(status) if xy == "??"]
    scope = "uncommitted"
    if patch is not None and not patch.strip() and not untracked:
        patch = _git(["log", "-1", "--format=%h %s", "--patch", *_DIFF_FLAGS], w["path"], 8.0, hard)
        scope = "last commit"
    if patch is None:
        raise BridgeError("unavailable", "git could not read this worktree")
    files, cur = [], None
    for line in patch.splitlines():
        m = _DIFF_FILE.match(line)
        if m:
            cur = {"path": _unquote(m.group("q")) if m.group("q") is not None else m.group("p"), "add": 0, "del": 0}
            files.append(cur)
        elif cur is not None and line.startswith("+") and not line.startswith("+++"):
            cur["add"] += 1
        elif cur is not None and line.startswith("-") and not line.startswith("---"):
            cur["del"] += 1
    if scope == "uncommitted":
        files += [{"path": u, "add": 0, "del": 0, "untracked": True} for u in untracked[:UNTRACKED_MAX]]
    truncated = len(patch) > DIFF_MAX or len(untracked) > UNTRACKED_MAX
    return {"path": w["path"], "branch": w["branch"], "repo": w["repo"], "scope": scope, "files": files,
            "patch": patch[:DIFF_MAX], "truncated": truncated}


# ---------------------------------------------------------------- media the bot sent (read-only)

MEDIA_MAX = 25 * 1024 * 1024   # larger files come back as `too_big` and are never read
MEDIA_SCAN = 50                # newest assistant rows naming the path that are checked line by line
MEDIA_READY_PREFIX = "OMHER_MEDIA_SERVED "  # stdout line the app reads: the only paths it may open
_MEDIA_LINE = re.compile(r"^[ \t]*MEDIA:[ \t]*(.+?)[ \t]*$")
_MEDIA_PATH = re.compile(r"^(?:/|~/|[A-Za-z]:[\\/])")
_MEDIA_FENCE = re.compile(r"^[ \t]*(```|~~~)")
MEDIA_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
    "heic": "image/heic", "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm", "m4v": "video/x-m4v",
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg", "pdf": "application/pdf",
    "zip": "application/zip",
}
# The main chat by title, and every elsewhere place (what `elsewhere.list` shows); never subagent rows.
_MEDIA_SESSIONS = ("(s.title = ? OR s.source NOT IN ("
                   + ",".join("?" * (len(LOCAL_SOURCES) + 2)) + "))")


def media_paths(text: str) -> list[str]:
    """Paths named by whole `MEDIA:<path>` lines, in order (fenced code is skipped). The UI parses the same
    way (src/chat/parts/mediaLines.ts), so a path the UI shows is a path this bridge will serve."""
    out, fence = [], False
    for line in (text or "").splitlines():
        if _MEDIA_FENCE.match(line):
            fence = not fence
            continue
        m = None if fence else _MEDIA_LINE.match(line)
        if not m:
            continue
        p = m.group(1)
        if len(p) >= 2 and p[0] == p[-1] and p[0] in "`\"'":
            p = p[1:-1].strip()
        if _MEDIA_PATH.match(p):
            out.append(p)
    return out


def media_named(profile_dir: Path, path: str) -> bool:
    """True when an assistant message of the bot's main chat or one of its elsewhere sessions has a
    `MEDIA:` line naming exactly *path*. state.db is opened read-only."""
    import sqlite3
    db = profile_dir / "state.db"
    if not path or not db.is_file():
        return False
    try:
        con = sqlite3.connect(ro_uri(db), uri=True, timeout=1.0)
        try:
            rows = con.execute(
                "SELECT m.content FROM messages m JOIN sessions s ON s.id = m.session_id"
                f" WHERE m.role = 'assistant' AND instr(m.content, ?) > 0 AND {_MEDIA_SESSIONS}"
                " ORDER BY m.id DESC LIMIT ?",
                (path, BOT_CHAT_TITLE, *sorted(LOCAL_SOURCES), "subagent", "oneshot", MEDIA_SCAN)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return any(isinstance(c, str) and path in media_paths(c) for (c,) in rows)


def media_file(path: str) -> str | None:
    """The real file behind *path*, or None: not absolute, missing, a directory, or a symlink that leads
    out of its own folder."""
    p = Path(os.path.expanduser(path))
    if not p.is_absolute():
        return None
    try:
        os.lstat(p)
    except OSError:
        return None
    real = os.path.realpath(p)
    if os.path.islink(p):
        base = os.path.realpath(p.parent)
        try:
            if os.path.commonpath([base, real]) != base:
                return None
        except ValueError:  # another drive on Windows
            return None
    return real if os.path.isfile(real) else None


def read_media(profile_dir: Path, path: str, info: bool = False) -> dict:
    """`media.read`: one file the bot itself named, base64, up to MEDIA_MAX (`info`: name, type and size
    only, for a file card). Anything else is `not_found`."""
    import base64
    real = media_file(path) if media_named(profile_dir, path) else None
    if real is None:
        raise BridgeError("not_found", "not a file this bot sent")
    ext = real.rsplit(".", 1)[-1].lower() if "." in os.path.basename(real) else ""
    import mimetypes
    mime = MEDIA_TYPES.get(ext) or mimetypes.guess_type(real)[0] or "application/octet-stream"
    size = os.path.getsize(real)
    out = {"path": real, "name": os.path.basename(real), "mime": mime, "size": size}
    if size > MEDIA_MAX:
        return {**out, "too_big": True}
    if info:
        return out
    try:
        with open(real, "rb") as f:
            data = f.read(MEDIA_MAX + 1)
    except OSError:
        raise BridgeError("not_found", "could not read the file")
    if len(data) > MEDIA_MAX:  # grew since stat
        return {**out, "size": len(data), "too_big": True}
    return {**out, "size": len(data), "data_base64": base64.b64encode(data).decode("ascii")}


def read_bot_facts(profile_dir: Path) -> dict:
    """What the bot has done, for the bot page: sessions per place, first and last activity, skills
    and routines. Read from the profile's own files; ``state.db`` is opened read-only."""
    import sqlite3
    places: dict[str, int] = {}
    first = last = None
    db = profile_dir / "state.db"
    if db.is_file():
        try:
            con = sqlite3.connect(ro_uri(db), uri=True, timeout=1.0)
            try:
                for source, n, lo, hi in con.execute(
                        "SELECT source, COUNT(*), MIN(started_at), MAX(COALESCE(last_activity_at, started_at)) "
                        "FROM sessions GROUP BY source"):
                    src = str(source or "")
                    if src in ("subagent", "oneshot") or src in LOCAL_SOURCES:
                        continue
                    places[src] = int(n)
                    first = lo if first is None or (lo is not None and lo < first) else first
                    last = hi if last is None or (hi is not None and hi > last) else last
            finally:
                con.close()
        except sqlite3.Error:
            pass
    skills_dir = profile_dir / "skills"
    skills = sum(1 for _ in skills_dir.rglob("SKILL.md")) if skills_dir.is_dir() else 0
    return {"places": dict(sorted(places.items(), key=lambda kv: -kv[1])), "first_active": first,
            "last_active": last, "skills": skills, "routines": len(read_routines(profile_dir))}


# ---------------------------------------------------------------- skills (read-only, the composer's ./ picker)

SKILL_HEAD_MAX = 8 * 1024     # bytes read from the top of a SKILL.md: its frontmatter, nothing past it
SKILL_DESC_MAX = 120
# Folders Hermes' own skill scan skips (agent/skill_utils.py EXCLUDED_SKILL_DIRS), plus every hidden folder,
# and a skill's support folders (only below a folder that has its own SKILL.md).
SKILL_SKIP_DIRS = frozenset(("venv", "node_modules", "site-packages", "__pycache__"))
SKILL_SUPPORT_DIRS = frozenset(("references", "templates", "assets", "scripts"))
# Hermes' `/command` key for a skill name (agent/skill_commands.py slugify_skill_name).
_SKILL_INVALID_CHARS = re.compile(r"[^\w-]")
_SKILL_MULTI_HYPHEN = re.compile(r"-{2,}")


def skill_slug(name: str) -> str:
    """The name Hermes registers as `/<slug>`: lower case, spaces and `_` to `-`, other marks dropped."""
    cmd = _SKILL_INVALID_CHARS.sub("", name.lower().replace(" ", "-").replace("_", "-"))
    return _SKILL_MULTI_HYPHEN.sub("-", cmd).strip("-")


def _frontmatter_value(lines: list[str], key: str) -> str:
    """One top-level `key:` of a YAML frontmatter, as one line of text: a quoted value unquoted, a folded or
    literal block (`>`, `|`) or a value on the next lines read as its first line. No YAML library."""
    for i, line in enumerate(lines):
        if not line.startswith(f"{key}:"):
            continue
        value = line[len(key) + 1:].strip()
        if value[:1] == '"':
            m = re.match(r'"((?:[^"\\]|\\.)*)"', value)
            if not m:
                return value[1:].strip()
            try:
                return str(json.loads(f'"{m.group(1)}"'))
            except ValueError:
                return m.group(1)
        if value[:1] == "'":
            m = re.match(r"'((?:[^']|'')*)'", value)
            return m.group(1).replace("''", "'") if m else value[1:].strip()
        value = re.sub(r"\s+#.*$", "", value)
        if value in ("", ">", "|", ">-", "|-", ">+", "|+"):
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[:1].isspace():
                    break  # the next key: the block was empty
                if nxt.strip():
                    return nxt.strip()
            return ""
        return value
    return ""


def read_skill_head(path: Path) -> dict | None:
    """`name` and `description` from a SKILL.md's frontmatter (`---` lines at the top), or None without one."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(SKILL_HEAD_MAX)
    except OSError:
        return None
    lines = raw.decode("utf-8", errors="replace").removeprefix("\ufeff").replace("\r\n", "\n").split("\n")
    if lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    block = lines[1:end]
    return {"name": _frontmatter_value(block, "name"), "description": _frontmatter_value(block, "description")}


def read_skills(profile_dir: Path) -> list[dict]:
    """`skills.list`: the bot's own skills (`<profile>/skills/**/SKILL.md`), each as the `/command` Hermes registers
    for it (`name`, the slug of the frontmatter name or of the folder's) and a one-line description, sorted, one
    row per slug (the first in path order wins, as in Hermes' scan). Symlinked skill folders and files are
    followed as Hermes' own scan follows them, each real folder once (a link back up is a cycle, not a loop);
    hidden folders (`.archive`, `.hub`) are skipped. Read-only: the first 8 KB of each SKILL.md."""
    root = profile_dir / "skills"
    if not root.is_dir():
        return []
    found: dict[str, str] = {}
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        here = Path(dirpath)
        has_skill = "SKILL.md" in filenames
        dirnames[:] = sorted(
            n for n in dirnames
            if not n.startswith(".") and n not in SKILL_SKIP_DIRS and not (has_skill and n in SKILL_SUPPORT_DIRS))
        skill = here / "SKILL.md"
        if not has_skill or not skill.is_file():
            continue
        head = read_skill_head(skill)
        if head is None:
            continue
        slug = skill_slug(head["name"] or here.name)
        if not slug or slug in found:
            continue
        desc = " ".join(head["description"].split())
        found[slug] = desc if len(desc) <= SKILL_DESC_MAX else desc[:SKILL_DESC_MAX - 1].rstrip() + "…"
    return [{"name": n, "description": found[n]} for n in sorted(found)]


# ---------------------------------------------------------------- usage meters (read-only)

USAGE_FILES = 5               # newest session files read per CLI
USAGE_TAIL = 512 * 1024       # bytes read from the end of each file
_CLAUDE_WINDOWS = {"five_hour": "5 hours", "seven_day": "Weekly", "seven_day_opus": "Weekly (Opus)",
                   "seven_day_sonnet": "Weekly (Sonnet)"}


def _tail_lines(path: Path, needle: str, limit: int = USAGE_TAIL):
    """Lines of the last `limit` bytes of `path` that contain `needle`, newest first (a cut first line is dropped)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit))
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").split("\n")
    if size > limit:
        lines = lines[1:]
    return [ln for ln in reversed(lines) if needle in ln]


def _newest(paths, n: int = USAGE_FILES) -> list[tuple[float, Path]]:
    out = []
    for p in paths:
        try:
            out.append((p.stat().st_mtime, p))
        except OSError:
            continue
    out.sort(key=lambda t: -t[0])
    return out[:n]


def _window_label(minutes) -> str:
    m = int(minutes or 0)
    if m == 300:
        return "5 hours"
    if m == 10080:
        return "Weekly"
    if m <= 0:
        return "Limit"
    if m % 1440 == 0:
        return f"{m // 1440}d"
    return f"{max(1, round(m / 60))}h"


def _finish(provider: dict, now: float) -> dict:
    """A window whose reset time has passed loses its number (`stale`); a provider whose every window is stale
    is `stale` itself. No number is ever made up: windows keep `used_percent` only when the source gave one."""
    windows = provider["windows"]
    for w in windows:
        if w.get("resets_at") is not None and w["resets_at"] <= now:
            w.pop("used_percent", None)
            w["stale"] = True
    if windows and all(w.get("stale") for w in windows):
        provider["state"] = "stale"
    return provider


def _codex_usage(user_home: Path, now: float, root: Path | None = None) -> dict | None:
    root = root or user_home / ".codex" / "sessions"
    if not root.is_dir():
        return None
    best = None  # (event ts, mtime, rate_limits)
    for mtime, path in _newest(root.rglob("rollout-*.jsonl")):
        for line in _tail_lines(path, '"rate_limits"'):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            payload = ev.get("payload") if isinstance(ev, dict) else None
            rl = payload.get("rate_limits") if isinstance(payload, dict) else None
            if not isinstance(rl, dict) or not (rl.get("primary") or rl.get("secondary")):
                continue
            ts = _to_ts(ev.get("timestamp")) if ev.get("timestamp") else mtime
            if best is None or ts > best[0]:
                best = (ts, mtime, rl)
            break  # newest usable event of this file
    if best is None:
        return None
    ts, mtime, rl = best
    windows = []
    for key in ("primary", "secondary"):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        out: dict = {"label": _window_label(w.get("window_minutes"))}
        if isinstance(w.get("used_percent"), (int, float)):
            out["used_percent"] = float(w["used_percent"])
        if isinstance(w.get("resets_at"), (int, float)):
            out["resets_at"] = float(w["resets_at"])
        elif isinstance(w.get("resets_in_seconds"), (int, float)):
            out["resets_at"] = ts + float(w["resets_in_seconds"])
        windows.append(out)
    top = max((w.get("used_percent", 0.0) for w in windows), default=0.0)
    state = "limited" if rl.get("rate_limit_reached_type") or top >= 100 else "near" if top >= 70 else "ok"
    provider = {"id": "codex", "windows": windows, "state": state, "source_mtime": mtime}
    if isinstance(rl.get("plan_type"), str) and rl["plan_type"]:
        provider["plan"] = rl["plan_type"]
    return _finish(provider, now)


def _find_key(obj, key: str, depth: int = 0):
    if depth > 4 or not isinstance(obj, dict):
        return None
    if isinstance(obj.get(key), dict):
        return obj[key]
    for v in obj.values():
        hit = _find_key(v, key, depth + 1)
        if hit is not None:
            return hit
    return None


def _claude_usage(user_home: Path, now: float, root: Path | None = None) -> dict | None:
    root = root or user_home / ".claude" / "projects"
    if not root.is_dir():
        return None
    best = None  # (event ts, mtime, rate_limit_info)
    for mtime, path in _newest(root.glob("*/*.jsonl")):
        for line in _tail_lines(path, '"rate_limit_info"'):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            info = _find_key(ev, "rate_limit_info")
            if not info or not info.get("status"):
                continue
            ts = _to_ts(ev.get("timestamp")) if isinstance(ev, dict) and ev.get("timestamp") else mtime
            if best is None or ts > best[0]:
                best = (ts, mtime, info)
            break
    if best is None:
        return None
    _, mtime, info = best
    kind = str(info.get("rateLimitType") or "")
    window: dict = {"label": _CLAUDE_WINDOWS.get(kind) or (kind.replace("_", " ").capitalize() or "Limit")}
    if isinstance(info.get("resetsAt"), (int, float)):
        window["resets_at"] = float(info["resetsAt"])
    status = str(info.get("status"))
    state = "limited" if status == "rejected" else "near" if status == "allowed_warning" else "ok"
    return _finish({"id": "claude", "windows": [window], "state": state, "source_mtime": mtime}, now)


def read_usage(user_home: Path | None = None, *, now: float | None = None, which=None,
               with_accounts: bool = True) -> dict:
    """Subscription usage per CLI, from the CLIs' own local session files only (read-only, tail reads, no
    network, no tokens). Codex gives percentages; Claude Code gives a state and a reset time, never a %.
    A CLI with no usage record shows as `connected` when it is on PATH, and not at all otherwise.
    With two or more Claude logins (Claude Code's own, omher accounts, a local CLIProxyAPI's auth file names),
    the Claude meter also lists them, each with only its own usage record (see `claude_accounts`)."""
    import shutil
    user_home = Path(user_home) if user_home else Path.home()
    now = time.time() if now is None else now
    which = which or shutil.which
    providers = []
    for pid, reader, cli in (("codex", _codex_usage, "codex"), ("claude", _claude_usage, "claude"),
                             ("grok", None, "grok"), ("gemini", None, "gemini")):
        found = reader(user_home, now) if reader else None
        if pid == "claude" and with_accounts:
            accounts = claude_accounts(user_home, now, found)
            if found is None and len(accounts) > 1:
                found = {"id": pid, "windows": [], "state": "connected", "source_mtime": None}
            if found is not None and len(accounts) > 1:
                found["accounts"] = accounts
        if found is None and which(cli):
            found = {"id": pid, "windows": [], "state": "connected", "source_mtime": None}
        if found is not None:
            providers.append(found)
    return {"providers": providers}


def claude_accounts(user_home: Path, now: float, default_usage: dict | None) -> list[dict]:
    """Every Claude login on this computer for the sidebar meter, in the Accounts page's order: Claude Code's own,
    the omher accounts, then a local CLIProxyAPI's other logins (from its auth file names). Each carries only its
    own usage record (`state`, `resets_at`); a CLIProxyAPI-only login has none (`no_record`)."""
    rows = _with_cpa(_omher_rows("claude", user_home, now, default_usage, {}, lambda _: None), user_home)
    out = []
    for r in rows:
        if r["state"] == "login" and r.get("source") != "cpa" and not r.get("in_cpa"):
            continue  # nobody signed in there
        u = r.get("usage") or {}
        item = {"email": r["email"], "label": r["label"], "source": r.get("source") or ("cli" if r["id"] == "default" else "omher"),
                "in_cpa": bool(r.get("in_cpa")), "state": u.get("state") or "no_record"}
        resets = [w["resets_at"] for w in u.get("windows") or [] if "resets_at" in w and not w.get("stale")]
        if item["state"] == "limited" and resets:
            item["resets_at"] = max(resets)
        out.append(item)
    return out


def _read_jobs(profile_dir: Path) -> list[dict]:
    """The job dicts in `<profile>/cron/jobs.json` (Hermes' own cron store), opened read-only; [] when absent."""
    try:
        data = json.loads((profile_dir / "cron" / "jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    return [j for j in (jobs if isinstance(jobs, list) else []) if isinstance(j, dict) and j.get("id")]


def _routine_row(j: dict) -> dict:
    sched = j.get("schedule_display")
    if not sched and isinstance(j.get("schedule"), dict):
        sched = j["schedule"].get("display") or j["schedule"].get("expr")
    return {"id": str(j["id"]), "name": str(j.get("name") or j["id"]), "schedule": str(sched or ""),
            "next_run_at": j.get("next_run_at"), "last_run_at": j.get("last_run_at"),
            "last_status": j.get("last_status"), "enabled": bool(j.get("enabled", True))}


def read_routines(profile_dir: Path) -> list[dict]:
    return [_routine_row(j) for j in _read_jobs(profile_dir)]


AUTOMATION_PROMPT_MAX = 2000  # chars of a job's prompt the Automations page shows


def _origin_place(origin) -> dict | None:
    """Where an `origin` delivery lands, for display only: `{platform, place}` (a Discord guild name dropped)."""
    if not isinstance(origin, dict):
        return None
    platform = str(origin.get("platform") or "").strip().lower()
    if not platform:
        return None
    name = " ".join(str(origin.get("chat_name") or "").split())
    if platform == "discord":
        parts = [x.strip() for x in name.split(" / ") if x.strip()]
        name = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
    elif platform == "slack" and name and not name.startswith("#"):
        name = f"#{name}"
    return {"platform": platform, "place": name[:80]}


def read_automations(profile_dir: Path) -> list[dict]:
    """A bot's cron jobs for the Automations page: `read_routines`' fields plus what the detail panel shows
    (prompt or script name, delivery, created, last error, repeat). Read-only; `cron.manage` on the bot's gateway is the
    only way omher changes a job."""
    out = []
    for j in _read_jobs(profile_dir):
        base = _routine_row(j)
        rep = j.get("repeat") if isinstance(j.get("repeat"), dict) else {}
        times, done = rep.get("times"), rep.get("completed")
        out.append({**base,
                    "paused": not base["enabled"] or str(j.get("state") or "") == "paused" or bool(j.get("paused_at")),
                    "prompt": str(j.get("prompt") or "")[:AUTOMATION_PROMPT_MAX],
                    "script": _clip(Path(str(j["script"])).name, 120) if j.get("script") else None,
                    "deliver": str(j.get("deliver") or "local"),
                    "origin": _origin_place(j.get("origin")),
                    "created_at": j.get("created_at"),
                    "last_error": _clip(str(j.get("last_error") or j.get("last_delivery_error") or ""), 300) or None,
                    "repeat": {"times": times if isinstance(times, int) else None,
                               "completed": done if isinstance(done, int) else 0}})
    return out


# ---------------------------------------------------------------- plugins (catalog cache + folder names)

PLUGIN_CATEGORIES = ("automation", "tools", "memory", "voice", "web", "desktop", "models", "platform", "general")
CATALOG_PAGE = 60  # catalog entries sent per plugins.catalog answer
_CATALOG_CACHE: dict[str, tuple[int, list[dict], str]] = {}


def catalog_path(profile_dir: Path, root: Path) -> Path | None:
    """The plugin catalog cache Hermes keeps for this profile, else the one at the Hermes root."""
    for p in (profile_dir / "cache" / "plugin-catalog.json", root / "cache" / "plugin-catalog.json"):
        if p.is_file():
            return p
    return None


def _strs(value, n: int = 40) -> list[str]:
    return [str(x) for x in value[:n] if isinstance(x, (str, int))] if isinstance(value, list) else []


def read_catalog(path: Path) -> tuple[list[dict], str]:
    """The catalog's entries (those it lists as removed left out), compacted for the UI, and `generated_at`.
    Cached by mtime: the file is a few MB."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return [], ""
    hit = _CATALOG_CACHE.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1], hit[2]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], ""
    data = data if isinstance(data, dict) else {}
    removed = {str(r.get("name")) for r in data.get("removed") or [] if isinstance(r, dict)}
    out = []
    for e in data.get("entries") or []:
        if not isinstance(e, dict) or not isinstance(e.get("name"), str) or e["name"] in removed:
            continue
        caps = e.get("capabilities") if isinstance(e.get("capabilities"), dict) else {}
        out.append({"name": e["name"], "title": str(e.get("title") or ""),
                    "description": _clip(str(e.get("description") or ""), 400),
                    "tier": str(e.get("tier") or "community"), "category": str(e.get("category") or "general"),
                    "version": str(e.get("version") or ""), "repo": str(e.get("repo") or ""),
                    "maintainer": str(e.get("maintainer") or ""), "platforms": _strs(e.get("platforms"), 8),
                    "tools": _strs(caps.get("provides_tools")), "hooks": _strs(caps.get("provides_hooks")),
                    "requires_env": _strs(caps.get("requires_env"), 12)})
    gen = str(data.get("generated_at") or "")
    _CATALOG_CACHE[str(path)] = (mtime, out, gen)
    return out, gen


_TIER_RANK = {"official": 0, "verified": 1, "community": 2}


def search_catalog(entries: list[dict], query: str = "", category: str = "", limit: int = CATALOG_PAGE) -> dict:
    """Entries matching `query` (name, title, description) in `category`, official tier first, then by name."""
    q = query.strip().lower()
    hits = [e for e in entries if (not category or e["category"] == category)
            and (not q or q in e["name"].lower() or q in e["title"].lower() or q in e["description"].lower())]
    hits.sort(key=lambda e: (_TIER_RANK.get(e["tier"], 3), e["name"].lower()))
    counts = {c: 0 for c in PLUGIN_CATEGORIES}
    for e in entries:
        if e["category"] in counts:
            counts[e["category"]] += 1
    return {"total": len(entries), "matched": len(hits), "entries": hits[:max(1, min(limit, 200))], "categories": counts}


def plugin_folders(profile_dir: Path) -> set[str]:
    """Names of the folders under `<profile>/plugins/` (the bot's own installs). Names only; nothing is opened."""
    try:
        return {p.name for p in (profile_dir / "plugins").iterdir() if p.is_dir() and not p.name.startswith(".")}
    except OSError:
        return set()


def plugin_row(row: dict, catalog: dict[str, dict]) -> dict:
    """One `plugins.manage list` row for the UI, joined with its catalog entry for tier, hooks and category."""
    name = str(row.get("name") or "")
    cat = catalog.get(str(row.get("catalog_name") or "")) or catalog.get(name) or {}
    schema = row.get("settings_schema") if isinstance(row.get("settings_schema"), list) else []
    needs = [str(f.get("env") or f.get("key")) for f in schema
             if isinstance(f, dict) and f.get("type") == "secret" and not f.get("has_value")]
    source = str(row.get("source") or "user")
    tools = row.get("tools") if isinstance(row.get("tools"), list) else []
    return {"name": name, "key": str(row.get("key") or name), "title": str(cat.get("title") or ""),
            "version": str(row.get("version") or ""),
            "description": _clip(str(row.get("description") or cat.get("description") or ""), 400),
            "source": source, "enabled": str(row.get("status") or "") == "enabled",
            "tier": str(row.get("catalog_tier") or cat.get("tier") or ("bundled" if source == "bundled" else "user")),
            "category": str(cat.get("category") or ""), "catalog_name": str(row.get("catalog_name") or "") or None,
            "tools": len(tools) or len(cat.get("tools") or []), "hooks": len(cat.get("hooks") or []),
            "update_available": bool(row.get("update_available")), "needs_env": needs[:8]}


def _to_ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return time.time()


# ---------------------------------------------------------------- runs: OMH dag records (read-only)

DAG_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")  # OMH's own id rule for runs and nodes
HANDOFF_MAX = 8000  # chars of one node's handoff sent to the UI
_OUTCOME_STATE = {"accepted": "done", "failed": "failed", "blocked": "blocked", "parked": "parked", "retry": "waiting"}


def omh_home_for(profile_dir: Path) -> Path:
    """The OMH store a profile's plugin uses: its `plugins.entries.omh.settings.omh_home`, else `OMH_HOME`,
    else `~/.omh` (OMH's own standalone order)."""
    node = _load_yaml(profile_dir / "config.yaml")
    for key in ("plugins", "entries", "omh", "settings"):
        node = node.get(key) if isinstance(node, dict) else None
    value = node.get("omh_home") if isinstance(node, dict) else None
    if isinstance(value, str) and value.strip():
        path = Path(os.path.expanduser(value.strip()))
        return path if path.is_absolute() else profile_dir / path
    env = (os.environ.get("OMH_HOME") or "").strip()
    return Path(os.path.expanduser(env)) if env else Path.home() / ".omh"


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def layer_of(nodes: list[dict]) -> dict[str, int]:
    """Longest-path layer of each node from its deps (deps on unknown ids are ignored). A cycle raises."""
    deps = {n["id"]: n["deps"] for n in nodes}
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(i: str) -> int:
        if i in memo:
            return memo[i]
        if i in visiting:
            raise ValueError(f"cycle through {i}")
        visiting.add(i)
        memo[i] = 1 + max((visit(d) for d in deps[i]), default=-1)
        visiting.discard(i)
        return memo[i]

    for i in deps:
        visit(i)
    return memo


def dag_to_run(record: dict, bot: str, handoffs=()) -> dict:
    """One `omh_dag/v1` record as an AgentRun (src/lib/runs.ts has the same mapping as `fromDag`)."""
    raw = [n for n in record.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    ids = {n["id"] for n in raw}
    cancelled = record.get("cancelled_at") is not None
    nodes = []
    for n in raw:
        attempts = [a for a in n.get("attempts") or [] if isinstance(a, dict)]
        last = attempts[-1] if attempts else None
        state = "waiting" if last is None else _OUTCOME_STATE.get(str(last.get("outcome") or ""), "running")
        if cancelled and state in ("running", "parked", "waiting"):
            state = "cancelled"
        node = {"id": n["id"], "label": str(n.get("label") or n["id"]),
                "deps": [d for d in n.get("depends_on") or [] if d in ids], "state": state, "attempts": []}
        if isinstance(n.get("category"), str) and n["category"]:
            node["category"] = node["route"] = n["category"]
        if isinstance(n.get("role"), str) and n["role"]:
            node["role"] = n["role"]
        for a in attempts:
            item = {"n": int(a["n"]) if isinstance(a.get("n"), int) else len(node["attempts"]) + 1,
                    "outcome": str(a.get("outcome") or "") or "open"}
            for src, dst in (("reason", "reason"), ("lane", "lane")):
                if isinstance(a.get(src), str) and a[src]:
                    item[dst] = a[src]
            for src, dst in (("handed_out_at", "started"), ("settled_at", "ended")):
                if _num(a.get(src)) is not None:
                    item[dst] = _num(a.get(src))
            node["attempts"].append(item)
        if node["attempts"]:
            first, end = node["attempts"][0], node["attempts"][-1]
            if "lane" in end:
                node["lane"] = end["lane"]
            if "started" in first:
                node["started"] = first["started"]
            if state in ("done", "failed", "blocked") and "ended" in end:
                node["ended"] = end["ended"]
        if n["id"] in handoffs:
            node["handoff"] = f"{n['id']}.md"
        nodes.append(node)
    repairs = record.get("repairs")
    groups: dict = repairs if isinstance(repairs, dict) else {}
    by_id = {node["id"]: node for node in nodes}
    # each repair member points at the node it repairs (the latest group naming it wins), so the graph can
    # draw that link and place the repair after the failure
    for target, g in groups.items():
        if target not in by_id or not isinstance(g, list):
            continue
        for group in g:
            for m in group if isinstance(group, list) else []:
                if m in by_id and m != target:
                    by_id[m]["repairOf"] = target
    layers = layer_of([{"id": node["id"], "deps": node["deps"] + ([node["repairOf"]] if "repairOf" in node else [])}
                       for node in nodes])
    for node in nodes:
        node["layer"] = layers[node["id"]]
    superseded = {m for g in groups.values() if isinstance(g, list) for older in g[:-1] if isinstance(older, list)
                  for m in older if by_id.get(m, {}).get("state") != "done"}

    def satisfied(node) -> bool:
        if node["state"] == "done":
            return True
        latest = (groups.get(node["id"]) or [[]])[-1]
        return node["state"] in ("failed", "blocked") and bool(latest) and all(
            by_id.get(m, {}).get("state") == "done" for m in latest)

    live = [node for node in nodes if node["id"] not in superseded]
    if cancelled:
        run_state = "cancelled"
    elif all(satisfied(node) for node in live):
        run_state = "done"
    elif any(node["state"] in ("running", "parked") or node["state"] == "waiting" and all(
            satisfied(by_id[d]) for d in node["deps"]) for node in live):
        run_state = "running"
    else:
        run_state = "failed"
    sid, run = str(record.get("session_id") or ""), str(record.get("run") or "")
    out = {"id": f"dag:{sid}/{run}", "kind": "dag", "owner": {"type": "bot", "id": bot},
           "title": str(record.get("name") or run), "state": run_state, "nodes": nodes,
           "started": _num(record.get("defined_at")) or 0.0, "updated": _num(record.get("updated_at")) or 0.0}
    if isinstance(record.get("goal"), str) and record["goal"]:
        out["goal"] = record["goal"]
    if run_state != "running":
        ends = [a["ended"] for node in nodes for a in node["attempts"] if "ended" in a]
        ended = _num(record.get("cancelled_at")) if cancelled else (max(ends) if ends else None)
        if ended is not None:
            out["ended"] = ended
    return out


def repaired_ids(nodes: list[dict]) -> set[str]:
    """Failed (or blocked) nodes whose repairs all finished: OMH counts them as satisfied."""
    fixes: dict[str, list[dict]] = {}
    for n in nodes:
        if n.get("repairOf"):
            fixes.setdefault(n["repairOf"], []).append(n)
    return {n["id"] for n in nodes if n["state"] in ("failed", "blocked") and fixes.get(n["id"])
            and all(m["state"] == "done" for m in fixes[n["id"]])}


def run_summary(run: dict) -> dict:
    """A run without its nodes, plus counts. `failed` is open failures only; a failure its repairs fixed counts as
    `repaired` (and appears only when there is one)."""
    out = {k: v for k, v in run.items() if k != "nodes"}
    states = [n["state"] for n in run["nodes"]]
    fixed = len(repaired_ids(run["nodes"]))
    out["counts"] = {"nodes": len(states), "done": states.count("done"), "running": states.count("running"),
                     "failed": states.count("failed") + states.count("blocked") - fixed}
    if fixed:
        out["counts"]["repaired"] = fixed
    return out


# ---------------------------------------------------------------- runs: the PR a node produced (read-only)
# A node's attempt reasons, its helper's summary and its handoff often name the pull request it opened ("PR #2746",
# "https://github.com/o/r/pull/2750"). `runs.get` carries the newest such reference as `pr: {number, repo?, url?}`;
# `runs.prs` asks the person's own GitHub CLI for each one's state, later and apart, so the run list never waits.

PR_URL = re.compile(r"https?://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]{1,100})/pull/(\d{1,7})\b")
PR_WORD = re.compile(r"\b(?:PR|pull request)s?\b[\s:]*#(\d{1,7})\b", re.I)
PR_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}$")
PR_TTL = 300.0          # seconds a PR state is reused
PR_TTL_MISS = 60.0      # and a failed look-up (no gh, no network): tried again sooner
PR_TIMEOUT = 3.0        # seconds one `gh pr view` may take
PR_POOL = 4             # look-ups at once
PR_STATES = ("open", "merged", "closed", "draft", "unknown")


def _pr_refs(text: str) -> list[tuple[int, int, str | None]]:
    """(offset, number, repo or None) of every PR reference in `text`, in order. A URL names its repo."""
    out = [(m.start(), int(m.group(3)), f"{m.group(1)}/{m.group(2)}") for m in PR_URL.finditer(text)]
    out += [(m.start(), int(m.group(1)), None) for m in PR_WORD.finditer(text)]
    return sorted(out)


def find_pr(texts) -> dict | None:
    """The newest PR a node names: the last reference in the last text that has one (texts oldest first:
    the attempts' reasons, the helper's summary, then the handoff). A bare `PR #n` takes the repo of a URL with
    the same number in any of the texts, else the one repo all its URLs name. {number, repo?, url?} or None."""
    refs = [r for text in texts if isinstance(text, str) and text for r in _pr_refs(text)]
    if not refs:
        return None
    _, number, repo = refs[-1]
    repos = {r for _, _, r in refs if r}
    if repo is None:
        same = [r for _, n, r in refs if r and n == number]
        repo = same[-1] if same else (next(iter(repos)) if len(repos) == 1 else None)
    out: dict = {"number": number}
    if repo:
        out["repo"] = repo
        out["url"] = f"https://github.com/{repo}/pull/{number}"
    return out


def attach_prs(run: dict, texts: dict[str, str]) -> dict:
    """`pr` on each node that names one (see find_pr); `texts` holds each node's handoff text. A bare `#n` with no
    repo of its own takes the run's, when every URL in the run names the same one."""
    for node in run["nodes"]:
        found = find_pr([a.get("reason") for a in node.get("attempts") or []] + [node.get("summary"), texts.get(node["id"])])
        if found:
            node["pr"] = found
    repos = {n["pr"]["repo"] for n in run["nodes"] if n.get("pr", {}).get("repo")}
    if len(repos) == 1:
        repo = next(iter(repos))
        for node in run["nodes"]:
            if "pr" in node and "repo" not in node["pr"]:
                node["pr"].update(repo=repo, url=f"https://github.com/{repo}/pull/{node['pr']['number']}")
    return run


def pr_state_of(view: dict) -> str:
    """GitHub's answer (`gh pr view --json state,isDraft,mergedAt,url`) as one of PR_STATES."""
    state = str(view.get("state") or "").upper()
    if state == "MERGED" or (state == "CLOSED" and view.get("mergedAt")):
        return "merged"
    if state == "CLOSED":
        return "closed"
    if state == "OPEN":
        return "draft" if view.get("isDraft") is True else "open"
    return "unknown"


def _gh_path(which=None) -> str | None:
    """The GitHub CLI: on PATH, else where its installers put it (an app opened from the Dock has a short PATH)."""
    import shutil
    which = which or shutil.which
    found = which("gh")
    if found:
        return found
    if os.name == "nt":
        roots = [os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")]
        for p in (Path(r, "GitHub CLI", "gh.exe") for r in roots if r):
            if p.is_file():
                return str(p)
        return None
    for d in ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"), "/usr/bin"):
        p = Path(d) / "gh"
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def gh_pr_view(repo: str, number: int, *, gh: str | None = None, timeout: float = PR_TIMEOUT) -> dict | None:
    """One fixed read through the person's own `gh`: `gh pr view <n> -R <owner>/<repo> --json
    state,isDraft,mergedAt,url`. None when gh is missing, slow, signed out or offline. omher passes no token and
    reads none; gh uses its own login."""
    if not PR_REPO.match(repo) or not isinstance(number, int) or isinstance(number, bool) or not 0 < number < 10**7:
        raise ValueError(f"not a PR: {repo}#{number}")
    gh = gh or _gh_path()
    if not gh:
        return None
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run([gh, "pr", "view", str(number), "-R", repo, "--json", "state,isDraft,mergedAt,url"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, env={**os.environ, "GH_PROMPT_DISABLED": "1",
                                                          "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"}, **kw)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        view = json.loads(r.stdout)
    except ValueError:
        return None
    return view if isinstance(view, dict) else None


class PrStates:
    """PR states by (repo, number), each kept PR_TTL seconds (a failed look-up PR_TTL_MISS). `view` is the look-up
    (gh_pr_view; tests pass a stub)."""

    def __init__(self, view=None, clock=time.monotonic):
        self._view = view or gh_pr_view
        self._clock = clock
        self._cache: dict[tuple[str, int], tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _one(self, repo: str, number: int) -> dict:
        key = (repo, number)
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now < hit[0]:
            return hit[1]
        try:
            view = self._view(repo, number)
        except ValueError:
            view = None
        state = pr_state_of(view) if view else "unknown"
        out = {"state": state}
        url = view.get("url") if view else None
        if isinstance(url, str) and url == f"https://github.com/{repo}/pull/{number}":
            out["url"] = url
        with self._lock:
            self._cache[key] = (now + (PR_TTL if state != "unknown" else PR_TTL_MISS), out)
            if len(self._cache) > 2000:
                self._cache.clear()
        return out

    def states(self, run: dict) -> dict[str, dict]:
        """{node id: {number, repo?, url?, state}} for every node of `run` that names a PR; a PR with no repo is
        `unknown` without asking. The look-ups run side by side."""
        nodes = [n for n in run.get("nodes") or [] if isinstance(n.get("pr"), dict)]
        keys = sorted({(n["pr"]["repo"], n["pr"]["number"]) for n in nodes if n["pr"].get("repo")})
        got: dict[tuple[str, int], dict] = {}
        if keys:
            with ThreadPoolExecutor(max_workers=min(PR_POOL, len(keys))) as pool:
                for key, res in zip(keys, pool.map(lambda k: self._one(*k), keys)):
                    got[key] = res
        out = {}
        for n in nodes:
            pr = dict(n["pr"])
            pr.update(got.get((pr.get("repo"), pr["number"]), {"state": "unknown"}))
            out[n["id"]] = pr
        return out


# ---------------------------------------------------------------- runs: Hermes delegate_task fan-outs (read-only)

DELEG_ID = re.compile(r"^deleg_[0-9a-f]{6,32}$")
DAG_MARK = re.compile(r"\[dag:([a-z0-9][a-z0-9-]{0,31})/([a-z0-9][a-z0-9-]{0,31})\]")
SUMMARY_MAX = 600       # chars of a helper's final summary sent to the UI
DELEG_LIMIT = 40        # newest delegation folders read per bot
LOG_HEAD = 2048         # bytes read from the top of a task log (goal, started)
LOG_TAIL = 6144         # bytes read from its end (the `final` lines)
STALE_AFTER = 3600.0    # a "running" task whose log has not moved for this long has stopped reporting
QUIET_RUN = 86400.0     # a "running" dag run whose record has not changed for this long, with no helper log moving
                        # (STALE_AFTER), is no longer live: `stale` (nothing settled it; omher never does either)
ROUTE_FRESH = 900.0     # OMH's own window: a route record older than this no longer describes a dispatch
_FINAL = re.compile(r"^\d\d:\d\d:\d\d final\s+\|\s*(.*)$")
_TASK_STATE = {"running": "running", "completed": "done", "failed": "failed", "error": "failed",
               "timeout": "failed", "stalled": "failed", "interrupted": "cancelled", "cancelled": "cancelled"}
_ROUTE_WHY = {"head": "chain head", "fallback": "fallback", "exhausted_to_inherit": "chain exhausted"}


def _local_ts(text, tz=None) -> float | None:
    """`2026-11-09 21:29:55` (Hermes writes local time) as epoch seconds; `tz` pins the zone for tests."""
    try:
        dt = datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return (dt.replace(tzinfo=tz) if tz is not None else dt).timestamp()


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def read_task_log(path: Path) -> dict:
    """Head lines (goal, started) and the `final` lines of one `task-N.log`; the transcript between is skipped."""
    out: dict = {}
    try:
        with open(path, "rb") as fh:
            head = fh.read(LOG_HEAD).decode("utf-8", "replace")
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - LOG_TAIL))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return out
    for line in head.split("\n")[:6]:
        key, _, value = line.partition(": ")
        if key in ("goal", "started") and value.strip():
            out[key] = value.strip()
    for line in tail.split("\n"):
        m = _FINAL.match(line)
        if not m:
            continue
        body = m.group(1)
        if body.startswith("end "):
            for k, v in re.findall(r"(status|exit_reason)=(\S+)", body):
                out[k] = v
            if " error: " in body:
                out["error"] = _clip(body.split(" error: ", 1)[1], SUMMARY_MAX)
        elif "summary:" in body:
            out["summary"] = _clip(body.split("summary:", 1)[1], SUMMARY_MAX)
            st = re.search(r"status=(\S+)", body)
            if st:
                out.setdefault("status", st.group(1))
            took = re.search(r"\bduration=(\d+(?:\.\d+)?)s\b", body.split("summary:", 1)[0])
            if took:
                out["duration"] = float(took.group(1))
    return out


def load_route_records(omh_home: Path) -> list[dict]:
    """OMH's `routing/route-provenance.json` (what `omh_delegate_route` wrote before a dispatch), oldest first.
    Anything unreadable is no records."""
    try:
        raw = json.loads((omh_home / "routing" / "route-provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict) or raw.get("schema_version") != "delegation_route_provenance/v1":
        return []
    out = []
    for r in raw.get("records") or []:
        if isinstance(r, dict) and _num(r.get("written_at")) is not None and isinstance(r.get("origin"), str):
            out.append(r)
    return sorted(out, key=lambda r: r["written_at"])


def route_for(records: list[dict], started: float, model: str, sessions: set[str]) -> dict | None:
    """The route record that preceded a dispatch, by OMH's own pairing rule: the newest record written before
    the child started, no older than ROUTE_FRESH, not a `cleared` one, naming the child's model, and written by
    one of this bot's sessions. Hermes stamps a start in whole seconds (truncated), so a record from inside that
    second may have come after the dispatch: only records before the stamp count."""
    for r in reversed(records):
        if r.get("session_id") and r["session_id"] not in sessions:
            continue
        if r["written_at"] > started:
            continue
        if started - r["written_at"] > ROUTE_FRESH or r.get("origin") == "cleared":
            return None
        if model and model in (r.get("alias"), r.get("wire_model")):
            route = {"category": str(r.get("category") or ""), "origin": r["origin"]}
            for src, dst in (("provider", "provider"), ("reasoning_effort", "effort"), ("from_alias", "from")):
                if isinstance(r.get(src), str) and r[src]:
                    route[dst] = r[src]
            return route if route["category"] else None
        return None
    return None


class Delegations:
    """Reads `<profile>/cache/delegation/live/deleg_*/` (Hermes' delegate_task manifest plus the head and final
    lines of each task log) into plain dicts. Cached per folder by the mtimes and sizes inside it."""

    def __init__(self, tz=None):
        self.tz = tz
        self._cache: dict[str, tuple[tuple, dict]] = {}

    def _one(self, folder: Path, now: float) -> dict | None:
        try:
            files = sorted(p for p in folder.iterdir() if p.name == "manifest.json" or re.match(r"^task-\d+\.log$", p.name))
            stamp = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files if not p.is_symlink())
        except OSError:
            return None
        hit = self._cache.get(str(folder))
        if hit and hit[0] == stamp:
            d = hit[1]
        else:
            try:
                man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return hit[1] if hit else None
            if not isinstance(man, dict) or not isinstance(man.get("tasks"), list):
                return None
            d = {"id": folder.name, "started": _local_ts(man.get("started"), self.tz) or 0.0, "tasks": []}
            ended = _local_ts(man.get("completed"), self.tz)
            if ended is not None:
                d["ended"] = ended
            for key in ("model", "provider"):
                if isinstance(man.get(key), str) and man[key]:
                    d[key] = man[key]
            for t in man["tasks"]:
                if not isinstance(t, dict) or not isinstance(t.get("index"), int):
                    continue
                log = folder / f"task-{t['index']}.log"
                head = read_task_log(log) if log.is_file() and not log.is_symlink() else {}
                goal = str(t.get("goal") or head.get("goal") or "")
                task = {"index": t["index"], "goal": _clip(DAG_MARK.sub("", goal), 200),
                        "status": str(t.get("status") or head.get("status") or "running")}
                if task["status"] == "running" and head.get("status"):
                    task["status"] = head["status"]  # the log's final line can land before the manifest's
                started = _local_ts(head.get("started"), self.tz)
                if started is not None:
                    task["started"] = started
                    # the task's own end (its final line's duration): a fan-out still running has no `completed`
                    # yet, and its finished tasks must not keep counting
                    if head.get("duration") is not None and task["status"] != "running":
                        task["ended"] = round(started + head["duration"], 3)
                model = t.get("model") or d.get("model")
                if isinstance(model, str) and model:
                    task["model"] = model
                for key in ("summary", "error"):
                    if head.get(key):
                        task[key] = head[key]
                m = DAG_MARK.search(goal)
                if m:
                    task["dag"] = {"run": m.group(1), "node": m.group(2)}
                try:
                    task["_mtime"] = log.stat().st_mtime
                except OSError:
                    task["_mtime"] = d["started"]
                d["tasks"].append(task)
            self._cache[str(folder)] = (stamp, d)
        out = json.loads(json.dumps(d))
        for task in out["tasks"]:
            if task["status"] == "running" and now - task.pop("_mtime") > STALE_AFTER:
                task["status"] = "stalled"
                task.setdefault("error", "No log update for over an hour; the helper stopped reporting.")
            task.pop("_mtime", None)
        return out

    def list(self, profile_dir: Path, now: float | None = None) -> list[dict]:
        root = profile_dir / "cache" / "delegation" / "live"
        if not root.is_dir() or root.is_symlink():
            return []
        now = time.time() if now is None else now
        try:
            folders = [p for p in root.iterdir() if DELEG_ID.match(p.name) and p.is_dir() and not p.is_symlink()]
        except OSError:
            return []
        folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [d for d in (self._one(f, now) for f in folders[:DELEG_LIMIT]) if d is not None]


def attach_routes(delegs: list[dict], records: list[dict], sessions: set[str]) -> list[dict]:
    """Give each delegation the OMH route record that prepared it, when one pairs (`route_for`)."""
    for d in delegs:
        model = d.get("model") or next((t["model"] for t in d["tasks"] if t.get("model")), "")
        route = route_for(records, d["started"], model, sessions) if d["started"] else None
        if route:
            d["route"] = route
    return delegs


def _task_node(t: dict, d: dict) -> dict:
    """The node fields one delegation task gives (model, provider, effort, route, summary)."""
    out = {}
    if t.get("model"):
        out["model"] = t["model"]
    route = d.get("route") or {}
    provider = d.get("provider") or route.get("provider")
    if provider:
        out["provider"] = provider
    if route.get("effort"):
        out["effort"] = route["effort"]
    if route.get("category"):
        out["route"] = route["category"]
        why = _ROUTE_WHY.get(route.get("origin", ""))
        if why:
            out["routeWhy"] = why + (f" from {route['from']}" if why == "fallback" and route.get("from") else "")
    if t.get("summary") or t.get("error"):
        out["summary"] = t.get("summary") or t.get("error")
    return out


def delegation_to_run(d: dict, bot: str) -> dict:
    """One delegate_task fan-out as a one-layer AgentRun (src/lib/runs.ts `fromDelegation` is the same mapping)."""
    nodes = []
    for t in d["tasks"]:
        state = _TASK_STATE.get(t["status"], "running")
        att = {"n": 1, "outcome": t["status"]}
        if t.get("started") is not None or d["started"]:
            att["started"] = t.get("started", d["started"])
        end = t.get("ended", d.get("ended"))
        if state != "running" and end is not None:
            att["ended"] = end
        if state in ("failed", "cancelled") and (t.get("error") or t.get("summary")):
            att["reason"] = t.get("error") or t.get("summary")
        node = {"id": f"task-{t['index']}", "label": t["goal"] or f"Task {t['index'] + 1}", "deps": [], "layer": 0,
                "state": state, "attempts": [att]}
        node.update(_task_node(t, d))
        if "started" in att:
            node["started"] = att["started"]
        if "ended" in att:
            node["ended"] = att["ended"]
        nodes.append(node)
    states = [n["state"] for n in nodes]
    run_state = ("running" if "running" in states else "failed" if "failed" in states
                 else "cancelled" if "cancelled" in states else "done")
    first = nodes[0]["label"] if nodes else d["id"]
    run = {"id": f"delegate:{d['id']}", "kind": "delegate", "owner": {"type": "bot", "id": bot},
           "title": first + (f" +{len(nodes) - 1}" if len(nodes) > 1 else ""), "state": run_state, "nodes": nodes,
           "started": d["started"], "updated": max([d["started"], d.get("ended") or 0.0]
                                                   + [n.get("started", 0.0) for n in nodes])}
    if run_state != "running" and d.get("ended") is not None:
        run["ended"] = d["ended"]
    return run


FANOUT_UNITS = re.compile(r"^fanout-[0-9a-f]{6,32}-units\.json$")


def fanout_owners(folder: Path) -> dict[str, str]:
    """{node id: owner} from a dag run's own `fanout-*-units.json` files (what `omh_dag export` handed to an agent
    CLI such as codex). Plain files inside the run folder only; anything unreadable is skipped."""
    out: dict[str, str] = {}
    if not folder.is_dir() or folder.is_symlink():
        return out
    for f in sorted(folder.iterdir()):
        if not FANOUT_UNITS.match(f.name) or f.is_symlink() or not f.is_file():
            continue
        try:
            units = json.loads(f.read_text(encoding="utf-8")).get("units")
        except (OSError, ValueError, AttributeError):
            continue
        for u in units if isinstance(units, list) else []:
            if isinstance(u, dict) and isinstance(u.get("unit_id"), str) and isinstance(u.get("owner"), str) and u["owner"]:
                out[u["unit_id"]] = u["owner"]
    return out


def attach_owners(run: dict, owners: dict[str, str]) -> dict:
    """Name the agent CLI that ran each fanout node (`executor`), when the run's unit files say so."""
    for node in run["nodes"]:
        if node.get("lane") == "fanout" and owners.get(node["id"]):
            node["executor"] = owners[node["id"]]
    return run


def route_table(records: list[dict], sessions: set[str]) -> dict[str, dict]:
    """{category: {model, provider?, effort?}}: what each routing category resolved to in this bot's newest route
    record (OMH's `route-provenance.json`), so a node no helper has reported on can show the model it goes to."""
    table: dict[str, dict] = {}
    for r in records:  # oldest first: a newer record replaces an older one
        if r.get("origin") == "cleared" or (r.get("session_id") and r["session_id"] not in sessions):
            continue
        cat, model = r.get("category"), r.get("wire_model") or r.get("alias")
        if not (isinstance(cat, str) and cat and isinstance(model, str) and model):
            continue
        row = {"model": model}
        for src, dst in (("provider", "provider"), ("reasoning_effort", "effort")):
            if isinstance(r.get(src), str) and r[src]:
                row[dst] = r[src]
        table[cat] = row
    return table


def attach_planned(run: dict, table: dict[str, dict]) -> dict:
    """`planned` = the route table's model for a node with no reported model and no named executor."""
    for node in run["nodes"]:
        if not node.get("model") and not node.get("executor") and table.get(node.get("route") or ""):
            node["planned"] = dict(table[node["route"]])
    return run


def attach_delegations(run: dict, delegs: list[dict]) -> dict:
    """Fill a dag run's nodes with what their helpers ran on (model, provider, effort, route record, summary).
    A task belongs to a node through the `[dag:<run>/<node>]` marker in its goal; attempt k pairs with the
    first matching task that started at or after that attempt was handed out. The dag's own fields win."""
    name = run["id"].rsplit("/", 1)[-1]
    tasks = sorted(((t, d) for d in delegs for t in d["tasks"]
                    if t.get("dag", {}).get("run") == name and d["started"] >= run["started"] - 60),
                   key=lambda td: td[0].get("started", td[1]["started"]))
    for node in run["nodes"]:
        mine = [(t, d) for t, d in tasks if t["dag"]["node"] == node["id"]]
        if not mine:
            continue
        used: set[int] = set()
        last = None
        for att in node["attempts"]:
            at = att.get("started")
            pick = next((i for i, (t, d) in enumerate(mine) if i not in used
                         and (at is None or t.get("started", d["started"]) >= at - 5)), None)
            if pick is None:
                continue
            used.add(pick)
            t, d = mine[pick]
            if t.get("model"):
                att["model"] = t["model"]
            last = (t, d)
        if last is None:
            continue
        for k, v in _task_node(*last).items():
            node.setdefault(k, v)
    return run


def mark_stale(run: dict, path: Path | None, delegs: list[dict], now: float) -> dict:
    """`stale: true` on a running dag run that is not live any more: its record (the `updated_at` it carries, and
    the file's own mtime) did not change for QUIET_RUN, and none of its helpers is still reporting (a task log
    that has not moved for STALE_AFTER already reads as stalled). The state stays as the record says."""
    if run["state"] != "running":
        return run
    changed = run["updated"]
    try:
        changed = max(changed, path.stat().st_mtime) if path is not None else changed
    except OSError:
        pass
    name = run["id"].rsplit("/", 1)[-1]
    reporting = any(t.get("dag", {}).get("run") == name and t["status"] == "running" for d in delegs for t in d["tasks"])
    if now - changed > QUIET_RUN and not reporting:
        run["stale"] = True
    return run


class DagRuns:
    """Reads `<omh home>/runtime/dag/*/*.json` for one bot: a run belongs to the bot when its `session_id` is a
    session in the bot's own state.db. A record caught mid-write keeps its last good parse (cache keyed by
    mtime and size); nothing here writes, settles or retries a run."""

    def __init__(self, delegations: Delegations | None = None):
        self._cache: dict[str, tuple[tuple[int, int], dict]] = {}
        self.delegations = delegations or Delegations()

    def _record(self, path: Path) -> dict | None:
        key = str(path)
        hit = self._cache.get(key)
        try:
            st = path.stat()
        except OSError:
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return hit[1] if hit else None
        if not isinstance(rec, dict) or not isinstance(rec.get("nodes"), list):
            return hit[1] if hit else None
        self._cache[key] = (stamp, rec)
        return rec

    @staticmethod
    def _sessions(profile_dir: Path) -> set[str]:
        import sqlite3
        db = profile_dir / "state.db"
        if not db.is_file():
            return set()
        try:
            con = sqlite3.connect(ro_uri(db), uri=True, timeout=1.0)
            try:
                return {str(r[0]) for r in con.execute("SELECT id FROM sessions")}
            finally:
                con.close()
        except sqlite3.Error:
            return set()

    def _owned(self, bot: str, profile_dir: Path, now: float | None = None):
        """(json path or None, record or None, AgentRun) for each of the bot's runs: its dag runs with their
        helpers' models and routes filled in, then its delegate_task fan-outs that belong to no dag run."""
        now = time.time() if now is None else now
        mine = self._sessions(profile_dir)
        home = omh_home_for(profile_dir)
        records = load_route_records(home)
        delegs = attach_routes(self.delegations.list(profile_dir, now=now), records, mine)
        table = route_table(records, mine)
        out = [(path, rec, mark_stale(attach_planned(attach_delegations(run, delegs), table), path, delegs, now))
               for path, rec, run in self._dag(bot, profile_dir, mine)]
        for d in delegs:
            if d["tasks"] and not any(t.get("dag") for t in d["tasks"]):
                out.append((None, None, delegation_to_run(d, bot)))
        return out

    def _dag(self, bot: str, profile_dir: Path, mine: set[str]):
        root = omh_home_for(profile_dir) / "runtime" / "dag"
        if not root.is_dir():
            return []
        out = []
        for path in sorted(root.glob("*/*.json")):
            if path.is_symlink() or path.parent.is_symlink() or not DAG_ID.match(path.stem):
                continue
            rec = self._record(path)
            if rec is None or str(rec.get("session_id") or "") not in mine:
                continue
            try:
                run = dag_to_run(rec, bot, self._handoff_names(root, path, rec))
            except (ValueError, TypeError, KeyError, RecursionError):
                continue  # a cycle or a malformed record: not drawable, skip it
            attach_owners(run, fanout_owners(path.parent / path.stem))
            out.append((path, rec, run))
        return out

    @staticmethod
    def _handoff_file(root: Path, path: Path, node: str) -> Path | None:
        """`<run>/<node>.md` next to the record, when it is a plain file inside the dag dir (no symlinks)."""
        if not DAG_ID.match(node):
            return None
        folder = path.parent / path.stem
        f = folder / f"{node}.md"
        if folder.is_symlink() or f.is_symlink() or not f.is_file():
            return None
        real, top = os.path.realpath(f), os.path.realpath(root)
        if os.path.commonpath([real, top]) != top:
            return None
        return f

    def _handoff_names(self, root: Path, path: Path, rec: dict) -> set[str]:
        ids = [str(n["id"]) for n in rec.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
        return {i for i in ids if self._handoff_file(root, path, i) is not None}

    def list(self, bot: str, profile_dir: Path, now: float | None = None) -> list[dict]:
        runs = [run_summary(run) for _, _, run in self._owned(bot, profile_dir, now)]
        runs.sort(key=lambda r: (r["state"] != "running" or bool(r.get("stale")), -r["updated"]))
        return runs

    def get(self, bot: str, profile_dir: Path, run_id: str) -> dict:
        root = omh_home_for(profile_dir) / "runtime" / "dag"
        for path, _, run in self._owned(bot, profile_dir):
            if run["id"] != run_id:
                continue
            handoffs, whole = {}, {}
            for node in run["nodes"]:
                f = self._handoff_file(root, path, node["id"]) if node.get("handoff") and path else None
                if f is None:
                    continue
                try:
                    with open(f, "rb") as fh:
                        data = fh.read(HANDOFF_MAX * 4)
                except OSError:
                    continue
                whole[node["id"]] = data.decode("utf-8", "replace")
                handoffs[node["id"]] = whole[node["id"]][:HANDOFF_MAX]
            # the PR a node opened is often named at the end of its handoff: read the whole read, not the clip
            return {"run": attach_prs(run, whole), "handoffs": handoffs}
        raise BridgeError("not_found", f"no run {run_id} for {bot}")


# ---------------------------------------------------------------- runs: CLI agent sub-runs (read-only)
# Claude Code Task/Agent subagents and Codex spawned sub-agents, each session with sub-runs as one AgentRun.
# Only a session's short title and each sub-run's name, model, state, times and final text (SUMMARY_MAX) leave
# here; prompts and message bodies are never kept. Nothing here starts, resumes or stops a CLI session.

CLI_AGENTS = ("claude", "codex", "omo", "pi", "omp", "grok")
OMO_TASKS = 200             # newest OmO task records read per call
_OMO_TASK = re.compile(r"^st_[A-Za-z0-9_-]{1,64}\.json$")
_OMO_STATE = {"completed": "done", "failed": "failed", "error": "failed", "cancelled": "cancelled",
              "aborted": "cancelled", "running": "running", "queued": "running", "pending": "running"}
CLI_STALE = 600.0           # a sub-run with no result whose transcript has not moved for this long: failed, "no result"
CLI_WINDOW = 7 * 86400.0    # default `since`: sessions started in the last week
CLI_FILES = 60              # newest session files read per agent and call
CLI_RUNS = 30               # runs returned per call
CLI_TITLE = 80              # chars of a session title or a sub-run label
CLI_TAIL = 65536            # bytes read from the end of a Claude subagent transcript (its model and last words)
CLI_HEAD = 600              # bytes of a Codex line searched for its event type
_CLAUDE_TOOLS = ("Agent", "Task")
_TOOL_RESULT_ID = re.compile(rb'"tool_use_id"\s*:\s*"([^"]{1,120})"')
_TASK_CALL = re.compile(rb'"name"\s*:\s*"(?:Agent|Task)"')
_API_REQUEST = re.compile(rb'^\{\s*"type"\s*:\s*"api-request')
_ASSISTANT = re.compile(rb'"type"\s*:\s*"assistant"')
_NOTE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
_NOTE_TAG = re.compile(r"<(task-id|tool-use-id|status|result|summary)>(.*?)</\1>", re.S)
_NOTE_STATE = {"completed": "done", "failed": "failed", "stopped": "cancelled", "killed": "cancelled",
               "cancelled": "cancelled"}
_CODEX_EVENTS = (b'"turn_context"', b'"task_started"', b'"task_complete"', b'"turn_aborted"')
_OUTCOME = {"done": "completed", "failed": "failed", "running": "open", "cancelled": "stopped"}


def cli_homes(environ=None) -> dict[str, Path]:
    """Where each CLI keeps its sessions: Claude Code `CLAUDE_CONFIG_DIR` (else ~/.claude), Codex `CODEX_HOME`
    (else ~/.codex)."""
    env = os.environ if environ is None else environ
    home = Path.home()
    return {"claude": Path(env.get("CLAUDE_CONFIG_DIR") or home / ".claude"),
            "codex": Path(env.get("CODEX_HOME") or home / ".codex"),
            "omo": home / ".omo", "pi": home / ".pi", "omp": home / ".omp", "grok": home / ".grok"}


def claude_slug(cwd: str) -> str:
    """Claude Code's project folder for a cwd: every character that is not a letter or a digit becomes `-`."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _iso_ts(text) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _one_line(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _texts(value) -> list[str]:
    """The plain strings of a message `content` (a string, or a list of `{type: text, text}` parts)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [c["text"] for c in value if isinstance(c, dict) and isinstance(c.get("text"), str)]
    return []


def _plain_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


class _LineFeed:
    """Folds a growing JSONL file into a small state, reading only the whole lines appended since the last read
    (same inode and not shorter; else from the start). A last line without its newline waits for the next read."""

    def __init__(self, new_state, fold):
        self.new_state, self.fold = new_state, fold
        self._files: dict[str, list] = {}

    def read(self, path: Path):
        try:
            st = path.stat()
        except OSError:
            return None
        hit = self._files.get(str(path))
        if hit is None or hit[0] != st.st_ino or st.st_size < hit[1]:
            hit = [st.st_ino, 0, self.new_state()]
        if st.st_size > hit[1]:
            try:
                with open(path, "rb") as fh:
                    fh.seek(hit[1])
                    for raw in fh:
                        if not raw.endswith(b"\n"):
                            break
                        hit[1] += len(raw)
                        try:
                            self.fold(hit[2], raw)
                        except (ValueError, TypeError, KeyError, AttributeError):
                            continue  # one odd line never stops the read
            except OSError:
                return hit[2] if str(path) in self._files else None
        self._files[str(path)] = hit
        return hit[2]


_SESSION_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _title_state() -> dict:
    return {"custom": "", "ai": ""}


def _title_fold(s: dict, raw: bytes) -> None:
    """One transcript line for a Claude Code session's name: its last `custom-title` (the person renamed it in Claude
    Code) and last `ai-title` (Claude Code's own title). Only lines naming one of the two are parsed."""
    if b'"custom-title"' not in raw and b'"ai-title"' not in raw:
        return
    o = json.loads(raw)
    if not isinstance(o, dict):
        return
    if o.get("type") == "custom-title" and isinstance(o.get("customTitle"), str) and o["customTitle"].strip():
        s["custom"] = _one_line(o["customTitle"], CLI_TITLE)
    elif o.get("type") == "ai-title" and isinstance(o.get("aiTitle"), str) and o["aiTitle"].strip():
        s["ai"] = _one_line(o["aiTitle"], CLI_TITLE)


def _claude_state() -> dict:
    return {"sid": None, "cwd": None, "first": None, "title": None, "model": None, "tasks": {}, "notes": {}}


def _claude_fold(s: dict, raw: bytes) -> None:
    """One line of a Claude Code session transcript. Only lines that can matter are parsed: Agent/Task calls of
    the main thread, their tool results, task notifications and status, the AI title, and the first stamped line."""
    if _API_REQUEST.match(raw):
        return  # request snapshots repeat every tool name; never a call
    call = b'"tool_use"' in raw and _TASK_CALL.search(raw) is not None
    result = bool(s["tasks"]) and b'"tool_result"' in raw and any(
        m.decode("utf-8", "replace") in s["tasks"] for m in _TOOL_RESULT_ID.findall(raw))
    note = b"<task-notification>" in raw
    status = b'"task_status"' in raw
    title = b'"ai-title"' in raw
    head = s["first"] is None and b'"timestamp"' in raw
    if not (call or result or note or status or title or head):
        return
    o = json.loads(raw)
    if not isinstance(o, dict):
        return
    ts = _iso_ts(o.get("timestamp"))
    if s["first"] is None and ts is not None:
        s["first"] = ts
    if s["sid"] is None and isinstance(o.get("sessionId"), str):
        s["sid"] = o["sessionId"]
    if s["cwd"] is None and isinstance(o.get("cwd"), str):
        s["cwd"] = o["cwd"]
    if o.get("type") == "ai-title" and isinstance(o.get("aiTitle"), str) and o["aiTitle"].strip():
        s["title"] = _one_line(o["aiTitle"], CLI_TITLE)
    msg = o.get("message") if isinstance(o.get("message"), dict) else {}
    content = msg.get("content")
    if call and o.get("type") == "assistant" and not o.get("isSidechain") and isinstance(content, list):
        if isinstance(msg.get("model"), str) and not msg["model"].startswith("<"):
            s["model"] = msg["model"]
        for c in content:
            if not (isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") in _CLAUDE_TOOLS
                    and isinstance(c.get("id"), str)):
                continue
            inp = c.get("input") if isinstance(c.get("input"), dict) else {}
            s["tasks"][c["id"]] = {"label": _one_line(inp.get("description") or "", CLI_TITLE),
                                   "type": str(inp.get("subagent_type") or ""),
                                   "alias": str(inp.get("model") or ""), "started": ts}
    if result and isinstance(content, list):
        tur = o.get("toolUseResult") if isinstance(o.get("toolUseResult"), dict) else {}
        for c in content:
            if not (isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in s["tasks"]):
                continue
            t = s["tasks"][c["tool_use_id"]]
            if isinstance(tur.get("agentId"), str):
                t["agent"] = tur["agentId"]
            if isinstance(tur.get("resolvedModel"), str) and tur["resolvedModel"]:
                t["resolved"] = tur["resolvedModel"]
            if tur.get("status") in ("async_launched", "teammate_spawned") and not c.get("is_error"):
                t["launched"] = True  # a background agent: its end arrives later as a task notification
            else:
                t["result"] = {"error": bool(c.get("is_error")),
                               "text": _one_line(_claude_answer(tur, c), SUMMARY_MAX), "ended": ts}
    if note:
        att = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
        blob = "\n".join(_texts(content) + _texts(o.get("content")) + _texts(att.get("prompt")))
        for block in _NOTE.findall(blob):
            tags: dict[str, str] = {}
            for k, v in _NOTE_TAG.findall(block):
                tags.setdefault(k, v.strip())
            state = _NOTE_STATE.get(tags.get("status", ""))
            if not state:
                continue
            item = {"state": state, "text": _one_line(tags.get("result") or tags.get("summary") or "", SUMMARY_MAX),
                    "ended": ts}
            for key in (tags.get("task-id"), tags.get("tool-use-id")):
                if not key:
                    continue
                old = s["notes"].get(key)
                if old and old["state"] == state:
                    if old["text"] or not item["text"]:
                        continue
                    item = {**item, "ended": old["ended"] or ts}
                s["notes"][key] = item
    if status:
        att = o.get("attachment") if isinstance(o.get("attachment"), dict) else {}
        state = _NOTE_STATE.get(str(att.get("status") or ""))
        if att.get("type") == "task_status" and state and isinstance(att.get("taskId"), str):
            s["notes"].setdefault(att["taskId"], {"state": state, "text": "", "ended": ts})


_TOOLS_USED = re.compile(r"<tools-used-before-summary>.*?</tools-used-before-summary>", re.S)


def _claude_answer(tur: dict, block: dict) -> str:
    """A subagent's own words: the text of `toolUseResult.content` without the `<tools-used-before-summary>` block,
    never Claude Code's `[Subagent hand-back]` frame around them; else the tool result's text after that frame."""
    own = _TOOLS_USED.sub("", "\n".join(_texts(tur.get("content")))).strip()
    if not own:
        whole = "\n".join(_texts(block.get("content")))
        own = whole.split("The report follows:", 1)[-1].split("\nagentId:", 1)[0]
        own = _TOOLS_USED.sub("", own)
    return own.replace("```", " ").strip()


def _claude_sub_tail(path: Path) -> dict:
    """Model, stop reason and last words of a subagent transcript, from its last assistant line in the tail."""
    out: dict = {}
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - CLI_TAIL))
            tail = fh.read()
        out["mtime"] = path.stat().st_mtime
    except OSError:
        return out
    for raw in reversed(tail.split(b"\n")):
        if not _ASSISTANT.search(raw):
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            continue  # the first, cut line of the tail
        msg = o.get("message") if isinstance(o, dict) and isinstance(o.get("message"), dict) else {}
        if "stop" not in out:
            out["stop"] = msg.get("stop_reason")
            out["text"] = _one_line("\n".join(_texts(msg.get("content"))), SUMMARY_MAX)
        model = msg.get("model")
        if isinstance(model, str) and model and not model.startswith("<"):  # "<synthetic>" marks an error line
            out["model"] = model
            break
    return out


def _codex_state() -> dict:
    return {"meta": None, "start": None, "model": None, "effort": None, "status": None, "started": None,
            "ended": None, "text": None, "reason": None}


def _codex_fold(s: dict, raw: bytes) -> None:
    """One line of a Codex rollout: the session meta (first line), then the child's own turn contexts and task
    events. A spawned child's file starts with a copy of its parent's history; lines before its
    `subagent_history_start_ordinal` are that copy and are skipped."""
    if s["meta"] is None:
        o = json.loads(raw)
        pl = o.get("payload") if isinstance(o, dict) and o.get("type") == "session_meta" else None
        if not isinstance(pl, dict) or not isinstance(pl.get("id"), str):
            s["meta"] = {}
            return
        src = pl.get("source")
        spawn = (src.get("subagent") or {}).get("thread_spawn") if isinstance(src, dict) else None
        meta = {"id": pl["id"], "started": _iso_ts(pl.get("timestamp")) or _iso_ts(o.get("timestamp")),
                "cwd": pl.get("cwd") if isinstance(pl.get("cwd"), str) else ""}
        if isinstance(spawn, dict) and isinstance(spawn.get("parent_thread_id"), str):
            meta["parent"] = spawn["parent_thread_id"]
            meta["path"] = str(spawn.get("agent_path") or pl.get("agent_path") or "")
            meta["nick"] = str(spawn.get("agent_nickname") or pl.get("agent_nickname") or "")
        s["meta"] = meta
        if isinstance(pl.get("subagent_history_start_ordinal"), int):
            s["start"] = pl["subagent_history_start_ordinal"]
        return
    if not s["meta"] or not any(k in raw[:CLI_HEAD] for k in _CODEX_EVENTS):
        return
    o = json.loads(raw)
    if not isinstance(o, dict):
        return
    if s["start"] is not None and isinstance(o.get("ordinal"), int) and o["ordinal"] < s["start"]:
        return
    pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
    ts = _iso_ts(o.get("timestamp"))
    if o.get("type") == "turn_context":
        if isinstance(pl.get("model"), str) and pl["model"]:
            s["model"] = pl["model"]
        if isinstance(pl.get("effort"), str) and pl["effort"]:
            s["effort"] = pl["effort"]
    elif pl.get("type") == "task_started":
        s["status"] = "running"
        if s["started"] is None:
            s["started"] = _num(pl.get("started_at")) or ts
    elif pl.get("type") == "task_complete":
        s["status"] = "done"
        s["ended"] = _num(pl.get("completed_at")) or ts
        s["text"] = _one_line(pl.get("last_agent_message") or "", SUMMARY_MAX)
        s["reason"] = None
    elif pl.get("type") == "turn_aborted":
        s["status"] = "cancelled"
        s["ended"] = _num(pl.get("completed_at")) or ts
        s["reason"] = _one_line(pl.get("reason") or "", 120)


def _run_of(nodes: list[dict]) -> tuple[str, float | None]:
    """Run state from its sub-runs (as a delegate fan-out), and its end when it is not running."""
    states = [n["state"] for n in nodes]
    state = ("running" if "running" in states else "failed" if "failed" in states
             else "cancelled" if "cancelled" in states else "done")
    ends = [n["ended"] for n in nodes if n.get("ended") is not None]
    return state, (max(ends) if ends and state != "running" else None)


def _cli_node(nid: str, label: str, state: str, started, ended, *, summary: str = "", reason: str = "") -> dict:
    att: dict = {"n": 1, "outcome": "no result" if reason == "no result" else _OUTCOME[state]}
    node: dict = {"id": nid, "label": label, "deps": [], "layer": 0, "state": state, "attempts": [att]}
    if started is not None:
        att["started"] = node["started"] = started
    if ended is not None and state != "running":
        att["ended"] = node["ended"] = ended
    if reason:
        att["reason"] = reason
    if summary or reason:
        node["summary"] = summary or reason
    return node


class CliRuns:
    """`runs.cli`: CLI agent sessions on this machine that ran sub-runs, as AgentRuns. Claude Code keeps one
    transcript per session in `<claude>/projects/<cwd slug>/<id>.jsonl` (subagents in `<id>/subagents/`), Codex one
    rollout per thread in `<codex>/sessions/YYYY/MM/DD/`, a spawned sub-agent being its own thread whose session
    meta names its parent. OmO keeps one record per subagent in `<omo>/agent/projects/*/senpi-task/tasks/`. pi,
    omp and grok keep no sub-run record omher can read; they return no runs."""

    def __init__(self, homes: dict[str, Path] | None = None, clock=time.time):
        self.homes = {**cli_homes(), **(homes or {})}
        self.clock = clock
        self._claude = _LineFeed(_claude_state, _claude_fold)
        self._codex = _LineFeed(_codex_state, _codex_fold)
        self._titles = _LineFeed(_title_state, _title_fold)
        self._small: dict[str, tuple[tuple, object]] = {}
        self._last: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ---- small cached reads
    def _cached(self, path: Path, read):
        try:
            st = path.stat()
        except OSError:
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        hit = self._small.get(str(path))
        if hit and hit[0] == stamp:
            return hit[1]
        value = read(path)
        self._small[str(path)] = (stamp, value)
        return value

    @staticmethod
    def _json(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ---- status
    def agents(self) -> dict[str, str]:
        out = {"claude": "found" if (self.homes["claude"] / "projects").is_dir() else "not_installed",
               "codex": "found" if (self.homes["codex"] / "sessions").is_dir() else "not_installed"}
        omo = self.homes.get("omo")
        out["omo"] = "found" if omo and (omo / "agent" / "projects").is_dir() else "not_installed"
        for name in ("pi", "omp", "grok"):
            out[name] = "no_adapter" if self.homes[name].exists() else "not_installed"
        return out

    # ---- Claude Code
    def _claude_files(self, cwd: str | None, since: float) -> list[Path]:
        root = self.homes["claude"] / "projects"
        if not root.is_dir() or root.is_symlink():
            return []
        dirs = [root / claude_slug(cwd)] if cwd else None
        files: list[tuple[float, Path]] = []
        try:
            for d in dirs if dirs is not None else [e for e in os.scandir(root) if e.is_dir(follow_symlinks=False)]:
                d = Path(d)
                if not d.is_dir() or d.is_symlink():
                    continue
                for e in os.scandir(d):
                    if e.name.endswith(".jsonl") and e.is_file(follow_symlinks=False):
                        m = e.stat().st_mtime
                        if m >= since:
                            files.append((m, Path(e.path)))
        except OSError:
            return []
        files.sort(key=lambda x: -x[0])
        return [p for _, p in files[:CLI_FILES]]

    def _claude_subagents(self, folder: Path) -> dict[str, dict]:
        """{agent id or tool_use id: {meta…, tail…}} from `<session>/subagents/agent-<id>.meta.json` + `.jsonl`."""
        out: dict[str, dict] = {}
        if not folder.is_dir() or folder.is_symlink():
            return out
        try:
            names = [e.name for e in os.scandir(folder)]
        except OSError:
            return out
        for name in names:
            if not (name.startswith("agent-") and name.endswith(".meta.json")):
                continue
            meta_p = folder / name
            if not _plain_file(meta_p):
                continue
            meta = self._cached(meta_p, self._json)
            if not isinstance(meta, dict):
                continue
            aid = name[len("agent-"):-len(".meta.json")]
            log = folder / f"agent-{aid}.jsonl"
            info = {"finished": meta.get("finished") is True,
                    "meta_model": meta["model"] if isinstance(meta.get("model"), str) else "",
                    "type": str(meta.get("agentType") or "")}
            if _plain_file(log):
                info.update(self._cached(log, _claude_sub_tail) or {})
            out[aid] = info
            if isinstance(meta.get("toolUseId"), str):
                out.setdefault(meta["toolUseId"], info)
        return out

    def _claude_run(self, path: Path, now: float) -> dict | None:
        s = self._claude.read(path)
        if not s or not s["tasks"] or not s["sid"]:
            return None
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        subs = self._claude_subagents(path.parent / path.stem / "subagents")
        nodes = []
        for tid, t in s["tasks"].items():
            sub = subs.get(t.get("agent") or "") or subs.get(tid) or {}
            res, note = t.get("result"), s["notes"].get(t.get("agent") or "") or s["notes"].get(tid)
            moved = max(mtime, sub.get("mtime") or 0.0)
            summary = reason = ""
            ended = None
            if res and res["error"]:
                state, reason, ended = "failed", res["text"] or "error", res["ended"]
            elif res:
                state, summary, ended = "done", res["text"], res["ended"]
            elif note:
                state, ended = note["state"], note["ended"]
                if state == "done":
                    summary = note["text"] or sub.get("text", "")
                else:
                    reason = note["text"] or state
            elif sub.get("finished"):
                state, summary, ended = "done", sub.get("text", ""), sub.get("mtime")
            elif now - moved <= CLI_STALE:
                state = "running"
            elif sub.get("stop") == "end_turn":
                state, summary, ended = "done", sub.get("text", ""), sub.get("mtime")  # an idle teammate
            else:
                state, reason, ended = "failed", "no result", moved
            kind = t["type"].split(":")[-1] or sub.get("type", "").split(":")[-1]
            node = _cli_node(tid, t["label"] or kind or "Subagent", state, t["started"], ended,
                             summary=summary, reason=reason)
            # the child's own transcript first, then what Claude Code resolved, the meta, the call's alias, the parent
            # an alias ("opus") the parent's own model id spells out reads as that id
            alias = s["model"] if t["alias"] and s["model"] and t["alias"] in s["model"] else t["alias"]
            for m in (sub.get("model"), t.get("resolved"), sub.get("meta_model"), alias, s["model"]):
                if isinstance(m, str) and m and m != "inherit":
                    node["model"] = m
                    break
            node["executor"] = "claude"
            if kind:
                node["lane"] = kind
            nodes.append(node)
        state, ended = _run_of(nodes)
        run = {"id": f"claude:{s['sid']}", "kind": "claude-task", "agent": "claude",
               "owner": {"type": "session", "id": s["sid"]}, "title": s["title"] or "Claude Code session",
               "cwd": s["cwd"] or "", "state": state, "nodes": nodes,
               "started": s["first"] if s["first"] is not None else mtime,
               "updated": max([mtime] + [n.get("ended") or 0.0 for n in nodes])}
        if ended is not None:
            run["ended"] = ended
        return run

    def claude(self, cwd: str | None, since: float, now: float) -> list[dict]:
        runs = []
        for path in self._claude_files(cwd, since):
            run = self._claude_run(path, now)
            if run is None or run["started"] < since:
                continue
            if cwd and _norm(run["cwd"] or "") != _norm(cwd):
                continue  # the folder slug is lossy ("/a/b-c" and "/a/b/c" share it)
            runs.append(run)
        return runs

    # ---- Codex
    def _codex_rollouts(self, since: float) -> list[Path]:
        root = self.homes["codex"] / "sessions"
        if not root.is_dir() or root.is_symlink():
            return []
        first_day = time.strftime("%Y/%m/%d", time.localtime(since - 86400)) if since > 86400 else "0000/00/00"
        out = []
        for day in sorted(root.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]")):
            rel = day.relative_to(root).as_posix()
            if rel < first_day or day.is_symlink() or day.parent.is_symlink():
                continue
            out.extend(p for p in day.glob("rollout-*.jsonl") if _plain_file(p))
        return out

    def _codex_titles(self) -> dict[str, str]:
        idx = self.homes["codex"] / "session_index.jsonl"

        def read(path: Path) -> dict[str, str]:
            names: dict[str, str] = {}
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                return names
            for line in lines:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if isinstance(o, dict) and isinstance(o.get("id"), str) and isinstance(o.get("thread_name"), str):
                    names[o["id"]] = _one_line(o["thread_name"], CLI_TITLE)
            return names
        return (self._cached(idx, read) or {}) if _plain_file(idx) else {}

    def title(self, agent: str, session: str, cwd: str | None = None) -> str:
        """The title a Claude Code session or Codex thread carries in the agent's own files, or "": Claude Code's
        last `custom-title` (a rename in Claude Code) else its last `ai-title`, read from the session's transcript
        (`<claude>/projects/<cwd slug>/<id>.jsonl`, any project folder when the cwd is unknown or moved); Codex's
        thread name from `session_index.jsonl`. Reads only those title lines, never a message."""
        if agent == "codex":
            return self._codex_titles().get(session, "")
        if agent != "claude":
            return ""
        root = self.homes["claude"] / "projects"
        if not root.is_dir() or root.is_symlink():
            return ""
        name = f"{session}.jsonl"
        path = root / claude_slug(cwd) / name if cwd else None
        if path is None or not _plain_file(path):
            try:
                with os.scandir(root) as it:
                    path = next((Path(d.path) / name for d in it
                                 if d.is_dir(follow_symlinks=False) and _plain_file(Path(d.path) / name)), None)
            except OSError:
                path = None
        if path is None:
            return ""
        st = self._titles.read(path)  # only the lines appended since the last look
        return (st["custom"] or st["ai"]) if st else ""

    def _codex_meta(self, path: Path) -> dict | None:
        """The first line only (immutable once written): cached per file without reading the rest."""
        def read(p: Path):
            s = _codex_state()
            try:
                with open(p, "rb") as fh:
                    _codex_fold(s, fh.readline())
            except (OSError, ValueError, TypeError, AttributeError):
                return None
            return s["meta"] or None
        hit = self._small.get(f"meta:{path}")
        if hit:
            return hit[1]
        meta = read(path)
        if meta is not None:
            self._small[f"meta:{path}"] = ((), meta)
        return meta

    def codex(self, cwd: str | None, since: float, now: float) -> list[dict]:
        metas: dict[str, tuple[Path, dict]] = {}
        for p in self._codex_rollouts(since):
            m = self._codex_meta(p)
            if m:
                metas[m["id"]] = (p, m)
        kids = {i: pm for i, pm in metas.items() if pm[1].get("parent")}

        def root_of(i: str) -> str:
            seen = set()
            while i in kids and i not in seen:
                seen.add(i)
                i = kids[i][1]["parent"]
            return i
        groups: dict[str, list[str]] = {}
        for i in kids:
            groups.setdefault(root_of(i), []).append(i)
        titles = self._codex_titles()

        def newest(ids: list[str]) -> float:
            out = 0.0
            for i in ids:
                try:
                    out = max(out, metas[i][0].stat().st_mtime)
                except OSError:
                    pass
            return out
        order = sorted(groups, key=lambda r: -newest(groups[r] + ([r] if r in metas else [])))
        runs = []
        for root in order[:CLI_FILES]:
            head = metas.get(root, (None, {}))[1]
            ids = sorted(groups[root], key=lambda i: metas[i][1].get("started") or 0.0)
            run_cwd = head.get("cwd") or metas[ids[0]][1].get("cwd") or ""
            started = head.get("started") or metas[ids[0]][1].get("started") or 0.0
            if started < since or (cwd and _norm(run_cwd) != _norm(cwd)):
                continue
            nodes = []
            for i in ids:
                path, meta = metas[i]
                s = self._codex.read(path) or _codex_state()
                try:
                    moved = path.stat().st_mtime
                except OSError:
                    moved = 0.0
                state, reason = s["status"] or "running", s["reason"] or ""
                ended = s["ended"]
                if state == "running" and now - moved > CLI_STALE:
                    state, reason, ended = "failed", "no result", moved
                name = (meta.get("path") or "").rstrip("/").rsplit("/", 1)[-1] or meta.get("nick") or "sub-agent"
                label = _one_line(name.replace("_", " ").replace("-", " "), CLI_TITLE)
                node = _cli_node(i, label[:1].upper() + label[1:], state, s["started"] or meta.get("started"), ended,
                                 summary=s["text"] or "", reason=reason)
                if meta["parent"] in groups[root]:
                    node["deps"] = [meta["parent"]]  # spawned by another sub-agent of this run
                node["model"] = s["model"] or ""
                if not node["model"]:
                    del node["model"]
                if s["effort"]:
                    node["effort"] = s["effort"]
                node["executor"] = "codex"
                nodes.append(node)
            layers = layer_of(nodes)
            for n in nodes:
                n["layer"] = layers[n["id"]]
            state, ended = _run_of(nodes)
            run = {"id": f"codex:{root}", "kind": "codex-sub", "agent": "codex",
                   "owner": {"type": "session", "id": root}, "title": titles.get(root) or "Codex session",
                   "cwd": run_cwd, "state": state, "nodes": nodes, "started": started,
                   "updated": max([newest(groups[root] + ([root] if root in metas else []))]
                                  + [n.get("ended") or 0.0 for n in nodes])}
            if ended is not None:
                run["ended"] = ended
            runs.append(run)
        return runs

    # ---- OmO
    def omo(self, cwd: str | None, since: float, now: float) -> list[dict]:
        """OmO's subagents: one record per subagent in `<omo>/agent/projects/<proj>/senpi-task/tasks/st_*.json`
        (name, task summary, model, status, times, final response), keyed by the session that started them
        (`root_session_id`, the id omher's OmO session reports). One run per session. Only these records are read,
        never the subagents' own transcripts (`children/`)."""
        home = self.homes.get("omo")
        root = home / "agent" / "projects" if home else None
        if root is None or not root.is_dir() or root.is_symlink():
            return []
        files: list[tuple[float, Path]] = []
        try:
            for proj in os.scandir(root):
                tasks = Path(proj.path) / "senpi-task" / "tasks"
                if not proj.is_dir(follow_symlinks=False) or not tasks.is_dir() or tasks.is_symlink():
                    continue
                for e in os.scandir(tasks):
                    if _OMO_TASK.match(e.name) and e.is_file(follow_symlinks=False):
                        m = e.stat().st_mtime
                        if m >= since:
                            files.append((m, Path(e.path)))
        except OSError:
            return []
        files.sort(key=lambda x: -x[0])
        groups: dict[str, list[dict]] = {}
        for _, p in files[:OMO_TASKS]:
            rec = self._cached(p, self._json)
            if not isinstance(rec, dict) or not isinstance(rec.get("root_session_id"), str):
                continue
            groups.setdefault(rec["root_session_id"], []).append(rec)
        runs = []
        for sid, recs in groups.items():
            recs.sort(key=lambda r: _iso_ts(r.get("created_at")) or 0.0)
            nodes = []
            for r in recs:
                state = _OMO_STATE.get(str(r.get("status") or ""), "running")
                started = _iso_ts(r.get("started_at")) or _iso_ts(r.get("created_at"))
                ended = _iso_ts(r.get("terminal_at"))
                moved = _iso_ts(r.get("updated_at")) or started or 0.0
                reason = ""
                if state == "running" and now - moved > CLI_STALE and ended is None:
                    state, reason, ended = "failed", "no result", moved
                elif state == "failed":
                    reason = _one_line(r.get("error") or r.get("failure") or "failed", 200)
                label = _one_line(r.get("task_summary") or r.get("description") or r.get("name") or "Subagent", CLI_TITLE)
                node = _cli_node(str(r.get("task_id") or len(nodes)), label, state, started, ended,
                                 summary=_one_line(r.get("final_response") or "", SUMMARY_MAX) if state == "done" else "",
                                 reason=reason)
                eff = r.get("effective_model") if isinstance(r.get("effective_model"), dict) else {}
                model = eff.get("model_id") or (r.get("model") if isinstance(r.get("model"), str) else "")
                if model:
                    node["model"] = model.rsplit("/", 1)[-1]
                if isinstance(eff.get("provider"), str) and eff["provider"]:
                    node["provider"] = eff["provider"]
                if isinstance(r.get("agent_type"), str) and r["agent_type"]:
                    node["lane"] = r["agent_type"]
                node["executor"] = "omo"
                nodes.append(node)
            run_cwd = ""
            spec = recs[0].get("spawn_spec")
            if isinstance(spec, dict) and isinstance(spec.get("cwd"), str):
                run_cwd = spec["cwd"]
            if cwd and run_cwd and _norm(run_cwd) != _norm(cwd):
                continue
            state, ended = _run_of(nodes)
            started = min([n["started"] for n in nodes if n.get("started") is not None] or [0.0])
            run = {"id": f"omo:{sid}", "kind": "session", "agent": "omo", "owner": {"type": "session", "id": sid},
                   "title": "OmO session", "cwd": run_cwd, "state": state, "nodes": nodes, "started": started,
                   "updated": max([_iso_ts(r.get("updated_at")) or 0.0 for r in recs] + [n.get("ended") or 0.0 for n in nodes])}
            if ended is not None:
                run["ended"] = ended
            runs.append(run)
        return runs

    # ---- ops
    def list(self, agent: str | None = None, cwd: str | None = None, since: float | None = None) -> dict:
        now = self.clock()
        since = now - CLI_WINDOW if since is None else float(since)
        with self._lock:
            runs: list[dict] = []
            if agent in (None, "claude"):
                runs += self.claude(cwd, since, now)
            if agent in (None, "codex"):
                runs += self.codex(cwd, since, now)
            if agent in (None, "omo"):
                runs += self.omo(cwd, since, now)
            runs.sort(key=lambda r: (r["state"] != "running", -r["updated"]))
            runs = runs[:CLI_RUNS]
            self._last.update({r["id"]: r for r in runs})
        return {"runs": [run_summary(r) for r in runs], "agents": self.agents()}

    def get(self, run_id: str) -> dict:
        agent = run_id.split(":", 1)[0]
        run = self._last.get(run_id)
        if run is None and agent in ("claude", "codex", "omo"):
            self.list(agent, None, 0.0)
            run = self._last.get(run_id)
        if run is None:
            raise BridgeError("not_found", f"no CLI run {run_id}")
        return {"run": run, "handoffs": {}}


# ---------------------------------------------------------------- accounts (coding-CLI logins on this computer)
#
# Settings › Accounts lists, per coding CLI, the login already on this computer (the CLI's own home: the
# "default" row) and the extra subscriptions added in omher, one folder each under ~/.omher/accounts/<cli>/<id>/
# that a new session uses as the CLI's home (CLAUDE_CONFIG_DIR, CODEX_HOME, PI_CODING_AGENT_DIR…). Logging in
# is always the CLI's own; the app runs it (Rust) and asks the CLI for its status. From here: Claude Code's
# signed-in email (`.claude.json` `oauthAccount.emailAddress`, no token lives there), whether a login file
# exists (a stat, never opened), and the usage records of rule 17. A local CLIProxyAPI's Claude logins are
# listed from its auth file NAMES only (the email CLIProxyAPI puts in each name); no auth file is ever opened.

ACCOUNT_CLIS = ("claude", "codex", "pi", "omp", "grok", "gemini")
_ACCOUNT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
_CPA_FILE = re.compile(r"^claude-[A-Za-z0-9@._+-]{1,120}\.json$")
# Files whose presence (stat only, never opened) means the CLI logged in there. Claude Code keeps its login in
# the OS keychain, so its mark is the signed-in email instead (see `_signed_in`).
_LOGIN_MARK = {"codex": ("auth.json",), "pi": ("auth.json",), "omp": ("agent.db",),
               "grok": ("auth.json", "user-settings.json"), "gemini": (".gemini/oauth_creds.json",)}
# Each CLI's own home on this computer (the "This computer" row).
_DEFAULT_HOME = {"claude": "", "codex": ".codex", "pi": ".pi/agent", "omp": ".omp/agent", "grok": ".grok",
                 "gemini": ""}


def omher_accounts_root(user_home: Path | None = None) -> Path:
    return (Path(user_home) if user_home else Path.home()) / ".omher" / "accounts"


def cpa_names(user_home: Path) -> list[str]:
    """The Claude auth file NAMES a local CLIProxyAPI holds (`claude-*.json` in its `auth-dir`), sorted. No
    auth file is opened: the names are listed, and the config only gives `auth-dir`."""
    if not (user_home / ".cli-proxy-api" / "config.yaml").is_file():
        return []
    cfg = _load_yaml(user_home / ".cli-proxy-api" / "config.yaml")
    oauth = cfg.get("oauth") if isinstance(cfg.get("oauth"), dict) else {}
    auth_dir = oauth.get("auth-dir") or cfg.get("auth-dir") or "~/.cli-proxy-api"
    auth_dir = auth_dir if isinstance(auth_dir, str) else "~/.cli-proxy-api"
    cfg.clear()
    auth = Path(auth_dir.replace("~", str(user_home), 1) if auth_dir.startswith("~") else auth_dir)
    try:
        return sorted(p.name for p in auth.iterdir() if _CPA_FILE.match(p.name)) if auth.is_dir() else []
    except OSError:
        return []


def cpa_count(user_home: Path) -> int:
    """How many Claude logins a local CLIProxyAPI holds: auth file NAMES counted, no file opened."""
    return len(cpa_names(user_home))


_CPA_EMAIL = re.compile(r"^claude-(?:[0-9a-f]{8}-)?([A-Za-z0-9._+-]{1,64}@[A-Za-z0-9.-]{1,60}\.[A-Za-z]{2,24})\.json$")


def cpa_email(name: str) -> str:
    """The email CLIProxyAPI puts in an auth file's NAME (`claude-<8 hex>-<email>.json` or `claude-<email>.json`),
    else "". The file itself is never opened."""
    m = _CPA_EMAIL.match(name)
    return m.group(1) if m else ""


def _with_cpa(rows: list[dict], user_home: Path) -> list[dict]:
    """Claude rows plus a local CLIProxyAPI's logins, from its auth file names only. A login whose email is already
    a row (Claude Code's own, or an omher account) marks that row `in_cpa`; every other one is a read-only row
    (`source: cpa`, id `cpa:<n>`, never a folder, never usable for a session) with no usage: CLIProxyAPI writes no
    usage record on this computer."""
    seen = {r["email"].lower(): r for r in rows if r.get("email")}
    out = list(rows)
    for n, name in enumerate(cpa_names(user_home), 1):
        email = cpa_email(name)
        if email and email.lower() in seen:
            seen[email.lower()]["in_cpa"] = True
            continue
        row = {"id": f"cpa:{n}", "label": "", "email": email, "state": "ready", "dir": None, "usage": None,
               "source": "cpa"}
        out.append(row)
        if email:
            seen[email.lower()] = row
    return out


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_active(root: Path) -> dict:
    data = _read_json(root / "active.json")
    return {k: v for k, v in data.items() if k in ACCOUNT_CLIS and isinstance(v, str)}


def _claude_email(home_dir: Path) -> str:
    """The signed-in email from Claude Code's own `.claude.json` (`oauthAccount.emailAddress`; no token lives there)."""
    acct = _read_json(home_dir / ".claude.json").get("oauthAccount")
    email = acct.get("emailAddress") if isinstance(acct, dict) else None
    return email if isinstance(email, str) else ""


def _signed_in(cli: str, folder: Path) -> bool:
    if cli == "claude":
        return bool(_claude_email(folder))
    return any((folder / m).exists() for m in _LOGIN_MARK[cli])


def _account_usage(cli: str, folder: Path, user_home: Path, now: float) -> dict | None:
    if cli == "claude":
        return _claude_usage(user_home, now, root=folder / "projects")
    if cli == "codex":
        return _codex_usage(user_home, now, root=folder / "sessions")
    return None


def _text(value) -> str:
    """A label as the person typed it: a string, or "" for anything else (never `str()` of a dict)."""
    return value[:40] if isinstance(value, str) else ""


def _default_row(cli: str, user_home: Path, usage: dict | None, label: str, which) -> dict:
    """The CLI's own login on this computer."""
    if cli == "claude":
        email = _claude_email(user_home)
        signed = bool(email)
    else:
        email = ""
        home = _DEFAULT_HOME[cli]
        signed = _signed_in(cli, user_home / home) if home else bool(which(cli))
    return {"id": "default", "label": label, "email": email, "state": "ready" if signed else "login",
            "dir": None, "usage": usage}


def _omher_rows(cli: str, user_home: Path, now: float, default_usage: dict | None, labels: dict, which) -> list[dict]:
    """The CLI's own login on this computer first, then each omher account folder in name order."""
    root = omher_accounts_root(user_home) / cli
    rows = [_default_row(cli, user_home, default_usage, _text(labels.get(cli)), which)]
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if not folder.is_dir() or folder.is_symlink() or not _ACCOUNT_ID.match(folder.name):
            continue
        meta = _read_json(folder / "account.json")
        rows.append({"id": folder.name, "label": _text(meta.get("label")),
                     "email": _claude_email(folder) if cli == "claude" else "",
                     "state": "ready" if _signed_in(cli, folder) else "login", "dir": str(folder),
                     "usage": _account_usage(cli, folder, user_home, now)})
    for r in rows:
        u = r["usage"]
        if r["state"] == "ready" and u and u.get("state") == "limited":
            r["state"] = "limited"
            r["resets_at"] = max((w["resets_at"] for w in u["windows"] if "resets_at" in w), default=None)
    return rows


def read_accounts(user_home: Path | None = None, *, now: float | None = None, which=None) -> dict:
    """Every coding CLI omher knows, with `installed` (on the bridge's PATH; the app re-checks in its own
    install folders) and its rows. Never a token: a label, Claude Code's signed-in email, a usage record."""
    import shutil
    user_home = Path(user_home) if user_home else Path.home()
    now = time.time() if now is None else now
    which = which or shutil.which
    usage = {p["id"]: p for p in read_usage(user_home, now=now, which=lambda _: None, with_accounts=False)["providers"]}
    root = omher_accounts_root(user_home)
    active = _read_active(root)
    labels = _read_json(root / "labels.json")
    cpa = cpa_count(user_home)
    groups = []
    for cli in ACCOUNT_CLIS:
        rows = _omher_rows(cli, user_home, now, usage.get(cli), labels, which)
        if cli == "claude":
            rows = _with_cpa(rows, user_home)
        ids = [r["id"] for r in rows if r.get("source") != "cpa"]
        current = active.get(cli) if active.get(cli) in ids else "default"
        for r in rows:
            if r["id"] == current and r["state"] == "ready":
                r["state"] = "active"
        group = {"cli": cli, "installed": bool(which(cli)), "active": current, "accounts": rows}
        if cli == "claude" and cpa:
            group["also"] = {"name": "CLIProxyAPI", "accounts": cpa}
        groups.append(group)
    return {"groups": groups}


def _account_folder(cli, account_id, user_home: Path | None = None) -> Path:
    """`~/.omher/accounts/<cli>/<id>`, refusing anything that is not exactly one plain folder name there."""
    if cli not in ACCOUNT_CLIS:
        raise BridgeError("bad_request", "unknown cli")
    if not isinstance(account_id, str) or not _ACCOUNT_ID.match(account_id) or account_id == "default":
        raise BridgeError("bad_request", "bad account id")
    base = omher_accounts_root(user_home) / cli
    folder = base / account_id
    if folder.parent != base or os.path.realpath(folder.parent) != os.path.realpath(base):
        raise BridgeError("bad_request", "bad account id")
    return folder


def _clean_label(label) -> str:
    return re.sub(r"\s+", " ", str(label or "")).strip()[:40]


def add_account(cli, label, user_home: Path | None = None) -> dict:
    """A new, empty account folder; the app then runs the CLI's own login with it as the CLI's home."""
    text = _clean_label(label)
    slug = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-.")[:40]
    if cli not in ACCOUNT_CLIS:
        raise BridgeError("bad_request", "unknown cli")
    base = omher_accounts_root(user_home) / str(cli)
    if not slug or slug == "default":
        n = 2
        while (base / f"account-{n}").exists():
            n += 1
        slug = f"account-{n}"
    elif (base / slug).exists():
        raise BridgeError("exists", f"an account named {slug} already exists")
    folder = _account_folder(cli, slug, user_home)
    folder.mkdir(parents=True, mode=0o700)
    (folder / "account.json").write_text(json.dumps({"label": text, "created_at": time.time()}), encoding="utf-8")
    return {"id": slug, "dir": str(folder)}


def label_account(cli, account_id, label, user_home: Path | None = None) -> None:
    """The person's own name for a row ("" clears it). The default row's label lives in labels.json."""
    text = _clean_label(label)
    root = omher_accounts_root(user_home)
    if account_id == "default":
        if cli not in ACCOUNT_CLIS:
            raise BridgeError("bad_request", "unknown cli")
        labels = {k: v for k, v in _read_json(root / "labels.json").items() if k in ACCOUNT_CLIS and isinstance(v, str)}
        labels[cli] = text
        _write_json(root, "labels.json", {k: v for k, v in labels.items() if v})
        return
    folder = _account_folder(cli, account_id, user_home)
    if folder.is_symlink() or not folder.is_dir():
        raise BridgeError("not_found", "no such account")
    meta = _read_json(folder / "account.json")
    meta = {"label": text, "created_at": meta.get("created_at") if isinstance(meta.get("created_at"), (int, float)) else None}
    (folder / "account.json").write_text(json.dumps(meta), encoding="utf-8")


def remove_account(cli, account_id, user_home: Path | None = None, *, only_if_empty: bool = False) -> None:
    """Deletes `~/.omher/accounts/<cli>/<id>/` and nothing else. `only_if_empty`: a cancelled sign-in, so
    refuse when the CLI did log in there."""
    import shutil
    folder = _account_folder(cli, account_id, user_home)
    if folder.is_symlink() or not folder.is_dir():
        raise BridgeError("not_found", "no such account")
    if only_if_empty and _signed_in(cli, folder):
        raise BridgeError("signed_in", "this account is signed in; remove it from its menu")
    shutil.rmtree(folder)
    root = omher_accounts_root(user_home)
    active = _read_active(root)
    if active.get(cli) == account_id:
        active.pop(cli)
        _write_json(root, "active.json", active)


def _write_json(root: Path, name: str, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{name}.tmp"
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.replace(tmp, root / name)


def set_active_account(cli, account_id, user_home: Path | None = None) -> None:
    """The account new sessions of `cli` start with. Running sessions are never touched."""
    if account_id != "default":
        if not _account_folder(cli, account_id, user_home).is_dir():
            raise BridgeError("not_found", "no such account")
    elif cli not in ACCOUNT_CLIS:
        raise BridgeError("bad_request", "unknown cli")
    root = omher_accounts_root(user_home)
    active = _read_active(root)
    active[cli] = account_id
    _write_json(root, "active.json", active)


# ---------------------------------------------------------------- transcript helpers

_AUTHOR_RE = re.compile(r"^\[(?P<author>[^\]|]+?)\s*\|[^\]]*\]\s*(?P<rest>.*)$", re.DOTALL)


def split_author(text: str) -> tuple[str | None, str]:
    """``[김희망 (Khope) | Slack user <@U0…>] hi`` -> (``김희망 (Khope)``, ``hi``)."""
    m = _AUTHOR_RE.match(text or "")
    if not m:
        return None, text
    return m.group("author").strip() or None, m.group("rest")


# The argument a person recognises for each tool. Hermes' own `context` summarises (e.g. a two-command
# shell line becomes "date + 1 command"), which hides what actually ran.
_DETAIL_ARG = {
    "terminal": ("command",), "read_file": ("path", "file_path"), "write_file": ("path", "file_path"),
    "patch": ("path", "file_path"), "search_files": ("pattern", "query"), "web_search": ("query",),
    "web_extract": ("urls", "url"), "delegate_task": ("goal",), "skill_view": ("name",), "skill_use": ("name",),
    "browser_navigate": ("url",),
}


def tool_detail(tool: str, args: dict, context: str, n: int = 160) -> str:
    """One readable line for a tool call: the real command / path / query when the args carry it."""
    value = None
    for key in _DETAIL_ARG.get(tool, ()):
        v = args.get(key)
        if isinstance(v, list):
            v = v[0] if v and isinstance(v[0], str) else None
        if isinstance(v, str) and v.strip():
            value = v
            break
    text = value if value is not None else context
    if tool == "delegate_task" and value is None and isinstance(args.get("tasks"), list):
        goals = [t.get("goal") for t in args["tasks"] if isinstance(t, dict) and isinstance(t.get("goal"), str)]
        text = goals[0] + (f" (+{len(goals) - 1} more)" if len(goals) > 1 else "") if goals else context
    line = " ".join(str(text or "").split())
    return line if len(line) <= n else line[: n - 1] + "…"


# Hermes' `subagent.*` events of the bot's own turn (tui_gateway/tool_progress.py `_progress_subagent`), as one
# `subagent` UI event each: who the child is, what it works on, its state, its current step or its result line.
# Every text is clipped; a child's thinking text is never forwarded, only that it is thinking. Read-only: omher
# never assigns, steers or stops a subagent.
SUBAGENT_STATE = {"subagent.spawn_requested": "queued", "subagent.start": "running", "subagent.thinking": "thinking",
                  "subagent.tool": "running", "subagent.progress": "running"}
SUBAGENT_DONE = {"completed": "done", "complete": "done", "success": "done", "failed": "failed", "error": "failed",
                 "timeout": "failed", "stalled": "failed", "interrupted": "cancelled", "cancelled": "cancelled"}
SUBAGENT_GOAL, SUBAGENT_STEP, SUBAGENT_SUMMARY = 120, 120, 200


def subagent_fields(typ: str, p: dict) -> dict | None:
    """The UI fields of one `subagent.*` event, or None for one omher does not show (`subagent.text`, no id)."""
    sid = p.get("subagent_id")
    if typ not in SUBAGENT_STATE and typ != "subagent.complete" or not isinstance(sid, str) or not sid:
        return None
    goal = p.get("goal") if isinstance(p.get("goal"), str) else ""
    mark = DAG_MARK.search(goal)
    out: dict = {"id": _one_line(sid, 64), "index": p["task_index"] if isinstance(p.get("task_index"), int) else 0,
                 "count": p["task_count"] if isinstance(p.get("task_count"), int) else 1,
                 "goal": _one_line(DAG_MARK.sub("", goal), SUBAGENT_GOAL)}
    if mark:
        out["dag"] = {"run": mark.group(1), "node": mark.group(2)}
    for key, dst, n in (("delegation_id", "delegation", 64), ("model", "model", 80)):
        if isinstance(p.get(key), str) and p[key]:
            out[dst] = _one_line(p[key], n)
    if typ == "subagent.complete":
        out["state"] = SUBAGENT_DONE.get(str(p.get("status") or "completed"), "done")
        text = p.get("summary") or p.get("text")
        if isinstance(text, str) and text.strip():
            out["summary"] = _one_line(text, SUBAGENT_SUMMARY)
        if isinstance(p.get("duration_seconds"), (int, float)) and not isinstance(p.get("duration_seconds"), bool):
            out["seconds"] = round(float(p["duration_seconds"]), 1)
        return out
    out["state"] = SUBAGENT_STATE[typ]
    if typ == "subagent.tool":
        if isinstance(p.get("tool_name"), str) and p["tool_name"]:
            out["tool"] = _one_line(p["tool_name"], 40)
        step = p.get("tool_preview") or p.get("text")
        if isinstance(step, str) and step.strip():
            out["step"] = _one_line(step, SUBAGENT_STEP)
    elif typ == "subagent.progress" and isinstance(p.get("text"), str) and p["text"].strip():
        out["step"] = _one_line(p["text"].lstrip("🔀 "), SUBAGENT_STEP)
    return out


def dag_parts(args: dict) -> list[dict]:
    """The `[dag:<run>/<node>]` parts a delegate_task call hands out (its `goal` or each task's), in order."""
    goals = [args.get("goal")] + [t.get("goal") for t in args.get("tasks") or [] if isinstance(t, dict)]
    out: list[dict] = []
    for g in goals:
        for m in DAG_MARK.finditer(g if isinstance(g, str) else ""):
            part = {"run": m.group(1), "node": m.group(2)}
            if part not in out:
                out.append(part)
    return out


def read_origins(profile_dir: Path, ids: list[str]) -> dict[str, dict]:
    """Where each session lives (platform, channel name, ids) from the profile's own state.db, opened
    read-only. `session.list` carries no origin, and without it a session cannot link back to its thread."""
    return {sid: v["origin"] for sid, v in read_session_facts(profile_dir, ids).items() if "origin" in v}


def read_session_facts(profile_dir: Path, ids: list[str]) -> dict[str, dict]:
    """Per session: its origin and the bot's last answer there (`last_reply`, `last_reply_at`), read in two
    queries from the profile's state.db, opened read-only. Nothing is written."""
    import sqlite3
    db = profile_dir / "state.db"
    if not ids or not db.is_file():
        return {}
    marks = ",".join("?" * len(ids))
    try:
        con = sqlite3.connect(ro_uri(db), uri=True, timeout=1.0)
        try:
            origins = con.execute(f"SELECT id, origin_json FROM sessions WHERE id IN ({marks})", ids).fetchall()
            try:
                replies = con.execute(
                    "SELECT m.session_id, m.content, m.timestamp FROM messages m JOIN ("
                    "SELECT session_id, MAX(id) AS mid FROM messages WHERE role = 'assistant' AND content IS NOT NULL"
                    f" AND TRIM(content) <> '' AND session_id IN ({marks}) GROUP BY session_id) x ON m.id = x.mid",
                    ids).fetchall()
            except sqlite3.Error:
                replies = []
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    out: dict[str, dict] = {}
    for sid, raw in origins:
        try:
            origin = json.loads(raw) if raw else None
        except ValueError:
            origin = None
        if isinstance(origin, dict):
            out.setdefault(sid, {})["origin"] = origin
    for sid, content, ts in replies:
        text = reply_gist(content if isinstance(content, str) else "")
        if text:
            out.setdefault(sid, {}).update(last_reply=text, last_reply_at=float(ts or 0.0))
    return out


_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MENTION = re.compile(r"<[@#!][^>]*>")
# ASCII URL characters only (RFC 3986), so a URL stops at the Korean particle glued to it ("…/2695에서").
_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&()*+,;=%]+")
_URL_TAIL = ".,;:!?*_~"


def _split_url(raw: str) -> tuple[str, str]:
    """(url, tail): sentence punctuation and markdown marks after a URL are not part of it; a closing
    bracket is only when the URL leaves it unbalanced (`(see https://x.y/a)` vs `…/wiki/Foo_(bar)`)."""
    url = raw
    while url:
        if url[-1] in _URL_TAIL:
            url = url[:-1]
        elif url[-1] == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        elif url[-1] == "]" and url.count("]") > url.count("["):
            url = url[:-1]
        else:
            break
    return url, raw[len(url):]


def _short_url(url: str) -> str:
    """A bare URL inside a sentence stays readable instead of leaving a hole ("… 에서 열립니다"):
    `https://omher.app/docs/skills/` -> `omher.app/docs/skills`; a long path is cut to its host. The query
    and fragment are always dropped: they carry tokens (`?token=…`), not words."""
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url, flags=re.I)
    u = re.split(r"[?#]", u, maxsplit=1)[0].rstrip("/")
    u = re.sub(r"^www\.", "", u)
    return u if len(u) <= 40 else u.split("/", 1)[0]


def _media_names(text: str) -> tuple[str, list[str]]:
    """The answer without its whole `MEDIA:` lines (read as `media_paths` reads them), and "📎 name" for each."""
    keep, names, fence = [], [], False
    for line in text.splitlines():
        if _MEDIA_FENCE.match(line):
            fence = not fence
        path = None if fence else media_paths(line)
        if path:
            names.append("\U0001f4ce " + re.split(r"[\\/]", path[0])[-1])
        else:
            keep.append(line)
    return "\n".join(keep), names


def reply_gist(text: str, n: int = 220) -> str:
    """The first paragraph of an answer as plain text: markdown marks and mentions removed, bare URLs
    shortened, clipped at a sentence end when one is near. Files the bot sent (`MEDIA:` lines) follow as
    "📎 name", never as a path."""
    text, names = _media_names(text or "")
    para = next((p for p in re.split(r"\n\s*\n", text) if p.strip()), "")
    t = _MD_LINK.sub(r"\1", para)
    t = _MENTION.sub("", t)
    # file names sit behind placeholders too, so the markdown strip keeps their underscores
    urls: list[str] = list(names)
    t = " ".join([t, *(f"\x00{i}\x00" for i in range(len(names)))])

    def hold(m: "re.Match[str]") -> str:
        # URLs sit behind placeholders while markdown marks are stripped, so `foo_bar` keeps its underscore
        url, tail = _split_url(m.group(0))
        urls.append(_short_url(url))
        return f"\x00{len(urls) - 1}\x00{tail}"

    t = _URL.sub(hold, t)
    t = re.sub(r"^\s*(#+|[-*])\s+", "", t, flags=re.M)
    t = re.sub(r"[*_`~]+", "", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: urls[int(m.group(1))], t)
    t = " ".join(t.split())
    if len(t) <= n:
        return t
    cut = t[:n]
    end = max(cut.rfind(". "), cut.rfind("다. "), cut.rfind("요. "))
    return cut[: end + 1].rstrip() if end > n * 0.5 else cut.rstrip() + "…"


def origin_link(source: str, origin: dict) -> tuple[str | None, str | None]:
    """(url, place) for a session's origin: a link that opens the thread in its own app, and a short
    place name ("#product-opengateway", "#cron"). Either may be None."""
    s = lambda k: str(origin.get(k) or "").strip()
    chat, thread, guild, name = s("chat_id"), s("thread_id"), s("guild_id") or s("scope_id"), s("chat_name")
    url = place = None
    if source == "slack" and chat:
        url = f"slack://channel?team={guild}&id={chat}" if guild else None
        if thread and re.fullmatch(r"\d+\.\d+", thread) and guild:
            url = f"slack://channel?team={guild}&id={chat}&thread_ts={thread}"
        place = f"#{name}" if name and not name.startswith("#") else (name or None)
    elif source == "discord" and chat and guild:
        url = f"https://discord.com/channels/{guild}/{chat}"
        parts = [p.strip() for p in name.split(" / ")] if name else []
        place = parts[1] if len(parts) >= 2 else (parts[0] if parts else None)
    elif source == "telegram" and chat:
        place = name or None
    return url, place


REPLY_PLATFORMS = frozenset({"slack", "discord", "telegram"})
_REF_ID = re.compile(r"-?[A-Za-z0-9._]{1,64}")


def reply_target(origin: dict) -> tuple[str, str] | None:
    """(target, label) for asking the bot to post in a session's thread: Hermes' own send target
    (`platform:chat_id[:thread_id]`, the form Hermes' own send command and messaging tool take) and a
    short quote-free name for it. None when the origin names no messenger thread (cron, local, a missing
    or malformed id). omher only passes this reference to the bot; it never posts anything itself."""
    s = lambda k: str(origin.get(k) or "").strip()
    platform, chat, thread = s("platform").lower(), s("chat_id"), s("thread_id")
    if platform not in REPLY_PLATFORMS or not _REF_ID.fullmatch(chat) or (thread and not _REF_ID.fullmatch(thread)):
        return None
    target = f"{platform}:{chat}:{thread}" if thread else f"{platform}:{chat}"
    name = s("chat_name")
    if platform == "discord":  # "Guild / #channel / thread title" -> "#channel / thread title"
        parts = [x.strip() for x in name.split(" / ") if x.strip()]
        name = " / ".join(parts[1:]) if len(parts) >= 2 else (parts[0] if parts else "")
    elif platform == "slack" and name and not name.startswith("#") and s("chat_type") != "dm":
        name = f"#{name}"
    label = " ".join(name.replace('"', "'").split())[:80] or platform.capitalize()
    return target, label


LINK_PLACES_MAX = 500   # newest messenger sessions read for channel names


def read_link_places(profile_dir: Path) -> dict[str, dict[str, str]]:
    """Channel names the bot already knows, for naming Slack and Discord link chips: `{"slack": {channel id:
    "#name"}, "discord": {channel id: "#name"}}`, from the `origin_json` of the bot's own newest messenger
    sessions in its state.db, opened read-only. Only ids and names; no message is read, nothing is fetched."""
    import sqlite3
    db = profile_dir / "state.db"
    out: dict[str, dict[str, str]] = {"slack": {}, "discord": {}}
    if not db.is_file():
        return out
    try:
        con = sqlite3.connect(ro_uri(db), uri=True, timeout=1.0)
        try:
            rows = con.execute("SELECT origin_json FROM sessions WHERE origin_json IS NOT NULL AND (origin_json LIKE"
                               " '%\"slack\"%' OR origin_json LIKE '%\"discord\"%') ORDER BY rowid DESC LIMIT ?",
                               (LINK_PLACES_MAX,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    for (raw,) in rows:
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        platform = str(o.get("platform") or "").lower()
        chat, name = str(o.get("chat_id") or "").strip(), str(o.get("chat_name") or "").strip()
        if platform not in out or not _REF_ID.fullmatch(chat) or not name:
            continue
        if platform == "slack":
            if str(o.get("chat_type") or "") == "dm":
                continue
            place = name if name.startswith("#") else f"#{name}"
        else:  # "Guild / #channel / thread title": the channel; a thread's parent channel gets the name too
            parts = [x.strip() for x in name.split(" / ") if x.strip()]
            place = parts[1] if len(parts) >= 2 else parts[0]
            parent = str(o.get("parent_chat_id") or "").strip()
            if parent and _REF_ID.fullmatch(parent) and place.startswith("#"):
                out[platform].setdefault(parent, place)
        place = " ".join(place.split())[:60]
        out[platform].setdefault(chat, place)
    return out


def reply_block(target: str, label: str) -> str:
    """The one short block appended to a turn sent with a reply target: plain context the bot may act on."""
    kind = "thread" if target.count(":") >= 2 else "channel"
    return (f"[omher] Reply target: {target} ({kind} \"{label}\"). Post there only if the user asked; "
            f"use your own messaging tool or `hermes send --to {target}`.")


_REPLY_BLOCK = re.compile(r"\n*\[omher\] Reply target: (\S+) \((?:thread|channel) \"([^\"]*)\"\)\. Post there only if "
                          r"the user asked; use your own messaging tool or `hermes send --to \S+`\.\s*$")


def split_reply_block(text: str) -> tuple[str, dict | None]:
    """A user row sent with a reply target, back as (what the person typed, {target, label})."""
    m = _REPLY_BLOCK.search(text or "")
    if not m:
        return text, None
    return text[: m.start()].rstrip(), {"target": m.group(1), "label": m.group(2)}


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
        reply = None
        if row["role"] == "user":
            text, reply = split_reply_block(text)
        m = {"id": str(rid) if rid is not None else f"m{i}", "role": row["role"], "text": text,
             "ts": float(row.get("timestamp") or 0.0)}
        if reply:
            m["reply_to"] = reply
        out.append(m)
    return out[-MAX_OPEN_MESSAGES:]


# ---------------------------------------------------------------- one Hermes gateway connection

class FolderChat:
    """A Hermes chat this bridge created in a folder the person picked (SESSIONS `+` > oh-my-hermes)."""

    def __init__(self, fid: str, cwd: str, runtime_id: str, stored_id: str, subscription_id: str = ""):
        self.id = fid
        self.cwd = cwd
        self.runtime_id = runtime_id
        self.stored_id = stored_id
        self.subscription_id = subscription_id  # from session.create: what session.detach closes
        self.generation = None
        self.in_turn = False
        self.last_thinking = -1e9
        self.prompts: dict[str, int | None] = {}
        self.asked: dict[str, tuple[float, float | None]] = {}  # open prompt_id -> (asked at, gateway timeout s)
        self.batches: dict[str, list[str]] = {}  # open batch clarify request id -> question ids, in order

    @property
    def ids(self) -> set[str]:
        return {i for i in (self.runtime_id, self.stored_id) if i}


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
        self.folders: dict[str, FolderChat] = {}  # folder chats this bridge created, by our own id
        self.asked: dict[str, tuple[float, float | None]] = {}  # open prompt_id -> (asked at, gateway timeout s)
        self.batches: dict[str, list[str]] = {}  # open batch clarify request id -> question ids, in order
        self.clarify_batch: bool | None = None  # the gateway asks a multi-question clarify as one request

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
        self.home = Path(hermes_home) if hermes_home else default_hermes_home()
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
        self._routine_changes: list[tuple[str, str, dict]] = []  # routines.update / routine.added, queued by a poll
        self._plugin_state: dict[str, set[str]] = {}  # plugin folder names per bot at the last look
        # What omher itself just added: never announced back to the chat as something the bot did.
        self._own_jobs: set[tuple[str, str]] = set()
        self._own_plugins: set[tuple[str, str]] = set()
        self.ops = {
            "hello": self.op_hello, "bots.list": self.op_bots_list, "chat.open": self.op_chat_open,
            "chat.send": self.op_chat_send, "chat.interrupt": self.op_chat_interrupt,
            "approval.respond": self.op_approval_respond, "clarify.respond": self.op_clarify_respond,
            "elsewhere.list": self.op_elsewhere_list, "elsewhere.peek": self.op_elsewhere_peek,
            "routines.list": self.op_routines_list, "models.options": self.op_models_options,
            "chat.set_model": self.op_set_model,
            "bots.rename": self.op_bots_rename, "bots.avatar": self.op_bots_avatar,
            "bots.set_avatar": self.op_bots_set_avatar, "bots.info": self.op_bots_info,
            "skills.list": self.op_skills_list, "links.places": self.op_links_places,
            "folder.open": self.op_folder_open, "folder.close": self.op_folder_close,
            "panel.terminal": self.op_panel_terminal, "panel.worktrees": self.op_panel_worktrees,
            "panel.diff": self.op_panel_diff, "media.read": self.op_media_read,
            "chat.attach": self.op_chat_attach, "runs.list": self.op_runs_list, "runs.get": self.op_runs_get,
            "runs.cli": self.op_runs_cli, "runs.prs": self.op_runs_prs, "cli.title": self.op_cli_title,
            "usage.read": self.op_usage_read,
            "accounts.list": self.op_accounts_list, "accounts.add": self.op_accounts_add,
            "accounts.remove": self.op_accounts_remove, "accounts.set_active": self.op_accounts_set_active,
            "accounts.label": self.op_accounts_label, "accounts.discard": self.op_accounts_discard,
            "automations.list": self.op_automations_list, "automations.add": self.op_automations_add,
            "automations.pause": self.op_automations_pause, "automations.resume": self.op_automations_resume,
            "automations.remove": self.op_automations_remove,
            "plugins.list": self.op_plugins_list, "plugins.catalog": self.op_plugins_catalog,
            "plugins.inspect": self.op_plugins_inspect, "plugins.install": self.op_plugins_install,
            "plugins.toggle": self.op_plugins_toggle, "plugins.update": self.op_plugins_update,
            "plugins.remove": self.op_plugins_remove,
        }
        self.announce_media = False  # amain: tell the app (stdout) which files it may open
        self.runs = DagRuns()
        self.cli = CliRuns()
        self.prs = PrStates()

    # ------------------------------------------------------------ lifecycle

    async def start(self, host: str = "127.0.0.1", port: int = 0, *, watch: bool = True) -> int:
        from websockets.asyncio.server import serve
        self.server = await serve(self._handler, host, port, process_request=self._process_request,
                                  max_size=UI_FRAME_MAX)
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
        folders = list(conn.folders.values())
        conn.folders.clear()
        conn.asked.clear()
        conn.batches.clear()
        conn.clarify_batch = None
        if pump is not None and pump is not asyncio.current_task():
            pump.cancel()
            with contextlib.suppress(BaseException):
                await pump
        if stack is not None:
            with contextlib.suppress(BaseException):
                await stack.aclose()
        if emit:
            for f in folders:
                if f.in_turn:
                    await self.emit("turn.end", conn.name, session=f.id, outcome="error", error=reason or "gateway disconnected")
                await self.emit("folder.closed", conn.name, session=f.id, reason=reason or "gateway disconnected")
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
        if isinstance(frame, dict) and frame.get("method") == "clarify" and isinstance(frame.get("id"), str):
            return await self._batch_clarify(conn, frame)
        if not isinstance(frame, dict) or frame.get("method") != "event":
            return
        params = frame.get("params")
        if not isinstance(params, dict):
            return
        typ, sid = params.get("type"), params.get("session_id")
        payload = params.get("payload") if isinstance(params.get("payload"), dict) else {}
        if typ == "sessions.changed":
            return await self._elsewhere_changed(conn)
        if typ == "cron.changed":  # Hermes saw the bot's jobs.json move: re-read it now, not at the next poll
            return await self.poll_routines_once()
        if sid and sid in conn.main_ids:
            return await self._main_event(conn, typ, params, payload)
        for f in list(conn.folders.values()):
            if sid and sid in f.ids:
                return await self._main_event(conn, typ, params, payload, f)
        if typ in ("message.start", "message.complete"):  # someone else's session moved
            await self._elsewhere_changed(conn)

    async def _elsewhere_changed(self, conn: Conn) -> None:
        now = self.clock()
        if now - conn.last_elsewhere_emit >= 1.0:
            conn.last_elsewhere_emit = now
            await self.emit("elsewhere.update", conn.name)

    async def _chat_emit(self, conn: Conn, chat: FolderChat | None, event: str, **fields) -> None:
        """An event of the main chat (``chat`` None) or of a folder chat (tagged with ``session``)."""
        if chat is not None:
            fields["session"] = chat.id
        await self.emit(event, conn.name, **fields)

    async def _begin_turn(self, conn: Conn, chat: FolderChat | None = None) -> None:
        t = chat or conn
        if not t.in_turn:
            t.in_turn = True
            await self._chat_emit(conn, chat, "turn.start")
            if chat is None:
                await self.emit("bot.status", conn.name, status="online", running=True)

    async def _end_turn(self, conn: Conn, outcome: str, error: str | None = None, chat: FolderChat | None = None) -> None:
        t = chat or conn
        t.in_turn = False
        t.prompts.clear()
        t.asked.clear()
        t.batches.clear()
        fields = {"outcome": outcome}
        if error:
            fields["error"] = error
        await self._chat_emit(conn, chat, "turn.end", **fields)
        if chat is None:
            await self.emit("bot.status", conn.name, status="online", running=False)

    async def _main_event(self, conn: Conn, typ: str, params: dict, p: dict, chat: FolderChat | None = None) -> None:
        t = chat or conn

        async def out(event, **fields):
            await self._chat_emit(conn, chat, event, **fields)
        if params.get("execution_generation") is not None:
            t.generation = params["execution_generation"]
        if typ == "message.start":
            await self._begin_turn(conn, chat)
        elif typ == "status.update":
            text = p.get("text")
            if isinstance(text, str) and text.strip():
                await out("status", text=text.strip())
        elif typ in ("thinking.delta", "reasoning.delta"):
            now = self.clock()
            if now - t.last_thinking >= THINKING_MIN_GAP:
                t.last_thinking = now
                await out("thinking")
        elif typ == "tool.start":
            await self._begin_turn(conn, chat)
            tool_id = str(p.get("tool_id") or p.get("tool_call_id") or "")
            tool = str(p.get("name") or p.get("tool_name") or "tool")
            context = p.get("context") if isinstance(p.get("context"), str) else ""
            args = p.get("args") if isinstance(p.get("args"), dict) else {}
            extra = {}
            if tool == "delegate_task":
                parts = dag_parts(args)
                if parts:
                    extra["dag"] = parts
            await out("tool.start", tool_id=tool_id, name=tool, detail=tool_detail(tool, args, context), **extra)
            if tool in ("skill_view", "skill_use"):
                args = p.get("args") if isinstance(p.get("args"), dict) else {}
                skill = str(args.get("name") or context).strip()
                if skill:
                    await out("skill", name=skill)
        elif typ == "tool.complete":
            dur = p.get("duration_s")
            await out("tool.end", tool_id=str(p.get("tool_id") or p.get("tool_call_id") or ""),
                      name=str(p.get("name") or p.get("tool_name") or "tool"),
                      ok=not p.get("is_error"), ms=int(round(dur * 1000)) if isinstance(dur, (int, float)) else 0)
        elif typ.startswith("subagent."):
            # a background fan-out outlives the turn that started it: these never open a turn
            fields = subagent_fields(typ, p)
            if fields is not None:
                await out("subagent", **fields)
        elif typ == "session.title" and chat is not None:
            # Hermes named a folder chat (its own titler, or /title); the name omher gave it at create is not news
            title = p.get("title")
            if isinstance(title, str) and title.strip() and not title.startswith(FOLDER_CHAT_PREFIX):
                await out("session.title", title=_one_line(title, CLI_TITLE))
        elif typ == "message.delta":
            text = p.get("text")
            if isinstance(text, str) and text:
                await self._begin_turn(conn, chat)
                await out("delta", text=text)
        elif typ == "message.complete":
            text = p.get("text") if isinstance(p.get("text"), str) else ""
            turn = p.get("persisted_turn") if isinstance(p.get("persisted_turn"), dict) else {}
            mid = turn.get("final_assistant_row_id") or p.get("admission_id") or uuid.uuid4().hex
            status = p.get("status")
            if text.strip():
                await out("message", id=str(mid), text=text)
            if status == "interrupted":
                await self._end_turn(conn, "interrupted", chat=chat)
            elif status == "error":
                await self._end_turn(conn, "error", str(p.get("error") or p.get("failure_reason") or "turn failed"), chat=chat)
            else:
                await self._end_turn(conn, "done", chat=chat)
        elif typ == "error":
            if t.in_turn:
                await self._end_turn(conn, "error", str(p.get("message") or "error"), chat=chat)
        elif typ == "approval.request":
            pid = str(p.get("prompt_id") or p.get("request_id") or "")
            if pid:
                t.prompts[pid] = p.get("execution_generation", params.get("execution_generation"))
                await self._emit_approval(conn, pid, p, chat)
        elif typ == "clarify.request":
            pid = str(p.get("prompt_id") or p.get("request_id") or "")
            if pid:
                t.prompts[pid] = p.get("execution_generation", params.get("execution_generation"))
                await self._emit_clarify(conn, pid, p, chat)
        elif typ in ("approval.settled", "clarify.settled"):
            # The wait ended without omher's answer: the gateway timed it out, or it was answered elsewhere.
            pid = str(p.get("prompt_id") or "")
            if pid in t.prompts:
                t.prompts.pop(pid, None)
                await self._emit_expired(conn, pid, None, chat)
        elif typ == "request.cancel":
            rid = str(p.get("id") or "")
            if rid in t.batches:
                t.batches.pop(rid, None)
                reason = str(p.get("reason") or "")
                await self._emit_expired(conn, rid, {"timeout": "timeout", "resolved": "resolved"}.get(reason, "cancelled"), chat)

    def _timeout(self, conn: Conn, pid: str, p: dict, chat: FolderChat | None = None) -> dict:
        t = p.get("timeout_s")
        t = float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0 else None
        (chat or conn).asked.setdefault(pid, (self.clock(), t))
        return {"timeout_s": t} if t is not None else {}

    async def _emit_approval(self, conn: Conn, pid: str, p: dict, chat: FolderChat | None = None) -> None:
        choices = [c for c in (p.get("choices") or ["once", "deny"]) if c in ("once", "session", "always", "deny")]
        await self._chat_emit(conn, chat, "approval.request", request_id=pid,
                              title=str(p.get("description") or "Allow this command?"),
                              command=str(p.get("command") or ""), choices=choices or ["once", "deny"],
                              **self._timeout(conn, pid, p, chat))

    async def _emit_clarify(self, conn: Conn, pid: str, p: dict, chat: FolderChat | None = None) -> None:
        fields = {"request_id": pid, "question": str(p.get("question") or "")}
        if p.get("choices"):
            fields["choices"] = [str(c) for c in p["choices"]]
            if p.get("multi_select") is True:
                fields["multi_select"] = True
        await self._chat_emit(conn, chat, "clarify.request", **fields, **self._timeout(conn, pid, p, chat))

    async def _batch_clarify(self, conn: Conn, frame: dict) -> None:
        """Hermes' clarify tool asking several questions at once (a server->client ``clarify`` request with
        ``questions``): one interview card. Only the main chat's and this bridge's folder chats' asks are
        shown; omher answers them per question with ``clarify.lock`` (op_clarify_respond)."""
        params = frame.get("params") if isinstance(frame.get("params"), dict) else {}
        sid = params.get("session_id")
        chat = None
        if sid not in conn.main_ids:
            chat = next((f for f in conn.folders.values() if sid and sid in f.ids), None)
            if chat is None:
                return
        rid = frame["id"]
        questions = []
        for q in params.get("questions") or []:
            if not isinstance(q, dict) or not isinstance(q.get("qid"), str) or not str(q.get("question") or "").strip():
                continue
            item = {"qid": q["qid"], "question": str(q["question"])}
            if q.get("choices"):
                item["choices"] = [str(c) for c in q["choices"]]
                if q.get("multi_select") is True:
                    item["multi_select"] = True
            questions.append(item)
        if not questions:
            return
        (chat or conn).batches[rid] = [q["qid"] for q in questions]
        first = questions[0]
        fields = {"request_id": rid, "question": first["question"]}
        if len(questions) == 1:
            fields.update({k: first[k] for k in ("choices", "multi_select") if k in first})
        else:
            fields["questions"] = questions
        await self._chat_emit(conn, chat, "clarify.request", **fields, **self._timeout(conn, rid, params, chat))

    async def _emit_expired(self, conn: Conn, pid: str, reason: str | None, chat: FolderChat | None = None) -> None:
        asked_at, timeout = (chat or conn).asked.pop(pid, (None, None))
        if reason is None:  # a settled prompt says no more: past its known deadline it timed out
            if asked_at is None or timeout is None:
                reason = "cancelled"
            else:
                reason = "timeout" if self.clock() - asked_at >= timeout - 1.0 else "resolved"
        await self._chat_emit(conn, chat, "prompt.expired", request_id=pid, reason=reason)

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

        asks = [x for x in (snap.get("open_requests") or [])
                if isinstance(x, dict) and x.get("method") == "clarify" and isinstance(x.get("id"), str)]

        async def replay():  # prompts still waiting on the person
            for x in prompts:
                pid = str(x["prompt_id"])
                conn.prompts[pid] = x.get("execution_generation")
                await (self._emit_clarify if x.get("kind") == "clarify" else self._emit_approval)(conn, pid, x)
            for x in asks:
                await self._batch_clarify(conn, x)
        return Reply(result, replay if prompts or asks else None)

    async def _target(self, conn: Conn, p: dict) -> tuple[str, FolderChat | None]:
        """The chat an op acts on: the main chat, or with ``session`` a folder chat this bridge created. Any
        other id (a client-supplied ``session_id``, another session's id) is never used."""
        fid = p.get("session")
        if fid is None:
            return await self._main(conn), None
        chat = conn.folders.get(fid) if isinstance(fid, str) else None
        if chat is None:
            raise BridgeError("not_found", "no such folder chat")
        return chat.runtime_id, chat

    async def op_chat_send(self, p) -> dict:
        text = p.get("text")
        if not isinstance(text, str) or not text.strip():
            raise BridgeError("bad_request", "missing text")
        reply_to = p.get("reply_to")
        if reply_to is not None and (not isinstance(reply_to, str) or not reply_to):
            raise BridgeError("bad_request", "reply_to must be a session id")
        conn = await self._conn(p.get("bot"))
        main, _chat = await self._target(conn, p)
        if reply_to is not None:
            # A thread reference for the bot, read from the profile's own state.db. omher posts nothing.
            if reply_to in conn.main_ids:
                raise BridgeError("bad_request", "reply_to names the main chat")
            facts = await asyncio.to_thread(read_session_facts, conn.bot["path"], [reply_to])
            ref = reply_target((facts.get(reply_to) or {}).get("origin") or {})
            if ref is None:
                raise BridgeError("bad_request", "that session has no thread to reply in")
            text = f"{text.rstrip()}\n\n{reply_block(*ref)}"
        input_id = str(uuid.uuid4())
        await self._probe_clarify_batch(conn)
        await self._submit(conn, main, text, input_id)
        return {"input_id": input_id}

    async def _probe_clarify_batch(self, conn: Conn) -> None:
        """Ask once per connection whether the gateway can send a turn's several clarify questions as one
        request (``canonical_clarify_batch``). Sent with no flags, so it changes nothing on the gateway; an
        older gateway that does not know the method leaves it off (one card per question, as before)."""
        if conn.clarify_batch is not None:
            return
        try:
            caps = await self._call(conn, "client.capabilities")
        except BridgeError:
            raise
        except Exception as e:
            if not _named(e, "GatewayRPCError"):
                raise
            caps = {}
        conn.clarify_batch = isinstance(caps, dict) and caps.get("canonical_clarify_batch") is True

    async def op_chat_attach(self, p) -> dict:
        """Stage one file the person picked for the next ``chat.send``, in the main chat only, through Hermes'
        own attach calls. The bytes come from the app; the bridge never opens a file for this."""
        kind, name, data = p.get("kind"), p.get("name"), p.get("data_base64")
        if kind not in ("image", "pdf", "file") or not isinstance(name, str) or not name.strip():
            raise BridgeError("bad_request", "need kind image|pdf|file and a name")
        if not isinstance(data, str) or not data:
            raise BridgeError("bad_request", "missing data_base64")
        if len(data) > ATTACH_B64_MAX:
            raise BridgeError("too_big", "files over 100 MB are not sent")
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)
        if kind == "image":
            method, source = "image.attach_bytes", {"content_base64": data, "filename": name}
        elif kind == "pdf":
            method, source = "pdf.attach", {"content_base64": data, "filename": name}
        else:
            method, source = "file.attach", {"data_url": f"data:application/octet-stream;base64,{data}", "name": name}
        res = await self._call(conn, method, session_id=main, _timeout=ATTACH_TIMEOUT, **source)
        res = res if isinstance(res, dict) else {}
        if res.get("attached") is False:
            raise BridgeError("attach_failed", str(res.get("message") or f"could not attach {name}"))
        return {"kind": kind, "name": name, "text": str(res.get("text") or ""), "ref_text": str(res.get("ref_text") or "")}

    async def _submit(self, conn: Conn, main_id: str, text: str, input_id: str):
        # The single place a turn is sent. It takes the main chat's id or a folder chat's that this bridge
        # created (both from _target), and nothing else.
        batch = {"clarify_batch": True} if conn.clarify_batch else {}
        return await self._call(conn, "prompt.submit", session_id=main_id, text=text, input_id=input_id, **batch)

    async def _generation(self, conn: Conn, main: str, chat: FolderChat | None = None):
        t = chat or conn
        if t.generation is None:
            snap = await self._call(conn, "session.resume", session_id=main)
            t.generation = snap.get("execution_generation")
        return t.generation if t.generation is not None else 0

    async def op_chat_interrupt(self, p) -> dict:
        conn = await self._conn(p.get("bot"))
        main, chat = await self._target(conn, p)
        await self._call(conn, "session.interrupt", session_id=main, execution_generation=await self._generation(conn, main, chat))
        return {}

    async def op_approval_respond(self, p) -> dict:
        choice, rid = p.get("choice"), p.get("request_id")
        if choice not in ("once", "session", "always", "deny") or not isinstance(rid, str) or not rid:
            raise BridgeError("bad_request", "need request_id and choice once|session|always|deny")
        conn = await self._conn(p.get("bot"))
        main, chat = await self._target(conn, p)
        t = chat or conn
        gen = t.prompts.pop(rid, None)
        t.asked.pop(rid, None)
        await self._call(conn, "approval.respond", session_id=main, prompt_id=rid, choice=choice,
                         execution_generation=gen if gen is not None else await self._generation(conn, main, chat))
        return {}

    async def op_clarify_respond(self, p) -> dict:
        answer, answers, rid = p.get("answer"), p.get("answers"), p.get("request_id")
        if answers is not None:
            if not isinstance(answers, dict) or not all(
                    isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in answers.items()):
                raise BridgeError("bad_request", "answers must map question ids to text or null")
        if (not isinstance(answer, str) and answers is None) or not isinstance(rid, str) or not rid:
            raise BridgeError("bad_request", "need request_id and answer")
        conn = await self._conn(p.get("bot"))
        main, chat = await self._target(conn, p)
        t = chat or conn
        qids = t.batches.get(rid)
        if qids is not None:
            # An interview: lock every question (null = skipped); the last lock hands Hermes the whole set.
            got = answers if answers is not None else {qids[0]: answer}
            for qid in qids:
                await self._call(conn, "clarify.lock", request_id=rid, question_id=qid, answer=got.get(qid))
            t.batches.pop(rid, None)
            t.asked.pop(rid, None)
            return {}
        if answer is None:  # one gateway card per question: only the first answer applies
            answer = next((v for v in answers.values() if v is not None), "")
        gen = t.prompts.pop(rid, None)
        t.asked.pop(rid, None)
        await self._call(conn, "clarify.respond", session_id=main, prompt_id=rid, answer=answer,
                         execution_generation=gen if gen is not None else await self._generation(conn, main, chat))
        return {}

    # ------------------------------------------------------------ folder chats (SESSIONS > oh-my-hermes)

    async def op_folder_open(self, p) -> dict:
        """Create a new Hermes chat for the bot in folder ``cwd`` (an existing absolute folder)."""
        cwd = p.get("cwd")
        if not isinstance(cwd, str) or not cwd.strip() or not os.path.isabs(cwd) or not os.path.isdir(cwd):
            raise BridgeError("bad_request", "cwd must be an existing folder")
        conn = await self._conn(p.get("bot"))
        if len(conn.folders) >= MAX_FOLDER_CHATS:
            raise BridgeError("bad_request", f"at most {MAX_FOLDER_CHATS} folder chats per bot")
        leaf = Path(cwd).name or cwd
        snap = await self._call(conn, "session.create", title=FOLDER_CHAT_PREFIX + leaf, cwd=cwd, cwd_explicit=True,
                                follow_profile_config=True)
        fid = "f" + uuid.uuid4().hex[:10]
        chat = FolderChat(fid, cwd, str(snap["session_id"]), str(snap.get("stored_session_id") or snap["session_id"]),
                          str(snap.get("subscription_id") or ""))
        if snap.get("execution_generation") is not None:
            chat.generation = snap["execution_generation"]
        conn.folders[fid] = chat
        info = snap.get("info") if isinstance(snap.get("info"), dict) else {}
        return {"session": fid, "cwd": str(info.get("cwd") or cwd),
                "model": str(info.get("model") or conn.bot["model"]),
                "provider": str(info.get("provider") or conn.bot["provider"]),
                "reasoning": str(info.get("reasoning_effort") or conn.bot["reasoning"])}

    async def op_folder_close(self, p) -> dict:
        """Close a folder chat this bridge created: Hermes stops its agent; the conversation stays saved.

        Hermes' gateway closes a conversation with ``session.detach`` of the subscription ``session.create`` gave
        and an ``end_reason`` (a viewer closing it, not leaving); it has no ``session.close``. A gateway without
        ``session.detach`` (``unknown_method``) gets ``session.close`` as before; any other refusal is the error."""
        conn = await self._conn(p.get("bot"))
        fid = p.get("session")
        chat = conn.folders.pop(fid, None) if isinstance(fid, str) else None
        if chat is None:
            raise BridgeError("not_found", "no such folder chat")
        if chat.subscription_id:
            try:
                await self._call(conn, "session.detach", session_id=chat.runtime_id, subscription_id=chat.subscription_id,
                                 end_reason="omher_close")
                return {}
            except Exception as e:
                if not (_named(e, "GatewayRPCError") and str(e) == "unknown_method"):
                    raise
        await self._call(conn, "session.close", session_id=chat.runtime_id)
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
        main, _chat = await self._target(conn, p)

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
                         "status": status, "running": bool(conn and conn.in_turn),
                         "avatar_rev": avatar_rev(b["path"])})
        return {"bots": bots}

    # ------------------------------------------------------------ bot profile: name, picture, facts
    # The only writes omher makes to a profile. Both are presentation-only in Hermes: the profile id,
    # its folder, config and sessions never change.

    async def op_bots_rename(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        name = clean_display_name(p.get("name"))
        await asyncio.to_thread(write_display_name, bot["path"], name)
        shown = discover_bots(self.home)
        display = next((b["display_name"] for b in shown if b["name"] == bot["name"]), name)
        await self.emit("bots.update", bot["name"])
        return {"display_name": display}

    async def op_bots_avatar(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        rev, data = await asyncio.to_thread(read_avatar, bot["path"])
        return {"rev": rev, "data": data}

    async def op_bots_set_avatar(self, p) -> dict:
        """Hand the picture to Hermes' own ``profiles.set_asset`` (it checks the format and size and
        writes ``assets/avatar.<ext>``); ``clear: true`` goes back to the built-in face."""
        bot = self._bot(p.get("bot"))
        clear = p.get("clear") is True
        data = p.get("data")
        if not clear and (not isinstance(data, str) or not data.startswith("data:image/")):
            raise BridgeError("bad_request", "data must be an image data URL")
        params = {"name": bot["name"], "asset": "avatar"}
        params.update({"clear": True} if clear else {"data": data})
        try:
            conn = await self._conn(bot["name"])
        except BridgeError as e:
            if e.code != "bot_offline":
                raise
            # gateway down: same checks and same file, written here
            await asyncio.to_thread(write_avatar, bot["path"], None if clear else data)
        else:
            await self._call(conn, "profiles.set_asset", **params)
        await self.emit("bots.update", bot["name"])
        return {"avatar_rev": avatar_rev(bot["path"])}

    async def op_bots_info(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return await asyncio.to_thread(read_bot_facts, bot["path"])

    async def op_skills_list(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"skills": await asyncio.to_thread(read_skills, bot["path"])}

    async def op_links_places(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"places": await asyncio.to_thread(read_link_places, bot["path"])}

    async def op_panel_terminal(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"runs": await asyncio.to_thread(read_terminal_runs, bot["path"])}

    async def op_panel_worktrees(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"worktrees": await asyncio.to_thread(read_worktrees, bot["path"])}

    async def op_usage_read(self, p) -> dict:
        return await asyncio.to_thread(read_usage)

    async def op_accounts_list(self, p) -> dict:
        return await asyncio.to_thread(read_accounts)

    async def op_accounts_add(self, p) -> Reply:
        out = await asyncio.to_thread(add_account, p.get("cli"), p.get("label"))
        return Reply(out, lambda: self.emit("accounts.update", ""))

    async def op_accounts_remove(self, p) -> Reply:
        await asyncio.to_thread(remove_account, p.get("cli"), p.get("account"))
        return Reply({}, lambda: self.emit("accounts.update", ""))

    async def op_accounts_set_active(self, p) -> Reply:
        await asyncio.to_thread(set_active_account, p.get("cli"), p.get("account"))
        return Reply({}, lambda: self.emit("accounts.update", ""))

    async def op_accounts_label(self, p) -> Reply:
        await asyncio.to_thread(label_account, p.get("cli"), p.get("account"), p.get("label"))
        return Reply({}, lambda: self.emit("accounts.update", ""))

    async def op_accounts_discard(self, p) -> Reply:
        """A cancelled sign-in: removes the new folder, refused when the CLI logged in there."""
        await asyncio.to_thread(remove_account, p.get("cli"), p.get("account"), only_if_empty=True)
        return Reply({}, lambda: self.emit("accounts.update", ""))

    async def op_panel_diff(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        path = p.get("path")
        if not isinstance(path, str) or not path:
            raise BridgeError("bad_request", "missing path")
        return await asyncio.to_thread(read_diff, bot["path"], path)

    async def op_media_read(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        path = p.get("path")
        if not isinstance(path, str) or not path or len(path) > 4096 or "\n" in path or "\0" in path:
            raise BridgeError("bad_request", "missing path")
        out = await asyncio.to_thread(read_media, bot["path"], path, p.get("info") is True)
        if self.announce_media:
            print(MEDIA_READY_PREFIX + json.dumps({"path": out["path"]}), flush=True)
        return out

    async def op_runs_list(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"runs": await asyncio.to_thread(self.runs.list, bot["name"], bot["path"])}

    async def op_runs_get(self, p) -> dict:
        run = p.get("run")
        if not isinstance(run, str) or not run:
            raise BridgeError("bad_request", "missing run")
        # a CLI agent's run (a SESSIONS chat's own, or one listed under a bot) is found by its id alone
        if run.split(":", 1)[0] in CLI_AGENTS:
            return await asyncio.to_thread(self.cli.get, run)
        bot = self._bot(p.get("bot"))
        return await asyncio.to_thread(self.runs.get, bot["name"], bot["path"], run)

    async def op_runs_prs(self, p) -> dict:
        """The state of each PR the run's nodes name (`runs.get` gives the numbers): {prs: {node id: {number,
        repo?, url?, state}}}. Asked apart from `runs.get` so a slow or missing `gh` never holds the graph."""
        bot = self._bot(p.get("bot"))
        run = p.get("run")
        if not isinstance(run, str) or not run:
            raise BridgeError("bad_request", "missing run")
        if run.split(":", 1)[0] in CLI_AGENTS:
            return {"prs": {}}
        got = await asyncio.to_thread(self.runs.get, bot["name"], bot["path"], run)
        return {"prs": await asyncio.to_thread(self.prs.states, got["run"])}

    async def op_runs_cli(self, p) -> dict:
        """CLI agent sessions with sub-runs: `agent` (claude, codex, omo, pi, omp, grok; all when absent), `cwd` (only
        sessions in that folder) and `since` (epoch seconds; the last week when absent)."""
        agent, cwd, since = p.get("agent"), p.get("cwd"), p.get("since")
        if agent is not None and agent not in CLI_AGENTS:
            raise BridgeError("bad_request", f"agent must be one of {', '.join(CLI_AGENTS)}")
        if cwd is not None and (not isinstance(cwd, str) or not cwd):
            raise BridgeError("bad_request", "cwd must be a folder path")
        if since is not None and (isinstance(since, bool) or not isinstance(since, (int, float))):
            raise BridgeError("bad_request", "since must be epoch seconds")
        return await asyncio.to_thread(self.cli.list, agent, cwd, since)

    async def op_cli_title(self, p) -> dict:
        """The title of one Claude Code session or Codex thread a SESSIONS chat runs (`agent`, `session`: the id the
        agent reported, `cwd`: its folder), from the agent's own files; `""` when it has none yet."""
        agent, session, cwd = p.get("agent"), p.get("session"), p.get("cwd")
        if agent not in ("claude", "codex"):
            raise BridgeError("bad_request", "agent must be claude or codex")
        if not isinstance(session, str) or not _SESSION_UUID.match(session):
            raise BridgeError("bad_request", "session must be the agent's session id")
        if cwd is not None and (not isinstance(cwd, str) or not cwd):
            raise BridgeError("bad_request", "cwd must be a folder path")
        return {"title": await asyncio.to_thread(self.cli.title, agent, session, cwd)}

    async def op_routines_list(self, p) -> dict:
        return {"routines": read_routines(self._bot(p.get("bot"))["path"])}

    # ------------------------------------------------------------ automations (cron) and plugins
    # Reads come from files (`cron/jobs.json`, the catalog cache, plugin folder names). Every change goes
    # through the bot's own gateway: `cron.manage` and `plugins.manage`, with the actions below only.

    async def _cron(self, conn: Conn, action: str, **params) -> dict:
        if action not in CRON_ACTIONS:
            raise BridgeError("bad_request", f"cron action {action} is not used by omher")
        res = await self._call(conn, "cron.manage", action=action, **params)
        res = res if isinstance(res, dict) else {}
        if res.get("success") is False or (res.get("error") and not res.get("success")):
            raise BridgeError("cron_refused", _clip(str(res.get("error") or "Hermes refused the change"), 600))
        return res

    async def _plugins(self, conn: Conn, action: str, **params) -> dict:
        if action not in PLUGIN_ACTIONS:
            raise BridgeError("bad_request", f"plugins action {action} is not used by omher")
        res = await self._call(conn, "plugins.manage", action=action, **params)
        return res if isinstance(res, dict) else {}

    def _job_of(self, bot: dict, job_id) -> dict:
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise BridgeError("bad_request", "need the automation's id")
        for j in read_automations(bot["path"]):
            if j["id"] == job_id:
                return j
        raise BridgeError("not_found", f"{bot['name']} has no automation {job_id}")

    async def op_automations_list(self, p) -> dict:
        out = []
        for b in discover_bots(self.home):
            out += [{**j, "bot": b["name"]} for j in read_automations(b["path"])]
        return {"automations": out}

    async def op_automations_add(self, p) -> dict:
        name, schedule, prompt, deliver = (p.get(k) for k in ("name", "schedule", "prompt", "deliver"))
        for k, v, n in (("name", name, 120), ("schedule", schedule, 200), ("prompt", prompt, 8000)):
            if not isinstance(v, str) or not v.strip() or len(v) > n:
                raise BridgeError("bad_request", f"{k} must be text (up to {n} characters)")
        bot = self._bot(p.get("bot"))
        if deliver is not None and deliver != f"bot-chat:{bot['name']}":
            raise BridgeError("bad_request", "deliver is the bot's own chat or left out")
        conn = await self._conn(bot["name"])
        res = await self._cron(conn, "add", name=name.strip(), schedule=schedule.strip(), prompt=prompt.strip(),
                               **({"deliver": deliver} if deliver else {}))
        jid = str(res.get("job_id") or (res.get("job") or {}).get("id") or "")
        if jid:
            self._own_jobs.add((bot["name"], jid))
        await self.poll_routines_once()
        return {"job": jid, "name": str(res.get("name") or name.strip())}

    async def _job_action(self, p, action: str) -> dict:
        bot = self._bot(p.get("bot"))
        job = self._job_of(bot, p.get("job"))
        conn = await self._conn(bot["name"])
        await self._cron(conn, action, name=job["id"])  # cron.manage carries the job id in `name`
        await self.poll_routines_once()
        return {"job": job["id"]}

    async def op_automations_pause(self, p) -> dict:
        return await self._job_action(p, "pause")

    async def op_automations_resume(self, p) -> dict:
        return await self._job_action(p, "resume")

    async def op_automations_remove(self, p) -> dict:
        return await self._job_action(p, "remove")

    def _catalog(self, bot: dict) -> tuple[list[dict], str]:
        path = catalog_path(bot["path"], hermes_root_of(self.home))
        return read_catalog(path) if path else ([], "")

    async def op_plugins_catalog(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        query, category = p.get("query") or "", p.get("category") or ""
        if not isinstance(query, str) or len(query) > 100 or (category and category not in PLUGIN_CATEGORIES):
            raise BridgeError("bad_request", "query is text, category one of the catalog's")
        limit = p.get("limit") if isinstance(p.get("limit"), int) else CATALOG_PAGE
        entries, generated = await asyncio.to_thread(self._catalog, bot)
        return {**search_catalog(entries, query, category, limit), "generated_at": generated or None}

    async def op_plugins_list(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        conn = await self._conn(bot["name"])
        res = await self._plugins(conn, "list")
        entries, _ = await asyncio.to_thread(self._catalog, bot)
        by_name = {e["name"]: e for e in entries}
        rows = [plugin_row(r, by_name) for r in res.get("plugins") or [] if isinstance(r, dict) and r.get("name")]
        return {"plugins": rows}

    def _plugin_name(self, p, key: str = "name") -> str:
        v = p.get(key)
        if not isinstance(v, str) or not PLUGIN_NAME.fullmatch(v):
            raise BridgeError("bad_request", f"need a plugin {key}")
        return v

    async def _catalog_entry(self, bot: dict, p) -> dict:
        """The catalog entry `catalog_name` names. Only a name the curated catalog cache lists passes: a Git
        URL, `owner/repo` or any other source is refused here, before Hermes is asked (BOUNDARY rule 25)."""
        name = p.get("catalog_name")
        if not isinstance(name, str) or not CATALOG_NAME.fullmatch(name):
            raise BridgeError("bad_request", "plugins install from the catalog by name only")
        entries, _ = await asyncio.to_thread(self._catalog, bot)
        entry = next((e for e in entries if e["name"] == name), None)
        if entry is None:
            raise BridgeError("not_found", f"{name} is not in the plugin catalog")
        return entry

    async def op_plugins_inspect(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        entry = await self._catalog_entry(bot, p)
        name = entry["name"]
        conn = await self._conn(bot["name"])
        res = await self._plugins(conn, "inspect", catalog_name=name)
        if not res.get("ok"):
            raise BridgeError("inspect_failed", _clip(str(res.get("error") or "Hermes could not read it"), 400))
        return {"entry": entry, "sha": str(res.get("sha") or ""), "agent": bool(res.get("agent")),
                "desktop": bool(res.get("desktop")), "warnings": _strs(res.get("warnings"), 6)}

    async def op_plugins_install(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        name = (await self._catalog_entry(bot, p))["name"]
        sha = p.get("inspected_sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{7,64}", sha):
            raise BridgeError("bad_request", "install needs the sha its inspect returned")
        conn = await self._conn(bot["name"])
        res = await self._plugins(conn, "install", catalog_name=name, enable=True, inspected_sha=sha)
        installed = str(res.get("plugin_name") or res.get("name") or name)
        self._own_plugins.add((bot["name"], installed))
        return {"name": installed, "enabled": bool(res.get("enabled", True)),
                "restart_required": bool(res.get("restart_required")), "warnings": _strs(res.get("warnings"), 6),
                "missing_env": _strs(res.get("missing_env"), 12)}

    async def op_plugins_toggle(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        key = self._plugin_name(p, "key")
        if not isinstance(p.get("enable"), bool):
            raise BridgeError("bad_request", "enable is true or false")
        conn = await self._conn(bot["name"])
        res = await self._plugins(conn, "toggle", key=key, enable=p["enable"])
        return {"name": str(res.get("name") or key), "restart_required": bool(res.get("restart_required"))}

    async def op_plugins_update(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        name = self._plugin_name(p)
        conn = await self._conn(bot["name"])
        res = await self._plugins(conn, "update", name=name)
        if res.get("consent_required") or res.get("scan_blocked"):
            raise BridgeError("needs_review", f"This update needs a closer look. Ask {bot['display_name']} in chat to update {name}.")
        return {"name": str(res.get("name") or name), "unchanged": bool(res.get("unchanged")),
                "restart_required": bool(res.get("restart_required"))}

    async def op_plugins_remove(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        name = self._plugin_name(p)
        conn = await self._conn(bot["name"])
        await self._plugins(conn, "remove", name=name)
        return {"name": name}

    def poll_routines(self) -> list[tuple[str, dict]]:
        """Compare each profile's cron/jobs.json to the last look; returns (bot, job) for each new run. A changed
        file also queues `routines.update`, and a job id first seen after the baseline queues `routine.added`
        (unless omher added it itself)."""
        ran = []
        for b in discover_bots(self.home):
            path = b["path"] / "cron" / "jobs.json"
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                mtime = None
            st = self._routine_state.get(b["name"])
            if st is not None and st["mtime"] == mtime:
                continue
            jobs = read_automations(b["path"]) if mtime is not None else []
            last = {j["id"]: j["last_run_at"] for j in jobs}
            if st is not None:
                ran += [(b["name"], j) for j in jobs if j["last_run_at"] and st["last"].get(j["id"]) != j["last_run_at"]]
                self._routine_changes.append(("routines.update", b["name"], {}))
                for j in jobs:
                    if j["id"] not in st["last"] and (b["name"], j["id"]) not in self._own_jobs:
                        self._routine_changes.append(("routine.added", b["name"], j))
            self._routine_state[b["name"]] = {"mtime": mtime, "last": last}
        return ran

    def poll_plugins(self) -> list[tuple[str, str]]:
        """(bot, folder name) for each plugin folder that appeared under a profile since the last look."""
        added = []
        for b in discover_bots(self.home):
            names = plugin_folders(b["path"])
            seen = self._plugin_state.get(b["name"])
            if seen is not None:
                added += [(b["name"], n) for n in sorted(names - seen) if (b["name"], n) not in self._own_plugins]
            self._plugin_state[b["name"]] = names
        return added

    async def poll_routines_once(self) -> int:
        ran = self.poll_routines()
        for bot, j in ran:
            await self.emit("routine.ran", bot, routine_id=j["id"], name=j["name"],
                            status=str(j["last_status"] or "ok"), ts=_to_ts(j["last_run_at"]))
        changes, self._routine_changes = self._routine_changes, []
        for event, bot, j in changes:
            if event == "routine.added":
                await self.emit(event, bot, routine_id=j["id"], name=j["name"], schedule=j["schedule"],
                                next_run_at=j["next_run_at"], deliver=j["deliver"], origin=j["origin"],
                                ts=_to_ts(j.get("created_at")))
            else:
                await self.emit(event, bot)
        return len(ran)

    async def poll_plugins_once(self) -> int:
        added = self.poll_plugins()
        for bot, name in added:
            entry = {}
            with contextlib.suppress(Exception):
                entries, _ = self._catalog(self._bot(bot))
                entry = next((e for e in entries if e["name"] == name), {})
            await self.emit("plugin.added", bot, name=name, title=str(entry.get("title") or ""),
                            tools=len(entry.get("tools") or []), hooks=len(entry.get("hooks") or []), ts=time.time())
            await self.emit("plugins.update", bot)
        return len(added)

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
        self.poll_plugins()
        last_else = self.clock()
        while True:
            await asyncio.sleep(self.poll_s)
            with contextlib.suppress(Exception):
                await self.poll_routines_once()
            with contextlib.suppress(Exception):
                await self.poll_plugins_once()
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
        out = out[:MAX_ELSEWHERE]
        facts = await asyncio.to_thread(read_session_facts, conn.bot["path"], [a["id"] for a in out])
        for a in out:
            f = facts.get(a["id"]) or {}
            a["url"], a["place"] = origin_link(a["source"], f.get("origin") or {})
            ref = reply_target(f.get("origin") or {})
            a["reply_target"] = ref[0] if ref else None
            a["last_reply"] = f.get("last_reply")
            a["last_reply_at"] = f.get("last_reply_at")
        return out

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


def _stop_on_signals(loop, stop: asyncio.Event) -> None:
    """Stop cleanly on SIGTERM/SIGINT. Windows' event loop has no signal handlers (NotImplementedError); there
    the app's stdin EOF (`--exit-on-stdin-eof`) and process kill are what stop the bridge."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass


async def amain(args) -> int:
    bridge = Bridge(token=args.token, hermes_home=Path(args.hermes_home) if args.hermes_home else None, eager=args.eager)
    bridge.announce_media = True
    port = await bridge.start("127.0.0.1", args.port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    _stop_on_signals(loop, stop)
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
    activate_hermes_dependencies(root)
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


def activate_hermes_dependencies(root: Path) -> None:
    """Boot Hermes' PM-committed dependency environment, as Hermes' own entry points do.

    A PM-managed install runs on its store Python, which owns no packages: the committed
    generation's site-packages must be selected before any third-party import (`websockets`,
    `yaml`). Installs without PM (a plain venv) have no `pm` package and keep their own path.
    """
    try:
        from pm.environments import activate_dependencies
    except ImportError:
        return
    activate_dependencies(root)


if __name__ == "__main__":
    sys.exit(main())
