from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from threading import Thread
import time
from typing import BinaryIO, Final

from .cross_harness_benchmark_values import JsonValue
from .cross_harness_adapter_io import read_regular_file
from . import cross_harness_adapter_backend as _backend_security


MAX_OUTPUT_BYTES: Final = 1_048_576
PROCESS_CLEANUP_SECONDS: Final = 1.0
_SECRET_VALUE_PATTERNS: Final = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\bghp_[A-Za-z0-9]{20,}\b", r"\bAKIA[A-Z0-9]{16}\b",
    r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    r"\bbearer\s+\S+", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\bsk-[A-Za-z0-9_-]{16,}\b",
))
_CREDENTIAL_KEY_MARKERS: Final = (
    "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL", "API_KEY",
    "AWS_", "AZURE_", "GOOGLE_", "OPENAI_", "ANTHROPIC_", "GITHUB_",
    "CODEX_", "CLAUDE_", "HERMES_",
)
_SENSITIVE_PARTS: Final = {
    ".ssh", ".aws", ".config", ".codex", ".claude", ".hermes", ".omh",
    "keychains", "credentials",
}
_MACOS_RUNTIME_ROOTS: Final = tuple(
    Path(item) for item in (
        "/usr/lib", "/System/Library", "/Library/Apple/System/Library",
        "/private/var/db/dyld",
        "/private/var/select",
    )
)
PopenFactory = Callable[..., subprocess.Popen[bytes]]


@dataclass(frozen=True, slots=True)
class ChildContext:
    root: Path
    home: Path
    work: Path
    temporary: Path
    output: Path
    request_path: Path
    artifact_path: Path
    spawn_digest: str


@dataclass(frozen=True, slots=True)
class ProcessObservation:
    status: str
    exit_code: int | None
    process_group_terminated: bool
    stdout_hash: str
    stdout_bytes: int
    stderr_hash: str
    stderr_bytes: int
    stdout_sample: bytes
    stderr_sample: bytes
    overflow: bool


def allocate_child(
    root: Path,
    request_payload: Mapping[str, JsonValue],
    request_digest: str,
    repetition: int,
) -> ChildContext:
    root = root.resolve()
    home, work, temporary, output = (root / name for name in ("home", "work", "tmp", "output"))
    root.chmod(0o700)
    for directory in (home, work, temporary, output):
        directory.mkdir(mode=0o700)
    request_path = root / "request.json"
    request_path.write_text(json.dumps(request_payload, sort_keys=True), encoding="utf-8")
    request_path.chmod(0o600)
    spawn_digest = hashlib.sha256(os.urandom(32)).hexdigest()
    artifact_path = output / f"result-{repetition}-{spawn_digest}.json"
    return ChildContext(root, home, work, temporary, output, request_path, artifact_path, spawn_digest)


def observe_process(
    argv: tuple[str, ...],
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    popen_factory: PopenFactory,
    backend_digest: str | None = None,
) -> ProcessObservation:
    if not _backend_security.command_is_trusted(argv[0], backend_digest):
        raise OSError("sandbox backend identity changed")
    process = popen_factory(
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
        start_new_session=True,
    )
    stream_results: list[tuple[str, int, bytes, bool] | None] = [None, None]
    assert process.stdout is not None and process.stderr is not None

    def consume_stream(position: int, stream: BinaryIO) -> None:
        digest, count, sample, overflow = hashlib.sha256(), 0, bytearray(), False
        try:
            while chunk := stream.read(8192):
                count += len(chunk)
                overflow = overflow or count > MAX_OUTPUT_BYTES
                digest.update(chunk)
                if len(sample) < 512:
                    sample.extend(chunk[: 512 - len(sample)])
        except OSError:
            overflow = True
        finally:
            stream_results[position] = (digest.hexdigest(), count, bytes(sample), overflow)

    threads = (
        Thread(target=consume_stream, args=(0, process.stdout), daemon=True),
        Thread(target=consume_stream, args=(1, process.stderr), daemon=True),
    )
    for thread in threads:
        thread.start()
    try:
        try:
            exit_code = process.wait(timeout=timeout)
            status = "crash" if exit_code < 0 else "exit"
        except subprocess.TimeoutExpired:
            status, exit_code = "timeout", None
    finally:
        cleanup_deadline = time.monotonic() + PROCESS_CLEANUP_SECONDS
        cleanup_ok = terminate_process_group(process.pid, process, cleanup_deadline)
        for thread in threads:
            thread.join(max(0.0, cleanup_deadline - time.monotonic()))
        streams_done = not any(thread.is_alive() for thread in threads)
        cleanup_ok = cleanup_ok and streams_done
        if streams_done:
            process.stdout.close()
            process.stderr.close()
    stdout, stderr = stream_results
    stdout = stdout or (hashlib.sha256().hexdigest(), 0, b"", True)
    stderr = stderr or (hashlib.sha256().hexdigest(), 0, b"", True)
    return ProcessObservation(
        status, exit_code, cleanup_ok, stdout[0], stdout[1], stderr[0],
        stderr[1], stdout[2], stderr[2], stdout[3] or stderr[3],
    )


