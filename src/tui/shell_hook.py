"""The opt-in shell-rc block that reopens a dropped OMH session when a new terminal opens (path B).

`omh auto-resume shell install` appends one marked block to the end of the
person's shell rc (zsh `${ZDOTDIR:-$HOME}/.zshrc`, bash `~/.bashrc`, PowerShell's
`$PROFILE` for the current user and host); `omh auto-resume shell remove` takes
exactly that block out again, and a file the block was appended to comes back
byte for byte. Nothing else writes a shell rc, and nothing here runs a shell.

What the block does, in every shell: only in an interactive shell, and only
when none of `OMH_AUTO_RESUME_DONE`, `HERMES_SESSION_ID`, `OMH_TUI_SESSION_FILE`
or `CI` is set, it exports `OMH_AUTO_RESUME_DONE=1` (so a nested shell does
nothing) and looks, with the shell's own builtins, for a session to reopen:
the pending marker `<omh_home>/tui/resume-pending` (some session was dropped),
or a pid in `<omh_home>/tui/live-pids` (the TUIs recorded as running, after
the boot they ran on) that no longer runs, which is how a TUI killed outright
(SIGKILL, power loss) shows before anything has swept it
(`tui/live_sessions.py`). Where `/proc/sys/kernel/random/boot_id` can be read
(Linux), zsh and bash also wake when it differs from the recorded boot, so a
pid a new boot reused does not hide a TUI the reboot ended. macOS and
PowerShell have no boot source a builtin can read and keep the pid check
alone: after a reboot that hands a recorded pid to a live process, the hook
stays quiet and a later terminal, or a bare `omh` (which sweeps by boot),
reopens the session. `kill -0` cannot tell a pid that is gone from one another
user now holds; the second also wakes, and `shell-start` then finds nothing
and exits at once (the file lists only this user's TUIs, so that needs a
recycled pid). No process starts
unless one of the two holds and `omh` is on PATH. Then, at the first prompt,
it runs `omh --omh-home <home> auto-resume shell-start`, which reopens the
session this terminal dropped, or exits at once:

* zsh: from the first `zle-line-init` (`add-zle-hook-widget`), which puts the
  command in the line and accepts it, then removes its hook; a one-shot
  `zshaddhistory` hook keeps that line out of the history, and nothing changes
  the person's history options. A `precmd` hook would run under
  powerlevel10k's instant prompt, where stdin is /dev/null.
* bash: from the first `PROMPT_COMMAND` run, with stdin and stdout on the
  terminal; it then takes itself out of `PROMPT_COMMAND` (a string or, from
  bash 5.1, an array) and leaves whatever else was there.
* PowerShell: at the end of the profile, in the console host.

The zsh and bash blocks are written with LF line ends whatever the rc uses
(a CR inside a shell keyword is a syntax error); the person's own bytes, and
the line end added before the block, keep the rc's own convention.

Stdlib only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys

SHELLS = ("zsh", "bash", "powershell")
BEGIN = "# >>> omh auto-resume >>>"
END = "# <<< omh auto-resume <<<"
ABOUT = "# Reopens the OMH session this terminal dropped. `omh auto-resume shell remove` takes this block out."
# Kept inside the block so `remove` can undo exactly what `install` added around it.
ADDED_LINE_END = "# (omh added the line end just before this block)"
CREATED_FILE = "# (omh created this file for this block)"
NEW_RC_MODE = 0o644
MAX_RC_BYTES = 4 * 1024 * 1024
PENDING_MARKER_PARTS = ("tui", "resume-pending")
LIVE_PIDS_PARTS = ("tui", "live-pids")
# Linux's boot id, read by the POSIX blocks with `read` when it exists; the store writes the same id verbatim as the
# first word of `live-pids`. A module constant only so tests can point a rendered block at a fake boot file.
LINUX_BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"


class ShellHookError(ValueError):
    """A refusal: the rc cannot be written safely, or its block is not one `remove` can take out exactly."""


@dataclass(frozen=True)
class HookResult:
    shell: str
    rc: Path
    action: str  # installed | updated | unchanged | removed | absent
    changed: bool
    dry_run: bool
    block: str = ""


def home_dir(environ: Mapping[str, str]) -> Path:
    """The person's home: `HOME`, else `USERPROFILE`, else what Python knows."""
    for name in ("HOME", "USERPROFILE"):
        value = environ.get(name)
        if value:
            return Path(value)
    return Path.home()


