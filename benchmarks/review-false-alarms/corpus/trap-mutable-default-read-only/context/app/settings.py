DEFAULTS = {"theme": "light", "page_size": 25, "beta": False}


def merged(overrides: dict = {}) -> dict:
    result = dict(DEFAULTS)
    if overrides:
        result.update(overrides)
    return result
