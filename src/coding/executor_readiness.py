from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import os
import re
import shutil
import stat
from hashlib import sha256
import subprocess
from tempfile import TemporaryDirectory
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any

from .fanout_executor_sessions import (
    SESSION_HELP_PROBE_BYTES,
    BinaryIdentity,
    SessionCapability,
    bounded_session_probe,
)

from ..executors import EXECUTOR_PROFILES, executor_label
from ..local_store import atomic_write_json, read_json_object_result, utc_now
from ..paths import OmhPaths, find_project_root
from .pre_handoff_readiness import (
    build_pre_handoff_repair_card,
    evaluate_pre_handoff_readiness,
    readiness_binding,
)


def observe_session_binary(binary: str, *, env: Mapping[str, str] | None = None) -> BinaryIdentity | None:
    """Keep the PATH launch identity while hashing its canonical regular target."""
    resolved = shutil.which(binary, path=None if env is None else env.get('PATH', ''))
    if resolved is None:
        return None
    try:
        path = Path(resolved).resolve(strict=True)
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            budget = 512 * 1024 * 1024
            if not stat.S_ISREG(before.st_mode) or before.st_size > budget:
                return None
            digest = sha256()
            while chunk := stream.read(65536):
                budget -= len(chunk)
                if budget < 0:
                    return None
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                    before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                return None
        return BinaryIdentity(str(path), digest.hexdigest(), os.path.abspath(resolved))
    except OSError:
        return None


class PinnedSessionBinaryError(RuntimeError):
    pass


def _copy_windows_launcher_closure(launcher: Path, mirror: Path) -> None:
    try:
        text = launcher.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise PinnedSessionBinaryError("executor launcher closure is unavailable") from exc
    packages: set[tuple[str, ...]] = set()
    for match in re.finditer(r'%(?:~dp0|dp0%)[\\/]*([^"\r\n%]+)', text, re.IGNORECASE):
        parts = PureWindowsPath(match[1]).parts
        try:
            node_modules_index = tuple(part.lower() for part in parts).index("node_modules")
        except ValueError:
            continue
        if node_modules_index + 1 >= len(parts):
            continue
        package_end = node_modules_index + (3 if parts[node_modules_index + 1].startswith("@") else 2)
        if package_end <= len(parts) and ".." not in parts[:package_end]:
            packages.add(tuple(parts[:package_end]))
    for parts in packages:
        source = launcher.parent.joinpath(*parts)
        destinations = [(source, mirror.joinpath(*parts))]
        if source.parent.name.startswith("@"):
            destinations.extend(
                (sibling, mirror.joinpath(*parts[:-1], sibling.name))
                for sibling in source.parent.iterdir()
                if sibling.is_dir() and sibling.name.startswith(source.name + "-")
            )
        for package_source, destination in destinations:
            if package_source.is_dir() and not destination.exists():
                shutil.copytree(package_source, destination, symlinks=False)


