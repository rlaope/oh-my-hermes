"""Filesystem confinement for the local fanout subprocess boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import re
import shutil
import subprocess
from typing import cast
from uuid import uuid4

from ..quality.cross_harness_adapter_backend import trusted_bwrap
from ..quality.cross_harness_adapter_sandbox import (
    ChildContext,
    backend,
    backend_available,
    preflight,
    runtime_roots,
    sandbox_command,
    unique_roots,
)

FANOUT_FILESYSTEM_CONFINEMENT_SCHEMA_VERSION = "fanout_filesystem_confinement/v1"
FANOUT_FILESYSTEM_CONFINEMENT_CLAIM_BOUNDARY = (
    "A confinement receipt is observed only when its same-run sandbox probe wrote inside the unit worktree "
    "and every selected owner state directory, then was refused outside every write root. Owner state may also "
    "include an exact file literal and the two named credential mach-lookup allowances; neither expands into a "
    "directory or broader IPC permission. Backend availability, preflight, and a prepared command alone are not "
    "confinement evidence. Reads are not part of this boundary: every command this confinement returns runs with "
    "broad host read, so no receipt here reports a read boundary, whatever its write verdict."
)
# Fanout confines writes, not reads: an invited coding CLI needs its own toolchain,
# configuration, credentials, and caches. The receipt attests only the write boundary.
_FANOUT_MACOS_TOOLCHAIN_WRITE_DATA_LITERALS = (Path("/dev/null"),)
# Claude Code retrieves its OAuth credential through securityd. This named IPC
# lookup is orthogonal to file-write*: a Keychain ACL denial can invoke the
# external SecurityAgent prompt rather than hard-failing here, and still governs
# credential access.
_FANOUT_MACOS_CREDENTIAL_MACH_SERVICES = ("com.apple.securityd.xpc", "com.apple.SecurityServer")
_FANOUT_TOOLCHAIN_TEMP_DIRECTORY = Path(".omh") / "confinement-tmp"


@dataclass(frozen=True, slots=True)
class _OwnerStatePath:
    environment_variable: str | None
    default: Path
    fallback_environment_variables: tuple[str, ...] = ()
    is_file: bool = False
    configured_relative: bool = False


# The argv table in fanout_dispatch identifies the executable profile. These defaults
# are each CLI's state home; an explicit environment value wins. OMO state follows
# the resolved host, rather than Hermes state, because those are distinct owners.
_OWNER_STATE_DIRECTORIES: dict[str, dict[str | None, tuple[_OwnerStatePath, ...]]] = {
    "codex": {None: (_OwnerStatePath("CODEX_HOME", Path(".codex")),)},
    "claude-code": {
        # Claude's config directory is one owner-owned state tree, while the
        # home-level config file remains an exact literal outside that tree.
        None: (
            _OwnerStatePath("CLAUDE_CONFIG_DIR", Path(".claude")),
            _OwnerStatePath("CLAUDE_CONFIG_DIR", Path(".claude.json"), is_file=True, configured_relative=True),
        )
    },
    "hermes": {None: (_OwnerStatePath("HERMES_HOME", Path(".hermes")),)},
    "omo-runtime": {
        "pi": (_OwnerStatePath("PI_CODING_AGENT_DIR", Path(".pi") / "agent"),),
        # omh resolves and invokes senpi directly, never the branded `omo`
        # launcher. The latter owns the observed ~/.omo tree beyond agent/
        # (memory, codegraph, lsp-daemon, and config.jsonc), but that tree is
        # not direct-senpi state. Senpi itself has only agent/ on this host;
        # its resolver reads SENPI_CODING_AGENT_DIR then PI_CODING_AGENT_DIR,
        # never OMO_CODING_AGENT_DIR.
        "senpi": (
            _OwnerStatePath(
                "SENPI_CODING_AGENT_DIR",
                Path(".senpi") / "agent",
                fallback_environment_variables=("PI_CODING_AGENT_DIR",),
            ),
        ),
        # UNVERIFIED against a running OpenCode CLI: it is absent on this
        # host. Lead-observed XDG data contains logs/repos and XDG state is
        # present; ~/.opencode is absent and ~/.config/opencode is empty.
        # No OpenCode environment override is named without CLI evidence.
        "opencode": (
            _OwnerStatePath(None, Path(".local") / "share" / "opencode"),
            _OwnerStatePath(None, Path(".local") / "state" / "opencode"),
        ),
    },
}


def _owner_state_paths(owner: str, environment: Mapping[str, str]) -> tuple[tuple[Path, bool], ...]:
    profiles = _OWNER_STATE_DIRECTORIES.get(owner)
    if profiles is None:
        return ()
    host = None
    if owner == "omo-runtime":
        runtime_host = cast(
            Callable[[], str | None],
            getattr(import_module("omh.coding.fanout_dispatch"), "omo_runtime_host"),
        )
        host = runtime_host()
    profile = profiles.get(host)
    if profile is None:
        return ()
    paths: list[tuple[Path, bool]] = []
    for entry in profile:
        configured = ""
        for environment_variable in (entry.environment_variable, *entry.fallback_environment_variables):
            if environment_variable is not None and environment_variable in environment:
                configured = str(environment.get(environment_variable, "") or "").strip()
                break
        path = (
            (Path(configured).expanduser() / entry.default).resolve()
            if configured and entry.configured_relative
            else Path(configured).expanduser().resolve()
            if configured
            else (Path.home() / entry.default).resolve()
        )
        paths.append((path, entry.is_file))
    return tuple(paths)


def owner_state_directories(owner: str, environment: Mapping[str, str]) -> tuple[Path, ...]:
    """Return only the dispatched owner's state directories without creating them."""
    return unique_roots(tuple(path for path, is_file in _owner_state_paths(owner, environment) if not is_file))


