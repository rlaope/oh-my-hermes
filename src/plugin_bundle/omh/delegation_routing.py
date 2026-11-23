"""Prepared per-dispatch model routing for Hermes-native delegation.

Hermes `delegate_task` resolves the child's model, provider, and reasoning
effort from the `delegation.*` keys of `config.yaml` **at every dispatch**,
and its config cache is keyed on the file's mtime and size — editing the file
between dispatches is therefore a supported, race-free way to give each child
its own route: write the route, dispatch the lane, write the next route,
dispatch the next lane. Children already running keep the model they were
built with.

This module owns that write. It is deliberately narrow:

* Only the three routable keys under the top-level `delegation:` section are
  ever touched — `model`, `reasoning_effort`, `provider`. Every other byte of
  the config, including the rest of the delegation section, passes through
  unchanged.
* Values must be plain identifier tokens; anything else is refused rather
  than quoted, so a crafted "model name" can never smuggle YAML structure.
* The write is atomic (temp file + rename in the config's directory) and a
  symlinked config is refused instead of silently replaced with a file.
* A route Hermes would not send where it says is refused before any byte is
  written (`guard_route_endpoint`, see `route_endpoint_guard`): a direct
  `delegation.base_url` that overrides the provider, the main model's
  local-endpoint bypass, a managed config layered over this file, or a shape
  the guard cannot read. The keys it names are the person's; OMH never
  rewrites them.
* A leading byte-order mark stays where it is, and the `delegation:` line
  after it is recognised rather than duplicated.
* `delegation.fallback_providers` is a fourth key only when a caller asks for
  it (the opt-in in-child chain, `delegation_fallback_chain`). It is a block
  sequence, written by its own block writer under the same rules: every value
  is a plain identifier token in single quotes, the write is the same atomic
  replace, and a value this writer did not produce in its own shape (`[]`,
  a flow list, an entry with a `base_url` or any other key, a comment inside
  the block) is the person's and is never rewritten or removed.

Writing a route is preparation, not execution: nothing dispatches from here,
and the route only takes effect when the agent's next `delegate_task` call
reads it.
"""

from __future__ import annotations

from . import runtime_paths
from .route_endpoint_guard import BOM, child_endpoint, managed_config_layer, route_endpoint_refusal

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping

ROUTABLE_KEYS = ("model", "reasoning_effort", "provider")
# The in-child fallback chain. A mapping OMH STORES (the record's last
# write, a conversation's route, provenance) carries it, as
# `encode_fallback_chain`'s canonical text, only when OMH wrote that chain;
# the person's own chain is never part of a route. A live read is compared
# with a stored mapping through `route_like`, which keeps the chain key only
# when the stored side has one, so a person editing or removing their own
# chain is never mistaken for a change to OMH's route.
FALLBACK_CHAIN_KEY = "fallback_providers"
ROUTE_KEYS = (*ROUTABLE_KEYS, FALLBACK_CHAIN_KEY)
_CHAIN_ENTRY_KEYS = ("provider", "model", "reasoning_effort")
_MAX_CHAIN_ENTRIES = 16
# The longest chain text a provenance record keeps (`hermes_delegation`).
MAX_CHAIN_TEXT = 4096
# What `_read_fallback_chain` can say about the key.
CHAIN_ABSENT = "absent"
CHAIN_OMH_SHAPE = "chain"
CHAIN_FOREIGN = "foreign"
# More than one `delegation:` section: the scalar writer writes each, a list
# cannot be put in both, so no chain is written or removed there.
CHAIN_UNSUPPORTED = "unsupported"

_VALUE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]|:(?=[A-Za-z0-9])){0,127}$")
_SECTION_RE = re.compile(r"^delegation:\s*(#.*)?$")
_MODEL_SECTION_RE = re.compile(r"^model:\s*(#.*)?$")
_MODEL_PROVIDER_RE = re.compile(r"^\s+provider\s*:")
def _managed_key_re(key: str, indent: int) -> re.Pattern[str]:
    return re.compile(rf"^ {{{indent}}}{re.escape(key)}\s*:")


