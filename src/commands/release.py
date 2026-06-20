from __future__ import annotations

import argparse

from .. import __version__
from ..installer import OmhError
from ..release import (
    DEFAULT_HERMES_SKILL,
    DEFAULT_HERMES_TAP,
    INSTALL_PATHS,
    hermes_release_smoke_plan,
    release_readiness_checklist,
    run_hermes_release_smoke,
    run_installed_command_smoke,
    skill_content_smoke,
)
from ..release_install_smoke import install_script_smoke_plan, run_install_script_smoke
from .common import _print_json, _wants_json


def cmd_release_checklist(args: argparse.Namespace) -> int:
    try:
        payload = release_readiness_checklist(version=args.version or __version__, omh_command=args.omh_command)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_release_checklist_summary(payload)
    return 0


def cmd_release_hermes_smoke(args: argparse.Namespace) -> int:
    if args.timeout < 1:
        raise OmhError("release hermes-smoke --timeout must be at least 1")
    if args.live and not args.target_confirmed and not args.hermes_home:
        raise OmhError(
            "release hermes-smoke --live mutates the target Hermes profile; pass --target-confirmed "
            "or set top-level --hermes-home to an explicit smoke profile"
        )
    if args.live:
        payload = run_hermes_release_smoke(
            install_path=args.install_path,
            skill=args.skill,
            tap=args.tap,
            omh_command=args.omh_command,
            omh_home=args.omh_home,
            hermes_home=args.hermes_home,
            timeout_seconds=args.timeout,
            include_command_smoke=args.include_command_smoke,
        )
        _print_json(payload)
        return 0 if payload["ok"] else 1
    installed_command_smoke = (
        run_installed_command_smoke(
            omh_command=args.omh_command,
            omh_home=args.omh_home,
            hermes_home=args.hermes_home,
            timeout_seconds=args.timeout,
        )
        if args.include_command_smoke
        else None
    )
    payload = hermes_release_smoke_plan(
        install_path=args.install_path,
        skill=args.skill,
        tap=args.tap,
        omh_command=args.omh_command,
        omh_home=args.omh_home,
        hermes_home=args.hermes_home,
        installed_command_smoke=installed_command_smoke,
    )
    _print_json(payload)
    return 0 if payload["ok"] else 1


def cmd_release_install_smoke(args: argparse.Namespace) -> int:
    setup_args = tuple(args.setup_args or (["--no-interactive"] if args.run_setup else []))
    try:
        if args.live:
            payload = run_install_script_smoke(
                repo_root=args.repo_root,
                install_script=args.install_script,
                package_url=args.package_url,
                python_command=args.python,
                setup_args=setup_args,
                run_setup=args.run_setup,
                run_doctor=not args.skip_doctor,
                timeout_seconds=args.timeout,
                work_dir=args.work_dir,
                keep_work_dir=args.keep_work_dir,
            )
        else:
            payload = install_script_smoke_plan(
                repo_root=args.repo_root,
                install_script=args.install_script,
                package_url=args.package_url,
                python_command=args.python,
                setup_args=setup_args,
                run_setup=args.run_setup,
                run_doctor=not args.skip_doctor,
                work_dir=args.work_dir,
            )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args) or args.live:
        _print_json(payload)
    else:
        _print_install_smoke_summary(payload)
    return 0 if payload["ok"] else 1


def cmd_release_skill_content_smoke(args: argparse.Namespace) -> int:
    payload = skill_content_smoke()
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_skill_content_smoke_summary(payload)
    return 0 if payload["ok"] else 1


