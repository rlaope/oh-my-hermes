"""A short interpreter path for fanout verification-command fixtures.

The dispatcher caps a verification command at 240 characters
(`MAX_UNIT_VERIFICATION_COMMAND_CHARS`). A fixture that spells the interpreter
as `sys.executable` carries the checkout path (`<checkout>/.venv/bin/python3`)
into that command, so the same test passed in CI and failed in a checkout whose
path was long enough. The cap is the product's contract; the fixture must not
depend on where the checkout lives.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

# Longest interpreter spelling that keeps the widest fixture command (about 115
# characters of body) well under the 240-character cap.
SHORT_INTERPRETER_CHARS = 60

_link_dir: str | None = None


def _remove_link_dir() -> None:
    if _link_dir is not None:
        shutil.rmtree(_link_dir, ignore_errors=True)


def _short_link() -> str | None:
    """A symlink to the interpreter under a short root, or None when it cannot be made."""
    global _link_dir
    if _link_dir is None:
        root = "/tmp" if os.path.isdir("/tmp") else None
        _link_dir = tempfile.mkdtemp(prefix="omhpy", dir=root)
        atexit.register(_remove_link_dir)
    link = Path(_link_dir) / "py"
    if not link.exists():
        try:
            link.symlink_to(sys.executable)
        except OSError:
            return None
    return str(link)


def verification_python() -> str:
    """The quoted interpreter for a verification command, short whatever the checkout path."""
    if len(sys.executable) <= SHORT_INTERPRETER_CHARS:
        return shlex.quote(sys.executable)
    link = _short_link()
    if link is None or len(link) > SHORT_INTERPRETER_CHARS:
        return shlex.quote(sys.executable)
    return shlex.quote(link)
