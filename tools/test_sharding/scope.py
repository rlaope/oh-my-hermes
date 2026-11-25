"""Narrow a pull request's unit-test plan when it touches only the omher app.

A pull request whose every changed path is under ``apps/omher/`` (or is
``CHANGELOG.md``) cannot change the Python package, so the unit suite it needs
is the slice that reads those paths. That slice is chosen from the test
sources themselves, never from a hand-kept list: a module is in when its text
names omher, the changelog, ``apps/``, or walks the whole repository tree.
Every other change, and every main push, runs the full inventory.

The narrowing is a planning input only. The aggregate still re-proves that
every planned test ran exactly once, and main runs the whole suite on the
merged tree, so a slice that misses a test is caught there.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Final

OMHER_SCOPE: Final = "omher"
FULL_SCOPE: Final = "full"

_OMHER_ONLY_PREFIXES: Final = ("apps/omher/",)
_OMHER_ONLY_FILES: Final = frozenset({"CHANGELOG.md"})

# A test module that reads the omher tree or the changelog names one of them;
# one that audits every tracked file walks the repository root.
_OMHER_RELEVANT: Final = re.compile(
    r"omher|CHANGELOG|apps/|\"apps\"|ls-files"
    r"|(?:REPO_ROOT|PROJECT_ROOT|ROOT)\.(?:rglob|iterdir)\("
    r"|os\.walk\((?:REPO_ROOT|PROJECT_ROOT|ROOT)"
)


def read_changed_paths(path: Path) -> tuple[str, ...]:
    """Read one repository-relative path per line, ignoring blank lines."""

    text = path.read_text(encoding="utf-8")
    return tuple(line.strip().replace("\\", "/") for line in text.splitlines() if line.strip())


def change_scope(paths: tuple[str, ...]) -> str:
    """Return the omher scope only for a non-empty, omher-only change."""

    if not paths:
        return FULL_SCOPE
    for path in paths:
        if path in _OMHER_ONLY_FILES or path.startswith(_OMHER_ONLY_PREFIXES):
            continue
        return FULL_SCOPE
    return OMHER_SCOPE


def scoped_modules(start_dir: Path) -> frozenset[str]:
    """Top-level test modules under ``start_dir`` whose source is omher-relevant."""

    selected: set[str] = set()
    for path in sorted(start_dir.glob("test*.py")):
        if _OMHER_RELEVANT.search(path.read_text(encoding="utf-8")):
            selected.add(path.stem)
    return frozenset(selected)


def narrow_inventory(inventory: tuple[str, ...], modules: frozenset[str]) -> tuple[str, ...]:
    """Keep the test IDs whose top-level module is in ``modules``."""

    return tuple(test_id for test_id in inventory if test_id.split(".", 1)[0] in modules)
