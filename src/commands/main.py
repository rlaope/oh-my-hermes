# allow: SIZE_OK -- Central argparse registry intentionally keeps all command wiring cohesive and auditable.
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from ..version import __version__
from ..maintenance.build_identity import build_identity_summary, probe_build_identity
from ..installer import OmhError
from .achievements import (
    _add_achievements_commands,
    cmd_achievements_export,
    cmd_achievements_list,
    cmd_achievements_show,
    cmd_achievements_summary,
)
from .capabilities import (
    _add_capabilities_commands,
    cmd_capabilities_export,
    cmd_capabilities_inspect,
    cmd_capabilities_list,
)
from .chat import (
    _add_chat_commands,
    cmd_chat_interact,
    cmd_chat_route,
    cmd_chat_route_hint,
    cmd_chat_session_decision,
    cmd_chat_session_list,
    cmd_chat_session_prepare_handoff,
    cmd_chat_session_select_executor,
    cmd_chat_session_show,
    cmd_chat_session_start,
    cmd_chat_session_status,
)
from .coding import (
    _add_coding_commands,
    cmd_coding_delegate,
    cmd_coding_dynamic_workflow,
    cmd_coding_executor_readiness,
    cmd_coding_lifecycle_dispatch,
    cmd_coding_lifecycle_report,
    cmd_coding_lifecycle_result,
    cmd_coding_lifecycle_start,
    cmd_coding_lifecycle_verify,
)
from .codegraph import _add_codegraph_commands, cmd_codegraph_build, cmd_codegraph_handoff, cmd_codegraph_summary
from .common import _paths, set_json_output_pretty
from .context import _add_context_commands, cmd_context_brief
from .model_chains import _add_model_chains_commands
from .conformance import _add_conformance_commands, cmd_conformance_check
from .demo import _add_demo_commands, cmd_demo_orchestration
from .design import _add_design_commands, cmd_design_data
from .docs import (
    _add_docs_commands,
    _add_harness_commands,
    cmd_docs_workflows,
    cmd_harness_inspect,
    cmd_harness_list,
    cmd_harness_validate,
)
from .ecosystem import (
    _add_ecosystem_commands,
    cmd_ecosystem_awesome_inspect,
    cmd_ecosystem_awesome_list,
    cmd_ecosystem_awesome_outcomes,
    cmd_ecosystem_awesome_summary,
)
from .goal import (
    _add_goal_commands,
    cmd_goal_blocker,
    cmd_goal_checkpoint,
    cmd_goal_complete,
    cmd_goal_continue,
    cmd_goal_create,
    cmd_goal_status,
)
from .hermes import _add_hermes_commands, cmd_hermes_plan
from .hud import _add_hud_commands, cmd_hud
from .learning import (
    _add_learning_commands,
    cmd_learning_audit,
    cmd_learning_candidate,
    cmd_learning_eval,
    cmd_learning_export,
    cmd_learning_index_check,
    cmd_learning_index_rebuild,
    cmd_learning_list,
    cmd_learning_record,
    cmd_learning_regression_add,
    cmd_learning_regression_replay,
    cmd_learning_show,
)
from .loop import _add_loop_commands, cmd_loop_feedback, cmd_loop_permit, cmd_loop_run_once, cmd_loop_start, cmd_loop_status
from .materials import (
    _add_materials_commands,
    cmd_materials_export,
    cmd_materials_list,
    cmd_materials_plan,
    cmd_materials_qa_ladder,
    cmd_materials_show,
    cmd_materials_validate,
)
from .menubar import _add_menubar_commands, cmd_menubar_status
from .memory import (
    _add_memory_commands,
    cmd_memory_apply,
    cmd_memory_approve,
    cmd_memory_capture,
    cmd_memory_inspect,
    cmd_memory_pack,
    cmd_memory_recall,
    cmd_memory_reject,
    cmd_memory_review,
    cmd_memory_status,
)
from .mcp import (
    _add_mcp_commands,
    cmd_mcp_config_recipe,
    cmd_mcp_manifest,
    cmd_mcp_observe_host,
    cmd_mcp_serve,
    cmd_mcp_sessions,
)
from .plugin import _add_plugin_commands, cmd_plugin_observations, cmd_plugin_observe_host
from .quickstart import _add_quickstart_commands, cmd_quickstart
from .ops import (
    _add_ops_commands,
    cmd_ops_agent_review,
    cmd_ops_agent_review_list,
    cmd_ops_agent_review_show,
    cmd_ops_blueprint,
    cmd_ops_blueprint_list,
    cmd_ops_blueprint_show,
    cmd_ops_export,
    cmd_ops_list,
    cmd_ops_research_department,
    cmd_ops_research_department_list,
    cmd_ops_research_department_show,
    cmd_ops_show,
    cmd_ops_validate,
    cmd_ops_write,
)
from .playbook import _add_playbook_commands, cmd_playbook_inspect, cmd_playbook_list, cmd_playbook_recommend
from .release import _add_release_commands, cmd_release_checklist, cmd_release_hermes_smoke
from .runtime import (
    _add_runtime_commands,
    cmd_runtime_ci,
    cmd_runtime_delegate,
    cmd_runtime_delegation_status,
    cmd_runtime_export,
    cmd_runtime_merge,
    cmd_runtime_record,
    cmd_runtime_review,
    cmd_runtime_runs,
    cmd_runtime_show,
    cmd_runtime_status,
    cmd_runtime_team_readiness,
    cmd_runtime_validate,
    cmd_runtime_wrapper,
)
from .setup import (
    _add_top_level_commands,
    cmd_apply,
    cmd_convert,
    cmd_doctor,
    cmd_install,
    cmd_list,
    cmd_profile_inspect,
    cmd_profile_list,
    cmd_probe,
    cmd_recommend,
    cmd_setup,
    cmd_skill_profile_reconcile,
    cmd_skill_profile_status,
    cmd_snippet,
    cmd_uninstall,
    cmd_update,
)
from .state import _add_state_commands, cmd_state_clear, cmd_state_finish, cmd_state_start, cmd_state_status
from .theme import _add_theme_commands
from .update_check import _add_update_check_commands
from .use_cases import _add_cases_commands, cmd_cases_inspect, cmd_cases_list, cmd_cases_recommend
from .visual import _add_visual_commands, cmd_visual_observe, cmd_visual_prompt_card
from .adapter_quality import _add_adapter_quality_commands
from .cross_harness_benchmark import _add_benchmark_commands
from .quality_evidence import _add_quality_evidence_commands
from .web_qa import _add_web_qa_commands, cmd_web_qa_observe_capture, cmd_web_qa_package, cmd_web_qa_record_verdict
from .worktree import cmd_worktree_bind, cmd_worktree_list, _add_worktree_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omh",
        description=(
            "Install OMH once, then use Hermes chat.\n"
            "This command is for setup, health checks, local artifacts,\n"
            "and wrapper/backend operations."
        ),
        epilog=(
            "Quick start:\n"
            "  omh setup\n"
            "  omh doctor\n"
            "  omh quickstart\n\n"
            "First five minutes:\n"
            "  1. Run setup, accepting the recommended choices.\n"
            "  2. Restart or reload Hermes Agent.\n"
            "  3. Ask Hermes the prompt below.\n\n"
            "Normal use happens in Hermes chat:\n"
            "  Use OMH request-to-handoff for: I want to safely add a feature to this repo.\n\n"
            "If your shell says `omh` was not found after install, use the absolute\n"
            "command path printed by the installer or add that directory to PATH.\n\n"
            "Operator examples:\n"
            "  omh recommend \"risky refactor\"\n"
            "  omh cases recommend \"daily competitor digest\"\n"
            "  omh cases readiness\n"
            "  omh cases demo --all\n"
            "  omh cases artifact --all --write\n"
            "  omh cases replay\n"
            "  omh context brief \"make an image card for this PR\"\n"
            "  omh design data --kind palette --context fintech\n"
            "  omh playbook recommend \"turn this issue into a PR\"\n"
            "  omh chat interact \"turn this issue into a PR-ready plan\"\n"
            "  omh hud\n"
            "  omh achievements summary\n"
            "  omh menubar status\n"
            "  omh mcp manifest\n"
            "  omh mcp config-recipe --host codex\n"
            "  omh release evidence-bundle --version 1.0.5 --write\n"
            "  omh plugin observe-host --host hermes-agent --session <session-id> --event plugin_load --evidence-ref <host-log>\n"
            "  omh loop status\n"
            "  omh ops list\n"
            "  omh materials list\n"
            "  omh img-summary prompt-card --kind github_pr --visual-format auto --section summary:What_changed:Safer_setup_copy\n"
            "  omh img-summary prompt-card --kind report --aspect-ratio long_scroll --section summary:Executive_summary:Weekly_metrics_changed\n"
            "  omh worktree list\n"
            "  omh worktree bind --path .worktrees/risky-refactor --executor codex --session <session-id>\n"
            "  omh runtime status\n"
            "  omh runtime team-readiness\n\n"
            "Human-facing maintenance, catalog, and operator checklist commands print summaries by default;\n"
            "pass --json or set OMH_OUTPUT=json when a wrapper needs full payloads.\n"
            "Plain chat preview commands such as chat route, route-hint, and interact are summary-first;\n"
            "pass --json for adapter envelopes.\n"
            "Ledger/control-plane commands such as chat session, coding, runtime, goal, loop,\n"
            "learning, memory, state, harness, release smoke, and demo print JSON by design.\n"
            "JSON stdout is compact by default so supervising-agent context stays bounded;\n"
            "pass --pretty or set OMH_JSON_PRETTY=1 for indented, human-readable output."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--omh-home", default=None, help="Override the managed OMH home directory (default: ~/.omh).")
    parser.add_argument("--hermes-home", default=None, help="Override the target Hermes home directory (default: ~/.hermes).")
    parser.add_argument(
        "--scope",
        choices=("user", "project"),
        default=None,
        help="Choose default OMH/Hermes paths when explicit homes are not supplied.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print indented JSON for human reading (default is compact; OMH_JSON_PRETTY=1 also works).",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    _add_top_level_commands(sub)
    _add_quickstart_commands(sub)
    _add_docs_commands(sub)
    _add_harness_commands(sub)
    _add_cases_commands(sub)
    _add_playbook_commands(sub)
    _add_release_commands(sub)
    _add_demo_commands(sub)
    _add_design_commands(sub)
    _add_chat_commands(sub)
    _add_achievements_commands(sub)
    _add_capabilities_commands(sub)
    _add_conformance_commands(sub)
    _add_context_commands(sub)
    _add_model_chains_commands(sub)
    _add_ecosystem_commands(sub)
    _add_coding_commands(sub)
    _add_codegraph_commands(sub)
    _add_hermes_commands(sub)
    _add_hud_commands(sub)
    status = sub.add_parser("status", help="Alias for `omh hud`; show compact OMH status metadata.")
    status.add_argument("--json", action="store_true", help="Print the full machine-readable HUD payload.")
    status.add_argument("--preset", choices=("minimal", "focused", "full"), default="focused")
    status.add_argument("--limit", type=int, default=3, help="Recent runtime run count to summarize.")
    status.add_argument("--tokens-remaining", type=float, default=None)
    status.add_argument("--token-budget", type=float, default=None)
    status.add_argument("--input-tokens", type=float, default=None)
    status.add_argument("--output-tokens", type=float, default=None)
    status.add_argument("--context-remaining-percent", type=float, default=None)
    status.set_defaults(func=cmd_hud)
    _add_learning_commands(sub)
    _add_loop_commands(sub)
    _add_memory_commands(sub)
    _add_menubar_commands(sub)
    _add_mcp_commands(sub)
    _add_plugin_commands(sub)
    _add_ops_commands(sub)
    _add_materials_commands(sub)
    _add_visual_commands(sub)
    _add_adapter_quality_commands(sub)
    _add_benchmark_commands(sub)
    _add_quality_evidence_commands(sub)
    _add_web_qa_commands(sub)
    _add_worktree_commands(sub)
    _add_runtime_commands(sub)
    _add_goal_commands(sub)
    _add_state_commands(sub)
    _add_theme_commands(sub)
    _add_update_check_commands(sub)
    return parser


def _print_welcome() -> None:
    print(
        """OMH - oh-my-hermes

Install OMH, then talk to Hermes. The `omh` command is the setup, doctor,
update, verifier, and wrapper/backend surface; the normal user experience is
Hermes Agent chat with installed OMH skills.

If this screen appears after `omh uninstall`, the command package is still on
PATH. `uninstall` removes OMH-managed Hermes files and removes the command only
when it can prove the command came from the installer-managed OMH venv.

Start:
  omh setup              Install skills and connect them to Hermes
  omh doctor             Check local OMH health and registration
  omh quickstart         Show what to do next in Hermes
  omh update             Refresh managed skills and update metadata
  omh --version          Print the command version and its build identity

First five minutes:
  1. Run `omh setup` and accept the recommended choices.
  2. Restart or reload Hermes Agent.
  3. Ask Hermes the prompt below.

Useful operator commands:
  omh quickstart         Show first-use prompts and evidence boundaries
  omh recommend "risky refactor"
  omh cases recommend "daily competitor digest"
  omh cases readiness   Check the G1-G10 readiness rollup
  omh cases demo --all  Show wrapper-ready G1-G10 use-case cards
  omh cases artifact --all --write
                          Write local G1-G10 runbook artifacts
  omh cases replay        Replay G1-G10 routing fixtures
  omh context brief "make an image card for this PR"
                          Show compact OMH context and route hint
  omh playbook recommend "turn this issue into a PR"
  omh chat interact "turn this issue into a PR-ready plan"
  omh hud                Show the compact OMH status line
  omh achievements summary
                          Show observed hermes-achievements badges
  omh menubar status     Show the OMH menu bar status summary
  omh mcp manifest       Print the optional stdio MCP bridge manifest
  omh release evidence-bundle --version 1.0.5 --write
                          Write local deterministic release evidence
  omh plugin observe-host --host hermes-agent --session <session-id> --event plugin_load --evidence-ref <host-log>
  omh loop status        Show loopable goal cycle state
  omh ops list           List local operations artifacts
  omh materials list     List material-processing artifacts
  omh img-summary prompt-card Prepare image-generation-ready summary cards
  omh worktree list      List observed worktree isolation records
  omh worktree bind --path .worktrees/risky-refactor --executor codex --session <session-id>
  omh runtime status     Show local evidence artifacts

After setup, restart or reload Hermes Agent and try:
  Use OMH request-to-handoff for: I want to safely add a feature to this repo.

If `omh` is not found in a new terminal, use the absolute command path printed
by the installer or add that directory to PATH. Run `omh doctor` after that to
verify Hermes registration.

Run `omh --help` for the full command list."""
    )


def _run_startup_update_check(args: argparse.Namespace) -> None:
    """Compare the local install against `origin/main` and act per `omh update-check`.

    Opt-in only: `update_check.mode` defaults to `off`, which returns before
    any network attempt. Runs synchronously, right before exec'ing `hermes`,
    because that exec hands the terminal to a separate process -- there is no
    "after the TUI paints" moment left in this process to report a result in,
    so the whole probe has to fit inside its own bounded timeout ahead of the
    handoff rather than racing it. Any failure here is a silent skip; it must
    never block, delay beyond that bound, or crash the launch.

    The except clause is deliberately wider than `OSError` alone: it is the
    same "corrupt on-disk JSON" shape `local_store.read_json_object_result`
    already classifies, kept here only as a backstop in case a future reader
    on this path stops going through it -- `evaluate_update_check`'s own
    readers no longer raise on a corrupt `setup-profile.json`/state/cache
    file, so a user who never opted into this check must never see a launch
    traceback from one.
    """
    from ..maintenance.update_check import evaluate_update_check, format_notice_line

    paths = _paths(args)
    try:
        result = evaluate_update_check(paths)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if result.get("should_auto_update"):
        _run_auto_update(args, paths, result)
        return
    # Only a fresh probe prints a notice. Reusing the cache inside the same
    # interval would otherwise reprint the same "behind"/"inconclusive" line
    # on every launch until the interval elapses -- once per interval is the
    # documented cadence (docs/INSTALLATION.md, "Startup update check").
    if result.get("checked"):
        notice = format_notice_line(result)
        if notice:
            print(notice)


# `omh update` streams pip/npm/brew output and can take minutes on the
# preview channel (`commands/setup.py:_run_command_package_self_update`); this
# bounds that wait instead of letting a hung download block the launch
# forever.
_AUTO_UPDATE_SUBPROCESS_TIMEOUT_SECONDS = 600.0


def _auto_update_started_line(result: dict[str, object]) -> str:
    """What `auto` says before it spends the launch on an update.

    `notify` mode already prints why the launch is not current
    (`maintenance/update_check.py:format_notice_line`); `auto` used to print
    nothing at all and simply hold the terminal for however long `omh
    update` took, which reads as a hung launch rather than as a running
    update. Same sentence shape as the `notify` notice, so the two modes
    read as one voice.
    """
    local = str(result.get("local_commit", ""))[:7] or "unknown"
    remote = str(result.get("remote_commit", ""))[:7] or "unknown"
    channel = str(result.get("channel", "")) or "unknown"
    return f"OMH Auto Update: {local} -> {remote} ({channel} channel); running `omh update`."


def _auto_update_complete_line(paths) -> str:
    """What `auto` says once the update subprocess has succeeded.

    The version comes from the record `omh update` just rewrote
    (`commands/setup.py`), not from this process: this process is still
    running the pre-update package, and its own `__version__` would report
    the version the update just replaced. That record is also what the TUI
    HUD renders (`plugin_bundle/omh/runtime_reader.py:_package_version`), so
    the line names exactly the version the terminal is about to show.
    """
    from ..maintenance.update_check_state import read_runtime_state

    version = str(read_runtime_state(paths).get("version", "") or "").strip()
    if version:
        return f"OMH Auto Update complete: omh {version} is installed."
    return "OMH Auto Update complete."


def _run_auto_update(args: argparse.Namespace, paths, result: dict[str, object]) -> None:
    """Auto mode: reuse `omh update`'s own code path, never a reimplementation.

    Spawns `omh update --no-interactive` as a real subprocess rather than
    calling `cmd_update()` in-process. `cmd_update()` can re-enter itself via
    `commands/setup.py:_reentry_argv_with_command_package_updated()`, which
    reads the real process's `sys.argv[1:]` -- not the synthesized
    `update_argv` below. Calling it in-process left `sys.argv` at whatever
    bare `omh` was launched with (empty), so that re-entry became `python -m
    omh.cli --command-package-updated` with no `update` subcommand, exited 2,
    and the post-update half (managed skills, plugin bundle, widgets,
    registration, `release_source_commit`) never ran. A real subprocess gives
    that re-entry its own correct `sys.argv`.

    Deliberately `--no-interactive` without `--yes`: `--yes` presets the
    branded-TUI identity choice (`commands/setup.py:_preset_tui_identity_choice`)
    and would rewrite a user's own `display.interface`/skin choice on every
    auto-update. `--no-interactive` alone leaves that choice unset --
    `_update_should_interact()` still skips the prompt (this is a
    non-interactive background launch), and `_apply_result()` then takes the
    non-forcing `ensure_tui_interface`/`ensure_omh_skin` path instead of the
    forcing `activate_*` one, so an existing explicit choice is preserved.

    The attempt announces itself on stdout and says so again when it lands
    (`_auto_update_started_line`, `_auto_update_complete_line`), because the
    launch is held for the whole subprocess: an unannounced wait of minutes
    is indistinguishable from a hung launch.

    A non-blocking lock keeps two simultaneous launches from auto-updating at
    once; losing the race is a silent skip, not a retry. A failed update is
    reported once (so the user is not left guessing) and never retried before
    the next `evaluate_update_check` interval -- `_run_startup_update_check`
    only reaches here on a fresh "behind" outcome, so a cached one from
    within the same interval never re-triggers this. On success, the cache is
    re-anchored so a launch later in the same interval reads it as resolved
    instead of still "behind".
    """
    from ..installer import OmhError
    from ..local_store import FileLockTimeout
    from ..maintenance.update_check import acquire_auto_update_lock, refresh_cache_after_auto_update

    try:
        with acquire_auto_update_lock(paths):
            # Announced only after the lock is held: a launch that loses the
            # race skips silently and must not claim an update it never ran.
            print(_auto_update_started_line(result))
            # --omh-home/--hermes-home/--scope are TOP-LEVEL parser options
            # (defined before `add_subparsers`), so they must precede the
            # "update" subcommand token, not follow it.
            update_argv: list[str] = []
            if getattr(args, "omh_home", None):
                update_argv += ["--omh-home", str(args.omh_home)]
            if getattr(args, "hermes_home", None):
                update_argv += ["--hermes-home", str(args.hermes_home)]
            if getattr(args, "scope", None):
                update_argv += ["--scope", str(args.scope)]
            update_argv += ["update", "--no-interactive"]
            # Fail fast on a malformed argv rather than handing it to a
            # subprocess that can only report it as an opaque exit code.
            build_parser().parse_args(update_argv)
            completed = subprocess.run(
                [sys.executable, "-m", "omh.cli", *update_argv],
                timeout=_AUTO_UPDATE_SUBPROCESS_TIMEOUT_SECONDS,
            )
            if completed.returncode == 0:
                refresh_cache_after_auto_update(paths)
                print(_auto_update_complete_line(paths))
            else:
                print(
                    f"omh: update-check auto-update failed (exit {completed.returncode})",
                    file=sys.stderr,
                )
    except FileLockTimeout:
        return
    except (OmhError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"omh: update-check auto-update failed: {exc}", file=sys.stderr)


def _launch_hermes_tui(args: argparse.Namespace) -> int | None:
    """Open the OH-MY-HERMES terminal: bare `omh` is the same door as `hermes`.

    The oh-my-zsh contract, applied here: the wrapper's bare name IS the
    styled experience. This execs the user's own `hermes` binary with no
    flags -- a user-invoked local launch, not background dispatch. It used to
    force `--tui`, which made the two doors open DIFFERENT terminals whenever
    `display.interface` selected the classic REPL: `omh` showed the HUD, bare
    `hermes` showed no OMH surface at all, and the split read as a bug from
    the first boot. Which terminal opens belongs to Hermes' own
    `display.interface`; OMH's door just walks through it. No terminal or no
    Hermes install means there is nothing to launch, and the caller falls
    back to the welcome text.
    """
    import shutil

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    hermes = shutil.which("hermes")
    if not hermes:
        return None
    _run_startup_update_check(args)
    try:
        return int(subprocess.run([hermes]).returncode)
    except (OSError, KeyboardInterrupt):
        return None


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv in (["--version"], ["-V"]):
        # The semantic version still leads the line, so every consumer that
        # reads a version out of this output keeps working. The build identity
        # follows it, because two same-version checkouts are exactly the case
        # the version alone cannot tell apart.
        print(build_identity_summary(probe_build_identity()))
        return 0
    parser = build_parser()
    args = parser.parse_args(raw_argv)
    set_json_output_pretty(bool(getattr(args, "pretty", False)))
    if not getattr(args, "command", None):
        launched = _launch_hermes_tui(args)
        if launched is not None:
            return launched
        _print_welcome()
        return 0
    try:
        return int(args.func(args))
    except OmhError as exc:
        print(f"omh: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
