"""Read an omher terminal's status from its link, and ask omher to type a prompt into it.

omher (the OMH desktop app) keeps one status file per TERMINALS session while it lives:
``~/.omher/terminals/<link id>.json``, owner-only. This tool reads that file and nothing else of omher; it never
imports omher and never talks to it. ``send`` puts one request file in the session's inbox
(``~/.omher/terminals/<link id>.inbox/``). omher shows it to the person as a card, and only their Allow types the
prompt. Nothing here can type into a terminal, and a link id that is not 10 base32 characters, or any path that
would land outside ``~/.omher/terminals``, is refused before a file is touched.

On Windows omher keeps no status files and reads no inbox (its owner-only checks are POSIX), so the tool touches no
file there: ``status`` says it is not available and ``send`` that terminal sharing is not available on Windows.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from .. import runtime_paths
from ..host_observation import host_session_id

# Tests point this at a temp folder (tests/_local_package.py); the real one is the user's own ~/.omher/terminals.
TERMINALS_ENV = "OMH_OMHER_TERMINALS"
PROMPT_MAX = 4000
REQUEST_MAX = 16 * 1024
STATUS_MAX = 16 * 1024
_LINK = re.compile(r"^(?:omher://terminal/)?([a-z2-7]{10})/?$")
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_FIELDS = ("link", "title", "agent", "folder", "state", "started", "last_line", "updated_at")

OMH_OMHER_TERMINAL_SCHEMA = {
    "name": "omh_omher_terminal",
    "description": (
        "An omher terminal link (omher://terminal/<id>): `status` reads that session's title, CLI, folder, state "
        "and last printed line; `send` asks omher to type `prompt` into it. omher shows the person a card and "
        "types only if they allow it, so a sent prompt is a request, not a typed one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "send"]},
            "link": {"type": "string", "description": "The omher://terminal/ link or its 10-character id."},
            "prompt": {"type": "string", "description": f"For send: the text to type, at most {PROMPT_MAX} characters."},
        },
        "required": ["action", "link"],
    },
}


def sharing_available() -> bool:
    """omher shares terminals with bots on this system (not on Windows)."""
    return not sys.platform.startswith("win")


def terminals_root() -> Path:
    override = os.environ.get(TERMINALS_ENV, "").strip()
    return Path(override) if override else Path.home() / ".omher" / "terminals"


def omher_present() -> bool:
    """omher runs on this computer (its folder is there): the tool is offered only then."""
    return terminals_root().parent.is_dir()


def link_id(value: object) -> str | None:
    """The link id in ``value`` (the link or the bare id), or None."""
    if not isinstance(value, str):
        return None
    m = _LINK.match(value.strip())
    return m.group(1) if m else None


def clean_prompt(text: str) -> str:
    """Control characters out; a newline stays (a CR/LF pair becomes one newline)."""
    return _CONTROL.sub("", text.replace("\r\n", "\n"))


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _reply(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _refuse(reason: str, text: str) -> str:
    return _reply({"ok": False, "reason": reason, "text": text})


def read_status(root: Path, lid: str) -> dict[str, Any] | None:
    """The session's status file, or None when there is none (closed, or not on this computer)."""
    path = root / f"{lid}.json"
    if not _inside(root, path) or root.is_symlink():
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(STATUS_MAX + 1)
    if len(raw) > STATUS_MAX:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {k: data[k] for k in _FIELDS if k in data}


def _bot_name() -> str:
    """The Hermes profile this bot runs as (``default`` for the root home)."""
    try:
        _omh, hermes = runtime_paths.resolve_homes()
    except runtime_paths.RuntimeBindingError:
        return "a bot"
    return hermes.name if hermes.parent.name == "profiles" else "default"


def write_request(root: Path, lid: str, prompt: str, sender: str, session: str) -> str:
    """Put one request in the session's inbox, owner-only; the file's name."""
    inbox = root / f"{lid}.inbox"
    if inbox.is_symlink() or not inbox.is_dir() or not _inside(root, inbox):
        raise FileNotFoundError("no inbox")
    body = json.dumps({"prompt": prompt, "from": sender, "session": session}, ensure_ascii=False).encode("utf-8")
    if len(body) > REQUEST_MAX:
        raise ValueError("request too large")
    name = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    tmp = inbox / f".{name}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(body)
    # omher takes only *.json: the file shows whole, never half written
    os.replace(tmp, inbox / f"{name}.json")
    return f"{name}.json"


def omh_omher_terminal_handler(args: dict[str, Any], **kwargs: Any) -> str:
    action = args.get("action")
    lid = link_id(args.get("link"))
    if lid is None:
        return _refuse("bad_link", "That is not an omher terminal link (omher://terminal/ and a 10-character id).")
    if not sharing_available():
        if action == "send":
            return _refuse("unavailable", "terminal sharing is not available on Windows")
        return _refuse("unavailable", "not available")
    root = terminals_root()
    status = read_status(root, lid)
    if status is None:
        return _refuse("not_found", "No omher terminal with that link is open on this computer.")
    if action == "status":
        return _reply({"ok": True, "status": status})
    if action != "send":
        return _refuse("bad_action", "action is status or send.")
    prompt = args.get("prompt")
    prompt = clean_prompt(prompt) if isinstance(prompt, str) else ""
    if not prompt.strip():
        return _refuse("no_prompt", "send needs a prompt.")
    if len(prompt) > PROMPT_MAX:
        return _refuse("too_long", f"The prompt is over {PROMPT_MAX} characters.")
    try:
        name = write_request(root, lid, prompt, _bot_name(), host_session_id(kwargs))
    except (OSError, ValueError):
        return _refuse("not_sent", "omher's inbox for that terminal could not take the request.")
    title = status.get("title") or lid
    return _reply({
        "ok": True,
        "requested": name,
        "text": f"Asked omher to type into \"{title}\". The person sees a card there and it is typed only if they allow it.",
    })
