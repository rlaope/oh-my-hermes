from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from ..catalogs.roles import roles_reference_markdown
from ..installer import OmhError
from ..install.manifest import read_manifest
from ..local_store import atomic_write_text
from ..skill_pack import builtin_skill_reference_templates, builtin_skill_templates
from ..skills.catalog import omh_skill_display_name
from ..skills.context_cost import skill_context_cost_markdown, skill_context_cost_payload
from ..skills.render import workflow_reference_markdown, workflow_reference_payload
from ..skills.validation import harness_inspection_payload, harness_summary_payload, validate_catalog_contract
from .common import _paths, _print_json


def cmd_docs_agent_skills(args: argparse.Namespace) -> int:
    from ..install.agent_skills_projection import agent_skill_files
    from ..skills.host_adapter_render import host_adapter_files

    root = Path(args.output or "agent-skills").expanduser().absolute()
    files = agent_skill_files()
    adapters = host_adapter_files(files)
    try:
        if args.check:
            actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() or path.is_symlink()}
            missing = sorted(files.keys() - actual)
            extra = sorted(actual - files.keys())
            stale = sorted(
                relative for relative in files.keys() & actual
                if (root / relative).is_symlink() or (root / relative).read_bytes() != files[relative].encode("utf-8")
            )
            adapter_missing = sorted(path for path in adapters if not (root.parent / path).exists())
            adapter_stale = sorted(
                path for path, content in adapters.items() if path not in adapter_missing
                and ((root.parent / path).is_symlink()
                     or (root.parent / path).parent.is_symlink()
                     or not (root.parent / path).is_file()
                     or (root.parent / path).read_bytes() != content.encode("utf-8"))
            )
            payload = {"ok": not (missing or extra or stale or adapter_missing or adapter_stale),
                       "checked": str(root), "missing": missing, "stale": stale,
                       "extra": extra, "file_count": len(files),
                       "adapter_file_count": len(adapters),
                       "adapter_missing": adapter_missing, "adapter_stale": adapter_stale}
            _print_json(payload)
            return 0 if payload["ok"] else 1
        for relative, content in files.items():
            atomic_write_text(root / relative, content)
        for relative, content in adapters.items():
            path = root.parent / relative
            atomic_write_text(path, content)
            if path.suffix == ".sh":
                path.chmod(0o755)
    except OSError as exc:
        raise OmhError(f"Agent Skills docs projection failed: {exc}") from exc
    _print_json({"written": str(root), "file_count": len(files), "adapter_file_count": len(adapters)})
    return 0


def _installed_workflow_reference_markdown(args: argparse.Namespace) -> str:
    paths = _paths(args)
    manifest = read_manifest(paths.manifest_path)
    if not manifest:
        raise OmhError(f"installed workflow docs require an OMH manifest: {paths.manifest_path}")
    raw_skills = manifest.get("skills", [])
    if not isinstance(raw_skills, list):
        raise OmhError("installed workflow manifest skills must be a list")
    installed_names = {str(item.get("name") or "") for item in raw_skills if isinstance(item, dict) and item.get("name")}
    catalog = workflow_reference_payload()
    skills = [skill for skill in catalog["skills"] if str(skill.get("name") or "") in installed_names]
    harness_names = {str(skill.get("primary_harness") or "") for skill in skills if skill.get("primary_harness")}
    harnesses = [item for item in catalog["harnesses"] if str(item.get("name") or "") in harness_names]
    lines = ["# Installed Workflow Reference", "", "Generated from the local OMH install manifest and canonical workflow catalog.", "",
             f"- Installed manifest skills: `{len(installed_names)}`", f"- Catalog workflows documented: `{len(skills)}`", "",
             "Installed guidance only; this is not runtime execution evidence.", "", "## Installed Workflows", ""]
    for skill in skills:
        triggers = ", ".join(f"`{item}`" for item in skill.get("triggers", []))
        lines.extend([f"### {skill['name']}", "", str(skill.get("description") or ""), "",
                      f"- Category: `{skill.get('category', '')}`", f"- Phase: `{skill.get('phase', '')}`",
                      f"- Hermes role: `{skill.get('hermes_role', '')}`", f"- Primary harness: `{skill.get('primary_harness', '')}`",
                      f"- Preferred usage: {skill.get('preferred_usage', '')}", f"- Handoff policy: {skill.get('handoff_policy', '')}",
                      f"- Why this exists: {skill.get('why_this_exists', '')}", f"- Use when: {skill.get('use_when', '')}",
                      f"- Strong routing signals: {triggers}", ""])
    lines.extend(["## Relevant Harnesses", ""])
    for item in harnesses:
        lines.extend([f"### {item['name']}", "", str(item.get("purpose") or ""), "",
                      f"- Use when: {item.get('use_when', '')}", f"- Quality tier: `{item.get('quality_tier', '')}`",
                      f"- Privacy default: `{item.get('privacy_default', '')}`", ""])
    return "\n".join(lines).rstrip() + "\n"


