import sqlite3


class Store:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def busy_intervals(self, room_id: int, day: str) -> list[tuple[int, int]]:
        """Bookings for one room and day as (start, end) minutes, sorted by start."""
        rows = self._conn.execute(
            "SELECT start_min, end_min FROM bookings WHERE room_id = ? AND day = ?",
            (room_id, day),
        ).fetchall()
        return sorted((start, end) for start, end in rows)
