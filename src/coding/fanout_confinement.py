"""Filesystem confinement for the local fanout subprocess boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from ..quality.cross_harness_adapter_sandbox import (
    ChildContext,
    backend,
    backend_available,
    preflight,
    read_roots_are_safe,
    runtime_roots,
    sandbox_command,
    unique_roots,
)

FANOUT_FILESYSTEM_CONFINEMENT_SCHEMA_VERSION = "fanout_filesystem_confinement/v1"
FANOUT_FILESYSTEM_CONFINEMENT_CLAIM_BOUNDARY = (
    "A confinement receipt is observed only when its same-run sandbox probe wrote inside the unit worktree "
    "and was refused outside it. Backend availability, preflight, and a prepared command alone are not confinement evidence."
)
# Fanout confines writes, not reads: an invited coding CLI needs its own toolchain,
# configuration, credentials, and caches. The receipt attests only the write boundary.
_FANOUT_MACOS_TOOLCHAIN_WRITE_DATA_LITERALS = (Path("/dev/null"),)
_FANOUT_MACOS_TOOLCHAIN_TEMP_DIRECTORY = Path(".omh") / "confinement-tmp"


@dataclass(frozen=True, slots=True)
class FanoutFilesystemConfinement:
    """One backend/root set that can wrap every process in one unit run."""

    selected: str
    roots: tuple[Path, ...]
    child: ChildContext | None
    environment: Mapping[str, str]
    backend_digest: str
    executables: Mapping[str, str]
    receipt: dict[str, object]

    def command(self, argv: Sequence[str]) -> tuple[str, ...] | None:
        """Return the same-root sandbox command, or None when no receipt proved it."""
        if self.receipt.get("enforced") is not True or not argv or self.child is None:
            return None
        executable = self.executables.get(str(argv[0]))
        if not executable:
            return None
        return sandbox_command(
            (executable, *[str(argument) for argument in argv[1:]]),
            self.selected,
            self.roots,
            self.child,
            True,
            self.environment,
            self.backend_digest,
            allow_broad_process_exec=True,
            macos_write_data_literals=_FANOUT_MACOS_TOOLCHAIN_WRITE_DATA_LITERALS,
            allow_broad_file_read=True,
        )

    def command_environment(self) -> dict[str, str]:
        """Keep macOS toolchain scratch writes within the confined worktree."""
        if (
            self.receipt.get("enforced") is not True
            or self.child is None
            or self.selected != "sandbox-exec"
        ):
            return dict(self.environment)
        return {
            **self.environment,
            "TMPDIR": str(self.child.work / _FANOUT_MACOS_TOOLCHAIN_TEMP_DIRECTORY),
        }


def planned_fanout_filesystem_confinement(worktree: Path) -> dict[str, object]:
    """Describe a dry-run boundary without claiming the probe ran."""
    selected = backend("auto")
    reason_code = "dry_run_no_confinement_probe"
    if selected == "unsupported":
        reason_code = "no_os_confinement_backend_on_this_platform"
    return _receipt(
        status="prepared_not_observed",
        selected=selected,
        worktree=worktree,
        enforced=False,
        reason_code=reason_code,
    )


def prepare_fanout_filesystem_confinement(
    worktree: Path,
    environment: Mapping[str, str],
    commands: Sequence[Sequence[str]],
) -> FanoutFilesystemConfinement:
    """Probe one unit's backend before allowing its owner or checks to use it."""
    worktree = worktree.resolve()
    selected = backend("auto")
    if selected == "unsupported":
        return _unconfined(worktree, selected, environment, "no_os_confinement_backend_on_this_platform")
    if not backend_available(selected):
        return _unconfined(worktree, selected, environment, "sandbox_backend_unavailable")
    if not commands:
        return _unconfined(worktree, selected, environment, "sandbox_no_runnable_command")
    executables = _resolve_executables(commands, environment)
    if not executables:
        return _unconfined(worktree, selected, environment, "sandbox_executable_not_found")
    roots = unique_roots(
        (worktree, *(Path(executable).parent for executable in executables.values()), *runtime_roots(selected))
    )
    if not read_roots_are_safe(roots):
        return _unconfined(
            worktree, selected, environment, "unsafe_sandbox_read_root", roots=roots, executables=executables
        )
    if selected == "sandbox-exec":
        scratch_directory = worktree / _FANOUT_MACOS_TOOLCHAIN_TEMP_DIRECTORY
        scratch_directory.mkdir(parents=True, exist_ok=True)
        _ = (scratch_directory / ".gitignore").write_text("*\n", encoding="utf-8")
    child = ChildContext(
        worktree,
        worktree,
        worktree,
        worktree,
        worktree,
        worktree / ".omh-confinement-request",
        worktree / ".omh-confinement-artifact",
        "fanout-filesystem-confinement",
    )
    ready, backend_digest = preflight(selected, roots, child, True, environment)
    if not ready:
        return _unconfined(
            worktree,
            selected,
            environment,
            "sandbox_preflight_failed",
            roots=roots,
            child=child,
            backend_digest=backend_digest,
            executables=executables,
        )
    receipt = _probe(selected, roots, child, environment, backend_digest)
    return FanoutFilesystemConfinement(
        selected,
        roots,
        child,
        environment,
        backend_digest,
        executables,
        receipt,
    )


