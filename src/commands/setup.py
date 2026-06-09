from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows compatibility guard.
    termios = None
    tty = None

from .. import __version__
from ..config_adapter import ensure_external_dir, external_dirs, read_config, remove_external_dir, write_config
from ..doctor import doctor_ok, recommended_next_action, run_doctor
from ..executors import CODING_EXECUTOR_TARGETS
from ..hashutil import sha256_file
from ..installer import OmhError, install_skill_pack, uninstall_skill_pack
from ..local_store import atomic_write_text
from ..manifest import read_manifest
from ..plugin_pack import PluginPackError, install_plugin_bundle
from ..probe import probe_capabilities
from ..release import RELEASE_CHANNELS, package_url_for
from ..routing.recommend import recommend_skills
from ..runtime.artifacts import update_state
from ..setup_profiles import (
    build_setup_profile,
    setup_profile_categories_for_executor,
    write_setup_profile,
)
from ..snippet import WORKSPACE_SNIPPET
from ..targets import record_target_observation
from ..team_profiles import TeamProfileError, inspect_team_profile_pack, install_team_profile_pack, list_team_profile_packs
from .common import _paths, _print_json, _wants_json


def cmd_install(args: argparse.Namespace) -> int:
    if _wants_json(args):
        payload = _install_result(args)
        _print_json(payload)
    else:
        command = str(getattr(args, "command", "install"))
        label = "update" if command == "update" else "install"
        progress = _HumanProgress(enabled=True, use_color=_use_color())
        progress.header(f"OMH {label}", "Refresh the managed Hermes skill pack.")
        progress.step(1, 1, "Preparing managed skills")
        payload = _install_result(args)
        skills = payload.get("skills", [])
        progress.done(f"{len(skills) if isinstance(skills, list) else 0} managed skill(s) ready")
        _print_install_summary(payload, command=str(getattr(args, "command", "install")))
    return 0


def _install_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    try:
        release = package_url_for(args.channel, args.version or "", args.package_url or "")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.channel == "local" and not (args.from_skills_dir or args.source):
        raise OmhError("local channel requires --from-skills-dir or --source")
    source_dir = Path(args.from_skills_dir or args.source).expanduser().resolve() if (args.from_skills_dir or args.source) else None
    source = str(source_dir) if source_dir else "builtin"
    result = install_skill_pack(paths, source=source, source_dir=source_dir, force=args.force, dry_run=args.dry_run)
    result.update({"release_channel": release.channel, "release_version": release.version, "release_package_url": release.package_url})
    if not args.dry_run:
        update_state(
            paths,
            {
                "package": "oh-my-hermes-agent",
                "version": __version__,
                "manifest_path": str(paths.manifest_path),
                "manifest_sha256": sha256_file(paths.manifest_path),
                "source": source,
                "release_channel": release.channel,
                "release_version": release.version,
                "release_package_url": release.package_url,
                "installed_skills": len(result.get("skills", [])),
                "skills_dir": str(paths.skills_dir),
            },
        )
    return result


def cmd_update(args: argparse.Namespace) -> int:
    return cmd_install(args)


def cmd_convert(args: argparse.Namespace) -> int:
    args.source = args.from_skills_dir
    args.channel = "local"
    args.version = ""
    args.package_url = ""
    return cmd_install(args)


def cmd_apply(args: argparse.Namespace) -> int:
    _print_json(_apply_result(args))
    return 0


def _apply_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = ensure_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    if not args.dry_run:
        update_state(
            paths,
            {
                "hermes_config_path": str(paths.hermes_config_path),
                "last_applied_skills_dir": str(paths.skills_dir),
                "external_dir_registered": str(paths.skills_dir) in read_config(paths.hermes_config_path),
            },
        )
    return {"changed": change.changed, "message": change.message, "config": str(paths.hermes_config_path), "skills_dir": str(paths.skills_dir), "dry_run": args.dry_run}


