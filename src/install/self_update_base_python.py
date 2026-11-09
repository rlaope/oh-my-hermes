"""Which base interpreter a staged generation's venv is created from.

`python -m venv` run from inside a venv links the new venv to
`sys._base_executable`, the running venv's base resolved through every
symlink. On a Homebrew framework build that is the version-pinned keg
(`/opt/homebrew/Cellar/python@3.15/3.15.0/...`), so a generation staged from
the running `omh` bound itself to one patch release and broke with "bad
interpreter" once `brew upgrade` and cleanup removed that keg (#2683). The
installer's own venv survived: it was created from the stable spelling
(`/opt/homebrew/opt/python@3.15/bin/python3.15`), and a base interpreter run
directly records the path it was started by.

This module reads the evidence a venv already holds, its `pyvenv.cfg`, and
names the interpreters worth trying, most trusted first. It knows no vendor
paths, runs nothing, and decides nothing about versions: the caller checks
each candidate runs the same major.minor and falls back to the interpreter it
was given.
"""

from __future__ import annotations

from pathlib import Path

PYVENV_CFG = "pyvenv.cfg"
VENV_COMMAND_MARKER = " -m venv "
# A generation's venv was created by the bootstrap venv's interpreter, which
# was created by the base the installer ran: two hops covers every layout this
# repository has produced, and the bound keeps a cycle of hand-edited files finite.
MAX_CREATOR_HOPS = 4


def venv_root(interpreter: Path) -> Path | None:
    """The venv an interpreter path sits in (`<venv>/bin/python`, `<venv>\\Scripts\\python.exe`), or None.

    Read from the path as spelled, never resolved: a venv's `python` is a
    symlink to its base, and resolving it is the very step that lands on a
    version-pinned path.
    """
    root = interpreter.parent.parent
    return root if (root / PYVENV_CFG).is_file() else None


def read_pyvenv_cfg(venv: Path) -> dict[str, str]:
    """`key = value` lines of a venv's `pyvenv.cfg`, as CPython's `site` reads them; {} when unreadable."""
    try:
        text = (venv / PYVENV_CFG).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip().lower()] = value.strip()
    return values


def creator_interpreter(config: dict[str, str]) -> Path | None:
    """The interpreter that created a venv, from `command = <interpreter> -m venv <dir>`; None when absent."""
    command = config.get("command", "")
    interpreter, separator, _target = command.partition(VENV_COMMAND_MARKER)
    interpreter = interpreter.strip()
    return Path(interpreter) if separator and interpreter else None


def home_interpreters(home: str, *, version: tuple[int, int], is_windows: bool) -> list[Path]:
    """The executables a venv's `home` directory holds for the running major.minor, most specific first."""
    if not home:
        return []
    directory = Path(home)
    if is_windows:
        return [directory / "python.exe"]
    major, minor = version
    return [directory / f"python{major}.{minor}", directory / f"python{major}", directory / "python"]


def base_python_candidates(seed: str, *, version: tuple[int, int], is_windows: bool) -> list[str]:
    """Interpreters to create a generation venv from instead of `seed`, most trusted first.

    `seed` is the interpreter the update would use today (the plan's, else the
    running one). When it is a base interpreter, not inside a venv, there is
    nothing to correct and the list is empty. When it is a venv's interpreter,
    each `pyvenv.cfg` on the chain of creators contributes, oldest creator first:

    - the interpreter its `command` names, when that is a base interpreter
      (exactly what the installer ran); when it is another venv's
      interpreter, that venv's own file is read first, so a generation staged
      by an older `omh` still leads back to the installer's base;
    - its `home` directory's `pythonX.Y` (`python.exe` on Windows).

    Every candidate exists on disk; whether it runs `version` is the caller's check.
    """
    seen: set[Path] = set()
    ordered: list[str] = []

    def visit(interpreter: Path, hops: int) -> None:
        venv = venv_root(interpreter)
        if venv is None or hops > MAX_CREATOR_HOPS:
            return
        key = Path(venv).absolute()
        if key in seen:
            return
        seen.add(key)
        config = read_pyvenv_cfg(venv)
        creator = creator_interpreter(config)
        found: list[Path] = []
        if creator is not None:
            if venv_root(creator) is not None:
                visit(creator, hops + 1)
            else:
                found.append(creator)
        found.extend(home_interpreters(config.get("home", ""), version=version, is_windows=is_windows))
        for path in found:
            spelled = str(path)
            if spelled != seed and spelled not in ordered and path.is_file():
                ordered.append(spelled)

    visit(Path(seed), 0)
    return ordered
