import sqlite3

from app.kinds import EventKind


def count_events(conn: sqlite3.Connection, kind: EventKind, since: str) -> int:
    table = f"{kind.value}_events"
    row = conn.execute(f"SELECT count(*) FROM {table} WHERE created_at >= ?", (since,)).fetchone()
    return row[0]