def cmd_uninstall(args: argparse.Namespace) -> int:
    paths = _paths(args)
    current = read_config(paths.hermes_config_path)
    try:
        change = remove_external_dir(current, paths.skills_dir)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run and change.changed:
        write_config(paths.hermes_config_path, change.text)
    result = uninstall_skill_pack(paths, remove_files=args.remove_files and not args.dry_run)
    result.update({"config_changed": change.changed, "dry_run": args.dry_run})
    _print_json(result)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    manifest = read_manifest(_paths(args).manifest_path)
    _print_json(manifest or {"skills": [], "message": "not installed"})
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = _doctor_result(args)
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_doctor_summary(payload)
    return 0 if payload["ok"] else 1


def _doctor_result(args: argparse.Namespace) -> dict[str, object]:
    paths = _paths(args)
    checks = run_doctor(paths)
    runtime_writable = any(check.name == "runtime_artifacts" and check.ok for check in checks)
    runtime_state_readable = not any(check.name == "runtime_state" and not check.ok for check in checks)
    if runtime_writable and runtime_state_readable:
        next_action = recommended_next_action(checks)
        update_state(
            paths,
            {
                "last_doctor": {
                    "ok": doctor_ok(checks),
                    "checks": {check.name: check.ok for check in checks},
                    "recommended_next_action": next_action,
                }
            },
        )
    return {
        "ok": doctor_ok(checks),
        "checks": [check.__dict__ for check in checks],
        "recommended_next_action": recommended_next_action(checks),
    }


def cmd_setup(args: argparse.Namespace) -> int:
    paths = _paths(args)
    if _setup_should_interact(args):
        _run_setup_wizard(args, paths)

    progress = _HumanProgress(enabled=not _wants_json(args), use_color=_use_color())
    if not _wants_json(args):
        progress.header("OMH setup", "Connect the installed OMH workflows to this Hermes profile.")
    total_steps = 4 + (1 if args.with_plugin else 0) + (1 if args.profile_pack else 0)
    step_index = 1

    progress.step(step_index, total_steps, "Installing managed skills", detail=str(paths.skills_dir))
    steps: dict[str, object] = {"install": _install_result(args)}
    install_skills = steps["install"].get("skills", []) if isinstance(steps["install"], dict) else []
    progress.done(f"{len(install_skills) if isinstance(install_skills, list) else 0} skill(s) installed")
    step_index += 1

    progress.step(step_index, total_steps, "Registering Hermes skill discovery", detail=str(paths.hermes_config_path))
    if args.skip_apply:
        steps["apply"] = {"skipped": True, "message": "Skipped Hermes config registration because --skip-apply was set."}
        progress.skip("skipped by --skip-apply")
    else:
        steps["apply"] = _apply_result(args)
        apply_message = steps["apply"].get("message", "configured") if isinstance(steps["apply"], dict) else "configured"
        progress.done(str(apply_message))
    step_index += 1

    if args.with_plugin:
        progress.step(step_index, total_steps, "Installing optional plugin bridge", detail=str(paths.hermes_plugin_dir))
        steps["plugin"] = _plugin_setup_result(args, paths)
        plugin_status = steps["plugin"].get("status", "installed") if isinstance(steps["plugin"], dict) else "installed"
        progress.done(str(plugin_status))
        step_index += 1

    if args.profile_pack:
        progress.step(step_index, total_steps, "Activating visible team role preset", detail=", ".join(args.profile_pack))
        steps["team_profiles"] = _team_profile_setup_result(args, paths)
        progress.done(f"{len(steps['team_profiles']) if isinstance(steps['team_profiles'], list) else 0} profile pack(s) activated")
        step_index += 1

    progress.step(step_index, total_steps, "Saving routing preferences")
    steps["profile"] = _setup_profile_result(args, paths)
    profile_executor = steps["profile"].get("default_executor", "choose") if isinstance(steps["profile"], dict) else "choose"
    progress.done(f"default executor: {profile_executor}")
    step_index += 1

    progress.step(step_index, total_steps, "Detecting Hermes target topology")
    steps["targets"] = record_target_observation(
        paths,
        source="setup",
        dry_run=args.dry_run,
        ensure_config=not args.skip_apply,
        setup_context={
            "apply_skipped": bool(args.skip_apply),
            "with_plugin": bool(args.with_plugin),
            "profile_packs": list(args.profile_pack),
            "setup_profiles": list(args.profile),
            "default_executor": str(getattr(args, "default_executor", "") or ""),
        },
    )
    target_topology = steps["targets"].get("topology", {}) if isinstance(steps["targets"], dict) else {}
    if isinstance(target_topology, dict):
        progress.done(f"{target_topology.get('mode', 'unknown')} ({target_topology.get('known_target_count', 0)} target(s))")
    else:
        progress.done("target topology recorded")
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
        "equivalent_hermes_commands": [
            "hermes skills tap add rlaope/oh-my-hermes-agent",
            "hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes",
        ],
        "bootstrap_final_state": bootstrap_final_state,
        "skills_dir": str(paths.skills_dir),
        "hermes_config_path": str(paths.hermes_config_path),
        "hermes_config_key": "skills.external_dirs",
        "target_topology": steps["targets"]["topology"],
        "wrapper_backend_surface": "omh chat interact and runtime commands are adapter/operator contracts, not the normal chat UX",
    }

    if not args.dry_run:
        update_state(
            paths,
            {
                "last_setup": {
                    "ok": True,
                    "apply_skipped": bool(args.skip_apply),
                    "hermes_native": hermes_native,
                    "setup_profile": steps["profile"],
                    "team_profiles": steps.get("team_profiles", []),
                    "target_observation": steps["targets"],
                }
            },
        )
    payload: dict[str, object] = {"ok": True, "steps": steps, "dry_run": args.dry_run, "hermes_native": hermes_native}
    if args.with_plugin:
        payload["plugin_distribution"] = steps["plugin"]
    if args.profile_pack:
        payload["team_profiles"] = steps["team_profiles"]
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_setup_summary(payload)
    return 0


