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
        "src/workflows/repro_audit/operations.py", "_publish", INTENTIONAL,
        "Exclusive publication rolls back only invocation-owned staged files and re-raises the original failure; it never relabels a failed audit as success.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/dashboard/plugin_api.py",
        "hud_payload",
        INTENTIONAL,
        "A reader failure inside the Hermes gateway becomes a record with `error` naming the "
        "exception class and message under `omh_desktop_hud/v1`, and no `display` key; the pane "
        "renders that record as a reader error, so it is never mistaken for a HUD payload; the "
        "route answers 200 because in the pane a thrown error is indistinguishable from a transport "
        "failure, and the record is what lets it say which one happened.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/jev_ask_client.py",
        "send_ask",
        INTENTIONAL,
        "A transport failure urllib does not name (an http.client error the bridge may not import) "
        "becomes the named network_error status with ok false and answers null; it is never an "
        "answer, and the caller sees retryable true.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/jev_ask_store.py",
        "route_available",
        INTENTIONAL,
        "The check_fn availability probe fails closed to route none, which hides omh_jev_ask; a host "
        "reader error can only remove the tool, never enable a send.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/team_tool.py",
        "_host_floor",
        INTENTIONAL,
        "Hermes' own command floor raising is not a yes: the team command is refused with the named "
        "reason host_command_floor_unavailable, so a check is never run past a floor that failed.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/jev_ask_tool.py",
        "jev_ask_available",
        INTENTIONAL,
        "An unbound OMH home at check time hides omh_jev_ask rather than failing the host's tool "
        "registry probe; the tool stays unavailable, which is the safe side.",
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
        "src/plugin_bundle/omh/__init__.py",
        "_section_already_registered",
        INTENTIONAL,
        "A pre-check before registering the awareness section: building the memory-provider "
        "collector's plugin context must not abort `register()`, which would fail the whole "
        "plugin load. On failure the check answers 'not registered' and the registration "
        "proceeds; the collector's forward builds the same context, fails the same way, and "
        "Hermes logs it on its warning channel, so the failure is surfaced, not relabeled.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/memory_provider.py",
        "_demotion_rows",
        INTENTIONAL,
        "Runs inside a live memory hook while a brief is being written. A fault is counted and "
        "recorded as op `demotion_rows` with its error class in the write failures the next receipt "
        "reports, and the brief goes out without rows, so the model is asked to demote nothing "
        "rather than losing the whole consolidation request.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/memory_provider.py",
        "_guard_digest",
        INTENTIONAL,
        "The session digest is read inside `initialize`, a session switch and every pack render. "
        "Whatever its stores hold, a fault costs only the digest: it is counted and recorded as op "
        "`session_digest` with its error class in the write failures the next receipt reports, and "
        "the session gets no digest rather than a failed hook or a blank pack.",
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
        "src/coding/fanout_confinement.py",
        "_git_write_roots",
        INTENTIONAL,
        "Deciding which git paths a unit may write is fail-closed: any error while reading the "
        "worktree layout (git missing or timing out, an unreadable file, an unexpected layout) "
        "returns no git write root, so the unit stays sandboxed and simply cannot commit. The "
        "reason is recorded as `git_error` in the bounded skip map the receipt reports, so the "
        "failure is visible rather than relabeled, and no exception can reach the caller and make "
        "it fall back to an unconfined run.",
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
        "_capture",
        INTENTIONAL,
        "Memory admission runs in-process inside Hermes' tool dispatch; a fault becomes status "
        "`error` with the sanitized exception class as `reason` and `receipt_state` null, never a "
        "status that says something was saved, and never a raise into the host.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/memory_tool.py",
        "_demote",
        INTENTIONAL,
        "Reading Hermes memory and capturing the entry run in-process inside Hermes' tool dispatch; "
        "a fault becomes status `error` with the sanitized exception class as `reason` and no "
        "`remove_from_hermes`, so the model is never told to delete an entry whose copy is unconfirmed.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/memory_tool.py",
        "_lifecycle",
        INTENTIONAL,
        "recall, confirm, correct and retire read and write OMH's store in-process inside Hermes' "
        "tool dispatch; a fault becomes status `error` with the sanitized exception class as "
        "`reason` and no `display_line`, never a status that says a record was confirmed, "
        "corrected or retired, and never a raise into the host.",
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
        "src/plugin_bundle/omh/tools/recommend_tool.py",
        "_route_summary",
        INTENTIONAL,
        "The `route` key is additive beside a ranking that already computed: a chat import or "
        "decision failure returns `route: None` -- the same value the standalone fallback "
        "reports -- and never empties `recommendations` or relabels the source.",
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
        "src/commands/coding.py",
        "cmd_coding_fanout_status",
        INTENTIONAL,
        "Exit-code boundary for `omh coding fanout status --wait`, whose codes are answers about "
        "the work: 0 every unit verified, 1 one unit terminal and not verified, 3 stuck, 65 "
        "journal unreadable, 124 deadline. An escaping exception would exit 1 and read as a unit "
        "that failed, so with --wait the handler prints the traceback to stderr and returns 70, "
        "a code no answer uses; stdout stays empty. An OmhError is re-raised ahead of it and stays "
        "`main`'s exit 2, and a single read re-raises, so its crash stays Python's own. The "
        "failure is never relabeled as a roster or a verdict.",
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
        "src/plugin_bundle/omh/hooks/result_transforms.py",
        "_delegation_snapshot",
        INTENTIONAL,
        "The delegation snapshot runs on `transform_llm_output` beside the honest stop, in OMH's one "
        "handler for that hook; Hermes swallows a raise from it (`agent/turn_finalizer.py::"
        "_invoke_hook_safely`), which would also drop the honest stop. The failure is counted by "
        "type in `snapshot_failures` and the reply goes out with no block, never with a wrong one.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/remote_wait_nudge.py",
        "honest_stop_output",
        INTENTIONAL,
        "The end-of-turn half of `annotate_remote_wait`, on `transform_llm_output`, which "
        "the host also runs inside its own swallow (`agent/turn_finalizer.py::"
        "_invoke_hook_safely`), so a raise would vanish. The handler records the failure by "
        "type in the same decline tally `remote_wait_declines()` reads and returns None, "
        "which the seam contract defines as 'leave the response alone'. It cannot "
        "manufacture the sentence: that is returned only from the success path, after the "
        "per-turn latch and a readable process record showing nothing armed.",
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
    ClassifiedSite(
        "src/plugin_bundle/omh/package_backend.py",
        "load_backend",
        INTENTIONAL,
        "A native tool's import of its `omh` package backend. Every failure becomes a "
        "`package_backend` block whose status is `absent`, `incompatible` or `broken` and whose "
        "`error_type` names the exception class; `omh_loop` and `omh_decision_gate` return it inside "
        "a refusal that wrote nothing and `omh_probe` reports it as its own row, so a skewed "
        "install is never mistaken for a working backend or for the supported no-package host, "
        "and a module-scope RuntimeError never raises out of a tool (#2166).",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/package_backend.py",
        "_found_omh",
        INTENTIONAL,
        "The presence check runs inside `load_backend`'s own handler, so a raise from an import "
        "hook asked for the name `omh` would escape the tool. It answers `other`, which makes "
        "the block read `broken` with the original import's class in `error_type`: never "
        "`absent`, never a working backend, and never a raise (#2166 follow-up).",
    ),
    ClassifiedSite(
        "src/tui/bot_board.py",
        "poll_once",
        INTENTIONAL,
        "The bot board's reading thread runs the board's readers, which catch the file and SQLite errors "
        "they expect. Any other failure becomes a snapshot with no profiles and a `problem` naming the "
        "exception class, which the board draws as `the board could not be read: <class>` in the warning "
        "colour, so it is never mistaken for a machine without bots; catching it keeps the thread alive "
        "and keeps a traceback from being printed over the board.",
    ),
    ClassifiedSite(
        "src/tui/panels.py",
        "_read",
        INTENTIONAL,
        "The OMH TUI's HUD poll thread calls `read_omh_hud` in process. A reader failure becomes a "
        "payload carrying only `error` (the exception class name) and no `privacy` or `display` "
        "keys, which `panel_lines` renders as a one-line `OMH HUD unavailable: <class>` notice, so it "
        "is never mistaken for an empty or healthy HUD; catching it here is what keeps the thread "
        "alive and keeps a traceback from being printed over the TUI's own screen.",
    ),
    ClassifiedSite(
        "src/tui/panels.py",
        "_run",
        INTENTIONAL,
        "The HUD poll thread's loop: a read that raises past every reader's own guard (a "
        "PermissionError from a state.db probe, say) becomes `_read_failed`, a snapshot whose payload "
        "is only `error` (drawn as `OMH HUD unavailable: <class>`) and whose background processes are "
        "the ones last read with `refreshes` 0, so the failure is shown, never read as the processes' "
        "end, and the thread reads again instead of dying for the rest of the session.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/host_process.py",
        "this_process",
        INTENTIONAL,
        "Two handlers. A failing import of Hermes' `gateway.status` (not only ImportError, as "
        "Hermes' own `_persist_dispatch` guards it) records no process, the path a record from "
        "before this change takes: `omh_team` keeps the part out under its four-hour bound, and "
        "`omh_dag` keeps the node running with no bound, as on main. Hermes' start-time reader raising "
        "records the process with `started` None, the shape its own async-delegation record keeps "
        "for an unread time; `process_alive` then answers None (unknown) while that pid exists and "
        "False (gone) once it does not, never True. Either way the `subagent_start` observers that "
        "call it keep their promise never to raise, and binding the helper is never lost to it.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/host_process.py",
        "process_alive",
        INTENTIONAL,
        "Two handlers. A failing import of the probes, or a probe that raised, answers None, which "
        "callers keep apart from False (gone) and True: `omh_team` keeps the part out under its "
        "four-hour bound and `omh_dag` keeps the node running, exactly as with no process "
        "recorded. Only a probe's own answer that the process ended hands work out again, so a "
        "raise never re-runs a live helper.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/dag_tool.py",
        "terminal_backend",
        INTENTIONAL,
        "Hermes' terminal resolver failing to import or raising (a bad TERMINAL_* value) falls back "
        "to TERMINAL_ENV, the variable it reads; a backend not named docker or ssh records nothing, "
        "so the run keeps the host's handoff check exactly as before. Define never fails on it.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/dag_tool.py",
        "_backend_lines",
        INTENTIONAL,
        "Two handlers. Hermes' environment registry failing to import or raising is `no_read_path`, "
        "and the backend's execute raising is `backend_unanswered`; neither yields a line. At settle "
        "that is never read as a handoff that exists or one that is missing: the node is accepted with "
        "handoff_checked false and that reason on the attempt, its row and its say, and every view "
        "shows `handoff not checked`. At the first hand-out it keeps this host's handoff path for the "
        "run, as before the backend was read.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/search_tool.py",
        "omh_search_handler",
        INTENTIONAL,
        "Unexpected failures from the delegated search backend become the distinct "
        "`package_backend_error` result, separate from successful `result` output and the "
        "`backend_unavailable` optional-dependency path. The handler exposes only that fixed "
        "classification, never the exception message or raw backend body, so failure is surfaced "
        "without leaking search content.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/dag_tool.py",
        "_single_query_session",
        INTENTIONAL,
        "Hermes' optional `agent.oneshot_footprint` detector is imported and called at define time. Only "
        "ModuleNotFoundError during import naming exactly `agent` or `agent.oneshot_footprint` is the "
        "documented absent path (no cap). A missing unrelated dependency during import, or any callable "
        "or truth-conversion failure including ModuleNotFoundError, is refused with the named reason "
        "`oneshot_detection_unavailable` and actionable text; the raw exception is suppressed. These "
        "failures are never answered `False`, which would silently disable the one-shot child budget.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/lsp_bridge.py",
        "available",
        INTENTIONAL,
        "Hermes' LSP service failing to import or construct is answered `(None, \"lsp_unavailable: cannot load "
        "Hermes LSP (<exception class>)\")`; every lsp_* handler returns that as error `lsp_unavailable` with the "
        "class in the hint, never a location list or an applied rename.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/lsp_bridge.py",
        "in_git_worktree",
        INTENTIONAL,
        "Hermes' workspace resolver raising is answered not gated, so the handler refuses with error "
        "`no_workspace` before any request or write; a resolver failure can only refuse a call, never run one "
        "outside the worktree Hermes would gate in.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/lsp_bridge.py",
        "_language_id",
        INTENTIONAL,
        "Only the didOpen languageId label falls back (python for .py/.pyi, else plaintext, the same answer "
        "Hermes' `language_id_for` gives a .py file); the server was already chosen by path through "
        "`enabled_for`/`_get_or_spawn`, and a server that cannot use the label fails the request, which "
        "`request` reports as `server_unavailable`.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/lsp_bridge.py",
        "request",
        INTENTIONAL,
        "Any failure driving Hermes' private LSP loop or client becomes BridgeError `server_unavailable` naming "
        "the exception class; the handler answers it as `ok: false` with that code, separate from `timeout`, "
        "`lsp_unavailable` and a real (possibly empty, `no_result`) server answer.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/lsp_bridge.py",
        "notify_changed",
        INTENTIONAL,
        "Runs after the rename is already on disk: the result truthfully says applied with the files written. "
        "A failed re-sync only leaves the server's copy stale until the next lsp_* call re-opens the files it "
        "uses (from disk, or from the snapshot a rename later proves against the disk bytes), so it never "
        "turns a failed write into success or lets a stale copy reach disk (`stale_file`).",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/lsp_nav.py",
        "_write_atomic",
        INTENTIONAL,
        "Cleanup only: removes its own temp file and re-raises the original exception, which the rename "
        "handler reports as an error; it never relabels a failed write as written.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/lsp_nav_tool.py",
        "_lsp_tools_enabled",
        INTENTIONAL,
        "The check_fn reading the profile's lsp_tools setting fails closed: a config read error hides the "
        "opt-in omh-lsp tools, so a host reader failure can only remove them, never enable them.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/lsp_nav_tool.py",
        "_workspace_root",
        INTENTIONAL,
        "Hermes' private `_resolve_base_dir` absent or raising falls back to TERMINAL_CWD and then the process "
        "cwd, the same roots Hermes' file tools fall back to. Every path stays confined to that root "
        "(`scope_mismatch` otherwise), results are root-relative, and a miss names the root it used, so the "
        "fallback is visible and cannot widen what a call may read or write.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/lsp_nav_tool.py",
        "_navigate",
        INTENTIONAL,
        "Handlers must not raise into the host: an unexpected failure is `ok: false`, error "
        "`unexpected_error` with the exception class, never a location list or `no_result`.",
    ),
    ClassifiedSite(
        "src/plugin_bundle/omh/tools/lsp_nav_tool.py",
        "lsp_rename_handler",
        INTENTIONAL,
        "Handlers must not raise into the host: an unexpected failure is `ok: false`, error "
        "`unexpected_error` with the exception class, never `applied: true`; every new text is planned and "
        "checked against the synced bytes before the first write.",
    ),
)

