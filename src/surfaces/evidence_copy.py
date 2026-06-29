from __future__ import annotations


def first_not_evidence_item(items: list[str]) -> str:
    """Return the first evidence gap as readable chat copy."""
    return items[0].replace("_", " ") if items else ""


def not_evidence_reply_suffix(items: list[str], *, fallback: str) -> str:
    item = first_not_evidence_item(items)
    if item:
        return f" This is still not evidence of {item}."
    return fallback


def not_evidence_action_suffix(items: list[str], *, fallback: str = "; keep evidence claims separate") -> str:
    item = first_not_evidence_item(items)
    if item:
        return f"; do not claim {item} until observed"
    return fallback
