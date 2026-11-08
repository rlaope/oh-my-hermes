"""The coding-owner invariant and its provenance contract (plan §5.3, §11.3 PR A).

The one property this file gates: no card and no prepared handoff carries a
`selected_executor_profile` in `EXTERNAL_CLI_PROFILES` unless
`read_owner_preference(paths)` holds state written by an explicit-choice
writer — `record_accepted_explicit_choice` (the user answered the question) or
`record_in_message_explicit_naming` (the user named the CLI in their own
words). *Unresolved owner* means `executor_selection.choice_required is True`,
or `executor_selection.status == "executor_choice_required"`, or
`selected_executor_profile is None`. `dispatch_policy` appears nowhere in
these definitions: the genuine ask-state and a resolved external owner share
its value, so it discriminates nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.executors import EXTERNAL_CLI_PROFILES
from omh.paths import resolve_paths
from omh.quality.routing_precision import (
    ROUTING_INTERVENTION_CASES,
    ROUTING_PRECISION_CASES,
)
from omh.routing.owner_preference import (
    empty_owner_preference_state,
    explicit_choice_provenance,
    owner_preference_path,
    read_owner_preference,
    record_accepted_explicit_choice,
    record_in_message_explicit_naming,
    reset_owner_preference,
    validate_owner_preference,
    write_owner_preference,
)
from omh.wrapper.contract import build_chat_interaction_payload


ROUTE_FAMILY = "ulw-coding-delivery"
TS = "2026-08-13T00:00:01Z"
CODING_MESSAGE = "research, plan, implement, verify, and review this coding change in one cycle"

# The retired-engine session flows that used to resolve Codex from the message
# alone now surface the owner-selection path instead (#954 stage 5, plan Q9):
# these corpus rows must resolve NO unrecorded external owner. The
# naming-is-choosing carve-out (§5.3.1) still applies to ordinary named
# delivery requests, witnessed by IN_MESSAGE_NAMING_DELIVERY_MESSAGE below.
OWNER_SELECTION_WITNESS_IDS = (
    "korean-codex-issue-pr-start",
    "korean-codex-session-liveness",
    "korean-codex-current-activity-status",
)

# A named delivery request outside the legacy cue cluster: routing resolves
# Codex from the in-message naming and must record it as explicit-choice
# provenance through the in-message-naming writer.
IN_MESSAGE_NAMING_DELIVERY_MESSAGE = "use codex to fix the login bug"

# The paraphrase negative control: the witness request with the CLI name
# removed. It lives in ROUTING_PRECISION_CASES and must resolve no external
# owner and record nothing.
PARAPHRASE_CASE_ID = "korean-issue-pr-start-no-named-cli"
PARAPHRASE_MESSAGE = "이 이슈 PR 만들 수 있게 작업 시작해줘"

# `choice_required is True` occurs in the shipping corpus; naming one witness
# keeps the offer-not-dispatch criterion loudly non-vacuous if the ask-state
# ever leaves the corpus.
CHOICE_REQUIRED_WITNESS_ID = "one-cycle-delivery"


def _delegation(payload: Mapping[str, Any]) -> dict[str, Any]:
    delegation = payload.get("delegation")
    return delegation if isinstance(delegation, dict) else {}


def _selection(payload: Mapping[str, Any]) -> dict[str, Any]:
    selection = _delegation(payload).get("executor_selection")
    return selection if isinstance(selection, dict) else {}


def external_owner_violation(
    payload: Mapping[str, Any], state: Mapping[str, Any] | None
) -> bool:
    """True when an external CLI owner appears without explicit-choice provenance."""
    profile = _delegation(payload).get("selected_executor_profile")
    if profile not in EXTERNAL_CLI_PROFILES:
        return False
    decision = payload.get("coding_route_decision")
    family = ""
    if isinstance(decision, Mapping):
        family = str(decision.get("owner_preference_route_family") or "")
    return explicit_choice_provenance(state, route_family=family or ROUTE_FAMILY) == ""


def offer_not_dispatch_violation(payload: Mapping[str, Any]) -> bool:
    """True when offering the owner choice also resolved or dispatched it."""
    if _selection(payload).get("choice_required") is not True:
        return False
    delegation = _delegation(payload)
    return (
        delegation.get("selected_executor_profile") is not None
        or bool(delegation.get("dispatchable"))
    )


class OwnerInvariantCorpusTests(unittest.TestCase):
    def test_owner_invariant_over_both_corpora(self) -> None:
        """External owner only with explicit-choice-writer provenance.

        Quantifies over every ROUTING_PRECISION_CASES case and every
        non-owner-choice ROUTING_INTERVENTION_CASES case. A case is
        owner-choice iff its payload yields `executor_selection.choice_required
        is True` — a producer predicate, never a property of the case id. The
        three Korean witnesses are non-owner-choice and therefore inside this
        quantifier: they pass because the chat path records their in-message
        naming as explicit-choice provenance at resolution time.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            preference_file = owner_preference_path(paths)
            for case in (*ROUTING_PRECISION_CASES, *ROUTING_INTERVENTION_CASES):
                if preference_file.exists():
                    preference_file.unlink()
                payload = build_chat_interaction_payload(
                    case.message, source="discord", paths=paths
                )
                if _selection(payload).get("choice_required") is True:
                    continue  # owner-choice case: outside this criterion's quantifier
                state = read_owner_preference(paths)
                self.assertFalse(
                    external_owner_violation(payload, state),
                    f"case {case.id} carries an external owner without provenance",
                )

    def test_unresolved_owner_states_use_producer_fields_only(self) -> None:
        payload = build_chat_interaction_payload(CODING_MESSAGE, source="discord")
        selection = _selection(payload)
        self.assertIs(selection.get("choice_required"), True)
        self.assertEqual(selection.get("status"), "executor_choice_required")
        self.assertIsNone(_delegation(payload).get("selected_executor_profile"))

    def test_codex_mutant_fails_the_gate(self) -> None:
        """`executor_target="codex"` with no recorded preference must be flagged.

        Mandatory because a `dispatch_policy`-based disjunction passed on
        exactly this state: a dispatchable executor handoff naming Codex.
        """
        payload = build_chat_interaction_payload(
            CODING_MESSAGE, source="discord", executor_target="codex"
        )
        delegation = _delegation(payload)
        self.assertEqual(delegation.get("selected_executor_profile"), "codex")
        self.assertIs(delegation.get("dispatchable"), True)
        self.assertIsInstance(delegation.get("executor_handoff"), dict)
        self.assertTrue(external_owner_violation(payload, empty_owner_preference_state()))

    def test_claude_code_mutant_fails_the_gate(self) -> None:
        """Same mutant for claude-code, which reaches a prompt handoff."""
        payload = build_chat_interaction_payload(
            CODING_MESSAGE, source="discord", executor_target="claude-code"
        )
        delegation = _delegation(payload)
        self.assertEqual(delegation.get("selected_executor_profile"), "claude-code")
        self.assertIsInstance(delegation.get("prompt_handoff"), dict)
        self.assertTrue(external_owner_violation(payload, empty_owner_preference_state()))