@contextmanager
def pinned_session_binary(identity: BinaryIdentity):
    """Yield an immutable executable copy whose bytes match the recorded identity."""
    launch_path = Path(identity.launch_path)
    try:
        descriptor = os.open(launch_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as source, TemporaryDirectory(
            prefix="omh-executor-"
        ) as temporary:
            observed = os.fstat(source.fileno())
            canonical = os.stat(identity.resolved_path)
            if (
                not stat.S_ISREG(observed.st_mode)
                or (observed.st_dev, observed.st_ino) != (canonical.st_dev, canonical.st_ino)
            ):
                raise PinnedSessionBinaryError("executor binary identity changed before spawn")
            prefix = source.read(2)
            source.seek(0)
            canonical_path = Path(identity.resolved_path)
            if os.name == "nt":
                package_mirror = Path(temporary)
                mirror = package_mirror / canonical_path.parent.name
                mirror.mkdir(mode=0o700)
                for sibling in canonical_path.parent.iterdir():
                    if sibling != canonical_path and sibling.is_file():
                        shutil.copy2(sibling, mirror / sibling.name)
                _copy_windows_launcher_closure(canonical_path, mirror)
            else:
                package_source = canonical_path.parent.parent
                if package_source == Path(package_source.anchor):
                    package_source = canonical_path.parent
                package_mirror = Path(temporary) / package_source.name
                mirror = package_mirror / canonical_path.parent.name
                mirror.mkdir(parents=True, mode=0o700)
                for sibling in package_source.iterdir():
                    if sibling != canonical_path.parent:
                        (package_mirror / sibling.name).symlink_to(
                            sibling,
                            target_is_directory=sibling.is_dir(),
                        )
                if prefix == b"#!":
                    for sibling in canonical_path.parent.iterdir():
                        if sibling == canonical_path:
                            continue
                        (mirror / sibling.name).symlink_to(
                            sibling,
                            target_is_directory=sibling.is_dir(),
                        )
            artifact = mirror / canonical_path.name
            node_modules = next(
                (parent for parent in canonical_path.parents if parent.name == "node_modules"),
                None,
            )
            if node_modules is not None and not (Path(temporary) / "node_modules").exists():
                (Path(temporary) / "node_modules").symlink_to(
                    node_modules,
                    target_is_directory=True,
                )
            protected_directories = (mirror, package_mirror, Path(temporary))
            digest = sha256()
            artifact_descriptor: int | None = None
            try:
                with artifact.open("xb") as destination:
                    while chunk := source.read(65536):
                        digest.update(chunk)
                        destination.write(chunk)
                    destination.flush()
                    os.fsync(destination.fileno())
                artifact.chmod(observed.st_mode & 0o555)
                for directory in protected_directories:
                    directory.chmod(0o555)
                if digest.hexdigest() != identity.sha256:
                    raise PinnedSessionBinaryError("executor binary identity changed before spawn")
                artifact_descriptor = os.open(artifact, os.O_RDONLY)
                yield str(artifact)
            finally:
                if artifact_descriptor is not None:
                    os.close(artifact_descriptor)
                for directory in reversed(protected_directories):
                    directory.chmod(0o700)
                if artifact.exists():
                    artifact.chmod(0o700)
                artifact.unlink(missing_ok=True)
    except OSError as exc:
        raise PinnedSessionBinaryError("executor binary identity changed before spawn") from exc


def negotiate_session_capability(owner: str, binary: str, *, env: Mapping[str, str]) -> SessionCapability | None:
    """Help/version negotiation only; never a provider request or release-floor guess."""
    identity = observe_session_binary(binary, env=env)
    if identity is None:
        return None
    capability = SessionCapability(owner, None, identity, None)
    if owner not in ('codex', 'claude-code'):
        return capability
    launch_path = identity.launch_path or identity.resolved_path
    try:
        with pinned_session_binary(identity) as executable:
            version_bytes, version_reason = bounded_session_probe(
                [launch_path, '--version'], env=env, executable=executable
            )
            help_args = ['exec', '--help'] if owner == 'codex' else ['--help']
            # The help probe reads a document, so it gets a document-sized budget and
            # keeps what it read when even that was not enough: finding every flag in
            # the part that was read settles the question, and only a flag MISSING
            # from a truncated read is ambiguous. Before this, a help page that
            # outgrew the shared 16 KiB cap silently switched the whole lane off.
            help_bytes, help_reason = bounded_session_probe(
                [launch_path, *help_args],
                env=env,
                limit_bytes=SESSION_HELP_PROBE_BYTES,
                keep_partial=True,
                executable=executable,
            )
    except PinnedSessionBinaryError:
        return replace(capability, reason='binary_changed_during_probe')
    if version_bytes is None:
        return replace(capability, reason=f'version_probe_{version_reason}')
    if help_bytes is None:
        return replace(capability, reason=f'help_probe_{help_reason}')
    try:
        version, help_text = version_bytes.decode('utf-8').strip(), help_bytes.decode('utf-8')
    except UnicodeError:
        return replace(capability, reason='probe_output_not_utf8')
    # Retain only the version token, never arbitrary help/version output.
    match = re.fullmatch(r'(?:[A-Za-z][A-Za-z0-9_. -]{0,64}\s+)?([0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9.-]+)?)(?: \(Claude Code\))?', version, re.IGNORECASE)
    if match is None:
        return replace(capability, reason='version_output_unrecognized')
    flags = ('--json', 'resume') if owner == 'codex' else ('--output-format', 'stream-json', '--verbose', '--resume')
    absent = [flag for flag in flags
              if not re.search(r'(?<![\w-])' + re.escape(flag) + r'(?![\w-])', help_text)]
    if absent:
        # A flag missing from a help page that was cut off is unanswered, not
        # answered "no" -- both refuse the protocol, and the reason says which
        # so an operator knows whether to raise the budget or to update the CLI.
        detail = 'help_truncated' if help_reason == 'probe_output_limited' else 'help_complete'
        return replace(capability, reason=f'flags_absent[{detail}]:' + ','.join(absent))
    return SessionCapability(
        owner,
        'codex_exec_json' if owner == 'codex' else 'claude_stream_json',
        identity,
        match[1],
    )


EXECUTOR_READINESS_SCHEMA_VERSION = "executor_readiness/v1"
EXECUTOR_READINESS_PROFILES = EXECUTOR_PROFILES
_PROBE_TIMEOUT_SECONDS = 3

# How many PATH resolutions of one command get their version observed. Users
# update codex and claude on their own cadence and by more than one installer
# (npm, standalone, brew), so several binaries of different versions routinely
# coexist; two or three is the realistic ceiling worth the subprocess cost.
_MAX_OBSERVED_RESOLUTIONS = 3

# OMH pins no executor version, ever -- a guard test rejects any version
# literal in this module, including comments. The observed failure that
# motivates the shadow report was not "the version was wrong": `shutil.which`
# returns only the FIRST match, so a stale npm codex probed "ready" while the
# newer standalone the auth session actually required sat one PATH entry
# later, invisible. Version requirements belong to the executor CLI's own
# output at run time; OMH's job is to observe every resolution and say when
# the one that will run is not the only one installed.
EXECUTOR_VERSION_POLICY = (
    "OMH pins no executor CLI version. Version requirements come from the executor's own "
    "output at run time; the probe reports every PATH resolution it observed so a stale "
    "binary shadowing a newer install is visible instead of silently selected."
)

# What this probe actually observed, stated as a value so no reader has to
# infer it from the absence of anything else. The probe runs one command and
# reads its version line; it has no worktree, touches no repository, and
# therefore cannot answer whether the work can be done anywhere.
READINESS_OBSERVED_BINARY_VERSION_ONLY = "binary_version_only"

# Appended to a ready summary. The workspace question is not left unanswered --
# it is answered LATER, by `workspace_preflight` running in the unit's own
# isolation immediately before the spawn, which is the only place a worktree
# exists to probe.
READINESS_WORKSPACE_PROBE_NOTE = (
    "Binary runs; workspace not yet probed — the dispatch runs `workspace_preflight` in the unit's "
    "isolation before spawning."
)

READINESS_BINARY_ONLY_CLAIM_BOUNDARY = (
    "`available: true` means one command was run and it exited 0. It is not a claim that the work "
    "can be done: file writes, git index writes, the presence of the commits the work needs, and "
    "case-collision safety are properties of the unit's isolation, which this probe never sees. "
    "The dispatch observes those four with `workspace_preflight` before it spawns anything. "
    "Readiness is not dispatch, execution, verification, review, CI, or merge evidence."
)
_COMMANDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "codex": ("codex", ("--version",)),
    "claude-code": ("claude", ("--version",)),
    "omx-runtime": ("omx", ("--version",)),
    # omo ships as an extension of a host agent CLI, not as its own binary.
    # This static entry is NEVER read for omo-runtime: `_resolved_command`
    # always overrides it with the DETECTED host (`omo_runtime_host` in
    # fanout_dispatch — pi first, then its senpi distribution, then the
    # opencode plugin host). The entry mirrors OMO_RUNTIME_HOST_CANDIDATES[0]
    # so a future second consumer of this table sees the same pi-first
    # default the detector promises — do not repin it to one distribution.
    # No host on PATH probes the first candidate and truthfully reads
    # `missing`; the runtime prompt-handoff path never needed a local CLI.
    "omo-runtime": ("pi", ("--version",)),
    "omc-runtime": ("omc", ("--version",)),
}


