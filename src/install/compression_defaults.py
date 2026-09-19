"""Hermes ``auxiliary.compression`` resilience defaults.

Contract: additive, idempotent, and never destructive to user-authored config.

A supervising session dies unrecoverably when the main model endpoint goes down,
the smaller fallback model rejects the oversized prompt, and the compressor that
would shrink it is pinned to the same dead endpoint. This module adds a
compression ``fallback_chain`` derived from the fallback providers the user
already configured; it never invents an endpoint and never rewrites an existing
user-authored chain.

Auxiliary config reasoning is deliberately kept out of ``install/config_adapter``
(which owns ``skills.external_dirs`` only). Like ``maintenance/advisory``, this
module uses a self-contained tolerant indentation reader instead of a YAML
dependency.
"""

from __future__ import annotations

from .config_adapter import ConfigChange, section_edit_guard


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block_end(lines: list[str], start: int, indent: int) -> int:
    """Index just past the last non-blank child line of the block opened at `start`."""
    end = start + 1
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        if not line.strip():
            continue
        if _indent_of(line) <= indent:
            break
        end = idx + 1
    return end


def _find_mapping_key(lines: list[str], key: str, *, indent: int, start: int, stop: int) -> int | None:
    for idx in range(start, min(stop, len(lines))):
        line = lines[idx]
        if not line.strip() or _indent_of(line) != indent:
            continue
        stripped = line.strip()
        if stripped == f"{key}:" or stripped.startswith(f"{key}: "):
            return idx
    return None


def _scalar_value(line: str) -> str:
    _, _, value = line.strip().partition(":")
    return value.strip().strip("'\"")


def _fallback_entries(lines: list[str], start: int, indent: int) -> list[dict[str, str]]:
    """Parse a `fallback_chain`/`fallback_providers` block list into provider/model pairs."""
    entries: list[dict[str, str]] = []
    end = _block_end(lines, start, indent)
    current: dict[str, str] | None = None
    item_indent: int | None = None
    for idx in range(start + 1, end):
        line = lines[idx]
        if not line.strip():
            continue
        line_indent = _indent_of(line)
        stripped = line.strip()
        if stripped.startswith("- "):
            item_indent = line_indent
            current = {}
            entries.append(current)
            inner = stripped[2:].strip()
            if inner.startswith("provider:"):
                current["provider"] = _scalar_value(inner)
            elif ":" not in inner:
                current["provider"] = inner.strip("'\"")
            continue
        if current is None or item_indent is None or line_indent <= item_indent:
            continue
        if stripped.startswith("provider:"):
            current["provider"] = _scalar_value(stripped)
        elif stripped.startswith("model:"):
            current["model"] = _scalar_value(stripped)
    return [entry for entry in entries if entry.get("provider")]


def compression_fallback_candidates(config_text: str) -> list[dict[str, str]]:
    """Fallback provider/model pairs the user already configured outside `auxiliary`."""
    lines = config_text.splitlines()
    auxiliary_index = _find_mapping_key(lines, "auxiliary", indent=0, start=0, stop=len(lines))
    auxiliary_range = (
        range(auxiliary_index, _block_end(lines, auxiliary_index, 0)) if auxiliary_index is not None else range(0)
    )
    candidates: list[dict[str, str]] = []
    for idx, line in enumerate(lines):
        if idx in auxiliary_range:
            continue
        stripped = line.strip()
        if stripped not in ("fallback_chain:", "fallback_providers:"):
            continue
        for entry in _fallback_entries(lines, idx, _indent_of(line)):
            if entry not in candidates:
                candidates.append(entry)
    return candidates


def compression_settings(config_text: str) -> dict[str, object]:
    """Read `auxiliary.compression` without interpreting the rest of the config."""
    lines = config_text.splitlines()
    auxiliary_index = _find_mapping_key(lines, "auxiliary", indent=0, start=0, stop=len(lines))
    if auxiliary_index is None:
        return {"configured": False, "provider": "", "model": "", "has_fallback_chain": False}
    auxiliary_end = _block_end(lines, auxiliary_index, 0)
    compression_index = None
    for idx in range(auxiliary_index + 1, auxiliary_end):
        stripped = lines[idx].strip()
        if stripped == "compression:" and _indent_of(lines[idx]) > 0:
            compression_index = idx
            break
    if compression_index is None:
        return {"configured": False, "provider": "", "model": "", "has_fallback_chain": False}
    compression_indent = _indent_of(lines[compression_index])
    compression_end = _block_end(lines, compression_index, compression_indent)
    key_indent = next(
        (
            _indent_of(lines[idx])
            for idx in range(compression_index + 1, compression_end)
            if lines[idx].strip() and _indent_of(lines[idx]) > compression_indent
        ),
        compression_indent + 2,
    )
    provider_index = _find_mapping_key(lines, "provider", indent=key_indent, start=compression_index + 1, stop=compression_end)
    model_index = _find_mapping_key(lines, "model", indent=key_indent, start=compression_index + 1, stop=compression_end)
    fallback_index = _find_mapping_key(
        lines, "fallback_chain", indent=key_indent, start=compression_index + 1, stop=compression_end
    )
    return {
        "configured": True,
        "provider": _scalar_value(lines[provider_index]) if provider_index is not None else "",
        "model": _scalar_value(lines[model_index]) if model_index is not None else "",
        "has_fallback_chain": fallback_index is not None,
        "block_start": compression_index,
        "block_end": compression_end,
        "key_indent": key_indent,
    }


