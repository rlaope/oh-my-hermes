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

import os
from pathlib import Path
import shlex

PYVENV_CFG = "pyvenv.cfg"
VENV_COMMAND_MARKER = " -m venv "
# A generation's venv was created by the bootstrap venv's interpreter, which
# was created by the base the installer ran: two hops covers every layout this
# repository has produced, and the bound keeps a cycle of hand-edited files finite.
MAX_CREATOR_HOPS = 4


def _is_file(path: Path) -> bool:
    """`Path.is_file()` that answers False for a path the user cannot reach.

    On Python 3.11-3.13 `is_file()` swallows only ENOENT, ENOTDIR, EBADF and
    ELOOP, so a `home` under a folder this account cannot enter raised
    `PermissionError` out of `omh update` instead of falling back.
    """
    try:
        return path.is_file()
    except OSError:
        return False


def venv_root(interpreter: Path) -> Path | None:
    """The venv an interpreter path sits in (`<venv>/bin/python`, `<venv>\\Scripts\\python.exe`), or None.

    Read from the path as spelled, never resolved: a venv's `python` is a
    symlink to its base, and resolving it is the very step that lands on a
    version-pinned path.
    """
    root = interpreter.parent.parent
    return root if _is_file(root / PYVENV_CFG) else None


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


def _anchored(venv: Path, spelled: str) -> Path:
    """A path a `pyvenv.cfg` records, read against the venv's folder when relative, never the cwd."""
    path = Path(spelled)
    return path if path.is_absolute() else venv / path


def creator_interpreter(config: dict[str, str], venv: Path) -> Path | None:
    """The interpreter that created a venv, from `command = <interpreter> -m venv <dir>`; None when absent."""
    command = config.get("command", "")
    interpreter, separator, _target = command.partition(VENV_COMMAND_MARKER)
    interpreter = interpreter.strip()
    return _anchored(venv, interpreter) if separator and interpreter else None


def home_interpreters(config: dict[str, str], venv: Path, *, version: tuple[int, int], abiflags: str, is_windows: bool) -> list[Path]:
    """The executables a venv's `home` folder holds for the running build, most specific first.

    A free-threaded or debug build (`abiflags` `t`, `d`) shares its folder with
    the default build (`python3.14t` beside `python3.14`), so its own name
    leads; the caller's probe still refuses a name that runs another build.
    """
    home = config.get("home", "")
    if not home:
        return []
    directory = _anchored(venv, home)
    major, minor = version
    if is_windows:
        names = [f"python{major}.{minor}{abiflags}.exe"] if abiflags else []
        return [directory / name for name in (*names, "python.exe")]
    names = [f"python{major}.{minor}{abiflags}"] if abiflags else []
    return [directory / name for name in (*names, f"python{major}.{minor}", f"python{major}", "python")]