def process_group_absent(process_id: int) -> bool:
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def terminate_process_group(process_id: int, process: subprocess.Popen[bytes], deadline: float) -> bool:
    try:
        os.killpg(process_id, signal.SIGKILL)
    except ProcessLookupError:
        return process.poll() is not None
    except PermissionError:
        return False
    if process.poll() is None:
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return False
    while not process_group_absent(process_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    return process_group_absent(process_id)


def backend(selected: str) -> str:
    if selected != "auto":
        return selected
    if sys.platform == "darwin":
        return "sandbox-exec"
    return "bwrap" if sys.platform.startswith("linux") else "unsupported"


def backend_available(selected: str) -> bool:
    return (
        (selected == "sandbox-exec" and sys.platform == "darwin")
        or (selected == "bwrap" and sys.platform.startswith("linux"))
    )


def environment_is_safe(environment: Sequence[tuple[str, str]]) -> bool:
    return not any(
        not key.startswith("OMH_")
        or any(marker in key.upper() for marker in _CREDENTIAL_KEY_MARKERS)
        or "ignore previous" in value.casefold()
        or any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
        for key, value in environment
    )


def read_roots_are_safe(read_roots: Sequence[Path]) -> bool:
    home = Path.home().resolve()
    for root in read_roots:
        resolved = root.resolve()
        if resolved == Path("/") or resolved == home:
            return False
        if _SENSITIVE_PARTS.intersection(part.casefold() for part in resolved.parts):
            return False
    return True


def runtime_roots(selected: str) -> tuple[Path, ...]:
    return _MACOS_RUNTIME_ROOTS if selected == "sandbox-exec" else ()


def preflight(
    selected: str,
    roots: tuple[Path, ...],
    child: ChildContext,
    allow_network: bool,
    environment: Mapping[str, str],
) -> tuple[bool, str]:
    tool = "/usr/bin/sandbox-exec" if selected == "sandbox-exec" else _trusted_bwrap()
    if tool is None:
        return False, "unavailable"
    try:
        tool_digest = hashlib.sha256(read_regular_file(Path(tool))[0]).hexdigest()
    except OSError:
        return False, "unavailable"
    try:
        completed = subprocess.run(
            sandbox_command(("/usr/bin/true",), selected, roots, child, allow_network, environment, tool_digest),
            cwd=child.work, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, tool_digest
    return completed.returncode == 0, tool_digest


def sandbox_command(
    argv: tuple[str, ...],
    selected: str,
    roots: Sequence[Path],
    child: ChildContext,
    allow_network: bool,
    environment: Mapping[str, str],
    backend_digest: str | None = None,
    allow_broad_process_exec: bool = False,
    macos_read_root_aliases: Sequence[Path] = (),
    macos_read_literals: Sequence[Path] = (),
    macos_write_data_literals: Sequence[Path] = (),
    write_literals: Sequence[Path] = (),
    macos_mach_lookup_names: Sequence[str] = (),
    allow_broad_file_read: bool = False,
    # A write root is not screened as a read root: this is an explicit execution
    # allowance, while `read_roots_are_safe` protects data exposed to a child.
    write_roots: Sequence[Path] = (),
) -> tuple[str, ...]:
    if selected == "sandbox-exec":
        executables = (argv[0], "/usr/bin/true")
        if Path(argv[0]).resolve() == Path("/bin/sh").resolve():
            # macOS dispatches `/bin/sh` through `/bin/bash` after consulting
            # `/private/var/select`; the same narrow allowance lets the
            # confinement probe run without widening ordinary adapter argv.
            executables += ("/bin/bash",)
        literals = " ".join(
            f'(literal {json.dumps(str(Path(item).resolve()))})'
            for item in executables
        )
        process_exec = "(allow process-exec*)" if allow_broad_process_exec else f"(allow process-exec {literals})"
        canonical_roots = unique_roots((*roots, child.root))
        canonical_root_names = {str(root) for root in canonical_roots}
        policy_roots = (
            *canonical_roots,
            *(root for root in macos_read_root_aliases if str(root) not in canonical_root_names),
        )
        subpaths = " ".join(f'(subpath {json.dumps(str(root))})' for root in policy_roots)
        read_literals = " ".join(
            f'(literal {json.dumps(str(root))})' for root in macos_read_literals
        )
        read_literal_clause = f" {read_literals}" if read_literals else ""
        file_read = (
            "(allow file-read*)"
            if allow_broad_file_read
            else f'(allow file-read* (literal "/") {literals}{read_literal_clause} {subpaths})'
        )
        write_data_literals = "".join(
            f'(allow file-write-data (literal {json.dumps(str(root))}))'
            for root in macos_write_data_literals
        )
        write_subpaths = " ".join(
            f'(subpath {json.dumps(str(root))})' for root in unique_roots((child.root, *write_roots))
        )
        # Seatbelt's literal grants operations on the exact name. If an
        # external writer removes that file and replaces it with a directory,
        # the literal rule still denies writes below the replacement directory.
        write_literal_policy = "".join(
            f'(allow file-write* (literal {json.dumps(str(path.resolve()))}))'
            for path in unique_roots(write_literals)
        )
        mach_lookup = "".join(
            f'(allow mach-lookup (global-name {json.dumps(name)}))'
            for name in macos_mach_lookup_names
        )
        network = "(allow network*)" if allow_network else ""
        policy = f'(version 1)(deny default)(deny syscall-unix (syscall-number 147 82))(allow process-fork){process_exec}(allow sysctl-read){file_read}{write_data_literals}{write_literal_policy}(allow file-write* {write_subpaths}){mach_lookup}{network}'
        return ("/usr/bin/sandbox-exec", "-p", policy, *argv)
    tool = _trusted_bwrap(backend_digest)
    assert tool is not None
    flags = ["--unshare-user", "--unshare-ipc", "--unshare-pid", "--unshare-uts", "--disable-userns", "--new-session", "--die-with-parent", "--clearenv"]
    if not allow_network:
        flags.insert(3, "--unshare-net")
    bind_roots = unique_roots((*roots, Path(argv[0]).resolve().parent))
    binds = [part for root in bind_roots for part in ("--ro-bind", str(root), str(root))]
    writable_roots = tuple(root for root in unique_roots((*write_roots, *write_literals)) if root != child.root)
    # --bind-try keeps preparation non-fatal when an allowed state directory has
    # not been created yet; it never grants the broad parent directory instead.
    # In particular, it cannot create an absent exact file literal (#1356).
    write_binds = [part for root in writable_roots for part in ("--bind-try", str(root), str(root))]
    env_flags = [part for key, value in sorted(environment.items()) for part in ("--setenv", key, value)]
    return (tool, *flags, "--tmpfs", "/", *binds, "--bind", str(child.root), str(child.root), *write_binds, "--chdir", str(child.work), *env_flags, "--", *argv)


def _trusted_bwrap(expected_digest: str | None = None) -> str | None:
    snapshot = _backend_security.trusted_bwrap(expected_digest)
    return str(snapshot.path) if snapshot is not None else None


def unique_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    return tuple(dict.fromkeys(root.resolve() for root in roots))