def ensure_compression_defaults(config_text: str) -> ConfigChange:
    """Add a compression fallback chain when the compressor is a single endpoint.

    Hermes cannot compress a session when `auxiliary.compression` points at one
    unreachable provider, so a dead endpoint strands the session in an
    unrecoverable `Cannot compress further` loop. Derive the fallback from the
    fallback providers the user already configured; never invent an endpoint,
    never touch an existing user-authored `fallback_chain`.
    """
    settings = compression_settings(config_text)
    if not settings["configured"]:
        return ConfigChange(False, "auxiliary.compression not configured", config_text)
    if settings["has_fallback_chain"]:
        return ConfigChange(False, "compression fallback chain already present", config_text)
    provider = str(settings["provider"])
    candidates = [entry for entry in compression_fallback_candidates(config_text) if entry.get("provider") != provider]
    if not candidates:
        return ConfigChange(False, "no configured fallback provider to derive a compression chain from", config_text)
    fallback = candidates[0]
    key_indent = int(settings["key_indent"])
    item_indent = key_indent + 2
    block = [f"{' ' * key_indent}fallback_chain:", f"{' ' * item_indent}- provider: {fallback['provider']}"]
    if fallback.get("model"):
        block.append(f"{' ' * (item_indent + 2)}model: {fallback['model']}")
    lines = config_text.splitlines()
    lines[int(settings["block_end"]):int(settings["block_end"])] = block
    return ConfigChange(True, "added auxiliary.compression fallback chain", "\n".join(lines) + "\n")


def compression_fallback_chain_lines(config_text: str) -> list[str]:
    """The verbatim lines of `auxiliary.compression.fallback_chain`, or [].

    Verbatim rather than parsed because the only consumer compares them
    against the ones OMH wrote: a chain that still reads byte for byte the
    way `ensure_compression_defaults` left it is OMH's to take back, and a
    chain a person has since edited by one character is not.
    """
    settings = compression_settings(config_text)
    if not settings["configured"] or not settings["has_fallback_chain"]:
        return []
    lines = config_text.splitlines()
    start = _find_mapping_key(
        lines,
        "fallback_chain",
        indent=int(settings["key_indent"]),
        start=int(settings["block_start"]) + 1,
        stop=int(settings["block_end"]),
    )
    if start is None:
        return []
    end = _block_end(lines, start, int(settings["key_indent"]))
    return lines[start:end]


def remove_compression_fallback_chain(config_text: str, expected: list[str]) -> ConfigChange:
    """Take back a compression fallback chain that still reads exactly `expected`.

    The chain is derived from the person's own providers, so unlike
    `display.skin: omh` it carries no mark saying OMH wrote it. The recorded
    lines are that mark, and a mismatch of any kind -- edited, extended,
    replaced -- leaves the chain alone and is reported.
    """
    if not expected:
        return ConfigChange(False, "no recorded compression fallback chain", config_text)
    # The same refusal the display and memory removers take. The verbatim
    # compare below is already strict, but it says nothing about the rest of
    # the document: deleting lines out of a file whose root is a sequence, or
    # whose keys carry anchors, changes what a node elsewhere resolves to.
    guard = section_edit_guard(config_text.splitlines(), "auxiliary", "compression")
    if guard:
        return ConfigChange(False, guard, config_text)
    current = compression_fallback_chain_lines(config_text)
    if not current:
        return ConfigChange(False, "auxiliary.compression.fallback_chain is not set", config_text)
    if current != expected:
        return ConfigChange(
            False,
            "auxiliary.compression.fallback_chain no longer matches the one OMH wrote; leaving it alone",
            config_text,
        )
    lines = config_text.splitlines()
    settings = compression_settings(config_text)
    start = _find_mapping_key(
        lines,
        "fallback_chain",
        indent=int(settings["key_indent"]),
        start=int(settings["block_start"]) + 1,
        stop=int(settings["block_end"]),
    )
    if start is None:
        return ConfigChange(False, "auxiliary.compression.fallback_chain line not found", config_text)
    del lines[start : start + len(current)]
    return ConfigChange(True, "removed auxiliary.compression fallback chain", "\n".join(lines).rstrip("\n") + "\n")