def default_shell(environ: Mapping[str, str], platform: str | None = None) -> str | None:
    """The shell `$SHELL` names (zsh or bash); PowerShell on Windows; None for anything else."""
    name = Path(str(environ.get("SHELL", "") or "")).name
    if name in ("zsh", "bash"):
        return name
    if (platform or sys.platform) == "win32":
        return "powershell"
    return None


def rc_path(
    shell: str, environ: Mapping[str, str], *, platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> Path:
    """The rc file a new interactive `shell` reads for this person."""
    home = home_dir(environ)
    if shell == "zsh":
        return Path(environ.get("ZDOTDIR") or home) / ".zshrc"
    if shell == "bash":
        return home / ".bashrc"
    if shell != "powershell":
        raise ShellHookError(f"unsupported shell: {shell!r}; expected one of {', '.join(SHELLS)}")
    name = "Microsoft.PowerShell_profile.ps1"
    if (platform or sys.platform) != "win32":
        return Path(environ.get("XDG_CONFIG_HOME") or home / ".config") / "powershell" / name
    core = home / "Documents" / "PowerShell" / name  # PowerShell 7
    desktop = home / "Documents" / "WindowsPowerShell" / name  # Windows PowerShell 5.1
    for candidate in (core, desktop):
        if candidate.is_file():
            return candidate
    return core if which("pwsh") else desktop


def marker_path(omh_home: str | Path) -> Path:
    return Path(omh_home).joinpath(*PENDING_MARKER_PARTS)


def live_pids_path(omh_home: str | Path) -> Path:
    return Path(omh_home).joinpath(*LIVE_PIDS_PARTS)


def _printable(path: Path, what: str) -> str:
    text = str(path)
    if not text or not text.isprintable():
        raise ShellHookError(f"the {what} path {text!r} cannot be written into a shell rc")
    return text


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _posix_wake(marker: str, live_pids: str, boot_file: str, split: str) -> list[str]:
    """Lines that set `_omh_wake` when the marker exists, when `boot_file` reads as a boot other than the one
    `live_pids` recorded, or when a pid in `live_pids` no longer runs, by builtins only (`read`, `kill -0`): no
    process starts here. `live_pids` is `<boot> <pid> ...`; a recorded boot of `-` (unknown) or an unreadable
    `boot_file` (not Linux) leaves the pid check alone. `split` is how the shell word-splits `$_omh_pids`. A word
    that is not a plain decimal of at most nine digits is skipped. `kill -0` failing for a pid another user now
    holds also wakes: the TUI that wrote it is gone either way, and `shell-start` finds nothing to reopen."""
    return [
        "  _omh_wake= _omh_pids= _omh_rec= _omh_boot=",
        f"  if [[ -e {_sh_quote(marker)} ]]; then",
        "    _omh_wake=1",
        f"  elif [[ -f {_sh_quote(live_pids)} ]]; then",
        f"    read -r _omh_pids < {_sh_quote(live_pids)} || :",
        "    _omh_rec=${_omh_pids%% *}",
        "    if [[ $_omh_pids == *' '* ]]; then _omh_pids=${_omh_pids#* }; else _omh_pids=; fi",
        f"    if [[ -n $_omh_rec && $_omh_rec != - && -r {_sh_quote(boot_file)} ]]; then",
        f"      read -r _omh_boot < {_sh_quote(boot_file)} || :",
        '      [[ -n $_omh_boot && $_omh_boot != "$_omh_rec" ]] && _omh_wake=1',
        "    fi",
        "    if [[ -z $_omh_wake ]]; then",
        f"      for _omh_p in {split}; do",
        '        [[ $_omh_p == [0-9]* && $_omh_p != *[!0-9]* && ${#_omh_p} -le 9 ]] || continue',
        "        kill -0 \"$_omh_p\" 2>/dev/null || { _omh_wake=1; break; }",
        "      done",
        "    fi",
        "  fi",
    ]


def render_block(shell: str, omh_home: str | Path) -> list[str]:
    """The block's lines, markers included, for `shell` and this OMH home (absolute)."""
    boot_file = _printable(Path(LINUX_BOOT_ID_FILE), "boot id")
    home = Path(os.path.abspath(omh_home))
    home_text = _printable(home, "OMH home")
    marker = _printable(marker_path(home), "pending marker")
    live_pids = _printable(live_pids_path(home), "live pids")
    guard_names = ("OMH_AUTO_RESUME_DONE", "HERMES_SESSION_ID", "OMH_TUI_SESSION_FILE", "CI")
    if shell == "zsh":
        line = " " + f"command omh --omh-home {_sh_quote(home_text)} auto-resume shell-start"
        unset = "".join(f"${{{name}-}}" for name in guard_names)
        body = [
            f'if [[ -o interactive && -z "{unset}" ]]; then',
            "  export OMH_AUTO_RESUME_DONE=1",
            *_posix_wake(marker, live_pids, boot_file, "${=_omh_pids}"),
            "  if [[ -n $_omh_wake ]] && (( $+commands[omh] )); then",
            "    _omh_auto_resume_history() {",
            "      add-zsh-hook -d zshaddhistory _omh_auto_resume_history",
            f"      [[ ${{1%$'\\n'}} != {_sh_quote(line)} ]]",
            "    }",
            "    _omh_auto_resume() {",
            "      add-zle-hook-widget -d zle-line-init _omh_auto_resume",
            f"      BUFFER={_sh_quote(line)}",
            "      add-zsh-hook zshaddhistory _omh_auto_resume_history",
            "      zle accept-line",
            "    }",
            "    autoload -Uz add-zle-hook-widget add-zsh-hook && zle -N _omh_auto_resume &&",
            "      add-zle-hook-widget zle-line-init _omh_auto_resume",
            "  fi",
            "  unset _omh_wake _omh_pids _omh_p _omh_rec _omh_boot",
            "fi",
        ]
    elif shell == "bash":
        command = f"command omh --omh-home {_sh_quote(home_text)} auto-resume shell-start"
        unset = "".join(f"${{{name}-}}" for name in guard_names)
        body = [
            f'if [[ $- == *i* && -z "{unset}" ]]; then',
            "  export OMH_AUTO_RESUME_DONE=1",
            *_posix_wake(marker, live_pids, boot_file, "$_omh_pids"),
            '  if [[ -n $_omh_wake ]] && command -v omh >/dev/null 2>&1; then',
            "    _omh_auto_resume() {",
            '      [[ -n "${_omh_auto_resume_ran-}" ]] && return 0',
            "      _omh_auto_resume_ran=1",
            "      local _omh_i _omh_nl=$'\\n'",
            '      if [[ -n "${_omh_auto_resume_array-}" ]]; then',
            '        for _omh_i in "${!PROMPT_COMMAND[@]}"; do',
            '          [[ "${PROMPT_COMMAND[$_omh_i]}" == _omh_auto_resume ]] && unset "PROMPT_COMMAND[$_omh_i]"',
            "        done",
            '      elif [[ "${PROMPT_COMMAND-}" == _omh_auto_resume ]]; then',
            "        unset PROMPT_COMMAND",
            "      else",
            '        PROMPT_COMMAND="${PROMPT_COMMAND%"${_omh_nl}_omh_auto_resume"}"',
            "      fi",
            f"      [[ -t 0 && -t 1 ]] && {command}",
            "      return 0",
            "    }",
            "    if (( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1) )) &&",
            '        [[ -n "${PROMPT_COMMAND+x}" && ${PROMPT_COMMAND@a} == *a* ]]; then',
            "      PROMPT_COMMAND+=(_omh_auto_resume) _omh_auto_resume_array=1",
            '    elif [[ -n "${PROMPT_COMMAND-}" ]]; then',
            "      PROMPT_COMMAND=\"$PROMPT_COMMAND\"$'\\n'_omh_auto_resume",
            "    else",
            "      PROMPT_COMMAND=_omh_auto_resume",
            "    fi",
            "  fi",
            "  unset _omh_wake _omh_pids _omh_p _omh_rec _omh_boot",
            "fi",
        ]
    elif shell == "powershell":
        set_any = " -or ".join(f"$env:{name}" for name in guard_names)
        body = [
            f"if ($Host.Name -eq 'ConsoleHost' -and -not ({set_any}) -and",
            "    -not ([Environment]::GetCommandLineArgs() -match '^-NonI')) {",
            "  $env:OMH_AUTO_RESUME_DONE = '1'",
            f"  if (((Test-Path -LiteralPath {_ps_quote(marker)}) -or (& {{",
            f"        $line = Get-Content -LiteralPath {_ps_quote(live_pids)} -TotalCount 1 -ErrorAction SilentlyContinue",
            "        foreach ($id in (\"$line\" -split ' ' | Select-Object -Skip 1)) {",
            "          if ($id -match '^[0-9]{1,9}$' -and -not (Get-Process -Id $id -ErrorAction SilentlyContinue)) {",
            "            return $true",
            "          }",
            "        }",
            "        $false",
            "      })) -and (Get-Command omh -CommandType Application -ErrorAction SilentlyContinue)) {",
            f"    & omh --omh-home {_ps_quote(home_text)} auto-resume shell-start",
            "  }",
            "}",
        ]
    else:
        raise ShellHookError(f"unsupported shell: {shell!r}; expected one of {', '.join(SHELLS)}")
    return [BEGIN, ABOUT, *body, END]


def _target(rc: Path, environ: Mapping[str, str]) -> Path:
    """The file to read and write for `rc`: itself, or the file a symlink resolves to inside the home."""
    if not rc.is_symlink():
        return rc
    resolved = rc.resolve()
    home = home_dir(environ).resolve()
    if resolved != home and home not in resolved.parents:
        raise ShellHookError(f"{rc} is a symbolic link to {resolved}, outside {home}; OMH writes no file there")
    return resolved


def _read(path: Path) -> bytes | None:
    """The file's bytes, or None when it does not exist."""
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ShellHookError(f"{path} is not a regular file")
    if info.st_size > MAX_RC_BYTES:
        raise ShellHookError(f"{path} is larger than {MAX_RC_BYTES} bytes; OMH leaves it alone")
    return path.read_bytes()


def _write(path: Path, data: bytes, mode: int) -> None:
    """`data` at `path` through a temporary file beside it and a rename; the file keeps `mode`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.omh-{os.getpid()}-{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(mode))
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _lines(data: bytes) -> list[bytes]:
    return data.splitlines(keepends=True)


def _stripped(line: bytes) -> bytes:
    return line.rstrip(b"\r\n")


def _find_block(data: bytes) -> tuple[int, int, list[bytes]] | None:
    """The first block's byte span (begin line start to end line end) and its lines; None when there is none."""
    begin, end = BEGIN.encode(), END.encode()
    offset, start, inside = 0, -1, []
    for line in _lines(data):
        if start < 0 and _stripped(line) == begin:
            start = offset
        if start >= 0:
            inside.append(line)
            if _stripped(line) == end:
                return start, offset + len(line), inside
        offset += len(line)
    if start >= 0:
        raise ShellHookError(f"an `{BEGIN}` line has no `{END}` line after it; OMH will not guess where the block ends")
    return None


def _eol(data: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in data else b"\n"


def _block_eol(shell: str, data: bytes) -> bytes:
    """The block's own line end: LF for zsh and bash, which read a CR as part of the word before it (`then\\r` is
    a syntax error); PowerShell takes either, so its block follows the file."""
    return b"\n" if shell in ("zsh", "bash") else _eol(data)


def _encode(lines: list[str], eol: bytes) -> bytes:
    return b"".join(line.encode("utf-8") + eol for line in lines)


def install(
    shell: str, omh_home: str | Path, environ: Mapping[str, str], *, dry_run: bool = False,
    platform: str | None = None,
) -> HookResult:
    """Append the block to `shell`'s rc, or bring an existing block up to date; nothing written on `dry_run`."""
    rc = rc_path(shell, environ, platform=platform)
    target = _target(rc, environ)
    lines = render_block(shell, omh_home)
    data = _read(target)
    if data is not None and (found := _find_block(data)) is not None:
        start, stop, inside = found
        kept = [_stripped(line).decode("utf-8", "replace") for line in inside
                if _stripped(line).decode("utf-8", "replace") in (ADDED_LINE_END, CREATED_FILE)]
        fresh = lines[:2] + kept + lines[2:]
        block = _encode(fresh, _block_eol(shell, data))
        if data[start:stop] == block:
            return HookResult(shell, target, "unchanged", False, dry_run, "\n".join(fresh))
        if not dry_run:
            _write(target, data[:start] + block + data[stop:], target.stat().st_mode)
        return HookResult(shell, target, "updated", True, dry_run, "\n".join(fresh))
    flags = []
    if data is None:
        flags.append(CREATED_FILE)
    elif data and not data.endswith(b"\n"):
        flags.append(ADDED_LINE_END)
    fresh = lines[:2] + flags + lines[2:]
    prefix = _eol(data or b"") if ADDED_LINE_END in flags else b""  # the person's line, ended their way
    if not dry_run:
        mode = NEW_RC_MODE if data is None else target.stat().st_mode
        _write(target, (data or b"") + prefix + _encode(fresh, _block_eol(shell, data or b"")), mode)
    return HookResult(shell, target, "installed", True, dry_run, "\n".join(fresh))


def remove(
    shell: str, environ: Mapping[str, str], *, dry_run: bool = False, platform: str | None = None,
) -> HookResult:
    """Take every OMH block out of `shell`'s rc, and what `install` added around it; nothing written on `dry_run`."""
    rc = rc_path(shell, environ, platform=platform)
    target = _target(rc, environ)
    data = _read(target)
    if data is None or _find_block(data) is None:
        return HookResult(shell, target, "absent", False, dry_run)
    created = False
    while (found := _find_block(data)) is not None:
        start, stop, inside = found
        flags = {_stripped(line) for line in inside}
        if ADDED_LINE_END.encode() in flags:
            eol = _eol(data)
            if data[:start].endswith(eol):
                start -= len(eol)
            elif data[:start].endswith(b"\n"):
                start -= 1
        created = created or CREATED_FILE.encode() in flags
        data = data[:start] + data[stop:]
    if not dry_run:
        if created and not data:
            target.unlink()
        else:
            _write(target, data, target.stat().st_mode)
    return HookResult(shell, target, "removed", True, dry_run)


def hook_state(shell: str, environ: Mapping[str, str], *, platform: str | None = None) -> dict[str, object]:
    """Read-only: `shell`'s rc path, whether it exists, and whether it holds an OMH block (None: unreadable)."""
    rc = rc_path(shell, environ, platform=platform)
    state: dict[str, object] = {"shell": shell, "rc": str(rc), "exists": False, "installed": False}
    try:
        target = _target(rc, environ)
        data = _read(target)
        state["exists"] = data is not None
        state["installed"] = data is not None and _find_block(data) is not None
    except (OSError, ShellHookError) as error:
        state["installed"] = None
        state["error"] = str(error)
    return state


def offer(environ: Mapping[str, str], *, platform: str | None = None) -> tuple[str, Path] | None:
    """The default shell and its rc when that rc exists and holds no block yet: what `omh setup` may offer."""
    shell = default_shell(environ, platform)
    if shell is None:
        return None
    state = hook_state(shell, environ, platform=platform)
    if state["exists"] and state["installed"] is False:
        return shell, Path(str(state["rc"]))
    return None