def cmd_docs_workflows(args: argparse.Namespace) -> int:
    if args.installed:
        if args.json or args.check:
            raise OmhError("docs workflows --installed cannot be combined with --json or --check")
        content = _installed_workflow_reference_markdown(args)
        if args.output:
            output = Path(args.output).expanduser().resolve()
            atomic_write_text(output, content)
            _print_json({"written": str(output), "scope": "installed"})
            return 0
        print(content.rstrip())
        return 0
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


def cmd_docs_roles(args: argparse.Namespace) -> int:
    content = roles_reference_markdown()
    output = Path(args.output).expanduser().resolve() if args.output else Path("docs/ROLES.md").resolve()
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise OmhError(f"role docs check failed: {exc}") from exc
        if current != content:
            raise OmhError(f"role docs are stale: {output}")
        _print_json({"ok": True, "checked": str(output)})
        return 0
    if args.output:
        atomic_write_text(output, content)
        _print_json({"written": str(output)})
        return 0
    print(content.rstrip())
    return 0


def cmd_docs_capability_families(args: argparse.Namespace) -> int:
    from ..capabilities.families import standalone_capability_families_json

    content = standalone_capability_families_json()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else _default_capability_families_path()
    )
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise OmhError(f"capability families sidecar check failed: {exc}") from exc
        if current != content:
            raise OmhError(f"capability families sidecar is stale: {output}")
        _print_json({"ok": True, "checked": str(output)})
        return 0
    atomic_write_text(output, content)
    _print_json({"written": str(output)})
    return 0


def cmd_docs_ulw_inventory(args: argparse.Namespace) -> int:
    from ..skills.catalog import ulw_inventory_payload

    if args.json:
        if args.check:
            raise OmhError("docs ulw-inventory --json cannot be combined with --check")
        _print_json(ulw_inventory_payload())
        return 0
    return _sync_ulw_region(
        path=Path(args.path).expanduser().resolve(),
        check=args.check,
        label="README ULW inventory region",
    )


def cmd_docs_ulw_site(args: argparse.Namespace) -> int:
    return _sync_ulw_region(
        path=Path(args.path).expanduser().resolve(),
        check=args.check,
        label="site ULW region",
        site=True,
    )


def _sync_ulw_region(*, path: Path, check: bool, label: str, site: bool = False) -> int:
    from ..catalogs.ulw_surfaces import readme_with_generated_region, site_with_generated_region

    regenerate = readme_with_generated_region if not site else site_with_generated_region
    try:
        current = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OmhError(f"{label} check failed: {exc}") from exc
    try:
        updated = regenerate(current)
    except ValueError as exc:
        raise OmhError(f"{label} check failed: {exc}") from exc
    if check:
        if current != updated:
            raise OmhError(f"{label} is stale: {path}")
        _print_json({"ok": True, "checked": str(path)})
        return 0
    if updated != current:
        atomic_write_text(path, updated)
    _print_json({"written": str(path)})
    return 0


