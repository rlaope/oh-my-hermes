from __future__ import annotations

import argparse
from pathlib import Path

from ..installer import OmhError
from ..local_store import atomic_write_text
from ..skill_pack import builtin_harnesses, builtin_skill_templates
from ..skills.render import workflow_reference_markdown, workflow_reference_payload
from ..skills.validation import harness_inspection_payload, harness_summary_payload, validate_catalog_contract
from .common import _print_json


def cmd_docs_workflows(args: argparse.Namespace) -> int:
    if args.json:
        if args.check:
            raise OmhError("docs workflows --json cannot be combined with --check")
        if args.output:
            raise OmhError("docs workflows --json cannot be combined with --output")
        _print_json(workflow_reference_payload())
        return 0
    content = workflow_reference_markdown()
    output = Path(args.output).expanduser().resolve() if args.output else Path("docs/WORKFLOWS.md").resolve()
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise OmhError(f"workflow docs check failed: {exc}") from exc
        if current != content:
            raise OmhError(f"workflow docs are stale: {output}")
        tap_skills = _tap_skills_check_payload(Path("skills"))
        if not tap_skills["ok"]:
            stale = ", ".join(tap_skills["missing"] + tap_skills["stale"] + tap_skills["extra"])
            raise OmhError(f"tap skills are stale: {stale}")
        _print_json({"ok": True, "checked": str(output), "tap_skills": tap_skills})
        return 0
    if args.output:
        atomic_write_text(output, content)
        _print_json({"written": str(output)})
        return 0
    print(content.rstrip())
    return 0


def _tap_skills_check_payload(skills_root: Path) -> dict[str, object]:
    templates = {template.name: template for template in builtin_skill_templates()}
    paths = {path.parent.name: path for path in skills_root.glob("*/SKILL.md")}
    missing = sorted(name for name in templates if name not in paths)
    extra = sorted(name for name in paths if name not in templates)
    stale: list[str] = []
    for name, path in sorted(paths.items()):
        if name in templates and path.read_text(encoding="utf-8") != templates[name].content:
            stale.append(name)
    return {
        "ok": not missing and not stale and not extra,
        "root": str(skills_root.resolve()),
        "expected": len(templates),
        "checked": len(paths),
        "missing": missing,
        "stale": stale,
        "extra": extra,
    }


def cmd_harness_list(args: argparse.Namespace) -> int:
    _print_json(harness_summary_payload())
    return 0


def cmd_harness_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(harness_inspection_payload(args.name))
    except KeyError as exc:
        raise OmhError(f"unknown harness: {args.name}") from exc
    return 0


def cmd_harness_validate(args: argparse.Namespace) -> int:
    result = validate_catalog_contract()
    _print_json(result)
    return 0 if result["ok"] else 1


def _add_docs_commands(sub) -> None:
    docs = sub.add_parser("docs")
    docs_sub = docs.add_subparsers(dest="docs_command", required=True)

    docs_workflows = docs_sub.add_parser("workflows")
    docs_workflows.add_argument("--output", default=None)
    docs_workflows.add_argument("--check", action="store_true")
    docs_workflows.add_argument("--json", action="store_true", help="Print machine-readable workflow and harness catalog metadata.")
    docs_workflows.set_defaults(func=cmd_docs_workflows)


def _add_harness_commands(sub) -> None:
    harness = sub.add_parser("harness")
    harness_sub = harness.add_subparsers(dest="harness_command", required=True)

    harness_list = harness_sub.add_parser("list")
    harness_list.set_defaults(func=cmd_harness_list)

    harness_inspect = harness_sub.add_parser("inspect")
    harness_inspect.add_argument("name")
    harness_inspect.set_defaults(func=cmd_harness_inspect)

    harness_validate = harness_sub.add_parser("validate")
    harness_validate.set_defaults(func=cmd_harness_validate)
