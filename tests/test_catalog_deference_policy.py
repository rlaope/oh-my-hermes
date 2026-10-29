"""Gate for the deference graph the catalog already writes down in prose.

`SkillDefinition.do_not_use_when` is where a skill declines a request, and
many of its statements decline it *to a named sibling* - "use `ultrawork`",
"belongs to `oh-my-hermes`". Those names are written in backticks, which makes
the field a machine-readable deference graph: (owner, sibling) pairs asserting
who owns a request when the two skills compete. Its size is pinned in
`EXPECTED_DEFERENCE_CASES`, `EXPECTED_DEFERENCE_PAIRS`, and
`EXPECTED_DEFERRING_OWNERS`; the first command below re-derives all three.

Almost nothing reads that graph. `src/routing/recommend.py` derives its scoring
surface from `name`, `description`, `use_when` and `triggers`;
`do_not_use_when` reaches `render.py`, `capabilities/`, and `validation.py` and
stops there. The one exception is `_SIBLING_POINTER_METADATA_TOKENS` in
`recommend.py`, a hand-maintained one-entry dict that subtracts a sibling's
vocabulary from `research` - the same idea, applied once, by hand, after a
specific misroute. So the catalog can otherwise contradict itself at the routing
surface - a skill outranking the sibling it says owns the request - and no test
notices.

This module notices. It re-derives the graph from the catalog at run time and
compiles each declining statement into an executable probe, asserting the
disclaiming skill does not outrank the sibling it names. Catalog-name backticks
encode graph metadata here, not quoted user intent; non-skill references stay
quoted.

WHAT A PASS IS AND IS NOT WORTH. The query is the owner's own authored prose, so
the owner carries a large home-field vocabulary advantage - and the statement
also contains the sibling's literal name, which hands the sibling an advantage
back. Measured on the catalog when this gate landed, that name was doing most
of the work: with the sibling's name blanked out of the query, inversions rose
several-fold and the sibling lost rank 0 in many cases. Read the two halves
differently. The passes are weak - they largely restate that the router
surfaces a skill named verbatim in the query. The inversions are strong: an
owner that outranks a sibling *whose name is in the query* is the hardest
version of the failure to produce, and an inversion introduced later would have
to clear the same bar to show up here.

`KNOWN_INVERSIONS` records the verdict for every pair that inverts today,
anchored by (owner, siblings) - never by line number or by rank, which drift on
unrelated edits. A new inversion cannot land unclassified, a recorded one that
stops inverting fails too, and `EXPECTED_INVERSION_COUNT` makes growing the list
a deliberate edit rather than a quiet one. Fixing the recorded ones means
changing scoring weights, which is a routing-behaviour change carrying its own
overroute-guard obligations; it is deferred, not owned by an issue yet, and the
ratchet is what keeps that debt visible.

Re-derive the three shape counts:

    uv run python -c "import re; from omh.skills.catalog import builtin_definitions as b, routable_skill_names as r; \
n=set(r()); p=re.compile(r'\\`([a-z0-9][a-z0-9-]*)\\`'); \
c=[(d.name,tuple(sorted({x for x in p.findall(s) if x in n and x!=d.name}))) \
for d in b() if d.name in n for s in d.do_not_use_when]; c=[x for x in c if x[1]]; \
print(len(c), len({(o,s) for o,ss in c for s in ss}), len({o for o,_ in c}))"

Inspect one case with the same field width the test scores against:

    uv run python -m omh.cli recommend --limit 25 --json "<a do_not_use_when statement>"
"""

from __future__ import annotations

import re
import unittest

from omh.routing.recommend import recommend_skills
from omh.skills.catalog import builtin_definitions, routable_skill_names
from omh.skills.catalog_types import HermesSkillLine

# Skill references in `do_not_use_when` use the catalog's own name shape. The
# pattern is deliberately narrower than "any backticked token" because the field
# also backticks things that are not skills at all - see NON_SKILL_BACKTICKS -
# and a leading `.` keeps those out by construction rather than by luck.
_BACKTICKED_NAME = re.compile(r"`([a-z0-9][a-z0-9-]*)`")

