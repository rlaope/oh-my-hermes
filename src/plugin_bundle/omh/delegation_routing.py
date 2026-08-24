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

Writing a route is preparation, not execution: nothing dispatches from here,
and the route only takes effect when the agent's next `delegate_task` call
reads it.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROUTABLE_KEYS = ("model", "reasoning_effort", "provider")

_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_SECTION_RE = re.compile(r"^delegation:\s*(#.*)?$")
def _managed_key_re(key: str, indent: int) -> re.Pattern[str]:
    return re.compile(rf"^ {{{indent}}}{re.escape(key)}\s*:")


def read_delegation_route(hermes_home: str | Path | None = None) -> dict[str, str]:
    """Read the current routable delegation keys from config.yaml (text scan).

    Last occurrence wins, mirroring YAML's duplicate-key behaviour, so what
    this reports is what Hermes will actually resolve.
    """
    config_path = _config_path(hermes_home)
    text, _, error = _read_config_snapshot(config_path)
    if error:
        return {}
    return _read_delegation_route_text(text)


def _read_delegation_route_text(text: str) -> dict[str, str]:
    lines = text.splitlines()
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
                values[key] = value
    return values


def write_delegation_route(
    hermes_home: str | Path | None = None,
    *,
    model: str = "",
    reasoning_effort: str = "",
    provider: str = "",
    clear: bool = False,
    expected_previous: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Set (or clear) the routable delegation keys, touching nothing else.

    Keys with an empty desired value are removed, restoring parent
    inheritance for that key; `clear=True` removes all three.
    """
    desired = {} if clear else {
        "model": model.strip(),
        "reasoning_effort": reasoning_effort.strip(),
        "provider": provider.strip(),
    }
    for key, value in desired.items():
        if value and not _VALUE_RE.match(value):
            return {"status": "error", "error": f"invalid {key} value"}
    config_path = _config_path(hermes_home)
    text, signature, error = _read_config_snapshot(config_path)
    if error:
        return {"status": "error", "error": error}
    if _file_signature(config_path) != signature:
        return {"status": "error", "error": "config changed during route read"}
    previous = _read_delegation_route_text(text)
    if expected_previous is not None and previous != dict(expected_previous):
        return {
            "status": "error",
            "error": "active route changed before fallback write",
        }
    lines = text.splitlines()
    if _has_unsupported_delegation(lines):
        return {
            "status": "error",
            "error": "unsupported delegation mapping; refusing to rewrite it",
        }
    child_indents = _delegation_child_indents(lines)
    output: list[str] = []
    inserted = False
    in_section = False
    section_seen = False
    child_indent = 2
    for index, line in enumerate(lines):
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
    if wanted and not inserted:
        if output and output[-1].strip():
            output.append("")
        output.append("delegation:")
        for key in ROUTABLE_KEYS:
            value = wanted.get(key, "")
            if value:
                output.append(f"  {key}: '{value}'")
        section_seen = True
    if not section_seen and not wanted:
        # Nothing to remove and nothing to add: leave the file untouched.
        return {"status": "cleared" if clear else "routed", "previous": previous, "applied": {}}

    new_text = "\n".join(output)
    if text.endswith("\n") or not text:
        new_text += "\n"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".omh-delegation-route-", dir=str(config_path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(new_text)
            if _file_signature(config_path) != signature:
                os.unlink(temp_name)
                return {
                    "status": "error",
                    "error": "config changed during route update",
                }
            if config_path.exists():
                os.chmod(temp_name, config_path.stat().st_mode & 0o7777)
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
        "previous": previous,
        "applied": wanted,
    }


def _config_path(hermes_home: str | Path | None) -> Path:
    home = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    return home / "config.yaml"


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


def _file_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.lstat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


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
    return any(
        _top_level_key(line) == "delegation" and not _SECTION_RE.match(line)
        for line in lines
    )


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


def _yaml_string_token(raw: str) -> str | None:
    value = raw.split("#", 1)[0].strip()
    if (
        len(value) >= 2
        and value[0] in {"'", '"'}
        and value[-1] == value[0]
    ):
        token = value[1:-1]
        return token if _VALUE_RE.fullmatch(token) else None
    lowered = value.casefold()
    if lowered in {
        "",
        "~",
        "null",
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
        r"|0x[0-9a-f]+|0o[0-7]+|\d{4}-\d{2}-\d{2})",
        lowered,
    ):
        return None
    return value if _VALUE_RE.fullmatch(value) else None
