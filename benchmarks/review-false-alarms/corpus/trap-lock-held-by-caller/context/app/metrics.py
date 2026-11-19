import threading


class Counter:
    """Thread-safe named counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._total = 0

    def record(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._bump(name, amount)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._counts)

    def total(self) -> int:
        with self._lock:
            return self._total

    def _bump(self, name: str, amount: int) -> None:
        self._counts[name] = self._counts.get(name, 0) + amount
        self._total += amount