def _add_release_commands(sub) -> None:
    release = sub.add_parser("release", help="Plan or run release smoke checks for real Hermes installation paths.")
    release_sub = release.add_subparsers(dest="release_command", required=True)

    checklist = release_sub.add_parser(
        "checklist",
        help="Print the deterministic release readiness checklist.",
    )
    checklist.add_argument("--version", default="", help="Release version to prepare, such as 1.0.0 or v1.0.0.")
    checklist.add_argument("--omh-command", default="omh", help="Installed OMH executable name or path to show in smoke commands.")
    checklist.add_argument("--json", action="store_true", help="Print the machine-readable release checklist payload.")
    checklist.set_defaults(func=cmd_release_checklist)

    smoke = release_sub.add_parser(
        "hermes-smoke",
        help="Plan or run the release smoke for a real Hermes CLI skill install.",
    )
    smoke.add_argument("--live", action="store_true", help="Actually run the commands against the target Hermes profile.")
    smoke.add_argument(
        "--target-confirmed",
        action="store_true",
        help="Confirm that --live may mutate the resolved Hermes profile when no explicit --hermes-home was provided.",
    )
    smoke.add_argument(
        "--install-path",
        choices=INSTALL_PATHS,
        default="tap",
        help="Install path to exercise before list/check/inspect verification.",
    )
    smoke.add_argument("--skill", default=DEFAULT_HERMES_SKILL, help="Hermes skill identifier to install/check.")
    smoke.add_argument("--tap", default=DEFAULT_HERMES_TAP, help="Hermes skill tap repository to add for tap installs.")
    smoke.add_argument("--omh-command", default="omh", help="OMH executable to use for the setup install path.")
    smoke.add_argument(
        "--include-command-smoke",
        action="store_true",
        help="Also execute installed `omh --help` and installed setup-path plan rendering without mutating Hermes.",
    )
    smoke.add_argument("--timeout", type=int, default=30, help="Per-command timeout in seconds for --live or --include-command-smoke.")
    smoke.set_defaults(func=cmd_release_hermes_smoke)

    install_smoke = release_sub.add_parser(
        "install-smoke",
        help="Plan or run install.sh in an isolated temp home like a first-time downloader.",
    )
    install_smoke.add_argument("--live", action="store_true", help="Actually run install.sh in an isolated temp HOME/venv/bin.")
    install_smoke.add_argument("--repo-root", default=None, help="OMH source checkout to install from; defaults to the current checkout.")
    install_smoke.add_argument("--install-script", default=None, help="Path to install.sh; defaults to <repo-root>/install.sh.")
    install_smoke.add_argument("--package-url", default=None, help="Package URL/path passed to install.sh; defaults to the repo root.")
    install_smoke.add_argument("--python", default="", help="Python executable passed as OMH_PYTHON; defaults to this Python.")
    install_smoke.add_argument(
        "--run-setup",
        action="store_true",
        help="Set OMH_RUN_SETUP=1 for an advanced one-shot installer/setup compatibility smoke.",
    )
    install_smoke.add_argument(
        "--setup-args",
        nargs="*",
        default=None,
        help="Extra OMH_SETUP_ARGS passed only when --run-setup is used.",
    )
    install_smoke.add_argument(
        "--skip-doctor",
        action="store_true",
        help="Set OMH_RUN_DOCTOR=0 when --run-setup is used.",
    )
    install_smoke.add_argument("--work-dir", default=None, help="Use this work directory instead of a temporary one.")
    install_smoke.add_argument("--keep-work-dir", action="store_true", help="Keep the generated temporary work directory after --live.")
    install_smoke.add_argument("--timeout", type=int, default=120, help="Per-command timeout in seconds for --live.")
    install_smoke.add_argument("--json", action="store_true", help="Print the machine-readable install smoke payload.")
    install_smoke.set_defaults(func=cmd_release_install_smoke)

    skill_content = release_sub.add_parser(
        "skill-content-smoke",
        help="Verify generated OMH skill guidance in the current command package.",
    )
    skill_content.add_argument("--json", action="store_true", help="Print the machine-readable skill content smoke payload.")
    skill_content.set_defaults(func=cmd_release_skill_content_smoke)


def _print_release_checklist_summary(payload: dict[str, object]) -> None:
    print(f"OMH release checklist for {payload['version']} ({payload['tag']})")
    print("Mode: plan; observed evidence: no")
    print("Boundary: this command does not run checks, tag releases, or mutate Hermes.")
    print("")
    print("Required gates:")
    items = payload.get("items", [])
    required_items = [item for item in items if isinstance(item, dict) and item.get("required")]
    for index, item in enumerate(required_items, start=1):
        marker = "profile-mutating" if item.get("mutates_profile") else "local"
        if item.get("requires_release_authority"):
            marker = f"{marker}, release authority"
        print(f"  {index}. {item['id']} [{item['phase']}; {marker}]")
        print(f"     {item['command']}")
        print(f"     Evidence: {item['evidence_required']}")
    optional_items = [item for item in items if isinstance(item, dict) and not item.get("required")]
    authority_items = [item for item in optional_items if item.get("requires_release_authority")]
    non_authority_items = [item for item in optional_items if not item.get("requires_release_authority")]
    if authority_items:
        print("")
        print("Manual release-authority actions after evidence is attached:")
        for item in authority_items:
            print(f"  - {item['id']} [{item['phase']}; release authority]")
            print(f"    {item['command']}")
    if non_authority_items:
        print("")
        print("Optional follow-ups after evidence is attached:")
        for item in non_authority_items:
            print(f"  - {item['id']} [{item['phase']}]")
            print(f"    {item['command']}")
    print("")
    print(f"Next: {payload['recommended_next_action']}")
    print("For machine-readable output, rerun with `--json`.")