def base_python_candidates(seed: str, *, version: tuple[int, int], is_windows: bool, abiflags: str = "", anchors: tuple[str, ...] = ()) -> list[str]:
    """Interpreters to create a generation venv from instead of `seed`, most trusted first.

    `seed` is the interpreter the update would use today (the plan's, else the
    running one). `anchors` are other venv interpreters whose chain also leads
    to the installer's base: the bootstrap venv, which cleanup never deletes.
    Each `pyvenv.cfg` on a chain of creators contributes:

    - the interpreter its `command` names, when that is a base interpreter
      (exactly what the installer ran); when it is another venv's
      interpreter, that venv's own file is read first;
    - its `home` folder's `pythonX.Y` (`python.exe` on Windows).

    Every creator comes before every `home`, and the anchors' homes before the
    seed chain's. Before this fix each generation was created by the one
    before it, and cleanup keeps only the active, the previous and the
    bootstrap generations; after three updates the seed's chain stops at a
    deleted venv with only version-pinned `home` values left, while the
    bootstrap still names the installer's base.

    Every candidate exists on disk; whether it runs the same build is the caller's check.
    """
    seen: set[Path] = set()

    def walk(interpreter: Path, hops: int, creators: list[Path], homes: list[Path]) -> None:
        venv = venv_root(interpreter)
        if venv is None or hops > MAX_CREATOR_HOPS:
            return
        key = venv.absolute()
        if key in seen:
            return
        seen.add(key)
        config = read_pyvenv_cfg(venv)
        creator = creator_interpreter(config, venv)
        if creator is not None:
            if venv_root(creator) is not None:
                walk(creator, hops + 1, creators, homes)
            else:
                creators.append(creator)
        homes.extend(home_interpreters(config, venv, version=version, abiflags=abiflags, is_windows=is_windows))

    seed_creators: list[Path] = []
    seed_homes: list[Path] = []
    walk(Path(seed), 0, seed_creators, seed_homes)
    anchor_creators: list[Path] = []
    anchor_homes: list[Path] = []
    for anchor in anchors:
        walk(Path(anchor), 0, anchor_creators, anchor_homes)
    ordered: list[str] = []
    for path in (*seed_creators, *anchor_creators, *anchor_homes, *seed_homes):
        spelled = str(path)
        if spelled != seed and spelled not in ordered and _is_file(path):
            ordered.append(spelled)
    return ordered


def pinned_base_finding(venv: Path, *, version: tuple[int, int], is_windows: bool, abiflags: str = "", anchors: tuple[str, ...] = ()) -> dict[str, str] | None:
    """Why a venv's base interpreter will not survive, with the repair; None when it will.

    `gone`: no interpreter is left in its `home` (a `brew cleanup` removed the
    keg). `pinned`: its `home` folder is already fully resolved (no link left
    in it to move on an upgrade) and its interpreter is reachable under
    another spelling (`samefile`), so it breaks on the next patch upgrade. A
    `home` that is itself a link, such as uv's minor-version folder, moves
    with the upgrade and is not pinned. Reads files only; nothing is run, so
    the repair names a `pythonX.Y` candidate first and says the minor must match.
    """
    config = read_pyvenv_cfg(venv)
    homes = home_interpreters(config, venv, version=version, abiflags=abiflags, is_windows=is_windows)
    if not homes:
        return None
    python = venv / ("Scripts" if is_windows else "bin") / ("python.exe" if is_windows else "python")
    bound = next((home for home in homes if _is_file(home)), None)
    candidates = [Path(path) for path in base_python_candidates(str(python), version=version, abiflags=abiflags, is_windows=is_windows, anchors=anchors)]
    spelled_homes = {str(home) for home in homes}
    others = [path for path in candidates if str(path) not in spelled_homes]
    if bound is None:
        state = "gone"
        versioned = f"python{version[0]}.{version[1]}"
        stable = next((path for path in others if path.name.startswith(versioned)), next(iter(others), None))
    else:
        state = "pinned"
        if not _fully_resolved(homes[0].parent):
            return None
        stable = next((path for path in others if _same_file(path, bound)), None)
        if stable is None:
            return None
    finding = {"state": state, "venv": str(venv), "home": str(homes[0]), "stable": str(stable or "")}
    if stable is not None:
        if is_windows:
            finding["repair"] = f'"{stable}" -m venv --upgrade "{venv}"'
        else:
            link = venv / "bin" / f"python{version[0]}.{version[1]}{abiflags}"
            # `venv --upgrade` keeps an existing link, dangling or not, so the link goes first.
            finding["repair"] = f"rm -f {shlex.quote(str(link))} && {shlex.quote(str(stable))} -m venv --upgrade {shlex.quote(str(venv))}"
    return finding


def _fully_resolved(folder: Path) -> bool:
    """Whether a folder path contains no link: resolving it changes nothing."""
    try:
        resolved = os.path.realpath(folder)
    except OSError:
        return False
    return os.path.normcase(resolved) == os.path.normcase(os.path.normpath(folder))


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError:
        return False
