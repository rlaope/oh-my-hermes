"""One-shot report of everything a catalog change knocks out of sync.

Adding a single skill invalidates counts, budgets, and generated artifacts at
once, but the test suite reveals them a few at a time: you fix what the run
showed, rerun the whole suite, and learn about the next one. An observed
session spent twelve full-suite cycles that way -- four of them chasing the
same byte budget down 305 -> 303 -> 299 -> 264, and one hunting a limit that
lived in `src/maintenance/release.py` rather than in a test.

This module recomputes every drift-prone value from source and reports the
whole set in one pass, with the sites that hardcode each one.

The expected values here do not replace the assertions in `tests/` -- those are
deliberate contracts (see `CLAUDE.md`). This is the index that says which ones
a change just invalidated. `tests/test_drift_registry.py` keeps the index
honest by checking that every declared site still contains the value it claims.

No source parsing: every live value comes from calling the real producer, and
every site is declared data. Sites are file paths, never line numbers, because
line numbers drift.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NotRequired, TypedDict


DRIFT_REPORT_SCHEMA_VERSION = "omh_drift_report/v1"


class DriftFindingBase(TypedDict):
    name: str
    describe: str
    sites: list[str]
    fix: str


class CountDriftFinding(DriftFindingBase):
    kind: Literal["count"]
    expected: int
    live: int


class BudgetDriftFinding(DriftFindingBase):
    kind: Literal["budget"]
    limit: int
    live: int
    over_by: int
    reviewed_exception: NotRequired[int]
    exception_reason: NotRequired[str]


class GeneratedDriftFinding(DriftFindingBase):
    kind: Literal["generated"]
    state: Literal["missing", "stale", "unreadable"]
    error: NotRequired[str]


class TapSkillsDriftFinding(GeneratedDriftFinding):
    missing: list[str]
    stale: list[str]
    extra: list[str]


DriftFinding = CountDriftFinding | BudgetDriftFinding | GeneratedDriftFinding


class DriftReport(TypedDict):
    schema_version: str
    ok: bool
    checked_count: int
    drift_count: int
    checked: list[str]
    drift: list[DriftFinding]
    next_action: str
    claim_boundary: str


@dataclass(frozen=True)
class CountMetric:
    """A value that must match exactly across every site that hardcodes it."""

    name: str
    describe: str
    live: Callable[[], int]
    expected: int
    sites: tuple[str, ...]


@dataclass(frozen=True)
class BudgetMetric:
    """A rendered size that must stay under a declared ceiling.

    `reviewed_exception` is an explicit, named allowance above the limit for
    growth a PR body has recorded and reviewers have accepted (plan §1.2 for
    the ULW fold). It is never a silent limit bump: the limit keeps its
    captured baseline value, the exception names the accepted overage, and
    both live at `limit_site`.
    """

    name: str
    describe: str
    live: Callable[[], int]
    limit: int
    limit_site: str
    reviewed_exception: int = 0
    exception_reason: str = ""


@dataclass(frozen=True)
class GeneratedArtifact:
    """A committed file that must byte-match what the catalog renders today."""

    name: str
    path: str
    render: Callable[[], str]
    regenerate: str


def _chat_card_case_count() -> int:
    from ..quality.chat_card_coverage import build_chat_card_coverage_demo

    return int(build_chat_card_coverage_demo()["summary"]["case_count"])


def _route_hint_case_count() -> int:
    from ..quality.route_hint_alignment import build_route_hint_alignment_demo

    return int(build_route_hint_alignment_demo()["summary"]["case_count"])


def _routing_precision_case_count() -> int:
    from ..quality.routing_precision import build_routing_precision_demo

    return int(build_routing_precision_demo()["summary"]["case_count"])


def _routing_precision_intervention_case_count() -> int:
    from ..quality.routing_precision import build_routing_precision_demo

    count = build_routing_precision_demo()["summary"]["intervention_case_count"]
    return count if not isinstance(count, bool) else 0


def _installable_skill_count() -> int:
    from ..skills.catalog import installable_skill_names

    return len(installable_skill_names())


def _common_request_case_count() -> int:
    from ..quality.common_request_coverage import build_common_request_coverage_demo

    return int(build_common_request_coverage_demo()["summary"]["case_count"])


def _ulw_canonical_engine_count() -> int:
    from ..skills.catalog import ulw_inventory_payload

    return len(ulw_inventory_payload()["canonical_engines"])


def _ulw_alias_engine_count() -> int:
    from ..skills.catalog import ulw_inventory_payload

    return len(ulw_inventory_payload()["alias_engines"])


def _ulw_retired_engine_count() -> int:
    from ..skills.catalog import ulw_inventory_payload

    return len(ulw_inventory_payload()["retired_engines"])


def _awareness_primer_markdown_chars() -> int:
    from ..plugin_bundle.omh.awareness import awareness_primer_markdown

    return len(awareness_primer_markdown())


def _full_capability_section_chars() -> int:
    from ..capabilities.skills import skill_capabilities

    return len(json.dumps(skill_capabilities(), sort_keys=True, ensure_ascii=False))


def _standalone_capability_section_chars() -> int:
    from ..plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items

    return len(json.dumps(standalone_skill_capability_items(), sort_keys=True, ensure_ascii=False))


def _full_profile_skill_body_chars() -> int:
    from ..skills.context_cost import skill_context_cost_payload

    for profile in skill_context_cost_payload()["profiles"]:
        if profile["profile"] == "full":
            return int(profile["skill_body"]["bytes"])
    raise KeyError("full profile missing from skill_context_cost_payload()")


def count_metrics() -> tuple[CountMetric, ...]:
    return (
        CountMetric(
            name="chat_card_case_count",
            describe="Chat card coverage cases",
            live=_chat_card_case_count,
            expected=91,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
            ),
        ),
        CountMetric(
            name="route_hint_case_count",
            describe="Route hint alignment cases",
            live=_route_hint_case_count,
            expected=211,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
            ),
        ),
        CountMetric(
            name="routing_precision_case_count",
            describe="Routing precision cases",
            live=_routing_precision_case_count,
            # The public-board contract adds three negative controls: a concept
            # question, a disclosure question, and a team's own board. The
            # scroll-motion lane adds three negatives for the frontend scroll
            # triggers: two parallax (astronomy, camera optics) and the
            # terminal-emulator scroll bug that pins the `scroll` hold-back.
            # The realtime voice lane adds four negatives that mention voice or
            # a receipt without asking about connector adoption: a translation
            # input, a definition question, a voice-memo file lookup, and a
            # billing receipt.
            # Protected-reference controls remain alongside the upstream corpus;
            # merged totals are re-derived from build_routing_precision_demo().
            # The long-document lane adds negatives that use its own words
            # in another sense (eleven): writing documentation, reading a repo file,
            # processing a refund, reading the room, writing a long document
            # (en/ko/ja/zh), translating a whole document, and a site walked
            # page by page, and a page number beside a port number.
            # The router-misroute round adds seven negatives that use a repaired
            # lane's own words in another sense: a browser window resized, disk
            # space running out, a heap leak beside a list of providers, a
            # Korean question about surveillance-camera video, and one per bare
            # verb held back from the continuous-watch phrases (keeping an old
            # API, buying a monitor, watching out for a race condition).
            # The application-threat-model lane adds six negatives that use its
            # own words in another sense: what threat modeling is, what a STRIDE
            # analysis is, a trust boundary asked as a domain-modeling term,
            # hitting one's stride, modeling churn, and a scale model.
            # The live-incident-response lane adds seven of the same shape:
            # three concept questions about the discipline (what an incident
            # commander does at a wildfire, what an incident response plan is,
            # what a war room is), a military rank, severity as a bug-tracker
            # field, a manufacturing line down for maintenance, and a
            # figurative outage.
            expected=235,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
                "tests/test_routing_precision.py",
            ),
        ),
        CountMetric(
            name="routing_precision_intervention_case_count",
            describe="Routing precision intervention cases",
            live=_routing_precision_intervention_case_count,
            # The public-board contract adds two LLM-build interventions and the
            # agent-board cross-lane guard. The scroll-motion lane adds three
            # more: smooth scroll, a parallax hero, and the Korean phrasing.
            # The realtime voice lane adds four: adoption, a supplied trial
            # receipt, turn integrity with barge-in, and the Korean phrasing.
            # Direct and mixed-reference interventions remain alongside the
            # upstream corpus; the merged producer determines the exact total.
            # The long-document lane adds twenty: six reading requests across
            # English, Korean, Japanese, and Chinese, plus thirteen requests that
            # share its words and stay with their owners (slides, Word action
            # items, a paper by level, contract compliance review in two
            # languages, a large-PDF upload failure in four, a viewer crash, an
            # OCR pipeline, a section added to a long style guide, and a spec
            # page dated by a year).
            # The router-misroute round adds eight: a filling context window and
            # running out of context reaching budget review, a continuous watch
            # reaching the recurring-ops lane in Korean and in English (two
            # phrase families), a memory-provider comparison reaching its
            # declared owner, and the sense each of those displaced staying
            # where it was (terminology alignment, operations telemetry).
            # The application-threat-model lane adds five: four requests that
            # model a real application (a payment service, an attacker path
            # between two components, attack scenarios on an endpoint, abuse
            # cases on a flow) and one that keeps the agent's own prompt and
            # tool surface with `security-safety-review`.
            # The live-incident-response lane adds eight: five requests that
            # command an incident still open (an outage declared now, the
            # commander and severity question, a timeline to start, a temporary
            # mitigation with recovery unverified, a severity level and a
            # bridge) and three that keep the siblings it defers to -- a closed
            # incident with `reliability-review`, one customer's outage reply
            # with `support-operations`, and a healthy release watch with
            # `deploy-and-monitor`.
            # The CJK tier lane adds four: a ja and a zh pack phrase inside a
            # sentence, each pinned at clarify/medium with its skill still
            # named, and a zh phrase pinned bare at dispatch/high beside the
            # same phrase inside a question at clarify/medium. They record the
            # tokenisation tier gap as intended so a scoring change has to
            # move them deliberately (#1607).
            expected=392,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
                "tests/test_routing_precision.py",
            ),
        ),
        CountMetric(
            name="installable_skill_count",
            describe="Installable workflow skills quoted in reference surfaces",
            live=_installable_skill_count,
            # The current workflow additions are part of the installable catalog.
            expected=126,
            sites=(
                "docs/README.md",
                # The docs index quotes the count in prose and
                # `test_first_release_trust_surfaces_are_present` asserts that
                # exact string, so the number lives in two files, not one.
                "tests/test_router_content.py",
            ),
        ),
        CountMetric(
            name="common_request_case_count",
            describe="Common request coverage cases",
            live=_common_request_case_count,
            expected=92,
            sites=(
                "tests/test_cli.py",
                "tests/test_hermes_ux_quality.py",
                "tests/test_release_smoke.py",
                "tests/test_common_request_coverage.py",
            ),
        ),
        CountMetric(
            name="ulw_canonical_engine_count",
            describe="ULW engines in the canonical lifecycle stage",
            live=_ulw_canonical_engine_count,
            expected=9,
            sites=(
                "README.ko.md",
                "README.ja.md",
                "tests/test_ulw_inventory.py",
            ),
        ),
        CountMetric(
            name="ulw_alias_engine_count",
            describe="ULW engines in the alias or warning lifecycle stage",
            live=_ulw_alias_engine_count,
            expected=0,
            sites=(
                "tests/test_ulw_inventory.py",
            ),
        ),
        CountMetric(
            name="ulw_retired_engine_count",
            describe="ULW engines in the retired lifecycle stage",
            live=_ulw_retired_engine_count,
            expected=4,
            sites=(
                "tests/test_ulw_inventory.py",
            ),
        ),
    )


def _skill_density_filler_hits() -> int:
    from ..quality.skill_density import catalog_filler_hit_total

    return catalog_filler_hit_total()


def budget_metrics() -> tuple[BudgetMetric, ...]:
    from ..quality.skill_density import DENSITY_FILLER_HIT_CEILING
    from .release import (
        AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
        FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS,
        STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
    )

    return (
        BudgetMetric(
            name="awareness_primer_markdown_chars",
            describe="Awareness primer markdown size",
            live=_awareness_primer_markdown_chars,
            limit=AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
        ),
        BudgetMetric(
            name="full_capability_skill_section_chars",
            describe="Full capability skill section size",
            live=_full_capability_section_chars,
            limit=FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
        ),
        BudgetMetric(
            name="standalone_capability_skill_section_chars",
            describe="Standalone capability skill section size",
            live=_standalone_capability_section_chars,
            limit=STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
        ),
        BudgetMetric(
            name="full_profile_skill_body_chars",
            describe="Full install profile skill_body size (producer chars)",
            live=_full_profile_skill_body_chars,
            limit=FULL_PROFILE_SKILL_BODY_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            reviewed_exception=FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS,
        ),
        # The byte budget above says how much the pack costs; this says whether
        # the characters carry instruction. A hit is a reviewed filler phrase
        # that an install pays for in every context window without changing
        # what a reader does, so the ceiling is zero on a corpus measured at
        # zero. The other two density signals are floats and stay in
        # `tests/test_skill_density.py`.
        BudgetMetric(
            name="skill_density_filler_hits",
            describe="Reviewed filler phrases across all catalog skill bodies",
            live=_skill_density_filler_hits,
            limit=DENSITY_FILLER_HIT_CEILING,
            limit_site="src/quality/skill_density.py",
        ),
    )


def generated_artifacts() -> tuple[GeneratedArtifact, ...]:
    from ..capabilities.families import standalone_capability_families_json
    from ..catalogs.roles import roles_reference_markdown
    from ..skills.render import workflow_reference_markdown

    return (
        GeneratedArtifact(
            name="workflows_doc",
            path="docs/WORKFLOWS.md",
            render=workflow_reference_markdown,
            regenerate="uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md",
        ),
        GeneratedArtifact(
            name="roles_doc",
            path="docs/ROLES.md",
            render=roles_reference_markdown,
            regenerate="uv run python -m omh.cli docs roles --output docs/ROLES.md",
        ),
        GeneratedArtifact(
            name="capability_families_sidecar",
            path="src/plugin_bundle/omh/tools/capability_families.json",
            render=standalone_capability_families_json,
            regenerate="uv run python -m omh.cli docs capability-families",
        ),
    )


def _count_drift(metric: CountMetric) -> CountDriftFinding | None:
    live = metric.live()
    if live == metric.expected:
        return None
    return {
        "name": metric.name,
        "kind": "count",
        "describe": metric.describe,
        "expected": metric.expected,
        "live": live,
        "sites": list(metric.sites),
        "fix": (
            f"replace {metric.expected} with {live} in src/maintenance/drift.py "
            f"and in every site listed above"
        ),
    }


def _budget_drift(metric: BudgetMetric) -> BudgetDriftFinding | None:
    live = metric.live()
    ceiling = metric.limit + metric.reviewed_exception
    if live <= ceiling:
        return None
    finding: BudgetDriftFinding = {
        "name": metric.name,
        "kind": "budget",
        "describe": metric.describe,
        "limit": metric.limit,
        "live": live,
        "over_by": live - ceiling,
        "sites": [metric.limit_site],
        "fix": (
            f"shorten the rendered content by {live - ceiling} chars, or raise the limit "
            f"in {metric.limit_site} if the growth is genuinely warranted"
        ),
    }
    if metric.reviewed_exception:
        finding["reviewed_exception"] = metric.reviewed_exception
        finding["exception_reason"] = metric.exception_reason
    return finding


def _tap_skills_drift(repo_root: Path) -> TapSkillsDriftFinding | None:
    """Generated `skills/*/SKILL.md` and `skills/*/references/*.md`.

    These do not fit the one-file-per-artifact shape above -- there are dozens,
    and a catalog change can make some stale while adding or removing others.
    Reusing the same check `docs workflows --check` runs keeps one definition of
    stale.
    """
    from ..commands.docs import tap_skills_check_payload

    payload = tap_skills_check_payload(repo_root / "skills")
    if payload["ok"]:
        return None
    affected = list(payload["missing"]) + list(payload["stale"]) + list(payload["extra"])
    return {
        "name": "tap_skills",
        "kind": "generated",
        "describe": f"{len(affected)} generated skill file(s) out of sync",
        "state": "stale",
        "missing": payload["missing"],
        "stale": payload["stale"],
        "extra": payload["extra"],
        "sites": [f"skills/{item}" for item in affected],
        "fix": (
            "write each template's .content back under skills/ "
            "(builtin_skill_templates() and builtin_skill_reference_templates())"
        ),
    }


def _generated_drift(artifact: GeneratedArtifact, repo_root: Path) -> GeneratedDriftFinding | None:
    target = repo_root / artifact.path
    expected = artifact.render()
    try:
        current = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        state = "missing"
    except OSError as exc:
        return {
            "name": artifact.name,
            "kind": "generated",
            "describe": f"{artifact.path} could not be read",
            "state": "unreadable",
            "error": str(exc),
            "sites": [artifact.path],
            "fix": artifact.regenerate,
        }
    else:
        if current == expected:
            return None
        state = "stale"
    return {
        "name": artifact.name,
        "kind": "generated",
        "describe": f"{artifact.path} is {state}",
        "state": state,
        "sites": [artifact.path],
        "fix": artifact.regenerate,
    }


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def drift_report(
    *,
    repo_root: Path | None = None,
    counts: tuple[CountMetric, ...] | None = None,
    budgets: tuple[BudgetMetric, ...] | None = None,
    artifacts: tuple[GeneratedArtifact, ...] | None = None,
    include_tap_skills: bool = True,
) -> DriftReport:
    """Check every metric and report all findings; never stop at the first.

    Stopping early is the behaviour this command exists to replace.
    """
    root = repo_root or repo_root_default()
    counts = count_metrics() if counts is None else counts
    budgets = budget_metrics() if budgets is None else budgets
    artifacts = generated_artifacts() if artifacts is None else artifacts

    drift: list[DriftFinding] = []
    checked: list[str] = []
    for metric in counts:
        checked.append(metric.name)
        found: DriftFinding | None = _count_drift(metric)
        if found:
            drift.append(found)
    for metric in budgets:
        checked.append(metric.name)
        found = _budget_drift(metric)
        if found:
            drift.append(found)
    for artifact in artifacts:
        checked.append(artifact.name)
        found = _generated_drift(artifact, root)
        if found:
            drift.append(found)
    if include_tap_skills:
        checked.append("tap_skills")
        found = _tap_skills_drift(root)
        if found:
            drift.append(found)

    return {
        "schema_version": DRIFT_REPORT_SCHEMA_VERSION,
        "ok": not drift,
        "checked_count": len(checked),
        "drift_count": len(drift),
        "checked": checked,
        "drift": drift,
        "next_action": (
            "apply every listed fix in one pass, then rerun this command"
            if drift
            else "no drift; run the full suite as the final proof"
        ),
        "claim_boundary": (
            "Drift detection is a preflight over recomputed catalog values. It is not test, "
            "review, CI, or merge evidence."
        ),
    }


def format_drift_report(payload: DriftReport) -> str:
    drift = payload.get("drift") or []
    lines: list[str] = []
    if not drift:
        lines.append(f"No drift. {payload.get('checked_count', 0)} checks passed.")
        return "\n".join(lines)
    lines.append(f"DRIFT ({len(drift)} of {payload.get('checked_count', 0)} checks)")
    lines.append("")
    for item in drift:
        if item["kind"] == "count":
            headline = f"  {item['name']}: {item['expected']} -> {item['live']}"
        elif item["kind"] == "budget":
            headline = f"  {item['name']}: {item['live']} (over budget {item['limit']} by {item['over_by']})"
        else:
            headline = f"  {item['name']}: {item.get('state', 'stale')}"
        lines.append(headline)
        for site in item.get("sites", []):
            lines.append(f"      site: {site}")
        lines.append(f"      fix:  {item.get('fix', '')}")
        lines.append("")
    lines.append(str(payload.get("next_action", "")))
    return "\n".join(lines)