def cmd_docs_chain_table(args: argparse.Namespace) -> int:
    """Write or check the generated shipped-chain table region.

    The failure path names the rows that disagree, not just the file: the byte
    comparison knows the region is stale, and `model_chain_table_drift` knows
    which chain moved, so the message carries both.
    """
    from ..catalogs.model_chain_table import (
        installation_with_generated_region,
        model_chain_table_drift,
    )

    path = Path(args.path).expanduser().resolve()
    label = "shipped chain table region"
    try:
        current = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OmhError(f"{label} check failed: {exc}") from exc
    try:
        updated = installation_with_generated_region(current)
        findings = model_chain_table_drift(current)
    except ValueError as exc:
        raise OmhError(f"{label} check failed: {exc}") from exc
    if args.check:
        if current != updated:
            raise OmhError(
                f"{label} is stale: {path}: {'; '.join(findings)}. "
                "Regenerate with: uv run python -m omh.cli docs chain-table"
            )
        _print_json({"ok": True, "checked": str(path)})
        return 0
    if updated != current:
        atomic_write_text(path, updated)
    _print_json({"written": str(path), "rewritten": updated != current})
    return 0


def cmd_docs_skill_trigger_report(args: argparse.Namespace) -> int:
    from ..skills.trigger_review import skill_trigger_review_payload

    if args.format != "json":
        raise OmhError(f"unsupported skill-trigger-report format: {args.format}")
    _print_json(skill_trigger_review_payload())
    return 0


def cmd_docs_skill_context_cost(args: argparse.Namespace) -> int:
    if args.json:
        _print_json(skill_context_cost_payload())
        return 0
    print(skill_context_cost_markdown().rstrip())
    return 0


def cmd_docs_skill_lint(args: argparse.Namespace) -> int:
    """Return one structural pass/fail verdict for every tracked skill.

    Exit codes are the contract: 0 pass, 1 violations, 2 invocation or internal
    error. The unsupported-format branch raises `OmhError` so it exits 2 through
    the same path every other invocation error uses.

    An unexpected failure inside the lint is the third case, and it is caught
    here rather than left to escape. Escaping is not neutral: the interpreter
    would exit 1, which already means "this tree has structural violations", so
    a crash would be indistinguishable from a real verdict to any caller reading
    the exit code. The handler is deliberately at this one command boundary and
    nowhere deeper, so the rest of the repository keeps its existing behavior.
    """
    from ..quality.skill_governance import skill_structure_lint_report

    if args.format != "json":
        raise OmhError(f"unsupported skill-lint format: {args.format}")
    try:
        report = skill_structure_lint_report()
    except Exception as exc:
        _print_internal_error(exc)
        return 2
    _print_json(report)
    return 0 if report["ok"] else 1


def _print_internal_error(exc: BaseException) -> None:
    """Report a lint crash on the error channel as a classified result.

    The exception *type* is surfaced because it is what makes the failure
    triageable and is not attacker-influenced. The message is not: it is
    arbitrary text that may carry a path, a token, or any other value the
    failing code happened to be holding, and this command's whole contract is
    deterministic machine-readable output.

    Written to stderr so stdout carries only real reports; a caller parsing
    stdout therefore never has to tell a verdict apart from a crash.
    """
    from ..skills.validation import SKILL_STRUCTURE_LINT_SCHEMA_VERSION

    payload = {
        "schema_version": SKILL_STRUCTURE_LINT_SCHEMA_VERSION,
        "ok": False,
        "status": "internal_error",
        "error_type": type(exc).__name__,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=sys.stderr)


