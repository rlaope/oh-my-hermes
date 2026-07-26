"""Gate for the broad-exception (`BLE001`) policy recorded in `pyproject.toml`.

Ruff's `BLE001` (flake8-blind-except) is deliberately not in `select`. That
omission is a decision, not an oversight, and this module is where the decision
is kept honest.

The policy, as established by issue #637 / PR #641:

    A broad `except` is not itself the defect. Around a delegated call it is
    acceptable when the failure is classified and surfaced -- the handler
    produces a result the caller can tell apart from success and from the
    "optional dependency absent" path, or reports it on an error channel. It
    is a defect when the failure is relabeled as a normal result, so a runtime
    error inside a delegated call becomes indistinguishable from a healthy
    fallback.

`CLASSIFIED_SITES` below records that verdict for every broad `except` site in
`src/`, anchored by file plus enclosing function -- never by line number, which
drifts on unrelated edits. The tests re-derive the live site list from source
and fail when it stops matching, so a new broad `except` cannot land
unclassified and enabling `BLE001` later stays bounded work rather than an
open-ended audit.

Re-derive the same list with Ruff:

    uv run --group lint ruff check --select BLE001 src

`_broad_except_sites()` is intentionally at least as broad as `BLE001`: it
flags every handler catching `Exception` or `BaseException`, including one
carrying a `# noqa: BLE001`, because silencing the rule is exactly the case
that most needs a recorded verdict.

Policy owner: issue #652.
"""

from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
POLICY_TEST_PATH = "tests/test_broad_exception_policy.py"
REDERIVE_COMMAND = "uv run --group lint ruff check --select BLE001 src"
POLICY_OWNER_ISSUE = "#652"

BLIND_EXCEPTION_NAMES = frozenset({"Exception", "BaseException"})

# The failure is classified and surfaced: the caller can tell it apart from
# both success and the "optional dependency absent" path.
INTENTIONAL = "intentional_classified_failure"
# The failure is relabeled as a normal result. Same shape as the defect #637
# fixed; needs that treatment before `BLE001` can be enforced.
NEEDS_637_TREATMENT = "needs_637_treatment"

VERDICTS = frozenset({INTENTIONAL, NEEDS_637_TREATMENT})


class ClassifiedSite(NamedTuple):
    path: str
    function: str
    verdict: str
    rationale: str


CLASSIFIED_SITES: tuple[ClassifiedSite, ...] = (
    ClassifiedSite(
        "src/install/plugin_pack.py",
        "_register_smoke",
        INTENTIONAL,
        "Returns import_smoke=False, register_smoke=False and an `error` string carrying the "
        "exception text, so a failed smoke run is never readable as a passing one.",
    ),
    ClassifiedSite(
        "src/mcp/bridge.py",
        "run_stdio_mcp_server",
        INTENTIONAL,
        "Defensive stdio transport boundary: prints the exception to stderr and answers the "
        "JSON-RPC peer with -32603 Internal error instead of a result.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/awareness.py",
        "_localized_routing_text",
        INTENTIONAL,
        "Still returns the raw message, but appends `localized_routing_text` plus a sanitized "
        "error type to the `degraded` accumulator its caller passes in, which the "
        "`_prepare_routing_text is None` branch above deliberately does not. The signal reaches "
        "`omh_route_hint/v1.degradation`, `omh_context_brief/v1.degradation`, and the "
        "`pre_llm_call` return's `omh_degradation`.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/awareness.py",
        "_loop_route_hint_next_action",
        INTENTIONAL,
        "Still returns `default_action`, but appends `loop_route_hint_assessment` plus a "
        "sanitized error type to the caller's `degraded` accumulator, which the "
        "`_assess_loopability is None` branch does not. The signal surfaces at "
        "`omh_route_hint/v1.degradation` and merges upward to `omh_degradation`.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/context_brief.py",
        "_is_catalog_question",
        INTENTIONAL,
        "Two handlers in one function, treated differently on purpose. The import guard stays "
        "broad and deliberately emits nothing: a module that raises at import really is "
        "unusable, so `_standalone_catalog_question` is the accurate label and a host where "
        "`omh` is genuinely absent must stay indistinguishable from before. The second wraps "
        "the delegated `is_skill_catalog_question()` call and now appends "
        "`catalog_question_classifier` plus a sanitized error type to the caller's `degraded` "
        "accumulator, so the call failure is told apart from that absence path even on a "
        "non-catalog message that produces no `catalog_question` key.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/hooks/llm_hooks.py",
        "pre_llm_call",
        INTENTIONAL,
        "Still sets status={} and hud={}, but appends `runtime_status_read` plus a sanitized "
        "error type, so the return carries `omh_degradation` and one bounded `[OMH Degraded]` "
        "context line where a genuinely idle host still returns None. A failed status read is "
        "no longer readable as a host with nothing to report.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/host_observation.py",
        "_record_observation",
        INTENTIONAL,
        "Already carries the #637 split: ImportError/ModuleNotFoundError takes the standalone "
        "path, any other exception returns `_observation_error(...)` with the error text.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/chat_tool.py",
        "omh_interact_handler",
        INTENTIONAL,
        "Already carries the #637 split: ImportError/ModuleNotFoundError takes "
        "`_fallback_interaction`, any other exception takes `_backend_error_interaction` with the "
        "error type.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/context_tool.py",
        "_context_brief",
        INTENTIONAL,
        "Fixed by #637: returns `_package_context_error(...)` under the distinct "
        "`package_context_error` source instead of `standalone_plugin_bundle_fallback`.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/memory_tool.py",
        "_memory_bridge",
        INTENTIONAL,
        "Returns the distinct `package_memory_error` source plus a sanitized error type, so a "
        "package runtime failure never reads as `standalone_plugin_bundle_fallback` -- the label "
        "a host that genuinely lacks OMH would get.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/recommend_tool.py",
        "_recommendations",
        INTENTIONAL,
        "Fixed by #637: returns the distinct `package_recommend_error` source plus a sanitized "
        "error type instead of `standalone_plugin_bundle_fallback`.",
    ),
)