def _setup_should_interact(args: argparse.Namespace) -> bool:
    if getattr(args, "interactive", False):
        return True
    if getattr(args, "no_interactive", False) or getattr(args, "yes", False):
        return False
    if _wants_json(args) or getattr(args, "dry_run", False):
        return False
    if args.profile or getattr(args, "default_executor", None) or args.profile_pack or args.with_plugin or args.skip_apply:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _run_setup_wizard(args: argparse.Namespace, paths) -> None:
    use_color = _use_color()
    print(_color("OMH setup", "1;36", use_color))
    print("I will install the OMH skill pack, connect it to Hermes, and only ask for choices that change runtime behavior.")
    print(f"Hermes home: {_color(str(paths.hermes_home), '36', use_color)}")
    if paths.hermes_config_path.exists():
        config_text = read_config(paths.hermes_config_path)
        registered = str(paths.skills_dir) in external_dirs(config_text)
        status = "already registered" if registered else "will register OMH skills"
        print(f"Hermes config: {_color(str(paths.hermes_config_path), '36', use_color)} ({status})")
    else:
        print(f"Hermes config: {_color(str(paths.hermes_config_path), '36', use_color)} (will create)")
    print(f"Managed skills: {_color(str(paths.skills_dir), '36', use_color)}")

    args.skip_apply = not _ask_yes_no(
        "Register OMH skills in this Hermes profile?",
        default=True,
        use_color=use_color,
        note="This updates skills.external_dirs so Hermes can discover the managed OMH skills.",
    )
    args.default_executor = _ask_default_executor(use_color=use_color)
    args.profile = setup_profile_categories_for_executor(str(args.default_executor))
    args.with_plugin = _ask_yes_no(
        "Install the optional plugin bridge?",
        default=False,
        use_color=use_color,
        note="The plugin exposes local status context to Hermes; OMH skills work without it.",
    )
    args.profile_pack = _ask_team_profile_packs(use_color=use_color)
    print("")


