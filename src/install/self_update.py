"""Staged command-package updates; subprocess execution stays in this module."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, Literal, NotRequired, Protocol, TypedDict

try:
    from ..core.errors import OmhError
    from ..maintenance.build_identity import read_archive_commit
    from ..maintenance.hermes_gateway import recorded_gateway_starts, refresh_skill_dir_caches
    from ..system.local_store import FileLockTimeout, file_lock
    from ..system.paths import managed_command_venv_dir, resolve_paths
    from .self_update_platform import SelfUpdatePlatform
    from .self_update_state import CleanupResult, GenerationEntry, collect_garbage, commit_activation, generation_entry, interrupted_activation, load_state, mark_activation, mark_switched, migrate_legacy, pointer_target, record_pointer, recovery_target, restore_known_good, save_state, state_path, switch_current
    from .self_update_state_validation import require_generation_path, same_existing_path
except ImportError:  # pragma: no cover - direct-source installer smoke.
    from core.errors import OmhError
    from maintenance.build_identity import read_archive_commit
    from maintenance.hermes_gateway import recorded_gateway_starts, refresh_skill_dir_caches
    from system.local_store import FileLockTimeout, file_lock
    from system.paths import managed_command_venv_dir, resolve_paths
    from install.self_update_platform import SelfUpdatePlatform
    from install.self_update_state import CleanupResult, GenerationEntry, collect_garbage, commit_activation, generation_entry, interrupted_activation, load_state, mark_activation, mark_switched, migrate_legacy, pointer_target, record_pointer, recovery_target, restore_known_good, save_state, state_path, switch_current
    from install.self_update_state_validation import require_generation_path, same_existing_path

RESULT_SCHEMA_VERSION = "command_package_self_update/v1"
IDENTITY_CHANGE_SCHEMA_VERSION = "update_identity_change/v1"
REENTRY_TIMEOUT_SECONDS = 600.0
# `omh update` exits with this when its own home refreshed and only a bot
# profile failed. The activated generation runs; rolling it back cannot repair
# a profile (the previous generation fails on the same profile), so a staged
# update keeps the generation and reports the profiles instead. On 2026-11-04
# four bench profiles whose `plugins/omh` links pointed at deleted worktrees
# rolled an update back, and the restore failed the same way on every later run.
PROFILE_REPAIR_EXIT_CODE = 3
class Runner(Protocol):
    """The complete subprocess contract used by a staged self-update."""

    def __call__(
        self,
        command: list[str],
        /,
        *,
        text: Literal[True],
        stdout: int | None,
        stderr: int | None,
        env: dict[str, str] | None,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]: ...



class PhaseStatus(TypedDict):
    status: str


class PhaseResult(PhaseStatus, total=False):
    reason: str
    pointer: str
    launcher: str
    profiles_need_repair: bool


class RollbackFields(TypedDict, total=False):
    status: str
    reason: str


class RollbackResult(RollbackFields):
    performed: bool
    restored: str


class RecoveryResult(TypedDict, total=False):
    status: str
    action: str
    selected: str
    reason: str


class SelfUpdateResult(TypedDict):
    schema_version: str
    ok: bool
    phase: str
    candidate: GenerationEntry
    staging: PhaseResult
    verification: PhaseResult
    migration: PhaseResult
    activation: PhaseResult
    post_activation: PhaseResult
    rollback: RollbackResult
    recovery: RecoveryResult
    cleanup: CleanupResult
    hermes_skill_refresh: NotRequired[list[dict[str, str]]]
    identity_change: NotRequired["IdentityChange"]


class GenerationIdentity(TypedDict):
    version: str
    ref: str
    commit_sha: str


class IdentityChange(TypedDict):
    schema_version: str
    status: str
    previous: GenerationIdentity
    current: GenerationIdentity
    version_changed: bool


def _result(candidate: Path) -> SelfUpdateResult:
    entry = generation_entry(candidate)
    return {"schema_version": RESULT_SCHEMA_VERSION, "ok": False, "phase": "lock", "candidate": entry, "staging": {"status": "skipped"}, "verification": {"status": "skipped"}, "migration": {"status": "skipped"}, "activation": {"status": "skipped"}, "post_activation": {"status": "skipped"}, "rollback": {"performed": False, "restored": ""}, "recovery": {"status": "skipped", "action": ""}, "cleanup": {"collected": []}}


def _python(generation: Path, platform: SelfUpdatePlatform) -> str:
    executable = "python.exe" if platform.is_windows else "python"
    return str(platform.scripts_dir(generation / "venv") / executable)


ROLLBACK_RESTORE_ENV = "OMH_UPDATE_ROLLBACK_RESTORE"


def _omh_cli(python: str, *arguments: str) -> list[str]:
    """`python -P -m omh.cli ...`: the generation's own package, never the cwd's.

    `python -m` puts the working directory at `sys.path[0]`. An `omh update`
    run from inside a source checkout (which ships a top-level `omh/` shim
    package) therefore re-entered the checkout's code instead of the
    generation that had just been activated: on the owner machine the 2.0.2
    candidate was judged by a stale 2.0.1 checkout, refused, rolled back, and
    the rollback re-entry stamped the manifest `2.0.1`. `-P` (Python 3.11+,
    the package floor) drops that entry so the interpreter resolves `omh`
    from its own site-packages wherever the operator happens to stand.
    """
    return [python, "-P", "-m", "omh.cli", *arguments]


def current_omh_cli(root: Path, *arguments: str, platform: SelfUpdatePlatform | None = None) -> list[str]:
    """`python -P -m omh.cli ...` on the generation `<root>/current` names now: how a process started on an older
    generation hands over to the one an update installed (bare `omh` relaunching its TUI after one)."""
    return _omh_cli(_python(root / "current", platform or SelfUpdatePlatform.host()), *arguments)


def _run(runner: Runner, command: list[str], *, env: dict[str, str] | None = None, timeout: float | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return runner(command, text=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None, env=env, timeout=timeout)


def _detail(value: subprocess.CompletedProcess[str], fallback: str) -> str:
    return str(value.stderr or value.stdout or fallback).strip()[:2000]


def _stage(candidate: Path, package_url: str, base_python: str, *, runner: Runner, json_mode: bool, platform: SelfUpdatePlatform) -> tuple[bool, str]:
    candidate.parent.mkdir(parents=True, exist_ok=True)
    try:
        built = _run(runner, [base_python, "-m", "venv", str(candidate / "venv")], capture=json_mode)
        if built.returncode:
            return False, _detail(built, "candidate venv creation failed")
        command = [_python(candidate, platform), "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--upgrade", package_url]
        if json_mode:
            command.insert(command.index("install") + 1, "-q")
        installed = _run(runner, command, capture=json_mode)
    except OSError as exc:
        return False, f"candidate staging failed: {exc}"
    return (True, "") if installed.returncode == 0 else (False, _detail(installed, "candidate pip install failed"))


def _smoke(candidate: Path, expected_version: str, *, runner: Runner, platform: SelfUpdatePlatform) -> tuple[bool, str]:
    env = dict(os.environ, OMH_SELF_UPDATE_GENERATION=str(candidate))
    with TemporaryDirectory(prefix="omh-self-update-") as temporary:
        env["OMH_HOME"] = str(Path(temporary) / "omh")
        env["HERMES_HOME"] = str(Path(temporary) / "hermes")
        python = _python(candidate, platform)
        checks = (([python, "-P", "-c", "import omh.cli"], "import"), (_omh_cli(python, "--version"), "version"), (_omh_cli(python, "update", "--command-package-updated", "--no-interactive", "--json"), "workflow-pack"))
        try:
            for command, name in checks:
                checked = _run(runner, command, env=env)
                if checked.returncode:
                    return False, f"{name} smoke failed: {_detail(checked, name + ' smoke failed')}"
                if name == "version" and expected_version and expected_version not in str(checked.stdout):
                    return False, f"version smoke failed: expected {expected_version}"
        except OSError as exc:
            return False, f"smoke execution failed: {exc}"
    skills = candidate / "skills"
    if not skills.is_dir() or not any(skills.iterdir()):
        return False, "workflow-pack smoke failed: candidate pack is empty"
    return True, ""



# The gateway restart after an update is the started process's alone (`commands/update_gateway.py`), and a restored,
# older generation does not know those flags, so no re-entry carries them.
OUTER_ONLY_FLAGS = frozenset({"--recover-known-good", "--restart-gateway", "--no-restart-gateway"})


def names_flag(item: str, flags: frozenset[str]) -> bool:
    """Whether a command-line word is one of `flags`, or the abbreviation of one that argparse accepted."""
    return item.startswith("--") and len(item) > 2 and any(flag.startswith(item) for flag in flags)


def _reentry_argv() -> list[str]:
    argv: list[str] = []
    for item in sys.argv[1:]:
        if names_flag(item, OUTER_ONLY_FLAGS):
            continue
        # `--channel main` is an alias a restored, older generation may not know.
        if item == "--channel=main" or (item == "main" and argv[-1:] == ["--channel"]):
            item = "--channel=preview" if item.startswith("--") else "preview"
        argv.append(item)
    return argv if "--command-package-updated" in argv else [*argv, "--command-package-updated"]


def generation_identity(generation: Path) -> GenerationIdentity:
    """The omh version, archive ref and archive commit a generation holds.

    Read from files, not by running the generation: the dist-info directory
    names the version, and the archive commit file plus pip's PEP 610 record
    name the commit and ref (`maintenance.build_identity.read_archive_commit`).
    Empty strings where a generation does not record one, such as a package
    built from a checkout or the pre-generation legacy venv.
    """
    venv = generation / "venv"
    for site in (*sorted(venv.glob("lib/python*/site-packages")), venv / "Lib" / "site-packages"):
        package = site / "omh"
        if not package.is_dir():
            continue
        dist_info = sorted(site.glob("oh_my_hermes-*.dist-info"))
        version = dist_info[-1].name.removeprefix("oh_my_hermes-").removesuffix(".dist-info") if dist_info else ""
        archive = read_archive_commit(package, version=version)
        return {"version": version, "ref": archive["ref"] or "", "commit_sha": archive["commit_sha"] or ""}
    return {"version": "", "ref": "", "commit_sha": ""}


def identity_label(identity: GenerationIdentity) -> str:
    """`4.0.5 main@1a2b3c4d`: the version and archive commit a generation records; "" when it records neither."""
    short = identity["commit_sha"][:8]
    commit = f"{identity['ref']}@{short}" if identity["ref"] and short else short
    return " ".join(part for part in (identity["version"], commit) if part)


def identity_change(previous: GenerationIdentity, current: GenerationIdentity) -> IdentityChange:
    """Classify what an activated update moved between.

    `changed` / `unchanged` need both commits. `previous_unrecorded` is the
    first update onto a generation that records its commit. Without a current
    commit only the version can be compared: `version_changed` or `unrecorded`.
    """
    if current["commit_sha"] and previous["commit_sha"]:
        status = "unchanged" if current["commit_sha"] == previous["commit_sha"] else "changed"
    elif current["commit_sha"]:
        status = "previous_unrecorded"
    else:
        status = "version_changed" if current["version"] != previous["version"] else "unrecorded"
    return {
        "schema_version": IDENTITY_CHANGE_SCHEMA_VERSION,
        "status": status,
        "previous": previous,
        "current": current,
        "version_changed": current["version"] != previous["version"],
    }


def _reenter(root: Path, generation: Path, args: Any, runner: Runner, platform: SelfUpdatePlatform, *, restoring: bool = False) -> tuple[bool, str, bool]:
    """Run the update through the pointer: (passed, reason, bot profiles need repair)."""
    trusted = require_generation_path(root, generation, None, "re-entry generation")
    pointed = pointer_target(root, platform=platform)
    if pointed is None:
        raise OmhError("cannot re-enter an untrusted self-update generation")
    pointed = require_generation_path(root, pointed, None, "current pointer target")
    if not same_existing_path(pointed, trusted):
        raise OmhError("cannot re-enter an untrusted self-update generation")
    env = dict(os.environ, OMH_UPDATE_COMMAND_PACKAGE_REENTERED="1", OMH_SELF_UPDATE_GENERATION=str(trusted))
    if restoring:
        # The rollback re-entry re-renders the known-good pack. Left to
        # itself it prints the ordinary update card ("Installed release ...
        # OMH update complete."), which is what the owner read as a
        # downgrade; the marker lets that run label itself a rollback.
        env[ROLLBACK_RESTORE_ENV] = "1"
    command = _omh_cli(_python(root / "current", platform), *_reentry_argv())
    # stdout stays on the terminal so the re-entered update's own progress and
    # prompts show live; stderr is captured so the failure that stops the
    # update reaches the summary line, then replayed so nothing is lost.
    try:
        checked = runner(command, text=True, stdout=None, stderr=subprocess.PIPE, env=env, timeout=REENTRY_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return False, "post-activation re-entry timed out", False
    if checked.stderr:
        sys.stderr.write(str(checked.stderr))
        sys.stderr.flush()
    if checked.returncode == PROFILE_REPAIR_EXIT_CODE:
        return True, "bot profiles were not refreshed; see the warnings above", True
    # The re-entry's stdout went to the terminal, so an exit without stderr
    # still has to say which run failed and where its reasons are.
    fallback = f"the re-entered `omh update` exited {checked.returncode}; its warnings are printed above"
    return checked.returncode == 0, _detail(checked, fallback), False


def _running_generation(root: Path) -> Path | None:
    executable = Path(sys.executable).expanduser().resolve()
    generations = root / "generations"
    for generation in generations.iterdir() if generations.exists() else ():
        try:
            executable.relative_to(generation.resolve() / "venv")
            return generation
        except ValueError:
            continue
    return None


def _cleanup_candidate(root: Path, candidate: Path) -> None:
    trusted = require_generation_path(root, candidate, None, "candidate cleanup target")
    shutil.rmtree(trusted, ignore_errors=True)


def _switch(root: Path, target: Path, platform: SelfUpdatePlatform) -> None:
    if platform.is_windows:
        switch_current(root, target, platform=platform)
    else:
        switch_current(root, target)


def _refresh_hermes_skills(root: Path, hermes_home: Path | None, result: SelfUpdateResult) -> None:
    """After a final pointer switch, make a running Hermes re-resolve `current/skills`.

    The re-entered `cmd_update` refreshes after an ordinary switch, but a
    rollback or a known-good revert may land on a generation older than that
    refresh, or not re-enter at all. Best effort: the rows, a `failed` one
    included, go into the result rather than raising.
    """
    if hermes_home is not None:
        result["hermes_skill_refresh"] = refresh_skill_dir_caches(hermes_home, root / "current" / "skills")


def run_installer_self_update(args: Any, plan: Mapping[str, object], *, runner: Runner = subprocess.run, platform: SelfUpdatePlatform | None = None) -> SelfUpdateResult:
    """Run stage, verification, pointer activation, rollback, and retention."""
    release = plan.get("release")
    package_url = str(getattr(release, "package_url", "") or "")
    expected_version = str(getattr(release, "version", "") or getattr(args, "version", "") or "")
    legacy = Path(str(plan.get("venv_dir") or managed_command_venv_dir() or Path(sys.executable).parent.parent))
    root = legacy.parent
    identifier = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{hashlib.sha256(package_url.encode()).hexdigest()[:10]}"
    candidate = root / "generations" / identifier
    result = _result(candidate)
    paths = resolve_paths(getattr(args, "omh_home", None), getattr(args, "hermes_home", None), scope=getattr(args, "scope", None))
    selected = platform or SelfUpdatePlatform.host()
    try:
        with file_lock(state_path(root), timeout_seconds=0.0, private=True) as lock:
            if not lock.get("enforced"):
                raise OmhError("atomic self-update requires an enforced file lock; no changes were made")
            state = load_state(root, legacy)
            had_marker = isinstance(state.get("activation_in_progress"), dict)
            interrupted = interrupted_activation(root, state, platform=selected)
            if had_marker and interrupted is None:
                result["recovery"] = {"status": "ok", "action": "discarded_unswitched_candidate"}
            if interrupted is not None:
                recovered = _recover_interrupted(root, state, interrupted, args, runner, selected, result, hermes_home=paths.hermes_home)
                if recovered["recovery"].get("action") != "completed_pending_restore" or not package_url:
                    return recovered
                # The restore an earlier run left pending is done, so this run
                # goes on to the update it was asked for instead of stopping.
                result = _result(candidate)
                result["recovery"] = recovered["recovery"]
            if bool(getattr(args, "recover_known_good", False)):
                return _recover_known_good(root, state, args, runner, selected, result, hermes_home=paths.hermes_home)
            if not package_url:
                raise OmhError("cannot update command package because no package URL is available")
            staged, reason = _stage(candidate, package_url, str(plan.get("python") or sys.executable), runner=runner, json_mode=bool(getattr(args, "json", False)), platform=selected)
            result.update(phase="staging", staging={"status": "ok" if staged else "failed", "reason": reason})
            if not staged:
                _cleanup_candidate(root, candidate)
                return result
            verified, reason = _smoke(candidate, expected_version, runner=runner, platform=selected)
            result.update(phase="verification", verification={"status": "ok" if verified else "failed", "reason": reason})
            if not verified:
                _cleanup_candidate(root, candidate)
                return result
            try:
                migrate_legacy(root, state, paths, selected)
            except (OSError, ValueError, OmhError) as exc:
                _cleanup_candidate(root, candidate)
                result.update(phase="migration", migration={"status": "failed", "reason": str(exc)})
                return result
            return _activate(root, state, candidate, args, runner, selected, result, hermes_home=paths.hermes_home)
    except FileLockTimeout as exc:
        raise OmhError("another omh update is already in progress; no changes were made") from exc


def _activate(root: Path, state: dict[str, Any], candidate: Path, args: Any, runner: Runner, platform: SelfUpdatePlatform, result: SelfUpdateResult, *, hermes_home: Path | None = None) -> SelfUpdateResult:
    result["migration"] = {"status": "ok", "reason": "old pair migrated onto current"}
    previous = Path(str(state["active"]["path"]))
    mark_activation(state, candidate, previous)
    save_state(root, state)
    try:
        _switch(root, candidate, platform)
    except OmhError as exc:
        result.update(phase="activation", activation={"status": "failed", "reason": str(exc)})
        return result
    mark_switched(state)
    save_state(root, state)
    launcher = "present" if state["migration"].get("launcher_on_pointer") else "absent_manual_instruction"
    result["activation"] = {"status": "ok", "pointer": str(root / "current"), "launcher": launcher}
    passed, reason, profiles = _reenter(root, candidate, args, runner, platform)
    post_activation: PhaseResult = {"status": "ok" if passed else "failed", "reason": reason}
    if profiles:
        post_activation["profiles_need_repair"] = True
    result.update(phase="post_activation", post_activation=post_activation)
    if not passed:
        _rollback_activation(root, state, candidate, previous, args, runner, platform, result, hermes_home=hermes_home)
        return result
    commit_activation(root, state, candidate)
    # Read before garbage collection, which may delete the previous generation.
    result["identity_change"] = identity_change(generation_identity(previous), generation_identity(candidate))
    collect_garbage(root, state, result, running_generation=_running_generation(root), gateway_starts=recorded_gateway_starts(hermes_home) if hermes_home is not None else ())
    save_state(root, state)
    result.update(ok=True, phase="cleanup")
    return result


def _rollback_activation(root: Path, state: dict[str, Any], candidate: Path, previous: Path, args: Any, runner: Runner, platform: SelfUpdatePlatform, result: SelfUpdateResult, *, hermes_home: Path | None = None) -> None:
    # Persist the recovery intent before moving the pointer. A crash or failed
    # reentry must not make the next update discard this transaction as unswitched.
    state["activation_in_progress"]["restore_required"] = True
    save_state(root, state)
    try:
        _switch(root, previous, platform)
    except OmhError as exc:
        restored, reason = False, str(exc)
    else:
        restored, reason, _profiles = _reenter(root, previous, args, runner, platform, restoring=True)
        # The candidate's re-entry may have refreshed Hermes onto the candidate,
        # which is about to be deleted; the restored generation may predate the refresh.
        _refresh_hermes_skills(root, hermes_home, result)
    if not restored:
        result["rollback"] = {"performed": True, "restored": "", "status": "failed", "reason": reason}
        result["recovery"] = {"status": "required", "action": "restore_failed", "reason": reason}
        return
    state["activation_in_progress"] = None
    record_pointer(state, root, previous)
    save_state(root, state)
    _cleanup_candidate(root, candidate)
    result["rollback"] = {"performed": True, "restored": previous.name}


def _recover_interrupted(root: Path, state: dict[str, Any], interrupted: tuple[Path, Path], args: Any, runner: Runner, platform: SelfUpdatePlatform, result: SelfUpdateResult, *, hermes_home: Path | None = None) -> SelfUpdateResult:
    candidate, previous = interrupted
    restoring = state["activation_in_progress"].get("restore_required") is True
    passed, reason, profiles = (False, "restore pending", False) if restoring else _reenter(root, candidate, args, runner, platform)
    if passed:
        commit_activation(root, state, candidate)
        save_state(root, state)
        result.update(ok=True, phase="recovery", recovery={"status": "ok", "action": "completed_interrupted_activation"})
        if profiles:
            result["post_activation"] = {"status": "ok", "reason": reason, "profiles_need_repair": True}
        return result
    result.update(phase="recovery", recovery={"status": "failed", "action": "rolled_back_interrupted_activation"})
    _rollback_activation(root, state, candidate, previous, args, runner, platform, result, hermes_home=hermes_home)
    if restoring and result["rollback"].get("restored"):
        result["recovery"] = {"status": "ok", "action": "completed_pending_restore", "selected": previous.name}
    return result


def _recover_known_good(root: Path, state: dict[str, Any], args: Any, runner: Runner, platform: SelfUpdatePlatform, result: SelfUpdateResult, *, hermes_home: Path | None = None) -> SelfUpdateResult:
    target = recovery_target(root, state)
    previous = Path(str(state["active"]["path"]))
    mark_activation(state, target, previous)
    save_state(root, state)
    _switch(root, target, platform)
    passed, reason, _profiles = _reenter(root, target, args, runner, platform)
    if not passed:
        _switch(root, previous, platform)
        _refresh_hermes_skills(root, hermes_home, result)
        state["activation_in_progress"] = None
        save_state(root, state)
        result.update(phase="recovery", recovery={"status": "failed", "action": "restore_failed", "reason": reason})
        return result
    restore_known_good(root, state, target)
    save_state(root, state)
    # The known-good target may predate the refresh its own re-entry would run.
    _refresh_hermes_skills(root, hermes_home, result)
    result.update(ok=True, phase="recovery", recovery={"status": "ok", "action": "selected_known_good", "selected": target.name}, activation={"status": "skipped", "reason": "recovery"}, post_activation={"status": "ok", "reason": "known-good restored"})
    return result
