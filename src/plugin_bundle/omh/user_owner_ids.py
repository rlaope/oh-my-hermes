"""Operator-declared executor ids a dag-ulw node may name as its owner.

Stdlib only: Hermes loads this bundle without the core ``omh`` package. The one
file read is ``<omh_home>/routing/executors.toml``, the operator's own file under
the OMH home (never the repository or the working directory). This module admits
ids only and prints nothing about an entry. Core (``src/coding/user_executors.py``)
stays the execution authority: it validates the full argv contract at launch and
refuses anything this admission lets through that core would not run.
"""

from __future__ import annotations

import os
import re
import stat
import tomllib
from pathlib import Path
from typing import Final

# Standalone mirror of the core launch gate; registry admission remains portable.
USER_EXECUTOR_LAUNCH_SUPPORTED: Final = os.name == "posix"
USER_EXECUTOR_PLATFORM_UNSUPPORTED: Final = "user_executor_platform_unsupported"

EXECUTORS_FILE_PARTS: Final[tuple[str, str]] = ("routing", "executors.toml")
USER_EXECUTORS_MAX_BYTES: Final[int] = 256 * 1024  # the same bound core reads with
_ROOT_KEYS: Final[frozenset[str]] = frozenset({"schema_version", "executors"})
_ID: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9-]{1,31}")
_PROMPT_PLACEHOLDERS: Final[frozenset[str]] = frozenset({"{prompt}", "{prompt_file}"})
# The preset ids core ships (`src/coding/executor_presets.py`); a preset name is only admitted as its own preset.
PRESET_IDS: Final[frozenset[str]] = frozenset(
    {"devin", "gemini", "qwen", "kimi", "cursor-agent", "amp", "droid", "aider", "goose"}
)
# Literal copy of core's `RESERVED_OWNER_IDS` (`src/coding/user_executors.py`); the bundle cannot import core.
# `tests/test_plugin_dag_owner_executors.py` asserts the two are equal. A preset id is in this set too, so
# `_admitted` checks presets first and admits one only as its own preset.
RESERVED_IDS: Final[frozenset[str]] = frozenset(
    {
        "aider", "amp", "choose", "claude", "claude-code", "claude-code-cli", "claude_code", "codex",
        "cursor-agent", "devin", "droid", "gemini", "generic", "goose", "hermes", "hermes-local", "hermes_local",
        "kimi", "maestro", "omc-runtime", "omo-runtime", "omp", "omx-runtime", "opencode", "pi",
        "pi-family-runtime", "pi_family_runtime", "qwen", "senpi", "unassigned",
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


def _local_fragment(value: object, *, has_program: bool = False) -> bool:
    """Mirror core's declares_cloud: check arguments, never the program name."""
    if not isinstance(value, list) or not all(isinstance(arg, str) for arg in value):
        return False
    arguments = value[1:] if has_program else value
    return arguments[:1] != ["cloud"] and not any(arg == "--cloud" or arg.startswith("--cloud=") for arg in arguments)


def _admitted(executor_id: object, entry: object) -> bool:
    if not isinstance(executor_id, str) or _ID.fullmatch(executor_id) is None:
        return False
    if not isinstance(entry, dict):
        return False
    if executor_id in PRESET_IDS:
        # Core permits no argv fragment overrides on a preset.
        return entry.get("preset") == executor_id and not (entry.keys() - {"preset", "remote_pr"})
    if executor_id in RESERVED_IDS or "preset" in entry:
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
    session = entry.get("session", {})
    if not isinstance(session, dict):
        return False
    return (sum(token in _PROMPT_PLACEHOLDERS for token in argv) == 1
            and _local_fragment(argv, has_program=True)
            and _local_fragment(entry.get("version", []), has_program=True)
            and all(_local_fragment(entry.get(field, [])) for field in ("model", "effort"))
            and all(_local_fragment(session.get(field, [])) for field in ("export", "resume")))
