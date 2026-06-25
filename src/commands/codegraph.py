from __future__ import annotations

import argparse
from pathlib import Path

from ..codegraph import (
    build_codegraph,
    build_handoff_context,
    codegraph_artifact_path,
    render_build_text,
    render_handoff_text,
    render_summary_text,
    summarize_codegraph,
    write_codegraph_artifact,
)
from ..installer import OmhError
from .common import _print_json, _wants_json


def cmd_codegraph_build(args: argparse.Namespace) -> int:
    try:
        graph = build_codegraph(args.repo)
        if args.write:
            artifact_path = codegraph_artifact_path(Path(graph["repo_root"]))
            graph["artifact_path"] = str(artifact_path)
            write_codegraph_artifact(graph)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(graph)
    else:
        print(render_build_text(graph))
    return 0


def cmd_codegraph_summary(args: argparse.Namespace) -> int:
    try:
        graph = build_codegraph(args.repo)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    summary = summarize_codegraph(graph)
    if _wants_json(args):
        _print_json(summary)
    else:
        print(render_summary_text(summary))
    return 0


def cmd_codegraph_handoff(args: argparse.Namespace) -> int:
    try:
        graph = build_codegraph(args.repo)
        context = build_handoff_context(graph, task=args.task)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(context)
    else:
        print(render_handoff_text(context))
    return 0


def _add_codegraph_commands(sub) -> None:
    codegraph = sub.add_parser(
        "codegraph",
        help="Build static local codegraph artifacts for prepared coding context.",
    )
    codegraph_sub = codegraph.add_subparsers(dest="codegraph_command", required=True)

    build = codegraph_sub.add_parser("build", help="Build a static local Python AST codegraph.")
    build.add_argument("--repo", default=".", help="Repository root to scan.")
    build.add_argument("--write", action="store_true", help="Write .omh/codegraph/codegraph.json.")
    build.add_argument("--json", action="store_true", help="Print the full codegraph artifact as JSON.")
    build.set_defaults(func=cmd_codegraph_build)

    summary = codegraph_sub.add_parser("summary", help="Print a compact static codegraph summary.")
    summary.add_argument("--repo", default=".", help="Repository root to scan.")
    summary.add_argument("--json", action="store_true", help="Print the summary payload as JSON.")
    summary.set_defaults(func=cmd_codegraph_summary)

    handoff = codegraph_sub.add_parser("handoff", help="Build compact prepared context for coding agents.")
    handoff.add_argument("--repo", default=".", help="Repository root to scan.")
    handoff.add_argument("--task", required=True, help="Task description used to rank relevant files and symbols.")
    handoff.add_argument("--json", action="store_true", help="Print the handoff context payload as JSON.")
    handoff.set_defaults(func=cmd_codegraph_handoff)