def read_delegation_route(hermes_home: str | Path | None = None, *, with_chain: bool = False) -> dict[str, str]:
    """Read the current routable delegation keys from config.yaml (text scan).

    Last occurrence wins, mirroring YAML's duplicate-key behaviour, so what
    this reports is what Hermes will actually resolve.

    `with_chain` adds `fallback_providers` when the file holds a chain in
    this writer's shape, whoever wrote it; compare it with a stored mapping
    through `route_like`.
    """
    config_path = _config_path(hermes_home)
    text, _, error = _read_config_snapshot(config_path)
    if error:
        return {}
    return _read_route_with_chain(text) if with_chain else _read_delegation_route_text(text)


def route_like(live: Mapping[str, str], stored: Mapping[str, str]) -> dict[str, str]:
    """`live` (a `with_chain` read) as `stored` sees it: the chain only when `stored` has one.

    A stored mapping names a chain only when OMH wrote it, so a chain the
    person owns stays out of every "does the file still hold OMH's route?"
    comparison, and a record from before the chain existed still matches.
    """
    if FALLBACK_CHAIN_KEY in stored:
        return dict(live)
    return {key: value for key, value in live.items() if key != FALLBACK_CHAIN_KEY}


def read_delegation_settings(hermes_home: str | Path | None, keys: tuple[str, ...]) -> dict[str, str]:
    """Other `delegation.*` scalars (`max_concurrent_children`, ...) as written, quotes and comments dropped.

    The same section scan as the routable keys, read-only and last occurrence
    wins; a value that is not a one-line scalar is left out, so a caller falls
    back to Hermes' own default for it.
    """
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return {}
    lines = text.removeprefix(BOM).splitlines()
    child_indents = _delegation_child_indents(lines)
    values: dict[str, str] = {}
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section, child_indent = True, child_indents.get(index, 2)
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        key = _mapping_key(line, child_indent) if in_section else None
        if key in keys and _managed_key_re(key, child_indent).match(line):
            raw = line.partition(":")[2].split("#", 1)[0].strip().strip("'\"")
            if raw and not _continuation_follows(lines, index, child_indent):
                values[key] = raw
            else:
                values.pop(key, None)
    return values


def read_child_endpoint(hermes_home: str | Path | None = None) -> dict[str, str] | None:
    """Where Hermes builds a delegated child while `delegation.base_url` is set.

    `route_endpoint_guard.child_endpoint` over config.yaml and Hermes'
    managed config. A route that names no provider is written on that
    endpoint, so this is what makes it visible.
    """
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return {"from": "config.yaml", "host": "", "provider": ""}
    return child_endpoint(text, managed_config_layer())


def _read_delegation_route_text(text: str) -> dict[str, str]:
    lines = text.removeprefix(BOM).splitlines()
    if _has_unsupported_delegation(lines):
        return {}
    child_indents = _delegation_child_indents(lines)
    values: dict[str, str] = {}
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section = True
            child_indent = child_indents.get(index, 2)
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        if not in_section:
            continue
        for key in ROUTABLE_KEYS:
            if _managed_key_re(key, child_indent).match(line):
                _, _, raw = line.partition(":")
                value = _yaml_string_token(raw)
                if value is None:
                    return {}
                # An empty value is Hermes's stock "inherit" spelling for the
                # key; last occurrence wins, so it unsets an earlier value.
                if value:
                    values[key] = value
                else:
                    values.pop(key, None)
    return values


def _read_route_with_chain(text: str) -> dict[str, str]:
    """The three keys plus a chain in this writer's shape, whoever wrote it."""
    values = _read_delegation_route_text(text)
    lines = text.removeprefix(BOM).splitlines()
    if not _has_unsupported_delegation(lines):
        state, chain, _span = _read_fallback_chain(lines)
        if state == CHAIN_OMH_SHAPE:
            values[FALLBACK_CHAIN_KEY] = chain
    return values


def read_fallback_chain_state(hermes_home: str | Path | None = None) -> str:
    """`absent`, `chain` (a list in this writer's shape), `foreign` (a shape only a person writes) or `unsupported`.

    `null`, `~` and a bare `fallback_providers:` read as absent: Hermes treats
    them as the key not being there. An unreadable config reads as `foreign`, so nothing is written
    over a value nobody could see.
    """
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return CHAIN_FOREIGN
    return _read_fallback_chain(text.removeprefix(BOM).splitlines())[0]