# Every backticked token, whatever its shape. Used only by the authoring-
# discipline test, which must not reuse `_BACKTICKED_NAME`: checking the narrow
# pattern's own matches against the catalog is circular and would stay green
# while a real name drifted out of the pattern (`Ultraprocess`, say).
_ANY_BACKTICKED_TOKEN = re.compile(r"`([^`]+)`")

# Backticked tokens in `do_not_use_when` that are deliberately not skills: file
# and artifact names quoted in the prose. Enumerated so a genuinely misspelled
# skill name cannot hide among them.
# The three `ulw-work` internal capability ids that its do_not_use_when
# boundaries reference after the ULW fold (issue #954, PR D) are deliberate
# non-skill names: they are capabilities of `ultrawork`, not catalog siblings.
# A skill Hermes bundles is named only inside a `HermesSkillLine`, which
# declares its names itself, so it needs no entry here; it adds no deference
# pair, because the router can only rank catalog skills.
NON_SKILL_BACKTICKS = frozenset(
    {
        ".env",
        ".pptx",
        "coordinated_scope",
        "single_owner_persistence",
        "durable_checkpoint",
        "delivery_boundary",
        # A Rust language keyword, backticked as code in `backend` and
        # `native-debugging`'s do_not_use_when, never a skill name.
        "unsafe",
        # Hermes' own session commands and their flags, named in `loop`'s
        # do_not_use_when where a request belongs to the host's timer or
        # single-objective driver rather than a sibling.
        "/loop",
        "--until",
        "--times",
        "/goal",
        "/goal draft",
    }
)

