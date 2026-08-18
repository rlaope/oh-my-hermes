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
from typing import Any

ROUTABLE_KEYS = ("model", "reasoning_effort", "provider")

_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_SECTION_RE = re.compile(r"^delegation:\s*(#.*)?$")
_TOP_LEVEL_RE = re.compile(r"^[A-Za-z0-9_-]+\s*:")


def _managed_key_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^\s+{re.escape(key)}\s*:")


def read_delegation_route(hermes_home: str | Path | None = None) -> dict[str, str]:
    """Read the current routable delegation keys from config.yaml (text scan).

    Last occurrence wins, mirroring YAML's duplicate-key behaviour, so what
    this reports is what Hermes will actually resolve.
    """
    config_path = _config_path(hermes_home)
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    values: dict[str, str] = {}
    in_section = False
    for line in text.splitlines():
        if _SECTION_RE.match(line):
            in_section = True
            continue
        if in_section and _TOP_LEVEL_RE.match(line):
            in_section = False
        if not in_section:
            continue
        for key in ROUTABLE_KEYS:
            if _managed_key_re(key).match(line):
                _, _, raw = line.partition(":")
                values[key] = raw.split("#", 1)[0].strip().strip("'\"")
    return values


def write_delegation_route(
    hermes_home: str | Path | None = None,
    *,
    model: str = "",
    reasoning_effort: str = "",
    provider: str = "",
    clear: bool = False,
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
    if config_path.is_symlink():
        return {"status": "error", "error": "config.yaml is a symlink; refusing to rewrite it"}
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as exc:
        return {"status": "error", "error": f"config unreadable: {type(exc).__name__}"}

    previous = read_delegation_route(hermes_home)
    lines = text.splitlines()
    output: list[str] = []
    inserted = False
    in_section = False
    section_seen = False
    for line in lines:
        if _SECTION_RE.match(line):
            in_section = True
            section_seen = True
            output.append(line)
            for key in ROUTABLE_KEYS:
                value = desired.get(key, "")
                if value:
                    output.append(f"  {key}: {value}")
            inserted = True
            continue
        if in_section and _TOP_LEVEL_RE.match(line):
            in_section = False
        if in_section and any(_managed_key_re(key).match(line) for key in ROUTABLE_KEYS):
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
                output.append(f"  {key}: {value}")
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
