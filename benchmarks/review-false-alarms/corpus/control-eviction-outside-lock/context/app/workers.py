from concurrent.futures import ThreadPoolExecutor

from app.cache import Cache


def resolve_all(keys, loader):
    cache = Cache(loader, max_entries=64)
    with ThreadPoolExecutor(max_workers=16) as pool:
        return list(pool.map(cache.get, keys))