def owner_state_files(owner: str, environment: Mapping[str, str]) -> tuple[Path, ...]:
    """Return only the dispatched owner's state files without creating them."""
    return unique_roots(tuple(path for path, is_file in _owner_state_paths(owner, environment) if is_file))


def owner_state_directory(owner: str, environment: Mapping[str, str]) -> Path | None:
    """Return the first state directory for compatibility with singular callers."""
    return next(iter(owner_state_directories(owner, environment)), None)


@dataclass(frozen=True, slots=True)
class FanoutFilesystemConfinement:
    """One backend/root set that can wrap every process in one unit run."""

    selected: str
    roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    write_literals: tuple[Path, ...]
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
            write_literals=self.write_literals,
            macos_mach_lookup_names=_FANOUT_MACOS_CREDENTIAL_MACH_SERVICES,
            allow_broad_file_read=True,
            write_roots=self.write_roots,
            inherit_environment=True,
            # Resolved once in `prepare_fanout_filesystem_confinement`.
            write_paths_resolved=True,
        )

    def command_environment(self, environment: Mapping[str, str] | None = None) -> dict[str, str]:
        """Keep toolchain scratch writes within the confined worktree."""
        selected_environment = self.environment if environment is None else environment
        if (
            self.receipt.get("enforced") is not True
            or self.child is None
            or self.selected not in {"sandbox-exec", "bwrap"}
        ):
            return dict(selected_environment)
        return {
            **selected_environment,
            "TMPDIR": str(self.child.work / _FANOUT_TOOLCHAIN_TEMP_DIRECTORY),
        }


