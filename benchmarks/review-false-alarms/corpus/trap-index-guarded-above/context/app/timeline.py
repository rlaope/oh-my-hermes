from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    at: float
    label: str


def next_event(events: list[Event], index: int) -> Event | None:
    """The event after events[index], or None when there is none."""
    if index < 0 or index >= len(events) - 1:
        return None
    return events[index + 1]
