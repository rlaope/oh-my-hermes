import threading


class Cache:
    def __init__(self, loader, max_entries: int = 256) -> None:
        self._loader = loader
        self._max = max_entries
        self._entries: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._entries:
                return self._entries[key]
        value = self._loader(key)
        self._entries[key] = value
        if len(self._entries) > self._max:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        return value
