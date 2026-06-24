from __future__ import annotations

import argparse
import sys

from ..installer import OmhError
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
    cmd_coding_executor_readiness,
    cmd_coding_lifecycle_dispatch,
    cmd_coding_lifecycle_report,
    cmd_coding_lifecycle_result,
    cmd_coding_lifecycle_start,
    cmd_coding_lifecycle_verify,
)
from .context import _add_context_commands, cmd_context_brief
from .demo import _add_demo_commands, cmd_demo_orchestration
from .docs import (
    _add_docs_commands,
    _add_harness_commands,
    cmd_docs_workflows,
    cmd_harness_inspect,
    cmd_harness_list,
    cmd_harness_validate,
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
from .memory import _add_memory_commands, cmd_memory_apply, cmd_memory_inspect, cmd_memory_pack
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
    cmd_snippet,
    cmd_uninstall,
    cmd_update,
)
from .state import _add_state_commands, cmd_state_clear, cmd_state_finish, cmd_state_start, cmd_state_status
from .use_cases import _add_cases_commands, cmd_cases_inspect, cmd_cases_list, cmd_cases_recommend
from .visual import _add_visual_commands, cmd_visual_observe, cmd_visual_prompt_card
from .worktree import cmd_worktree_bind, cmd_worktree_list, cmd_worktree_prepare, _add_worktree_commands


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
            "  omh playbook recommend \"turn this issue into a PR\"\n"
            "  omh chat interact \"turn this issue into a PR-ready plan\"\n"
            "  omh hud\n"
            "  omh menubar status\n"
            "  omh mcp manifest\n"
            "  omh mcp config-recipe --host codex\n"
            "  omh release evidence-bundle --version 1.0.1 --write\n"
            "  omh plugin observe-host --host hermes-agent --session <session-id> --event plugin_load --evidence-ref <host-log>\n"
            "  omh loop status\n"
            "  omh ops list\n"
            "  omh materials list\n"
            "  omh img-summary prompt-card --kind github_pr --visual-format auto --section summary:What_changed:Safer_setup_copy\n"
            "  omh img-summary prompt-card --kind report --aspect-ratio long_scroll --section summary:Executive_summary:Weekly_metrics_changed\n"
            "  omh worktree prepare --repo . --task \"risky refactor\" --dry-run\n"
            "  omh worktree bind --path .worktrees/risky-refactor --executor codex --session <session-id>\n"
            "  omh runtime status\n\n"
            "  omh runtime team-readiness\n\n"
            "Human-facing maintenance, catalog, and operator checklist commands print summaries by default;\n"
            "pass --json or set OMH_OUTPUT=json when a wrapper needs full payloads.\n"
            "Backend/control-plane commands such as chat, coding, runtime, goal, loop,\n"
            "learning, memory, ops, materials, state, harness, release smoke, and demo print JSON by design."
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
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    _add_top_level_commands(sub)
    _add_quickstart_commands(sub)
    _add_docs_commands(sub)
    _add_harness_commands(sub)
    _add_cases_commands(sub)
    _add_playbook_commands(sub)
    _add_release_commands(sub)
    _add_demo_commands(sub)
    _add_chat_commands(sub)
    _add_capabilities_commands(sub)
    _add_context_commands(sub)
    _add_coding_commands(sub)
    _add_hermes_commands(sub)
    _add_hud_commands(sub)
    _add_learning_commands(sub)
    _add_loop_commands(sub)
    _add_memory_commands(sub)
    _add_menubar_commands(sub)
    _add_mcp_commands(sub)
    _add_plugin_commands(sub)
    _add_ops_commands(sub)
    _add_materials_commands(sub)
    _add_visual_commands(sub)
    _add_worktree_commands(sub)
    _add_runtime_commands(sub)
    _add_goal_commands(sub)
    _add_state_commands(sub)
    return parser


def _print_welcome() -> None:
    print(
        """OMH - oh-my-hermes

Install OMH, then talk to Hermes. The `omh` command is the setup, doctor,
update, verifier, and wrapper/backend surface; the normal user experience is
Hermes Agent chat with installed OMH skills.

If this screen appears after `omh uninstall`, the command package is still on
PATH. `uninstall` removes OMH-managed Hermes files and removes the command only
when it can prove the command came from the install.sh-managed OMH venv.

Start:
  omh setup              Install skills and connect them to Hermes
  omh doctor             Check local OMH health and registration
  omh quickstart         Show what to do next in Hermes
  omh update             Refresh managed skills and update metadata

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
  omh menubar status     Show the menu bar app status view model
  omh mcp manifest       Print the optional stdio MCP bridge manifest
  omh release evidence-bundle --version 1.0.1 --write
                          Write local deterministic release evidence
  omh plugin observe-host --host hermes-agent --session <session-id> --event plugin_load --evidence-ref <host-log>
  omh loop status        Show loopable goal cycle state
  omh ops list           List local operations artifacts
  omh materials list     List material-processing artifacts
  omh img-summary prompt-card Prepare image-generation-ready summary cards
  omh worktree prepare --repo . --task "risky refactor" --dry-run
  omh worktree bind --path .worktrees/risky-refactor --executor codex --session <session-id>
  omh runtime status     Show local evidence artifacts

After setup, restart or reload Hermes Agent and try:
  Use OMH request-to-handoff for: I want to safely add a feature to this repo.

If `omh` is not found in a new terminal, use the absolute command path printed
by the installer or add that directory to PATH. Run `omh doctor` after that to
verify Hermes registration.

Run `omh --help` for the full command list."""
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        _print_welcome()
        return 0
    try:
        return int(args.func(args))
    except OmhError as exc:
        print(f"omh: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
