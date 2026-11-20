from app.intervals import merge_busy

DAY_END = 24 * 60


def free_slots(store, room_id: int, day: str) -> list[tuple[int, int]]:
    busy = merge_busy(store.busy_intervals(room_id, day))
    slots, cursor = [], 0
    for start, end in busy:
        if start > cursor:
            slots.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < DAY_END:
        slots.append((cursor, DAY_END))
    return slots
