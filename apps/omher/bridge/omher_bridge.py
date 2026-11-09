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


def reply_gist(text: str, n: int = 220) -> str:
    """The first paragraph of an answer as plain text: markdown marks and mentions removed, bare URLs
    shortened, clipped at a sentence end when one is near."""
    para = next((p for p in re.split(r"\n\s*\n", text or "") if p.strip()), "")
    t = _MD_LINK.sub(r"\1", para)
    t = _MENTION.sub("", t)
    urls: list[str] = []

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
        self.ops = {
            "hello": self.op_hello, "bots.list": self.op_bots_list, "chat.open": self.op_chat_open,
            "chat.send": self.op_chat_send, "chat.interrupt": self.op_chat_interrupt,
            "approval.respond": self.op_approval_respond, "clarify.respond": self.op_clarify_respond,
            "elsewhere.list": self.op_elsewhere_list, "elsewhere.peek": self.op_elsewhere_peek,
            "routines.list": self.op_routines_list, "models.options": self.op_models_options,
            "chat.set_model": self.op_set_model,
            "bots.rename": self.op_bots_rename, "bots.avatar": self.op_bots_avatar,
            "bots.set_avatar": self.op_bots_set_avatar, "bots.info": self.op_bots_info,
            "panel.terminal": self.op_panel_terminal, "panel.worktrees": self.op_panel_worktrees,
            "panel.diff": self.op_panel_diff,
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
            args = p.get("args") if isinstance(p.get("args"), dict) else {}
            await self.emit("tool.start", name, tool_id=tool_id, name=tool, detail=tool_detail(tool, args, context))
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
        reply_to = p.get("reply_to")
        if reply_to is not None and (not isinstance(reply_to, str) or not reply_to):
            raise BridgeError("bad_request", "reply_to must be a session id")
        conn = await self._conn(p.get("bot"))
        main = await self._main(conn)
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

    async def op_panel_terminal(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"runs": await asyncio.to_thread(read_terminal_runs, bot["path"])}

    async def op_panel_worktrees(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        return {"worktrees": await asyncio.to_thread(read_worktrees, bot["path"])}

    async def op_panel_diff(self, p) -> dict:
        bot = self._bot(p.get("bot"))
        path = p.get("path")
        if not isinstance(path, str) or not path:
            raise BridgeError("bad_request", "missing path")
        return await asyncio.to_thread(read_diff, bot["path"], path)

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