# A statement that names a sibling, and the sibling(s) it names. The counts are
# contracts: a new skill whose do_not_use_when points at a sibling adds a case
# here, and that is the moment to confirm the router honours the new boundary.
# ULW fold (issue #954, PR D): ultrawork's carried delivery/durable boundaries
# add one deference statement naming `loop`.
# ULW retirement (#954 stage 5): loop's bad-examples repoint from the retired
# `ultraprocess`/`ultragoal` to `ultrawork`'s delivery-boundary and
# durable-checkpoint capabilities, adding two loop -> ultrawork cases, one new
# pair, and loop as a new deferring owner.
# `adversarial-consensus` is a new deferring owner: its do_not_use_when points
# at `ralplan` (the plan itself), `deep-interview` (a proposal too vague to
# attack), `code-review` (finished code, not a proposal), and `ultraqa`
# (hostile runtime scenarios) -- four cases, four new pairs.
# `llm-app-dev` is a new deferring owner: its do_not_use_when points at
# `agent-evaluation` (comparing executors, not the product's own model calls),
# `agent-debug` (a run already stuck or looping), `context-budget-review` (the
# harness's own prompt cache, not the application), and `security-safety-review`
# (a risk gate on work that already exists) -- four cases, four new pairs.
# The domain skill pack adds three deferring owners and eleven cases: `backend`
# points at `frontend`, `security-safety-review`, `verification-gate`, and
# `rust`; `rust` points at `backend`, `native-debugging`, and `code-review`;
# `native-debugging` points at `build-failure-triage`, `agent-debug`, `rust`,
# and `verification-gate`. Eleven cases, eleven new pairs.
# The `web-research` split adds one deferring owner and nine cases: the new
# lane points at `research`, `best-practice-research`, `source-finder`,
# `research-brief`, `research-department`, `codebase-onboarding`, and
# `websearch-setup`; `research` points back at it; and
# `best-practice-research`'s single statement became two when the lookup half
# of its boundary stopped belonging to the engine. (`best-practice-research`
# has since retired into `web-research` itself -- see the #1691 note at the
# counts below.)
# `tech-debt-audit` defers on four boundaries -- diff-scoped judgement to
# `code-review`, deletion-first cleanup to `ai-slop-cleaner`, phased execution
# of a big fix to `refactor-plan`, and release risk to `production-audit`.
# Four cases, four new pairs, one new deferring owner.
# The `refactor-plan` repointing gives the phase planner the deference edges
# its own boundaries already claimed: `frontend-refactor` and
# `ai-slop-cleaner` hand a boundary-crossing restructure to it (keeping
# `ralplan` for a contested direction), and `ralplan` hands back a decided
# refactor that only needs its execution shape. One new case (ralplan's new
# statement), three new pairs; the two rewritten statements already counted.
# `omh-docs` adds three measured mutation-deference cases and pairs, with
# `product-docs` as one new deferring owner.
# `long-document-reading` defers on four boundaries -- a paper explained by
# level to `paper-learning`, file production and office conversion to
# `materials-package`, non-document media to `media-input-operator`, and a
# document not yet in hand to `source-finder`. Four cases, four new pairs, one
# new deferring owner.
# `application-threat-model` defers on five boundaries -- the agent's own
# prompt, tool, and credential surface to `security-safety-review` (the
# collision this skill exists to end), diff-scoped defect hunting to
# `code-review`, release readiness to `production-audit`, merge commands to
# `verification-gate`, and a regulatory obligation rather than an attacker to
# `legal-compliance-review`. Five cases, five new pairs, one new deferring
# owner. `security-safety-review` gains the reciprocal statement pointing back
# at `application-threat-model`, which closes the collision in both directions:
# one more case and one more pair, no new owner.
# `live-incident-response` defers on five boundaries -- a closed incident's
# postmortem, SLO consequence, and remediation follow-up to `reliability-review`
# (the misroute this skill exists to end), one customer's support case to
# `support-operations`, a release being watched with nothing declared broken to
# `deploy-and-monitor`, the actual send of a page, status-page update, or
# customer notice to `connector-operator`, and pre-release readiness to
# `production-audit`. Five cases, five new pairs, one new deferring owner.
# The boundary closes in all three directions rather than one:
# `reliability-review` and `deploy-and-monitor` each gain their first
# `do_not_use_when` statement pointing back at the live lane, which makes them
# two new deferring owners, and `support-operations`'s single active-incident
# statement splits into two -- the live half to `live-incident-response`, the
# retrospective half staying with `reliability-review` -- because that one line
# is what sent an open outage to a postmortem. Three more cases, three more
# pairs, two more owners.
# `strategy-brief` gains one statement handing the hiring PROCESS -- scorecards,
# interview loops, candidate comparison -- to `people-ops`, because the
# capacity-planning example it now carries answers whether to hire and stops
# there (#1580). One case, one pair, no new owner: `strategy-brief` already
# defers to `product-discovery-validation`.
# Three strict-subset skills retire into a stronger sibling (#1691), and a
# retired contract is not a deference destination a reader can reach. The
# deferring owners `best-practice-research`, `autoresearch-goal`, and
# `performance-goal` leave the graph with their bodies; `research` and
# `web-research` each lose the statement pointing at the lookup skill now
# folded into `web-research`; and `inference-serving`, `model-optimization`,
# and `ultraperf` keep their statements with one destination each instead of
# two. Six cases, eight pairs, two owners.
# The six `jev-*` skills each defer to the ordinary owner of their partner
# lane (`jev-ask` to `ask`, `strategy-brief`, and `model-setup`; `jev-route`
# to `model-setup`; the four preset skills to `build-failure-triage`,
# `agent-debug`, `live-incident-response`, `code-review`,
# `verification-gate`, `security-safety-review`, `command-operator`, and
# `loop`): fourteen cases, fourteen pairs, six new owners. `ask` gains its
# first statement, handing typed Jev probabilities to `jev-ask` (a new
# owner), and `strategy-brief` gains the same hand-off (no new owner). Sixteen
# cases, sixteen pairs, seven owners.
# `app-debugging` (#1709) defers to `native-debugging`, `build-failure-triage`,
# `agent-debug`, and `verification-gate` (a new owner), and the first two each
# gain the statement pointing back at it. Six cases, six pairs, one owner.
# `commit-pr-authoring` (#1711) defers to `code-review`, `github-event-ops`,
# `github-issue-intake`, and `content-operator`. Four cases, four pairs, one
# owner.
# `git-workflow` (#1695) defers to `commit-pr-authoring`, `code-review`,
# `build-failure-triage`, and `ultrawork`. Four cases, four pairs, one owner.
# `relational-db` (#1692) defers to `backend`, `ultraperf`, `data-analysis`,
# and `deploy-and-monitor`, and `backend` gains the statement pointing back.
# Five cases, five pairs, one owner.
# `security-event-response` (#1694) defers to `security-safety-review`,
# `application-threat-model`, `github-event-ops`, `legal-compliance-review`,
# and `live-incident-response`; `security-safety-review` gains the statement
# pointing back, and `github-event-ops` gains its first backticked statement
# (a new owner). Seven cases, seven pairs, two owners.
# `release-cut` (#1693) defers to `deploy-and-monitor`, `live-incident-response`,
# `production-audit`, and `commit-pr-authoring`, and `deploy-and-monitor`
# gains the statement pointing back. Five cases, five pairs, one owner.
# `agent-instructions` (#1713) defers to `rules-distill`, `codebase-onboarding`,
# `context`, and `product-docs`, and `rules-distill` gains the statement
# pointing back. Five cases, five pairs, one owner.
# The dependabot split (#1712): `refactor-plan` defers a bump that carries an
# advisory to `security-event-response`, and `github-event-ops` defers a bump
# with none to `refactor-plan`; `security-event-response`'s bump statement now
# names `refactor-plan` instead of `github-event-ops`, which swaps one pair for
# another. Two cases, two pairs, no new owner.
# `iac-change` (#1566) defers to `deploy-and-monitor`, `release-cut`,
# `inference-serving`, and `live-incident-response`, and `deploy-and-monitor`
# gains the statement pointing back. Five cases, five pairs, one owner.
# `data-pipelines` (#1565) defers to `backend`, `data-analysis`,
# `relational-db`, and `memory-sync`, and `backend` gains the statement
# pointing back. Five cases, five pairs, one owner.
# `model-finetuning` (#1567) defers to `model-optimization`,
# `inference-serving`, `llm-app-dev`, and `workflow-learning`, and
# `llm-app-dev` gains the statement pointing back. Five cases, five pairs, one
# owner.
# `mobile-release` (#1568) defers to `release-cut`, `deploy-and-monitor`,
# `production-audit`, and `app-debugging`, and `release-cut` gains the
# statement pointing back. Five cases, five pairs, one owner.
# `internal-audit` (#1569) defers to `finance-analysis`,
# `legal-compliance-review`, `production-audit`, and `tech-debt-audit`, and
# `finance-analysis` gains the statement pointing back. Five cases, five
# pairs, one owner.
# Six feature-surface skills replace the shape's three generic Do-Not-Use
# lines with their own: `github-event-ops` adds `github-issue-intake` and
# `build-failure-triage`; `browser-operator` adds `visual-qa` and
# `web-research`; `workspace-file-operator` adds `materials-package` and
# `deliverable-package` in one statement; `command-operator` adds
# `build-failure-triage` and `agent-debug` in one statement and
# `security-safety-review`; `connector-operator` adds `gateway-intent-card`
# and `external-connector-readiness`; `physical-device-readiness` adds
# `external-connector-readiness`, `toolbelt-readiness`, and `command-operator`
# with `connector-operator` in one statement. Twelve cases, fifteen pairs,
# five new owners (`github-event-ops` already deferred).
# Two more skills state their own Do-Not-Use against Hermes' native producers:
# `deliverable-package` (a feature-surface skill) adds `materials-package` and
# `report-package`; `ultraqa` replaces the catalog's generic fallback lines and
# adds `visual-qa` and `verification-gate`. Four cases, four pairs, two new
# owners.
# Tracker skills onto Hermes' own surfaces: `run-efficiency` and
# `ops-observability-card` state their own Do-Not-Use and name each other;
# `toolbelt-readiness` names `external-connector-readiness` and
# `executor-runtime-readiness` in two statements; `cancel` names
# `running-work-board`; `skill` names `capability-toggle`, `skill-scout`, and
# `skill-health` in three statements; `context-budget-review` stops naming
# `ops-observability-card`, which cannot produce a session's own usage (Hermes'
# /usage and omh_run_summary do). Seven cases and seven pairs net, five new
# owners.
# Seven memory and learning feature-surface skills do the same, three
# statements each, every one naming a sibling: `memory-sync` adds
# `memory-new`, `decision-recall`, and `external-connector-readiness`;
# `external-connector-readiness` adds `executor-runtime-readiness`,
# `toolbelt-readiness`, and `live-info-operator` with `connector-operator` in
# one statement; `prompt-import-readiness` adds `external-connector-readiness`,
# `toolbelt-readiness`, and `skill-scout`; `instinct-ledger` adds
# `workflow-learning`, `rules-distill`, and `agent-debug`; `skill-scout` adds
# `doctor`, `skill-health`, and `skill`; `skill-health` adds `doctor`,
# `workflow-learning`, and `skill-scout`; `workflow-learning` adds
# `memory-new`, `instinct-ledger`, and `agent-debug`. Twenty-one cases,
# twenty-two pairs, seven new owners.
# `data-share-review`, added for files leaving the team, defers to
# `legal-compliance-review`, `security-safety-review`, `data-analysis`,
# `github-issue-intake`, `model-finetuning`, and `support-operations`, and
# `legal-compliance-review` gains the statement pointing back. Seven cases,
# seven pairs, one owner.
# `spend-gate` defers to `browser-operator`, `feedback-triage`,
# `finance-analysis`, and `provider-profile-posture`; no sibling gains a
# statement pointing back. Four cases, four pairs, one owner.
# `automation-blueprint` (a recurring job that would move money) and
# `browser-operator` (a page step that moves money) now point at
# `spend-gate`, and `loop`'s unattended-schedule statement points at
# `automation-blueprint` instead of naming Hermes' cron tool. Three cases,
# three pairs, no new owner.
# `dag-ulw` defers a small change and coordinated lanes to `ultrawork` and an
# undecided plan to `ralplan`; no sibling gains a statement pointing back.
# Three cases, two pairs, one owner.
# `market-research` defers a kill/pivot gate to `product-discovery-validation`,
# a recurring source inbox to `research-department`, ticket clustering to
# `feedback-triage`, a supplied spreadsheet to `data-analysis`, an academic
# PDF to `paper-learning`, and an audience-ready synthesis to
# `research-brief`; no sibling gains a statement pointing back. Six cases,
# six pairs, one owner.
# `show-reel` defers a static card to `img-summary`, a website build to
# `frontend`, a deck or document to `materials-package`, a layout assessment
# to `design-quality-gate`, and a verdict on rendered frames to `visual-qa`;
# no sibling gains a statement pointing back. Five cases, five pairs, one
# owner.
# Three science owners add four statements and six sibling pairs.
# Career work defers employer-side hiring to people-ops; re-derived from the catalog.
# `sprite-forge` defers motion production to `show-reel`, rendered-screen
# verdicts to `visual-qa` and image cards to `img-summary`; no sibling gains a
# statement pointing back. Three cases, three pairs, one owner.
# `show-reel`'s idea-video lane defers a recording that already exists
# (summary, transcript, captions, trim) to `media-input-operator`; one case,
# one pair, no new owner.
EXPECTED_DEFERENCE_CASES = 407
EXPECTED_DEFERENCE_PAIRS = 423
EXPECTED_DEFERRING_OWNERS = 120