def executor_readiness_contract(profile: str | None) -> dict[str, object]:
    normalized = _normalize_profile(profile)
    return _copy_executor_readiness_payload(_executor_readiness_contract_cached(normalized))


@lru_cache(maxsize=16)
def _executor_readiness_contract_cached(normalized: str) -> dict[str, object]:
    if normalized == "choose":
        return {
            "schema_version": EXECUTOR_READINESS_SCHEMA_VERSION,
            "profile": "choose",
            "status": "choice_required",
            "first_use_only": True,
            "cache_key": "executor_readiness:choose",
            "next_action": "choose_executor_before_probe",
            "fallback_policy": {
                "when_missing": "ask_user_to_choose_executor_or_configure_one",
                "retry_after_state_change": True,
                "retry_limit": 1,
            },
            "claim_boundary": "Executor readiness is not dispatch, execution, verification, review, CI, or merge evidence.",
        }
    command, args = _resolved_command(normalized) or ("", ())
    probe_kind = "local_command" if command else "wrapper_observed_profile"
    return {
        "schema_version": EXECUTOR_READINESS_SCHEMA_VERSION,
        "profile": normalized,
        "label": executor_label(normalized),
        "status": "not_observed",
        "first_use_only": True,
        "cache_key": f"executor_readiness:{normalized}",
        "probe": {
            "kind": probe_kind,
            "command": command,
            "args": list(args),
            "timeout_seconds": _PROBE_TIMEOUT_SECONDS if command else 0,
            "captures": ["available", "exit_code", "summary"],
        },
        "ready_action": _ready_action(normalized),
        "fallback_policy": {
            "when_missing": "ask_user_to_choose_executor_or_configure_one",
            "retry_after_state_change": True,
            "retry_limit": 1,
            "suggested_actions": [
                "choose_executor",
                "show_prompt_handoff",
                "show_runtime_handoff",
                "continue_in_hermes",
            ],
        },
        "not_evidence": [
            "executor dispatch",
            "executor result",
            "execution",
            "implementation",
            "verification",
            "review",
            "CI",
            "merge",
        ],
        "claim_boundary": "Readiness is not dispatch, execution, verification, review, CI, or merge evidence; it only checks whether the selected executor path appears available.",
    }


