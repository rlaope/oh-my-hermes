"""Operator-declared executor ids a dag-ulw node may name as its owner.

Stdlib only: Hermes loads this bundle without the core ``omh`` package. The one
file read is ``<omh_home>/routing/executors.toml``, the operator's own file under
the OMH home (never the repository or the working directory). This module admits
ids only and prints nothing about an entry. Core (``src/coding/user_executors.py``)
stays the execution authority: it validates the full argv contract at launch and
refuses anything this admission lets through that core would not run.
"""

from __future__ import annotations

import re
import stat
import tomllib
from pathlib import Path
from typing import Final

EXECUTORS_FILE_PARTS: Final[tuple[str, str]] = ("routing", "executors.toml")
USER_EXECUTORS_MAX_BYTES: Final[int] = 256 * 1024  # the same bound core reads with
_ROOT_KEYS: Final[frozenset[str]] = frozenset({"schema_version", "executors"})
_ID: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9-]{1,31}")
_PROMPT_PLACEHOLDERS: Final[frozenset[str]] = frozenset({"{prompt}", "{prompt_file}"})
# The preset ids core ships (`src/coding/executor_presets.py`); a preset name is only admitted as its own preset.
PRESET_IDS: Final[frozenset[str]] = frozenset(
    {"devin", "gemini", "qwen", "kimi", "cursor-agent", "amp", "droid", "aider", "goose"}
)
# Built-in and reserved names a custom entry may never take (core's `RESERVED_OWNER_IDS`, grammar-bearing part).
# A preset name is not in this set: it is admitted only as its own preset (see `_admitted`).
RESERVED_IDS: Final[frozenset[str]] = frozenset(
    {
        "codex", "claude-code", "omx-runtime", "pi-family-runtime", "omc-runtime", "generic", "hermes",
        "choose", "unassigned", "maestro", "omo-runtime", "senpi", "omp",
    }
)
# Programs core refuses (shells, interpreters, wrappers): admission must not let these through either.
_REFUSED_PROGRAMS: Final[frozenset[str]] = frozenset(
    {"sh", "bash", "zsh", "dash", "fish", "powershell", "pwsh", "cmd", "env", "command", "xargs", "busybox",
     "python", "python3", "node", "perl", "ruby"}
)
_REFUSED_SUFFIXES: Final[tuple[str, ...]] = (".bat", ".cmd", ".ps1", ".sh", ".py", ".js", ".pl", ".rb")


def configured_owner_ids(omh_home: str | Path) -> frozenset[str]:
    """The executor ids this home's operator file admits; empty for any file core would not read in full."""
    home = Path(omh_home)
    if not home.is_absolute() or (home / EXECUTORS_FILE_PARTS[0]).is_symlink():
        return frozenset()
    path = home.joinpath(*EXECUTORS_FILE_PARTS)
    try:
        if path.is_symlink():
            return frozenset()
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            return frozenset()
        with path.open("rb") as handle:
            raw = handle.read(USER_EXECUTORS_MAX_BYTES + 1)
    except OSError:
        return frozenset()
    if len(raw) > USER_EXECUTORS_MAX_BYTES:
        return frozenset()
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return frozenset()
    schema_version = document.get("schema_version")
    if set(document) - _ROOT_KEYS or type(schema_version) is not int or schema_version != 1:
        return frozenset()
    executors = document.get("executors", {})
    if not isinstance(executors, dict):
        return frozenset()
    return frozenset(name for name, entry in executors.items() if _admitted(name, entry))


def _admitted(executor_id: object, entry: object) -> bool:
    if not isinstance(executor_id, str) or _ID.fullmatch(executor_id) is None or executor_id in RESERVED_IDS:
        return False
    if not isinstance(entry, dict):
        return False
    if executor_id in PRESET_IDS:
        return entry.get("preset") == executor_id
    if "preset" in entry:
        return False
    argv = entry.get("argv")
    if not isinstance(argv, list) or not 1 <= len(argv) <= 64:
        return False
    if not all(isinstance(token, str) and token and "\x00" not in token for token in argv):
        return False
    program = argv[0]
    if program in _PROMPT_PLACEHOLDERS or "/" in program or "\\" in program:
        return False
    if program.lower() in _REFUSED_PROGRAMS or program.lower().endswith(_REFUSED_SUFFIXES):
        return False
    return sum(token in _PROMPT_PLACEHOLDERS for token in argv) == 1