# Ruff reports one hit per handler; the inventory is keyed per enclosing
# function. `_write_candidate_batch`, `_is_catalog_question`, `pre_llm_call`,
# `_resume_unlocked`, `_execute_cell`, `host_process.this_process`,
# `host_process.process_alive` and `dag_tool._backend_lines` each hold two
# handlers, so the handler count is eight above the anchor count.
# 45 -> 46 / 50 -> 51: `recommend_tool._route_summary`, the additive route beside
# the ranking (#2005 review: a route failure must not empty the ranking or
# relabel the source).
# 47 -> 49 / 52 -> 54: `memory_tool._demote`, the model's L1 -> L2 move (a fault
# is status `error` and never carries the native remove), and
# `memory_provider._demotion_rows` (a fault costs the brief's demote rows, is
# recorded as a write failure, and never costs the brief).
# 49 -> 50 / 54 -> 55: `memory_tool._lifecycle`, the model's recall, confirm,
# correct and retire (a fault is status `error`, never a status that says the
# record changed, and never a display_line).
# 50 -> 51 / 55 -> 56: `memory_provider._guard_digest`, the session digest (a
# fault costs the digest, is recorded as a write failure, and never fails
# initialize, a switch, or a render).
# 51 -> 52 / 56 -> 57: `cmd_coding_fanout_status`, the `--wait` watcher's crash
# code (a crash exits 70 with its traceback, never 1, which means a unit did
# not verify).
# 57 -> 58 / 52 -> 53: `tui/panels._read`, the OMH TUI's in-process HUD poll (a
# reader failure is a visible notice, never an empty panel or a dead thread).
# 58 -> 59 / 53 -> 54: `package_backend.load_backend`, a native tool's backend
# import (a failure is a classified refusal or probe row, never a raise; #2166).
# 59 -> 60 / 54 -> 55: `package_backend._found_omh`, the presence check an
# import hook can make raise (it reads `broken`, never a raise out of a tool).
# 60 -> 61 / 55 -> 56: `result_transforms._delegation_snapshot`, the messenger
# block beside the honest stop (a failure is counted and the reply goes out
# without a block, never without the honest stop).
# 61 -> 63 / 56 -> 58: `host_process.this_process` and `process_alive`, Hermes'
# own liveness probes (a raise is an unread start time or an unknown answer,
# never "gone", so it never hands a live helper's work out again).
# 63 -> 65 / 58 -> 58: the same two functions guard Hermes' import against any
# failure, as Hermes' own call sites do (#2198 review L2).
# 65 -> 68 / 58 -> 60: `dag_tool.terminal_backend` and `_backend_lines`, a
# dag-ulw handoff read inside a Docker or SSH terminal (a failure keeps the host
# check at define, and at settle accepts with the handoff not checked, never
# a refusal and never a file taken as there).
# 68 -> 69 / 60 -> 61: `search_tool.omh_search_handler`, which classifies
# unexpected delegated search failures separately from success and optional
# backend absence, without returning raw backend content.
# 69 -> 70 / 61 -> 62: `dag_tool._single_query_session`, Hermes' optional
# one-shot detector at define time (an installed detector that fails is a named
# refusal, `oneshot_detection_unavailable`, never a healthy `False` that
# silently drops the child budget; #preflight review).
# 70 -> 71 / 62 -> 63: `bot_board.BoardReader.poll_once`, the bot board's reading
# thread, which draws an unexpected reader failure as a named warning row.
# 71 -> 72 / 63 -> 64: `repro_audit.operations._publish`, which rolls back
# only the staged files it owns and re-raises the original failure.
# 72 -> 82 / 64 -> 74: the opt-in omh-lsp tools (`lsp_bridge`, `lsp_nav`,
# `tools/lsp_nav_tool`), one handler per function: host-reader probes that fail
# closed, Hermes' LSP loop failures named `server_unavailable`, a temp-file
# cleanup that re-raises, and handlers that answer `unexpected_error`.
# 82 -> 83 / 74 -> 75: `tui/panels.HudPoller._run`, the HUD poll loop (a read
# that raises is a visible notice with the last processes kept, never a dead
# thread and never the processes' end; #2388 review).
EXPECTED_HANDLER_COUNT = 83
EXPECTED_ANCHOR_COUNT = 75


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