def fallback_chain_is_empty_list(hermes_home: str | Path | None = None) -> bool:
    """Whether `delegation.fallback_providers` is the explicit `[]`, Hermes' "no fallback"."""
    text, _, error = _read_config_snapshot(_config_path(hermes_home))
    if error:
        return False
    lines = text.removeprefix(BOM).splitlines()
    child_indents = _delegation_child_indents(lines)
    in_section, child_indent, empty = False, 2, False
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section, child_indent = True, child_indents.get(index, 2)
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        if in_section and _mapping_key(line, child_indent) == FALLBACK_CHAIN_KEY:
            empty = line.partition(":")[2].split("#", 1)[0].strip() == "[]"
    return empty


def encode_fallback_chain(entries: Iterable[Mapping[str, Any]]) -> str | None:
    """The canonical text of a chain, or None when an entry is not writable.

    Each entry needs a provider and a model (Hermes drops an entry missing
    either), and every value must be a plain identifier token, the scalar
    writer's own rule, so nothing a model or a routing file supplies can
    carry YAML structure into the block.
    """
    cleaned: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            return None
        values = {key: str(entry.get(key, "") or "").strip() for key in _CHAIN_ENTRY_KEYS}
        if not values["provider"] or not values["model"]:
            return None
        if any(value and not _VALUE_RE.match(value) for value in values.values()):
            return None
        cleaned.append({key: value for key, value in values.items() if value})
    if not cleaned or len(cleaned) > _MAX_CHAIN_ENTRIES:
        return None
    text = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    return text if len(text) <= MAX_CHAIN_TEXT else None