def _ask_default_executor(*, use_color: bool) -> str:
    options = [
        {
            "choice": "1",
            "value": "choose",
            "label": "Ask me when coding is needed",
            "description": "Recommended. Hermes prepares the workflow and asks before choosing Codex, Claude Code, or another executor.",
        },
        {
            "choice": "2",
            "value": "codex",
            "label": "Codex tracked handoff",
            "description": "Use Codex as the default for implementation-shaped work and keep dispatch/result/review/CI evidence separate.",
        },
        {
            "choice": "3",
            "value": "claude-code",
            "label": "Claude Code prompt handoff",
            "description": "Prepare copy-ready Claude Code prompts; OMH will not claim Claude Code ran unless a wrapper records evidence.",
        },
        {
            "choice": "4",
            "value": "generic",
            "label": "Portable prompt handoff",
            "description": "Prepare executor-neutral prompts for any coding agent without direct dispatch.",
        },
        {
            "choice": "5",
            "value": "hermes",
            "label": "Keep coding-like work in Hermes",
            "description": "Keep retained planning and small changes with Hermes; larger coding can still be handed off per request.",
        },
        {
            "choice": "6",
            "value": "omx-runtime",
            "label": "Plugin/runtime prompt handoff",
            "description": "Prepare OMX/OMO/OMC-style runtime prompts without assuming those runtimes are active.",
        },
    ]
    value = _ask_single_choice(
        "Default for coding-shaped requests",
        [
            "This is only a default. All OMH skills are installed either way.",
            "Hermes can still ask or route differently when a request needs it.",
        ],
        options,
        default_choice="1",
        use_color=use_color,
    )
    try:
        build_setup_profile(default_executor=value)
    except ValueError as exc:
        print(_color(f"Invalid default executor: {exc}", "31", use_color))
        return "choose"
    return value


def _ask_team_profile_packs(*, use_color: bool) -> list[str]:
    catalog = list_team_profile_packs()
    packs = catalog.get("packs", []) if isinstance(catalog, dict) else []
    options = [
        {
            "choice": "0",
            "value": "",
            "label": "No extra team persona now",
            "description": "Recommended for first install. All OMH workflows remain installed and available.",
        }
    ]
    for idx, pack in enumerate(packs, start=1):
        pack_id = str(pack["id"])
        options.append(
            {
                "choice": str(idx),
                "value": pack_id,
                "label": str(pack["title"]),
                "description": str(pack["summary"]),
            }
        )
    while True:
        value = _ask_single_choice(
            "Activate a visible team persona now?",
            [
                "These are optional Hermes role files, not missing features.",
                "You can add them later with `omh setup --profile-pack <id>`.",
            ],
            options,
            default_choice="0",
            use_color=use_color,
        )
        if not value:
            return []
        return [value]


def _ask_yes_no(prompt: str, *, default: bool, use_color: bool, note: str = "") -> bool:
    if _keyboard_menu_available():
        value = _ask_single_choice(
            prompt,
            [note] if note else [],
            [
                {"choice": "1", "value": "yes", "label": "Yes", "description": "Apply this setup step."},
                {"choice": "2", "value": "no", "label": "No", "description": "Skip this step for now."},
            ],
            default_choice="1" if default else "2",
            use_color=use_color,
        )
        return value == "yes"
    suffix = "Y/n" if default else "y/N"
    if note:
        print(f"  {note}")
    while True:
        value = _ask(prompt, default=suffix, use_color=use_color).strip().lower()
        if not value or value == suffix.lower():
            return default
        if value in {"y", "yes", "1"}:
            return True
        if value in {"n", "no", "2"}:
            return False
        print(_color("Please answer y or n.", "31", use_color))