class InMessageNamingTests(unittest.TestCase):
    def test_named_delivery_request_records_in_message_provenance(self) -> None:
        """Naming is choosing (§5.3.1): a delivery request naming Codex
        resolves it as owner only with recorded in-message-naming
        provenance."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = build_chat_interaction_payload(
                IN_MESSAGE_NAMING_DELIVERY_MESSAGE, source="discord", paths=paths
            )
            delegation = _delegation(payload)
            self.assertEqual(delegation.get("selected_executor_profile"), "codex")
            self.assertIs(_selection(payload).get("choice_required"), False)
            state = read_owner_preference(paths)
            self.assertEqual(
                explicit_choice_provenance(state, route_family=ROUTE_FAMILY),
                "in_message_naming",
            )
            route = state["routes"][ROUTE_FAMILY]
            self.assertEqual(route["naming_cue"], "named_executor:codex")
            self.assertFalse(external_owner_violation(payload, state))

    def test_legacy_codex_session_flows_surface_owner_selection(self) -> None:
        """#954 stage 5 (plan Q9): the legacy Codex session flows resolve the
        owner-selection surface, never `ultrawork`, and never carry an
        unrecorded external owner."""
        cases = {case.id: case for case in ROUTING_INTERVENTION_CASES}
        for witness_id in OWNER_SELECTION_WITNESS_IDS:
            case = cases.get(witness_id)
            self.assertIsNotNone(case, f"witness {witness_id} left the corpus")
            with TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                payload = build_chat_interaction_payload(
                    case.message, source="discord", paths=paths
                )
                route = payload.get("route") or {}
                self.assertNotEqual(route.get("selected_skill"), "ultrawork", witness_id)
                self.assertEqual(
                    route.get("selected_skill"), "executor-runtime-readiness", witness_id
                )
                delegation = _delegation(payload)
                selected = delegation.get("selected_executor_profile")
                if selected in EXTERNAL_CLI_PROFILES:
                    state = read_owner_preference(paths)
                    self.assertFalse(external_owner_violation(payload, state), witness_id)

    def test_paraphrase_negative_control_resolves_no_external_owner(self) -> None:
        case_ids = {case.id for case in ROUTING_PRECISION_CASES}
        self.assertIn(PARAPHRASE_CASE_ID, case_ids)
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            payload = build_chat_interaction_payload(
                PARAPHRASE_MESSAGE, source="discord", paths=paths
            )
            self.assertIsNone(_delegation(payload).get("selected_executor_profile"))
            self.assertFalse(owner_preference_path(paths).exists())
            serialized = json.dumps(payload, ensure_ascii=False, default=str).casefold()
            self.assertNotIn("codex", serialized)
            self.assertNotIn("claude-code", serialized)
            self.assertNotIn("claude code", serialized)

    def test_in_message_writer_never_advances_the_learning_streak(self) -> None:
        state = record_in_message_explicit_naming(
            empty_owner_preference_state(),
            route_family=ROUTE_FAMILY,
            selected_owner="codex",
            naming_cue="named_executor:codex",
            occurred_at=TS,
        )
        for occurred_at in ("2026-08-13T00:00:02Z", "2026-08-13T00:00:03Z"):
            state = record_in_message_explicit_naming(
                state,
                route_family=ROUTE_FAMILY,
                selected_owner="codex",
                naming_cue="named_executor:codex",
                occurred_at=occurred_at,
            )
        route = state["routes"][ROUTE_FAMILY]
        self.assertEqual(route["consecutive_accepted_explicit_choices"], 1)
        self.assertEqual(route["provenance"], "in_message_naming")
        self.assertEqual(validate_owner_preference(state), [])


class OfferIsNotDispatchTests(unittest.TestCase):
    def test_choice_required_never_resolves_owner_or_dispatch(self) -> None:
        witnessed = False
        for case in (*ROUTING_PRECISION_CASES, *ROUTING_INTERVENTION_CASES):
            payload = build_chat_interaction_payload(case.message, source="discord")
            self.assertFalse(offer_not_dispatch_violation(payload), case.id)
            if case.id == CHOICE_REQUIRED_WITNESS_ID:
                witnessed = True
                self.assertIs(_selection(payload).get("choice_required"), True)
                self.assertIsNone(
                    _delegation(payload).get("selected_executor_profile")
                )
                self.assertIs(_delegation(payload).get("dispatchable"), False)
        self.assertTrue(
            witnessed,
            f"non-vacuity witness {CHOICE_REQUIRED_WITNESS_ID} left the corpus",
        )

    def test_offer_mutant_with_resolved_owner_is_flagged(self) -> None:
        mutant = {
            "delegation": {
                "selected_executor_profile": "codex",
                "dispatchable": False,
                "executor_selection": {
                    "status": "executor_choice_required",
                    "choice_required": True,
                    "options": [],
                },
            }
        }
        self.assertTrue(offer_not_dispatch_violation(mutant))


class ProvenanceTests(unittest.TestCase):
    def test_both_explicit_choice_writers_satisfy_provenance(self) -> None:
        accepted = record_accepted_explicit_choice(
            empty_owner_preference_state(),
            route_family=ROUTE_FAMILY,
            selected_owner="codex",
            occurred_at=TS,
        )
        self.assertEqual(
            explicit_choice_provenance(accepted, route_family=ROUTE_FAMILY),
            "accepted_explicit_choice",
        )
        named = record_in_message_explicit_naming(
            empty_owner_preference_state(),
            route_family=ROUTE_FAMILY,
            selected_owner="claude-code",
            naming_cue="named_executor:claude-code",
            occurred_at=TS,
        )
        self.assertEqual(
            explicit_choice_provenance(named, route_family=ROUTE_FAMILY),
            "in_message_naming",
        )

    def test_raw_state_writer_mutant_fails_provenance(self) -> None:
        """A raw write bypassing both explicit-choice writers must be rejected.

        The mutant targets the raw path specifically: after the carve-out a
        write through the in-message-naming writer is legitimate, so the check
        is provenance-based, not writer-name-based.
        """
        raw = empty_owner_preference_state(updated_at=TS)
        raw["routes"][ROUTE_FAMILY] = {
            "route_family": ROUTE_FAMILY,
            "selected_owner": "codex",
            "consecutive_accepted_explicit_choices": 1,
            "first_choice_at": TS,
            "last_choice_at": TS,
            "learned_at": "",
            "reset_at": "",
            "reset_reason": "",
            "provenance": "",
            "naming_cue": "",
        }
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_owner_preference(paths, raw)  # the raw path itself succeeds
            state = read_owner_preference(paths)
        self.assertEqual(explicit_choice_provenance(state, route_family=ROUTE_FAMILY), "")

        payload = build_chat_interaction_payload(
            CODING_MESSAGE, source="discord", executor_target="codex"
        )
        self.assertTrue(external_owner_violation(payload, state))

    def test_answers_never_stick_and_reset_clears_their_history(self) -> None:
        # A coding-owner choice counts only for the request it was made in: three answers leave history that
        # selects no owner for the next request, and a reset clears that history.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            for _ in range(3):
                build_chat_interaction_payload(
                    CODING_MESSAGE, source="discord", paths=paths, executor_target="codex"
                )
            state = read_owner_preference(paths)
            route = state["routes"][ROUTE_FAMILY]
            self.assertEqual(route["consecutive_accepted_explicit_choices"], 3)
            self.assertEqual(route["provenance"], "accepted_explicit_choice")

            fourth = build_chat_interaction_payload(CODING_MESSAGE, source="discord", paths=paths)
            selection = _selection(fourth)
            self.assertIs(selection.get("choice_required"), True)
            self.assertIsNone(_delegation(fourth).get("selected_executor_profile"))
            self.assertFalse(external_owner_violation(fourth, read_owner_preference(paths)))

            reset = reset_owner_preference(
                read_owner_preference(paths),
                route_family=ROUTE_FAMILY,
                reason="user_requested_reset",
                occurred_at=TS,
            )
            write_owner_preference(paths, reset)
            self.assertEqual(
                explicit_choice_provenance(
                    read_owner_preference(paths), route_family=ROUTE_FAMILY
                ),
                "",
            )

            after = build_chat_interaction_payload(
                CODING_MESSAGE, source="discord", paths=paths
            )
            selection = _selection(after)
            self.assertIs(selection.get("choice_required"), True)
            self.assertEqual(selection.get("status"), "executor_choice_required")
            self.assertIsNone(_delegation(after).get("selected_executor_profile"))

if __name__ == "__main__":
    unittest.main()