def decode_fallback_chain(text: str) -> list[dict[str, str]] | None:
    """The entries of a canonical chain text, or None for anything else."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, list):
        return None
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - set(_CHAIN_ENTRY_KEYS):
            return None
        if any(not isinstance(value, str) for value in entry.values()):
            return None
    if encode_fallback_chain(raw) != text:
        return None
    return [dict(entry) for entry in raw]


def _read_fallback_chain(lines: list[str]) -> tuple[str, str, tuple[int, int] | None]:
    """The chain key's state, its canonical text, and the lines it spans.

    The span is returned for a chain in this writer's shape and for a bare
    `null`/`~`, the two values the writer may replace; a foreign value has
    none, so there is nothing for a caller to rewrite.
    """
    child_indents = _delegation_child_indents(lines)
    found: list[tuple[int, int]] = []
    sections = 0
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            in_section, child_indent = True, child_indents.get(index, 2)
            sections += 1
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        if in_section and _mapping_key(line, child_indent) == FALLBACK_CHAIN_KEY:
            found.append((index, child_indent))
    if sections > 1:
        # Two `delegation:` sections are a file the block writer would have
        # to pick one of; the scalar writer writes both, a list cannot.
        return CHAIN_UNSUPPORTED, "", None
    if not found:
        return CHAIN_ABSENT, "", None
    if len(found) > 1:
        return CHAIN_FOREIGN, "", None
    index, indent = found[0]
    header = lines[index]
    if not _managed_key_re(FALLBACK_CHAIN_KEY, indent).match(header):
        return CHAIN_FOREIGN, "", None
    inline = header.partition(":")[2].strip()
    end = _chain_block_end(lines, index, indent)
    if inline:
        if inline.casefold() in {"null", "~"} and end == index + 1:
            return CHAIN_ABSENT, "", (index, end)
        return CHAIN_FOREIGN, "", None
    if end == index + 1:
        # A bare `fallback_providers:` with nothing under it is YAML null.
        return CHAIN_ABSENT, "", (index, end)
    entries = _parse_chain_items(lines[index + 1 : end])
    encoded = encode_fallback_chain(entries) if entries else None
    if encoded is None:
        return CHAIN_FOREIGN, "", None
    return CHAIN_OMH_SHAPE, encoded, (index, end)


def _chain_block_end(lines: list[str], index: int, indent: int) -> int:
    """One past the last line that belongs to the value of the key at `index`.

    A blank or comment line inside the value is taken in, so the parse
    sees it and calls the value foreign rather than stopping short of it.
    """
    end = index + 1
    for position in range(index + 1, len(lines)):
        line = lines[position]
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        depth = len(line) - len(stripped)
        if depth > indent or (depth == indent and stripped.startswith("- ")):
            end = position + 1
            continue
        break
    return end


def _parse_chain_items(block: list[str]) -> list[dict[str, str]] | None:
    """A block sequence of `provider`/`model`/`reasoning_effort` mappings, or None.

    Both sequence indents parse (`- ` under the key, and PyYAML's default
    `- ` at the key's own indent), so a chain Hermes re-dumped is still
    recognised. Anything else -- a comment or blank line, another key, a
    nested value, a flow mapping, a tab -- is not this writer's shape.
    """
    entries: list[dict[str, str]] = []
    item_indent: int | None = None
    key_indent: int | None = None
    for line in block:
        stripped = line.lstrip(" ")
        if not stripped or stripped.startswith("#") or stripped[0] == "\t":
            return None
        indent = len(line) - len(stripped)
        if stripped.startswith("- "):
            body = stripped[2:]
            here = indent + 2 + len(body) - len(body.lstrip(" "))
            body = body.lstrip(" ")
            if item_indent is None:
                item_indent, key_indent = indent, here
            if indent != item_indent or here != key_indent:
                return None
            entries.append({})
        else:
            if not entries or indent != key_indent:
                return None
            body = stripped
        key, separator, raw = body.partition(":")
        if not separator or key not in _CHAIN_ENTRY_KEYS or key in entries[-1]:
            return None
        if raw and not raw[0].isspace():
            return None
        if "#" in raw:
            # No token this writer writes holds `#`, so it is a comment, and
            # a chain with the person's note in it is theirs: rewriting it
            # would drop the note.
            return None
        value = _yaml_string_token(raw)
        if not value:
            return None
        entries[-1][key] = value
    return entries or None


def _chain_block_lines(prefix: str, chain: str) -> list[str]:
    """The block this writer emits for a canonical chain under `prefix`."""
    lines = [f"{prefix}{FALLBACK_CHAIN_KEY}:"]
    for entry in decode_fallback_chain(chain) or []:
        lead = f"{prefix}  - "
        for key in _CHAIN_ENTRY_KEYS:
            if key in entry:
                lines.append(f"{lead}{key}: '{entry[key]}'")
                lead = f"{prefix}    "
    return lines


def read_session_provider(hermes_home: str | Path | None = None) -> str:
    """The provider this session runs on, from config.yaml's own `model:` block.

    A child dispatched with no `delegation.provider` inherits this value, so
    it is the provider that will actually serve the run. Read by the same
    text scan as the delegation keys, and empty whenever the file, the block,
    or the key is missing -- an unknown provider must never be treated as a
    wrong one.
    """
    config_path = _config_path(hermes_home)
    text, _, error = _read_config_snapshot(config_path)
    if error:
        return ""
    return _read_session_provider_text(text)


def _read_session_provider_text(text: str) -> str:
    lines = text.removeprefix(BOM).splitlines()
    in_model = False
    provider = ""
    for line in lines:
        if _MODEL_SECTION_RE.match(line):
            in_model = True
            continue
        if in_model and _top_level_key(line) is not None:
            in_model = False
        if not in_model:
            continue
        if _MODEL_PROVIDER_RE.match(line):
            _, _, raw = line.partition(":")
            value = _yaml_string_token(raw)
            # Last occurrence wins, mirroring YAML, and a bare empty value
            # unsets an earlier one exactly as it does for delegation keys.
            provider = value or ""
    return provider


_ROUTE_WRITE_ATTEMPTS = 5


def _apply_route_delta(text: str, desired: Mapping[str, str], chain: str | None = None) -> str:
    """Return text with only the routable delegation keys set to desired.

    Pure transformation: every other line passes through unchanged (line
    endings come out as LF, as this writer has always written them). Returns
    text itself when there is nothing to add or remove, so the caller can skip
    a byte-identical write.

    `chain` is the fallback chain: None leaves its lines as they are, `""`
    removes a chain in this writer's shape, and a canonical chain text
    replaces it (or a bare `null`). The caller has already decided that the
    value in the file is one it may replace; a foreign value has no span, so
    it is never touched here either.
    """
    bom = BOM if text.startswith(BOM) else ""
    lines = text[len(bom):].splitlines()
    child_indents = _delegation_child_indents(lines)
    skip: range = range(0)
    if chain is not None:
        state, _current, span = _read_fallback_chain(lines)
        if span is not None and (state == CHAIN_OMH_SHAPE or chain):
            skip = range(*span)
    output: list[str] = []
    inserted = False
    in_section = False
    section_seen = False
    child_indent = 2
    for index, line in enumerate(lines):
        if index in skip:
            continue
        if _SECTION_RE.match(line):
            in_section = True
            section_seen = True
            output.append(line)
            child_indent = child_indents.get(index, 2)
            prefix = " " * child_indent
            for key in ROUTABLE_KEYS:
                value = desired.get(key, "")
                if value:
                    output.append(f"{prefix}{key}: '{value}'")
            if chain and not inserted:
                output.extend(_chain_block_lines(prefix, chain))
            inserted = True
            continue
        if in_section and _top_level_key(line) is not None:
            in_section = False
        if in_section and any(
            _managed_key_re(key, child_indent).match(line)
            for key in ROUTABLE_KEYS
        ):
            continue
        output.append(line)
    wanted = {key: value for key, value in desired.items() if value}
    if (wanted or chain) and not inserted:
        if output and output[-1].strip():
            output.append("")
        output.append("delegation:")
        for key in ROUTABLE_KEYS:
            value = wanted.get(key, "")
            if value:
                output.append(f"  {key}: '{value}'")
        if chain:
            output.extend(_chain_block_lines("  ", chain))
        section_seen = True
    if not section_seen and not wanted:
        return text
    new_text = bom + "\n".join(output)
    if text.endswith("\n") or not text:
        new_text += "\n"
    return new_text


def _unsupported_mapping_error() -> dict[str, str]:
    return {
        "status": "error",
        "error": (
            "unsupported delegation mapping; refusing to rewrite it — "
            "no route was written, so the next delegate_task dispatch "
            "inherits the parent model"
        ),
    }


def _route_candidate_refusal(
    text: str,
    previous: Mapping[str, str],
    desired: Mapping[str, str],
    *,
    expected_previous: Mapping[str, str] | None,
    guard_route_endpoint: bool,
) -> dict[str, Any] | None:
    """Every check a route write makes, judged on ONE read of the config.

    `previous` is that same read's route, so the endpoint guard's
    `current_provider` and a conditional write's predicate never mix two
    states of the file.
    """
    if expected_previous is not None and route_like(previous, expected_previous) != dict(expected_previous):
        return {
            "status": "error",
            "error": "active route changed before fallback write",
        }
    if _has_unsupported_delegation(text.removeprefix(BOM).splitlines()):
        return _unsupported_mapping_error()
    if guard_route_endpoint:
        return route_endpoint_refusal(
            text,
            provider=desired.get("provider", ""),
            current_provider=previous.get("provider", ""),
            managed=managed_config_layer(),
        )
    return None


def write_delegation_route(
    hermes_home: str | Path | None = None,
    *,
    model: str = "",
    reasoning_effort: str = "",
    provider: str = "",
    clear: bool = False,
    expected_previous: Mapping[str, str] | None = None,
    guard_route_endpoint: bool = False,
    fallback_providers: str | None = None,
    replaceable_fallback: Collection[str] | None = None,
) -> dict[str, Any]:
    """Set (or clear) the routable delegation keys, touching nothing else.

    Keys with an empty desired value are removed, restoring parent
    inheritance for that key; `clear=True` removes all three.

    `fallback_providers` is the in-child chain, independent of `clear`: None
    (every caller that predates it) leaves the key alone, `""` removes a
    chain, and a canonical chain text (`encode_fallback_chain`) writes it.
    The person's own value is never replaced or removed, judged on the read
    the write replaces: a foreign shape always, and a chain in this writer's
    shape unless it is in `replaceable_fallback` (None means any, which is
    for a restore that already matched the file against its record). A kept
    value is reported as `fallback_chain: kept_person_owned`.

    `previous` and `applied` are in the stored shape: each names a chain
    only when it is OMH's (the replaced one when it was replaceable, the
    written or unchanged one after), so they compare with a later
    `route_like` read. `expected_previous` is compared the same way.

    `guard_route_endpoint` is for a route: it refuses one Hermes would not
    send where it says (`route_endpoint_guard.route_endpoint_refusal`),
    judged on the same read of the config the write replaces. A restore
    leaves it off, because putting back the person's own values is not a
    switch.

    `previous` in a successful result is the route of the read the write
    replaced (or, when there was nothing to change, the read it confirmed),
    so a caller recording a baseline records what was really there.
    """
    desired = {} if clear else {
        "model": model.strip(),
        "reasoning_effort": reasoning_effort.strip(),
        "provider": provider.strip(),
    }
    for key, value in desired.items():
        if value and not _VALUE_RE.match(value):
            return {"status": "error", "error": f"invalid {key} value"}
    if fallback_providers and decode_fallback_chain(fallback_providers) is None:
        return {"status": "error", "error": f"invalid {FALLBACK_CHAIN_KEY} value"}
    config_path = _config_path(hermes_home)
    text, signature, error = _read_config_snapshot(config_path)
    if error:
        return {"status": "error", "error": error}
    if _file_signature(config_path) != signature:
        return {"status": "error", "error": "config changed during route read"}
    first_route = _read_route_with_chain(text)
    refusal = _route_candidate_refusal(
        text,
        first_route,
        desired,
        expected_previous=expected_previous,
        guard_route_endpoint=guard_route_endpoint,
    )
    if refusal:
        return refusal
    wanted = {key: value for key, value in desired.items() if value}
    # Write from the latest config, not the validation snapshot. A writer
    # outside the OMH lock (`hermes config set`) may change the file at any
    # time, so each attempt re-reads it and that read is THE candidate: every
    # check above runs again on it, and the delegation delta is applied to it.
    # Drift in an unrelated key is merged. Drift in the routable keys
    # themselves is refused, as it was before this loop existed, so a newer
    # pin is never overwritten. The candidate's stamp is compared again right
    # before success: before a no-op is reported, and after the temp file is
    # written and its mode set, immediately before `os.replace` (the ordering
    # of `system.local_store.atomic_write_text`).
    #
    # Best effort, not a transaction: Hermes' CLI takes no OMH lock, so a
    # write landing after that last comparison and before the rename is
    # still replaced. The loop narrows that window; it cannot close it.
    for _attempt in range(_ROUTE_WRITE_ATTEMPTS):
        fresh_text, fresh_signature, fresh_error = _read_config_snapshot(config_path)
        if fresh_error:
            return {"status": "error", "error": fresh_error}
        previous = _read_route_with_chain(fresh_text)
        refusal = _route_candidate_refusal(
            fresh_text,
            previous,
            desired,
            expected_previous=expected_previous,
            guard_route_endpoint=guard_route_endpoint,
        )
        if refusal:
            return refusal
        if previous != first_route:
            return {
                "status": "error",
                "error": (
                    "active route changed during route update; no route was "
                    "written, so the route already in place stays"
                ),
            }
        chain, chain_note = _chain_decision(
            fresh_text, previous, fallback_providers, replaceable_fallback
        )
        current_chain = previous.get(FALLBACK_CHAIN_KEY, "")
        applied = dict(wanted)
        if chain_note == "written" and chain:
            applied[FALLBACK_CHAIN_KEY] = chain
        elif chain_note == "unchanged" and current_chain:
            applied[FALLBACK_CHAIN_KEY] = current_chain
        replaced = {key: value for key, value in previous.items() if key != FALLBACK_CHAIN_KEY}
        if current_chain and chain_note in ("written", "removed", "unchanged"):
            replaced[FALLBACK_CHAIN_KEY] = current_chain
        noted = {"fallback_chain": chain_note} if chain_note else {}
        new_text = _apply_route_delta(fresh_text, desired, chain)
        if new_text == fresh_text:
            if not _unchanged_since(config_path, fresh_signature, fresh_text):
                continue
            return {
                "status": "cleared" if clear else "routed",
                "previous": replaced,
                "applied": applied,
                **noted,
            }
        try:
            # The mode is read before the temp file exists, so nothing but
            # the stamp comparison sits between the last check and the rename.
            try:
                mode: int | None = config_path.stat().st_mode & 0o7777
            except FileNotFoundError:
                mode = None
            config_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=".omh-delegation-route-", dir=str(config_path.parent)
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(new_text)
                if mode is not None:
                    os.chmod(temp_name, mode)
                if not _unchanged_since(config_path, fresh_signature, fresh_text):
                    os.unlink(temp_name)
                    continue
                os.replace(temp_name, config_path)
            except OSError:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            return {"status": "error", "error": f"config write failed: {type(exc).__name__}"}
        return {
            "status": "cleared" if clear else "routed",
            "previous": replaced,
            "applied": applied,
            **noted,
        }
    return {"status": "error", "error": "config kept changing during route update"}


def _chain_decision(
    text: str,
    previous: Mapping[str, str],
    desired: str | None,
    replaceable: Collection[str] | None,
) -> tuple[str | None, str]:
    """What the writer does to the chain on this read: the `chain` for `_apply_route_delta`, and a note.

    The note is empty when the caller did not ask about the chain, and
    otherwise names the outcome: `written`, `removed`, `unchanged` or
    `kept_person_owned` (or `kept_unsupported_config` for a file with two
    `delegation:` sections). After `written`, `removed` or `unchanged` any
    chain in the file is OMH's; after a `kept_` note it is not.
    """
    if desired is None:
        return None, ""
    state = _read_fallback_chain(text.removeprefix(BOM).splitlines())[0]
    current = previous.get(FALLBACK_CHAIN_KEY, "")
    if state == CHAIN_UNSUPPORTED:
        return None, "kept_unsupported_config" if desired else "unchanged"
    if state == CHAIN_FOREIGN:
        return None, "kept_person_owned"
    if current and replaceable is not None and current not in replaceable:
        # Even when it equals the chain asked for: the note is what says
        # whose chain the file holds, and this one is the person's.
        return None, "kept_person_owned"
    if current == desired:
        return None, "unchanged"
    return desired, "written" if desired else "removed"


def delegation_config_path(hermes_home: str | Path | None = None) -> Path:
    """The canonical identity of the config.yaml these keys live in.

    Public because the restore record has to say WHICH config it describes:
    two Hermes profiles may share one OMH home by design, and a record that
    named no file let one profile's session act on the other's route.

    The PARENT is resolved and the file name is not. Resolving the parent is
    what makes two callers agree: one may hold `/var/...` and another the
    `/private/var/...` the same path resolves to, and an unresolved compare
    reported one profile's own record as another profile's. Resolving the
    file itself would defeat the writer's `O_NOFOLLOW` refusal of a
    symlinked config, so this is identity only and never the path opened.
    """
    path = _config_path(hermes_home)
    try:
        return Path(os.path.realpath(path.parent)) / path.name
    except OSError:
        return path


def _config_path(hermes_home: str | Path | None) -> Path:
    if hermes_home:
        return Path(hermes_home).expanduser() / "config.yaml"
    return runtime_paths.default_hermes_home() / "config.yaml"


def _delegation_child_indents(lines: list[str]) -> dict[int, int]:
    indents: dict[int, int] = {}
    section_index: int | None = None
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line):
            section_index = index
            continue
        if section_index is None:
            continue
        if _top_level_key(line) is not None:
            section_index = None
            continue
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if indent:
            indents[section_index] = min(indents.get(section_index, indent), indent)
    return indents


def config_file_signature(path: Path) -> tuple[int, int, int, int] | None:
    """The stamp this writer compares, exposed for OMH's other config writers.

    Public on purpose and as a one-line alias rather than a second
    implementation: the whole point of one write discipline is that a CLI
    write and a route write can each detect the other, which they cannot do
    if the two sides compute their own idea of "the file changed" (#1742).

    `st_ino` is what carries the compare in practice. Both OMH writer
    families replace by rename, so the inode changes on every OMH write and
    the timestamp's resolution never enters into it. `st_mtime_ns` matters
    only for a third party rewriting the config IN PLACE at exactly the same
    size, and only on a filesystem that stores whole seconds (ext4 with
    128-byte inodes, HFS+); APFS and ext4 with 256-byte inodes store
    nanoseconds and distinguish consecutive rewrites.
    """
    return _file_signature(path)


def config_unchanged_since(
    path: Path, signature: tuple[int, int, int, int] | None, text: str
) -> bool:
    """The compare both writer families run right before their rename.

    The stamp plus a re-read of the text: an in-place same-size rewrite
    within the timestamp tick (NTFS keeps the write time coarsely) leaves
    the stamp equal, so the stamp alone would call an edited file unchanged.
    """
    return _unchanged_since(path, signature, text)


def read_config_snapshot(path: Path) -> tuple[str, tuple[int, int, int, int] | None, str]:
    """Read the config and its stamp together, the way this writer does.

    Same reason as above, plus the `O_NOFOLLOW` refusal of a symlinked
    config: a writer that reached the file another way would not inherit it.
    """
    return _read_config_snapshot(path)


def _file_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _unchanged_since(
    path: Path, signature: tuple[int, int, int, int] | None, text: str
) -> bool:
    """Whether the file still holds what was read: same stamp AND same text.

    The stamp alone misses an in-place rewrite of the same size within the
    file system's timestamp tick (NTFS updates the write time lazily and
    coarsely), so an equal stamp is confirmed by reading the text again.
    """
    if _file_signature(path) != signature:
        return False
    now_text, now_signature, error = _read_config_snapshot(path)
    return not error and now_signature == signature and now_text == text


def _read_config_snapshot(
    path: Path,
) -> tuple[str, tuple[int, int, int, int] | None, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return "", None, ""
    except OSError as exc:
        if path.is_symlink():
            return "", None, "config.yaml is a symlink; refusing to rewrite it"
        return "", None, f"config unreadable: {type(exc).__name__}"
    try:
        stat = os.fstat(descriptor)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        return "", None, f"config unreadable: {type(exc).__name__}"
    signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return text, signature, ""


def _has_unsupported_delegation(lines: list[str]) -> bool:
    child_indents = _delegation_child_indents(lines)
    in_section = False
    child_indent = 2
    for index, line in enumerate(lines):
        top_level_key = _top_level_key(line)
        if top_level_key == "delegation":
            if not _SECTION_RE.match(line):
                return True
            in_section = True
            child_indent = child_indents.get(index, 2)
            continue
        if in_section and top_level_key is not None:
            in_section = False
        if not in_section:
            continue
        key = _mapping_key(line, child_indent)
        if key not in ROUTABLE_KEYS:
            continue
        if not _managed_key_re(key, child_indent).match(line):
            return True
        _, _, raw = line.partition(":")
        if _yaml_string_token(raw) is None:
            return True
        # A plain scalar (null, ~, or an ordinary token) continues onto a
        # more-indented following line in YAML: OMH would read one value
        # while Hermes resolves the continuation, and the writer would drop
        # the key line and orphan that continuation into unparseable YAML.
        # Refuse any routable key whose next content line sits deeper — the
        # guard is about whether a continuation follows, not which token
        # appeared.
        if _continuation_follows(lines, index, child_indent):
            return True
    return False


def _continuation_follows(lines: list[str], index: int, indent: int) -> bool:
    for following in lines[index + 1 :]:
        stripped = following.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        return len(following) - len(stripped) > indent
    return False


def _top_level_key(line: str) -> str | None:
    if not line or line[0].isspace() or line.startswith("#"):
        return None
    if line[0] in {"'", '"'}:
        quote = line[0]
        end = line.find(quote, 1)
        if end < 0 or not line[end + 1 :].lstrip().startswith(":"):
            return None
        return line[1:end]
    key, separator, _ = line.partition(":")
    return key.strip() if separator and key.strip() else None


def _mapping_key(line: str, indent: int) -> str | None:
    prefix = " " * indent
    if not line.startswith(prefix):
        return None
    remainder = line[indent:]
    if not remainder or remainder[0].isspace():
        return None
    return _top_level_key(remainder)


def _yaml_string_token(raw: str) -> str | None:
    value = raw.split("#", 1)[0].strip()
    if (
        len(value) >= 2
        and value[0] in {"'", '"'}
        and value[-1] == value[0]
    ):
        token = value[1:-1]
        if not token:
            # `model: ''` is Hermes's own stock config shape for "no route,
            # inherit the parent". It is an absent value, not an unsupported
            # mapping — refusing it locked routing out of every vanilla
            # install (observed live: all category sets refused, lanes
            # silently dispatched as inherit).
            return ""
        return token if _VALUE_RE.fullmatch(token) else None
    lowered = value.casefold()
    if lowered in {"~", "null"}:
        # Same inherit family. These are PLAIN scalars, which YAML continues
        # onto a more-indented following line — that continuation case is
        # refused by the lookahead in _has_unsupported_delegation, not here.
        return ""
    if not lowered:
        # A BARE empty value is different: `model:` with nothing after the
        # colon may be a block-mapping header whose children live on the next,
        # more-indented lines. Treating it as an empty scalar would let the
        # writer drop the header and orphan those children into unparseable
        # YAML, so it stays refused.
        return None
    if lowered in {
        "true",
        "false",
        "yes",
        "no",
        "on",
        "off",
        "y",
        "n",
    }:
        return None
    if re.fullmatch(
        r"(?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?"
        r"|0x[0-9a-f]+|0o[0-7]+|0b[01]+|\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return None
    return value if _VALUE_RE.fullmatch(value) else None
