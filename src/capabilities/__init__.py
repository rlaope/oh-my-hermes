from __future__ import annotations

__all__ = [
    "capability_snapshot",
    "filtered_capability_snapshot",
    "inspect_capability",
    "list_capabilities",
]


def __getattr__(name: str):
    if name in __all__:
        from . import registry

        return getattr(registry, name)
    raise AttributeError(name)
