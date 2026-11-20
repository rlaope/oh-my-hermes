from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Token:
    user_id: int
    expires_at: datetime
    revoked: bool = False


def token_from_row(row) -> Token:
    # Rows store expires_at as written by issue(): "2026-11-20T08:30:00", no offset.
    return Token(
        user_id=row["user_id"],
        expires_at=datetime.fromisoformat(row["expires_at"]),
        revoked=bool(row["revoked"]),
    )


def issue(conn, user_id: int, ttl: timedelta) -> None:
    expires_at = datetime.utcnow() + ttl
    conn.execute(
        "INSERT INTO tokens (user_id, expires_at, revoked) VALUES (?, ?, 0)",
        (user_id, expires_at.isoformat(timespec="seconds")),
    )
