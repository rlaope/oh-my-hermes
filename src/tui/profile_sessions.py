"""Foreground-only, read-only session inventory over registered Hermes homes."""

from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import Future
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import re
import json
import sqlite3
import stat
from threading import Thread
from time import monotonic
from typing import Any, TypeVar

from ..plugin_bundle.omh.live_session import conversation_segments
from ..plugin_bundle.omh.sqlite_readonly import connect_readonly
from .bot_board import DELETED_PROFILES, PROFILE_MARKERS, _columns, _no_connection_open
from .history import history_path
from .markdown import clean_text
from .session_picker import SessionRow, session_rows

_PROFILE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")  # Hermes' named profile IDs
_NOISE = ("acp", "cron", "kanban", "oneshot", "subagent", "tool")  # same as the gateway picker
_ROW_LIMIT = 500
_PAGE_LIMIT = 500
_TEXT_LIMIT = 8192
_T = TypeVar("_T")


def _homes(environ: Mapping[str, str]) -> Iterator[tuple[str, Path]]:
    history = history_path(environ)
    if history is None:
        return
    current = history.parent
    root = current.parent.parent if current.parent.name == "profiles" else current
    yield "default", root
    profiles = root / "profiles"
    if profiles.is_symlink():
        raise OSError("linked profiles directory")
    try:
        entries = sorted(profiles.iterdir())
    except FileNotFoundError:
        return
    for home in entries:
        if (_PROFILE.fullmatch(home.name) and home.name != "default" and not home.is_symlink() and home.is_dir()
                and not (profiles / DELETED_PROFILES / home.name).exists()
                and any((home / marker).is_file() or (home / marker).is_symlink() for marker in PROFILE_MARKERS)):
            yield home.name, home


@contextmanager
def _store(home: Path) -> Iterator[tuple[sqlite3.Connection, tuple[int, int]]]:
    path = home / "state.db"
    info = path.lstat()
    if home.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise OSError("not a regular session store")
    # Idle WAL databases must not acquire sidecars. A live reader participates in the existing WAL.
    sidecars = set()
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        try:
            mode = sidecar.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            raise OSError("not a regular session store sidecar")
        sidecars.add(suffix)
    if sidecars and sidecars != {"-wal", "-shm"}:
        raise OSError("session store has an incomplete WAL pair or requires recovery")
    # Recheck just before open in case the last writer already closed. Like the bot board,
    # SQLite owns synchronization once connected; the sidecar check and open are not atomic.
    idle = not sidecars or _no_connection_open(path)
    with closing(connect_readonly(path, timeout=0.2, immutable=idle)) as db:
        db.text_factory = lambda raw: raw.decode("utf-8", "replace")
        deadline = monotonic() + 0.75
        db.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
        db.execute("BEGIN")  # revalidation and messages share one read transaction
        yield db, (info.st_dev, info.st_ino)


def _eligibility(columns: set[str]) -> str:
    visible = "".join(f" AND COALESCE(s.{flag}, 0) = 0" for flag in ("hidden", "archived") if flag in columns)
    if "model_config" in columns:
        visible += (" AND json_extract(CASE WHEN json_valid(s.model_config) THEN s.model_config ELSE '{}' END, "
                    "'$._delegate_from') IS NULL")
    marks = ",".join("?" for _ in _NOISE)
    return (f"lower(trim(COALESCE(s.source, ''))) NOT IN ({marks}) AND s.message_count > 0{visible} "
            "AND EXISTS (SELECT 1 FROM messages WHERE session_id = s.id)")


