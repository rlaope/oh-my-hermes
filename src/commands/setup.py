from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import cast
import unicodedata

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows compatibility guard.
    termios = None
    tty = None

from ..version import __version__
from ..command_path import COMMAND_PATH_MISSING_NEXT_ACTION, inspect_omh_command_path
from ..capabilities.registry import capability_summary
from ..capabilities.skills import skill_capabilities
from ..coding.executor_auth_signals import auth_signal_for_profile
from ..coding.executors import EXTERNAL_CLI_PROFILES
from ..coding.fanout_dispatch import (
    DISPATCH_MODEL_PREFERENCE_SCHEMA_VERSION,
    dispatch_model_preferences_path,
)
from ..coding.hermes_model_config import (
    apply_hermes_model_config,
    inspect_hermes_model_config,
    preview_hermes_model_config,
)
from ..coding.model_discovery import discover_local_models
from ..coding.model_recommendations import resolve_model_recommendation
from ..config_adapter import (
    ConfigChange,
    activate_omh_skin,
    activate_tui_interface,
    configured_provider_ids,
    display_interface_selection,
    display_skin_selection,
    ensure_external_dir,
    ensure_omh_skin,
    ensure_plugin_enabled,
    ensure_tui_interface,
    external_dirs,
    maybe_set_memory_provider,
    memory_provider_selection,
    read_config,
    remove_external_dir,
    write_config,
)
from ..install.compression_defaults import ensure_compression_defaults
from ..doctor import DEFAULT_DOCTOR_NEXT_ACTION, doctor_ok, recommended_next_action, run_doctor
from ..maintenance.build_identity import probe_build_identity
from ..maintenance.doctor import run_doctor_advisories
from ..executors import CODING_EXECUTOR_TARGETS
from ..hashutil import sha256_file
from ..installer import (
    SKILL_PROFILE_RECONCILE_COMMAND,
    OmhError,
    install_skill_pack,
    reconcile_skill_profile,
    skill_profile_report,
    uninstall_profile_plugin,
    uninstall_skill_pack,
)
from ..local_store import atomic_write_text
from ..install.installer import DEFAULT_SKILL_PROFILE, SKILL_PROFILES
from ..manifest import read_manifest
from ..menubar_app import is_managed_menubar_install, setup_menubar_app, uninstall_menubar_app
from ..mcp.host_config import install_mcp_host_config
from ..mcp_bridge import MCP_HOST_CONFIG_RECIPE_HOSTS
from ..paths import OmhPaths, managed_command_venv_dir, managed_current_workflow_pack_dir, managed_generation_for_executable
from ..plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from ..plugin_pack import PLUGIN_NAME, PluginPackError, install_plugin_bundle
from ..probe import probe_capabilities
from ..release import (
    RELEASE_CHANNELS,
    package_url_for,
    release_artifact_note,
)
from ..skin_pack import SKIN_NAME, install_skin, is_omh_skin_name, uninstall_skin
from ..tui_widget_pack import install_tui_widget, uninstall_tui_widget
from ..routing.recommend import recommend_skills
from ..routing.route_plan import build_workflow_route_plan, compact_workflow_route_plan
from ..runtime.artifacts import read_state_result, update_state
from ..setup_profiles import (
    PROJECT_MEMORY_MODES,
    build_setup_profile,
    write_setup_profile,
)
from ..snippet import WORKSPACE_SNIPPET
from ..targets import record_target_observation
from ..team_profiles import (
    TeamProfileError,
    inspect_operating_model,
    inspect_team_profile_pack,
    install_team_profile_pack,
    list_team_profile_packs,
    operating_model_ids,
)
from .common import _action_label, _paths, _print_json, _wants_json
from .language import LANGUAGE_CODES, language_from_env, normalize_language, tr
from .model_setup_flow import (
    ModelSetupFlowDependencies,
    model_activation_result,
)
from .model_setup_inputs import validate_model_setup_args
from .model_setup_rendering import (
    print_model_activation_summary,
    print_model_preview_review,
)

POSIX_INSTALLER_COMMAND = "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh"
WINDOWS_INSTALLER_COMMAND = "irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex"
COMMAND_PACKAGE_MANAGER_ENV = "OMH_COMMAND_PACKAGE_MANAGER"
COMMAND_PACKAGE_ROOT_ENV = "OMH_COMMAND_PACKAGE_ROOT"
COMMAND_PACKAGE_RUNTIME_ENV = "OMH_COMMAND_PACKAGE_RUNTIME"
COMMAND_PACKAGE_ENTRYPOINT_ENV = "OMH_COMMAND_PACKAGE_ENTRYPOINT"
COMMAND_PACKAGE_UPDATE_COMMANDS = {
    "npm": "npm update -g oh-my-hermes",
    "bun": "bun update -g --latest oh-my-hermes",
    "homebrew": "brew upgrade rlaope/tap/omh",
}
COMMAND_PACKAGE_UPDATE_ARGUMENTS = {
    "npm": ("update", "-g", "oh-my-hermes"),
    "bun": ("update", "-g", "--latest", "oh-my-hermes"),
    "homebrew": ("upgrade", "rlaope/tap/omh"),
}
COMMAND_PACKAGE_EXECUTABLES = {
    "npm": "npm",
    "bun": "bun",
    "homebrew": "brew",
}


def installer_command() -> str:
    """The installer one-liner for the host this command is running on.

    A Windows user told to run `curl ... | sh` has been handed something their
    shell cannot execute, which reads as "OMH does not support this platform"
    rather than "wrong line was printed".
    """
    return WINDOWS_INSTALLER_COMMAND if os.name == "nt" else POSIX_INSTALLER_COMMAND


def _command_package_update_guidance() -> tuple[str, str]:
    explicit = os.environ.get(COMMAND_PACKAGE_MANAGER_ENV, "").strip().lower()
    if explicit in COMMAND_PACKAGE_UPDATE_COMMANDS:
        return explicit, COMMAND_PACKAGE_UPDATE_COMMANDS[explicit]
    if _homebrew_prefix_root() is not None:
        return "homebrew", COMMAND_PACKAGE_UPDATE_COMMANDS["homebrew"]
    direct = _direct_url_update_guidance()
    if direct is not None:
        return direct
    return "installer", installer_command()


def _direct_url_update_guidance() -> tuple[str, str] | None:
    """Name the real owner of a PEP 610 direct-URL install.

    An agent handed only the repository link often installs the command with
    `pip install git+...`, `pip install <clone>`, or `uv tool install`. Those
    installs carry no manager provenance state, and the generic curl fallback
    would create a second, conflicting install next to the one that already
    owns the command. The dist-info `direct_url.json` records the actual
    origin, so the update instruction points there instead. The curl
    installer's own managed venv also leaves a `direct_url.json`, but it
    names the deleted download directory, so it falls through to the
    installer fallback as before.
    """
    import importlib.metadata
    from urllib.parse import urlsplit
    from urllib.request import url2pathname

    try:
        raw = importlib.metadata.distribution("oh-my-hermes").read_text("direct_url.json")
    except (importlib.metadata.PackageNotFoundError, OSError):
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    url = str(data.get("url", "") or "")
    prefix_parts = tuple(part.casefold() for part in Path(sys.prefix).parts)
    if "uv" in prefix_parts and "tools" in prefix_parts:
        return "uv-tool", "uv tool upgrade oh-my-hermes"
    if isinstance(data.get("vcs_info"), dict) and url and not url.startswith("file:"):
        return "pip", f'{sys.executable} -m pip install --upgrade "git+{url}"'
    dir_info = data.get("dir_info")
    if isinstance(dir_info, dict) and url.startswith("file://"):
        if dir_info.get("editable"):
            # An editable install is a development checkout; its command
            # updates through `git pull` alone and keeps the long-standing
            # installer fallback wording rather than a pip reinstall.
            return None
        # url2pathname handles Windows drive letters (`file:///C:/...`),
        # which a bare unquote of the URL path would leave unusable.
        checkout = Path(url2pathname(urlsplit(url).path))
        if checkout.is_dir():
            return "pip", (
                f"git -C {checkout} pull && "
                f"{sys.executable} -m pip install --upgrade {checkout}"
            )
    return None


def _homebrew_prefix_root() -> Path | None:
    prefix = Path(sys.prefix)
    folded_parts = tuple(part.casefold() for part in prefix.parts)
    for index, part in enumerate(folded_parts):
        if part == "cellar" and folded_parts[index + 1 : index + 2] == ("omh",):
            return Path(*prefix.parts[:index])
    return None


COMMAND_PACKAGE_STATUS_SCHEMA_VERSION = "command_package_status/v1"
RELEASE_UPDATE_SCHEMA_VERSION = "release_update_status/v1"
SETUP_OPERATOR_SUMMARY_SCHEMA_VERSION = "setup_operator_summary/v1"
DOCTOR_SUMMARY_SCHEMA_VERSION = "doctor_summary/v1"
MCP_SETUP_SCHEMA_VERSION = "omh_mcp_setup/v1"
SELF_UPDATE_REENTRY_ENV = "OMH_UPDATE_COMMAND_PACKAGE_REENTERED"
SELF_UPDATE_SKIP_ENV = "OMH_SKIP_COMMAND_PACKAGE_UPDATE"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def cmd_install(args: argparse.Namespace) -> int:
    language = _resolve_language(args)
    if _wants_json(args):
        payload = _install_result(args)
        _print_json(payload)
    else:
        operation = _install_operation(args)
        progress = _HumanProgress(enabled=True, use_color=_use_color())
        progress.header(f"OMH {operation}", tr(language, "install_subtitle"))
        progress.step(1, 1, tr(language, "step_install_skills"))
        payload = _install_result(args)
        skills = payload.get("skills", [])
        progress.done(tr(language, "done_skills_ready", count=len(skills) if isinstance(skills, list) else 0))
        _print_install_summary(payload, command=operation, language=language)
    return 0


def _install_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    language = _resolve_language(args)
    operation = _install_operation(args)
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.channel == "local" and not (args.from_skills_dir or args.source):
        raise OmhError("local channel requires --from-skills-dir or --source")
    source_dir = Path(args.from_skills_dir or args.source).expanduser().resolve() if (args.from_skills_dir or args.source) else None
    source = str(source_dir) if source_dir else "builtin"
    source_ref = _release_source_ref(args, release)
    previous_release = _previous_release_update_state(paths)
    # Read before install_skill_pack rewrites the manifest.
    previous_manifest_sha256 = _previous_manifest_sha256(paths)
    skill_profile = _resolved_skill_profile(args, paths)
    result = install_skill_pack(
        paths,
        source=source,
        source_dir=source_dir,
        force=args.force,
        dry_run=args.dry_run,
        profile=skill_profile,
    )
    result.update(
        {
            "operation": operation,
            "release_channel": release.channel,
            "release_version": release.version,
            "release_package_url": release.package_url,
            "release_artifact_kind": release.artifact_kind,
            "release_artifact_note": release_artifact_note(release),
            "release_source_ref": source_ref,
            "language": language,
        }
    )
    if not args.dry_run:
        result["runtime_state_path"] = str(paths.runtime_state_path)
        result["runtime_state_key"] = f"last_{operation}"
    result["managed_skills"] = _managed_skills_status(result, dry_run=bool(args.dry_run))
    result["command_package"] = _command_package_status_for_install(
        operation=operation,
        source=source,
        dry_run=bool(args.dry_run),
        command_package_updated=bool(getattr(args, "command_package_updated", False)),
    )
    result["workflow_content"] = _workflow_content_status(
        paths,
        previous_manifest_sha256,
        dry_run=bool(args.dry_run),
    )
    result["release_update"] = _release_update_status(
        release_channel=release.channel,
        release_version=release.version,
        release_package_url=release.package_url,
        source_ref=source_ref,
        explicit_metadata=_explicit_release_metadata_supplied(args),
        previous=previous_release,
        command_package=result["command_package"],
        dry_run=bool(args.dry_run),
    )
    if not args.dry_run:
        operation_log = _install_operation_log(result, source=source)
        state_patch: dict[str, object] = {
            "package": "oh-my-hermes",
            "version": __version__,
            "manifest_path": str(paths.manifest_path),
            "manifest_sha256": sha256_file(paths.manifest_path),
            "source": source,
            "release_channel": release.channel,
            "release_version": release.version,
            "release_package_url": release.package_url,
            "release_source_ref": source_ref,
            "release_update": result["release_update"],
            "installed_skills": len(result.get("skills", [])),
            "skills_dir": str(paths.skills_dir),
            f"last_{operation}": operation_log,
        }
        # Only overwrite a previously recorded identity with a freshly
        # confirmed one; never regress it to "" just because update-check
        # was off (or the probe failed) on this particular run. The helper
        # also enforces the issue #1282 replayable advance policy: an open,
        # unaccepted coverage gap (or a non-fast-forward ancestry) pins the
        # cursor by returning "".
        release_source_commit = _release_source_commit_for_state(paths, release)
        if release_source_commit:
            state_patch["release_source_commit"] = release_source_commit
        update_state(paths, state_patch)
    return result


def cmd_update(args: argparse.Namespace) -> int:
    self_update = _command_package_self_update_plan(args)
    if self_update.get("should_update"):
        return _run_command_package_self_update(args, self_update)
    _preset_tui_identity_choice(args)
    if _update_should_interact(args):
        _ask_tui_identity_choice(args, _paths(args), _resolve_language(args))
    code = cmd_install(args)
    if code == 0:
        if not (args.from_skills_dir or args.source):
            if _paths(args).hermes_plugin_dir.is_dir():
                _refresh_installed_plugin_bundle(args)
                _refresh_hermes_registration(args)
                # Same carry-forward rule as registration: a surface only
                # setup seeds never lands on machines that update forever.
                # Seeding is create-only, so user edits are never touched.
                _seed_model_chains_result(_paths(args), dry_run=bool(args.dry_run))
            else:
                _bootstrap_tui_surface(args)
        _refresh_installed_tui_widget(args)
        _refresh_installed_menubar_app(args)
        # Bot profiles are independent Hermes homes; update carries the same
        # managed registration into each so a bot chat sees the same skills
        # the default chat does — including bots created after install.
        profile_results: list[dict[str, object]] = []
        if not (args.from_skills_dir or args.source) and hasattr(args, "omh_home"):
            profile_results = _sync_hermes_profiles(args)
        # The verdict prints LAST on purpose: a success summary followed by a
        # stock-Hermes terminal is what users kept reporting as a broken
        # install. Human output only — the JSON payload was already emitted
        # by cmd_install before the surface refreshes above ran.
        if (
            not _wants_json(args)
            and not bool(getattr(args, "dry_run", False))
            and hasattr(args, "omh_home")
        ):
            _print_hermes_profiles_line(profile_results, language=_resolve_language(args))
            _print_tui_verdict_block(_tui_verdict_payload(args), language=_resolve_language(args))
    return code


def _tui_verdict_payload(args: argparse.Namespace) -> dict[str, object]:
    from ..maintenance.hermes_tui import tui_identity_verdict

    return tui_identity_verdict(_paths(args))


def _print_tui_verdict_block(verdict: dict[str, object], *, language: str) -> None:
    use_color = _use_color()
    status = str(verdict.get("status", ""))
    if status == "ready":
        print(_color(f"  {tr(language, 'tui_verdict_ready')}", "1;32", use_color))
    elif status == "unknown":
        print(f"  {tr(language, 'tui_verdict_unknown')}")
    else:
        print(_color(f"  {tr(language, 'tui_verdict_blocked')}", "1;33", use_color))
        blockers = verdict.get("blockers", [])
        if isinstance(blockers, list):
            for blocker in blockers:
                print(f"    - {blocker}")
        next_commands = verdict.get("next_commands", [])
        if isinstance(next_commands, list):
            for command in next_commands:
                print(_color(f"  {tr(language, 'tui_verdict_next', command=command)}", "1;33", use_color))
    notes = verdict.get("notes", [])
    if isinstance(notes, list):
        for note in notes:
            print(f"  {note}")


def _bootstrap_tui_surface(args: argparse.Namespace) -> dict[str, object] | None:
    """Give `omh update` on a never-set-up machine the full OMH TUI.

    Update and setup must converge on the same machine state (owner decision,
    2026-08-20): a user who only ever runs `omh update` still ends with the
    plugin bundle installed, OMH registered and enabled in the Hermes config
    (which also activates the skin), and the chain-override document seeded —
    instead of a plain Hermes that silently lacks the OMH identity. The
    deliberate opt-out stays respected: `omh uninstall --registration-only`
    keeps the plugin directory in place, so an unregistered-but-installed
    machine never reaches this path and stays unregistered.
    """
    paths = _paths(args)
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError as exc:
        print(
            f"note: could not install the OMH plugin bundle: {exc}; run `omh setup --force`",
            file=sys.stderr,
        )
        return None
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    _seed_model_chains_result(paths, dry_run=bool(args.dry_run))
    try:
        _apply_result(args)
    except OmhError as exc:
        # The bundle landed; an unwritable config must not fail the update.
        # Say what is missing instead of leaving a half-silent install.
        print(
            f"note: could not register OMH in the Hermes config: {exc}; run `omh setup`",
            file=sys.stderr,
        )
    return result


def _hermes_profile_dirs(paths) -> list[tuple[str, "Path"]]:
    """List the Hermes bot-profile homes under ``<hermes_home>/profiles/``.

    Hermes profiles (``hermes profile create``, Desktop bot chats) are fully
    independent HERMES_HOME directories with their own config.yaml, skills,
    and skins — a registration written to the primary home never reaches
    them, which is why bot chats showed zero OMH skills while the default
    chat had the full set. Sorted for deterministic output; hidden entries
    are Hermes-internal, never profiles.
    """
    root = paths.hermes_home / "profiles"
    try:
        entries = sorted(entry for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith("."))
    except OSError:
        return []
    return [(entry.name, entry) for entry in entries]


def _sync_hermes_profiles(args: argparse.Namespace) -> list[dict[str, object]]:
    """Apply the managed OMH registration to every bot-profile home.

    Each profile is its own Hermes home, so each gets the same per-home pair
    the primary gets: the plugin bundle plus config registration (with the
    widget and skin artifacts the registration references). The primary
    home's deliberate-unregistration rule carries over per profile: a
    profile whose plugin directory exists while its config does not list the
    skills directory chose to be unregistered, and neither setup nor update
    puts it back. A profile with no bundle at all is a new bot — it gets the
    full bootstrap, which is what makes bots created after install pick up
    OMH on the next `omh update`.
    """
    results: list[dict[str, object]] = []
    for name, profile_dir in _hermes_profile_dirs(_paths(args)):
        clone = argparse.Namespace(**vars(args))
        clone.hermes_home = str(profile_dir)
        profile_paths = _paths(clone)
        registered = _external_dir_registered(
            read_config(profile_paths.hermes_config_path),
            _registered_workflow_dir(profile_paths),
        )
        if profile_paths.hermes_plugin_dir.is_dir() and not registered:
            results.append({"profile": name, "status": "unregistered_kept"})
            continue
        entry: dict[str, object] = {
            "profile": name,
            "status": "refreshed" if profile_paths.hermes_plugin_dir.is_dir() else "bootstrapped",
        }
        try:
            install_plugin_bundle(profile_paths, force=bool(getattr(args, "force", False)), dry_run=bool(args.dry_run))
            install_tui_widget(profile_paths.hermes_home, dry_run=bool(args.dry_run))
            install_skin(profile_paths.hermes_home, dry_run=bool(args.dry_run))
            _apply_result(clone)
        except (PluginPackError, OmhError) as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
        results.append(entry)
    return results


def _uninstall_hermes_profiles(args: argparse.Namespace, *, remove_all: bool) -> list[dict[str, object]]:
    """Reverse the per-profile sync: unregister every bot-profile home.

    Full scopes also removes each profile's managed artifacts through the
    manifest-checked helpers -- never a raw rmtree -- so a profile whose plugin
    directory OMH cannot prove ownership of is kept and reported, exactly as the
    primary is. Registration-only scopes keep the plugin directory on purpose:
    plugin-dir-present plus unregistered is the deliberate opt-out marker
    _sync_hermes_profiles respects, so unregistering must not destroy that state.
    One malformed profile config fails its own row and never aborts the primary uninstall
    halfway.
    """
    results: list[dict[str, object]] = []
    for name, profile_dir in _hermes_profile_dirs(_paths(args)):
        clone = argparse.Namespace(**vars(args))
        clone.hermes_home = str(profile_dir)
        profile_paths = _paths(clone)
        entry: dict[str, object] = {"profile": name}
        try:
            change = remove_external_dir(
                read_config(profile_paths.hermes_config_path),
                _registered_workflow_dir(profile_paths),
            )
            if not args.dry_run and change.changed:
                write_config(profile_paths.hermes_config_path, change.text)
            touched = change.changed
            if remove_all:
                plugin = uninstall_profile_plugin(
                    profile_paths,
                    dry_run=bool(args.dry_run),
                    force=bool(args.force),
                )
                uninstall_tui_widget(profile_paths.hermes_home, dry_run=bool(args.dry_run))
                uninstall_skin(profile_paths.hermes_home, dry_run=bool(args.dry_run))
                touched = touched or bool(plugin["removed_paths"]) or bool(plugin["would_remove"])
                if plugin["kept_paths"]:
                    entry["kept_paths"] = plugin["kept_paths"]
            entry["status"] = (
                ("cleared" if touched else "absent")
                if remove_all
                else ("unregistered" if change.changed else "absent")
            )
        except (ValueError, OmhError) as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
        results.append(entry)
    return results


