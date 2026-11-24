"""The `hermes gateway run` processes on this machine, read from the kernel without starting a process.

`omh doctor` spawns nothing (`tests/test_ai_job_search_distribution.py` runs
it with `subprocess.Popen` forbidden), so the gateway health row cannot run
`ps`. Each process's argument vector is read where the OS keeps it:

- Linux: `/proc/<pid>/cmdline` (NUL-separated arguments) of this user's
  processes only (the `/proc/<pid>` owner), as macOS answers;
- macOS: `proc_listallpids` (libproc) for the pids, then
  `sysctl(KERN_PROCARGS2)` per pid, which answers only for this user's
  processes. The kernel returns the argument count, the executable path, the
  arguments and then the environment in one buffer; only the first `argc`
  strings are decoded, and the buffer is dropped without the environment
  ever being parsed;
- anything else (Windows): no listing, said as such (`None`), never as an
  empty one.

Nothing is signalled, written or spawned; every read is bounded.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import struct
import sys

PROCESS_CAP = 1 << 16
ARGS_BYTES = 256 << 10  # macOS' default `kern.argmax` is 1 MiB; a gateway's arguments are a few hundred bytes
CTL_KERN = 1
KERN_PROCARGS2 = 49
INTERPRETER_FLAGS = frozenset({"-I", "-B", "-E", "-s", "-S", "-u", "-O", "-OO", "-P"})  # flags before `-m`


# Hermes' `spawn_unmanaged_gateway` adds it for a client's own start (chat, TUI, cron); `gateway/run_idle_exit.py`
# then ends that gateway once it is idle for `gateway.unmanaged_idle_exit_seconds`.
IDLE_EXIT_FLAG = "--idle-exit"
RETITLED_ARGV = ["hermes"]  # Hermes' optional `setproctitle("hermes")` replaces the whole command line with this
LAUNCH_SHAPES = (
    "`python -m hermes_cli.main [--profile N] gateway run`, `python …/hermes-agent/hermes gateway run` and Hermes' "
    "launcher `python -I -c <bootstrap> [--profile N] gateway run`"
)


@dataclass(frozen=True)
class GatewayListing:
    listed: bool  # False where this platform offers no listing: never read as an empty one
    gateways: tuple[tuple[int, str], ...] = ()  # (pid, the profile its command line names, "" for none)
    retitled: tuple[int, ...] = ()  # this user's processes titled just `hermes`, whose arguments cannot be read
    idle_exit: tuple[int, ...] = ()  # gateways launched with `--idle-exit`: a Hermes client's own start, ended once idle


def process_argvs() -> list[tuple[int, list[str]]] | None:
    """Every readable process of this user as `(pid, argv)`, or None where this platform offers no listing."""
    if sys.platform.startswith("linux"):
        return _linux_argvs(Path("/proc"), os.getuid())
    if sys.platform == "darwin":
        return _darwin_argvs()
    return None


def hermes_gateway_processes() -> GatewayListing:
    """Every `hermes gateway run` of this user the kernel's process table shows."""
    argvs = process_argvs()
    if argvs is None:
        return GatewayListing(False)
    retitled = tuple(pid for pid, argv in argvs if argv == RETITLED_ARGV)
    runs = _gateway_run_options(argvs)
    idle_exit = tuple(pid for pid, _profile, options in runs if IDLE_EXIT_FLAG in options)
    return GatewayListing(True, tuple((pid, profile) for pid, profile, _options in runs), retitled, idle_exit)


def gateway_runs(argvs: list[tuple[int, list[str]]]) -> list[tuple[int, str]]:
    """The `(pid, profile)` of each argv that runs `hermes gateway run`; profile "" when the command line names none."""
    return [(pid, profile) for pid, profile, _options in _gateway_run_options(argvs)]