def _copy_executor_readiness_payload(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    probe = copied.get("probe")
    if isinstance(probe, dict):
        copied_probe = dict(probe)
        copied_probe["args"] = _copy_list(probe.get("args", []))
        copied_probe["captures"] = _copy_list(probe.get("captures", []))
        copied["probe"] = copied_probe
    fallback_policy = copied.get("fallback_policy")
    if isinstance(fallback_policy, dict):
        copied_policy = dict(fallback_policy)
        if "suggested_actions" in copied_policy:
            copied_policy["suggested_actions"] = _copy_list(copied_policy.get("suggested_actions", []))
        copied["fallback_policy"] = copied_policy
    if "not_evidence" in copied:
        copied["not_evidence"] = _copy_list(copied.get("not_evidence", []))
    profiles = copied.get("profiles")
    if isinstance(profiles, list):
        copied["profiles"] = [
            _copy_executor_readiness_payload(profile)
            for profile in profiles
            if isinstance(profile, dict)
        ]
    return copied


def executor_readiness_for_selection(
    selected_profile: str | None,
    *,
    choice_required: bool,
) -> dict[str, object]:
    if choice_required or not selected_profile:
        payload = executor_readiness_contract("choose")
        payload["profiles"] = [executor_readiness_contract(profile) for profile in EXECUTOR_READINESS_PROFILES]
        return payload
    return executor_readiness_contract(selected_profile)


def with_executor_readiness_options(options: list[dict[str, object]]) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for option in options:
        profile = str(option.get("profile", ""))
        updated = dict(option)
        updated["readiness_probe"] = executor_readiness_contract(profile)
        enriched.append(updated)
    return enriched


def probe_executor_readiness(
    paths: OmhPaths,
    profile: str,
    *,
    force: bool = False,
    dry_run: bool = False,
    now: str = "",
) -> dict[str, object]:
    """Readiness for one profile, rechecked against the machine it was observed on.

    A cached decision is reused only while it is still fresh AND still bound to
    the same profile, tool, permission profile, and workspace. When it is not,
    the cached decision is NOT silently re-probed: this call reports the exact
    gap and a repair card, and `force=True` stays the only way to replace the
    stored observation. Re-probing on staleness would hide a missing tool
    behind a subprocess run nobody asked for, which is the same surprise #837
    exists to remove --- only later in the handoff.
    """
    normalized = _normalize_profile(profile)
    if normalized == "choose":
        return executor_readiness_contract("choose")
    contract = executor_readiness_contract(normalized)
    state, state_error = _read_state(paths)
    cached = _cached_profile(state, normalized)
    if cached and not force:
        verdict = evaluate_pre_handoff_readiness(
            profile=normalized,
            cached=cached,
            binding=live_readiness_binding(paths, normalized),
            capability_snapshot=_capability_snapshot(paths, normalized),
            now=now,
        )
        result = dict(cached)
        result["pre_handoff_readiness"] = verdict
        # A cached command probe keeps the boundary that describes what it
        # observed. Replacing it with the generic contract sentence would put
        # the "binary runs; the workspace was never probed" qualification back
        # out of reach of exactly the readers who read a cached `ready`.
        result["claim_boundary"] = (
            READINESS_BINARY_ONLY_CLAIM_BOUNDARY
            if result.get("observed") == READINESS_OBSERVED_BINARY_VERSION_ONLY
            else contract["claim_boundary"]
        )
        if verdict["usable"]:
            result["cache_status"] = "cached"
            result["first_use_skipped"] = True
        else:
            # Never `ready`: a decision that no longer describes this machine
            # is not weaker evidence of readiness, it is none.
            result["cache_status"] = "invalidated"
            result["first_use_skipped"] = False
            result["status"] = "stale"
            result["available"] = False
            result["summary"] = str(verdict["reason"])
            result["next_action"] = "repair_prerequisite_then_force_readiness_probe"
            result["repair_card"] = build_pre_handoff_repair_card(
                verdict,
                repair_command=_repair_command(normalized),
            )
        return _with_advisory_signals(paths, normalized, result)
    if dry_run:
        result = dict(contract)
        result.update(
            {
                "status": "not_observed",
                "cache_status": "would_probe",
                "first_use_skipped": False,
                "state_error": state_error or "",
            }
        )
        return _with_advisory_signals(paths, normalized, result)
    result = _run_probe(contract)
    _write_state(paths, state, normalized, result)
    return _with_advisory_signals(paths, normalized, result)


def live_readiness_binding(
    paths: OmhPaths,
    profile: str,
    *,
    workspace_ref: str | None = None,
) -> dict[str, object]:
    """The current value of every input whose change invalidates readiness.

    Four axes, each read from where that input actually lives:

    * `profile` --- the profile's own identity and what a ready result would
      let a wrapper do, so renaming a profile or changing its ready action
      cannot silently reuse an observation made under the old definition.
    * `tool` --- the command the probe would run and every PATH resolution of
      it, so an uninstall, a reinstall somewhere else, or a newer binary
      appearing ahead of the observed one all register.
    * `permission` --- the safety profile revision, the same content hash
      `fanout_dispatch` already rechecks before it spawns anything.
    * `workspace` --- the repository this readiness was observed in, because a
      per-user readiness cache is shared across every checkout on the machine.

    Local reads only: no subprocess, no network. `workspace_ref` is injectable
    so a caller (and a test) can bind readiness to a workspace other than the
    process working directory.
    """
    from ..quality.safety_preflight import safety_profile_revision

    command, args = _resolved_command(profile) or ("", ())
    probe_kind = "local_command" if command else "wrapper_observed_profile"
    return readiness_binding(
        profile=profile,
        profile_revision="\x1e".join((executor_label(profile), _ready_action(profile), probe_kind)),
        tool_paths=(command, *args, *_path_resolutions(command)) if command else (),
        permission_revision=safety_profile_revision(),
        workspace_ref=workspace_ref if workspace_ref is not None else _workspace_ref(paths),
    )


def _workspace_ref(paths: OmhPaths) -> str:
    """The workspace a readiness observation belongs to.

    The repository root when there is one, so a readiness decision made in one
    checkout is not reused in another; the store home otherwise, which is the
    only workspace identity a run outside a repository has.
    """
    root = find_project_root()
    return str(root) if root is not None else str(paths.omh_home)


def _capability_snapshot(paths: OmhPaths, profile: str) -> dict[str, object] | None:
    """The recorded capability snapshot for this profile, if one exists.

    Absent is not the same as prepared-only here: with no snapshot on disk
    there is no capability claim riding the handoff, so readiness stands on its
    own probe evidence. A snapshot that IS present is re-checked at dispatch
    time --- prepared-only or expired evidence cannot support a ready result.
    """
    from .executor_capability_snapshots import (
        executor_capability_snapshot_path,
        read_matching_executor_capability_snapshot,
    )

    try:
        path = executor_capability_snapshot_path(paths.executor_capability_snapshots_dir, profile)
    except ValueError:
        return None
    return read_matching_executor_capability_snapshot(path, expected_executor=profile)


def _repair_command(profile: str) -> str:
    """The owner-specific command that confirms the missing prerequisite.

    Executor-specific value inside an executor-neutral card: a probeable
    profile confirms its own CLI, and a wrapper-observed profile has no CLI to
    confirm, so it gets the local check that covers it instead.
    """
    command, args = _resolved_command(profile) or ("", ())
    if not command:
        return "omh doctor"
    return " ".join((command, *args))


def _with_advisory_signals(paths: OmhPaths, profile: str, result: dict[str, object]) -> dict[str, object]:
    """Attach live advisory markers outside the observed_once cache.

    Login and limit markers change whenever the user logs in/out or a dispatch
    hits a provider limit, so they are recomputed on every call and never
    persisted with the cached probe (which would freeze them at first use).

    `last_auth_failure_signal` is the third, and the only one of the three that
    can currently refuse a spawn (see `dispatch_failure_recovery.spawn_cooldown`).
    It is surfaced here because an operator whose unit came back
    `executor_auth_invalid` should be able to read WHY from the readiness
    surface, rather than only from the dispatch summary that refused them.
    """
    from .dispatch_failure_recovery import last_auth_failure_signal
    from .executor_auth_signals import auth_signal_for_profile, last_limit_signal_for_profile

    result["auth_signal"] = auth_signal_for_profile(profile)
    result["last_limit_signal"] = last_limit_signal_for_profile(paths, profile)
    result["last_auth_failure_signal"] = last_auth_failure_signal(paths, profile)
    return result


def _path_resolutions(command: str) -> list[str]:
    """Every distinct binary this command resolves to, in PATH order.

    `shutil.which` answers "what will run"; this answers "what else could".
    Deduplicated by real path so a symlink chain to the same binary does not
    read as a conflict.
    """
    resolutions: list[str] = []
    seen: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / command
        try:
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            real = str(candidate.resolve())
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        resolutions.append(str(candidate))
    return resolutions


def _observed_version(binary: str, args: list[str]) -> str:
    """The binary's own version line, or the failure it printed instead."""
    try:
        completed = subprocess.run(
            [binary, *args],
            text=True,
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"probe failed: {exc}"[:200]
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0][:200] if output else f"exited with {completed.returncode}"


def _resolution_report(command: str, args: list[str]) -> list[dict[str, str]]:
    """One row per distinct PATH resolution, each with its observed version."""
    return [
        {"path": path, "observed_version": _observed_version(path, args)}
        for path in _path_resolutions(command)[:_MAX_OBSERVED_RESOLUTIONS]
    ]


def _resolved_command(profile: str) -> tuple[str, tuple[str, ...]] | None:
    entry = _COMMANDS.get(profile)
    if profile == "omo-runtime":
        from .fanout_dispatch import OMO_RUNTIME_HOST_CANDIDATES, omo_runtime_host

        host = omo_runtime_host()
        return ((host, ("--version",)) if host else (OMO_RUNTIME_HOST_CANDIDATES[0], ("--version",)))
    return entry


def _run_probe(contract: dict[str, object]) -> dict[str, object]:
    result = dict(contract)
    probe = result.get("probe")
    if not isinstance(probe, dict):
        result.update({"status": "not_applicable", "available": False, "observed_once": True})
        return result
    command = str(probe.get("command", ""))
    args = [str(arg) for arg in probe.get("args", [])] if isinstance(probe.get("args"), list) else []
    if not command:
        result.update(
            {
                "status": "not_applicable",
                "available": False,
                "observed_once": True,
                "summary": "This executor profile is wrapper-observed rather than command-probed.",
                "next_action": "ask_wrapper_to_confirm_profile",
            }
        )
        return result
    resolved = shutil.which(command)
    if not resolved:
        result.update(
            {
                "status": "missing",
                "available": False,
                "observed": READINESS_OBSERVED_BINARY_VERSION_ONLY,
                "observed_once": True,
                "summary": f"`{command}` was not found on PATH.",
                "next_action": "choose_executor_or_configure_path",
            }
        )
        return result
    try:
        completed = subprocess.run(
            [resolved, *args],
            text=True,
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.update(
            {
                "status": "blocked",
                "available": False,
                "observed": READINESS_OBSERVED_BINARY_VERSION_ONLY,
                "observed_once": True,
                "summary": str(exc),
                "next_action": "choose_executor_or_configure_path",
            }
        )
        return result
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    summary = output[0][:200] if output else f"`{command}` exited with {completed.returncode}."
    resolutions = _resolution_report(command, args)
    versions = {row["observed_version"] for row in resolutions}
    shadowed = len(resolutions) > 1 and len(versions) > 1
    if shadowed:
        others = "; ".join(
            f"{row['path']} ({row['observed_version']})" for row in resolutions[1:]
        )
        summary = f"{summary} — PATH also resolves: {others}"[:400]
    if completed.returncode == 0:
        # `available: true` used to be read as "this executor can do the work".
        # It never meant that, and on 2026-09-11 the gap cost 36 minutes: the
        # binary ran, and the isolation it was pointed at could not take a git
        # index write. The sentence is appended to the summary rather than kept
        # only in a field because the summary is what a person reads.
        summary = f"{summary} {READINESS_WORKSPACE_PROBE_NOTE}"[:600]
    result.update(
        {
            "status": "ready" if completed.returncode == 0 else "blocked",
            "available": completed.returncode == 0,
            "observed": READINESS_OBSERVED_BINARY_VERSION_ONLY,
            "claim_boundary": READINESS_BINARY_ONLY_CLAIM_BOUNDARY,
            "observed_once": True,
            "exit_code": completed.returncode,
            "command_path": resolved,
            "path_resolutions": resolutions,
            # Shadowed means: more than one distinct binary, with differing
            # observed versions. The first is what will run and status reflects
            # it honestly; the flag exists so a stale binary hiding a newer
            # install is a stated fact, not a mid-dispatch surprise.
            "shadowed": shadowed,
            "version_policy": EXECUTOR_VERSION_POLICY,
            "summary": summary,
            "next_action": _ready_action(str(result.get("profile", ""))) if completed.returncode == 0 else "choose_executor_or_configure_path",
        }
    )
    return result


# CLI-backed candidates for the choose-executor question: profiles with a
# locally probeable agent CLI. omo-runtime joined when the senpi host CLI
# gained a validated dispatch template — the choice card should offer every
# surface the user can actually run.
EXECUTOR_CHOICE_CONTEXT_PROFILES = ("codex", "claude-code", "omo-runtime")
EXECUTOR_CHOICE_CONTEXT_CLAIM_BOUNDARY = (
    "Choice context ranks locally-installed executor candidates from cached readiness and local "
    "markers only. It is not provider quota, entitlement, or login truth, and it never removes a "
    "candidate the user may still pick."
)


def executor_choice_context(
    paths: OmhPaths,
    *,
    now: str = "",
    plan: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return per-candidate readiness/auth context for the choose-executor question.

    Reads cached readiness state and cheap local markers only — no subprocess
    runs — so wrapper cards can embed it as deterministic data. The model
    inventory hint rides along so Hermes answers the choice from what the user
    actually has instead of asking blind; the full report stays behind
    `omh coding model-inventory`.

    Each candidate's stored readiness goes through the same freshness rule the
    probe applies (#837), so a decision that no longer describes this machine
    reads `stale` here too. Ranking a candidate whose CLI is gone to the top of
    the choose-executor card is the failure that rule exists to prevent.

    `plan` is the accepted plan's declared fields (#810). When one is supplied,
    each candidate also carries its owner-fit verdict and the required
    capabilities recorded unavailable for it, and fit becomes the FIRST ranking
    key — an owner that cannot do the work must never head this card, whatever
    its login marker says. Candidates are still never removed: the card offers
    what the user may pick, and the verdict says what each pick would cost.
    """
    from .executor_auth_signals import auth_signal_for_profile, last_limit_signal_for_profile
    from .model_inventory import local_model_inventory
    from .owner_fit import derive_plan_capability_requirements, evaluate_owner_fit

    requirements = derive_plan_capability_requirements(plan) if plan is not None else None
    state, _ = _read_state(paths)
    candidates: list[dict[str, object]] = []
    for profile in EXECUTOR_CHOICE_CONTEXT_PROFILES:
        cached = _cached_profile(state, profile) or {}
        snapshot = _capability_snapshot(paths, profile)
        # Same freshness rule as the probe: a stale or rebound decision must
        # not read `ready` here either, or the ranking would put a candidate
        # whose CLI is gone at the top of the choose-executor card.
        verdict = evaluate_pre_handoff_readiness(
            profile=profile,
            cached=cached or None,
            binding=live_readiness_binding(paths, profile),
            capability_snapshot=snapshot,
            now=now,
        )
        observed_status = str(cached.get("status", "not_observed"))
        candidate: dict[str, object] = {
            "profile": profile,
            "label": executor_label(profile),
            "readiness_status": observed_status if (verdict["usable"] or not cached) else "stale",
            "readiness_freshness": str(verdict["reason_code"]),
            "auth_signal": auth_signal_for_profile(profile),
            "last_limit_signal": last_limit_signal_for_profile(paths, profile),
        }
        if requirements is not None:
            # The same snapshot the freshness rule just read, so readiness and
            # fit cannot describe different evidence for one candidate.
            fit = evaluate_owner_fit(
                owner=profile,
                requirements=requirements,
                capability_snapshot=snapshot,
                now=now,
            )
            candidate["owner_fit_verdict"] = str(fit["verdict"])
            candidate["owner_fit_unmet"] = list(fit["unmet"])
            candidate["owner_fit_unknown"] = list(fit["unknown"])
        candidates.append(candidate)
    # Advisory ranking, never a veto: owner fit first when a plan says what the
    # work needs, then logged-in, then no fresh limit signal, then cached-ready,
    # with the fixed profile order as tiebreak so equal candidates stay
    # deterministic.
    candidates.sort(key=_choice_context_rank)
    inventory = local_model_inventory()
    return {
        "candidates": candidates,
        "ranked_by": (
            ("owner_fit_verdict", "login_marker", "fresh_limit_signal_absent", "readiness_status")
            if requirements is not None
            else ("login_marker", "fresh_limit_signal_absent", "readiness_status")
        ),
        "model_inventory_hint": {
            "families_present": inventory.get("families_present", []),
            "model_count": len(inventory.get("available_models", [])),
            "full_report_command": "omh coding model-inventory",
            "claim_boundary": str(inventory.get("claim_boundary", "")),
        },
        "claim_boundary": EXECUTOR_CHOICE_CONTEXT_CLAIM_BOUNDARY,
    }


# Absent means "no plan said what this work needs", which must leave the
# pre-#810 ordering exactly as it was rather than sort by a verdict nobody
# derived.
_OWNER_FIT_RANKS: dict[str, int] = {"ready": 0, "unproven": 1, "blocked": 2}


def _choice_context_rank(candidate: dict[str, object]) -> tuple[int, int, int, int, int]:
    auth = candidate.get("auth_signal")
    login = str(auth.get("login_marker", "")) if isinstance(auth, dict) else ""
    limit = candidate.get("last_limit_signal")
    fresh_limit = isinstance(limit, dict) and bool(limit) and not limit.get("stale", False)
    ready = str(candidate.get("readiness_status", "")) == "ready"
    fit = _OWNER_FIT_RANKS.get(str(candidate.get("owner_fit_verdict", "")), 0)
    original = EXECUTOR_CHOICE_CONTEXT_PROFILES.index(str(candidate.get("profile", "")))
    return (fit, 0 if login == "present" else 1, 1 if fresh_limit else 0, 0 if ready else 1, original)


def _ready_action(profile: str) -> str:
    if profile == "codex":
        return "send_to_executor"
    if profile == "claude-code":
        return "show_prompt_handoff"
    if profile in {"omx-runtime", "omo-runtime", "omc-runtime", "hermes"}:
        return "show_runtime_handoff"
    return "show_prompt_handoff"


def _normalize_profile(profile: str | None) -> str:
    value = str(profile or "choose").strip()
    if value == "choose":
        return value
    if value not in EXECUTOR_READINESS_PROFILES:
        raise ValueError(f"unsupported executor readiness profile: {value}")
    return value


def _copy_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(value)


def _read_state(paths: OmhPaths) -> tuple[dict[str, Any], str]:
    state, error = read_json_object_result(paths.executor_readiness_path)
    return state or {"schema_version": "executor_readiness_cache/v1", "profiles": {}}, error or ""


def _cached_profile(state: dict[str, Any], profile: str) -> dict[str, object] | None:
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        return None
    cached = profiles.get(profile)
    if not isinstance(cached, dict):
        return None
    if cached.get("observed_once") is True:
        return {str(key): value for key, value in cached.items()}
    return None


def _write_state(paths: OmhPaths, state: dict[str, Any], profile: str, result: dict[str, object]) -> None:
    profiles = state.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    stored = dict(result)
    # Advisory markers are recomputed per call; persisting them would freeze
    # login/limit state at first probe (see _with_advisory_signals).
    stored.pop("auth_signal", None)
    stored.pop("last_limit_signal", None)
    stored.pop("last_auth_failure_signal", None)
    # The binding is what makes `updated_at` readable later: without it a
    # stored decision can only be aged, never checked against the machine it
    # described. It carries no timestamp of its own, deliberately -- it is
    # compared for equality, and a clock inside a compared payload turns that
    # comparison into a race.
    stored["readiness_binding"] = live_readiness_binding(paths, profile)
    stored["updated_at"] = utc_now()
    profiles[profile] = stored
    state.update(
        {
            "schema_version": "executor_readiness_cache/v1",
            "updated_at": stored["updated_at"],
            "profiles": profiles,
        }
    )
    atomic_write_json(paths.executor_readiness_path, state, private=True)
