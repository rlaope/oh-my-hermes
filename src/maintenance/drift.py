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

It is also the budget ledger: every per-turn and footprint budget is measured,
held with its limit and kind (`ratchet` or `ceiling`), and judged here, and
`skill_content_smoke` reads its budget verdicts from `drift_report()` rather
than comparing on its own.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

if TYPE_CHECKING:
    from ..skills.context_cost import SkillContextCostProfile


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

    `kind` is the policy that sets the limit. A `ratchet` is raised to exactly
    what the producer measured, with the reason recorded beside the constant.
    A `ceiling` carries standing headroom; when it records `measured` and
    `step`, the limit is `derive_ceiling(measured, percent, step)`.
    """

    name: str
    describe: str
    live: Callable[[], int]
    limit: int
    limit_site: str
    reviewed_exception: int = 0
    exception_reason: str = ""
    kind: Literal["ratchet", "ceiling"] = "ratchet"
    measured: int | None = None
    step: int | None = None


@dataclass(frozen=True)
class Limit:
    """A budget's limit as `limits()` reports it.

    `measured` is the producer reading the limit was derived from: the limit
    itself for a ratchet, the recorded measurement for a ceiling the headroom
    rule produced, and None for a ceiling set by hand -- its comment history
    may still record a reading, but no rule turned that reading into the value.
    """

    kind: Literal["ratchet", "ceiling"]
    value: int
    measured: int | None
    step: int | None


def derive_ceiling(measured: int, percent: int, step: int) -> int:
    """The headroom rule (P5 of the 2026-09-23 skill-budget study).

    The measurement plus `percent`, rounded UP to the next multiple of `step`
    (policy and reasons in src/maintenance/release.py).
    """
    with_headroom = -(-measured * (100 + percent) // 100)
    return -(-with_headroom // step) * step


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
    from ..plugin_bundle.omh.turn_budget import render

    return len(render("primer_markdown"))


def _awareness_primer_context_chars() -> int:
    from ..plugin_bundle.omh.turn_budget import render

    return len(render("primer"))


def _awareness_workflow_context_chars_max() -> int:
    from ..plugin_bundle.omh.awareness import awareness_workflow_context_markdown
    from ..skill_pack import builtin_skill_templates
    from .release import DEFAULT_HERMES_SKILL

    names = {template.name for template in builtin_skill_templates()} - {DEFAULT_HERMES_SKILL}
    return max((len(awareness_workflow_context_markdown(name)) for name in names), default=0)


def _role_context_chars_max() -> int:
    from ..catalogs.roles import role_definitions, role_file_markdown

    return max((len(role_file_markdown(role)) for role in role_definitions()), default=0)


def _full_capability_section_chars() -> int:
    from ..capabilities.skills import skill_capabilities

    return len(json.dumps(skill_capabilities(), sort_keys=True, ensure_ascii=False))


def _full_capability_item_chars_max() -> int:
    from ..capabilities.skills import skill_capabilities

    return max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in skill_capabilities()),
        default=0,
    )


def _standalone_capability_section_chars() -> int:
    from ..plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items

    return len(json.dumps(standalone_skill_capability_items(), sort_keys=True, ensure_ascii=False))


def _standalone_capability_item_chars_max() -> int:
    from ..plugin_bundle.omh.tools.capability_tool import standalone_skill_capability_items

    return max(
        (len(json.dumps(item, sort_keys=True, ensure_ascii=False)) for item in standalone_skill_capability_items()),
        default=0,
    )


def _skill_index_chars() -> int:
    from ..skills.skill_index import skill_index_chars

    return skill_index_chars()


def _skill_index_line_max_chars() -> int:
    from ..skills.skill_index import skill_index_line_max_chars

    return skill_index_line_max_chars()


def _plugin_tool_schema_chars() -> int:
    from .per_turn_context import plugin_tool_schema_chars

    return plugin_tool_schema_chars()


def _pre_llm_call_context_chars_max() -> int:
    from .per_turn_context import pre_llm_call_context_chars_max

    return pre_llm_call_context_chars_max()


def _pre_llm_call_context_fallback_chars_max() -> int:
    from .per_turn_context import pre_llm_call_context_fallback_chars_max

    return pre_llm_call_context_fallback_chars_max()


def _full_skill_context_cost_profile() -> SkillContextCostProfile:
    from ..skills.context_cost import skill_context_cost_payload

    for profile in skill_context_cost_payload()["profiles"]:
        if profile["profile"] == "full":
            return profile
    raise KeyError("full profile missing from skill_context_cost_payload()")


def _full_profile_skill_body_chars() -> int:
    return int(_full_skill_context_cost_profile()["skill_body"]["bytes"])


def _full_profile_skill_body_repeated_chars() -> int:
    return int(_full_skill_context_cost_profile()["repeated"]["bytes"])


def count_metrics() -> tuple[CountMetric, ...]:
    return (
        CountMetric(
            name="chat_card_case_count",
            describe="Chat card coverage cases",
            live=_chat_card_case_count,
            expected=90,
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
            expected=210,
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
            # #1688 adds twelve for the skill-name lane: two Kubernetes
            # restart-loop sentences (English and Korean) and one past-tense
            # `asked`, where the name matched inside a longer word; two
            # hiring sentences naming `backend`, where one word was credited
            # four times over; the three survey rows that reach their wrong
            # skill through the metadata fold instead of a name; two verbs
            # carrying the phrasings `plan` gained; an organisational remark
            # naming the frontend; and a recorded interview.
            # #1689 adds three: two senses of `serve` that are not a model
            # being served (a CDN, and people), and something broken up that
            # is not code.
            # The story close adds two, both about the same loose word:
            # `finance-analysis` carried the bare `close` out of the separate
            # tokens of "month-end close" and claimed a modal and a database
            # transaction. Only these two -- the lane shipped no chat trigger
            # of its own, so it contributed no positive cases and no
            # `story` negatives.
            # The Jev skills add seven: sentences that name Jev as a model, a
            # setting, or among options, or talk about its docs, pricing page,
            # or question format, none of which addresses Jev.
            # Strict guard trust adds one: a question about what a Playwright
            # task costs, the negative half of browser-operator's own-phrase
            # intervention case.
            # #1892 adds eight: four habits told with a cadence phrase and four
            # non-code fix commands on a product noun and a defect noun.
            # The #1893 review adds three: modals said of a person (advice,
            # obligation, belief), which stay narration.
            # The #1893 re-review adds five: a modal inside a subordinate or
            # reported clause, which does not make the main clause a request.
            # #1817 adds four: three turns the route question's decline
            # predicate declines (a one-word approval, a thank-you, a Choice
            # offering only `none`) and one four-candidate non-request it must
            # keep asking.
            # #1799 adds six: human agents, a database compaction, an app's API
            # bill, and a recursive function, none of which is an agent run;
            # and six more that carry the incident phrases themselves (goal
            # drift, redoing work, looping, context lost after compaction) in a
            # human or non-agent sense.
            # The design-reference lane adds six: a migration course, an email
            # footer, wrong chart numbers, NLP text splitting, a quarterly
            # theme, and a marquee signing, none of which names frontend.
            # The quoted/relay/URL masks (#2049) add five: a block-quoted
            # invocation, a relayed report, an arrow-relayed and a
            # sender-relayed invocation, and a workflow name in a URL path.
            expected=439,
            # The one reviewed test pin. Every other test compares its payload
            # against build_routing_precision_demo() rather than a literal.
            sites=("tests/test_routing_precision.py",),
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
            # #1688 adds one: `deep-interview` traded its bare `interview`
            # trigger for "interview me", so the form the skill is actually
            # asked for is pinned beside the negative control.
            # #1689 adds four: the three shipped skills that lost their own
            # home turf (live incident, model serving, breaking up a long
            # function), plus a real page operation, because the guard
            # ordering that stops `browser-operator` pre-empting an incident
            # must not cost it its own lane.
            # The Jev skills add forty-five: each skill's phrase and a
            # paraphrase, the partner swap, free-form questions that stay on
            # jev-ask, and sentences about Jev (descriptive, negated,
            # configuration, a maintainer's mention of a skill name, an
            # explicit non-Jev invocation) that keep their ordinary owner.
            # Strict guard trust adds one: a Playwright task reaching
            # browser-operator on its own phrase, once its guard-carried case
            # became a clarify.
            # #1892 adds three: a cadence request that still dispatches, a
            # command to fix a product crash that asks with the coding lane
            # first, and a report of the same crash that still triages.
            # The #1893 review adds seven: subject-initial and passive
            # scheduling requests (a directive modal or a delivery passive on a
            # noun-phrase subject) that must keep dispatching.
            # The achievements and wiki chat cards add two: a badge-progress
            # request and a wiki-from-notes request, each answered by its own
            # card instead of the generic acknowledgement.
            # #1817 adds three: a single-candidate clarify the route question's
            # decline predicate declines, and a one-word request and a
            # four-candidate clarify it keeps.
            # #1799 adds five: looping, repeated work, goal drift, context loss
            # and unexpected cost in an agent run, each reaching agent-debug.
            # The design-reference lane adds seven: chart theming, footer
            # design, neobrutalism, split-text animation, two Korean
            # dispatches, and a Korean logo marquee that names frontend.
            # The quoted/relay/URL masks (#2049) add three: an invocation
            # beside a URL, after a block-quote line, and after a relay header
            # line, each still dispatching.
            expected=637,
            # The one reviewed test pin. Every other test compares its payload
            # against build_routing_precision_demo() rather than a literal.
            sites=("tests/test_routing_precision.py",),
        ),
        CountMetric(
            name="installable_skill_count",
            describe="Installable workflow skills quoted in reference surfaces",
            live=_installable_skill_count,
            # The current workflow additions are part of the installable catalog.
            expected=142,
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
    from ..plugin_bundle.omh.turn_budget import (
        AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
        AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
        AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
        PRE_LLM_CALL_CONTEXT_CHAR_LIMIT,
        PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT,
        ROLE_CONTEXT_CHAR_LIMIT,
    )
    from .release import (
        FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
        FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_CEILING_STEP_CHARS,
        FULL_PROFILE_SKILL_BODY_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_MEASURED_CHARS,
        FULL_PROFILE_SKILL_BODY_REPEATED_CEILING_STEP_CHARS,
        FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT,
        FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS,
        FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS,
        PLUGIN_TOOL_SCHEMA_CHAR_LIMIT,
        SKILL_INDEX_CHAR_LIMIT,
        SKILL_INDEX_LINE_CHAR_LIMIT,
        STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
        STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
    )

    return (
        # The first five can reach the model on every request or turn (the tool
        # schemas only when Hermes's tool_search is off; with the default bridge
        # they are deferred behind a listing). Everything after them is paid on
        # demand (a tool call, a `skill_view` load) or is a quality signal. Read
        # this group first when a change grows context.
        BudgetMetric(
            name="skill_index_chars",
            describe="Per request: full-profile skill index lines Hermes renders (60-char descriptions)",
            live=_skill_index_chars,
            limit=SKILL_INDEX_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="skill_index_line_max_chars",
            describe="Per request: longest single skill line in that index",
            live=_skill_index_line_max_chars,
            limit=SKILL_INDEX_LINE_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="plugin_tool_schema_chars",
            describe="Eager ceiling, per request only if tool_search is off: plugin tool schemas as registered (JSON chars)",
            live=_plugin_tool_schema_chars,
            limit=PLUGIN_TOOL_SCHEMA_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="pre_llm_call_context_chars_max",
            describe="Per turn, replayed in history: largest fenced pre_llm_call context over the named scenarios",
            live=_pre_llm_call_context_chars_max,
            limit=PRE_LLM_CALL_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="pre_llm_call_context_fallback_chars_max",
            describe="Per turn, replayed in history: that context for a session without the awareness section (primer included)",
            live=_pre_llm_call_context_fallback_chars_max,
            limit=PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="awareness_primer_markdown_chars",
            describe="Awareness primer markdown size",
            live=_awareness_primer_markdown_chars,
            limit=AWARENESS_PRIMER_MARKDOWN_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        # The three below and the two capability item sizes were compared only
        # inside `skill_content_smoke`, which now reads their verdict here, so
        # `omh release drift` reports them too. Each is a hand-set ceiling with
        # standing headroom and no recorded measurement.
        BudgetMetric(
            name="awareness_primer_context_chars",
            describe="Awareness primer compact context size",
            live=_awareness_primer_context_chars,
            limit=AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="awareness_workflow_context_chars_max",
            describe="Largest per-skill awareness workflow context",
            live=_awareness_workflow_context_chars_max,
            limit=AWARENESS_WORKFLOW_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="role_context_chars_max",
            describe="Largest role context file",
            live=_role_context_chars_max,
            limit=ROLE_CONTEXT_CHAR_LIMIT,
            limit_site="src/plugin_bundle/omh/turn_budget.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="full_capability_skill_section_chars",
            describe="Full capability skill section size",
            live=_full_capability_section_chars,
            limit=FULL_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="full_capability_skill_item_chars_max",
            describe="Largest single full capability skill item",
            live=_full_capability_item_chars_max,
            limit=FULL_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="standalone_capability_skill_section_chars",
            describe="Standalone capability skill section size",
            live=_standalone_capability_section_chars,
            limit=STANDALONE_CAPABILITY_SKILL_SECTION_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ratchet",
        ),
        BudgetMetric(
            name="standalone_capability_skill_item_chars_max",
            describe="Largest single standalone capability skill item",
            live=_standalone_capability_item_chars_max,
            limit=STANDALONE_CAPABILITY_SKILL_ITEM_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ceiling",
        ),
        BudgetMetric(
            name="full_profile_skill_body_chars",
            describe="Install footprint: full-profile SKILL.md bodies, each loaded on demand (producer chars)",
            live=_full_profile_skill_body_chars,
            limit=FULL_PROFILE_SKILL_BODY_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            reviewed_exception=FULL_PROFILE_SKILL_BODY_REVIEWED_EXCEPTION_CHARS,
            kind="ceiling",
            measured=FULL_PROFILE_SKILL_BODY_MEASURED_CHARS,
            step=FULL_PROFILE_SKILL_BODY_CEILING_STEP_CHARS,
        ),
        # Text repeated verbatim across bodies is paid on every load of each of
        # them and belongs once in a reference. A ceiling with headroom like the
        # footprint above, sized so the rail copies an ordinary new lane member
        # carries fit (policy in src/maintenance/release.py).
        BudgetMetric(
            name="full_profile_skill_body_repeated_chars",
            describe="Repeated across bodies: full-profile SKILL.md sections byte-identical to another skill's (producer chars)",
            live=_full_profile_skill_body_repeated_chars,
            limit=FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT,
            limit_site="src/maintenance/release.py",
            kind="ceiling",
            measured=FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS,
            step=FULL_PROFILE_SKILL_BODY_REPEATED_CEILING_STEP_CHARS,
        ),
        # The byte budget above says how much the pack costs; this says whether
        # the characters carry instruction. A hit is a reviewed filler phrase
        # that every load of a body pays for without changing what a reader
        # does, so the ceiling is zero on a corpus measured at zero. The other
        # two density signals are floats and stay in `tests/test_skill_density.py`.
        BudgetMetric(
            name="skill_density_filler_hits",
            describe="Reviewed filler phrases across all catalog skill bodies",
            live=_skill_density_filler_hits,
            limit=DENSITY_FILLER_HIT_CEILING,
            limit_site="src/quality/skill_density.py",
            kind="ratchet",
        ),
    )


def limits() -> dict[str, Limit]:
    """Every budget's limit and kind, by metric name. Reads no producer."""
    return {
        metric.name: Limit(
            kind=metric.kind,
            value=metric.limit,
            measured=metric.limit if metric.kind == "ratchet" else metric.measured,
            step=metric.step,
        )
        for metric in budget_metrics()
    }


def measure() -> dict[str, int]:
    """Every count and budget as its producer reads it today, by metric name."""
    return {metric.name: metric.live() for metric in (*count_metrics(), *budget_metrics())}


def generated_artifacts() -> tuple[GeneratedArtifact, ...]:
    from ..capabilities.families import standalone_capability_families_json
    from ..catalogs.roles import roles_reference_markdown
    from ..routing.skill_shortlist_sidecar import standalone_skill_shortlist_json
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
        GeneratedArtifact(
            name="skill_shortlist_sidecar",
            path="src/plugin_bundle/omh/tools/skill_shortlist.json",
            render=standalone_skill_shortlist_json,
            regenerate="uv run python -m omh.cli docs skill-shortlist",
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


verdict = drift_report


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