def confinement_receipt(
    confinement: FanoutFilesystemConfinement | None,
    worktree: Path,
) -> dict[str, object]:
    """Return the receipt, keeping non-spawning injected runners explicit."""
    if confinement is not None:
        return confinement.receipt
    return _receipt(
        status="prepared_not_observed",
        selected=backend("auto"),
        worktree=worktree,
        enforced=False,
        reason_code="sandbox_not_applied_to_injected_runner",
    )


def _unconfined(
    worktree: Path,
    selected: str,
    environment: Mapping[str, str],
    reason_code: str,
    *,
    roots: tuple[Path, ...] = (),
    child: ChildContext | None = None,
    backend_digest: str = "",
    executables: Mapping[str, str] | None = None,
) -> FanoutFilesystemConfinement:
    return FanoutFilesystemConfinement(
        selected,
        roots,
        child,
        environment,
        backend_digest,
        {} if executables is None else executables,
        _receipt(
            status="prepared_not_observed",
            selected=selected,
            worktree=worktree,
            enforced=False,
            reason_code=reason_code,
        ),
    )


def _resolve_executables(
    commands: Sequence[Sequence[str]], environment: Mapping[str, str]
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    path = environment.get("PATH")
    for command in commands:
        if not command:
            continue
        name = str(command[0])
        located = name if Path(name).is_absolute() else shutil.which(name, path=path)
        if located is None:
            return {}
        resolved[name] = str(Path(located).resolve())
    return resolved


def _probe(
    selected: str,
    roots: tuple[Path, ...],
    child: ChildContext,
    environment: Mapping[str, str],
    backend_digest: str,
) -> dict[str, object]:
    token = uuid4().hex
    inside = child.work / f".omh-confinement-inside-{token}"
    outside = child.work.parent / f".omh-confinement-outside-{token}"
    script = (
        'printf inside > "$1"; inside=$?; printf outside > "$2"; outside=$?; '
        'printf "inside_exit=%s outside_exit=%s\\n" "$inside" "$outside"; '
        'test "$inside" -eq 0 -a "$outside" -ne 0'
    )
    argv = ("/bin/sh", "-c", script, "omh-confinement-probe", str(inside), str(outside))
    try:
        completed = subprocess.run(
            sandbox_command(argv, selected, roots, child, True, environment, backend_digest),
            cwd=child.work,
            env=environment,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        match = re.search(r"inside_exit=(\d+) outside_exit=(\d+)", completed.stdout)
        inside_code = int(match.group(1)) if match else None
        outside_code = int(match.group(2)) if match else None
        enforced = (
            completed.returncode == 0
            and inside_code == 0
            and outside_code is not None
            and outside_code != 0
            and inside.is_file()
            and not outside.exists()
        )
        return {
            **_receipt(
                status="observed",
                selected=selected,
                worktree=child.work,
                enforced=enforced,
                reason_code="" if enforced else "sandbox_probe_failed",
            ),
            "probe": {
                "status": "observed",
                "command": list(argv),
                "exit_code": completed.returncode,
                "inside_write_exit_code": inside_code,
                "outside_write_exit_code": outside_code,
                "refusal": completed.stderr.strip()[:300],
            },
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            **_receipt(
                status="observed",
                selected=selected,
                worktree=child.work,
                enforced=False,
                reason_code="sandbox_probe_failed",
            ),
            "probe": {
                "status": "observed",
                "command": list(argv),
                "exit_code": None,
                "inside_write_exit_code": None,
                "outside_write_exit_code": None,
                "refusal": str(exc)[:300],
            },
        }
    finally:
        inside.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


def _receipt(
    *,
    status: str,
    selected: str,
    worktree: Path,
    enforced: bool,
    reason_code: str,
) -> dict[str, object]:
    return {
        "schema_version": FANOUT_FILESYSTEM_CONFINEMENT_SCHEMA_VERSION,
        "status": status,
        "backend": selected,
        "write_root": str(worktree.resolve()),
        "enforced": enforced,
        "reason_code": reason_code,
        "claim_boundary": FANOUT_FILESYSTEM_CONFINEMENT_CLAIM_BOUNDARY,
    }