# Ruff reports one hit per handler; the inventory is keyed per enclosing
# function, and `_is_catalog_question` holds two handlers, so the two totals
# differ by exactly one.
EXPECTED_HANDLER_COUNT = 12
EXPECTED_ANCHOR_COUNT = 11


class DerivedSite(NamedTuple):
    path: str
    function: str


def _catches_blind_exception(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return False
    parts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(part, ast.Name) and part.id in BLIND_EXCEPTION_NAMES for part in parts)


def _enclosing_function(tree: ast.Module, lineno: int) -> str:
    innermost = ""
    innermost_start = -1
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= lineno <= end and node.lineno > innermost_start:
            innermost = node.name
            innermost_start = node.lineno
    return innermost or "<module>"


def _broad_except_sites() -> list[DerivedSite]:
    sites: list[DerivedSite] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _catches_blind_exception(node):
                relative = path.relative_to(REPO_ROOT).as_posix()
                sites.append(DerivedSite(relative, _enclosing_function(tree, node.lineno)))
    return sites


def _pyproject_text() -> str:
    return (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


class BroadExceptionPolicyTests(unittest.TestCase):
    def test_classified_inventory_covers_every_broad_except_site(self) -> None:
        derived = set(_broad_except_sites())
        classified = {DerivedSite(site.path, site.function) for site in CLASSIFIED_SITES}

        unclassified = sorted(derived - classified)
        stale = sorted(classified - derived)
        self.assertEqual(
            (unclassified, stale),
            ([], []),
            "Broad-exception inventory drifted from source. Re-derive with "
            f"`{REDERIVE_COMMAND}`, then update CLASSIFIED_SITES in {POLICY_TEST_PATH}: "
            f"add a verdict for {unclassified or 'nothing'}; drop the stale entries "
            f"{stale or 'nothing'}.",
        )

    def test_site_totals_match_the_recorded_counts(self) -> None:
        self.assertEqual(len(_broad_except_sites()), EXPECTED_HANDLER_COUNT)
        self.assertEqual(len(CLASSIFIED_SITES), EXPECTED_ANCHOR_COUNT)

    def test_every_site_carries_a_known_verdict_and_a_rationale(self) -> None:
        for site in CLASSIFIED_SITES:
            with self.subTest(path=site.path, function=site.function):
                self.assertIn(site.verdict, VERDICTS)
                self.assertGreater(
                    len(site.rationale.strip()),
                    40,
                    "Each verdict needs a rationale a reviewer can check against the source.",
                )

    def test_no_site_is_left_needing_the_637_treatment(self) -> None:
        outstanding = sorted(
            (site.path, site.function) for site in CLASSIFIED_SITES if site.verdict == NEEDS_637_TREATMENT
        )

        self.assertEqual(
            outstanding,
            [],
            "Every broad-exception site in `src/` was moved to the classified-and-surfaced "
            "verdict; this ratchet keeps it that way. If you are recording a genuine new defect "
            f"rather than regressing an existing one, that is a deliberate decision -- see {POLICY_TEST_PATH} "
            f"and policy owner {POLICY_OWNER_ISSUE}, then remove this test in the same commit "
            "with the reason in the commit body. Outstanding: "
            f"{outstanding}.",
        )

    def test_ble001_stays_unselected_under_the_pyflakes_baseline(self) -> None:
        config = tomllib.loads(_pyproject_text())
        select = config["tool"]["ruff"]["lint"]["select"]

        self.assertEqual(select, ["F"], "The baseline gate is Pyflakes-only; broadening it is separate work.")
        self.assertNotIn("BLE001", select)

    def test_recorded_policy_names_a_live_owner_and_the_rederive_command(self) -> None:
        # Issue #637 may still be cited as the precedent that established the
        # classified-versus-relabeled distinction, but it is closed and must not
        # be the tracking owner. The durable link is this module's path.
        for relative in ("pyproject.toml", "CLAUDE.md"):
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn(POLICY_OWNER_ISSUE, text)
                self.assertIn(POLICY_TEST_PATH, text)

        self.assertIn(REDERIVE_COMMAND, _pyproject_text())


if __name__ == "__main__":
    unittest.main()