def cmd_docs_skill_shortlist(args: argparse.Namespace) -> int:
    from ..routing.skill_shortlist_sidecar import standalone_skill_shortlist_json

    content = standalone_skill_shortlist_json()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else _default_plugin_tools_path("skill_shortlist.json")
    )
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError as exc:
            raise OmhError(f"skill shortlist sidecar check failed: {exc}") from exc
        if current != content:
            raise OmhError(f"skill shortlist sidecar is stale: {output}")
        _print_json({"ok": True, "checked": str(output)})
        return 0
    atomic_write_text(output, content)
    _print_json({"written": str(output)})
    return 0


def _default_capability_families_path() -> Path:
    return _default_plugin_tools_path("capability_families.json")


def _default_plugin_tools_path(name: str) -> Path:
    from ..plugin_bundle.omh import tools as plugin_tools

    return (Path(plugin_tools.__file__).resolve().parent / name).resolve()


class TapSkillsCheckPayload(TypedDict):
    ok: bool
    root: str
    expected: int
    checked: int
    missing: list[str]
    stale: list[str]
    extra: list[str]


def _tap_skills_check_payload(skills_root: Path) -> TapSkillsCheckPayload:
    templates = {omh_skill_display_name(template.name): template for template in builtin_skill_templates()}
    reference_templates = {
        Path(omh_skill_display_name(template.skill_name)) / template.relative_path: template
        for template in builtin_skill_reference_templates()
    }
    paths = {path.parent.name: path for path in skills_root.glob("*/SKILL.md")}
    reference_paths = {path.relative_to(skills_root): path for path in skills_root.glob("*/references/*.md")}
    missing = sorted(name for name in templates if name not in paths)
    missing.extend(path.as_posix() for path in sorted(reference_templates) if path not in reference_paths)
    extra = sorted(name for name in paths if name not in templates)
    extra.extend(path.as_posix() for path in sorted(reference_paths) if path not in reference_templates)
    stale: list[str] = []
    for name, path in sorted(paths.items()):
        if name in templates and path.read_text(encoding="utf-8") != templates[name].content:
            stale.append(name)
    for rel_path, path in sorted(reference_paths.items()):
        template = reference_templates.get(rel_path)
        if template and path.read_text(encoding="utf-8") != template.content:
            stale.append(rel_path.as_posix())
    return {
        "ok": not missing and not stale and not extra,
        "root": str(skills_root.resolve()),
        "expected": len(templates) + len(reference_templates),
        "checked": len(paths) + len(reference_paths),
        "missing": missing,
        "stale": stale,
        "extra": extra,
    }


# Public interface for maintenance consumers; retain the original private export.
tap_skills_check_payload = _tap_skills_check_payload


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