# The ratchet. Recording a new inversion must be a visible edit to this number,
# not one more dict line with a plausible sentence attached.
EXPECTED_INVERSION_COUNT = 4

# How much of the ranked field an inversion is judged against. Wide enough that
# a deferred-to sibling is never merely off the end: every pair surfaces within
# it except those in `DELIBERATELY_UNREACHABLE`, whose sibling the router does
# not return for that statement at all, so no wider field would reach it.
# `test_every_deferred_to_sibling_is_reachable` holds both: the other pairs
# inside this field, the listed ones outside it. Narrow enough that "outranks"
# still means something among the routable skills.
FIELD_LIMIT = 25

# A rationale short enough to be a label rather than a verdict defeats the point
# of recording one. Same floor as the broad-exception gate this file models.
MINIMUM_RATIONALE_LENGTH = 40

# Recorded inversions. Each is a near-tie - the owner takes rank 0 and the
# sibling rank 1 - where the owner's own prose out-weighs the sibling's name
# appearing verbatim in the query.
KNOWN_INVERSIONS: dict[tuple[str, tuple[str, ...]], str] = {
    ("source-finder", ("research",)): (
        "The statement contrasts 'factual findings, comparison, or a summary' with a 'typed candidate "
        "inventory'. Both halves are source-finder's own vocabulary, so the sentence scores as its home "
        "topic even though it hands the request to research. Adjacent to the one hand-tuned entry in "
        "_SIBLING_POINTER_METADATA_TOKENS, which compensates for research's cross-references by hand."
    ),
    ("product-brief", ("ralplan", "ultrawork")): (
        "'accepted, code-ready change with repository constraints and verification needs' is a product "
        "sentence describing a delivery request; product-brief matches the framing, the siblings match "
        "the work."
    ),
    ("ralplan", ("ai-slop-cleaner", "ultrawork")): (
        "'small local refactor or cleanup with no architectural or regression risk' names the risk "
        "vocabulary ralplan exists to reason about, so the skill that decides plan depth outranks the "
        "two skills that would carry out the cleanup."
    ),
    ("ai-slop-cleaner", ("ultrawork",)): (
        "'new or changed behavior rather than removing existing code' states the cleanup boundary using "
        "cleanup words; the removal vocabulary keeps the declining skill on top."
    ),
}


