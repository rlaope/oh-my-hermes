"""A short interpreter path for fanout verification-command fixtures.

The dispatcher caps a verification command at 240 characters
(`MAX_UNIT_VERIFICATION_COMMAND_CHARS`), a task-linked runner at 200 and a
reproduction command at 240. A fixture that spells the interpreter as
`sys.executable` carries the checkout path (`<checkout>/.venv/bin/python3`)
into that field, so the same test passed in CI and failed in a checkout whose
path was long enough (#1474 first hit it). The cap is the product's contract;
the fixture must not depend on where the checkout lives.

Order of preference, first one that is short enough wins:

1. `sys.executable` itself.
2. The base interpreter that created the venv (`sys._base_executable`). It
   lives outside the checkout and runs a stdlib-only command just as well.
3. POSIX only: a symlink to `sys.executable` under a stable per-user directory
   in `/tmp`, one link per distinct interpreter, so a killed run leaks nothing
   that grows.
4. `sys.executable`, unchanged. Windows has no unprivileged symlink; there the
   base interpreter is the short path, and this last step is the documented
   behaviour when it is not.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import sys

# Widest fixture body is about 115 chars; 100 + 115 stays under every cap.
SHORT_INTERPRETER_CHARS = 100

# Patched by the pin test so it never touches the shared per-user directory.
_LINK_ROOT = "/tmp"


def _base_interpreter() -> str | None:
    base = getattr(sys, "_base_executable", "") or ""
    if base and len(base) <= SHORT_INTERPRETER_CHARS and Path(base).exists():
        return base
    return None


def _short_link() -> str | None:
    """A stable symlink to the interpreter under a short root, or None when it cannot be made."""
    if os.name != "posix" or not os.path.isdir(_LINK_ROOT):
        return None
    uid = os.getuid()
    directory = Path(_LINK_ROOT) / f"omh-fixture-python-{uid}"
    digest = hashlib.sha1(sys.executable.encode("utf-8")).hexdigest()[:10]
    link = directory / f"py-{digest}"
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_uid != uid:
            return None
        if not os.path.lexists(link):
            link.symlink_to(sys.executable)
    except OSError:
        return None
    return str(link) if len(str(link)) <= SHORT_INTERPRETER_CHARS else None


def verification_python_path() -> str:
    """The interpreter path a capped command spells, unquoted (argv[0] as a runner sees it)."""
    if len(sys.executable) <= SHORT_INTERPRETER_CHARS:
        return sys.executable
    return _base_interpreter() or _short_link() or sys.executable


def verification_python() -> str:
    """The quoted interpreter for a capped command, short whatever the checkout path."""
    return shlex.quote(verification_python_path())