def _ask_single_choice(
    title: str,
    intro_lines: list[str],
    options: list[dict[str, str]],
    *,
    default_choice: str,
    use_color: bool,
) -> str:
    normalized = [_normalize_choice_option(option) for option in options]
    if _keyboard_menu_available():
        return _keyboard_single_choice(title, intro_lines, normalized, default_choice=default_choice, use_color=use_color)

    print("")
    print(_color(title, "1;32", use_color))
    for line in intro_lines:
        print(f"  {line}")
    for option in normalized:
        suffix = " (recommended)" if option["choice"] == default_choice else ""
        print(f"  {option['choice']}) {option['label']}{suffix}")
        if option["description"]:
            print(f"     {option['description']}")
    values_by_choice = {option["choice"]: option["value"] for option in normalized}
    values_by_value = {option["value"]: option["value"] for option in normalized}
    while True:
        raw = _ask("Select", default=default_choice, use_color=use_color).strip()
        value = raw or default_choice
        if value in values_by_choice:
            return values_by_choice[value]
        if value in values_by_value:
            return values_by_value[value]
        valid = ", ".join(option["choice"] for option in normalized)
        print(_color(f"Invalid selection. Choose one of: {valid}.", "31", use_color))


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
) -> str:
    cursor = _default_choice_index(options, default_choice)
    rendered_lines = 0
    while True:
        lines = _choice_menu_lines(title, intro_lines, options, cursor, default_choice=default_choice, use_color=use_color)
        if rendered_lines:
            sys.stdout.write(f"\033[{rendered_lines}F\033[J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        rendered_lines = len(lines)
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
) -> list[str]:
    lines = ["", _color(title, "1;32", use_color)]
    for line in intro_lines:
        lines.append(f"  {line}")
    lines.append(_color("  Use ↑/↓, Space/Enter, or a number. Colors are not required.", "2", use_color))
    for index, option in enumerate(options):
        active = index == cursor
        pointer = ">" if active else " "
        marker = "[x]" if active else "[ ]"
        suffix = " (recommended)" if option["choice"] == default_choice else ""
        label = f"  {pointer} {marker} {option['choice']}) {option['label']}{suffix}"
        if active:
            label = _color(label, "1;36", use_color)
        lines.append(label)
        if option["description"]:
            lines.append(f"      {option['description']}")
    return lines


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


