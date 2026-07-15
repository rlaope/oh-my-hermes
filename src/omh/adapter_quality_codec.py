from __future__ import annotations

import hashlib
import json


def fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def canonical(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def semantic(value: dict[str, object], excluded: set[str]) -> str:
    return canonical({key: item for key, item in value.items() if key not in excluded})