_PROFILE_STATUS_LABELS = {
    "bootstrapped": "set up",
    "refreshed": "refreshed",
    "unregistered_kept": "left unregistered",
    "failed": "failed",
    "cleared": "cleared",
    "unregistered": "unregistered",
    "absent": "nothing to remove",
}


def _print_hermes_profiles_line(results: list[dict[str, object]], *, language: str) -> None:
    if not results:
        return
    summary = ", ".join(
        f"{entry.get('profile')} ({_PROFILE_STATUS_LABELS.get(str(entry.get('status')), str(entry.get('status')))})"
        for entry in results
    )
    print(f"  {tr(language, 'hermes_profiles_synced', summary=summary)}")


def _registered_workflow_dir(paths: OmhPaths) -> Path:
    """Keep installer consumers under the non-resolved shared pointer."""
    current = managed_current_workflow_pack_dir()
    if current is not None and current.is_dir() and _managed_command_runtime().get("managed"):
        return current
    return paths.skills_dir


def _external_dir_registered(config: str, path: Path) -> bool:
    wanted = _external_dir_key(path)
    return any(_external_dir_key(entry) == wanted for entry in external_dirs(config))


def _external_dir_key(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).replace("\\", "/")


def _refresh_hermes_registration(args: argparse.Namespace) -> dict[str, object] | None:
    """Carry a registered install forward to what the running version needs.

    `omh setup` is meant to be a one-time act. It stopped being one the moment
    a release added something to Hermes' config that only setup wrote: update
    refreshed skills and the bundle, the new key never landed, and the fix was
    to tell people to run setup again. The memory-provider slot was exactly
    that, and it will not be the last.

    Only for an install that is already registered -- the skills directory is
    already in `skills.external_dirs`. Registering a fresh one stays setup's
    job, and someone who deliberately unregistered OMH must not have update
    put it back.
    """
    paths = _paths(args)
    if not _external_dir_registered(read_config(paths.hermes_config_path), _registered_workflow_dir(paths)):
        return None
    try:
        return _apply_result(args)
    except OmhError:
        # An update must not fail over a config it cannot rewrite; `omh doctor`
        # reports the gap with the command that repairs it.
        return None


def _refresh_installed_plugin_bundle(args: argparse.Namespace) -> dict[str, object] | None:
    """Bring an already-installed plugin bundle up to the running version.

    `omh update` used to refresh skills and stop there: `install_plugin_bundle`
    was reachable only from `cmd_setup`, so the tools, hooks, and memory
    provider under `$HERMES_HOME/plugins/omh/` stayed at whatever version last
    ran setup. The three commands AGENTS.md tells ordinary users to know are
    setup, update, and doctor -- and update was the one that did not update.

    Only refreshes what is already there; a machine with no bundle at all goes
    through `_bootstrap_tui_surface` instead, which installs the bundle AND
    performs the Hermes registration/enablement half of the pair.
    """
    paths = _paths(args)
    if not paths.hermes_plugin_dir.is_dir():
        return None
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError:
        # An update must not fail over a bundle a later `omh setup --force` can
        # repair; `omh doctor` reports the drift with the instruction to run it.
        return None
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    return result


def _hermes_tui_preflight_step(
    paths: OmhPaths, *, quiet: bool, dry_run: bool = False
) -> dict[str, object]:
    """Report whether the just-installed HUD can actually render, and why not.

    Installing the widget while the Hermes side cannot load it (old Hermes,
    stripped SDK, classic-REPL default, stale interpreter) is a success that
    behaves like a failure: every check passes and the user still sees no
    HUD. Setup and update therefore say so at install time instead of leaving
    the diagnosis to a screenshot comparison. A dry run skips the inspection —
    the state it would inspect is exactly the state the real run writes. In
    JSON mode the note goes to stderr so machine output stays parseable while
    a human watching the pipe still sees it. An absent Hermes install prints
    nothing: PATH-installed Hermes layouts are real, and "cannot render" would
    be a false claim there — doctor reports that state as unobserved instead.
    """
    from ..maintenance.hermes_tui import hermes_tui_preflight, widget_render_blockers

    if dry_run:
        return {"status": "skipped_dry_run"}
    preflight = hermes_tui_preflight(paths)
    blockers = widget_render_blockers(preflight)
    install_found = bool(preflight.get("install", {}).get("found"))
    if blockers and install_found:
        stream = sys.stderr if quiet else sys.stdout
        print("note: the OMH HUD may not render on this Hermes:", file=stream)
        for blocker in blockers:
            print(f"  - {blocker}", file=stream)
    preflight["render_blockers"] = blockers
    return preflight


def _refresh_installed_tui_widget(args: argparse.Namespace) -> dict[str, object] | None:
    paths = _paths(args)
    if not paths.hermes_plugin_dir.is_dir():
        return None
    result = install_tui_widget(paths.hermes_home, dry_run=bool(args.dry_run))
    install_skin(paths.hermes_home, dry_run=bool(args.dry_run))
    # A refreshed widget that the Hermes side cannot load is a success that
    # behaves like a failure; say so at update time (same note as setup).
    _hermes_tui_preflight_step(paths, quiet=_wants_json(args), dry_run=bool(args.dry_run))
    return result


def _refresh_installed_menubar_app(args: argparse.Namespace) -> dict[str, object] | None:
    """Bring an already-installed native menu bar helper up to date."""
    configured_omh_home = getattr(args, "omh_home", None)
    configured_hermes_home = getattr(args, "hermes_home", None)
    raw_homes = (
        configured_omh_home if configured_omh_home not in (None, "") else os.environ.get("OMH_HOME"),
        configured_hermes_home if configured_hermes_home not in (None, "") else os.environ.get("HERMES_HOME"),
    )
    if any(_configured_path_contains_symlink(value) for value in raw_homes):
        return None
    paths = _paths(args)
    if not is_managed_menubar_install(paths):
        return None
    try:
        result = setup_menubar_app(
            paths,
            dry_run=bool(args.dry_run),
            start=True,
            force=bool(args.force),
        )
    except (OSError, RuntimeError) as exc:
        print(f"note: OMH menu bar helper was not refreshed: {exc}", file=sys.stderr)
        return {"status": "failed", "reason": str(exc)}
    if result.get("status") == "installed_start_failed":
        reason = str(result.get("start_message", "launchctl start failed"))
        print(f"note: OMH menu bar helper was not refreshed: {reason}", file=sys.stderr)
    return result


def _configured_path_contains_symlink(value: object) -> bool:
    if value is None or value == "":
        return False
    path = Path(os.path.expandvars(str(value))).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    current = path
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _command_package_self_update_plan(args: argparse.Namespace) -> dict[str, object]:
    if bool(getattr(args, "command_package_updated", False)):
        return {"should_update": False, "reason": "command package update already observed"}
    if bool(getattr(args, "dry_run", False)):
        return {"should_update": False, "reason": "dry run does not update the command package"}
    if os.environ.get(SELF_UPDATE_REENTRY_ENV):
        return {"should_update": False, "reason": "already re-entered after command package update"}
    if os.environ.get(SELF_UPDATE_SKIP_ENV):
        return {"should_update": False, "reason": f"{SELF_UPDATE_SKIP_ENV} is set"}
    if getattr(args, "from_skills_dir", None) or getattr(args, "source", None):
        return {"should_update": False, "reason": "explicit skill source updates workflows only"}
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if release.channel == "local" and release.package_url == "local":
        return {"should_update": False, "reason": "local updates require an explicit package source"}
    package_manager, update_instruction = _command_package_update_guidance()
    update_arguments = COMMAND_PACKAGE_UPDATE_ARGUMENTS.get(package_manager)
    launcher = _validated_command_package_launcher(package_manager)
    homebrew_commands = (
        _validated_homebrew_commands()
        if package_manager == "homebrew"
        else None
    )
    if update_arguments is not None and (
        launcher is not None or homebrew_commands is not None
    ):
        if _explicit_release_metadata_supplied(args):
            raise OmhError(
                "package-manager installs accept the default published update only; "
                "use the owning manager directly for an explicit version or package URL"
            )
        if launcher is not None:
            manager_command = COMMAND_PACKAGE_EXECUTABLES[package_manager]
            manager_executable = shutil.which(manager_command)
            runtime = str(launcher["runtime"])
            reentry_command = [
                runtime,
                str(launcher["entrypoint"]),
            ]
        else:
            assert homebrew_commands is not None
            manager_command = "brew"
            manager_executable = str(homebrew_commands["brew"])
            runtime = ""
            reentry_command = [str(homebrew_commands["omh"])]
        if manager_executable is None:
            return {
                "should_update": False,
                "reason": (
                    f"cannot update command package because `{manager_command}` "
                    "is not available on PATH"
                ),
            }
        if not Path(manager_executable).is_file():
            return {
                "should_update": False,
                "reason": (
                    "cannot update command package because "
                    f"`{manager_executable}` is not a file"
                ),
            }
        if not Path(reentry_command[-1]).is_file():
            return {
                "should_update": False,
                "reason": (
                    "cannot re-enter the updated command package because "
                    "its launcher is missing"
                ),
            }
        try:
            update_command = _package_manager_update_command(
                package_manager,
                manager_executable,
                runtime=runtime,
            )
        except OmhError as exc:
            return {
                "should_update": False,
                "reason": str(exc),
            }
        return {
            "should_update": True,
            "method": "package_manager",
            "package_manager": package_manager,
            "update_instruction": update_instruction,
            "update_command": update_command,
            "reentry_command": reentry_command,
            "reason": f"running from the {package_manager} command package",
        }
    managed = _managed_command_runtime()
    if not managed["managed"]:
        return {"should_update": False, "reason": managed["reason"]}
    return {
        "should_update": True,
        "method": "installer",
        "release": release,
        "python": managed["python"],
        "venv_dir": managed["venv_dir"],
        "reason": "running from installer-managed command package venv",
    }


def _run_command_package_self_update(args: argparse.Namespace, plan: dict[str, object]) -> int:
    if plan.get("method") == "package_manager":
        return _run_package_manager_self_update(args, plan)
    # Installer-owned packages are never mutated in place.  The transaction
    # stages command and workflow-pack bytes together, then flips one pointer.
    from ..install.self_update import run_installer_self_update

    result = run_installer_self_update(args, plan, runner=subprocess.run)
    if _wants_json(args):
        _print_json(result)
    elif result.get("ok"):
        print("OMH update complete: command and workflow pack activated together.")
    else:
        print(f"OMH update stopped during {result.get('phase')}; the known-good generation remains active.")
    return 0 if result.get("ok") else 1