def _rows(db: sqlite3.Connection, profile: str) -> tuple[list[tuple[SessionRow, str]], bool]:
    columns = _columns(db, "sessions")
    eligible = _eligibility(columns)
    latest_message = "(SELECT max(timestamp) FROM messages WHERE session_id = s.id)"
    active = latest_message
    if "last_activity_at" in columns:
        active = f"max(COALESCE(s.last_activity_at, 0), COALESCE({latest_message}, 0))"
    source = "COALESCE(NULLIF(s.created_source, ''), s.source)" if "created_source" in columns else "s.source"
    recent = db.execute(f"""
        SELECT s.id, substr(s.title, 1, 240), (SELECT substr(m.content, 1, 240) FROM messages m
            WHERE m.session_id = s.id AND m.role = 'user' AND m.content IS NOT NULL
            ORDER BY m.timestamp, m.id LIMIT 1), s.started_at, s.message_count, {source},
            COALESCE(NULLIF({active}, 0), s.started_at)
        FROM sessions s WHERE {eligible}
        ORDER BY 7 DESC, s.started_at DESC, s.id DESC LIMIT ?
        """, (*_NOISE, _ROW_LIMIT + 1)).fetchall()

    # Hermes' canonical local reset receipt groups its segments separately from compression.
    # Only accept an alias backed by this row's own receipt membership in this store.
    receipt_ids = "chat_id" in columns and db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='state_meta'").fetchone()
    segment_aliases: dict[str, set[str]] = {}
    group_by_alias: dict[str, int] = {}
    groups: dict[int, set[str]] = {}
    for number, (sid, *_) in enumerate(recent[:_ROW_LIMIT]):
        lineage = segment_aliases.get(sid)
        if lineage is None:
            segments = conversation_segments(db, sid)
            lineage = segments.copy()
            if receipt_ids:
                lineage.update(row[0] for row in db.execute("""
                SELECT j.value FROM sessions s JOIN state_meta r ON r.key = 'gateway.local_policy.v1:' || s.chat_id,
                json_each(CASE WHEN json_valid(r.value) THEN r.value ELSE '{}' END, '$.lineage') j
                WHERE s.id IN (SELECT value FROM json_each(?)) AND s.source = 'local' AND j.type = 'text'
                AND json_extract(CASE WHEN json_valid(r.value) THEN r.value ELSE '{}' END, '$.session_id') = s.chat_id
                AND EXISTS (SELECT 1 FROM json_each(CASE WHEN json_valid(r.value) THEN r.value ELSE '{}' END,
                                                   '$.lineage') WHERE value = s.id) LIMIT 64
                """, (json.dumps(sorted(segments)),)))
            for segment in segments:
                segment_aliases[segment] = lineage
        # Fold overlapping reset and compression aliases before picking the newest representative.
        overlaps = {group_by_alias[alias] for alias in lineage if alias in group_by_alias}
        first = min(overlaps, default=number)
        merged = lineage.union(*(groups.pop(group) for group in overlaps))
        groups[first] = merged
        group_by_alias.update((alias, first) for alias in merged)

    result = []
    for number, lineage in sorted(groups.items()):
        sid, title, preview, started, count, source, activity = recent[number]
        fields = dict(id=sid, title=title, preview=preview, started_at=started, message_count=count,
                      source=source, activity_at=activity)
        for row in session_rows({"sessions": [fields]}):
            token = object()
            result.append((SessionRow("", " ".join(clean_text(row.title).split()),
                                      " ".join(clean_text(row.preview).split()) or clean_text(sid),
                                      row.started_at, row.message_count, row.activity_at, resumable=False,
                                      source=row.source, profile=profile, lineage=frozenset(lineage), local=token), sid))
    return result, len(recent) > _ROW_LIMIT


@dataclass
class Inventory:
    profiles: list[str] = field(default_factory=list)
    rows: list[SessionRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    _targets: dict[object, tuple[str, Path, str, tuple[int, int]]] = field(default_factory=dict, repr=False)

    @classmethod
    def read(cls, environ: Mapping[str, str]) -> "Inventory":
        inventory = cls()
        try:
            for name, home in _homes(environ):
                inventory.profiles.append(name)
                try:
                    with _store(home) as (db, identity):
                        rows, limited = _rows(db, name)
                except FileNotFoundError:  # an installed profile may not have started a session yet
                    continue
                except (OSError, sqlite3.Error, ValueError, OverflowError):
                    inventory.problems.append(f"{name}: session store unavailable")
                    continue
                if limited:
                    inventory.problems.append(f"{name}: newest {_ROW_LIMIT} stored segments shown")
                for row, sid in rows:
                    inventory.rows.append(row)
                    inventory._targets[row.local] = (name, home, sid, identity)
        except OSError:
            inventory.problems.append("Profile discovery incomplete")
        return inventory

    def transcript(self, environ: Mapping[str, str], handle: object) -> dict[str, Any]:
        """Look up a picker-issued handle; the UI supplies neither a store path nor a database ID."""
        target = self._targets.get(handle)
        if target is None:
            return {"problem": "Local history selection expired"}
        profile, home, sid, original = target
        try:
            if not any(name == profile and entry == home for name, entry in _homes(environ)):
                return {"problem": "Local profile is no longer registered"}
            with _store(home) as (db, identity):
                if identity != original:
                    return {"problem": "Local session store changed; reopen /sessions"}
                eligible = _eligibility(_columns(db, "sessions"))
                if not db.execute(f"SELECT 1 FROM sessions s WHERE s.id = ? AND {eligible}", (sid, *_NOISE)).fetchone():
                    return {"problem": "Local session is no longer available in the picker"}
                rows = db.execute("""
                    SELECT role, substr(content, 1, ?), length(content) > ? FROM messages
                    WHERE session_id = ? AND role IN ('user', 'assistant') AND content IS NOT NULL
                    ORDER BY timestamp DESC, id DESC LIMIT ?
                    """, (_TEXT_LIMIT, _TEXT_LIMIT, sid, _PAGE_LIMIT + 1)).fetchall()
        except (OSError, sqlite3.Error, ValueError):
            return {"problem": "Local session history unavailable"}
        return {"rows": [{"role": role, "text": text, "truncated": bool(cut)}
                         for role, text, cut in reversed(rows[:_PAGE_LIMIT])], "older": len(rows) > _PAGE_LIMIT}


def background(read: Callable[[], _T], wake: Callable[[], None]) -> Future[_T]:
    """Run the bounded SQLite read away from the key/paint loop."""
    future: Future[_T] = Future()

    def run() -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            result = read()
        except Exception as error:
            future.set_exception(error)
        else:
            future.set_result(result)
        finally:
            wake()

    Thread(target=run, name="omh-profile-sessions", daemon=True).start()
    return future
