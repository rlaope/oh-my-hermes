"""`omh skill-eval`: offline host-fit check of one skill folder or a folder of skills.

Reads files only: no model call, no network, no key. The verdicts come from
`omh.skills.harness_fit`, whose host facts name their source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..skills.harness_fit import check_catalog, check_skill

_MARK = {"loads": "✅", "degraded": "⚠️", "not_loaded": "❌"}


class SkillEvalArguments(argparse.Namespace):
    """The argument shape this command's parser guarantees."""
    path: str = ""
    host: str | None = None
    context_tokens: int = 0
    install_root: str | None = None
    catalog: bool = False
    json: str | None = None
    strict: bool = False


def _is_catalog(path: Path, forced: bool) -> bool:
    if forced:
        return True
    if (path / "SKILL.md").is_file():
        return False
    return any((child / "SKILL.md").is_file() for child in path.iterdir() if child.is_dir())


def _host_lines(result: dict[str, object], indent: str = "") -> list[str]:
    lines = []
    for row in result["hosts"]:
        findings = row["findings"]
        first = f" — {findings[0]['id']}: {findings[0]['message']}" if findings else ""
        more = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
        lines.append(f"{indent}{_MARK[row['status']]} {row['host']} {row['status']}{first}{more}")
    return lines


def _catalog_line(catalog: dict[str, object]) -> str:
    return f"catalog: {catalog['size']} skills, {catalog['desc_chars']:,} description chars in {catalog['folder']}"


def _overlap_lines(overlap: list[dict[str, object]]) -> list[str]:
    return [f"overlap: \"{group['opening']}\" opens {', '.join(group['skills'])}" for group in overlap]


def _static_lines(static: list[dict[str, str]], indent: str = "") -> list[str]:
    return [f"{indent}static {item['effect']}: {item['id']} — {item['message']}" for item in static]


def _root_lines(rows: list[dict[str, object]]) -> list[str]:
    if rows and all(row["root"] == "not_checked" for row in rows):
        return ["roots: not checked; pass --install-root to say where this folder is installed"]
    return []


def _print_skill(result: dict[str, object]) -> None:
    print(f"OMH skill-eval: {result['target']}")
    for line in (*_host_lines(result), _catalog_line(result["catalog"]), *_root_lines(result["hosts"]),
                 *_overlap_lines(result["overlap"]), *_static_lines(result["static"])):
        print(line)
    summary = result["summary"]
    print(f"{len(result['hosts'])} hosts: {summary['not_loaded']} not_loaded, {summary['degraded']} degraded")


def _print_catalog(result: dict[str, object]) -> None:
    print(f"OMH skill-eval: {result['target']} (catalog)")
    print(_catalog_line(result["catalog"]))
    for line in _root_lines([row for skill in result["skills"] for row in skill["hosts"]]):
        print(line)
    for skill in result["skills"]:
        flagged = [row for row in skill["hosts"] if row["status"] != "loads"]
        if not flagged and not skill["static"]:
            continue
        print(Path(str(skill["target"])).name)
        for line in (*_host_lines({"hosts": flagged}, "  "), *_static_lines(skill["static"], "  ")):
            print(line)
    for line in _overlap_lines(result["overlap"]):
        print(line)
    summary = result["summary"]
    counts = ", ".join(f"{key} {value}" for key, value in summary["findings"].items()) or "none"
    print(f"{summary['skills']} skills: {summary['not_loaded']} not_loaded and {summary['degraded']} degraded "
          f"host rows; findings: {counts}")


def cmd_skill_eval(args: SkillEvalArguments) -> int:
    path = Path(args.path).expanduser()
    if not path.is_dir():
        print(f"omh skill-eval: {path} is not a folder")
        return 2
    hosts = [name.strip() for name in args.host.split(",") if name.strip()] if args.host else None
    as_catalog = _is_catalog(path, args.catalog)
    check = check_catalog if as_catalog else check_skill
    try:
        result = check(path, hosts=hosts, context_tokens=args.context_tokens, install_root=args.install_root)
    except ValueError as error:
        print(f"omh skill-eval: {error}")
        return 2
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (_print_catalog if as_catalog else _print_skill)(result)
    summary = result["summary"]
    return int(args.strict and bool(summary["not_loaded"] or summary["degraded"]))


def _add_skill_eval_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sub.add_parser(
        "skill-eval",
        help="Offline check of whether a skill folder loads in Hermes, Claude Code, Codex and other hosts.",
        description=(
            "Read a skill folder (or a folder of skills) and report, per host, whether it loads, loads degraded, "
            "or is not loaded, with the finding behind each verdict. No model call, no network."
        ),
    )
    _ = parser.add_argument("path", help="A skill folder with SKILL.md, or a folder of skill folders.")
    _ = parser.add_argument("--host", metavar="H1,H2", help="Comma-separated hosts to check (default: all).")
    _ = parser.add_argument("--context-tokens", type=int, default=0, metavar="N",
                            help="The model's context window in tokens; 0 uses each host's unknown-context budget.")
    _ = parser.add_argument("--install-root", metavar="ROOT",
                            help="Where the folder is installed (.agents/skills, .claude/skills, ~/.hermes/skills); "
                                 "inferred from a dotted path, else roots read not_checked.")
    _ = parser.add_argument("--catalog", action="store_true",
                            help="Check every skill folder directly under PATH (automatic when PATH has no SKILL.md).")
    _ = parser.add_argument("--json", metavar="FILE", help="Also write the omh_skill_eval/v1 payload to FILE.")
    _ = parser.add_argument("--strict", action="store_true", help="Exit 1 when any host row is not_loaded or degraded.")
    parser.set_defaults(func=cmd_skill_eval)