# Siblings that are unreachable by design, keyed (owner, sibling). This is not
# routing debt: the router offers the sibling only to a shape of request that a
# Do-Not-Use statement is not, so the statement cannot surface it, and the owner
# then outranks it by default. Each pair carries its reason; a pair that becomes
# reachable fails until its entry is deleted, the rule `docs navigation --check`
# applies to a reachable page still marked exempt; and
# `EXPECTED_DELIBERATELY_UNREACHABLE_COUNT` makes growing the list a deliberate
# edit.
_SPEND_GATE_BY_DESIGN = (
    "by design (#2121): spend-gate is offered only to a request clause that leads with a spend and carries a "
    "request marker; a Do-Not-Use line is not such a request, so it cannot surface spend-gate. A person's "
    "marked request ('please pay ... with my card') reaches it."
)
DELIBERATELY_UNREACHABLE: dict[tuple[str, str], str] = {
    ("automation-blueprint", "spend-gate"): _SPEND_GATE_BY_DESIGN,
    ("browser-operator", "spend-gate"): _SPEND_GATE_BY_DESIGN,
}
EXPECTED_DELIBERATELY_UNREACHABLE_COUNT = 2


def _deference_cases() -> list[tuple[str, tuple[str, ...], str]]:
    """Return (owner, siblings, statement) for every declining statement that names a sibling."""

    routable = set(routable_skill_names())
    catalog_names = {
        definition.name for definition in builtin_definitions() if definition.name in routable
    }
    cases: list[tuple[str, tuple[str, ...], str]] = []
    for definition in builtin_definitions():
        if definition.name not in routable:
            continue
        for statement in definition.do_not_use_when:
            named = {
                name
                for name in _BACKTICKED_NAME.findall(statement)
                if name in catalog_names and name != definition.name
            }
            if named:
                cases.append((definition.name, tuple(sorted(named)), statement))
    return cases


