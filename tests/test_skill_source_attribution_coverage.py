"""Every upstream credit in a shipped skill is watched or explained (issue #2049).

`docs/SKILL-SOURCES.md` is what the upstream tracker reads. A skill body or
reference that credits an outside harness, with no registry row for that pair,
leaves the source unwatched: upstream can change the material OMH adapted and
nothing raises an issue. That is how superpowers, ECC, and oh-my-openagent
credits sat in shipped skills with zero rows.

The subject is derived from the producers rather than listed by hand. Each
(skill, upstream) pair whose generated text carries an attribution marker must
either have a registry row or appear in `INSPIRATION_ONLY` with the reason it
needs none, so a new credit cannot land silently in either direction.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.maintenance.skill_source_closure import parse_registry
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "docs" / "SKILL-SOURCES.md"

# Upstream source (as `normalize_source` writes it) -> the marker that credits
# it in generated skill text. Bare "omo" is not a marker: it also names the
# omo runtime OMH hands work to, which is interop, not a borrowing.
UPSTREAM_MARKERS = {
    "github.com/obra/superpowers": re.compile(r"\bsuperpowers\b", re.IGNORECASE),
    "github.com/affaan-m/everything-claude-code": re.compile(
        r"\bECC\b|everything-claude-code|affaan-m"
    ),
    "github.com/code-yeongyu/oh-my-openagent": re.compile(r"oh-my-openagent|code-yeongyu"),
}

_ECC_POSTURE = (
    "credits ECC for a posture only; compared section by section against ECC at "
    "ef648e01899ba3e8dc6371642deaaf64b4477775, the skill shares no section structure, "
    "rule list, or ECC-specific term with {ecc}"
)

# (skill, upstream source) -> why the credit needs no registry row.
INSPIRATION_ONLY = {
    ("accessibility-audit", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`agents/a11y-architect.md` or `skills/accessibility/SKILL.md`"),
    ("build-failure-triage", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`commands/build-fix.md`, `agents/build-error-resolver.md`, or `agents/pr-test-analyzer.md`"),
    ("workspace-audit", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`skills/workspace-surface-audit/SKILL.md`"),
    ("verification-gate", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`skills/verification-loop/SKILL.md`"),
    ("rules-distill", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`skills/rules-distill/SKILL.md`"),
    ("codebase-onboarding", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`skills/codebase-onboarding/SKILL.md` or `skills/code-tour/SKILL.md`"),
    ("codegraph-refresh", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`commands/update-codemaps.md`"),
    ("context-budget-review", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`skills/context-budget/SKILL.md` or `skills/token-budget-advisor/SKILL.md`"),
    ("security-safety-review", "github.com/affaan-m/everything-claude-code"): _ECC_POSTURE.format(
        ecc="`skills/security-scan/SKILL.md`, `skills/security-review/SKILL.md`, or `skills/safety-guard/SKILL.md`"),
}


def credited_pairs() -> set[tuple[str, str]]:
    """Every (skill, upstream source) pair whose generated text carries a marker."""
    texts = [(template.name, template.content) for template in builtin_skill_templates()]
    texts += [(template.skill_name, template.content) for template in builtin_skill_reference_templates()]
    return {
        (skill, source)
        for skill, content in texts
        for source, marker in UPSTREAM_MARKERS.items()
        if marker.search(content)
    }


def registry_pairs() -> set[tuple[str, str]]:
    rows, _findings = parse_registry(REGISTRY.read_text(encoding="utf-8"))
    return {(row["unit"], row["source"]) for row in rows}


class SkillSourceAttributionCoverageTest(unittest.TestCase):
    def test_every_upstream_marker_is_detected_in_shipped_skill_text(self) -> None:
        # A marker that matches nothing would make the coverage assertion pass
        # vacuously, so each upstream must be found at least once.
        found = {source for _skill, source in credited_pairs()}
        self.assertEqual(found, set(UPSTREAM_MARKERS))

    def test_every_credited_pair_has_a_registry_row_or_a_listed_reason(self) -> None:
        uncovered = sorted(credited_pairs() - registry_pairs() - set(INSPIRATION_ONLY))
        self.assertEqual(
            uncovered, [],
            "These skills credit an upstream with no row in docs/SKILL-SOURCES.md. Add a row and "
            "a null-prior receipt, or list the pair in INSPIRATION_ONLY with the reason it needs none.",
        )

    def test_inspiration_only_entries_name_a_live_credit_and_no_row(self) -> None:
        credited = credited_pairs()
        rows = registry_pairs()
        for pair, reason in INSPIRATION_ONLY.items():
            with self.subTest(pair=pair):
                self.assertIn(pair, credited, "stale entry: the skill no longer carries this credit")
                self.assertNotIn(pair, rows, "the pair has a row, so the entry is redundant")
                self.assertTrue(reason.strip())


if __name__ == "__main__":
    unittest.main()
