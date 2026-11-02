"""Read the parent channel of a Discord thread Hermes auto-created.

Hermes' ``gateway/session_recovery.py`` serializes the whole ``SessionSource``
into ``sessions.origin_json`` in the INSERT that creates the session row. The
Discord adapter in ``plugins/platforms/discord/adapter.py`` sets
``parent_chat_id`` for thread messages and ``auto_thread_created`` when it
opens a thread from a channel message. Only those auto-created threads can
widen their memory scope: ``message.create_thread`` makes a public thread in
the parent channel; a thread opened another way may be private.

Hermes does not pass ``parent_chat_id`` to memory providers at ``initialize``:
``agent/agent_init_params.py`` omits it from ``_GATEWAY_IDENTITY_PARAMS``. This
bounded, read-only lookup recovers that missing anchor without caching it,
writing Hermes state, or reading message text. A WAL store missing either
sidecar gives no parent: even a read-only SQLite open can create those files.
An unusable store gives no parent rather than widening a scope on uncertain
evidence.

Stdlib only; Hermes loads this bundle without the OMH package installed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3

from .sqlite_readonly import connect_readonly

_SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_DISCORD_SNOWFLAKE = re.compile(r"[1-9][0-9]{16,19}")
_BUSY_TIMEOUT_SECONDS = 0.2


def auto_thread_parent_channel(hermes_home: str | Path, session_id: str) -> str | None:
    """Return an auto-created Discord thread's distinct parent, or None on doubt."""
    if not isinstance(session_id, str) or not _SAFE_SESSION_ID.fullmatch(session_id):
        return None
    try:
        path = Path(hermes_home) / "state.db"
        if not path.is_file():
            return None
        if not all(path.with_name(path.name + suffix).is_file() for suffix in ("-wal", "-shm")):
            # A mode=ro WAL open can create missing sidecars. Do not use
            # immutable=1 on a live store, which would ignore committed WAL rows.
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                header = os.read(descriptor, 20)
            finally:
                os.close(descriptor)
            if b"\x02" in header[18:20]:
                return None
        connection = connect_readonly(path, timeout=_BUSY_TIMEOUT_SECONDS)
        try:
            row = connection.execute("SELECT origin_json FROM sessions WHERE id = ?", (session_id,)).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError, TypeError, ValueError):
        return None
    if row is None or not isinstance(row[0], str):
        return None
    try:
        origin = json.loads(row[0])
    except (ValueError, RecursionError):
        return None
    if not isinstance(origin, dict):
        return None
    if origin.get("platform") != "discord" or origin.get("chat_type") != "thread":
        return None
    if origin.get("auto_thread_created") is not True:
        return None
    parent = origin.get("parent_chat_id")
    if not isinstance(parent, str) or not _DISCORD_SNOWFLAKE.fullmatch(parent):
        return None
    return parent if parent != origin.get("chat_id") else None