def _routed_field(statement: str) -> list[str]:
    catalog_names = {definition.name for definition in builtin_definitions()}
    query = _BACKTICKED_NAME.sub(
        lambda match: match.group(1) if match.group(1) in catalog_names else match.group(0),
        statement,
    )
    return [recommendation["skill"] for recommendation in recommend_skills(query, limit=FIELD_LIMIT)]


def _rank(field: list[str], skill: str) -> int:
    return field.index(skill) if skill in field else len(field)


class CatalogDeferenceGraphTests(unittest.TestCase):
    def test_every_backticked_token_is_a_skill_or_a_declared_non_skill(self) -> None:
        """The authoring discipline the derivation depends on.

        Scanned with the broad pattern on purpose. If a statement backticks a
        renamed, miscased, or misspelled skill, the narrow pattern simply stops
        matching it and the pair vanishes from the graph instead of failing -
        so a test that reused the narrow pattern would be blind to exactly the
        drift it exists to catch.
        """

        catalog_names = {definition.name for definition in builtin_definitions()}
        routable = set(routable_skill_names())
        unknown: list[tuple[str, str]] = []
        for definition in builtin_definitions():
            if definition.name not in routable:
                continue
            for statement in definition.do_not_use_when:
                # A `HermesSkillLine` hands the request to a skill Hermes
                # bundles; it declares those names itself, and only those pass.
                bundled = statement.skills if isinstance(statement, HermesSkillLine) else ()
                for token in _ANY_BACKTICKED_TOKEN.findall(statement):
                    if token not in catalog_names and token not in NON_SKILL_BACKTICKS and token not in bundled:
                        unknown.append((definition.name, token))
        self.assertEqual(
            sorted(unknown),
            [],
            "do_not_use_when backticks a token that is neither a catalog skill name nor a declared "
            "non-skill; fix the name, or add it to NON_SKILL_BACKTICKS if it is genuinely not a skill",
        )

    def test_deference_graph_shape_is_stable(self) -> None:
        cases = _deference_cases()
        pairs = {(owner, sibling) for owner, siblings, _ in cases for sibling in siblings}
        owners = {owner for owner, _, _ in cases}
        self.assertEqual(len(cases), EXPECTED_DEFERENCE_CASES)
        self.assertEqual(len(pairs), EXPECTED_DEFERENCE_PAIRS)
        self.assertEqual(len(owners), EXPECTED_DEFERRING_OWNERS)

    def test_both_sides_of_every_pair_are_routable(self) -> None:
        """A pair is only meaningful if the router can actually return both skills."""

        routable = set(routable_skill_names())
        unroutable = sorted(
            {
                (owner, sibling)
                for owner, siblings, _ in _deference_cases()
                for sibling in siblings
                if owner not in routable or sibling not in routable
            }
        )
        self.assertEqual(unroutable, [], "a deference pair names a skill the router never returns")

    def test_every_deferred_to_sibling_is_reachable(self) -> None:
        """Close the both-absent blind spot in the inversion check.

        `_rank()` returns `len(field)` for a skill the router did not surface, so
        a statement where NEITHER the owner nor its sibling appears scores as a
        tie and reports no inversion - compliance by absence. Routing neither
        party for a sentence describing a real request is arguably worse than an
        inversion, so it is asserted here instead of being absorbed there. A pair
        in `DELIBERATELY_UNREACHABLE` is exempt only while it stays unreachable.
        """

        unreachable = [
            (owner, sibling, statement)
            for owner, siblings, statement in _deference_cases()
            for sibling in siblings
            if sibling not in _routed_field(statement)
        ]
        found = {(owner, sibling) for owner, sibling, _ in unreachable}
        self.assertEqual(
            sorted(set(DELIBERATELY_UNREACHABLE) - found),
            [],
            "a pair listed in DELIBERATELY_UNREACHABLE is reachable now, or no longer a deference pair; delete "
            "its entry so the list keeps describing live behaviour",
        )
        self.assertEqual(
            [(owner, sibling) for owner, sibling, _ in unreachable if (owner, sibling) not in DELIBERATELY_UNREACHABLE],
            [],
            f"a skill hands a request to a sibling the router does not surface within the top "
            f"{FIELD_LIMIT}; the deference boundary is unreachable, not merely out-ranked",
        )

    def test_every_deliberately_unreachable_pair_says_why(self) -> None:
        thin = sorted(
            key
            for key, rationale in DELIBERATELY_UNREACHABLE.items()
            if len(rationale.strip()) < MINIMUM_RATIONALE_LENGTH or not rationale.startswith("by design")
        )
        self.assertEqual(thin, [], "a deliberately unreachable pair must say why it is unreachable by design")
        self.assertEqual(
            len(DELIBERATELY_UNREACHABLE),
            EXPECTED_DELIBERATELY_UNREACHABLE_COUNT,
            "the deliberately-unreachable list changed size; growing it must be a deliberate edit to "
            "EXPECTED_DELIBERATELY_UNREACHABLE_COUNT",
        )

    def test_each_deliberately_unreachable_pair_comes_from_one_statement(self) -> None:
        """The exemption is keyed by pair, so a second statement naming the same pair would inherit it unreviewed."""

        statements: dict[tuple[str, str], list[str]] = {key: [] for key in DELIBERATELY_UNREACHABLE}
        for owner, siblings, statement in _deference_cases():
            for sibling in siblings:
                if (owner, sibling) in statements:
                    statements[(owner, sibling)].append(statement)
        self.assertEqual(
            {key: len(found) for key, found in statements.items() if len(found) != 1},
            {},
            "a DELIBERATELY_UNREACHABLE pair is named by other than exactly one statement; review the new statement "
            "on its own instead of letting it share the exemption",
        )

    def test_every_recorded_inversion_carries_a_rationale(self) -> None:
        thin = sorted(
            key for key, rationale in KNOWN_INVERSIONS.items() if len(rationale.strip()) < MINIMUM_RATIONALE_LENGTH
        )
        self.assertEqual(
            thin,
            [],
            "a recorded inversion carries no real verdict; say why the owner legitimately outranks the "
            "sibling it defers to, or fix the routing boundary instead of recording it",
        )
        self.assertEqual(
            len(KNOWN_INVERSIONS),
            EXPECTED_INVERSION_COUNT,
            "the recorded-inversion list changed size; growing it is accepted routing debt and must be a "
            "deliberate edit to EXPECTED_INVERSION_COUNT",
        )

    def test_no_skill_outranks_the_sibling_it_defers_to(self) -> None:
        inversions: dict[tuple[str, tuple[str, ...]], str] = {}
        for owner, siblings, statement in _deference_cases():
            if all((owner, sibling) in DELIBERATELY_UNREACHABLE for sibling in siblings):
                # Unreachable by design, which the reachability test holds; there is no rank to compare.
                continue
            field = _routed_field(statement)
            # `min` is the lenient reading for the 12 statements naming more than
            # one sibling: the best-placed sibling must beat the owner, not all
            # of them. Measured against `max` the result is identical today (4
            # inversions either way), so the lenient form is kept as the one that
            # states the weaker, more defensible claim.
            best_sibling = min(_rank(field, sibling) for sibling in siblings)
            if _rank(field, owner) < best_sibling:
                inversions[(owner, siblings)] = statement

        unclassified = sorted(key for key in inversions if key not in KNOWN_INVERSIONS)
        self.assertEqual(
            unclassified,
            [],
            "a skill now outranks the sibling its own do_not_use_when hands the request to; "
            "fix the routing boundary or record the verdict in KNOWN_INVERSIONS",
        )

        healed = sorted(key for key in KNOWN_INVERSIONS if key not in inversions)
        self.assertEqual(
            healed,
            [],
            "a recorded inversion no longer inverts; drop it from KNOWN_INVERSIONS so the list "
            "keeps describing live behaviour",
        )


if __name__ == "__main__":
    unittest.main()