def cmd_docs_claims(args: argparse.Namespace) -> int:
    from ..maintenance.documentation_claims import documentation_claims_report, format_documentation_claims

    try:
        payload = documentation_claims_report(
            root=Path(args.root), claim_ids=tuple(args.claim) if args.claim else None,
            enable_model=args.enable_model, model_run_cap=args.model_run_cap, timeout=args.timeout,
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.json:
        _print_json(payload)
    else:
        print(format_documentation_claims(payload))
    return 1 if args.check and not payload["ok"] else 0


def cmd_docs_navigation(args: argparse.Namespace) -> int:
    from ..maintenance.documentation_navigation import (
        documentation_navigation_report,
        format_documentation_navigation,
    )

    payload = documentation_navigation_report(root=Path(args.root))
    if args.json:
        _print_json(payload)
    else:
        print(format_documentation_navigation(payload))
    return 1 if args.check and not payload["ok"] else 0


def cmd_docs_skill_sources(args: argparse.Namespace) -> int:
    from ..maintenance.skill_source_closure import (
        format_skill_source_closure,
        skill_source_closure_report,
    )

    payload = skill_source_closure_report(root=Path(args.root))
    if args.json:
        _print_json(payload)
    else:
        print(format_skill_source_closure(payload))
    return 1 if args.check and not payload["ok"] else 0


def _add_docs_commands(sub) -> None:
    docs = sub.add_parser("docs", help="Render or check generated OMH workflow reference docs.")
    docs_sub = docs.add_subparsers(dest="docs_command", required=True)

    claims = docs_sub.add_parser("claims", help="Audit reviewed public claims against bounded local implementation probes (maintainers).")
    claims.add_argument("--check", action="store_true", help="Exit 1 for selected deterministic stale or unresolved claims; model judgments are advisory.")
    claims.add_argument("--json", action="store_true")
    claims.add_argument("--claim", action="append", help="Select a reviewed claim ID; repeat for multiple claims. Default: enrolled deterministic set.")
    claims.add_argument("--root", default=".", help="Trusted source tree containing enrolled pages and implementation anchors.")
    claims.add_argument("--timeout", type=float, default=10, help="Per-check deadline in seconds (maximum 30).")
    claims.add_argument("--enable-model", action="store_true", help="Explicit advisory opt-in, requires --claim. Core CLI has no provider adapter: reports not_run.")
    claims.add_argument("--model-run-cap", type=int, default=1, help="Advisory run cap (0-3); never a release gate.")
    claims.set_defaults(func=cmd_docs_claims)

    navigation = docs_sub.add_parser(
        "navigation",
        help=(
            "Check public documentation structure offline: reachability from declared roots, "
            "local link targets, navigation-root uniqueness, public-path collisions, and "
            "classification of every intentionally non-public page (maintainers)."
        ),
    )
    navigation.add_argument("--check", action="store_true", help="Exit 1 when any structural finding is reported; anchor advisories never block.")
    navigation.add_argument("--json", action="store_true", help="Print the machine-readable documentation_navigation_audit/v1 payload.")
    navigation.add_argument("--root", default=".", help="Repository tree to audit.")
    navigation.set_defaults(func=cmd_docs_navigation)

    skill_sources = docs_sub.add_parser(
        "skill-sources",
        help=(
            "Check recurring-watch closure continuity offline: every docs/SKILL-SOURCES.md row is "
            "closed by a terminal receipt chain, held at a named failure, or not applicable at its "
            "pre-receipt baseline. Never contacts a watched repository (maintainers)."
        ),
    )
    skill_sources.add_argument("--check", action="store_true", help="Exit 1 when any closure finding is reported.")
    skill_sources.add_argument("--json", action="store_true", help="Print the machine-readable skill_source_closure_audit/v1 payload.")
    skill_sources.add_argument("--root", default=".", help="Repository tree holding the registry and the receipt ledger.")
    skill_sources.set_defaults(func=cmd_docs_skill_sources)

    docs_agents = docs_sub.add_parser("agent-skills", help="Generate or byte-check the portable Agent Skills tree (maintainers).")
    docs_agents.add_argument("--output", default=None, help="Projection root (default: agent-skills).")
    docs_agents.add_argument("--check", action="store_true")
    docs_agents.set_defaults(func=cmd_docs_agent_skills)

    docs_workflows = docs_sub.add_parser("workflows")
    docs_workflows.add_argument("--output", default=None)
    docs_workflows.add_argument("--installed", action="store_true", help="Render workflows recorded in the local OMH install manifest.")
    docs_workflows.add_argument("--check", action="store_true")
    docs_workflows.add_argument("--json", action="store_true", help="Print machine-readable workflow and harness catalog metadata.")
    docs_workflows.set_defaults(func=cmd_docs_workflows)

    docs_roles = docs_sub.add_parser("roles")
    docs_roles.add_argument("--output", default=None)
    docs_roles.add_argument("--check", action="store_true")
    docs_roles.set_defaults(func=cmd_docs_roles)

    docs_capability_families = docs_sub.add_parser(
        "capability-families",
        help="Write or check the generated plugin-bundle capability-family sidecar JSON.",
    )
    docs_capability_families.add_argument("--output", default=None)
    docs_capability_families.add_argument("--check", action="store_true")
    docs_capability_families.set_defaults(func=cmd_docs_capability_families)

    docs_skill_shortlist = docs_sub.add_parser(
        "skill-shortlist",
        help="Write or check the generated plugin-bundle lexical skill shortlist index JSON.",
    )
    docs_skill_shortlist.add_argument("--output", default=None)
    docs_skill_shortlist.add_argument("--check", action="store_true")
    docs_skill_shortlist.set_defaults(func=cmd_docs_skill_shortlist)

    docs_ulw_inventory = docs_sub.add_parser(
        "ulw-inventory",
        help="Write or check the generated ULW table region of the English README, or print the inventory payload.",
    )
    docs_ulw_inventory.add_argument("--path", default="README.md")
    docs_ulw_inventory.add_argument("--check", action="store_true")
    docs_ulw_inventory.add_argument(
        "--json",
        action="store_true",
        help="Print the machine-readable omh_ulw_inventory/v1 payload.",
    )
    docs_ulw_inventory.set_defaults(func=cmd_docs_ulw_inventory)

    docs_ulw_site = docs_sub.add_parser(
        "ulw-site",
        help="Write or check the generated ULW region of site/index.html.",
    )
    docs_ulw_site.add_argument("--path", default="site/index.html")
    docs_ulw_site.add_argument("--check", action="store_true")
    docs_ulw_site.set_defaults(func=cmd_docs_ulw_site)

    docs_chain_table = docs_sub.add_parser(
        "chain-table",
        help="Write or check the generated shipped model-chain table region of docs/INSTALLATION.md.",
    )
    docs_chain_table.add_argument("--path", default="docs/INSTALLATION.md")
    docs_chain_table.add_argument("--check", action="store_true")
    docs_chain_table.set_defaults(func=cmd_docs_chain_table)

    docs_skill_context_cost = docs_sub.add_parser(
        "skill-context-cost",
        help="Report skill-body size (loaded per skill view) and cross-skill repetition for the core and full profiles.",
    )
    docs_skill_context_cost.add_argument(
        "--json",
        action="store_true",
        help="Print the machine-readable omh_skill_context_cost/v1 payload.",
    )
    docs_skill_context_cost.set_defaults(func=cmd_docs_skill_context_cost)

    docs_skill_lint = docs_sub.add_parser(
        "skill-lint",
        help=(
            "Check every tracked skill for structure only: parsed frontmatter, machine-consumed "
            "fields, resolvable harness, generated parity, trigger format, executable consumers, "
            "and the context budget. Offline and pass/fail; never scores, ranks, or reviews wording."
        ),
    )
    docs_skill_lint.add_argument(
        "--format",
        default="json",
        choices=("json",),
        help="Output format for the omh_skill_structure_lint/v1 report.",
    )
    docs_skill_lint.set_defaults(func=cmd_docs_skill_lint)

    docs_skill_trigger_report = docs_sub.add_parser(
        "skill-trigger-report",
        help=(
            "Report which defined triggers reached picker frontmatter, why the rest did not, "
            "and which normalized trigger identities are shared across skills."
        ),
    )
    docs_skill_trigger_report.add_argument(
        "--format",
        default="json",
        choices=("json",),
        help="Output format for the skill_trigger_review/v1 payload.",
    )
    docs_skill_trigger_report.set_defaults(func=cmd_docs_skill_trigger_report)


def _add_harness_commands(sub) -> None:
    from .mcp_tool_name_compatibility import add_harness_mcp_tool_name_compatibility_command

    harness = sub.add_parser("harness", help="List, inspect, and validate workflow harness contracts.")
    harness_sub = harness.add_subparsers(dest="harness_command", required=True)

    harness_list = harness_sub.add_parser("list")
    harness_list.set_defaults(func=cmd_harness_list)

    harness_inspect = harness_sub.add_parser("inspect")
    harness_inspect.add_argument("name")
    harness_inspect.set_defaults(func=cmd_harness_inspect)

    harness_validate = harness_sub.add_parser("validate")
    harness_validate.set_defaults(func=cmd_harness_validate)
    add_harness_mcp_tool_name_compatibility_command(harness_sub)
