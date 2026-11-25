#!/usr/bin/env python3
"""Offline unified-diff merge-danger scanner for omh-commit-pr-authoring.

Zero third-party dependencies, read-only, counts-only for secret detections.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys

SCHEMA_VERSION = "merge_danger_scan/v1"

_MIGRATION_PATH_RE = re.compile(
    r"(?:^|/)(?:migrations?|alembic|prisma|db/migrate)/|\.(?:sql|prisma)$|schema\.json$",
    re.IGNORECASE,
)
_LOCKFILE_PATH_RE = re.compile(
    r"(?:^|/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|uv\.lock|poetry\.lock|Cargo\.lock|Gemfile\.lock|go\.sum|pyproject\.toml|package\.json)$"
)
_CI_SECURITY_PATH_RE = re.compile(
    r"(?:^|/)(?:\.github/workflows/|CODEOWNERS$|Dockerfile(?:\.[^/]+)?$|docker-compose[^/]*\.ya?ml$)|\.tf$"
)
_PUBLIC_DEF_REMOVED_RE = re.compile(
    r"^\s*(?:def [A-Za-z][A-Za-z0-9_]*\(|class [A-Za-z][A-Za-z0-9_]*|export (?:async )?(?:function|class|const|type|interface) |pub (?:async )?(?:fn|struct|enum|trait) )"
)
_SECRET_ADDED_RE = re.compile(
    r"(?:\bsk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_-]{16,}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bAIza[0-9A-Za-z_-]{30,}\b"
    r"|\bxox[baprs]-[0-9A-Za-z-]{10,}\b"
    r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----)"
)


@dataclass
class FileDiffStats:
    path: str
    additions: int = 0
    deletions: int = 0
    removed_public_defs: int = 0
    added_secret_hits: int = 0
    hunks: int = 0
    categories: list[str] = field(default_factory=list)


def parse_unified_diff(diff_text: str) -> list[FileDiffStats]:
    files: list[FileDiffStats] = []
    current: FileDiffStats | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            path = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else parts[-1]
            current = FileDiffStats(path=path)
            files.append(current)
            continue
        if line.startswith("+++ ") and current is None:
            raw_path = line[4:].strip()
            path = raw_path[2:] if raw_path.startswith("b/") else raw_path
            current = FileDiffStats(path=path)
            files.append(current)
            continue
        if current is None:
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("@@ "):
            current.hunks += 1
            continue
        if line.startswith("+"):
            current.additions += 1
            if _SECRET_ADDED_RE.search(line[1:]):
                current.added_secret_hits += 1
        elif line.startswith("-"):
            current.deletions += 1
            if _PUBLIC_DEF_REMOVED_RE.match(line[1:]):
                current.removed_public_defs += 1
    return files


def scan_diff(diff_text: str, *, source: str = "diff") -> dict[str, object]:
    stats = parse_unified_diff(diff_text)
    findings: list[dict[str, object]] = []
    callouts: list[str] = []

    for item in stats:
        if _MIGRATION_PATH_RE.search(item.path):
            findings.append(
                {
                    "category": "schema_or_migration",
                    "severity": "high",
                    "path": item.path,
                    "detail": "Schema or migration file changed; document rollback and compatibility plan in PR body.",
                }
            )
        if _LOCKFILE_PATH_RE.search(item.path):
            findings.append(
                {
                    "category": "dependency_or_lockfile",
                    "severity": "moderate",
                    "path": item.path,
                    "detail": "Dependency or lockfile changed; verify packaging/dependency policy before merge.",
                }
            )
        if _CI_SECURITY_PATH_RE.search(item.path):
            findings.append(
                {
                    "category": "ci_or_security_surface",
                    "severity": "high",
                    "path": item.path,
                    "detail": "CI, container, ownership, or IaC file changed; call out operational blast radius.",
                }
            )
        if item.removed_public_defs > 0:
            findings.append(
                {
                    "category": "public_symbol_removed",
                    "severity": "moderate",
                    "path": item.path,
                    "count": item.removed_public_defs,
                    "detail": f"{item.removed_public_defs} public symbol definition line(s) removed; verify breaking-change notes.",
                }
            )
        total_lines = item.additions + item.deletions
        if item.deletions >= 40 and total_lines > 0 and (item.deletions / total_lines) >= 0.70:
            findings.append(
                {
                    "category": "high_deletion_ratio",
                    "severity": "moderate",
                    "path": item.path,
                    "additions": item.additions,
                    "deletions": item.deletions,
                    "detail": f"Heavy deletion ({item.deletions} removed vs {item.additions} added); verify intentional removal.",
                }
            )
        if item.added_secret_hits > 0:
            findings.append(
                {
                    "category": "possible_secret_added",
                    "severity": "critical",
                    "path": item.path,
                    "count": item.added_secret_hits,
                    "detail": "Added line(s) matched a vendor secret prefix or private key header (values suppressed).",
                }
            )

    severities = {str(f["severity"]) for f in findings}
    if "critical" in severities:
        risk_level = "critical"
    elif "high" in severities:
        risk_level = "high"
    elif "moderate" in severities:
        risk_level = "moderate"
    else:
        risk_level = "low"

    categories_seen = sorted({str(f["category"]) for f in findings})
    if "possible_secret_added" in categories_seen:
        callouts.append("BLOCK: remove any credential/private key material before committing or pushing.")
    if "schema_or_migration" in categories_seen:
        callouts.append("Document forward/backward migration compatibility and rollback steps in PR Risk/Rollout.")
    if "dependency_or_lockfile" in categories_seen:
        callouts.append("Confirm dependency additions/updates match project packaging policy.")
    if "public_symbol_removed" in categories_seen:
        callouts.append("Confirm removed public symbols have migration notes or internal-only callers.")
    if "ci_or_security_surface" in categories_seen:
        callouts.append("Call out CI/workflow or infrastructure permission/rollout impact explicitly.")

    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "risk_level": risk_level,
        "files_changed": len(stats),
        "total_additions": sum(item.additions for item in stats),
        "total_deletions": sum(item.deletions for item in stats),
        "paths": [item.path for item in stats],
        "findings": findings,
        "suggested_pr_callouts": callouts,
        "claim_boundary": (
            "Static unified-diff hazard scan only. Never commits, pushes, or proves CI/review readiness; "
            "stage only explicit paths rather than `git add -A`."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline read-only merge-danger scanner for omh-commit-pr-authoring."
    )
    parser.add_argument(
        "--diff-file",
        required=True,
        help="Path to a unified diff file, or '-' to read unified diff text from stdin (e.g. `git diff ... | ...`).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)
    try:
        if args.diff_file == "-":
            diff_text = sys.stdin.read()
            source = "stdin"
        else:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
            source = Path(args.diff_file).name
        payload = scan_diff(diff_text, source=source)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(
            json.dumps({"schema_version": SCHEMA_VERSION, "ok": False, "error": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"merge_danger_scan/v1 risk={payload['risk_level']} "
            f"files={payload['files_changed']} +{payload['total_additions']}/-{payload['total_deletions']}"
        )
        for finding in payload["findings"]:
            print(f"  - [{finding['severity']}] {finding['category']} ({finding['path']}): {finding['detail']}")
    return 1 if payload["risk_level"] == "critical" else 0


if __name__ == "__main__":
    raise SystemExit(main())
