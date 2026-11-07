"""Which module registers each `omh` subcommand, so one command imports only its own module.

`omh.commands.main` imports every command module up front to build the full
parser, which costs most of a second before the command runs. When argv opens
with a subcommand named here, `main` builds a parser with the same top-level
options and only that subcommand's registrar, and runs it. Everything else
(help, version, an unknown or abbreviated word, an option before the
subcommand) goes through the full parser exactly as before.

A registrar may register more than one subcommand (`setup` registers `doctor`,
`update`, ...); the fast parser holds them all. The table is checked against
`build_parser()` by `tests/test_cli_fast_dispatch.py`: every subcommand the full
parser has is here, and each entry builds the same subparser.
"""

from __future__ import annotations

import argparse
import sys

# subcommand -> (module under omh.commands, registrar function)
SUBCOMMAND_REGISTRARS: dict[str, tuple[str, str]] = {
    "achievements": ("achievements", "_add_achievements_commands"),
    "adapter-quality": ("adapter_quality", "_add_adapter_quality_commands"),
    "apply": ("setup", "_add_top_level_commands"),
    "benchmark": ("cross_harness_benchmark", "_add_benchmark_commands"),
    "capabilities": ("capabilities", "_add_capabilities_commands"),
    "capability-policy": ("setup", "_add_top_level_commands"),
    "cases": ("use_cases", "_add_cases_commands"),
    "chat": ("chat", "_add_chat_commands"),
    "codegraph": ("codegraph", "_add_codegraph_commands"),
    "coding": ("coding", "_add_coding_commands"),
    "conformance": ("conformance", "_add_conformance_commands"),
    "context": ("context", "_add_context_commands"),
    "convert": ("setup", "_add_top_level_commands"),
    "demo": ("demo", "_add_demo_commands"),
    "design": ("design", "_add_design_commands"),
    "docs": ("docs", "_add_docs_commands"),
    "doctor": ("setup", "_add_top_level_commands"),
    "ecosystem": ("ecosystem", "_add_ecosystem_commands"),
    "goal": ("goal", "_add_goal_commands"),
    "handoff-risk-scan": ("handoff_risk_scan", "add_handoff_risk_scan_command"),
    "harness": ("docs", "_add_harness_commands"),
    "hermes": ("hermes", "_add_hermes_commands"),
    "hud": ("hud", "_add_hud_commands"),
    "img-summary": ("visual", "_add_visual_commands"),
    "install": ("setup", "_add_top_level_commands"),
    "learning": ("learning", "_add_learning_commands"),
    "list": ("setup", "_add_top_level_commands"),
    "loop": ("loop", "_add_loop_commands"),
    "materials": ("materials", "_add_materials_commands"),
    "mcp": ("mcp", "_add_mcp_commands"),
    "memory": ("memory", "_add_memory_commands"),
    "menubar": ("menubar", "_add_menubar_commands"),
    "model": ("model_chains", "_add_model_chains_commands"),
    "model-chains": ("model_chains", "_add_model_chains_commands"),
    "ops": ("ops", "_add_ops_commands"),
    "paper": ("paper", "_add_paper_commands"),
    "playbook": ("playbook", "_add_playbook_commands"),
    "plugin": ("plugin", "_add_plugin_commands"),
    "probe": ("setup", "_add_top_level_commands"),
    "profile": ("setup", "_add_top_level_commands"),
    "quality-evidence": ("quality_evidence", "_add_quality_evidence_commands"),
    "quickstart": ("quickstart", "_add_quickstart_commands"),
    "recommend": ("setup", "_add_top_level_commands"),
    "release": ("release", "_add_release_commands"),
    "research": ("research", "_add_research_commands"),
    "runtime": ("runtime", "_add_runtime_commands"),
    "setup": ("setup", "_add_top_level_commands"),
    "setup-profile": ("setup", "_add_top_level_commands"),
    "skill-profile": ("setup", "_add_top_level_commands"),
    "snippet": ("setup", "_add_top_level_commands"),
    "state": ("state", "_add_state_commands"),
    "theme": ("theme", "_add_theme_commands"),
    "uninstall": ("setup", "_add_top_level_commands"),
    "update": ("setup", "_add_top_level_commands"),
    "update-check": ("update_check", "_add_update_check_commands"),
    "visual": ("visual", "_add_visual_commands"),
    "web-qa": ("web_qa", "_add_web_qa_commands"),
    "worktree": ("worktree", "_add_worktree_commands"),
}


def registrar_for(argv: list[str]):
    """The registrar for argv's subcommand when argv opens with one named here, else None."""
    if not argv:
        return None
    entry = SUBCOMMAND_REGISTRARS.get(argv[0])
    if entry is None:
        return None
    module, function = entry
    return getattr(_command_module(module), function)


