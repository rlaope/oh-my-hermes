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
        "src/coding/fanout_dispatch.py",
        "spawn",
        INTENTIONAL,
        "An interruption after entering the pinned-binary context must close that context "
        "before the process is returned. The handler performs only that ownership cleanup, "
        "then immediately re-raises the original exception without relabeling it.",
    ),
    ClassifiedSite(
        "src/coding/fanout_git_promotion.py",
        "promote_fanout_git_metadata",
        INTENTIONAL,
        "Any interruption after the linked index transaction starts must run the bounded "
        "recovery transaction. Known boundary and cancellation failures are re-raised; an "
        "unexpected failure is surfaced as GitMetadataBoundaryError and never as success.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/engagement_nudges.py",
        "observe_engagement_outcome",
        INTENTIONAL,
        "A best-effort outcome observer must not abort the shared post-tool hook. "
        "Failures increment the metadata-only observer_error:<type> diagnostic "
        "and return no observation; they never fabricate a successful effect.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/memory_provider.py",
        "_say",
        INTENTIONAL,
        "The host's status callback prints one line for the user; it is Hermes' code, not "
        "OMH's, and it runs inside a live memory hook (session end, memory write). A "
        "callback that raises -- a closed terminal, a torn-down gateway adapter -- must "
        "not fail the hook that was recording consolidation state; the line is dropped and "
        "nothing else changes. The failure is classified by where it happens (host channel) "
        "and surfaced nowhere because there is no channel left to surface it on.",
    ),
    ClassifiedSite(
        "src/coding/fanout_dispatch.py",
        "signal_safe_unit_runner",
        INTENTIONAL,
        "A raising on_spawn hook must not leak the process group it was just handed: the "
        "handler terminates the group it created, then immediately re-raises the same "
        "exception so the caller still sees the hook's failure. Nothing is swallowed or "
        "relabeled; the broad catch exists only so no exception type can leave a live "
        "orphan behind.",
    ),
    ClassifiedSite(
        "src/coding/fanout_dispatch.py",
        "_snapshot_output",
        INTENTIONAL,
        "The mid-run stdout snapshot hook is telemetry-only narration for a unit's HUD row: a "
        "raising hook must never kill or time out the unit it observes, so the handler returns "
        "and the poll loop keeps waiting on the process. Nothing is relabeled — no count is "
        "reported for that snapshot (an absent count, never a zero), the next poll retries, and "
        "the terminal close still parses the full stdout independently of every snapshot.",
    ),
    ClassifiedSite(
        'src/coding/fanout_dispatch.py',
        'dispatch_fanout',
        INTENTIONAL,
        'Reaps owned children, preserves completed siblings and bounded failure metadata, '
        + 'writes the batch summary, and re-raises the original dispatcher exception.',
    ),
    ClassifiedSite(
        'src/coding/fanout_dispatch.py',
        'drain',
        INTENTIONAL,
        'A binary stream observer fault terminates the invocation-owned process group, '
        + 'then the waiting caller re-raises the same exception after joining both readers.',
    ),
    ClassifiedSite(
        'src/coding/fanout_dispatch.py',
        '_dispatch_unit',
        INTENTIONAL,
        'A runner observer error is recorded as a bounded dispatcher failure, never '
        + 'worker success, and the original exception is re-raised after cleanup.',
    ),
    ClassifiedSite(
        "src/coding/diagnostic_execution_engine.py",
        "_observe",
        INTENTIONAL,
        "The handler catches every interruption only to publish that exact exception to the "
        "same-key single-flight Future before immediately re-raising it. The owner and every "
        "waiter therefore observe the same loud programming failure instead of a deadlock or "
        "a relabeled diagnostic result.",
    ),
    ClassifiedSite(
        "src/coding/local_diagnostic_process_owner.py",
        "start_owned_process",
        INTENTIONAL,
        "A Windows provider is created suspended before Job Object attachment. Any interruption "
        "during attachment must kill and reap that not-yet-returned process before immediately "
        "re-raising the same BaseException; otherwise cancellation could leak a suspended child. "
        "Nothing is swallowed or relabeled.",
    ),
    ClassifiedSite(
        "src/coding/paired_run_execution.py",
        "_execute_cell",
        INTENTIONAL,
        "Two injected-boundary handlers in one function, classified together. An unexpected "
        "runner failure becomes the cell's explicit CRASHED state and still reaches its cleaner; "
        "an unexpected cleaner failure becomes CLEANUP_FAILED with cleanup_succeeded=False. "
        "Neither can become a successful receipt or silently abort sibling-cell cleanup. Both "
        "record the exception's type and a sanitized message on the cell, so the contained "
        "failure is readable at the fan-in boundary instead of only classified there.",
    ),
    ClassifiedSite(
        "src/workflows/domain_intelligence_store_security.py",
        "_open_store_lock_descriptor",
        INTENTIONAL,
        "The portable no-O_NOFOLLOW fallback closes the opened lock descriptor after any "
        "interruption during metadata and identity validation, then immediately re-raises the "
        "same BaseException so cancellation cannot become a successful lock acquisition. A "
        "safely created regular lock remains as the stable synchronization inode.",
    ),
    ClassifiedSite(
        "src/workflows/project_terms_capture.py",
        "_write_candidate_batch",
        INTENTIONAL,
        "Two handlers in one function, classified together. The outer handler catches any "
        "interruption after the durable batch journal is written, invokes idempotent recovery, "
        "and always re-raises the original interruption. The inner handler catches an "
        "interruption of that recovery attempt, attaches its type and message as a note to the "
        "original interruption, leaves the durable journal for the next locked reader or "
        "writer, and then lets the outer handler re-raise the original interruption.",
    ),
    ClassifiedSite(
        "src/quality/cross_harness_adapter_io.py",
        "_open_directory",
        INTENTIONAL,
        "Closes the directory descriptor for every interruption, then immediately re-raises "
        "the same BaseException so cancellation cannot be mistaken for successful traversal.",
    ),
    ClassifiedSite(
        "src/install/plugin_pack.py",
        "_register_smoke",
        INTENTIONAL,
        "Returns import_smoke=False, register_smoke=False and an `error` string carrying the "
        "exception text, so a failed smoke run is never readable as a passing one.",
    ),
    ClassifiedSite(
        "src/install/plugin_pack.py",
        "_enforcement_smoke",
        INTENTIONAL,
        "Returns enforcement_status='unknown' with the exception text in enforcement_detail, a "
        "third outcome distinct from both 'enforced' and 'no_decision', so a probe that could "
        "not run is never readable as a plugin that enforced.",
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
        "The activity fast path and the enclosing status/HUD projection both append "
        "`runtime_status_read` plus a sanitized error type before returning a bounded "
        "`omh_degradation` block. A genuinely idle host still returns None, while either "
        "projection failing remains distinguishable from absence.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/host_observation.py",
        "_record_observation",
        INTENTIONAL,
        "Already carries the #637 split: ImportError/ModuleNotFoundError takes the standalone "
        "path, any other exception returns `_observation_error(...)` with the error text.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/hooks/tool_hooks.py",
        "_rule_directive_or_recorded_fault",
        INTENTIONAL,
        "The point of the handler is the exception the rules module did not anticipate: a "
        "narrower tuple would re-raise exactly that type, and the escape is an unreported "
        "allow, because the host logs one WARNING and then DEBUG only. The failure is not "
        "relabeled as a normal result -- it is counted in the rule-gate fault record with "
        "the exception's own type and text, and `omh doctor` reports it under "
        "`toolcall_rule_gate`, naming the last error and saying the call was allowed. "
        "Allowing rather than blocking is the module's documented fail-open contract; this "
        "verdict is about the breadth, and the breadth is what makes the report complete.",
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
        "Returns the distinct `bundle_memory_error` source plus a sanitized error type. The "
        "alternative is an empty comparison, which would read as `Hermes remembers nothing` when "
        "the truth is that OMH could not read the file.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/memory_tool.py",
        "_consolidation",
        INTENTIONAL,
        "Returns the distinct `bundle_memory_error` source plus a sanitized error type. Reporting "
        "`due: false` instead would say consolidation is not needed when the truth is that OMH "
        "could not work out whether it was.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/recommend_tool.py",
        "_recommendations",
        INTENTIONAL,
        "Fixed by #637: returns the distinct `package_recommend_error` source plus a sanitized "
        "error type instead of `standalone_plugin_bundle_fallback`.",
    ),
    ClassifiedSite(
        "src/workflows/memory_store.py",
        "_resume_unlocked",
        INTENTIONAL,
        "Two handlers in one function, classified together. Defensive recovery boundaries: catch "
        "all unexpected failures, persist the interrupted or failed operation state and "
        "re-raise, so callers never read a crashed resume as a completed memory operation.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/approval_bypass.py",
        "record_approval_bypass",
        INTENTIONAL,
        "Host-surface probe boundary: importing or calling tools.approval can fail in any "
        "host-specific way (unit tests, a stripped embed, an older Hermes), and the hook that "
        "feeds the model must never break for an optional HUD observation. The handler records "
        "nothing, so an absent surface reads as an idle ledger, never as an observed state.",
    ),
    ClassifiedSite(
        "src/commands/docs.py",
        "cmd_docs_skill_lint",
        INTENTIONAL,
        "Exit-code boundary for `omh docs skill-lint`. The command's contract is 0 pass, 1 "
        "violations, 2 invocation or internal error. An escaping exception would exit 1 and "
        "become indistinguishable from a real structural verdict, so the handler classifies the "
        "failure as status=internal_error with the exception type on stderr and returns 2. The "
        "failure is never relabeled as a pass or a violation, and stdout stays empty.",
    ),
    ClassifiedSite(
        "src/workflows/browser_skill_promotion_native_probe.py",
        "main",
        INTENTIONAL,
        "The fixed native-host subprocess boundary emits a closed unavailable result with "
        "the exception type. The parent refuses admission on that result; an unexpected "
        "Hermes SDK failure cannot become trust, a clean scan, or write approval.",
    ),
    ClassifiedSite(
        "src/workflows/browser_skill_promotion_native_probe.py",
        "_config_snapshot",
        INTENTIONAL,
        "A failing native YAML loader or filesystem snapshot returns an invalid snapshot "
        "sentinel. Its caller marks the complete native policy unavailable. Missing files "
        "are handled separately before this function, so parse/read failure never becomes "
        "a missing optional config or a not-required write policy.",
    ),
    ClassifiedSite(
        "src/workflows/web_qa_comparison.py",
        "_canary_requirements",
        INTENTIONAL,
        "The explicitly injected deployment resolver may fail with host-specific exceptions. "
        "The handler adds canary_deployment_resolver_failed and returns no observation; "
        "comparison stays BLOCK and cannot grant deployment or rollback authority.",
    ),
    ClassifiedSite(
        "src/workflows/web_qa_observation_store.py",
        "_commit",
        INTENTIONAL,
        "Any failure during private staging, publication, or capture readback triggers "
        "cleanup of this invocation's new directories, then re-raises the original failure. "
        "It never returns a completed import or hides a failed image verification as success.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/engagement_nudges.py",
        "annotate_engagement_nudge",
        INTENTIONAL,
        "Hermes wraps this seam in its own `except Exception` and logs at debug "
        "(`model_tools._apply_transform_tool_result_hook`), so a raise here disappears "
        "instead of failing loudly -- the exact silence #637 is about. The handler records "
        "the failure by type in the decline tally `engagement_nudge_declines()` reads, so a "
        "broken nudge is distinguishable from a session that had nothing to say, and returns "
        "None, which the seam contract defines as 'leave the tool result alone' rather than "
        "as a delivered nudge.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/remote_wait_nudge.py",
        "annotate_remote_wait",
        INTENTIONAL,
        "The same seam and the same swallow as `annotate_engagement_nudge`: Hermes wraps "
        "`transform_tool_result` in its own `except Exception` and logs at debug, so a raise "
        "here disappears rather than failing loudly. The handler records the failure by type "
        "in the decline tally `remote_wait_declines()` reads, and returns None, which the "
        "seam contract defines as 'leave the tool result alone'. It cannot turn an unarmed "
        "wait into an armed one either: the armed check is a separate function with narrow "
        "handlers whose unreadable-record answer is None, and None declines instead of "
        "accusing a session that may well be watching something.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/hooks/session_hooks.py",
        "subagent_start",
        INTENTIONAL,
        "An observer the host already invokes inside its own quiet block "
        "(`tools/delegate_tool.py`), so a raise is swallowed there and would only stop a "
        "child being recorded; failing to record one child must not interrupt that child's "
        "spawn. The failure is surfaced by a positive record, not by an absence: the handler "
        "calls `engagement_nudges.record_engagement_observer_failure`, which tallies "
        "`observer_error:<Type>` in the same readout every other decline on this path uses. "
        "Without that the only evidence would be a `delegated_session` decline that never "
        "happens, which cancels against the failure that caused it and leaves no trace.",
    ),
)

# Ruff reports one hit per handler; the inventory is keyed per enclosing
# function. `_write_candidate_batch`, `_is_catalog_question`, `pre_llm_call`,
# `_resume_unlocked`, and `_execute_cell` each hold two handlers, so the handler
# count is five above the anchor count.
EXPECTED_HANDLER_COUNT = 44
EXPECTED_ANCHOR_COUNT = 39


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
