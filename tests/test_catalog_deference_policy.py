"""Gate for the deference graph the catalog already writes down in prose.

`SkillDefinition.do_not_use_when` is where a skill declines a request, and 128
of the catalog's 329 statements decline it *to a named sibling* - "use
`ultraprocess`", "belongs to `oh-my-hermes`". Those names are written in
backticks, which makes the field a machine-readable deference graph: 138
(owner, sibling) pairs asserting who owns a request when the two skills
compete.

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
routes each declining statement, asserting the disclaiming skill does not
outrank the sibling it names.

WHAT A PASS IS AND IS NOT WORTH. The query is the owner's own authored prose, so
the owner carries a large home-field vocabulary advantage - and the statement
also contains the sibling's literal name, which hands the sibling an advantage
back. Measured on the live catalog, that name is doing most of the work: with
the sibling's name blanked out of the query, inversions rise from 4 to 19 and
the sibling holds rank 0 in 64 cases rather than 105. Read the two halves
differently. The 124 passes are weak - they largely restate that the router
surfaces a skill named verbatim in the query. The 4 inversions are strong: an
owner that outranks a sibling *whose name is in the query* is the hardest
version of the failure to produce, and an inversion introduced later would have
to clear the same bar to show up here.

`KNOWN_INVERSIONS` records the verdict for every pair that inverts today,
anchored by (owner, siblings) - never by line number or by rank, which drift on
unrelated edits. A new inversion cannot land unclassified, a recorded one that
stops inverting fails too, and `EXPECTED_INVERSION_COUNT` makes growing the list
a deliberate edit rather than a quiet one. Fixing the recorded four means
changing scoring weights, which is a routing-behaviour change carrying its own
overroute-guard obligations; it is deferred, not owned by an issue yet, and the
ratchet is what keeps that debt visible.

Re-derive the three shape counts:

    uv run python -c "import re; from omh.skills.catalog import builtin_definitions as b; \
n={d.name for d in b()}; p=re.compile(r'\\`([a-z0-9][a-z0-9-]*)\\`'); \
c=[(d.name,tuple(sorted({x for x in p.findall(s) if x in n and x!=d.name}))) \
for d in b() for s in d.do_not_use_when]; c=[x for x in c if x[1]]; \
print(len(c), len({(o,s) for o,ss in c for s in ss}), len({o for o,_ in c}))"

Inspect one case with the same field width the test scores against:

    uv run python -m omh.cli recommend --limit 25 --json "<a do_not_use_when statement>"
"""

from __future__ import annotations

import re
import unittest

from omh.routing.recommend import recommend_skills
from omh.skills.catalog import builtin_definitions, routable_skill_names

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
# of its boundary stopped belonging to the engine.
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
EXPECTED_DEFERENCE_CASES = 191
EXPECTED_DEFERENCE_PAIRS = 204
EXPECTED_DEFERRING_OWNERS = 61

# The ratchet. Recording a new inversion must be a visible edit to this number,
# not one more dict line with a plausible sentence attached.
EXPECTED_INVERSION_COUNT = 4

# How much of the ranked field an inversion is judged against. Wide enough that
# a deferred-to sibling is never merely off the end - it holds in 128/128 cases
# today, which `test_every_deferred_to_sibling_is_reachable` pins - and narrow
# enough that "outranks" still means something among 103 routable skills.
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
    return [recommendation["skill"] for recommendation in recommend_skills(statement, limit=FIELD_LIMIT)]


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
                for token in _ANY_BACKTICKED_TOKEN.findall(statement):
                    if token not in catalog_names and token not in NON_SKILL_BACKTICKS:
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
        inversion, so it is asserted here instead of being absorbed there.
        """

        unreachable = [
            (owner, sibling, statement)
            for owner, siblings, statement in _deference_cases()
            for sibling in siblings
            if sibling not in _routed_field(statement)
        ]
        self.assertEqual(
            [(owner, sibling) for owner, sibling, _ in unreachable],
            [],
            f"a skill hands a request to a sibling the router does not surface within the top "
            f"{FIELD_LIMIT}; the deference boundary is unreachable, not merely out-ranked",
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