def _command_module(module: str):
    """The command module `module` names, through a plain import statement per module.

    Spelled out rather than resolved by name, so every module this file can load is a literal
    import the static safety gates in `tests/test_handoff_safety_contract_enforcement.py` see.
    """
    if module == "achievements":
        from . import achievements as loaded
        return loaded
    if module == "adapter_quality":
        from . import adapter_quality as loaded
        return loaded
    if module == "capabilities":
        from . import capabilities as loaded
        return loaded
    if module == "chat":
        from . import chat as loaded
        return loaded
    if module == "codegraph":
        from . import codegraph as loaded
        return loaded
    if module == "coding":
        from . import coding as loaded
        return loaded
    if module == "conformance":
        from . import conformance as loaded
        return loaded
    if module == "context":
        from . import context as loaded
        return loaded
    if module == "cross_harness_benchmark":
        from . import cross_harness_benchmark as loaded
        return loaded
    if module == "demo":
        from . import demo as loaded
        return loaded
    if module == "design":
        from . import design as loaded
        return loaded
    if module == "docs":
        from . import docs as loaded
        return loaded
    if module == "ecosystem":
        from . import ecosystem as loaded
        return loaded
    if module == "goal":
        from . import goal as loaded
        return loaded
    if module == "handoff_risk_scan":
        from . import handoff_risk_scan as loaded
        return loaded
    if module == "hermes":
        from . import hermes as loaded
        return loaded
    if module == "hud":
        from . import hud as loaded
        return loaded
    if module == "learning":
        from . import learning as loaded
        return loaded
    if module == "loop":
        from . import loop as loaded
        return loaded
    if module == "materials":
        from . import materials as loaded
        return loaded
    if module == "mcp":
        from . import mcp as loaded
        return loaded
    if module == "memory":
        from . import memory as loaded
        return loaded
    if module == "menubar":
        from . import menubar as loaded
        return loaded
    if module == "model_chains":
        from . import model_chains as loaded
        return loaded
    if module == "ops":
        from . import ops as loaded
        return loaded
    if module == "paper":
        from . import paper as loaded
        return loaded
    if module == "playbook":
        from . import playbook as loaded
        return loaded
    if module == "plugin":
        from . import plugin as loaded
        return loaded
    if module == "quality_evidence":
        from . import quality_evidence as loaded
        return loaded
    if module == "quickstart":
        from . import quickstart as loaded
        return loaded
    if module == "release":
        from . import release as loaded
        return loaded
    if module == "research":
        from . import research as loaded
        return loaded
    if module == "runtime":
        from . import runtime as loaded
        return loaded
    if module == "setup":
        from . import setup as loaded
        return loaded
    if module == "state":
        from . import state as loaded
        return loaded
    if module == "theme":
        from . import theme as loaded
        return loaded
    if module == "update_check":
        from . import update_check as loaded
        return loaded
    if module == "use_cases":
        from . import use_cases as loaded
        return loaded
    if module == "visual":
        from . import visual as loaded
        return loaded
    if module == "web_qa":
        from . import web_qa as loaded
        return loaded
    if module == "worktree":
        from . import worktree as loaded
        return loaded
    raise LookupError(f"no command module {module!r}")


def build_fast_parser(registrar) -> argparse.ArgumentParser:
    """The full parser's top level (prog, options, `<command>` slot) holding only `registrar`'s subcommands.

    The description and epilog are left out: they print only for `omh --help`, which never takes this path.
    """
    from .bare_launch import add_top_level_options

    parser = argparse.ArgumentParser(prog="omh", formatter_class=argparse.RawDescriptionHelpFormatter)
    add_top_level_options(parser)
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    registrar(sub)
    return parser


def run_command(args: argparse.Namespace, raw_argv: list[str]) -> int:
    """Run a parsed subcommand: the tail `omh.commands.main.main` and the fast path share."""
    from ..core.errors import OmhError
    from .bare_launch import _TUI_PASSTHROUGH_OPTIONS
    from .common import set_json_output_pretty

    # The command line as typed, for a refusal that must name the same
    # command back (`omh setup --interactive` without a terminal).
    args._argv = raw_argv
    set_json_output_pretty(bool(getattr(args, "pretty", False)))
    try:
        # Refuse a bare-launch flag given alongside a subcommand. Unlike
        # `--omh-home`/`--hermes-home`/`--scope`, these three do not apply to a
        # subcommand at all: they are forwarded to `hermes` when the bare launch
        # opens the terminal, and there is no terminal here. Ignoring one
        # silently would run the subcommand against a profile or session the
        # person believes they selected.
        for dest, flag in _TUI_PASSTHROUGH_OPTIONS:
            if getattr(args, dest, None) is not None:
                raise OmhError(
                    f"{flag} opens the OH-MY-HERMES terminal and cannot be combined "
                    f"with the '{args.command}' command."
                )
        return int(args.func(args))
    except OmhError as exc:
        print(f"omh: {exc}", file=sys.stderr)
        return 2


def fast_main(raw_argv: list[str]) -> int | None:
    """Run argv through its own subcommand's parser; None when argv does not open with a known subcommand."""
    registrar = registrar_for(raw_argv)
    if registrar is None:
        return None
    args = build_fast_parser(registrar).parse_args(raw_argv)
    return run_command(args, raw_argv)