def _print_install_smoke_summary(payload: dict[str, object]) -> None:
    mode = str(payload.get("mode", "plan"))
    print("OMH install smoke")
    print(f"Mode: {mode}; observed evidence: {'yes' if payload.get('observed') else 'no'}")
    print(f"Install script: {payload.get('install_script')}")
    print(f"Package URL: {payload.get('package_url')}")
    print(f"Work dir: {payload.get('work_dir')}")
    print("")
    print("Steps:")
    for step in payload.get("steps", []):
        if not isinstance(step, dict):
            continue
        print(f"  - {step.get('name')} [{step.get('phase')}]")
        command = step.get("command", [])
        if isinstance(command, list):
            print(f"    {' '.join(str(part) for part in command)}")
        print(f"    Boundary: {step.get('proof_boundary', '')}")
    print("")
    print(f"Next: {payload.get('recommended_next_action')}")
    print("For machine-readable output, rerun with `--json`.")


def _print_skill_content_smoke_summary(payload: dict[str, object]) -> None:
    print("OMH skill content smoke")
    print(f"Status: {'ok' if payload.get('ok') else 'failed'}")
    print(f"Skills checked: {payload.get('skill_count')}")
    print(f"Markers checked: {payload.get('checked_marker_count')}")
    limits = payload.get("awareness_context_char_limits", {})
    if isinstance(limits, dict):
        primer_limit = limits.get("primer_context")
        workflow_limit = limits.get("workflow_context")
        print(
            "Awareness context: "
            f"primer {payload.get('awareness_primer_context_chars')}/{primer_limit} chars; "
            f"workflow max {payload.get('max_workflow_context_chars')}/{workflow_limit} chars"
        )
        role_limit = limits.get("role_context")
        print(
            "Role context: "
            f"{payload.get('role_context_count')} role surface(s); "
            f"bundled {payload.get('bundled_role_context_count')}; "
            f"max {payload.get('max_role_context_chars')}/{role_limit} chars"
        )
    capability_limits = payload.get("capability_context_char_limits", {})
    if isinstance(capability_limits, dict):
        print(
            "Capability payload: "
            f"full skills {payload.get('full_capability_skill_section_chars')}/"
            f"{capability_limits.get('full_skill_section')} chars; "
            f"fallback skills {payload.get('standalone_capability_skill_section_chars')}/"
            f"{capability_limits.get('standalone_skill_section')} chars"
        )
    failed = payload.get("failed_checks", [])
    missing = payload.get("missing_representative_skills", [])
    missing_awareness = payload.get("missing_awareness_lane_skills", [])
    unexpected_awareness = payload.get("unexpected_awareness_surfaces", [])
    missing_full = payload.get("missing_full_capability_skills", [])
    missing_full_context = payload.get("missing_full_capability_context_skills", [])
    missing_playbook_context = payload.get("missing_playbook_context_playbooks", [])
    missing_required_playbooks = payload.get("missing_required_playbook_capabilities", [])
    missing_standalone = payload.get("missing_standalone_capability_skills", [])
    unexpected_standalone = payload.get("unexpected_standalone_capability_skills", [])
    missing_standalone_context = payload.get("missing_standalone_capability_context_skills", [])
    missing_standalone_playbook_context = payload.get("missing_standalone_playbook_context_playbooks", [])
    missing_required_standalone_playbooks = payload.get("missing_required_standalone_playbook_capabilities", [])
    oversized_awareness = payload.get("oversized_awareness_contexts", [])
    missing_role_context = payload.get("missing_role_context_roles", [])
    missing_bundled_role_context = payload.get("missing_bundled_role_context_roles", [])
    missing_bundled_role_files = payload.get("missing_bundled_role_files", [])
    unexpected_bundled_role_files = payload.get("unexpected_bundled_role_files", [])
    stale_bundled_role_context = payload.get("stale_bundled_role_context_roles", [])
    oversized_role_contexts = payload.get("oversized_role_contexts", [])
    role_context_budget_failures = payload.get("role_context_budget_failures", [])
    capability_budget_failures = payload.get("capability_budget_failures", [])
    use_case_demo_failures = payload.get("use_case_demo_failures", [])
    print(
        "Full capability manifest: "
        f"{payload.get('full_capability_skill_count')} skill surface(s); "
        f"missing {len(missing_full) if isinstance(missing_full, list) else 0}; "
        f"context missing {len(missing_full_context) if isinstance(missing_full_context, list) else 0}"
    )
    print(
        "Playbook capabilities: "
        f"full {payload.get('playbook_capability_count')} playbook(s); "
        f"fallback {payload.get('standalone_playbook_capability_count')}; "
        f"context missing {len(missing_playbook_context) if isinstance(missing_playbook_context, list) else 0}/"
        f"{len(missing_standalone_playbook_context) if isinstance(missing_standalone_playbook_context, list) else 0}"
    )
    print(
        "Plugin fallback capabilities: "
        f"{payload.get('standalone_capability_skill_count')} workflow skill(s); "
        f"missing {len(missing_standalone) if isinstance(missing_standalone, list) else 0}; "
        f"context missing {len(missing_standalone_context) if isinstance(missing_standalone_context, list) else 0}"
    )
    print(
        "Use-case demo cards: "
        f"{payload.get('use_case_demo_card_count')}/{payload.get('expected_use_case_demo_card_count')} card(s); "
        f"failures {len(use_case_demo_failures) if isinstance(use_case_demo_failures, list) else 0}"
    )
    if missing:
        print("Missing representative skills: " + ", ".join(str(item) for item in missing))
    if missing_awareness:
        print("Missing awareness lane skills: " + ", ".join(str(item) for item in missing_awareness))
    if unexpected_awareness:
        print("Unexpected awareness surfaces: " + ", ".join(str(item) for item in unexpected_awareness))
    if missing_full:
        print("Missing full capability skills: " + ", ".join(str(item) for item in missing_full))
    if missing_full_context:
        print("Missing full capability context: " + ", ".join(str(item) for item in missing_full_context))
    if missing_required_playbooks:
        print("Missing required playbook capabilities: " + ", ".join(str(item) for item in missing_required_playbooks))
    if missing_playbook_context:
        print("Missing playbook capability context: " + ", ".join(str(item) for item in missing_playbook_context))
    if missing_standalone:
        print("Missing standalone capability skills: " + ", ".join(str(item) for item in missing_standalone))
    if unexpected_standalone:
        print("Unexpected standalone capability skills: " + ", ".join(str(item) for item in unexpected_standalone))
    if missing_standalone_context:
        print(
            "Missing standalone capability context: "
            + ", ".join(str(item) for item in missing_standalone_context)
        )
    if missing_required_standalone_playbooks:
        print(
            "Missing required standalone playbook capabilities: "
            + ", ".join(str(item) for item in missing_required_standalone_playbooks)
        )
    if missing_standalone_playbook_context:
        print(
            "Missing standalone playbook capability context: "
            + ", ".join(str(item) for item in missing_standalone_playbook_context)
        )
    if oversized_awareness:
        print("Oversized awareness contexts: " + ", ".join(str(item) for item in oversized_awareness))
    if missing_role_context:
        print("Missing role context: " + ", ".join(str(item) for item in missing_role_context))
    if missing_bundled_role_context:
        print("Missing bundled role context: " + ", ".join(str(item) for item in missing_bundled_role_context))
    if missing_bundled_role_files:
        print("Missing bundled role files: " + ", ".join(str(item) for item in missing_bundled_role_files))
    if unexpected_bundled_role_files:
        print("Unexpected bundled role files: " + ", ".join(str(item) for item in unexpected_bundled_role_files))
    if stale_bundled_role_context:
        print("Stale bundled role context: " + ", ".join(str(item) for item in stale_bundled_role_context))
    if oversized_role_contexts:
        print("Oversized role contexts: " + ", ".join(str(item) for item in oversized_role_contexts))
    if role_context_budget_failures:
        print("Role context budget failures: " + ", ".join(str(item) for item in role_context_budget_failures))
    if capability_budget_failures:
        print("Capability budget failures: " + ", ".join(str(item) for item in capability_budget_failures))
    if use_case_demo_failures:
        print("Use-case demo card failures: " + ", ".join(str(item) for item in use_case_demo_failures))
    if isinstance(failed, list) and failed:
        print("Failed markers:")
        for check in failed[:12]:
            if isinstance(check, dict):
                print(f"  - {check.get('skill')}: {check.get('marker')}")
        if len(failed) > 12:
            print(f"  ... {len(failed) - 12} more")
    print(f"Boundary: {payload.get('proof_boundary')}")
    print("For machine-readable output, rerun with `--json`.")
