"""Guard corpus for the deterministic request-complexity scorer.

Written in the `routing_precision` idiom and for the same reason: a scorer
without negative controls is an unguarded trigger. Two corpora, each with a
name worth grepping for and a failure metric of its own.

* `COMPLEXITY_PRECISION_CASES` is the **negative-control** corpus — ordinary
  small requests that must NOT escalate. Its failure metric is
  `overscore_count`.
* `COMPLEXITY_INTERVENTION_CASES` is the **positive** corpus — genuinely heavy
  requests that must reach at least the stated tier. Its failure metric is
  `missed_escalation_count`.

Grepping for "underscore" finds nothing; the positive guard lives under the
intervention name, exactly as the routing corpora do.

Every case names a `max_tier`/`min_tier` rather than an exact tier, so adding a
signal that moves a score within its band is a deliberate edit rather than a
fixture rewrite. Cases that DO pin an exact boundary live in the tier-boundary
tests, where a one-point change is supposed to be loud.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..coding.request_complexity import COMPLEXITY_TIERS, score_request_complexity

COMPLEXITY_PRECISION_SCHEMA_VERSION = "complexity_precision/v1"


@dataclass(frozen=True)
class ComplexityPrecisionCase:
    """A request that must stay at or below `max_tier`."""

    id: str
    title: str
    message: str
    max_tier: str
    routed_skill: str = ""


@dataclass(frozen=True)
class ComplexityInterventionCase:
    """A request that must reach at least `min_tier`, for the named reason."""

    id: str
    title: str
    message: str
    min_tier: str
    expected_signals: tuple[str, ...]
    routed_skill: str = ""


# Negative controls. A one-liner, a lookup, a rename, or a single narrow fix
# must never buy a frontier model. Several of these deliberately contain a word
# that ALSO appears in a heavy signal ("security header", "migrate one import")
# so the corpus proves the scorer needs more than one keyword to escalate.
COMPLEXITY_PRECISION_CASES: tuple[ComplexityPrecisionCase, ...] = (
    ComplexityPrecisionCase(
        "single-definition-lookup",
        "Looking up one definition stays light: one hit, not every hit",
        "where is the RouteDecision class defined?",
        "light",
    ),
    ComplexityPrecisionCase(
        "rename-everywhere",
        "A rename that says everywhere stays light: the tool does the finding",
        "rename DEFAULT_RETRY_LIMIT to MAX_RETRY_ATTEMPTS everywhere",
        "light",
    ),
    ComplexityPrecisionCase(
        "read-one-implementation",
        "Reading one implementation for facts stays light",
        "read the configuration implementation and return the default timeout and retries with citations",
        "light",
    ),
    ComplexityPrecisionCase(
        "typo-fix",
        "A typo fix never scores deep",
        "fix a typo in README.md",
        "light",
    ),
    ComplexityPrecisionCase(
        "one-line-change",
        "A stated one-liner never scores deep",
        "one line change: bump the version in pyproject.toml",
        "light",
    ),
    ComplexityPrecisionCase(
        "concept-question",
        "A concept question never scores deep",
        "what does reasoning effort mean in this report?",
        "light",
    ),
    ComplexityPrecisionCase(
        "file-lookup",
        "A file lookup never scores deep",
        "where is the router implemented?",
        "light",
    ),
    ComplexityPrecisionCase(
        "single-rename",
        "A rename in one file never scores deep",
        "rename the helper in src/routing/chat.py",
        "light",
    ),
    ComplexityPrecisionCase(
        "single-security-header",
        "One security header edit does not become deep on the word alone",
        "add a security header to the response in src/server.py",
        "standard",
    ),
    ComplexityPrecisionCase(
        "narrow-migration-import",
        "Migrating one import is not a migration project",
        "migrate one import in src/cli.py to the new module path",
        "standard",
    ),
    ComplexityPrecisionCase(
        "add-a-comment",
        "A comment request never scores deep",
        "add a comment explaining why this branch exists",
        "light",
    ),
    ComplexityPrecisionCase(
        "print-a-value",
        "A print/debug-line request never scores deep",
        "print the resolved config path at startup",
        "light",
    ),
    ComplexityPrecisionCase(
        "two-files-simple",
        "Two named files alone do not reach deep",
        "update the copyright year in src/a.py and src/b.py",
        "standard",
    ),
    ComplexityPrecisionCase(
        "long-but-simple",
        "A long request that is still a one-liner stays light",
        (
            "quick question, and sorry for the wall of text: I was reading through the installer "
            "yesterday and noticed that the help string for the scope flag reads a little oddly to me, "
            "it says 'scope' twice in a row which I think is just a copy-paste slip, so if you agree "
            "could you fix the spelling there? that is the whole ask, nothing else needs to change and "
            "I do not need any tests for it, it is a single line and I just kept typing to explain."
        ),
        "standard",
    ),
    ComplexityPrecisionCase(
        "enumerated-trivia",
        "An enumerated list of trivial edits stays light despite the step count",
        "1. fix the typo in the help text\n2. bump the version\n3. rename the flag",
        "light",
    ),
    ComplexityPrecisionCase(
        "routed-coding-skill-alone",
        "Routing to a coding skill alone does not make a small request deep",
        "rename the flag in src/commands/coding.py",
        "standard",
        routed_skill="code-review",
    ),
)


# Positive interventions. Each names the signals it expects to fire, so a case
# that passes for the wrong reason is still a failure.
COMPLEXITY_INTERVENTION_CASES: tuple[ComplexityInterventionCase, ...] = (
    ComplexityInterventionCase(
        "exhaustive-reference-search",
        "Finding every reference with exact locations reaches standard on its own",
        "Find every reference to RouteDecision, excluding comments and strings, and return exact locations as path, line, kind.",
        "standard",
        ("exhaustive_search",),
    ),
    ComplexityInterventionCase(
        "exhaustive-predicate-search",
        "Finding every function matching a predicate reaches standard on its own",
        "Find every function that converts a provider failure to a fallback result and return exact locations.",
        "standard",
        ("exhaustive_search",),
    ),
    ComplexityInterventionCase(
        "auth-rearchitecture",
        "A cross-service auth rearchitecture reaches deep",
        (
            "Refactor the authentication layer across every service, migrate the session schema, "
            "and keep backwards compatibility for existing tokens."
        ),
        "deep",
        ("architecture_keywords", "impact_system_wide", "risk_keywords"),
    ),
    ComplexityInterventionCase(
        "race-condition-investigation",
        "A multi-file race-condition investigation reaches deep",
        (
            "Investigate the intermittent race condition in the dispatcher: reproduce it, find the "
            "root cause, then fix src/coding/fanout_dispatch.py and src/coding/fanout_reap.py."
        ),
        "deep",
        ("risk_keywords", "debugging_keywords", "cross_file"),
        routed_skill="build-failure-triage",
    ),
    # Deliberately stops at `standard`. Two heavy-scope signals are six points
    # and the deep bound is eight, so scope-and-shape alone never buys the top
    # tier: deep needs a third independent reason (risk, cross-file span, an
    # enumerated plan, a heavy routed skill). Recorded as a case rather than a
    # comment because it is the boundary most likely to be tuned by accident.
    ComplexityInterventionCase(
        "system-wide-rewrite",
        "A system-wide rewrite reaches standard; deep still needs a third signal",
        "Rewrite the error handling system-wide so every caller reports a typed failure instead of a bare string.",
        "standard",
        ("architecture_keywords", "impact_system_wide"),
    ),
    ComplexityInterventionCase(
        "parallel-split",
        "An explicit parallel split reaches at least standard",
        "Split the work up and run the migration in parallel across the four packages.",
        "standard",
        ("architecture_keywords", "fanout_intent"),
    ),
    ComplexityInterventionCase(
        "enumerated-plan",
        "Three or more enumerated steps reach at least standard",
        (
            "Please do the following:\n"
            "1. add the new flag to the parser\n"
            "2. thread it into the payload builder\n"
            "3. cover it with a unit test\n"
            "4. update the help text"
        ),
        "standard",
        ("subtasks_many",),
    ),
    ComplexityInterventionCase(
        "concurrency-redesign",
        "A concurrency redesign reaches deep",
        (
            "Redesign the worker pool to remove the deadlock: the current thread safety story is wrong "
            "and we risk data loss on shutdown across the whole codebase."
        ),
        "deep",
        ("architecture_keywords", "impact_system_wide", "risk_keywords"),
    ),
    ComplexityInterventionCase(
        "coding-skill-heavy",
        "A heavy request routed to a coding skill reaches deep",
        "Refactor the dispatch layer end-to-end and prove the rollback path still works.",
        "deep",
        ("architecture_keywords", "impact_system_wide", "risk_keywords", "routed_skill_class"),
        routed_skill="maestro",
    ),
)


def complexity_precision_report() -> dict[str, object]:
    """Run both corpora and report the two failure metrics with their offenders."""
    tier_index = {tier: index for index, tier in enumerate(COMPLEXITY_TIERS)}

    overscored: list[dict[str, object]] = []
    for case in COMPLEXITY_PRECISION_CASES:
        result = score_request_complexity(case.message, routed_skill=case.routed_skill)
        if tier_index[str(result["tier"])] > tier_index[case.max_tier]:
            overscored.append({"id": case.id, "tier": result["tier"], "max_tier": case.max_tier, "score": result["score"]})

    missed: list[dict[str, object]] = []
    for case in COMPLEXITY_INTERVENTION_CASES:
        result = score_request_complexity(case.message, routed_skill=case.routed_skill)
        fired = {str(signal["name"]) for signal in result["signals"]}
        missing = sorted(set(case.expected_signals) - fired)
        if tier_index[str(result["tier"])] < tier_index[case.min_tier] or missing:
            missed.append(
                {
                    "id": case.id,
                    "tier": result["tier"],
                    "min_tier": case.min_tier,
                    "score": result["score"],
                    "missing_signals": missing,
                }
            )

    return {
        "schema_version": COMPLEXITY_PRECISION_SCHEMA_VERSION,
        "precision_case_count": len(COMPLEXITY_PRECISION_CASES),
        "intervention_case_count": len(COMPLEXITY_INTERVENTION_CASES),
        "overscore_count": len(overscored),
        "overscored": overscored,
        "missed_escalation_count": len(missed),
        "missed_escalations": missed,
    }