# Diagnostics only (why a unit got no git write root). Never read for a security decision.
_GIT_ROOTS_LAST_SKIP: dict[str, str] = {}
_GIT_ROOTS_SKIP_LIMIT = 1024
_UNIT_BRANCH_RE = re.compile(r"^agent/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GIT_ENV_STRIP = (
    "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_INDEX_FILE", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


def git_roots_skip_reason(worktree: Path) -> str:
    """Why the last _git_write_roots call for this worktree added no git root ("" = roots were added)."""
    return _GIT_ROOTS_LAST_SKIP.get(str(worktree), "")


def _real_dir_chain(base: Path, parts: tuple[str, ...], *, create: bool) -> bool:
    """Walk base/parts one component at a time with openat + O_NOFOLLOW.

    A component that is a symlink (ELOOP) or not a directory (ENOTDIR) fails the walk.
    With create=True a missing component is made with mkdirat relative to the verified
    parent fd, so nothing is ever created through a symlink.
    """
    import os

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(str(base), flags)
    try:
        for part in parts:
            if part in ("", ".", "..") or "/" in part:
                return False
            try:
                nfd = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    return False
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
                nfd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _git_write_roots(worktree: Path, unit_branch: str = "", repo_root: Path | None = None) -> tuple[Path, ...]:
    """Write roots git itself needs so a unit can commit on its own branch.

    A linked worktree's git metadata lives under the shared repository, outside the
    unit worktree. Only these are added, and only when the unit is on its own branch:
      - the unit's gitdir (<C>/worktrees/<wt>: index, HEAD, logs/HEAD),
      - <C>/objects (new objects for the commit),
      - <C>/refs/heads/agent and <C>/logs/refs/heads/agent (the unit branch ref + reflog).
    hooks/, config, packed-refs and every ref outside refs/heads/agent stay read-only.
    The bind set, not this check, is the boundary: a unit that moves its own HEAD after
    the check can still only write inside these roots. Residual exposure (recorded, not
    closed here): sibling refs under refs/heads/agent, and objects/ (delete, replace,
    objects/info/alternates). Policy (start-state hygiene): HEAD must be the symbolic ref
    refs/heads/<unit_branch> with unit_branch = agent/<name>, that ref must not itself be
    symbolic, the worktree must be linked (<C>/worktrees/<wt>) with <C>/worktrees/<wt>/gitdir naming
    this worktree's .git and <C> == repo_root's common dir, and every bound root must
    be a real directory reached without a symlink component below <C>. Otherwise, and on
    any error, no git root is added (the unit stays sandboxed and cannot commit).
    """
    import os
    import stat
    import subprocess

    key = str(worktree)

    def _skip(reason: str) -> tuple[Path, ...]:
        _GIT_ROOTS_LAST_SKIP.pop(key, None)
        while len(_GIT_ROOTS_LAST_SKIP) >= _GIT_ROOTS_SKIP_LIMIT:  # FIFO trim: drop the oldest entry only
            _GIT_ROOTS_LAST_SKIP.pop(next(iter(_GIT_ROOTS_LAST_SKIP), None), None)
        _GIT_ROOTS_LAST_SKIP[key] = reason
        return ()

    try:
        if not unit_branch or not _UNIT_BRANCH_RE.match(unit_branch) or ".." in unit_branch:
            return _skip("name")
        env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_STRIP}

        def _ran(completed: subprocess.CompletedProcess[str]) -> tuple[int, str]:
            return completed.returncode, (completed.stdout or "").strip()

        wt = str(worktree)
        # Every git argv is spelled as a literal so the no-remote-mutation gate can read its verb.
        rc, head_ref = _ran(subprocess.run(
            ("git", "symbolic-ref", "-q", "HEAD"),
            cwd=wt, capture_output=True, text=True, timeout=10, check=False, env=env,
        ))
        if rc == 1:
            return _skip("detached")
        if rc != 0 or not head_ref:
            return _skip("git_error")
        expected = f"refs/heads/{unit_branch}"
        if head_ref != expected:
            return _skip("name")
        rc_sym, _ = _ran(subprocess.run(
            ("git", "symbolic-ref", "-q", expected),
            cwd=wt, capture_output=True, text=True, timeout=10, check=False, env=env,
        ))
        if rc_sym == 0:  # defensive: symbolic-ref HEAD already resolves chains, so this is normally unreachable
            return _skip("symref")
        if rc_sym != 1:
            return _skip("git_error")
        rc1, git_dir = _ran(subprocess.run(
            ("git", "rev-parse", "--path-format=absolute", "--git-dir"),
            cwd=wt, capture_output=True, text=True, timeout=10, check=False, env=env,
        ))
        rc2, common = _ran(subprocess.run(
            ("git", "rev-parse", "--path-format=absolute", "--git-common-dir"),
            cwd=wt, capture_output=True, text=True, timeout=10, check=False, env=env,
        ))
        if rc1 != 0 or rc2 != 0 or not git_dir or not common:
            return _skip("git_error")
        common_dir = Path(common).resolve()
        if Path(git_dir).resolve() == common_dir:
            return _skip("not_linked")
        # git canonicalizes --git-dir, so read the path the worktree's .git file actually names
        # and require it to be <C>/worktrees/<name> with no symlink component (alias gitdirs fail closed).
        gitfile = Path(worktree) / ".git"
        if gitfile.is_symlink() or not gitfile.is_file():
            return _skip("layout")
        first = gitfile.read_text(encoding="utf-8", errors="strict").splitlines()[:1]
        if not first or not first[0].startswith("gitdir: "):
            return _skip("layout")
        named = Path(first[0][len("gitdir: "):].strip())
        if not named.is_absolute():
            named = (Path(worktree) / named)
        named = Path(os.path.normpath(str(named)))
        if named.parent != common_dir / "worktrees" or Path(git_dir).resolve() != named:
            return _skip("layout")
        wt_name = named.name
        if not _real_dir_chain(common_dir, ("worktrees", wt_name), create=False):
            return _skip("symlink")
        # Back-link: <C>/worktrees/<name>/gitdir must name THIS worktree's .git, and <C> must be the
        # repository the dispatcher created the worktree from (not another repo/worktree the .git file names).
        backlink = common_dir / "worktrees" / wt_name / "gitdir"
        if backlink.is_symlink() or not backlink.is_file():
            return _skip("layout")
        named_back = Path(os.path.normpath(backlink.read_text(encoding="utf-8", errors="strict").strip()))
        if named_back != Path(os.path.normpath(str(Path(worktree).resolve() / ".git"))):
            return _skip("layout")
        if repo_root is None:
            return _skip("layout")
        expected = subprocess.run(
            ("git", "rev-parse", "--path-format=absolute", "--git-common-dir"),
            cwd=str(repo_root), capture_output=True, text=True, timeout=10, check=False, env=env,
        )
        expected_common = (expected.stdout or "").strip()
        if expected.returncode != 0 or not expected_common or Path(expected_common).resolve() != common_dir:
            return _skip("layout")
        if not _real_dir_chain(common_dir, ("objects",), create=False):
            return _skip("symlink")
        if not _real_dir_chain(common_dir, ("refs", "heads", "agent"), create=True):
            return _skip("symlink")
        if not _real_dir_chain(common_dir, ("logs", "refs", "heads", "agent"), create=True):
            return _skip("symlink")
        # git-lfs clean/smudge filters run on `git add`/`checkout` and write `<C>/lfs/{tmp,objects,cache}`;
        # without it a unit in an LFS repository cannot stage anything.
        if not _real_dir_chain(common_dir, ("lfs",), create=True):
            return _skip("symlink")
        # Start-state hygiene: an earlier unit (which held these same binds) may have planted symlinks
        # inside the namespaces or written objects/info/alternates. Any such entry -> no git root.
        # Unreadable subdirectories raise (onerror) -> git_error, never "checked clean".
        def _raise(error: OSError) -> None:
            raise error

        if (common_dir / "objects" / "info" / "alternates").exists() or (common_dir / "objects" / "info" / "alternates").is_symlink():
            return _skip("hygiene")
        for ns_root in (common_dir / "refs" / "heads" / "agent", common_dir / "logs" / "refs" / "heads" / "agent"):
            for dirpath, dirnames, filenames in os.walk(ns_root, followlinks=False, onerror=_raise):
                for entry in (*dirnames, *filenames):
                    full = os.path.join(dirpath, entry)
                    st = os.lstat(full)
                    if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                        return _skip("hygiene")
        for sub in ((), ("info",), ("pack",)):
            target = common_dir.joinpath("objects", *sub)
            if sub and not target.exists():
                continue
            for top in os.scandir(target):
                if top.is_symlink() or not (top.is_dir(follow_symlinks=False) or top.is_file(follow_symlinks=False)):
                    return _skip("hygiene")
        _GIT_ROOTS_LAST_SKIP.pop(key, None)
        return unique_roots((
            common_dir / "worktrees" / wt_name,
            common_dir / "objects",
            common_dir / "refs" / "heads" / "agent",
            common_dir / "logs" / "refs" / "heads" / "agent",
            common_dir / "lfs",
        ))
    except Exception:  # noqa: BLE001 - containment is the point: never let this escape to _unconfined
        return _skip("git_error")