def _gateway_run_options(argvs: list[tuple[int, list[str]]]) -> list[tuple[int, str, list[str]]]:
    """`(pid, profile, the arguments after `gateway run`)` of each argv that runs `hermes gateway run`.

    Recognized: `python -m hermes_cli.main [--profile N|-p N|--profile=N] gateway run …`
    and `python …/hermes-agent/hermes [profile] gateway run …`, after any interpreter
    flags (`INTERPRETER_FLAGS`), and Hermes' own launcher (`.hermes/bin/hermes`,
    which service units and a typed `hermes gateway run` use):
    `python -I -c <bootstrap naming hermes_cli> [profile] gateway run …`. A
    wrapper whose arguments start otherwise (Hermes' `--run-module` stderr
    stamper around the launcher) is not a gateway itself.
    """
    found: list[tuple[int, str, list[str]]] = []
    for pid, argv in argvs:
        if len(argv) < 2 or not Path(argv[0]).name.startswith("python"):
            continue
        rest = argv[1:]
        while rest and rest[0] in INTERPRETER_FLAGS:
            rest = rest[1:]
        if len(rest) >= 2 and rest[0] == "-m" and rest[1] == "hermes_cli.main":
            arguments = rest[2:]
        elif len(rest) >= 2 and rest[0] == "-c" and "hermes_cli" in rest[1]:
            arguments = rest[2:]
        elif rest and Path(rest[0]).parts[-2:] == ("hermes-agent", "hermes"):
            arguments = rest[1:]
        else:
            continue
        split = _profile_and_command(arguments)
        if split is not None and split[1][:2] == ["gateway", "run"]:
            found.append((pid, split[0], split[1][2:]))
    return found


def _profile_and_command(arguments: list[str]) -> tuple[str, list[str]] | None:
    if arguments and arguments[0] in {"--profile", "-p"}:
        if len(arguments) < 2 or not arguments[1]:
            return None
        return arguments[1], arguments[2:]
    if arguments and arguments[0].startswith("--profile="):
        name = arguments[0].partition("=")[2]
        return (name, arguments[1:]) if name else None
    return "", arguments


def _linux_argvs(proc: Path, uid: int) -> list[tuple[int, list[str]]]:
    found: list[tuple[int, list[str]]] = []
    try:
        entries = [entry for entry in proc.iterdir() if entry.name.isdigit()]
    except OSError:
        return found
    for entry in entries[:PROCESS_CAP]:
        try:
            if entry.stat().st_uid != uid:
                continue  # another user's: `/proc` shows it, but its gateways are not this person's
            with (entry / "cmdline").open("rb") as handle:
                raw = handle.read(ARGS_BYTES)
        except OSError:
            continue
        argv = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        if argv:
            found.append((int(entry.name), argv))
    return found


def _darwin_argvs() -> list[tuple[int, list[str]]] | None:
    import ctypes

    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
    except OSError:
        return None
    libproc.proc_listallpids.argtypes = (ctypes.c_void_p, ctypes.c_int)
    count = libproc.proc_listallpids(None, 0)
    if count <= 0:
        return None
    slots = min(count + 256, PROCESS_CAP)
    pids = (ctypes.c_int * slots)()
    filled = libproc.proc_listallpids(pids, ctypes.sizeof(pids))
    if filled <= 0:
        return None
    found: list[tuple[int, list[str]]] = []
    buffer = ctypes.create_string_buffer(ARGS_BYTES)
    for pid in pids[: min(filled, slots)]:
        if pid <= 0:
            continue
        size = ctypes.c_size_t(ARGS_BYTES)
        mib = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
            continue  # another user's process, or one that just exited
        argv = procargs2_argv(buffer.raw[: size.value])
        if argv:
            found.append((pid, argv))
    return found


def procargs2_argv(raw: bytes) -> list[str]:
    """The `argc` argument strings of a `KERN_PROCARGS2` buffer; the environment after them is never decoded.

    Layout: a native `int` argc, the executable path NUL-terminated, NUL
    padding, then the arguments, each NUL-terminated.
    """
    if len(raw) < 4:
        return []
    (argc,) = struct.unpack_from("i", raw, 0)
    if argc <= 0:
        return []
    position = raw.find(b"\0", 4)  # end of the executable path
    if position < 0:
        return []
    while position < len(raw) and raw[position] == 0:
        position += 1
    argv: list[str] = []
    while len(argv) < argc and position < len(raw):
        end = raw.find(b"\0", position)
        if end < 0:
            return []
        argv.append(raw[position:end].decode("utf-8", errors="replace"))
        position = end + 1
    return argv if len(argv) == argc else []