def _print_setup_summary(payload: dict[str, object]) -> None:
    use_color = _use_color()
    steps = payload.get("steps", {})
    hermes_native = payload.get("hermes_native", {})
    if not isinstance(steps, dict):
        steps = {}
    if not isinstance(hermes_native, dict):
        hermes_native = {}

    install = steps.get("install", {})
    apply = steps.get("apply", {})
    profile = steps.get("profile", {})
    targets = steps.get("targets", {})
    skills = install.get("skills", []) if isinstance(install, dict) else []
    topology = targets.get("topology", {}) if isinstance(targets, dict) else {}

    dry_run = bool(payload.get("dry_run", False))
    title = "OMH setup preview complete." if dry_run else "OMH setup complete."
    print("")
    print(_color(title, "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Skills: {len(skills)} managed skill(s) at {hermes_native.get('skills_dir', '')}")

    discovery_status = str(hermes_native.get("discovery_status", ""))
    if discovery_status == "config_registered_reload_required":
        print(
            "  Hermes registration: configured in "
            f"{hermes_native.get('hermes_config_path', '')} "
            "(restart or reload Hermes Agent to observe it)."
        )
    elif discovery_status == "dry_run_not_observed":
        print("  Hermes registration: dry run only; no local registration was observed.")
    elif discovery_status == "not_registered_skip_apply":
        print("  Hermes registration: skipped by --skip-apply.")
    else:
        print(f"  Hermes registration: {discovery_status or 'unknown'}")

    if isinstance(apply, dict) and apply.get("message"):
        print(f"  Apply: {apply.get('message')}")

    if isinstance(profile, dict):
        selected = ", ".join(str(item) for item in profile.get("selected_categories", []) or [])
        executor = str(profile.get("default_executor", ""))
        if selected or executor:
            print(f"  Default handoff: {_executor_summary(executor)}")
            if selected:
                print(f"  Setup profile: {selected}")

    if isinstance(topology, dict):
        print(
            "  Target topology: "
            f"{topology.get('mode', 'unknown')} "
            f"({topology.get('known_target_count', 0)} known target(s))."
        )

    plugin = payload.get("plugin_distribution")
    if isinstance(plugin, dict):
        print(f"  Plugin bridge: {plugin.get('status', 'installed')}")
    elif not dry_run:
        print("  Plugin bridge: optional; install later with `omh setup --with-plugin`.")

    team_profiles = payload.get("team_profiles")
    if isinstance(team_profiles, list) and team_profiles:
        print(f"  Team persona: {len(team_profiles)} profile pack(s) activated.")
    elif not dry_run:
        print("  Team persona: none activated; all OMH workflows are still installed.")

    print(_color("Next", "1;32", use_color))
    if dry_run:
        print("  Rerun without `--dry-run` to install and register the managed skills.")
    else:
        print("  Restart or reload Hermes Agent, then try this in Hermes chat:")
        print("  Use OMH request-to-handoff for: I want to safely add a feature to this repo.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_doctor_summary(payload: dict[str, object]) -> None:
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    ok = bool(payload.get("ok", False))
    print("OMH doctor: ok" if ok else "OMH doctor: needs attention")
    print(f"Checks: {sum(1 for check in checks if isinstance(check, dict) and check.get('ok'))}/{len(checks)} passing")
    for check in checks:
        if not isinstance(check, dict) or check.get("ok"):
            continue
        name = check.get("name", "unknown")
        message = check.get("message", "")
        remediation = check.get("remediation", "") or check.get("next_action", "")
        print(f"- {name}: {message}")
        if remediation:
            print(f"  Fix: {remediation}")
    next_action = str(payload.get("recommended_next_action", "")).strip()
    if next_action:
        print(f"Next: {next_action}")
    print("For machine-readable output, rerun with `--json`.")


def _print_install_summary(payload: dict[str, object], *, command: str) -> None:
    use_color = _use_color()
    skills = payload.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    dry_run = bool(payload.get("dry_run", False))
    label = "update" if command == "update" else "install"
    title = f"OMH {label} preview complete." if dry_run else f"OMH {label} complete."
    print("")
    print(_color(title, "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Skills: {len(skills)} managed skill(s) at {payload.get('skills_dir', '')}")
    print(f"  Source: {payload.get('source', 'builtin')}")
    channel = str(payload.get("release_channel", "")).strip()
    package_url = str(payload.get("release_package_url", "")).strip()
    if channel:
        print(f"  Release channel: {channel}")
    if package_url and package_url != "local":
        print(f"  Package URL: {package_url}")
    print(_color("Next", "1;32", use_color))
    if dry_run:
        print("  Rerun without `--dry-run` to refresh the managed skills.")
    else:
        print("  Run `omh setup` to repair Hermes registration, or `omh doctor` to verify health.")
    print("  For machine-readable output, rerun with `--json`.")


def _executor_summary(executor: str) -> str:
    labels = {
        "choose": "ask before choosing executor",
        "codex": "Codex tracked handoff",
        "claude-code": "Claude Code prompt handoff",
        "generic": "portable prompt handoff",
        "hermes": "Hermes-retained work",
        "omx-runtime": "plugin/runtime prompt handoff",
        "omo-runtime": "plugin/runtime prompt handoff",
        "omc-runtime": "plugin/runtime prompt handoff",
    }
    return f"{labels.get(executor, 'unknown')} ({executor or 'unknown'})"


def _plugin_setup_result(args: argparse.Namespace, paths) -> dict[str, object]:
    try:
        result = install_plugin_bundle(paths, force=args.force, dry_run=args.dry_run)
    except PluginPackError as exc:
        raise OmhError(str(exc)) from exc
    if not args.dry_run:
        update_state(paths, {"last_plugin_distribution": result})
    return result


def _setup_profile_result(args: argparse.Namespace, paths) -> dict[str, object]:
    default_executor = str(getattr(args, "default_executor", "") or "") or None
    if args.dry_run:
        profile = build_setup_profile(args.profile, default_executor=default_executor)
        return {**profile, "dry_run": True, "written": False, "path": str(paths.setup_profile_path)}
    profile = write_setup_profile(paths, args.profile, default_executor=default_executor)
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
    _print_json(list_team_profile_packs())
    return 0


def cmd_profile_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(inspect_team_profile_pack(args.id))
    except TeamProfileError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("recommend --limit must be at least 1")
    query = " ".join(args.task).strip()
    if not query:
        raise OmhError("recommend requires a task description")
    _print_json({"query": query, "recommendations": recommend_skills(query, limit=args.limit)})
    return 0


def cmd_snippet(args: argparse.Namespace) -> int:
    if args.dry_run or not args.output:
        print(WORKSPACE_SNIPPET.rstrip())
        return 0
    output = Path(args.output).expanduser().resolve()
    atomic_write_text(output, WORKSPACE_SNIPPET)
    _print_json({"written": str(output)})
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    _print_json(probe_capabilities(_paths(args)))
    return 0


def _add_common_install_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--from-skills-dir", default=None, help="Import skills from a local skill directory.")
    p.add_argument("--source", default=None, help="Mockable local source directory for install/update.")
    p.add_argument("--channel", choices=RELEASE_CHANNELS, default="preview", help="Release channel metadata for this install/update.")
    p.add_argument("--version", default="", help="Stable release version such as 1.0.0 or v1.0.0.")
    p.add_argument("--package-url", default="", help="Explicit release archive URL for support and audit metadata.")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")


def _add_top_level_commands(sub) -> None:
    setup = sub.add_parser("setup")
    _add_common_install_options(setup)
    setup.add_argument("--json", action="store_true", help="Print the full machine-readable setup payload.")
    setup.add_argument("--yes", action="store_true", help="Use default setup choices without interactive prompts.")
    setup.add_argument("--interactive", action="store_true", help="Force the interactive setup wizard.")
    setup.add_argument("--no-interactive", action="store_true", help="Disable the interactive setup wizard.")
    setup.add_argument("--skip-apply", action="store_true", help="Install skills without registering them in Hermes config.")
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
        help="Default executor preference for coding-shaped handoffs. Use 'choose' to ask each time.",
    )
    setup.add_argument(
        "--with-plugin",
        action="store_true",
        help="Also install the optional OMH Hermes plugin bundle under ~/.hermes/plugins/omh.",
    )
    setup.add_argument(
        "--profile-pack",
        action="append",
        default=[],
        help="Install an optional Hermes agent/profile pack such as startup-delivery, engineering-delivery, research-strategy, or cto-loop.",
    )
    setup.set_defaults(func=cmd_setup)

    install = sub.add_parser("install")
    _add_common_install_options(install)
    install.add_argument("--json", action="store_true", help="Print the full machine-readable install payload.")
    install.set_defaults(func=cmd_install)

    update = sub.add_parser("update")
    _add_common_install_options(update)
    update.add_argument("--json", action="store_true", help="Print the full machine-readable update payload.")
    update.set_defaults(func=cmd_update)

    convert = sub.add_parser("convert")
    convert.add_argument("--from-skills-dir", required=True)
    convert.add_argument("--force", action="store_true")
    convert.add_argument("--dry-run", action="store_true")
    convert.set_defaults(func=cmd_convert)

    apply = sub.add_parser("apply")
    apply.add_argument("--dry-run", action="store_true")
    apply.set_defaults(func=cmd_apply)

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--remove-files", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall)

    list_cmd = sub.add_parser("list")
    list_cmd.set_defaults(func=cmd_list)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", help="Print the full machine-readable doctor payload.")
    doctor.set_defaults(func=cmd_doctor)

    recommend = sub.add_parser("recommend")
    recommend.add_argument("task", nargs="+", help="Task description to map to OMH workflow skills.")
    recommend.add_argument("--limit", type=int, default=5, help="Maximum recommendations to return.")
    recommend.set_defaults(func=cmd_recommend)

    snippet = sub.add_parser("snippet")
    snippet.add_argument("--dry-run", action="store_true")
    snippet.add_argument("--output", default=None)
    snippet.set_defaults(func=cmd_snippet)

    probe = sub.add_parser("probe")
    probe.set_defaults(func=cmd_probe)

    profile = sub.add_parser("profile")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.set_defaults(func=cmd_profile_list)
    profile_inspect = profile_sub.add_parser("inspect")
    profile_inspect.add_argument("id")
    profile_inspect.set_defaults(func=cmd_profile_inspect)