def planned_fanout_filesystem_confinement(
    worktree: Path,
    *,
    owner: str = "",
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Describe a dry-run boundary without claiming the probe ran."""
    selected = backend("auto")
    reason_code = "dry_run_no_confinement_probe"
    if selected == "unsupported":
        reason_code = "no_os_confinement_backend_on_this_platform"
    owner_state_roots = owner_state_directories(owner, {} if environment is None else environment)
    write_roots = unique_roots((worktree, *owner_state_roots))
    write_literals = owner_state_files(owner, {} if environment is None else environment)
    return _receipt(
        status="prepared_not_observed",
        selected=selected,
        worktree=worktree,
        write_roots=write_roots,
        write_literals=write_literals,
        enforced=False,
        reason_code=reason_code,
    )


def prepare_fanout_filesystem_confinement(
    worktree: Path,
    environment: Mapping[str, str],
    commands: Sequence[Sequence[str]],
    *,
    owner: str = "",
    intake_root: Path | None = None,
    unit_branch: str = "",
    repo_root: Path | None = None,
) -> FanoutFilesystemConfinement:
    """Probe one unit's backend before allowing its owner or checks to use it."""
    worktree = worktree.resolve()
    owner_state_roots = owner_state_directories(owner, environment)
    # This exact invocation-owned directory is removed by the dispatcher.
    intake_roots = () if intake_root is None else (intake_root.resolve(),)
    write_roots = unique_roots((worktree, *_git_write_roots(worktree, unit_branch, repo_root), *owner_state_roots, *intake_roots))
    write_literals = owner_state_files(owner, environment)
    selected = backend("auto")
    if selected == "unsupported":
        return _unconfined(
            worktree, selected, environment, "no_os_confinement_backend_on_this_platform",
            write_roots=write_roots, write_literals=write_literals,
        )
    # `backend_available` answers for the platform only. A Linux host with no
    # trusted bwrap on disk has no backend at all, which is not a preflight
    # failure (#1356).
    if not backend_available(selected) or (selected == "bwrap" and trusted_bwrap() is None):
        return _unconfined(
            worktree, selected, environment, "sandbox_backend_unavailable",
            write_roots=write_roots, write_literals=write_literals,
        )
    if not commands:
        return _unconfined(
            worktree, selected, environment, "sandbox_no_runnable_command",
            write_roots=write_roots, write_literals=write_literals,
        )
    executables = _resolve_executables(commands, environment)
    if not executables:
        return _unconfined(
            worktree, selected, environment, "sandbox_executable_not_found",
            write_roots=write_roots, write_literals=write_literals,
        )
    roots = unique_roots(
        (worktree, *(Path(executable).parent for executable in executables.values()), *runtime_roots(selected))
    )
    # `read_roots_are_safe` deliberately does not gate this lane, unlike the
    # strict adapter lane (`cross_harness_adapters._prelaunch_failure`), where
    # narrow read roots are the policy and an unsafe one refuses the launch.
    # Here `command()` passes `allow_broad_file_read=True` unconditionally, and
    # both backends then ignore `roots` for reads -- `(allow file-read*)` on
    # macOS, `--ro-bind / /` on Linux -- so screening `roots` cannot narrow what
    # a dispatched child reads. `roots` feed read rules only; the fence is
    # `write_roots` and `write_literals`. The screen's one remaining effect was
    # therefore inverted: an owner CLI under a `_SENSITIVE_PARTS` directory --
    # `~/.claude/local/claude` is a standard Claude Code install location --
    # returned `unsafe_sandbox_read_root`, and the run lost its write fence
    # while still reading the whole host tree (#1602). The macOS probe keeps its
    # narrow read layout, so such a directory is readable to the probe; it is
    # the directory the same executable is about to run from under broad read.
    if selected in {"sandbox-exec", "bwrap"}:
        scratch_directory = worktree / _FANOUT_TOOLCHAIN_TEMP_DIRECTORY
        scratch_directory.mkdir(parents=True, exist_ok=True)
        gitignore = scratch_directory / ".gitignore"
        if not gitignore.is_file() or gitignore.read_text(encoding="utf-8") != "*\n":
            _ = gitignore.write_text("*\n", encoding="utf-8")
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
    # bwrap's strict layout cannot start a dynamically linked program, so on
    # Linux the preflight and the probe both take the broad-read layout.
    # Only the PROBE matches the real spawn argv: `preflight` takes no write
    # roots or literals, so its command omits every `--bind-try`. That is
    # strictly narrower than the spawn and so cannot over-attest, and the probe
    # -- which is what the receipt attests -- is byte-identical to the command.
    # sandbox-exec keeps its stricter probe policy unchanged.
    linux_layout = selected == "bwrap"
    ready, backend_digest = preflight(
        selected, roots, child, True, environment,
        allow_broad_file_read=linux_layout, inherit_environment=linux_layout,
    )
    if not ready:
        return _unconfined(
            worktree,
            selected,
            environment,
            "sandbox_preflight_failed",
            roots=roots,
            write_roots=write_roots,
            write_literals=write_literals,
            child=child,
            backend_digest=backend_digest,
            executables=executables,
        )
    receipt = _probe(selected, roots, write_roots, write_literals, child, environment, backend_digest)
    return FanoutFilesystemConfinement(
        selected,
        roots,
        write_roots,
        write_literals,
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
        write_roots=(worktree,),
        write_literals=(),
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
    write_roots: tuple[Path, ...] = (),
    write_literals: tuple[Path, ...] = (),
    child: ChildContext | None = None,
    backend_digest: str = "",
    executables: Mapping[str, str] | None = None,
) -> FanoutFilesystemConfinement:
    return FanoutFilesystemConfinement(
        selected,
        roots,
        write_roots,
        write_literals,
        child,
        environment,
        backend_digest,
        {} if executables is None else executables,
        _receipt(
            status="prepared_not_observed",
            selected=selected,
            worktree=worktree,
            write_roots=write_roots,
            write_literals=write_literals,
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
    write_roots: tuple[Path, ...],
    write_literals: tuple[Path, ...],
    child: ChildContext,
    environment: Mapping[str, str],
    backend_digest: str,
) -> dict[str, object]:
    token = uuid4().hex
    inside = child.work / f".omh-confinement-inside-{token}"
    outside = child.work.parent / f".omh-confinement-outside-{token}"
    state_writes = tuple(
        owner_state / f".omh-confinement-state-{token}" for owner_state in write_roots[1:]
    )
    script = (
        'inside_path=$1; outside_path=$2; shift 2; printf inside > "$inside_path"; inside=$?; '
        'state=0; for state_path do printf state > "$state_path"; state_write=$?; '
        'printf "owner_state_exit=%s\\n" "$state_write"; test "$state_write" -eq 0 || state=$state_write; done; '
        'printf outside > "$outside_path"; outside=$?; '
        'printf "inside_exit=%s owner_state_exit=%s outside_exit=%s\\n" "$inside" "$state" "$outside"; '
        'test "$inside" -eq 0 -a "$state" -eq 0 -a "$outside" -ne 0'
    )
    argv = ("/bin/sh", "-c", script, "omh-confinement-probe", str(inside), str(outside), *(str(path) for path in state_writes))
    try:
        completed = subprocess.run(
            sandbox_command(
                argv, selected, roots, child, True, environment, backend_digest,
                write_roots=write_roots, write_literals=write_literals,
                allow_broad_file_read=selected == "bwrap", inherit_environment=selected == "bwrap",
            ),
            cwd=child.work,
            env=environment,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        match = re.search(r"inside_exit=(\d+) owner_state_exit=(\d+) outside_exit=(\d+)", completed.stdout)
        inside_code = int(match.group(1)) if match else None
        state_code = int(match.group(2)) if match and state_writes else None
        state_codes = tuple(
            int(code) for code in cast(list[str], re.findall(r"^owner_state_exit=(\d+)$", completed.stdout, re.MULTILINE))
        )
        outside_code = int(match.group(3)) if match else None
        enforced = (
            completed.returncode == 0
            and inside_code == 0
            and len(state_codes) == len(state_writes)
            and all(code == 0 for code in state_codes)
            and (not state_writes or state_code == 0)
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
                write_roots=write_roots,
                write_literals=write_literals,
                enforced=enforced,
                reason_code="" if enforced else "sandbox_probe_failed",
            ),
            "probe": {
                "status": "observed",
                "command": list(argv),
                "exit_code": completed.returncode,
                "inside_write_exit_code": inside_code,
                "owner_state_write_exit_code": state_code,
                "owner_state_write_exit_codes": list(state_codes),
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
                write_roots=write_roots,
                write_literals=write_literals,
                enforced=False,
                reason_code="sandbox_probe_failed",
            ),
            "probe": {
                "status": "observed",
                "command": list(argv),
                "exit_code": None,
                "inside_write_exit_code": None,
                "owner_state_write_exit_code": None,
                "owner_state_write_exit_codes": [],
                "outside_write_exit_code": None,
                "refusal": str(exc)[:300],
            },
        }
    finally:
        # This is best-effort cleanup, not an unconditional guarantee: a
        # SIGKILL between a sandboxed state write and this block leaves one
        # small marker per state root. `subprocess.run` also kills only the
        # direct sandbox-exec child on timeout, so a blocked grandchild can
        # outlive that timeout.
        inside.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)
        for state_write in state_writes:
            state_write.unlink(missing_ok=True)


def _receipt(
    *,
    status: str,
    selected: str,
    worktree: Path,
    write_roots: Sequence[Path],
    write_literals: Sequence[Path] = (),
    enforced: bool = False,
    reason_code: str = "",
) -> dict[str, object]:
    return {
        "schema_version": FANOUT_FILESYSTEM_CONFINEMENT_SCHEMA_VERSION,
        "status": status,
        "backend": selected,
        "write_root": str(worktree.resolve()),
        "write_roots": [str(root.resolve()) for root in write_roots],
        "write_literals": [str(path.resolve()) for path in write_literals],
        "enforced": enforced,
        "reason_code": reason_code,
        "claim_boundary": FANOUT_FILESYSTEM_CONFINEMENT_CLAIM_BOUNDARY,
    }