def _run_package_manager_self_update(
    args: argparse.Namespace,
    plan: dict[str, object],
) -> int:
    package_manager = str(plan["package_manager"])
    update_instruction = str(plan["update_instruction"])
    update_command = list(cast(list[str], plan["update_command"]))
    reentry_command = list(cast(list[str], plan["reentry_command"]))
    wants_json = _wants_json(args)
    progress = _HumanProgress(enabled=not wants_json, use_color=_use_color())
    progress.header("OMH update", "Refresh the OMH command package and workflow pack.")
    progress.step(
        1,
        2,
        "Updating omh command package",
        detail=update_instruction,
    )
    completed = subprocess.run(
        update_command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        detail = _bounded_command_error(
            completed.stderr
            or completed.stdout
            or f"{package_manager} update failed"
        )
        raise OmhError(f"command package update failed: {detail}")
    progress.done("command package updated")
    if not wants_json:
        progress.step(2, 2, "Refreshing OMH workflows with the updated command")
    argv = _reentry_argv_with_command_package_updated()
    env = dict(os.environ)
    env[SELF_UPDATE_REENTRY_ENV] = "1"
    rerun = subprocess.run([*reentry_command, *argv], env=env)
    return int(rerun.returncode)


def _validated_command_package_launcher(
    package_manager: str,
) -> dict[str, Path] | None:
    if package_manager not in {"npm", "bun"}:
        return None
    raw_root = os.environ.get(COMMAND_PACKAGE_ROOT_ENV, "")
    raw_runtime = os.environ.get(COMMAND_PACKAGE_RUNTIME_ENV, "")
    raw_entrypoint = os.environ.get(COMMAND_PACKAGE_ENTRYPOINT_ENV, "")
    if not raw_root or not raw_runtime or not raw_entrypoint:
        return None
    try:
        package_root = Path(raw_root).resolve(strict=True)
        runtime = Path(raw_runtime).resolve(strict=True)
        entrypoint = Path(raw_entrypoint).resolve(strict=True)
        expected_entrypoint = (package_root / "bin" / "omh.js").resolve(
            strict=True
        )
        package_manifest = json.loads(
            (package_root / "package.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not package_root.is_dir()
        or not runtime.is_file()
        or not entrypoint.is_file()
        or entrypoint != expected_entrypoint
        or package_manifest.get("name") != "oh-my-hermes"
        or package_manifest.get("version") != __version__
        or package_manifest.get("bin", {}).get("omh") != "bin/omh.js"
    ):
        return None
    return {
        "package_root": package_root,
        "runtime": runtime,
        "entrypoint": entrypoint,
    }


def _validated_homebrew_commands() -> dict[str, Path] | None:
    homebrew_root = _homebrew_prefix_root()
    if homebrew_root is None:
        return None
    brew = homebrew_root / "bin" / "brew"
    omh = homebrew_root / "bin" / "omh"
    try:
        cellar_omh = (homebrew_root / "Cellar" / "omh").resolve(strict=True)
        installed_omh = omh.resolve(strict=True)
    except OSError:
        return None
    if (
        not brew.is_file()
        or not installed_omh.is_file()
        or not installed_omh.is_relative_to(cellar_omh)
    ):
        return None
    return {"brew": brew, "omh": omh}


def _package_manager_update_command(
    package_manager: str,
    executable: str,
    *,
    runtime: str,
    platform: str = os.name,
) -> list[str]:
    arguments = COMMAND_PACKAGE_UPDATE_ARGUMENTS[package_manager]
    executable_path = Path(executable)
    if platform != "nt" or executable_path.suffix.casefold() not in {
        ".bat",
        ".cmd",
    }:
        return [str(executable_path), *arguments]
    if package_manager != "npm" or not runtime:
        raise OmhError(
            f"cannot safely execute the Windows `{package_manager}` command shim"
        )
    npm_cli = (
        executable_path.parent
        / "node_modules"
        / "npm"
        / "bin"
        / "npm-cli.js"
    )
    if not npm_cli.is_file():
        raise OmhError("cannot locate npm-cli.js beside the Windows npm shim")
    return [runtime, str(npm_cli), *arguments]


def _bounded_command_error(value: str, *, limit: int = 2_000) -> str:
    sanitized = ANSI_ESCAPE_RE.sub("", value)
    sanitized = "".join(
        character
        for character in sanitized
        if character in {"\n", "\t"} or ord(character) >= 32
    ).strip()
    if len(sanitized) <= limit:
        return sanitized
    return f"{sanitized[:limit]}…"


def _reentry_argv_with_command_package_updated() -> list[str]:
    argv = list(sys.argv[1:])
    if "--command-package-updated" not in argv:
        argv.append("--command-package-updated")
    return argv


def _managed_command_runtime() -> dict[str, object]:
    venv_dir = managed_command_venv_dir()
    if venv_dir is None:
        return {"managed": False, "reason": "no home directory or OMH_VENV_DIR is available"}
    executable = Path(sys.executable).expanduser()
    if not _is_relative_to_without_resolving_symlinks(executable, venv_dir) and managed_generation_for_executable(executable) is None:
        return {
            "managed": False,
            "reason": "current omh command is not running from the installer-managed OMH venv",
            "python": str(executable.resolve()),
            "venv_dir": str(venv_dir),
        }
    return {"managed": True, "reason": "", "python": str(executable), "venv_dir": str(venv_dir)}


def _is_relative_to_without_resolving_symlinks(path: Path, parent: Path) -> bool:
    try:
        _normalize_without_final_symlink(path).relative_to(_normalize_without_final_symlink(parent))
    except ValueError:
        return False
    return True


def _normalize_without_final_symlink(path: Path) -> Path:
    expanded = path.expanduser()
    return expanded.parent.resolve() / expanded.name


def _install_operation(args: argparse.Namespace) -> str:
    command = str(getattr(args, "command", "install"))
    return command if command in {"convert", "update"} else "install"


def _managed_skills_status(result: dict[str, object], *, dry_run: bool) -> dict[str, object]:
    skills = result.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    return {
        "schema_version": "managed_skills_status/v1",
        "status": "would_update" if dry_run else "updated",
        "count": len(skills),
        "skills_dir": str(result.get("skills_dir", "")),
    }


def _command_package_status_for_install(
    *,
    operation: str,
    source: str,
    dry_run: bool,
    command_package_updated: bool = False,
) -> dict[str, object]:
    package_manager, update_instruction = _command_package_update_guidance()
    status = "unchanged"
    reason = "managed skills were refreshed from the currently installed command package"
    updated = False
    if command_package_updated:
        status = "would_update" if dry_run else "updated"
        updated = not dry_run
        reason = (
            f"{package_manager} refreshed the OMH command package before "
            "running this command"
        )
    elif dry_run:
        status = "would_remain_unchanged"
        reason = "dry run previews managed skill changes without changing the command package"
    elif operation == "update" and source == "builtin":
        status = "not_updated"
        reason = "managed skills were refreshed, but the omh command package was not updated in this run"
    elif source != "builtin":
        reason = "managed skills were refreshed from an explicit skill source; the command package was not changed"
    return {
        "schema_version": COMMAND_PACKAGE_STATUS_SCHEMA_VERSION,
        "operation": operation,
        "status": status,
        "updated": updated,
        "source": _command_package_source(command_package_updated=command_package_updated, source=source),
        "reason": reason,
        "package_manager": package_manager,
        "update_instruction": update_instruction,
    }


def _command_package_source(*, command_package_updated: bool, source: str) -> str:
    if command_package_updated:
        return _command_package_update_guidance()[0]
    if source == "builtin":
        return "installed_command_package"
    return "explicit_skill_source"


def _release_source_ref(args: argparse.Namespace, release) -> str:
    explicit = str(getattr(args, "source_ref", "") or "").strip()
    if explicit:
        return explicit
    return str(getattr(release, "source_label", "") or "").strip()


def _release_source_commit_for_state(paths, release) -> str:
    """Best-effort remote `main` sha, recorded only when update-check is opted in.

    This is the comparable local identity `omh update-check`'s startup probe
    (`maintenance/update_check.py`) compares against a fresh remote read.
    Piggybacks on this already-explicit `omh install`/`omh update` invocation
    rather than adding a second, unscoped network surface (AGENTS.md
    Implementation Boundaries): a network call rides along only when the user
    has already opted update-check away from its shipped `off` default.
    Scoped to the preview channel, the one that actually tracks `main` -- a
    pinned stable tag or a local source is not meaningfully "behind main".
    Silent no-op (returns "") on any failure; this metadata must never fail
    the install/update command it rides along with.

    Advance policy (issue #1282): the cursor advances only under a replayable
    gap policy. `cursor_advance_allowed` reads the update-check cache (no
    network) and refuses while a coverage gap is open and unaccepted or the
    recorded ancestry is not a verified `fast_forward`, so `omh update` never
    re-anchors `release_source_commit` across a failed required source read;
    a completed recovery or an explicit `omh update-check accept-gap` re-arms
    it. The gate is checked before the recording probe so a blocked advance
    spends no network attempt.
    """
    if release.source_label != "main":
        return ""
    from ..maintenance.update_check import (
        cursor_advance_allowed,
        read_update_check_policy,
        record_remote_commit_for_install,
    )

    if read_update_check_policy(paths)["mode"] == "off":
        return ""
    if not cursor_advance_allowed(paths):
        return ""
    return record_remote_commit_for_install(paths)


def _explicit_release_metadata_supplied(args: argparse.Namespace) -> bool:
    return any(
        str(getattr(args, key, "") or "").strip()
        for key in ("source_ref", "version", "package_url")
    )


def _resolved_skill_profile(args: argparse.Namespace, paths) -> str:
    """The profile this run should record: what was asked for, else what is installed.

    This used to be `"full" if --full else "core"`, which reset the recorded
    profile on every run. An operator who installed the full catalog and then
    ran plain `omh update` had their manifest rewritten to `core` while all the
    full-only skills stayed on disk -- installs never delete -- so the install
    reported a profile it did not have and told them to run `omh skill-profile
    reconcile` to resolve a divergence nothing had asked for.

    An update carries the install forward. Only `--full` and an explicit
    reconcile change the profile, and reconcile stays the one path that deletes.
    """
    if bool(getattr(args, "core", False)):
        return "core"
    if bool(getattr(args, "full", False)):
        return "full"
    installed = str((read_manifest(paths.manifest_path) or {}).get("skill_profile") or "")
    return installed if installed in SKILL_PROFILES else DEFAULT_SKILL_PROFILE


def _previous_manifest_sha256(paths) -> str:
    state, _ = read_state_result(paths)
    return _string_value((state or {}).get("manifest_sha256"))


def _workflow_content_status(paths, previous_sha256: str, *, dry_run: bool) -> dict[str, object]:
    """Whether this run changed the installed workflow content.

    On the preview channel the version does not move between updates, so the
    version line alone cannot answer "did anything change?". The manifest hash
    can, without a network call: it is already recorded on every install.
    """

    if dry_run:
        return {"known": False, "reason": "dry run does not write the manifest"}
    try:
        current_sha256 = sha256_file(paths.manifest_path)
    except OSError:
        return {"known": False, "reason": "manifest is not readable"}
    if not previous_sha256:
        return {"known": False, "reason": "no previous manifest hash was recorded", "current_sha256": current_sha256}
    return {
        "known": True,
        "changed": previous_sha256 != current_sha256,
        "previous_sha256": previous_sha256,
        "current_sha256": current_sha256,
    }


def _previous_release_update_state(paths) -> dict[str, object]:
    state, _ = read_state_result(paths)
    state = state or {}
    candidates = [state.get("release_update"), state, state.get("last_update"), state.get("last_install")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if isinstance(candidate.get("current"), dict):
            return candidate["current"]
        release_update = candidate.get("release_update")
        if isinstance(release_update, dict) and isinstance(release_update.get("current"), dict):
            return release_update["current"]
        if any(
            candidate.get(key)
            for key in ("release_channel", "release_version", "release_package_url", "release_source_ref")
        ):
            return candidate
    return {}


def _release_update_status(
    *,
    release_channel: str,
    release_version: str,
    release_package_url: str,
    source_ref: str,
    explicit_metadata: bool,
    previous: dict[str, object],
    command_package: dict[str, object],
    dry_run: bool,
) -> dict[str, object]:
    previous_channel = _string_value(previous.get("release_channel") or previous.get("channel"))
    previous_version = _string_value(previous.get("release_version") or previous.get("version"))
    previous_package_url = _string_value(previous.get("release_package_url") or previous.get("package_url"))
    previous_ref = _string_value(previous.get("release_source_ref") or previous.get("source_ref"))
    previous_package_version = _string_value(previous.get("package_version"))
    current = {
        "release_channel": release_channel,
        "release_version": release_version,
        "release_package_url": release_package_url,
        "release_source_ref": source_ref,
        "package_version": __version__,
    }
    previous_effective_version = _effective_release_version(
        {"release_version": previous_version, "package_version": previous_package_version}
    )
    current_effective_version = _effective_release_version(current)
    command_status = str(command_package.get("status", ""))
    command_package_changed = bool(command_package.get("updated")) or command_status == "would_update"
    metadata_changed = any(
        [
            _metadata_value_changed(previous_channel, release_channel, explicit=explicit_metadata),
            _metadata_value_changed(previous_version, release_version, explicit=explicit_metadata),
            _metadata_value_changed(previous_package_url, release_package_url, explicit=explicit_metadata),
            _metadata_value_changed(previous_ref, source_ref, explicit=explicit_metadata),
        ]
    )
    changed = command_package_changed or metadata_changed
    if dry_run:
        if command_package_changed:
            status = "would_update"
        elif metadata_changed:
            status = "would_record_metadata"
        else:
            status = "would_refresh"
    elif command_package_changed:
        status = "updated"
    elif metadata_changed:
        status = "metadata_recorded"
    else:
        status = "refreshed"
    return {
        "schema_version": RELEASE_UPDATE_SCHEMA_VERSION,
        "status": status,
        "changed": changed,
        "command_package_changed": command_package_changed,
        "metadata_changed": metadata_changed,
        "previous": {
            "release_channel": previous_channel,
            "release_version": previous_version,
            "release_package_url": previous_package_url,
            "release_source_ref": previous_ref,
            "package_version": previous_package_version,
        },
        "current": current,
        "display": {
            "version_change": _change_label(previous_effective_version, current_effective_version),
            "source_ref_change": _change_label(previous_ref, source_ref),
            "package_url_change": _change_label(previous_package_url, release_package_url),
        },
    }


def _string_value(value: object) -> str:
    return str(value or "").strip()


def _metadata_value_changed(previous: str, current: str, *, explicit: bool) -> bool:
    if explicit and current:
        return previous != current
    return bool(previous and previous != current)


def _effective_release_version(release: dict[str, object]) -> str:
    """Version to show a user for one release record.

    `release_version` is only populated when the operator pinned one, which in
    practice means the stable channel. Preview installs track a branch archive and
    leave it empty, so fall back to the package version the command itself reports.
    Without this an update reads `main -> main` and hides the upgrade that happened.
    """

    if not isinstance(release, dict):
        return ""
    pinned = _string_value(release.get("release_version") or release.get("version"))
    if pinned:
        return pinned
    return _string_value(release.get("package_version"))


def _change_label(previous: str, current: str) -> str:
    if previous and current:
        return f"{previous} -> {current}"
    if current:
        return f"(none) -> {current}"
    if previous:
        return f"{previous} -> (none)"
    return ""


def _install_operation_log(result: dict[str, object], *, source: str) -> dict[str, object]:
    managed_skills = result.get("managed_skills", {})
    command_package = result.get("command_package", {})
    release_update = result.get("release_update", {})
    return {
        "operation": str(result.get("operation", "")),
        "source": source,
        "release_channel": str(result.get("release_channel", "")),
        "release_version": str(result.get("release_version", "")),
        "release_package_url": str(result.get("release_package_url", "")),
        "release_source_ref": str(result.get("release_source_ref", "")),
        "release_update": release_update if isinstance(release_update, dict) else {},
        "managed_skills": managed_skills if isinstance(managed_skills, dict) else {},
        "command_package": command_package if isinstance(command_package, dict) else {},
    }


def _setup_operator_summary(
    args: argparse.Namespace,
    paths,
    steps: dict[str, object],
    hermes_native: dict[str, object],
) -> dict[str, object]:
    dry_run = bool(getattr(args, "dry_run", False))
    status = "dry_run" if dry_run else "skills_only" if getattr(args, "skip_apply", False) else "configured"
    plugin = steps.get("plugin", {})
    plugin_status = str(plugin.get("status", "installed")) if isinstance(plugin, dict) else "installed"
    menubar = steps.get("menubar", {})
    menubar_status = str(menubar.get("status", "not_requested")) if isinstance(menubar, dict) else "not_requested"
    team_status = "profile_pack" if getattr(args, "profile_pack", []) else "available"
    mcp = steps.get("mcp", {})
    mcp_mode = str(mcp.get("mode", "none")) if isinstance(mcp, dict) else "none"
    mcp_host_config = mcp.get("host_config", {}) if isinstance(mcp, dict) else {}
    mcp_host_config_status = str(mcp_host_config.get("status", "not_requested")) if isinstance(mcp_host_config, dict) else "not_requested"
    profile = steps.get("profile", {})
    operating_model_id = str(profile.get("operating_model_id", "")) if isinstance(profile, dict) else ""
    memory_policy = profile.get("memory_policy", {}) if isinstance(profile, dict) else {}
    memory_mode = str(memory_policy.get("mode", profile.get("memory_mode", "review-first"))) if isinstance(memory_policy, dict) else "review-first"
    summary = {
        "schema_version": SETUP_OPERATOR_SUMMARY_SCHEMA_VERSION,
        "scope": _setup_scope(args),
        "install_mode": "managed_skills",
        "mcp_mode": mcp_mode,
        "mcp_host": str(mcp.get("host", "generic")) if isinstance(mcp, dict) else "generic",
        "mcp_host_config_status": mcp_host_config_status,
        "mcp_host_config_path": str(mcp_host_config.get("path", "")) if isinstance(mcp_host_config, dict) else "",
        "plugin_mode": plugin_status,
        "menubar_mode": menubar_status,
        "team_mode": team_status,
        "operating_model_id": operating_model_id,
        "memory_mode": memory_mode,
        "memory_policy": memory_policy if isinstance(memory_policy, dict) else {},
        "parallelism": profile.get("parallelism", {}) if isinstance(profile, dict) else {},
        "status": status,
        "requires_hermes_reload": bool(hermes_native.get("requires_hermes_reload", False)),
        "paths": {
            "omh_home": str(paths.omh_home),
            "hermes_home": str(paths.hermes_home),
            "skills_dir": str(paths.skills_dir),
            "hermes_config_path": str(paths.hermes_config_path),
        },
        "command_path": inspect_omh_command_path(),
        "state_log": {},
    }
    if not dry_run:
        summary["state_log"] = {"path": str(paths.runtime_state_path), "entry": "last_setup"}
    install = steps.get("install", {})
    if isinstance(install, dict):
        managed_skills = install.get("managed_skills", {})
        if isinstance(managed_skills, dict):
            summary["managed_skills"] = managed_skills
    return summary


def _setup_scope(args: argparse.Namespace) -> str:
    if getattr(args, "omh_home", None) or getattr(args, "hermes_home", None):
        return "custom"
    return "project" if str(getattr(args, "scope", "") or "").strip().lower() == "project" else "user"


def _doctor_operator_summary(checks: list[object]) -> dict[str, object]:
    check_dicts = [
        {
            "name": str(getattr(check, "name", "")),
            "ok": bool(getattr(check, "ok", False)),
            "severity": str(getattr(check, "severity", "")),
        }
        for check in checks
    ]
    passing = sum(1 for check in check_dicts if check["ok"])
    blocking = sum(1 for check in check_dicts if not check["ok"] and check["severity"] == "blocking")
    warnings = sum(1 for check in check_dicts if check["severity"] == "warning")
    return {
        "schema_version": DOCTOR_SUMMARY_SCHEMA_VERSION,
        "status": "ok" if doctor_ok(checks) else "needs_attention",
        "passing": passing,
        "total": len(check_dicts),
        "blocking": blocking,
        "warnings": warnings,
        "groups": [
            _doctor_group("command", check_dicts, ("command_path",)),
            _doctor_group("managed_skills", check_dicts, ("manifest", "manifest_skills_dir", "local_modifications", "skill_freshness", "skills_dir", "skill:", "guidance_projection")),
            _doctor_group("runtime", check_dicts, ("runtime_artifacts", "workflow_state", "runtime_state")),
            _doctor_group("hermes_registration", check_dicts, ("hermes_config", "external_dir", "identity_conflicts", "runtime_context")),
            _doctor_group("targets", check_dicts, ("target_registry", "target_topology")),
            _doctor_group("optional_surfaces", check_dicts, ("plugin_", "team_profile_packs", "structural_search", "trigger_language_packs")),
        ],
    }


def _doctor_group(name: str, checks: list[dict[str, object]], prefixes: tuple[str, ...]) -> dict[str, object]:
    members = [
        check
        for check in checks
        if any(str(check.get("name", "")).startswith(prefix) for prefix in prefixes)
    ]
    failed = [check for check in members if not check.get("ok")]
    warning = any(str(check.get("severity", "")) == "warning" for check in members)
    status = "needs_attention" if failed else "warning" if warning else "ok"
    return {
        "name": name,
        "status": status,
        "passing": sum(1 for check in members if check.get("ok")),
        "total": len(members),
        "failed": [str(check.get("name", "")) for check in failed],
    }


def _command_package_status_for_uninstall(result: dict[str, object]) -> dict[str, object]:
    removed = _string_list(result.get("command_package_removed_paths", []))
    would_remove = _string_list(result.get("command_package_would_remove", []))
    kept = result.get("command_package_kept", [])
    kept_items = kept if isinstance(kept, list) else []
    removal_requested = bool(result.get("command_package_remove_requested", False))
    dry_run = bool(result.get("dry_run", False))

    if dry_run and would_remove:
        status = "would_remove"
        reason = "dry run found installer-managed command package paths"
    elif removed:
        status = "removed"
        reason = "removed installer-managed command package paths"
    elif kept_items:
        status = "kept"
        reason = _first_kept_reason(kept_items)
    elif removal_requested:
        status = "not_found"
        reason = "command package removal was requested, but no installer-managed command package paths were found"
    else:
        status = "not_requested"
        reason = "command package removal was not requested"

    return {
        "schema_version": COMMAND_PACKAGE_STATUS_SCHEMA_VERSION,
        "operation": "uninstall",
        "status": status,
        "removal_requested": removal_requested,
        "removed": bool(removed),
        "would_remove": bool(would_remove),
        "kept": bool(kept_items),
        "reason": reason,
        "remaining_command_instruction": tr(
            str(result.get("language", "en")),
            "uninstall_command_still_available",
        )
        if kept_items
        else "",
    }


def _first_kept_reason(items: list[object]) -> str:
    for item in items:
        if isinstance(item, dict):
            reason = str(item.get("reason", "")).strip()
            if reason:
                return reason
    return "command package was not removed"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def cmd_convert(args: argparse.Namespace) -> int:
    args.source = args.from_skills_dir
    args.channel = "local"
    args.version = ""
    args.package_url = ""
    return cmd_install(args)


def cmd_apply(args: argparse.Namespace) -> int:
    result = _apply_result(args)
    if _wants_json(args):
        _print_json(result)
    else:
        _print_apply_summary(result)
    return 0


def _apply_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    memory_mode = str(getattr(args, "memory_mode", "") or "") or "review-first"
    current = read_config(paths.hermes_config_path)
    try:
        change = ensure_external_dir(current, _registered_workflow_dir(paths))
        compression = ensure_compression_defaults(change.text)
        # Installing the bridge and switching it on are separate steps in
        # Hermes. Doing only the first leaves an install that passes every
        # structural check while no OMH tool is reachable in chat.
        plugin_enable = ensure_plugin_enabled(compression.text, PLUGIN_NAME)
        # Fresh installs default to the one branded surface the product
        # promises: bare `omh` and bare `hermes` both enter Hermes' modern TUI,
        # where the OMH HUD can render. Existing explicit choices are preserved
        # unless the operator accepts the setup/update prompt; that consent
        # allows stock `cli`/`default` values to be migrated too.
        tui_choice = getattr(args, "_omh_tui_choice", None)
        if tui_choice is False:
            tui_interface = ConfigChange(
                False,
                "operator declined the OH-MY-HERMES modern TUI",
                plugin_enable.text,
            )
            skin_active = ConfigChange(
                False,
                "operator declined the OH-MY-HERMES skin",
                tui_interface.text,
            )
        elif tui_choice is True:
            tui_interface = activate_tui_interface(plugin_enable.text)
            # Accepting the branded TUI must not undo a theme choice: an
            # operator on `omh-crimson` who says yes to the modern TUI keeps
            # crimson. Only a non-OMH or unset skin resolves to the default.
            chosen_skin = display_skin_selection(tui_interface.text)
            skin_active = activate_omh_skin(
                tui_interface.text,
                chosen_skin if is_omh_skin_name(chosen_skin) else SKIN_NAME,
            )
        else:
            tui_interface = ensure_tui_interface(plugin_enable.text)
            skin_active = ensure_omh_skin(tui_interface.text, SKIN_NAME)
        # Same reasoning one layer down. OMH's memory provider ships inside the
        # bundle, and a provider Hermes never selects is a provider that never
        # runs -- so requiring a control-plane command to switch it on meant the
        # people AGENTS.md says should only need setup/update/doctor would never
        # have it. Claims the slot only when it is free; `set_memory_provider`
        # refuses when another product holds it, because Hermes runs exactly one.
        memory_provider = maybe_set_memory_provider(skin_active.text, MEMORY_PROVIDER_NAME, memory_mode)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and (
        change.changed
        or compression.changed
        or plugin_enable.changed
        or tui_interface.changed
        or skin_active.changed
        or memory_provider.changed
    ):
        write_config(paths.hermes_config_path, memory_provider.text)
    if not args.dry_run:
        update_state(
            paths,
            {
                "hermes_config_path": str(paths.hermes_config_path),
                "last_applied_skills_dir": str(_registered_workflow_dir(paths)),
                "external_dir_registered": _external_dir_registered(
                    read_config(paths.hermes_config_path),
                    _registered_workflow_dir(paths),
                ),
            },
        )
    return {
        "changed": (
            change.changed
            or compression.changed
            or plugin_enable.changed
            or tui_interface.changed
            or skin_active.changed
            or memory_provider.changed
        ),
        "message": change.message,
        "config": str(paths.hermes_config_path),
        "skills_dir": str(paths.skills_dir),
        "dry_run": args.dry_run,
        "compression_defaults": {"changed": compression.changed, "message": compression.message},
        "plugin_enabled": {"changed": plugin_enable.changed, "message": plugin_enable.message},
        "tui_interface": {
            "changed": tui_interface.changed,
            "message": tui_interface.message,
            "selected": display_interface_selection(memory_provider.text),
        },
        "skin": {
            "changed": skin_active.changed,
            "message": skin_active.message,
            "selected": display_skin_selection(memory_provider.text),
        },
        "memory_provider": {
            "changed": memory_provider.changed,
            "message": memory_provider.message,
            "selected": memory_provider_selection(memory_provider.text),
        },
    }


def cmd_uninstall(args: argparse.Namespace) -> int:
    language = _resolve_language(args)
    if args.registration_only and (args.remove_files or args.all or args.purge):
        raise OmhError("--registration-only cannot be combined with --remove-files, --all, or --purge")
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = remove_external_dir(current, _registered_workflow_dir(paths))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    remove_all = bool(args.all or args.purge or (not args.registration_only and not args.remove_files))
    menubar_result = (
        uninstall_menubar_app(paths, dry_run=bool(args.dry_run))
        if remove_all and _uninstall_should_remove_menubar(args)
        else {"status": "not_requested", "operation": "uninstall"}
    )
    result = uninstall_skill_pack(
        paths,
        remove_files=bool(args.remove_files),
        remove_all=remove_all,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
        remove_command_package=bool(remove_all and not args.keep_command),
    )
    tui_widget_result = (
        uninstall_tui_widget(paths.hermes_home, dry_run=bool(args.dry_run))
        if remove_all
        else {"status": "not_requested"}
    )
    skin_result = (
        uninstall_skin(paths.hermes_home, dry_run=bool(args.dry_run))
        if remove_all
        else {"status": "not_requested"}
    )
    profile_results = _uninstall_hermes_profiles(args, remove_all=remove_all)
    scope = (
        tr(language, "uninstall_scope_all")
        if remove_all
        else tr(language, "uninstall_scope_files")
        if args.remove_files
        else tr(language, "uninstall_scope_registration")
    )
    result.update(
        {
            "operation": "uninstall",
            "config_changed": change.changed,
            "config_message": change.message,
            "scope": scope,
            "registration_only": bool(args.registration_only),
            "dry_run": args.dry_run,
            "menubar_app": menubar_result,
            "tui_widget": tui_widget_result,
            "skin": skin_result,
            "language": language,
        }
    )
    if profile_results:
        result["hermes_profiles"] = profile_results
    result["command_package"] = _command_package_status_for_uninstall(result)
    if _wants_json(args):
        _print_json(result)
    else:
        _print_uninstall_summary(result, language=language)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    paths = _paths(args)
    manifest = read_manifest(paths.manifest_path)
    payload = _catalog_aware_list_payload(manifest)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_list_summary(payload, manifest_path=paths.manifest_path, skills_dir=paths.skills_dir)
    return 0


def cmd_skill_profile_status(args: argparse.Namespace) -> int:
    payload = skill_profile_report(_paths(args))
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_skill_profile_status_summary(payload)
    return 0


def cmd_skill_profile_reconcile(args: argparse.Namespace) -> int:
    paths = _paths(args)
    payload = reconcile_skill_profile(
        paths,
        target_profile=str(getattr(args, "to", "core")),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if not payload.get("dry_run"):
        state = payload.get("profile_state_after", {})
        update_state(
            paths,
            {
                "manifest_path": str(paths.manifest_path),
                "manifest_sha256": sha256_file(paths.manifest_path),
                "installed_skills": state.get("installed_skill_count", 0) if isinstance(state, dict) else 0,
                "skills_dir": str(paths.skills_dir),
                "last_skill_profile_reconcile": {
                    "target_profile": payload.get("target_profile", ""),
                    "removed_skills": payload.get("removed_skills", []),
                    "retained_skills": payload.get("retained_skills", []),
                    "effective_profile": state.get("effective_profile", "") if isinstance(state, dict) else "",
                },
            },
        )
        payload["runtime_state_path"] = str(paths.runtime_state_path)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_skill_profile_reconcile_summary(payload)
    return 0


def _print_skill_profile_status_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    state = payload.get("profile_state", {})
    if not isinstance(state, dict):
        state = {}
    print(_color("OMH skill profile", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    if not payload.get("installed"):
        print("  Status: not installed")
        print(f"  Manifest: {payload.get('manifest_path', '')}")
        print(_color("Next", "1;32", use_color))
        print("  Run `omh setup` to install managed Hermes skills.")
        return
    print(f"  Requested profile: {state.get('requested_profile', '') or 'unrecorded'}")
    print(f"  Effective profile: {state.get('effective_profile', '')}")
    print(
        f"  Installed skills: {state.get('installed_catalog_skill_count', 0)} catalog "
        f"(core profile is {state.get('core_profile_skill_count', 0)}, "
        f"full profile is {state.get('full_profile_skill_count', 0)})"
    )
    full_only = state.get("full_only_installed_skills", [])
    if isinstance(full_only, list) and full_only:
        print(f"  Full-only skills installed: {len(full_only)}")
    unmanaged_count = state.get("unmanaged_skill_count", 0)
    if isinstance(unmanaged_count, int) and unmanaged_count:
        print(f"  Non-catalog skill directories: {unmanaged_count}")
    retained = payload.get("retained_skills", [])
    if isinstance(retained, list) and retained:
        print(_color("Retained by reconcile", "1;33", use_color))
        for item in retained[:12]:
            if isinstance(item, dict):
                print(f"  - {item.get('name', '')}: {item.get('reason', '')}")
    print(_color("Context cost", "1;32", use_color))
    print(f"  {state.get('context_cost_note', '')}")
    print(f"  {state.get('non_destructive_default', '')}")
    print(_color("Next", "1;32", use_color))
    reconcilable = payload.get("reconcilable_skills", [])
    if isinstance(reconcilable, list) and reconcilable:
        print(f"  Run `{SKILL_PROFILE_RECONCILE_COMMAND} --dry-run` to preview removing {len(reconcilable)} skill(s).")
    else:
        print("  Nothing to reconcile; the installed skills already match the recorded profile.")


def _print_skill_profile_reconcile_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    dry_run = bool(payload.get("dry_run"))
    title = "OMH skill profile reconcile preview" if dry_run else "OMH skill profile reconciled"
    removed = payload.get("would_remove_skills" if dry_run else "removed_skills", [])
    if not isinstance(removed, list):
        removed = []
    before = payload.get("profile_state_before", {})
    after = payload.get("profile_state_after", before)
    if not isinstance(before, dict):
        before = {}
    if not isinstance(after, dict):
        after = {}
    print(_color(title, "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Target profile: {payload.get('target_profile', '')}")
    print(f"  Effective profile before: {before.get('effective_profile', '')}")
    if not dry_run:
        print(f"  Effective profile after: {after.get('effective_profile', '')}")
    verb = "Would remove" if dry_run else "Removed"
    print(f"  {verb}: {len(removed)} unmodified managed full-only skill(s)")
    if removed:
        shown = [str(name) for name in removed[:12]]
        print("  Names: " + ", ".join(shown) + (" ..." if len(removed) > len(shown) else ""))
    retained = payload.get("retained_skills", [])
    if isinstance(retained, list) and retained:
        print(_color("Retained", "1;33", use_color))
        for item in retained[:12]:
            if isinstance(item, dict):
                print(f"  - {item.get('name', '')}: {item.get('reason', '')}")
    print(_color("Context cost", "1;32", use_color))
    print(f"  {payload.get('context_cost_note', '')}")
    print(f"  {payload.get('non_destructive_default', '')}")
    print(_color("Next", "1;32", use_color))
    if dry_run:
        print(f"  Rerun without `--dry-run` to apply: `{SKILL_PROFILE_RECONCILE_COMMAND}`.")
    else:
        print("  Restart or reload Hermes Agent so it picks up the smaller skill set.")


def cmd_doctor(args: argparse.Namespace) -> int:
    language = _resolve_language(args)
    payload = _doctor_result(args)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_doctor_summary(payload, language=language)
    return 0 if payload["ok"] else 1


def _catalog_aware_list_payload(manifest: dict[str, object] | None) -> dict[str, object]:
    payload = dict(manifest or {"schema_version": 1, "skills": [], "message": "not installed"})
    raw_skills = payload.get("skills", [])
    if not isinstance(raw_skills, list):
        raw_skills = []
    capabilities = {
        str(item.get("id")): item
        for item in skill_capabilities()
        if isinstance(item, dict) and item.get("id")
    }
    enriched_skills: list[dict[str, object]] = []
    for raw_skill in raw_skills:
        if not isinstance(raw_skill, dict):
            continue
        record = dict(raw_skill)
        capability = capabilities.get(str(record.get("name") or ""))
        if capability:
            record.update(_list_skill_catalog_fields(capability))
        enriched_skills.append(record)
    payload["skills"] = enriched_skills
    payload["catalog_context"] = _list_catalog_context(enriched_skills)
    return payload


def _list_skill_catalog_fields(capability: dict[str, object]) -> dict[str, object]:
    fields = {
        "description": capability.get("description", ""),
        "category": capability.get("category", ""),
        "phase": capability.get("phase", ""),
        "hermes_role": capability.get("hermes_role", ""),
        "use_for": capability.get("use_for", ""),
        "preferred_usage": capability.get("preferred_usage", ""),
        "awareness_lane": capability.get("awareness_lane", ""),
        "awareness_lane_label": capability.get("awareness_lane_label", ""),
        "workflow_routing_hint": capability.get("workflow_routing_hint", ""),
        "handoff_policy": capability.get("handoff_policy", ""),
        "evidence_boundary": capability.get("evidence_boundary", ""),
    }
    triggers = capability.get("triggers", [])
    if isinstance(triggers, list):
        fields["triggers"] = [str(item) for item in triggers[:10] if str(item)]
    required_inputs = capability.get("required_inputs", [])
    if isinstance(required_inputs, list):
        fields["required_inputs"] = [str(item) for item in required_inputs[:8] if str(item)]
    expected_outputs = capability.get("expected_outputs", [])
    if isinstance(expected_outputs, list):
        fields["expected_outputs"] = [str(item) for item in expected_outputs[:8] if str(item)]
    return fields


def _list_catalog_context(skills: list[dict[str, object]]) -> dict[str, object]:
    names = {str(skill.get("name") or "") for skill in skills}
    described_count = sum(1 for skill in skills if skill.get("description"))
    summary = capability_summary()
    lanes = []
    for lane in summary.get("lanes", []):
        if not isinstance(lane, dict):
            continue
        lane_skills = [str(skill) for skill in lane.get("primary_skills", []) if str(skill) in names]
        if not lane_skills:
            continue
        lanes.append(
            {
                "id": lane.get("id", ""),
                "label": lane.get("label", ""),
                "owner_role": lane.get("owner_role", ""),
                "use_for": lane.get("use_for", ""),
                "primary_skills": lane_skills,
                "examples": lane.get("examples", []),
            }
        )
    return {
        "schema_version": "omh_installed_skill_catalog_context/v1",
        "purpose": (
            "Hermes-facing context for answering what installed OMH workflows are available "
            "without asking the user to approve extra shell catalog commands."
        ),
        "skill_count": len(skills),
        "described_skill_count": described_count,
        "lanes": lanes,
        "direct_response_guidance": [
            "Summarize workflow lanes before listing every skill.",
            "Offer `./omh` or the matching clean skill name when the user wants to choose manually.",
            "Use workflow_routing_hint and evidence_boundary before claiming execution or runtime evidence.",
        ],
        "evidence_boundary": summary.get("evidence_boundary", ""),
    }


def _doctor_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    checks = run_doctor(paths)
    next_action = recommended_next_action(checks)
    summary = _doctor_operator_summary(checks)
    runtime_writable = any(check.name == "runtime_artifacts" and check.ok for check in checks)
    runtime_state_readable = not any(check.name == "runtime_state" and not check.ok for check in checks)
    state_log: dict[str, str] = {}
    if runtime_writable and runtime_state_readable:
        update_state(
            paths,
            {
                "last_doctor": {
                    "ok": doctor_ok(checks),
                    "checks": {check.name: check.ok for check in checks},
                    "summary": summary,
                    "recommended_next_action": next_action,
                }
            },
        )
        state_log = {"path": str(paths.runtime_state_path), "entry": "last_doctor"}
    advisories = run_doctor_advisories(paths)
    return {
        "ok": doctor_ok(checks),
        "checks": [check.__dict__ for check in checks],
        "summary": summary,
        "state_log": state_log,
        "recommended_next_action": next_action,
        "advisories": advisories.to_dict(),
        # Diagnostic provenance for the command that produced this report. It
        # is deliberately not a doctor check: an installed artifact with no
        # stamped identity is a normal state, not a health failure, so it must
        # not move the doctor status, the issue counts, or the exit code.
        "build_identity": probe_build_identity(),
        "language": _resolve_language(args),
    }


def cmd_setup(args: argparse.Namespace) -> int:
    args.with_plugin = True
    validate_model_setup_args(args)
    language = _setup_language(args)
    paths = _paths(args)
    _preset_tui_identity_choice(args)
    if _setup_should_interact(args):
        if not _setup_paths_were_explicit(args) and not getattr(args, "scope", None):
            args.scope = _ask_setup_scope(use_color=_use_color(), language=language)
            paths = _paths(args)
        _run_setup_wizard(args, paths, language)
    if getattr(args, "star", False):
        _star_github_repo(language=language, use_color=_use_color(), dry_run=bool(args.dry_run))
    if not args.with_mcp and (
        str(getattr(args, "mcp_host", "generic") or "generic") != "generic"
        or getattr(args, "mcp_config_path", None)
    ):
        raise OmhError("--mcp-host and --mcp-config-path require --with-mcp.")

    progress = _HumanProgress(enabled=not _wants_json(args), use_color=_use_color())
    if not _wants_json(args):
        progress.header(tr(language, "setup_title"), tr(language, "setup_subtitle"))
    setup_menubar = _setup_should_attempt_menubar(args)
    total_steps = 5 + (1 if args.with_mcp else 0) + (1 if args.profile_pack else 0) + (1 if setup_menubar else 0)
    step_index = 1

    progress.step(step_index, total_steps, tr(language, "step_install_skills"), detail=str(paths.skills_dir))
    steps: dict[str, object] = {"install": _install_result(args)}
    install_skills = steps["install"].get("skills", []) if isinstance(steps["install"], dict) else []
    progress.done(tr(language, "done_skills_installed", count=len(install_skills) if isinstance(install_skills, list) else 0))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_register"), detail=str(paths.hermes_config_path))
    if args.skip_apply:
        steps["apply"] = {"skipped": True, "message": "Skipped Hermes config registration because --skip-apply was set."}
        progress.skip(tr(language, "skip_by_flag", flag="--skip-apply"))
    else:
        steps["apply"] = _apply_result(args)
        apply_message = steps["apply"].get("message", "configured") if isinstance(steps["apply"], dict) else "configured"
        progress.done(_config_change_label(language, str(apply_message)))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_plugin"), detail=str(paths.hermes_plugin_dir))
    steps["plugin"] = _plugin_setup_result(args, paths)
    steps["tui_widget"] = install_tui_widget(paths.hermes_home, dry_run=bool(args.dry_run))
    # The OMH identity skin ships next to the widget: same managed-artifact
    # discipline, same refresh cadence. Activation happens in the config
    # apply step (`ensure_omh_skin`), never here.
    steps["skin"] = install_skin(paths.hermes_home, dry_run=bool(args.dry_run))
    # Every install gets the editable mixture-chain override document so
    # customizing routing is a config edit, not a source edit.
    steps["model_chains"] = _seed_model_chains_result(paths, dry_run=bool(args.dry_run))
    # Bot profiles are independent Hermes homes under <hermes_home>/profiles;
    # registering only the primary home is why bot chats saw zero OMH skills.
    steps["hermes_profiles"] = _sync_hermes_profiles(args) if not args.skip_apply else []
    steps["hermes_tui_preflight"] = _hermes_tui_preflight_step(
        paths, quiet=_wants_json(args), dry_run=bool(args.dry_run)
    )
    plugin_status = steps["plugin"].get("status", "installed") if isinstance(steps["plugin"], dict) else "installed"
    progress.done(_plugin_status_label(language, str(plugin_status)))
    step_index += 1

    if setup_menubar:
        progress.step(step_index, total_steps, tr(language, "step_menubar"), detail=str(paths.omh_home / "menubar"))
        steps["menubar"] = _menubar_setup_result(args, paths)
        menubar_status = str(steps["menubar"].get("status", "unknown")) if isinstance(steps["menubar"], dict) else "unknown"
        if menubar_status in {"running", "installed", "dry_run"}:
            progress.done(_menubar_status_label(language, menubar_status))
        else:
            reason = str(steps["menubar"].get("reason", menubar_status)) if isinstance(steps["menubar"], dict) else menubar_status
            progress.skip(reason)
        step_index += 1
    else:
        steps["menubar"] = {"schema_version": "menubar_app/v1", "status": "not_requested"}

    steps["mcp"] = _mcp_setup_result(args, paths)
    if args.with_mcp:
        progress.step(step_index, total_steps, tr(language, "step_mcp"), detail=str(paths.runtime_state_path))
        mcp_status = steps["mcp"].get("status", "bridge_requested") if isinstance(steps["mcp"], dict) else "bridge_requested"
        progress.done(tr(language, "done_mcp_bridge", status=_mcp_status_label(language, str(mcp_status))))
        step_index += 1

    if args.profile_pack:
        progress.step(step_index, total_steps, tr(language, "step_team"), detail=", ".join(args.profile_pack))
        steps["team_profiles"] = _team_profile_setup_result(args, paths)
        progress.done(
            tr(language, "done_profile_packs", count=len(steps["team_profiles"]) if isinstance(steps["team_profiles"], list) else 0)
        )
        step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_preferences"))
    steps["profile"] = _setup_profile_result(args, paths)
    profile_executor = steps["profile"].get("default_executor", "choose") if isinstance(steps["profile"], dict) else "choose"
    progress.done(tr(language, "done_default_executor", executor=_executor_summary(language, str(profile_executor))))
    step_index += 1

    progress.step(step_index, total_steps, tr(language, "step_targets"))
    steps["targets"] = record_target_observation(
        paths,
        source="setup",
        dry_run=args.dry_run,
        ensure_config=not args.skip_apply,
        setup_context={
            "apply_skipped": bool(args.skip_apply),
            "with_plugin": True,
            "with_menubar": bool(setup_menubar),
            "with_mcp": bool(args.with_mcp),
            "profile_packs": list(args.profile_pack),
            "setup_profiles": list(args.profile),
            "default_executor": str(getattr(args, "default_executor", "") or ""),
            "operating_model": str(getattr(args, "operating_model", "") or ""),
            "memory_mode": str(getattr(args, "memory_mode", "") or "review-first"),
        },
    )
    target_topology = steps["targets"].get("topology", {}) if isinstance(steps["targets"], dict) else {}
    if isinstance(target_topology, dict):
        progress.done(
            tr(
                language,
                "done_target_topology",
                mode=target_topology.get("mode", "unknown"),
                count=target_topology.get("known_target_count", 0),
            )
        )
    else:
        progress.done(tr(language, "target_recorded"))
    if getattr(args, "model_setup", False):
        dependencies = _model_setup_flow_dependencies()
        steps["model_activation"] = model_activation_result(
            args,
            language=language,
            dependencies=dependencies,
        )
        if not _wants_json(args):
            print_model_activation_summary(
                steps["model_activation"],
                language=language,
                use_color=_use_color,
                color=_color,
            )
    if args.dry_run:
        bootstrap_final_state = (
            "dry run would install generated skills and register the managed OMH skills directory for Hermes discovery"
            if not args.skip_apply
            else "dry run would install generated skills, but Hermes discovery registration would be skipped"
        )
    elif args.skip_apply:
        bootstrap_final_state = "generated skills are installed, but Hermes discovery registration was skipped"
    else:
        bootstrap_final_state = "generated skills are installed in the managed OMH skills directory and registered for Hermes discovery"
    discovery_status = (
        "dry_run_not_observed"
        if args.dry_run
        else "not_registered_skip_apply"
        if args.skip_apply
        else "config_registered_reload_required"
    )
    hermes_native = {
        "schema_version": "hermes_native_setup/v1",
        "mode": "omh_bootstrap",
        "dry_run": bool(args.dry_run),
        "observed": not args.dry_run and not args.skip_apply,
        "observed_scope": "local install/apply steps only; this does not prove Hermes reloaded or used the skill",
        "discovery_status": discovery_status,
        "requires_hermes_reload": not args.skip_apply,
        "normal_user_surface": "Hermes Agent chat and installed Hermes skills",
        "setup_scope": _setup_scope(args),
        "equivalent_hermes_commands": [
            "hermes skills tap add rlaope/oh-my-hermes",
            "hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes",
        ],
        "bootstrap_final_state": bootstrap_final_state,
        "skills_dir": str(paths.skills_dir),
        "hermes_config_path": str(paths.hermes_config_path),
        "hermes_config_key": "skills.external_dirs",
        "mcp_setup": steps["mcp"],
        "target_topology": steps["targets"]["topology"],
        "wrapper_backend_surface": "omh chat interact and runtime commands are adapter/operator contracts, not the normal chat UX",
    }

    if not args.dry_run:
        operator_summary = _setup_operator_summary(args, paths, steps, hermes_native)
        state_patch: dict[str, object] = {
            "last_setup": {
                "ok": True,
                "apply_skipped": bool(args.skip_apply),
                "hermes_native": hermes_native,
                "operator_summary": operator_summary,
                "setup_profile": steps["profile"],
                "mcp_setup": steps["mcp"],
                "menubar_app": steps["menubar"],
                "team_profiles": steps.get("team_profiles", []),
                "target_observation": steps["targets"],
            }
        }
        durable_mcp_host_config = _durable_mcp_host_config_record(steps["mcp"])
        if durable_mcp_host_config:
            state_patch["last_mcp_host_config_install"] = durable_mcp_host_config
        update_state(paths, state_patch)
    else:
        operator_summary = _setup_operator_summary(args, paths, steps, hermes_native)
    payload: dict[str, object] = {
        "ok": True,
        "steps": steps,
        "dry_run": args.dry_run,
        "hermes_native": hermes_native,
        "operator_summary": operator_summary,
        "language": language,
    }
    payload["plugin_distribution"] = steps["plugin"]
    if steps.get("hermes_profiles"):
        payload["hermes_profiles"] = steps["hermes_profiles"]
    if args.profile_pack:
        payload["team_profiles"] = steps["team_profiles"]
    if not args.dry_run:
        payload["tui_verdict"] = _tui_verdict_payload(args)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_setup_summary(payload, language=language)
    return 0


def _setup_should_interact(args: argparse.Namespace) -> bool:
    if _wants_json(args) or getattr(args, "dry_run", False):
        return False
    if getattr(args, "interactive", False):
        return True
    if getattr(args, "no_interactive", False) or getattr(args, "yes", False):
        return False
    if (
        args.profile
        or getattr(args, "default_executor", None)
        or args.profile_pack
        or args.with_mcp
        or getattr(args, "memory_mode", None)
        or getattr(args, "with_menubar", False)
        or getattr(args, "no_menubar", False)
        or args.skip_apply
        or getattr(args, "scope", None)
        or getattr(args, "model_setup", False)
    ):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _update_should_interact(args: argparse.Namespace) -> bool:
    if not hasattr(args, "omh_home") or not hasattr(args, "hermes_home"):
        return False
    if getattr(args, "from_skills_dir", None) or getattr(args, "source", None):
        return False
    if _wants_json(args) or getattr(args, "dry_run", False):
        return False
    if getattr(args, "interactive", False):
        return True
    if (
        getattr(args, "no_interactive", False)
        or getattr(args, "yes", False)
        or getattr(args, "no_omh_tui", False)
    ):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _preset_tui_identity_choice(args: argparse.Namespace) -> None:
    if getattr(args, "no_omh_tui", False):
        args._omh_tui_choice = False
    elif getattr(args, "yes", False):
        args._omh_tui_choice = True


def _ask_tui_identity_choice(args: argparse.Namespace, paths: OmhPaths, language: str) -> None:
    if hasattr(args, "_omh_tui_choice"):
        return
    config_text = read_config(paths.hermes_config_path)
    # Any shipped theme counts as identity-active: asking a crimson user to
    # switch to the default skin is asking them to lose a choice they made.
    selected_skin = display_skin_selection(config_text)
    if display_interface_selection(config_text) == "tui" and is_omh_skin_name(selected_skin):
        return
    target_skin = selected_skin if is_omh_skin_name(selected_skin) else SKIN_NAME
    if (
        not activate_tui_interface(config_text).changed
        and not activate_omh_skin(config_text, target_skin).changed
    ):
        return
    args._omh_tui_choice = _ask_yes_no(
        tr(language, "tui_identity_prompt"),
        default=True,
        use_color=_use_color(),
        note=tr(language, "tui_identity_note"),
        language=language,
    )


# Binary name per external CLI profile, read-only PATH lookup only -- never
# invoked. Mirrors `_COMMANDS` in `coding/executor_readiness.py` (that table
# is module-private and also carries runtime-only profiles setup never asks
# about); kept as its own small map so this file does not reach into another
# module's private state for two literals that are unlikely to drift.
_EXTERNAL_CLI_BINARY_BY_PROFILE: dict[str, str] = {"claude-code": "claude", "codex": "codex"}


def _detect_external_cli_profiles(home: Path | None = None) -> dict[str, dict[str, object]]:
    """Read-only, no-invoke detection for the two external coding CLIs.

    A binary on PATH plus a local auth/config marker is `prepared` evidence,
    never `observed` (READINESS_EVIDENCE_RULE in `coding/coding_delegation.py`):
    this never runs either CLI, so "detected" means the binary resolves on
    PATH, and the login marker only refines the printed label.
    """
    detected: dict[str, dict[str, object]] = {}
    for profile in EXTERNAL_CLI_PROFILES:
        command = _EXTERNAL_CLI_BINARY_BY_PROFILE[profile]
        signal = auth_signal_for_profile(profile, home=home)
        detected[profile] = {
            "binary_present": shutil.which(command) is not None,
            "login_marker": signal.get("login_marker", "unknown"),
        }
    return detected


def _ask_maestro_delegation_choice(args: argparse.Namespace, paths: OmhPaths, language: str) -> None:
    """Ask, at most once, whether to set up the maestro coding-delegation lane.

    Only reached from the interactive wizard (`_setup_should_interact`), so
    `--yes`, `--no-interactive`, `--json`, and non-TTY runs never see this
    question and never mutate anything here. No CLI is ever invoked to answer
    it -- see `_detect_external_cli_profiles`. A "no" or no detected CLI
    changes nothing and prints nothing persistent.
    """
    if hasattr(args, "_maestro_delegation_choice"):
        return
    detected = _detect_external_cli_profiles()
    detected_profiles = [profile for profile in EXTERNAL_CLI_PROFILES if detected[profile]["binary_present"]]
    if not detected_profiles:
        args._maestro_delegation_choice = None
        return
    accepted = _ask_yes_no(
        tr(language, "maestro_delegation_prompt", clis=", ".join(detected_profiles)),
        default=False,
        use_color=_use_color(),
        note=tr(language, "maestro_delegation_note"),
        language=language,
    )
    args._maestro_delegation_choice = accepted
    if not accepted:
        return
    seed_result = _seed_dispatch_model_preferences_result(paths, dry_run=False)
    print(tr(language, "maestro_delegation_seeded", path=str(seed_result.get("path", ""))))
    print(tr(language, "maestro_delegation_pointers"))
    # The category dial is the part of the lane worth configuring during
    # install: offer the guided walk right here. A "no" changes nothing —
    # the built-in category table stays in effect until the operator opts in.
    if _ask_yes_no(
        tr(language, "maestro_category_prompt"),
        default=False,
        use_color=_use_color(),
        note=tr(language, "maestro_category_note"),
        language=language,
    ):
        from .coding import category_maestro_interview

        category_maestro_interview(paths)


# Env-key hints for Hermes' builtin providers. Hermes reaches these through a
# key in `$HERMES_HOME/.env` (or the process environment) rather than through
# a `providers:` block, so config keys alone never surface them. Only the
# variable NAME is read — never its value — and every hint is still confirmed
# by the operator before it is recorded. Kinds are the entitlement vocabulary.
_ENV_KEY_PROVIDER_HINTS: dict[str, tuple[str, str]] = {
    "ANTHROPIC_API_KEY": ("anthropic", "anthropic"),
    "OPENAI_API_KEY": ("openai", "openai"),
    "OPENROUTER_API_KEY": ("openrouter", "openrouter"),
    "OPENGATEWAY_API_KEY": ("opengateway", "gateway"),
    "ZAI_API_KEY": ("zai", "zai"),
    "DEEPSEEK_API_KEY": ("deepseek", "deepseek"),
    "XAI_API_KEY": ("xai", "xai"),
    "GEMINI_API_KEY": ("gemini", "gemini"),
    "GOOGLE_API_KEY": ("google", "google"),
    "MOONSHOT_API_KEY": ("kimi-coding", "kimi-coding"),
    "QWEN_API_KEY": ("qwen", "qwen-oauth"),
}
# `model.provider: auto` is Hermes' resolution mode, not an account.
_NON_PROVIDER_IDS = frozenset({"auto"})


def _env_key_names(paths: OmhPaths) -> set[str]:
    """Variable NAMES present in `$HERMES_HOME/.env` or the environment; no values."""
    names = {name for name in os.environ if name in _ENV_KEY_PROVIDER_HINTS}
    env_path = paths.hermes_home / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return names
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        name, separator, _value = stripped.partition("=")
        if separator and name.strip() in _ENV_KEY_PROVIDER_HINTS:
            names.add(name.strip())
    return names


def _provider_candidates(paths: OmhPaths) -> list[tuple[str, str]]:
    """Provider ids worth asking about, each with its default kind, in ask order.

    Config keys first (`providers.<id>`, `model.provider`) with `gateway` as
    the default kind, then env-key hints with their vendor kind. Ids that the
    entitlement document would reject (non-token keys such as YAML merge
    markers) and Hermes' `auto` mode are skipped rather than asked.
    """
    from ..plugin_bundle.omh.hermes_delegation import PROVIDER_KIND_GATEWAY, is_provider_id_token

    config_text = read_config(paths.hermes_config_path) if paths.hermes_config_path.exists() else ""
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for provider_id in configured_provider_ids(config_text):
        if provider_id in _NON_PROVIDER_IDS or not is_provider_id_token(provider_id) or provider_id in seen:
            continue
        seen.add(provider_id)
        candidates.append((provider_id, PROVIDER_KIND_GATEWAY))
    for name in sorted(_env_key_names(paths)):
        provider_id, kind = _ENV_KEY_PROVIDER_HINTS[name]
        if provider_id in seen:
            continue
        seen.add(provider_id)
        candidates.append((provider_id, kind))
    return candidates


def _ask_provider_entitlements(args: argparse.Namespace, paths: OmhPaths, language: str) -> None:
    """Ask, at most once, which providers and subscription CLIs this machine holds.

    Every account is different, and the shipped chains cannot know which of
    their entries this operator can actually reach. The answer is recorded as
    `~/.omh/routing/providers.json` (provider id -> kind, plus the confirmed
    subscription CLIs); `effective_mixture_category_chains` then reorders each
    chain so the reachable entries lead, without dropping anything. Only the
    interactive wizard reaches this: `--yes`, `--no-interactive`, `--json`,
    and runs without `--interactive` on a non-TTY ask nothing and write
    nothing. Detection is read-only (config keys, env-key names, PATH
    presence); no provider or CLI is invoked.

    A confirmed Claude Code subscription is a Maestro-lane entitlement: the
    Hermes lane cannot spend it (Hermes needs an API provider), so the only
    routing consequence is the Claude Code `--model` preference, seeded to the
    Claude chain head when the operator has not set one.
    """
    if hasattr(args, "_provider_entitlements"):
        return
    from ..plugin_bundle.omh.hermes_delegation import (
        MULTI_VENDOR_PROVIDER_KINDS,
        PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
        PROVIDER_FAMILY_VOCABULARY,
        PROVIDER_KIND_GATEWAY,
        PROVIDER_KIND_UNKNOWN,
        SUBSCRIPTION_CLI_PROFILES,
        is_provider_id_token,
        load_provider_entitlements,
        provider_entitlements_path,
    )

    existing, existing_status = load_provider_entitlements(paths.omh_home)
    candidates = _provider_candidates(paths)
    detected = _detect_external_cli_profiles()
    detected_profiles = [
        profile
        for profile in SUBSCRIPTION_CLI_PROFILES
        if detected.get(profile, {}).get("binary_present")
    ]
    if not candidates and not detected_profiles:
        args._provider_entitlements = None
        return
    use_color = _use_color()
    if existing_status.startswith("invalid:"):
        print(_color(tr(language, "provider_entitlements_invalid", status=existing_status), "33", use_color))
    if not _ask_yes_no(
        tr(language, "provider_entitlements_prompt"),
        default=existing_status != "applied",
        use_color=use_color,
        note=tr(language, "provider_entitlements_note"),
        language=language,
    ):
        args._provider_entitlements = None
        return

    previous_providers = dict(existing.get("providers", {})) if existing else {}
    previous_clis = list(existing.get("subscription_clis", [])) if existing else []
    kinds = (PROVIDER_KIND_GATEWAY, *PROVIDER_FAMILY_VOCABULARY, PROVIDER_KIND_UNKNOWN)
    kind_options = [
        {
            "choice": str(index + 1),
            "value": kind,
            "label": kind,
            "description": tr(language, "provider_kind_relay") if kind in MULTI_VENDOR_PROVIDER_KINDS else "",
        }
        for index, kind in enumerate(kinds)
    ]

    def ask_kind(provider_id: str, default_kind: str) -> str:
        default_choice = next(option["choice"] for option in kind_options if option["value"] == default_kind)
        return _ask_single_choice(
            tr(language, "provider_kind_title", provider=provider_id),
            [tr(language, "provider_kind_intro")],
            kind_options,
            default_choice=default_choice,
            use_color=use_color,
            language=language,
        )

    providers: dict[str, str] = {}
    for provider_id, hinted_kind in candidates:
        if _ask_yes_no(
            tr(language, "provider_hold_prompt", provider=provider_id),
            default=provider_id in previous_providers or not previous_providers,
            use_color=use_color,
            language=language,
        ):
            providers[provider_id] = ask_kind(provider_id, previous_providers.get(provider_id, hinted_kind))
    # Providers Hermes reaches some other way (a builtin with a key OMH does
    # not recognize, a gateway named only in a route) can be added by name.
    while True:
        extra = _ask(tr(language, "provider_add_prompt"), default="", use_color=use_color).strip()
        if not extra:
            break
        if extra in providers or not is_provider_id_token(extra):
            print(_color(tr(language, "provider_add_rejected", provider=extra), "31", use_color))
            continue
        providers[extra] = ask_kind(extra, previous_providers.get(extra, PROVIDER_KIND_GATEWAY))
    subscription_clis: list[str] = []
    for profile in detected_profiles:
        if _ask_yes_no(
            tr(language, "subscription_cli_prompt", cli=profile),
            default=profile in previous_clis or not previous_clis,
            use_color=use_color,
            note=tr(language, "subscription_cli_note"),
            language=language,
        ):
            subscription_clis.append(profile)

    document = {
        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
        "providers": providers,
        "subscription_clis": subscription_clis,
    }
    path = provider_entitlements_path(paths.omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    args._provider_entitlements = document
    print(tr(language, "provider_entitlements_recorded", path=str(path)))
    if "claude-code" in subscription_clis:
        seed = _seed_claude_code_dispatch_head(paths)
        status = str(seed.get("status", ""))
        if status == "seeded":
            print(tr(language, "claude_code_dispatch_seeded", model=str(seed.get("model", "")), path=str(seed.get("path", ""))))
        elif status == "already_present":
            print(tr(language, "claude_code_dispatch_kept", path=str(seed.get("path", ""))))
        else:
            print(_color(tr(language, "claude_code_dispatch_unreadable", path=str(seed.get("path", ""))), "33", use_color))


def _seed_claude_code_dispatch_head(paths: OmhPaths) -> dict[str, object]:
    """Point the Claude Code profile's `--model` at the Claude chain head, once.

    Only a confirmed Claude Code subscription reaches here. An existing
    `claude-code` entry, whatever its value, is never overwritten; an existing
    file without one gains the entry. A file the dispatch reader would not
    accept (wrong or missing `schema_version`, `profiles` not an object,
    unparsable) is left alone and reported as `unreadable`, so the seed is
    never a write the reader ignores. The value is the head of the Maestro
    lane's Claude chain, so it moves with the shipped chain rather than being
    a second place to maintain.
    """
    from ..coding.model_routing import CLAUDE_FRONTIER_CHAIN_MODELS

    path = dispatch_model_preferences_path(paths.omh_home)
    payload: dict[str, object] = {"path": str(path), "model": CLAUDE_FRONTIER_CHAIN_MODELS[0]}
    document: dict[str, object] = {
        "schema_version": DISPATCH_MODEL_PREFERENCE_SCHEMA_VERSION,
        "profiles": {},
    }
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload["status"] = "unreadable"
            return payload
        if (
            not isinstance(loaded, dict)
            or loaded.get("schema_version") != DISPATCH_MODEL_PREFERENCE_SCHEMA_VERSION
            or not isinstance(loaded.get("profiles"), dict)
        ):
            payload["status"] = "unreadable"
            return payload
        document = loaded
    profiles = document["profiles"]
    assert isinstance(profiles, dict)
    if str(profiles.get("claude-code", "") or "").strip():
        payload["status"] = "already_present"
        return payload
    profiles["claude-code"] = CLAUDE_FRONTIER_CHAIN_MODELS[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    payload["status"] = "seeded"
    return payload


def _seed_dispatch_model_preferences_result(paths: OmhPaths, *, dry_run: bool) -> dict[str, object]:
    """Seed the optional per-owner dispatch-model preference document, if absent.

    This document is otherwise operator-edited only -- nothing else seeds or
    writes it automatically. An explicit "yes" to the maestro-delegation setup
    question is the only caller, and only when the file does not already
    exist; an existing file, however it got there, is never overwritten.
    """
    path = dispatch_model_preferences_path(paths.omh_home)
    payload: dict[str, object] = {
        "schema_version": "dispatch_model_preference_seed/v1",
        "path": str(path),
        "dry_run": bool(dry_run),
    }
    if path.exists():
        payload["status"] = "already_present"
        return payload
    if dry_run:
        payload["status"] = "dry_run"
        return payload
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": DISPATCH_MODEL_PREFERENCE_SCHEMA_VERSION,
        "profiles": {},
    }
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    payload["status"] = "seeded"
    return payload


def _print_model_preview_review(payload: dict[str, object], *, language: str) -> None:
    print_model_preview_review(
        payload,
        language=language,
        use_color=_use_color,
        color=_color,
    )


def _model_setup_flow_dependencies() -> ModelSetupFlowDependencies:
    return ModelSetupFlowDependencies(
        discover_local_models=discover_local_models,
        inspect_hermes_model_config=inspect_hermes_model_config,
        preview_hermes_model_config=preview_hermes_model_config,
        apply_hermes_model_config=apply_hermes_model_config,
        resolve_model_recommendation=resolve_model_recommendation,
        ask_yes_no=_ask_yes_no,
        ask=_ask,
        use_color=_use_color,
        print_model_preview_review=_print_model_preview_review,
    )


def _setup_should_attempt_menubar(args: argparse.Namespace) -> bool:
    if getattr(args, "no_menubar", False):
        return False
    if getattr(args, "with_menubar", False):
        return True
    if os.environ.get("OMH_MENUBAR", "1") == "0":
        return False
    if _wants_json(args) or getattr(args, "dry_run", False):
        return False
    if _setup_scope(args) != "user":
        return False
    if _setup_paths_were_explicit(args):
        return False
    return sys.platform == "darwin"


def _uninstall_should_remove_menubar(args: argparse.Namespace) -> bool:
    return _setup_scope(args) == "user" and not _setup_paths_were_explicit(args)


def _resolve_language(args: argparse.Namespace) -> str:
    raw = getattr(args, "language", None)
    try:
        return normalize_language(raw) if raw else language_from_env()
    except ValueError as exc:
        raise OmhError(str(exc)) from exc


def _setup_language(args: argparse.Namespace) -> str:
    # English-first product surface: localized output is explicit opt-in via
    # --language or OMH_LANG, never inferred from the OS locale.
    if _language_was_explicit(args):
        return _resolve_language(args)
    return "en"


def _language_was_explicit(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "language", None) or os.environ.get("OMH_LANG") or os.environ.get("OMH_LANGUAGE"))


def _setup_paths_were_explicit(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "omh_home", None) or getattr(args, "hermes_home", None))


def _ask_setup_scope(*, use_color: bool, language: str) -> str:
    return _ask_single_choice(
        tr(language, "scope_title"),
        [
            tr(language, "scope_intro_1"),
            tr(language, "scope_intro_2"),
        ],
        [
            {
                "choice": "1",
                "value": "user",
                "label": tr(language, "scope_user_label"),
                "description": tr(language, "scope_user_desc"),
            },
            {
                "choice": "2",
                "value": "project",
                "label": tr(language, "scope_project_label"),
                "description": tr(language, "scope_project_desc"),
            },
        ],
        default_choice="1",
        use_color=use_color,
        language=language,
    )


def _run_setup_wizard(args: argparse.Namespace, paths, language: str) -> None:
    use_color = _use_color()
    explicit_profile_packs = list(getattr(args, "profile_pack", []) or [])
    print(_color(tr(language, "setup_title"), "1;36", use_color))
    print(tr(language, "wizard_subtitle"))
    print(f"{tr(language, 'hermes_home')}: {_color(str(paths.hermes_home), '36', use_color)}")
    if paths.hermes_config_path.exists():
        config_text = read_config(paths.hermes_config_path)
        registered = paths.skills_dir.as_posix() in external_dirs(config_text)
        status = tr(language, "status_already_registered") if registered else tr(language, "status_will_register")
        print(f"{tr(language, 'hermes_config')}: {_color(str(paths.hermes_config_path), '36', use_color)} ({status})")
    else:
        print(f"{tr(language, 'hermes_config')}: {_color(str(paths.hermes_config_path), '36', use_color)} ({tr(language, 'status_will_create')})")
    print(f"{tr(language, 'managed_skills')}: {_color(str(paths.skills_dir), '36', use_color)}")
    _ask_tui_identity_choice(args, paths, language)
    _ask_maestro_delegation_choice(args, paths, language)
    _ask_provider_entitlements(args, paths, language)

    if not args.profile and not getattr(args, "default_executor", None):
        # No upfront coding-owner question: safety-first records "choose" so
        # Hermes asks at the first coding request instead of setup time.
        args.profile = ["safety-first"]
    if args.with_mcp and str(getattr(args, "mcp_host", "generic") or "generic") == "generic":
        args.mcp_host = _ask_mcp_host(
            use_color=use_color,
            language=language,
            default_host=_default_mcp_host_for_executor(str(getattr(args, "default_executor", "") or "")),
        )
    args.profile_pack = explicit_profile_packs
    print("")


def _star_github_repo(*, language: str, use_color: bool, dry_run: bool = False) -> None:
    if dry_run:
        print(_color(tr(language, "github_star_dry_run"), "33", use_color))
        print("")
        return
    result = _try_star_github_repo()
    if result["ok"]:
        print(_color(tr(language, "github_star_thanks"), "1;32", use_color))
    else:
        reason = str(result.get("reason") or "GitHub star was not recorded")
        print(_color(tr(language, "github_star_failed", reason=reason), "33", use_color))
        print(tr(language, "github_star_continue"))
    print("")


def _try_star_github_repo() -> dict[str, object]:
    command = ["gh", "api", "-X", "PUT", "/user/starred/rlaope/oh-my-hermes"]
    try:
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except FileNotFoundError:
        return {"ok": False, "reason": "GitHub CLI `gh` is not installed or not on PATH."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "GitHub CLI star command timed out."}
    except OSError as exc:
        return {"ok": False, "reason": f"GitHub CLI could not run: {exc}"}
    if completed.returncode == 0:
        return {"ok": True, "reason": "starred_or_already_starred"}
    detail = (completed.stderr or completed.stdout or "gh repo star failed").strip()
    return {"ok": False, "reason": detail}


def _ask_mcp_host(*, use_color: bool, language: str, default_host: str = "generic") -> str:
    options = [
        {"choice": "1", "value": "generic", "label": "Generic MCP", "description": tr(language, "mcp_host_generic_desc")},
        {"choice": "2", "value": "codex", "label": "Codex", "description": tr(language, "mcp_host_codex_desc")},
        {"choice": "3", "value": "claude-code", "label": "Claude Code", "description": tr(language, "mcp_host_claude_desc")},
        {"choice": "4", "value": "opencode", "label": "OpenCode", "description": tr(language, "mcp_host_opencode_desc")},
        {"choice": "5", "value": "cursor", "label": "Cursor", "description": tr(language, "mcp_host_cursor_desc")},
    ]
    default_choice = next((option["choice"] for option in options if option["value"] == default_host), "1")
    return _ask_single_choice(
        tr(language, "mcp_host_title"),
        [tr(language, "mcp_host_intro")],
        options,
        default_choice=default_choice,
        use_color=use_color,
        language=language,
    )


def _default_mcp_host_for_executor(executor: str) -> str:
    normalized = executor.strip().lower()
    if normalized == "codex":
        return "codex"
    if normalized == "claude-code":
        return "claude-code"
    return "generic"


def _ask_yes_no(prompt: str, *, default: bool, use_color: bool, note: str = "", language: str = "en") -> bool:
    if _keyboard_menu_available():
        value = _ask_single_choice(
            prompt,
            [note] if note else [],
            [
                {"choice": "1", "value": "yes", "label": tr(language, "yes"), "description": tr(language, "yes_desc")},
                {"choice": "2", "value": "no", "label": tr(language, "no"), "description": tr(language, "no_desc")},
            ],
            default_choice="1" if default else "2",
            use_color=use_color,
            language=language,
        )
        return value == "yes"
    suffix = "Y/n" if default else "y/N"
    if note:
        print(f"  {note}")
    while True:
        value = _ask(prompt, default=suffix, use_color=use_color).strip().lower()
        if not value or value == suffix.lower():
            return default
        if value in {"y", "yes", "1", "예", "네", "はい", "是"}:
            return True
        if value in {"n", "no", "2", "아니요", "いいえ", "否"}:
            return False
        print(_color(tr(language, "invalid_yes_no"), "31", use_color))


def _ask_single_choice(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    *,
    default_choice: str,
    use_color: bool,
    language: str = "en",
) -> str:
    normalized = [_normalize_choice_option(option) for option in options]
    if _keyboard_menu_available():
        return _keyboard_single_choice(title, intro_lines, normalized, default_choice=default_choice, use_color=use_color, language=language)

    print("")
    print(_color(title, "1;32", use_color))
    for line in intro_lines:
        print(f"  {line}")
    for option in normalized:
        suffix = f" ({tr(language, 'recommended')})" if option["choice"] == default_choice else ""
        print(f"  {option['choice']}) {option['label']}{suffix}")
        if option["description"]:
            print(f"     {option['description']}")
    values_by_choice = {option["choice"]: option["value"] for option in normalized}
    values_by_value = {option["value"]: option["value"] for option in normalized}
    while True:
        raw = _ask(tr(language, "select"), default=default_choice, use_color=use_color).strip()
        value = raw or default_choice
        if value in values_by_choice:
            return values_by_choice[value]
        if value in values_by_value:
            return values_by_value[value]
        valid = ", ".join(option["choice"] for option in normalized)
        print(_color(tr(language, "invalid_selection", valid=valid), "31", use_color))


def _normalize_choice_option(option: dict[str, str]) -> dict[str, str]:
    return {
        "choice": str(option.get("choice", "")).strip(),
        "value": str(option.get("value", "")).strip(),
        "label": str(option.get("label", "")).strip(),
        "description": str(option.get("description", "")).strip(),
    }


def _keyboard_single_choice(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    *,
    default_choice: str,
    use_color: bool,
    language: str = "en",
) -> str:
    cursor = _default_choice_index(options, default_choice)
    rendered_option_rows = 0
    first_render = True
    while True:
        lines = _choice_menu_lines(
            title,
            intro_lines,
            options,
            cursor,
            default_choice=default_choice,
            use_color=use_color,
            language=language,
        )
        option_lines = _choice_menu_option_lines(lines, intro_lines)
        if first_render:
            sys.stdout.write("\n".join(lines) + "\n")
            first_render = False
        else:
            sys.stdout.write(f"\033[{rendered_option_rows}F\033[J")
            sys.stdout.write("\n".join(option_lines) + "\n")
        sys.stdout.flush()
        rendered_option_rows = _rendered_terminal_rows(option_lines)
        key = _read_tui_key()
        if key in {"\x03", "\x04"}:
            raise KeyboardInterrupt
        if key in {"\x1b[A", "k"}:
            cursor = (cursor - 1) % len(options)
            continue
        if key in {"\x1b[B", "j"}:
            cursor = (cursor + 1) % len(options)
            continue
        if key in {"\r", "\n", " "}:
            return options[cursor]["value"]
        for index, option in enumerate(options):
            if key == option["choice"]:
                cursor = index
                return option["value"]


def _choice_menu_lines(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    cursor: int,
    *,
    default_choice: str,
    use_color: bool,
    language: str = "en",
) -> list[str]:
    lines = ["", _color(title, "1;32", use_color)]
    for line in intro_lines:
        lines.append(f"  {line}")
    lines.append(_color(f"  {tr(language, 'menu_hint')}", "2", use_color))
    for index, option in enumerate(options):
        active = index == cursor
        pointer = ">" if active else " "
        suffix = f" ({tr(language, 'recommended')})" if option["choice"] == default_choice else ""
        label = f"  {pointer} {option['choice']}) {option['label']}{suffix}"
        if active:
            label = _color(label, "1;36", use_color)
        lines.append(label)
        if option["description"]:
            lines.append(f"      {option['description']}")
    return lines


def _choice_menu_option_lines(lines: list[str], intro_lines: list[str]) -> list[str]:
    option_start = 3 + len(intro_lines)
    return lines[option_start:]


def _rendered_terminal_rows(lines: list[str], columns: int | None = None) -> int:
    if columns is None:
        columns = shutil.get_terminal_size((80, 24)).columns
    columns = max(1, columns)
    rows = 0
    for line in lines:
        width = _visible_text_width(line)
        rows += max(1, (width + columns - 1) // columns)
    return rows


def _visible_text_width(text: str) -> int:
    visible = ANSI_ESCAPE_RE.sub("", text)
    width = 0
    for character in visible:
        if unicodedata.combining(character):
            continue
        category = unicodedata.category(character)
        if category in {"Cc", "Cf"}:
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
    return width


def _default_choice_index(options: list[dict[str, str]], default_choice: str) -> int:
    for index, option in enumerate(options):
        if option["choice"] == default_choice:
            return index
    return 0


def _keyboard_menu_available() -> bool:
    return (
        termios is not None
        and tty is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.environ.get("TERM", "") != "dumb"
        and os.environ.get("OMH_NO_TUI", "") != "1"
    )


def _read_tui_key() -> str:
    if termios is None or tty is None:
        return "\n"
    file_descriptor = sys.stdin.fileno()
    old_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        key = sys.stdin.read(1)
        if key == "\x1b":
            key += sys.stdin.read(2)
        return key
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)


def _ask(prompt: str, *, default: str, use_color: bool) -> str:
    try:
        return input(f"{_color('?', '1;36', use_color)} {prompt} [{default}]: ").strip()
    except EOFError:
        print("")
        return ""


def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


class _HumanProgress:
    def __init__(self, *, enabled: bool, use_color: bool) -> None:
        self.enabled = enabled
        self.use_color = use_color

    def header(self, title: str, subtitle: str) -> None:
        if not self.enabled:
            return
        print(_color(title, "1;36", self.use_color))
        print(subtitle)
        print("")

    def step(self, index: int, total: int, label: str, *, detail: str = "") -> None:
        if not self.enabled:
            return
        prefix = _color(f"[{index}/{total}]", "1;36", self.use_color)
        print(f"{prefix} {label}...", flush=True)
        if detail:
            print(f"      {detail}", flush=True)
        self._brief_tty_pause()

    def done(self, message: str = "done") -> None:
        if not self.enabled:
            return
        print(f"      {_color('[ok]', '1;32', self.use_color)} {message}", flush=True)
        self._brief_tty_pause()

    def skip(self, message: str) -> None:
        if not self.enabled:
            return
        print(f"      {_color('[skip]', '1;33', self.use_color)} {message}", flush=True)
        self._brief_tty_pause()

    @staticmethod
    def _brief_tty_pause() -> None:
        if sys.stdout.isatty() and os.environ.get("OMH_PROGRESS", "1") != "0":
            time.sleep(0.04)


def _print_setup_summary(payload: dict[str, object], *, language: str = "en") -> None:
    use_color = _use_color()
    steps = payload.get("steps", {})
    hermes_native = payload.get("hermes_native", {})
    operator_summary = payload.get("operator_summary", {})
    if not isinstance(steps, dict):
        steps = {}
    if not isinstance(hermes_native, dict):
        hermes_native = {}
    if not isinstance(operator_summary, dict):
        operator_summary = {}

    install = steps.get("install", {})
    profile = steps.get("profile", {})
    targets = steps.get("targets", {})
    skills = install.get("skills", []) if isinstance(install, dict) else []
    topology = targets.get("topology", {}) if isinstance(targets, dict) else {}

    dry_run = bool(payload.get("dry_run", False))
    title = tr(language, "setup_preview_complete") if dry_run else tr(language, "setup_complete")
    print("")
    print(_color(title, "1;36", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    scope_label = tr(language, "setup_scope_" + str(operator_summary.get("scope", "custom")))
    mcp_mode_label = tr(language, "setup_mcp_mode_" + str(operator_summary.get("mcp_mode", "none")))
    status_label = tr(language, "setup_status_" + str(operator_summary.get("status", "configured")))
    print(f"  {tr(language, 'setup_scope', scope=scope_label)}")
    print(f"  {tr(language, 'setup_status', status=status_label)}")
    command_path = operator_summary.get("command_path", {})
    if isinstance(command_path, dict):
        if command_path.get("found"):
            print(f"  {tr(language, 'command_path_found', path=command_path.get('path', 'omh'))}")
        else:
            print(f"  {tr(language, 'command_path_missing')}")
            print(f"  {tr(language, 'command_path_missing_next')}")
    print(f"  {tr(language, 'skills_line', count=len(skills), path=hermes_native.get('skills_dir', ''))}")

    discovery_status = str(hermes_native.get("discovery_status", ""))
    if discovery_status == "config_registered_reload_required":
        print(
            f"  {tr(language, 'registration_configured', path=hermes_native.get('hermes_config_path', ''))}"
        )
    elif discovery_status == "dry_run_not_observed":
        print(f"  {tr(language, 'registration_dry_run')}")
    elif discovery_status == "not_registered_skip_apply":
        print(f"  {tr(language, 'registration_skipped')}")
    else:
        print(f"  {tr(language, 'registration_unknown', status=discovery_status or 'unknown')}")

    if isinstance(profile, dict):
        executor = str(profile.get("default_executor", ""))
        if executor:
            print(f"  {tr(language, 'default_handoff', summary=_executor_summary(language, executor))}")
            if executor == "choose":
                print(f"  {tr(language, 'default_handoff_pin_hint')}")

    if isinstance(topology, dict):
        print(
            f"  {tr(language, 'target_topology', mode=topology.get('mode', 'unknown'), count=topology.get('known_target_count', 0))}"
        )
    plugin = payload.get("plugin_distribution")
    if isinstance(plugin, dict):
        print(f"  {tr(language, 'plugin_bridge', status=_plugin_status_label(language, str(plugin.get('status', 'installed'))))}")

    _print_memory_provider_summary(steps, language)

    menubar = steps.get("menubar")
    if isinstance(menubar, dict) and str(menubar.get("status", "not_requested")) != "not_requested":
        status = str(menubar.get("status", "unknown"))
        print(f"  {tr(language, 'menubar_helper', status=_menubar_status_label(language, status))}")

    if str(operator_summary.get("mcp_mode", "none")) == "bridge_requested":
        print(f"  {tr(language, 'setup_mcp_mode', mode=mcp_mode_label)}")

    team_profiles = payload.get("team_profiles")
    if isinstance(team_profiles, list) and team_profiles:
        print(f"  {tr(language, 'team_activated', count=len(team_profiles))}")

    print(_color(tr(language, "next"), "1;32", use_color))
    if dry_run:
        print(f"  {tr(language, 'setup_next_dry')}")
    else:
        print(f"  {tr(language, 'setup_next_reload')}")
        print(f"  {tr(language, 'setup_next_prompt')}")
        print(f"  {tr(language, 'setup_next_verify')}")
        # The chains recommendation belongs to setup's next steps, not the TUI
        # verdict block below — the verdict stays the final output line.
        print(f"  {tr(language, 'setup_next_chains')}")
    print(f"  {tr(language, 'machine_readable')}")
    profiles = payload.get("hermes_profiles")
    if isinstance(profiles, list):
        _print_hermes_profiles_line(profiles, language=language)
    verdict = payload.get("tui_verdict")
    if isinstance(verdict, dict):
        _print_tui_verdict_block(verdict, language=language)


def _print_doctor_summary(payload: dict[str, object], *, language: str = "en") -> None:
    use_color = _use_color()
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    ok = bool(payload.get("ok", False))
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    passing = int(summary.get("passing", sum(1 for check in checks if isinstance(check, dict) and check.get("ok"))))
    total = int(summary.get("total", len(checks)))
    title_key = "doctor_complete" if ok else "doctor_needs_attention"
    print(_color(tr(language, title_key), "1;36" if ok else "1;33", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'doctor_status', status=tr(language, 'doctor_status_ok' if ok else 'doctor_status_needs_attention'))}")
    print(f"  {tr(language, 'doctor_checks', passing=passing, total=total)}")
    print(
        f"  {tr(language, 'doctor_issue_counts', blocking=summary.get('blocking', 0), warnings=summary.get('warnings', 0))}"
    )
    build_identity = payload.get("build_identity", {})
    if isinstance(build_identity, dict) and build_identity.get("summary"):
        print(f"  {tr(language, 'doctor_build_identity', identity=build_identity['summary'])}")
    groups = summary.get("groups", [])
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            group_key = "doctor_group_" + str(group.get("name", "unknown"))
            status_key = "doctor_group_status_" + str(group.get("status", "ok"))
            print(
                f"  {tr(language, group_key)}: {tr(language, status_key)} "
                f"({group.get('passing', 0)}/{group.get('total', 0)})"
            )
    observation_lines = _doctor_observation_boundary_lines(checks, language=language)
    if observation_lines:
        print(_color(tr(language, "doctor_observation_boundaries"), "1;32", use_color))
        for line in observation_lines:
            print(f"  {line}")
    state_log = payload.get("state_log", {})
    if isinstance(state_log, dict) and state_log.get("path") and state_log.get("entry"):
        print(f"  {tr(language, 'state_log', path=state_log.get('path'), entry=state_log.get('entry'))}")
    for check in checks:
        if not isinstance(check, dict) or (check.get("ok") and check.get("severity") != "warning"):
            continue
        name = check.get("name", "unknown")
        message = check.get("message", "")
        remediation = check.get("remediation", "") or check.get("next_action", "")
        print(f"  - {name}: {message}")
        if remediation:
            print(f"    {tr(language, 'doctor_fix')}: {remediation}")
    _print_doctor_advice(payload, use_color=use_color)
    next_action = str(payload.get("recommended_next_action", "")).strip()
    print(_color(tr(language, "next"), "1;32", use_color))
    if next_action:
        print(f"  {_doctor_human_next_action(next_action, language=language)}")
    print(f"  {tr(language, 'doctor_boundary')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_doctor_advice(payload: dict[str, object], *, use_color: bool) -> None:
    """Render the read-only Advice lane, separate from doctor checks.

    Advice never affects the doctor status or exit code; it is a default-on,
    plain-text section that surfaces the ``hermes_config_advice`` advisory lane.
    """
    advisories = payload.get("advisories", {})
    if not isinstance(advisories, dict):
        return
    entries = advisories.get("entries", [])
    if not isinstance(entries, list):
        return
    actionable = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("status") == "advice"
    ]
    if not actionable:
        return
    print(_color("Advice (read-only; does not affect doctor status)", "1;36", use_color))
    for entry in actionable:
        check_id = entry.get("check_id", "unknown")
        observed = entry.get("observed", "")
        remediation = entry.get("remediation", "")
        print(f"  - {check_id}: {observed}")
        if remediation:
            print(f"    Suggestion: {remediation}")


def _doctor_human_next_action(next_action: str, *, language: str) -> str:
    if next_action == DEFAULT_DOCTOR_NEXT_ACTION:
        return tr(language, "doctor_default_next_action")
    if next_action == COMMAND_PATH_MISSING_NEXT_ACTION:
        return tr(language, "command_path_missing_next")
    return next_action


def _doctor_observation_boundary_lines(checks: list[object], *, language: str) -> list[str]:
    check_map = {str(check.get("name", "")): check for check in checks if isinstance(check, dict)}
    lines: list[str] = []
    plugin_bundle = check_map.get("plugin_bundle")
    plugin_register = check_map.get("plugin_register_smoke")
    plugin_loader = check_map.get("plugin_loader_observed")
    plugin_runtime = check_map.get("plugin_runtime_observed")

    if plugin_register:
        if plugin_register.get("ok"):
            lines.append(tr(language, "doctor_plugin_bridge_ready"))
        else:
            lines.append(tr(language, "doctor_plugin_bridge_needs_attention"))
    elif plugin_bundle:
        lines.append(tr(language, "doctor_plugin_bridge_not_installed"))

    if plugin_loader:
        lines.append(
            tr(
                language,
                (
                    "doctor_plugin_loader_observed"
                    if plugin_loader.get("observed") and str(plugin_loader.get("severity", "")) == "ok"
                    else "doctor_plugin_loader_not_observed"
                ),
            )
        )

    if plugin_runtime:
        if plugin_runtime.get("observed") and str(plugin_runtime.get("severity", "")) == "ok":
            lines.append(tr(language, "doctor_plugin_runtime_observed"))
        elif plugin_runtime.get("observed"):
            lines.append(tr(language, "doctor_plugin_runtime_historical"))
        else:
            lines.append(tr(language, "doctor_plugin_runtime_not_observed"))

    structural = check_map.get("structural_search_tooling")
    if structural:
        lines.append(
            tr(
                language,
                (
                    "doctor_structural_search_present"
                    if structural.get("observed") and "not on PATH" not in str(structural.get("message", ""))
                    else "doctor_structural_search_absent"
                ),
            )
        )

    return lines


def _print_uninstall_summary(payload: dict[str, object], *, language: str = "en") -> None:
    use_color = _use_color()
    dry_run = bool(payload.get("dry_run", False))
    title = tr(language, "uninstall_preview_complete") if dry_run else tr(language, "uninstall_complete")
    removed = payload.get("removed_paths", [])
    would_remove = payload.get("would_remove", [])
    kept = payload.get("kept_paths", [])
    if not isinstance(removed, list):
        removed = []
    if not isinstance(would_remove, list):
        would_remove = []
    if not isinstance(kept, list):
        kept = []
    command_kept = payload.get("command_package_kept", [])
    if not isinstance(command_kept, list):
        command_kept = []
    command_kept_paths = {
        item.get("path", "")
        for item in command_kept
        if isinstance(item, dict)
    }

    print("")
    print(_color(title, "1;36", use_color))
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'scope')}: {payload.get('scope', '')}")
    config_message = _config_change_label(language, str(payload.get("config_message", "")))
    print(f"  {tr(language, 'uninstall_config', message=config_message)}")
    if dry_run:
        print(f"  {tr(language, 'uninstall_would_remove', count=len(would_remove))}")
        for path in would_remove[:8]:
            print(f"    - {path}")
    else:
        print(f"  {tr(language, 'uninstall_removed', count=len(removed))}")
        for path in removed[:8]:
            print(f"    - {path}")
    if not removed and not would_remove:
        print(f"  {tr(language, 'uninstall_none')}")
    for item in kept:
        if isinstance(item, dict):
            if item.get("path", "") in command_kept_paths:
                continue
            print(f"  {tr(language, 'kept')}: {item.get('path', '')} ({item.get('reason', '')})")

    profiles = payload.get("hermes_profiles")
    if isinstance(profiles, list) and profiles:
        summary = ", ".join(
            f"{entry.get('profile')} ({_PROFILE_STATUS_LABELS.get(str(entry.get('status')), str(entry.get('status')))})"
            for entry in profiles
            if isinstance(entry, dict)
        )
        print(f"  {tr(language, 'hermes_profiles_uninstalled', summary=summary)}")
    print(_color(tr(language, "next"), "1;32", use_color))
    command_removed = payload.get("command_package_removed_paths", [])
    command_would_remove = payload.get("command_package_would_remove", [])
    if not isinstance(command_removed, list):
        command_removed = []
    if not isinstance(command_would_remove, list):
        command_would_remove = []
    if dry_run and command_would_remove:
        print(f"  {tr(language, 'uninstall_command_would_remove', count=len(command_would_remove))}")
    elif command_removed:
        print(f"  {tr(language, 'uninstall_command_removed', count=len(command_removed))}")
    elif command_kept:
        print(f"  {tr(language, 'uninstall_command_kept')}")
        print(f"  {tr(language, 'uninstall_command_still_available')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_install_summary(payload: dict[str, object], *, command: str, language: str = "en") -> None:
    use_color = _use_color()
    skills = payload.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    dry_run = bool(payload.get("dry_run", False))
    label = "update" if command == "update" else "install"
    title = tr(language, "install_preview_complete", label=label) if dry_run else tr(language, "install_complete", label=label)
    source = str(payload.get("source", "builtin"))
    source_label = tr(language, "source_builtin") if source == "builtin" else source
    print("")
    print(_color(title, "1;36", use_color))
    if label == "update":
        _print_update_release_card(payload, source_label=source_label, language=language, use_color=use_color)
    print(_color(tr(language, "summary"), "1;32", use_color))
    print(f"  {tr(language, 'skills_line', count=len(skills), path=payload.get('skills_dir', ''))}")
    release_update = payload.get("release_update", {})
    command_package = payload.get("command_package", {})
    if isinstance(command_package, dict):
        command_status = str(command_package.get("status", "")).strip()
        if command_status == "updated":
            change = _command_package_display_change(payload, release_update if isinstance(release_update, dict) else {})
            print(_color(f"  {tr(language, 'command_package_update_line', change=change)}", "1;32", use_color))
        elif label == "update" and source == "builtin" and not dry_run:
            print(_color(f"  {tr(language, 'command_package_not_updated_line')}", "1;33", use_color))
    print(f"  {tr(language, 'source', source=source_label)}")
    channel = str(payload.get("release_channel", "")).strip()
    package_url = str(payload.get("release_package_url", "")).strip()
    if channel:
        print(f"  {tr(language, 'release_channel', channel=channel)}")
    if package_url and package_url != "local":
        package_url_key = "recorded_package_url" if source == "builtin" else "package_url"
        print(f"  {tr(language, package_url_key, url=package_url)}")
    if isinstance(release_update, dict):
        display = release_update.get("display", {})
        if isinstance(display, dict):
            version_change = str(display.get("version_change", "")).strip()
            source_ref_change = str(display.get("source_ref_change", "")).strip()
            if version_change and str(payload.get("release_channel", "")) == "stable":
                print(f"  {tr(language, 'release_version_change', change=version_change)}")
            if source_ref_change:
                print(f"  {tr(language, 'release_source_ref_change', change=source_ref_change)}")
        status = str(release_update.get("status", "")).strip()
        if status:
            print(f"  {tr(language, 'release_update_status', status=status)}")
    state_path = str(payload.get("runtime_state_path", "")).strip()
    state_key = str(payload.get("runtime_state_key", "")).strip()
    if state_path and state_key:
        print(f"  {tr(language, 'state_log', path=state_path, entry=state_key)}")
    profile_state = payload.get("skill_profile_state")
    if isinstance(profile_state, dict) and profile_state.get("retained_exception"):
        retained = profile_state.get("full_only_installed_skills", [])
        retained_count = len(retained) if isinstance(retained, list) else 0
        line = tr(language, "skill_profile_retained_line", count=retained_count, command=SKILL_PROFILE_RECONCILE_COMMAND)
        print(_color(f"  {line}", "1;33", use_color))
    print(_color(tr(language, "next"), "1;32", use_color))
    if dry_run:
        print(f"  {tr(language, 'install_next_dry')}")
    elif label == "update":
        print(f"  {tr(language, 'update_next')}")
        if source == "builtin" and not (isinstance(command_package, dict) and command_package.get("updated")):
            instruction = str(command_package.get("update_instruction", "")).strip()
            if instruction:
                print(f"  {tr(language, 'update_command_next', command=instruction)}")
    else:
        print(f"  {tr(language, 'install_next')}")
    print(f"  {tr(language, 'machine_readable')}")


def _print_update_release_card(
    payload: dict[str, object], *, source_label: str, language: str, use_color: bool
) -> None:
    release_update = payload.get("release_update", {})
    if not isinstance(release_update, dict):
        release_update = {}
    previous = release_update.get("previous", {})
    if not isinstance(previous, dict):
        previous = {}
    current = release_update.get("current", {})
    if not isinstance(current, dict):
        current = {}
    skills = payload.get("skills", [])
    workflow_count = len(skills) if isinstance(skills, list) else 0
    dry_run = bool(payload.get("dry_run", False))
    command_package = payload.get("command_package", {})
    command_updated = isinstance(command_package, dict) and bool(command_package.get("updated"))
    command_key = (
        "update_card_command_preview"
        if dry_run
        else "update_card_command_updated"
        if command_updated
        else "update_card_command_unchanged"
    )
    previous_release = _release_card_identity(previous, language=language)
    current_release = _release_card_identity(current, language=language)
    current_label = "update_card_available_release" if dry_run else "update_card_installed_release"
    notes_label = "update_card_release_preview" if dry_run else "update_card_release_notes"
    workflows_label = "update_card_workflows_to_refresh" if dry_run else "update_card_workflows_refreshed"
    title = tr(language, "update_card_title")

    print(_color("╔═══════════════════════════════════════════════════════════╗", "1;34", use_color))
    print(_color(f"║{title:^59}║", "1;34", use_color))
    print(_color("╚═══════════════════════════════════════════════════════════╝", "1;34", use_color))
    print(f"  {tr(language, 'update_card_previous_release', release=previous_release)}")
    print(f"  {tr(language, current_label, release=current_release)}")
    print(f"  {tr(language, 'update_card_install_method', source=source_label)}")
    print("")
    print(f"  {tr(language, notes_label)}")
    print(f"    - {tr(language, workflows_label, count=workflow_count)}")
    print(f"    - {tr(language, command_key)}")
    workflow_content = payload.get("workflow_content", {})
    if isinstance(workflow_content, dict) and workflow_content.get("known"):
        content_key = (
            "update_card_workflow_content_changed"
            if workflow_content.get("changed")
            else "update_card_workflow_content_unchanged"
        )
        print(f"    - {tr(language, content_key)}")
    if previous_release != current_release:
        print(f"    - {tr(language, 'release_version_change', change=f'{previous_release} -> {current_release}')}")
    print("")


def _release_card_identity(release: dict[str, object], *, language: str) -> str:
    version = _effective_release_version(release)
    if version:
        return version
    source_ref = _string_value(release.get("release_source_ref") or release.get("source_ref"))
    if source_ref:
        return source_ref
    return tr(language, "update_card_release_not_recorded")


def _command_package_display_change(payload: dict[str, object], release_update: dict[str, object]) -> str:
    display = release_update.get("display", {})
    if not isinstance(display, dict):
        display = {}
    previous = release_update.get("previous", {})
    if not isinstance(previous, dict):
        previous = {}
    current = release_update.get("current", {})
    if not isinstance(current, dict):
        current = {}
    channel = str(payload.get("release_channel", "")).strip()
    version_change = str(display.get("version_change", "")).strip()
    source_ref_change = str(display.get("source_ref_change", "")).strip()
    package_url_change = str(display.get("package_url_change", "")).strip()
    previous_version = _effective_release_version(previous)
    current_version = _effective_release_version(current)
    previous_ref = str(previous.get("release_source_ref", "")).strip()
    current_ref = str(current.get("release_source_ref", "")).strip()
    previous_package_url = str(previous.get("release_package_url", "")).strip()
    current_package_url = str(current.get("release_package_url", "")).strip()
    version_changed = bool(current_version and previous_version != current_version)
    source_ref_changed = bool(current_ref and previous_ref != current_ref)
    package_url_changed = bool(current_package_url and previous_package_url != current_package_url)
    # A real version move is the most useful thing to show on any channel. Preview
    # installs track a branch, so without this they report `main -> main` and the
    # upgrade is invisible.
    if version_changed and version_change:
        return version_change
    if channel == "stable" and current_version and source_ref_changed and source_ref_change:
        return f"{current_version} ({source_ref_change})"
    if channel == "stable" and current_version and package_url_changed and package_url_change:
        return f"{current_version} (package URL changed)"
    if source_ref_changed and source_ref_change:
        return source_ref_change
    if package_url_changed and package_url_change:
        return package_url_change
    if current_version:
        return f"{current_version} -> {current_version}" if previous_version == current_version else current_version
    if current_ref:
        return f"{current_ref} -> {current_ref}" if previous_ref == current_ref else current_ref
    package_url = str(payload.get("release_package_url", "")).strip()
    return package_url or "updated"


def _print_apply_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    dry_run = bool(payload.get("dry_run", False))
    changed = bool(payload.get("changed", False))
    title = "OMH apply preview complete." if dry_run else "OMH apply complete."
    print(_color(title, "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Config: {payload.get('config', '')}")
    print(f"  Managed skills: {payload.get('skills_dir', '')}")
    if dry_run:
        status = "would update Hermes registration" if changed else "registration already up to date"
    else:
        status = "updated Hermes registration" if changed else "registration already up to date"
    message = str(payload.get("message", "")).strip()
    print(f"  Status: {status}")
    if message:
        print(f"  Detail: {message}")
    print(_color("Next", "1;32", use_color))
    print("  Restart or reload Hermes Agent before expecting chat to see new skills.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_list_summary(payload: dict[str, object], *, manifest_path: Path, skills_dir: Path) -> None:
    use_color = _use_color()
    skills = payload.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    print(_color("OMH managed skills", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    if not skills:
        print("  Status: not installed")
        print(f"  Manifest: {manifest_path}")
        print(f"  Managed skills: {skills_dir}")
        print(_color("Next", "1;32", use_color))
        print("  Run `omh setup` to install managed Hermes skills.")
        print(f"  {tr('en', 'machine_readable')}")
        return
    package = str(payload.get("package", "oh-my-hermes"))
    installed_at = str(payload.get("installed_at", ""))
    print(f"  Package: {package}")
    print(f"  Skills: {len(skills)} managed skill(s) at {skills_dir}")
    if installed_at:
        print(f"  Installed at: {installed_at}")
    print(f"  Manifest: {manifest_path}")
    names = [str(skill.get("name", "")) for skill in skills if isinstance(skill, dict) and skill.get("name")]
    shown = names[:12]
    if shown:
        print("  Names: " + ", ".join(shown) + (" ..." if len(names) > len(shown) else ""))
    catalog = payload.get("catalog_context")
    if isinstance(catalog, dict):
        lanes = catalog.get("lanes", [])
        if isinstance(lanes, list) and lanes:
            print(_color("Workflow lanes", "1;32", use_color))
            for lane in lanes[:6]:
                if not isinstance(lane, dict):
                    continue
                lane_skills = lane.get("primary_skills", [])
                if not isinstance(lane_skills, list):
                    lane_skills = []
                skill_names = ", ".join(str(skill) for skill in lane_skills[:5])
                overflow = f" +{len(lane_skills) - 5}" if len(lane_skills) > 5 else ""
                label = str(lane.get("label") or lane.get("id") or "workflow lane")
                use_for = _short_summary(str(lane.get("use_for", "")), limit=96)
                print(f"  - {label}: {skill_names}{overflow}")
                if use_for:
                    print(f"    Use for: {use_for}")
    print(_color("Next", "1;32", use_color))
    print("  Run `omh doctor` to verify Hermes registration.")
    if skills:
        print("  In chat, ask Hermes what OMH can do or type `./omh` to open the workflow picker.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_recommend_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    recommendations = payload.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    print(_color("OMH recommendation", "1;36", use_color))
    print(f"Query: {payload.get('query', '')}")
    if not recommendations:
        print("No recommendations.")
        print(f"  {tr('en', 'machine_readable')}")
        return
    for index, recommendation in enumerate(recommendations, start=1):
        if not isinstance(recommendation, dict):
            continue
        name = str(recommendation.get("skill", "unknown"))
        confidence = str(recommendation.get("confidence", "unknown"))
        print(f"{index}. {name} [{confidence}]")
        description = _short_summary(str(recommendation.get("description", "")), limit=120)
        if description:
            print(f"   {description}")
        next_action = str(recommendation.get("next_action", "")).strip()
        if next_action:
            print(f"   Next action: {_action_label(next_action)}")
        why = _short_summary(str(recommendation.get("why", "")), limit=120)
        if why:
            print(f"   Why: {why}")
    workflow_route_plan = payload.get("workflow_route_plan")
    if isinstance(workflow_route_plan, dict):
        steps = workflow_route_plan.get("steps", [])
        if isinstance(steps, list) and steps:
            path = " -> ".join(str(step.get("skill", "")) for step in steps if isinstance(step, dict))
            if path:
                print(_color("Workflow path", "1;35", use_color))
                print(f"  {path}")
    print(_color("Boundary", "1;32", use_color))
    print("  A recommendation is routing guidance, not execution or verification evidence.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_profile_list_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    packs = payload.get("packs", [])
    if not isinstance(packs, list):
        packs = []
    models = payload.get("operating_models", [])
    if not isinstance(models, list):
        models = []
    print(_color("OMH profile packs", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Default install: {payload.get('default_install', 'none')}")
    print(f"  Operating models: {len(models)}")
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id", "unknown"))
        title = str(model.get("title", model_id))
        summary = _short_summary(str(model.get("summary", "")), limit=110)
        print(f"  - {model_id}: {title}")
        if summary:
            print(f"    {summary}")
    print(f"  Available packs: {len(packs)}")
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        pack_id = str(pack.get("id", "unknown"))
        title = str(pack.get("title", pack_id))
        summary = _short_summary(str(pack.get("summary", "")), limit=110)
        print(f"  - {pack_id}: {title}")
        if summary:
            print(f"    {summary}")
    print(_color("Next", "1;32", use_color))
    print("  Inspect a model or pack with `omh profile inspect <id>`.")
    print("  Install one with `omh setup --profile-pack <id>`.")
    print(f"  {tr('en', 'machine_readable')}")


def _print_profile_inspect_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    if "model" in payload:
        model = payload.get("model", {})
        if not isinstance(model, dict):
            model = {}
        model_id = str(model.get("id", "unknown"))
        print(_color(f"OMH operating model: {model.get('title', model_id)}", "1;36", use_color))
        print(_color("Summary", "1;32", use_color))
        print(f"  ID: {model_id}")
        summary = str(model.get("summary", "")).strip()
        use_when = str(model.get("use_when", "")).strip()
        if summary:
            print(f"  Summary: {summary}")
        if use_when:
            print(f"  Use when: {use_when}")
        print(f"  Default executor: {model.get('default_executor', 'choose')}")
        packs = model.get("recommended_profile_packs", [])
        if isinstance(packs, list) and packs:
            print(f"  Recommended profile packs: {', '.join(str(item) for item in packs)}")
        guidance = model.get("runtime_guidance", [])
        if isinstance(guidance, list) and guidance:
            print(_color("Runtime guidance", "1;32", use_color))
            for item in guidance:
                print(f"  - {item}")
        print(_color("Next", "1;32", use_color))
        print(f"  {model.get('setup_command', f'omh setup --operating-model {model_id}')}")
        boundary = str(model.get("claim_boundary", "")).strip()
        if boundary:
            print(_color("Boundary", "1;32", use_color))
            print(f"  {boundary}")
        print(f"  {tr('en', 'machine_readable')}")
        return
    pack = payload.get("pack", {})
    if not isinstance(pack, dict):
        pack = {}
    roles = pack.get("roles", [])
    if not isinstance(roles, list):
        roles = []
    pack_id = str(pack.get("id", "unknown"))
    print(_color(f"OMH profile pack: {pack.get('title', pack_id)}", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  ID: {pack_id}")
    summary = str(pack.get("summary", "")).strip()
    use_when = str(pack.get("use_when", "")).strip()
    if summary:
        print(f"  Summary: {summary}")
    if use_when:
        print(f"  Use when: {use_when}")
    print(f"  Roles: {len(roles)}")
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("id", "unknown"))
        title = str(role.get("title", role_id))
        purpose = _short_summary(str(role.get("purpose", "")), limit=120)
        print(f"  - {role_id}: {title}")
        if purpose:
            print(f"    {purpose}")
    install_command = str(pack.get("install_command", "")).strip()
    if install_command:
        print(_color("Next", "1;32", use_color))
        print(f"  {install_command}")
    boundary = str(pack.get("claim_boundary", "")).strip()
    if boundary:
        print(_color("Boundary", "1;32", use_color))
        print(f"  {boundary}")
    print(f"  {tr('en', 'machine_readable')}")


def _print_probe_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    counts = {status: 0 for status in ("available", "missing", "unknown", "unverified")}
    for capability in capabilities:
        if isinstance(capability, dict):
            status = str(capability.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
    print(_color("OMH capability probe", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  OMH home: {payload.get('omh_home', '')}")
    print(f"  Hermes home: {payload.get('hermes_home', '')}")
    print(
        "  Capabilities: "
        f"{counts.get('available', 0)} available, "
        f"{counts.get('missing', 0)} missing, "
        f"{counts.get('unknown', 0)} unknown, "
        f"{counts.get('unverified', 0)} unverified"
    )
    topology = payload.get("target_topology", {})
    if isinstance(topology, dict):
        print(
            "  Target topology: "
            f"{topology.get('mode', 'unknown')} "
            f"({topology.get('known_target_count', 0)} known target(s))"
        )
    print(f"  Plugin distribution ready: {payload.get('plugin_distribution_ready', False)}")
    print(f"  Native integration claim ready: {payload.get('native_integration_claim_ready', False)}")
    print(_color("Details", "1;32", use_color))
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        status = str(capability.get("status", "unknown"))
        name = str(capability.get("name", "unknown"))
        message = _short_summary(str(capability.get("message", "")), limit=120)
        print(f"  - {name}: {status}")
        if message:
            print(f"    {message}")
    boundary = str(payload.get("claim_boundary", "")).strip()
    if boundary:
        print(_color("Boundary", "1;32", use_color))
        print(f"  {boundary}")
    parity = payload.get("parity_matrix")
    if isinstance(parity, dict):
        _print_probe_parity_summary(parity, use_color=use_color)
    roadmap = payload.get("capability_gap_roadmap")
    if isinstance(roadmap, dict):
        _print_probe_roadmap_summary(roadmap, use_color=use_color)
    print(f"  {tr('en', 'machine_readable')}")


def _print_probe_parity_summary(payload: dict[str, object], *, use_color: bool) -> None:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    print(_color("Parity matrix", "1;32", use_color))
    print(
        "  Common oh-my runtime axes: "
        f"{summary.get('available', 0)} available, "
        f"{summary.get('partial', 0)} partial, "
        f"{summary.get('planned', 0)} planned, "
        f"{summary.get('deferred', 0)} deferred"
    )
    capabilities = payload.get("capabilities", [])
    if not isinstance(capabilities, list):
        capabilities = []
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        title = str(capability.get("title", "unknown"))
        status = str(capability.get("status", "unknown"))
        missing = _short_summary(str(capability.get("missing_piece", "")), limit=108)
        print(f"  - {title}: {status}")
        if missing:
            print(f"    Gap: {missing}")
    boundary = str(payload.get("claim_boundary", "")).strip()
    if boundary:
        print(_color("Parity boundary", "1;32", use_color))
        print(f"  {_short_summary(boundary, limit=132)}")


def _print_probe_roadmap_summary(payload: dict[str, object], *, use_color: bool) -> None:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    print(_color("Capability roadmap", "1;32", use_color))
    print(
        "  Gaps: "
        f"{summary.get('baseline_product_gaps', 0)} product setup, "
        f"{summary.get('evidence_gaps', 0)} evidence, "
        f"{summary.get('optional_or_host_unknowns', 0)} optional/host unknown"
    )
    actions = payload.get("next_actions", [])
    if not isinstance(actions, list):
        actions = []
    for action in actions[:3]:
        if not isinstance(action, dict):
            continue
        label = str(action.get("label", "Next action"))
        kind = str(action.get("kind", "unknown"))
        next_step = _short_summary(_roadmap_next_step(action), limit=100)
        print(f"  - {label} ({kind})")
        if next_step:
            print(f"    Next: {next_step}")
    boundary = str(payload.get("claim_boundary", "")).strip()
    if boundary:
        print(f"  Boundary: {_short_summary(boundary, limit=132)}")


def _roadmap_next_step(action: dict[str, object]) -> str:
    command = str(action.get("command", "")).strip()
    if command:
        return command
    return str(action.get("operator_instruction", "")).strip()


def _short_summary(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _config_change_label(language: str, message: str) -> str:
    key = "config_" + message.replace(".", "_").replace(" ", "_").replace("-", "_")
    translated = tr(language, key)
    return translated if translated != key else message


def _executor_summary(language: str, executor: str) -> str:
    labels = {
        "en": {
            "choose": "Ask every time",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "Other coding agent",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my runtime",
            "omo-runtime": "Oh-my runtime",
            "omc-runtime": "Oh-my runtime",
        },
        "ko": {
            "choose": "매번 물어보기",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "기타 코딩 에이전트",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my 런타임",
            "omo-runtime": "Oh-my 런타임",
            "omc-runtime": "Oh-my 런타임",
        },
        "ja": {
            "choose": "毎回確認",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "その他のコーディングエージェント",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my ランタイム",
            "omo-runtime": "Oh-my ランタイム",
            "omc-runtime": "Oh-my ランタイム",
        },
        "zh": {
            "choose": "每次询问",
            "codex": "Codex",
            "claude-code": "Claude Code",
            "generic": "其他编码代理",
            "hermes": "Hermes",
            "omx-runtime": "Oh-my 运行时",
            "omo-runtime": "Oh-my 运行时",
            "omc-runtime": "Oh-my 运行时",
        },
    }
    code = normalize_language(language)
    return labels.get(code, labels["en"]).get(executor, labels.get(code, labels["en"])["choose"])


def _plugin_status_label(language: str, status: str) -> str:
    code = normalize_language(language)
    labels = {
        "en": {"installed": "ready", "would_install": "would be installed", "unchanged": "ready", "updated": "updated"},
        "ko": {"installed": "준비됨", "would_install": "설치 예정", "unchanged": "준비됨", "updated": "업데이트됨"},
        "ja": {"installed": "準備完了", "would_install": "インストール予定", "unchanged": "準備完了", "updated": "更新済み"},
        "zh": {"installed": "已就绪", "would_install": "将安装", "unchanged": "已就绪", "updated": "已更新"},
    }
    return labels.get(code, labels["en"]).get(status, status)


def _menubar_status_label(language: str, status: str) -> str:
    code = normalize_language(language)
    labels = {
        "en": {
            "running": "started",
            "installed": "installed",
            "installed_start_failed": "installed; start failed",
            "dry_run": "would install",
            "skipped": "skipped",
            "failed": "failed",
            "not_requested": "not started",
        },
        "ko": {
            "running": "시작됨",
            "installed": "설치됨",
            "installed_start_failed": "설치됨; 시작 실패",
            "dry_run": "설치 예정",
            "skipped": "건너뜀",
            "failed": "실패",
            "not_requested": "시작 안 함",
        },
        "ja": {
            "running": "起動済み",
            "installed": "インストール済み",
            "installed_start_failed": "インストール済み; 起動失敗",
            "dry_run": "インストール予定",
            "skipped": "スキップ",
            "failed": "失敗",
            "not_requested": "未起動",
        },
        "zh": {
            "running": "已启动",
            "installed": "已安装",
            "installed_start_failed": "已安装；启动失败",
            "dry_run": "将安装",
            "skipped": "已跳过",
            "failed": "失败",
            "not_requested": "未启动",
        },
    }
    return labels.get(code, labels["en"]).get(status, status)


def _mcp_status_label(language: str, status: str) -> str:
    code = normalize_language(language)
    labels = {
        "en": {
            "bridge_requested": "preference recorded",
            "host_config_written": "host config written",
            "host_config_unchanged": "host config already ready",
            "host_config_planned": "host config planned",
            "not_requested": "not enabled",
        },
        "ko": {
            "bridge_requested": "선호 기록됨",
            "host_config_written": "호스트 설정 작성됨",
            "host_config_unchanged": "호스트 설정 이미 준비됨",
            "host_config_planned": "호스트 설정 예정",
            "not_requested": "사용 안 함",
        },
        "ja": {
            "bridge_requested": "設定を記録済み",
            "host_config_written": "ホスト設定を書き込み済み",
            "host_config_unchanged": "ホスト設定は準備済み",
            "host_config_planned": "ホスト設定を予定",
            "not_requested": "無効",
        },
        "zh": {
            "bridge_requested": "偏好已记录",
            "host_config_written": "已写入 host 配置",
            "host_config_unchanged": "host 配置已就绪",
            "host_config_planned": "将写入 host 配置",
            "not_requested": "未启用",
        },
    }
    return labels.get(code, labels["en"]).get(status, status)


def _print_memory_provider_summary(steps: dict[str, object], language: str) -> None:
    """Say, in one line, that memory is on -- or why it is not.

    A capability nobody is told about is one nobody uses. This is the summary a
    normal user actually reads, so it names the outcome rather than the config
    key, and it stays silent when the slot is simply free and unclaimed.
    """
    apply_step = steps.get("apply")
    if not isinstance(apply_step, dict):
        return
    provider = apply_step.get("memory_provider")
    if not isinstance(provider, dict):
        return
    selected = str(provider.get("selected", "") or "")
    if selected == MEMORY_PROVIDER_NAME:
        print(f"  {tr(language, 'memory_provider_on')}")
    elif selected:
        print(f"  {tr(language, 'memory_provider_other', provider=selected)}")


def _plugin_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError as exc:
        raise OmhError(_friendly_plugin_error(paths, str(exc))) from exc
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    return result


def _seed_model_chains_result(paths, *, dry_run: bool) -> dict[str, object]:
    """Materialize the editable mixture-chain override document once.

    Seeded empty on purpose: an empty ``categories`` object means the shipped
    default chains apply and keep updating with `omh update`; a category the
    user writes into the file replaces that chain until they remove it.
    Seeding the full defaults instead would silently pin every user to the
    chains of their install day.
    """
    from ..plugin_bundle.omh.hermes_delegation import (
        MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
        mixture_chain_overrides_path,
    )

    path = mixture_chain_overrides_path(paths.omh_home)
    payload: dict[str, object] = {
        "schema_version": "model_chain_seed/v1",
        "path": str(path),
        "dry_run": bool(dry_run),
    }
    if path.exists():
        payload["status"] = "already_present"
        return payload
    if dry_run:
        payload["status"] = "dry_run"
        return payload
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
        "categories": {},
    }
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")
    payload["status"] = "seeded"
    return payload


def _menubar_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = setup_menubar_app(paths, dry_run=bool(args.dry_run), start=True, force=bool(args.force))
    except RuntimeError as exc:
        result = {
            "schema_version": "menubar_app/v1",
            "status": "failed",
            "supported": sys.platform == "darwin",
            "dry_run": bool(args.dry_run),
            "reason": str(exc),
        }
    if not args.dry_run:
        update_state(paths, {"last_menubar_app": result})
    return result


def _friendly_plugin_error(paths, message: str) -> str:
    if "exists without an OMH plugin manifest" in message:
        return (
            "OMH status helper location already exists, but it does not look like an OMH-managed install: "
            f"{paths.hermes_plugin_dir}. Run `omh setup --force` to replace only the OMH status helper files."
        )
    if "managed plugin files changed" in message:
        return (
            "OMH status helper files were changed outside OMH. Run `omh setup --force` to refresh the helper, "
            "or inspect the plugin directory before replacing it."
        )
    return message


def _durable_mcp_host_config_record(mcp_setup: object) -> dict[str, object] | None:
    if not isinstance(mcp_setup, dict):
        return None
    host_config = mcp_setup.get("host_config")
    if not isinstance(host_config, dict):
        return None
    status = str(host_config.get("status", ""))
    path = str(host_config.get("path", "")).strip()
    host = str(host_config.get("host", "generic"))
    if host == "generic" or status not in {"updated", "unchanged"} or not path:
        return None
    return {**host_config, "durable_state_key": "last_mcp_host_config_install"}


def _mcp_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    requested = bool(getattr(args, "with_mcp", False))
    host = str(getattr(args, "mcp_host", "") or "generic")
    command = str(getattr(args, "mcp_command", "") or "omh")
    config_path = getattr(args, "mcp_config_path", None)
    host_config: dict[str, object] = {
        "schema_version": "omh_mcp_host_config_install/v1",
        "host": host,
        "status": "not_requested",
        "changed": False,
        "written": False,
        "dry_run": bool(args.dry_run),
        "path": str(config_path or ""),
    }
    if requested:
        try:
            host_config = install_mcp_host_config(
                paths,
                host=host,
                command=command,
                config_path=config_path,
                scope=_setup_scope(args),
                dry_run=bool(args.dry_run),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise OmhError(f"Could not prepare MCP host config: {exc}") from exc
        host_config_status = str(host_config.get("status", "skipped"))
        if host_config_status == "updated":
            status = "host_config_written"
        elif host_config_status == "unchanged":
            status = "host_config_unchanged"
        elif host_config_status.startswith("dry_run"):
            status = "host_config_planned"
        else:
            status = "bridge_requested"
        mode = "bridge_requested"
    else:
        status = "not_requested"
        mode = "none"
    return {
        "schema_version": MCP_SETUP_SCHEMA_VERSION,
        "mode": mode,
        "host": host,
        "requested": requested,
        "status": status,
        "dry_run": bool(args.dry_run),
        "observed": False,
        "host_config": host_config,
        "scope": _setup_scope(args),
        "paths": {
            "omh_home": str(paths.omh_home),
            "runtime_state_path": str(paths.runtime_state_path),
        },
        "bridge": {
            "manifest_command": "omh mcp manifest",
            "host_config_recipes_command": "omh mcp config-recipe --host <host>",
            "known_recipe_hosts": ["generic", "claude-code", "codex", "opencode", "cursor"],
            "server_command": "omh mcp serve",
            "server_command_configured": f"{command} mcp serve",
            "host_observation_command": (
                f"{command} mcp observe-host --host <host> --session <session-id> "
                "--event host_load --evidence-ref <host-log-or-session-ref>"
            ),
            "transport": "stdio",
            "tools": ["omh_status", "omh_recommend", "omh_probe"],
        },
        "claim_boundary": (
            "OMH setup records the operator MCP bridge preference and may write a local host config entry; "
            "it does not prove an MCP host loaded OMH, called a tool, or observed runtime evidence."
        ),
        "next_action": (
            "Use Hermes skills as the normal surface. If a concrete MCP host config was written, restart or reload "
            "that host and record a concrete load or tool-call event with `omh mcp observe-host`. If the host is generic, "
            "export `omh mcp manifest` or `omh mcp config-recipe --host <host>` and wire the stdio bridge manually."
        ),
    }


def _setup_profile_result(args: argparse.Namespace, paths) -> dict[str, object]:
    default_executor = str(getattr(args, "default_executor", "") or "") or None
    operating_model = str(getattr(args, "operating_model", "") or "") or None
    memory_mode = str(getattr(args, "memory_mode", "") or "") or None
    if args.dry_run:
        profile = build_setup_profile(args.profile, default_executor=default_executor, operating_model=operating_model, memory_mode=memory_mode)
        return {**profile, "dry_run": True, "written": False, "path": str(paths.setup_profile_path)}
    profile = write_setup_profile(paths, args.profile, default_executor=default_executor, operating_model=operating_model, memory_mode=memory_mode)
    return {**profile, "dry_run": False, "written": True, "path": str(paths.setup_profile_path)}


def _team_profile_setup_result(args: argparse.Namespace, paths) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for pack_id in args.profile_pack:
        try:
            result = install_team_profile_pack(paths, pack_id, force=args.force, dry_run=args.dry_run)
        except TeamProfileError as exc:
            raise OmhError(str(exc)) from exc
        results.append(result)
    if not args.dry_run:
        update_state(paths, {"last_team_profile_install": results})
    return results


def cmd_profile_list(args: argparse.Namespace) -> int:
    payload = list_team_profile_packs()
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_profile_list_summary(payload)
    return 0


def cmd_profile_inspect(args: argparse.Namespace) -> int:
    try:
        payload = inspect_team_profile_pack(args.id)
    except TeamProfileError as exc:
        try:
            payload = inspect_operating_model(args.id)
        except TeamProfileError:
            raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_profile_inspect_summary(payload)
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("recommend --limit must be at least 1")
    query = " ".join(args.task).strip()
    if not query:
        raise OmhError("recommend requires a task description")
    full_recommendations = recommend_skills(query, limit=max(args.limit, 8))
    payload = {"query": query, "recommendations": full_recommendations[: args.limit]}
    selected_skill = str(full_recommendations[0].get("skill", "oh-my-hermes")) if full_recommendations else "oh-my-hermes"
    top_score = int(full_recommendations[0].get("score", 0)) if full_recommendations else 0
    workflow_route_plan = compact_workflow_route_plan(
        build_workflow_route_plan(
            query,
            full_recommendations,
            selected_skill=selected_skill,
            action="dispatch" if top_score > 0 else "fallback",
        )
    )
    if workflow_route_plan:
        payload["workflow_route_plan"] = workflow_route_plan
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_recommend_summary(payload)
    return 0


def cmd_snippet(args: argparse.Namespace) -> int:
    if args.dry_run or not args.output:
        print(WORKSPACE_SNIPPET.rstrip())
        return 0
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(output, WORKSPACE_SNIPPET)
    payload = {"written": str(output)}
    if _wants_json(args):
        _print_json(payload)
    else:
        print(f"OMH workspace snippet written: {output}")
        print(f"  {tr('en', 'machine_readable')}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    payload = probe_capabilities(
        _paths(args),
        include_parity=bool(getattr(args, "parity", False)),
        include_roadmap=bool(getattr(args, "roadmap", False)),
    )
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_probe_summary(payload)
    return 0


def _add_common_install_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from-skills-dir", default=None, help="Import skills from a local skill directory.")
    p.add_argument("--source", default=None, help="Mockable local source directory for install/update.")
    p.add_argument("--channel", choices=RELEASE_CHANNELS, default="preview", help="Release channel metadata for this install/update.")
    p.add_argument("--version", default="", help="Stable release version such as 1.0.0 or v1.0.0.")
    p.add_argument("--package-url", default="", help="Explicit release archive URL for support and audit metadata.")
    p.add_argument("--source-ref", default="", help="Release source ref metadata such as main, main@sha, or v1.0.1.")
    p.add_argument("--command-package-updated", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--language", default=None, help=f"Human output language for setup/install/update ({', '.join(LANGUAGE_CODES)}).")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--full",
        action="store_true",
        help=(
            "Install every packaged skill. This is already the default for a "
            "fresh install; the flag remains to upgrade an existing core "
            "install and for script compatibility."
        ),
    )
    p.add_argument(
        "--core",
        action="store_true",
        help=(
            "Install only the lightweight core profile (chat/plan/status/"
            "handoff essentials plus the doctor health floor) instead of the "
            "full default. Every installed skill adds per-turn context weight; "
            "core keeps that footprint minimal at the cost of the ULW engines "
            "and most workflow skills."
        ),
    )


def _add_top_level_commands(sub) -> None:
    setup = sub.add_parser("setup", help="Connect OMH workflows to the target Hermes profile.")
    _add_common_install_options(setup)
    setup.add_argument(
        "--scope",
        choices=("user", "project"),
        default=argparse.SUPPRESS,
        help="Install to user-wide ~/.omh/~/.hermes or project-local ./.omh/./.hermes paths.",
    )
    setup.add_argument("--json", action="store_true", help="Print the full machine-readable setup payload.")
    setup.add_argument("--yes", action="store_true", help="Use default setup choices without interactive prompts.")
    setup.add_argument("--interactive", action="store_true", help="Force the interactive setup wizard.")
    setup.add_argument("--no-interactive", action="store_true", help="Disable the interactive setup wizard.")
    setup.add_argument(
        "--no-omh-tui",
        action="store_true",
        help="Keep the current Hermes display interface and skin instead of activating the branded OMH TUI.",
    )
    setup.add_argument("--skip-apply", action="store_true", help="Install skills without registering them in Hermes config.")
    setup.add_argument(
        "--model-setup",
        action="store_true",
        help="Inspect local model metadata and guide explicit Hermes model-alias activation.",
    )
    setup.add_argument(
        "--import-omo-category-overrides",
        action="store_true",
        help="Import category model preferences from canonical ~/.omo/omo.json[c].",
    )
    setup.add_argument(
        "--confirm-model",
        action="append",
        default=[],
        metavar="PROVIDER/MODEL",
        help="Confirm one locally available model as active. Repeat for multiple models.",
    )
    setup.add_argument(
        "--model-alias",
        action="append",
        default=[],
        metavar="ALIAS=MODEL",
        help="Preview one editable Hermes model alias. Repeat for multiple aliases.",
    )
    setup.add_argument(
        "--apply-model-config",
        action="store_true",
        help="Apply the model-alias preview after explicit confirmation and digest binding.",
    )
    setup.add_argument(
        "--model-config-digest",
        default="",
        help="Expected Hermes config digest printed by the model-alias preview.",
    )
    setup.add_argument(
        "--allow-model-alias-collision",
        action="store_true",
        help="Explicitly allow replacing an existing Hermes model alias in the preview.",
    )
    setup.add_argument("--star", action="store_true", help="Star the oh-my-hermes GitHub repo via gh after setup (opt-in; never prompted).")
    setup.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Setup profile category to record by number or id. Repeat for multiple categories; choices are listed in setup output.",
    )
    setup.add_argument(
        "--default-executor",
        choices=CODING_EXECUTOR_TARGETS,
        default=None,
        help="Durable coding-owner preference for automation and scripted installs. Interactive setup never asks; by default Hermes asks at the first coding request.",
    )
    setup.add_argument(
        "--operating-model",
        choices=operating_model_ids(),
        default=None,
        help="Advanced: record a Hermes-facing operating model for this profile; normal setup lets Hermes choose per request.",
    )
    setup.add_argument(
        "--memory-mode",
        choices=PROJECT_MEMORY_MODES,
        default=None,
        help="Configure OMH project memory: off, review-first, or auto-safe. Defaults to review-first.",
    )
    setup.add_argument(
        "--with-plugin",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    setup.add_argument(
        "--with-menubar",
        action="store_true",
        help="Install and start the native macOS OMH menu bar helper when supported.",
    )
    setup.add_argument(
        "--no-menubar",
        action="store_true",
        help="Do not start the native macOS OMH menu bar helper during setup.",
    )
    setup.add_argument(
        "--with-mcp",
        action="store_true",
        help="Prepare the optional OMH MCP bridge. Use --mcp-host to also write a supported host config.",
    )
    setup.add_argument(
        "--mcp-host",
        choices=MCP_HOST_CONFIG_RECIPE_HOSTS,
        default="generic",
        help="MCP host config to prepare when --with-mcp is set. generic keeps recipe-only output.",
    )
    setup.add_argument(
        "--mcp-config-path",
        default=None,
        help="Explicit host config path to update for --with-mcp --mcp-host.",
    )
    setup.add_argument(
        "--mcp-command",
        default="omh",
        help="Command path the MCP host should launch. Use an absolute installed omh path when needed.",
    )
    setup.add_argument(
        "--profile-pack",
        action="append",
        default=[],
        help="Advanced: install optional visible Hermes role/profile files such as startup-delivery, engineering-delivery, research-strategy, or cto-loop.",
    )
    setup.set_defaults(func=cmd_setup)

    install = sub.add_parser("install", help="Refresh the managed OMH skill pack without changing Hermes registration.")
    _add_common_install_options(install)
    install.add_argument("--json", action="store_true", help="Print the full machine-readable install payload.")
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update", help="Refresh OMH from a preview, stable, local, or explicit package source.")
    _add_common_install_options(update)
    update.add_argument("--json", action="store_true", help="Print the full machine-readable update payload.")
    update.add_argument("--yes", action="store_true", help="Use the recommended branded TUI choice without prompting.")
    update.add_argument("--interactive", action="store_true", help="Force the interactive update prompt.")
    update.add_argument("--no-interactive", action="store_true", help="Disable the interactive update prompt.")
    update.add_argument("--recover-known-good", action="store_true", help="Atomically restore the retained known-good installer generation.")
    update.add_argument(
        "--no-omh-tui",
        action="store_true",
        help="Keep the current Hermes display interface and skin instead of activating the branded OMH TUI.",
    )
    update.set_defaults(func=cmd_update)

    convert = sub.add_parser("convert", help="Import a local skills directory into the managed OMH skill pack.")
    convert.add_argument("--from-skills-dir", required=True)
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--dry-run", action="store_true")
    convert.add_argument("--json", action="store_true", help="Print the full machine-readable convert payload.")
    convert.set_defaults(func=cmd_convert)

    apply = sub.add_parser("apply", help="Register the managed OMH skills directory in Hermes config.")
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--json", action="store_true", help="Print the machine-readable apply payload.")
    apply.set_defaults(func=cmd_apply)

    uninstall = sub.add_parser("uninstall", help="Remove OMH-managed registration, local files, and optional command package.")
    uninstall.add_argument("--registration-only", action="store_true", help="Only remove the OMH skills.external_dirs registration from Hermes config.")
    uninstall.add_argument("--remove-files", action="store_true", help="Legacy mode: remove Hermes registration and the managed OMH home directory.")
    uninstall.add_argument("--all", action="store_true", help="Remove all OMH-managed local state, plugin bundle, and generated team role files.")
    uninstall.add_argument("--purge", action="store_true", help="Alias for --all.")
    uninstall.add_argument("--keep-command", action="store_true", help="Keep the installer-managed omh command venv/shim during full cleanup.")
    uninstall.add_argument("--force", action="store_true", help="Also remove an unmanaged ~/.hermes/plugins/omh directory when using --all.")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--json", action="store_true", help="Print the machine-readable uninstall payload.")
    uninstall.add_argument("--language", default=None, help=f"Human output language ({', '.join(LANGUAGE_CODES)}).")
    uninstall.set_defaults(func=cmd_uninstall)

    list_cmd = sub.add_parser("list", help="Show the installed managed skill manifest.")
    list_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable manifest.")
    list_cmd.set_defaults(func=cmd_list)

    skill_profile = sub.add_parser(
        "skill-profile",
        help="Inspect or explicitly reconcile the installed core/full skill profile.",
    )
    skill_profile_sub = skill_profile.add_subparsers(dest="skill_profile_command", required=True)
    skill_profile_status = skill_profile_sub.add_parser(
        "status",
        help="Show the requested profile, the effective installed profile, and retained exceptions.",
    )
    skill_profile_status.add_argument("--json", action="store_true", help="Print the full machine-readable profile state.")
    skill_profile_status.set_defaults(func=cmd_skill_profile_status)
    skill_profile_reconcile = skill_profile_sub.add_parser(
        "reconcile",
        help=(
            "Explicitly shrink an existing install to the core profile by removing unmodified "
            "managed full-only skills. setup/install/update never do this."
        ),
    )
    skill_profile_reconcile.add_argument(
        "--to",
        choices=("core",),
        default="core",
        help="Target profile to reconcile down to. Only core shrinks an install.",
    )
    skill_profile_reconcile.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the removals and retained exceptions without deleting anything.",
    )
    skill_profile_reconcile.add_argument("--json", action="store_true", help="Print the full machine-readable reconcile payload.")
    skill_profile_reconcile.set_defaults(func=cmd_skill_profile_reconcile)

    # Imported here rather than at module scope: `capability_policy` is a
    # command module like the ones `main` imports from here, so a top-level
    # import would close a cycle through this module's own parser wiring.
    from .capability_policy import (
        cmd_capability_policy_disable,
        cmd_capability_policy_enable,
        cmd_capability_policy_status,
    )

    capability_policy = sub.add_parser(
        "capability-policy",
        help="Show or change which OMH capability families this install offers.",
    )
    capability_policy_sub = capability_policy.add_subparsers(dest="capability_policy_command", required=True)
    capability_policy_status = capability_policy_sub.add_parser(
        "status",
        help="Show each capability family, whether it is offered, and the command that flips it.",
    )
    capability_policy_status.add_argument("--json", action="store_true", help="Print the full machine-readable policy report.")
    capability_policy_status.set_defaults(func=cmd_capability_policy_status)
    capability_policy_disable = capability_policy_sub.add_parser(
        "disable",
        help="Stop offering one capability family. Core skills are never removed and the change is reversible.",
    )
    capability_policy_disable.add_argument("family", help="Capability family id, label, or short alias (for example memory).")
    capability_policy_disable.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the affected workflows without writing the policy.",
    )
    capability_policy_disable.add_argument("--json", action="store_true", help="Print the full machine-readable change payload.")
    capability_policy_disable.set_defaults(func=cmd_capability_policy_disable)
    capability_policy_enable = capability_policy_sub.add_parser(
        "enable",
        help="Offer one capability family again.",
    )
    capability_policy_enable.add_argument("family", help="Capability family id, label, or short alias (for example memory).")
    capability_policy_enable.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the affected workflows without writing the policy.",
    )
    capability_policy_enable.add_argument("--json", action="store_true", help="Print the full machine-readable change payload.")
    capability_policy_enable.set_defaults(func=cmd_capability_policy_enable)

    doctor = sub.add_parser("doctor", help="Check local OMH install health and Hermes skill registration.")
    doctor.add_argument("--json", action="store_true", help="Print the full machine-readable doctor payload.")
    doctor.add_argument("--language", default=None, help=f"Human output language ({', '.join(LANGUAGE_CODES)}).")
    doctor.set_defaults(func=cmd_doctor)

    recommend = sub.add_parser("recommend", help="Map a task description to likely OMH workflow skills.")
    recommend.add_argument("task", nargs="+", help="Task description to map to OMH workflow skills.")
    recommend.add_argument("--limit", type=int, default=5, help="Maximum recommendations to return.")
    recommend.add_argument("--json", action="store_true", help="Print the full machine-readable recommendation payload.")
    recommend.set_defaults(func=cmd_recommend)

    snippet = sub.add_parser("snippet", help="Print or write the workspace guidance snippet for agents.")
    snippet.add_argument("--dry-run", action="store_true")
    snippet.add_argument("--output", default=None)
    snippet.add_argument("--json", action="store_true", help="Print machine-readable output when writing to --output.")
    snippet.set_defaults(func=cmd_snippet)

    probe = sub.add_parser("probe", help="Inspect observable OMH/Hermes capability surfaces.")
    probe.add_argument(
        "--parity",
        action="store_true",
        help="Include the OMH parity matrix for common oh-my agent runtime capability axes.",
    )
    probe.add_argument(
        "--roadmap",
        action="store_true",
        help="Include next actions that separate product setup gaps from missing host/runtime evidence.",
    )
    probe.add_argument("--json", action="store_true", help="Print the full machine-readable capability payload.")
    probe.set_defaults(func=cmd_probe)

    profile = sub.add_parser("profile", help="List or inspect optional visible team role/profile packs.")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true", help="Print the full machine-readable profile pack catalog.")
    profile_list.set_defaults(func=cmd_profile_list)
    profile_inspect = profile_sub.add_parser("inspect")
    profile_inspect.add_argument("id")
    profile_inspect.add_argument("--json", action="store_true", help="Print the full machine-readable profile pack payload.")
    profile_inspect.set_defaults(func=cmd_profile_inspect)
