"""The risky-action confirmation ladder and the account-authorization projection.

Two issues meet here.

#800 asks that a risky action get an explainable allow, deny, or ask, that the
approval binding it never stretch to a sibling action, a broader scope, another
owner, or a later session, and that one intent still produce one prompt. The
load-bearing tests below are therefore not "a risky action asks": they are that
the *classifier never reads message text*, and that arming a fourth ladder did
not create a fourth prompt.

#799 asks for account authorization. Roughly three quarters of it is a
projection over things the tree already derives; the rest cannot be implemented
at all, because a consent flow owned by a provider's website is not observable
from here. The tests hold both halves in place: the projection is asserted, and
the declaration that the rest is not enforced is asserted just as hard, so a
later change cannot quietly promote a rendered instruction into a guarantee.
"""

from __future__ import annotations

import builtins
import importlib
import inspect
import json
import socket
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _credential_fixtures import AWS_ACCESS_KEY_ID, AWS_TEMPORARY_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()

from omh.coding import isolation as isolation_module  # noqa: E402
from omh.coding.action_gate import (  # noqa: E402
    ACCOUNT_ACCESS_STATES,
    ACCOUNT_AUTHORIZATION_BLOCKER,
    ACCOUNT_BACKED_ACTIONS,
    ACCOUNT_BLOCKER_NAMES,
    ACCOUNT_SIGNAL_STALE_AFTER_SECONDS,
    ACTION_RISK_INPUTS,
    CONFIRMATION_LADDERS,
    DATA_BOUNDARY_LIMIT_NAMES,
    DATA_BOUNDARY_NAMES,
    LADDER_ACTION_IDS,
    MAX_UNCONFIRMED_TARGET_PATHS,
    MUTATING_ACTIONS,
    RISK_CLASS_NAMES,
    RISK_CONSENT_BLOCKER,
    RISK_CONSENT_ENFORCERS,
    RISKY_ACTION_CLASSES,
    SAFETY_BOUNDARY_NAMES,
    build_account_authorization,
    build_task_authority_envelope,
    build_task_handoff_safety_contract,
    classify_action_risk,
    data_boundary_facts,
    evaluate_action_gate,
    granted_risk_actions,
    loop_actions,
    risk_classes_present,
    safety_boundary_names,
    split_handoff_safety_contract,
    validate_account_authorization,
    validate_action_gate_verdict,
    validate_action_risk,
    validate_task_authority_envelope,
)
from omh.coding.coding_delegation import build_coding_delegation_payload  # noqa: E402
from omh.quality import safety_preflight as safety_preflight_module  # noqa: E402
from omh.quality.safety_preflight import (  # noqa: E402
    ACCESS_INTENTS,
    DATA_BOUNDARY_LIMIT_NAMES as PREFLIGHT_DATA_BOUNDARY_LIMIT_NAMES,
    MAX_TARGET_PATHS,
    data_boundary_enforcement_facts,
)
from omh.system.metadata_safety import is_secret_value_shaped  # noqa: E402
from omh.workflows.approval_receipts import (  # noqa: E402
    APPROVABLE_ACTIONS,
    APPROVAL_TTL_SECONDS,
    CONFIRMATION_LADDERS as RECEIPT_CONFIRMATION_LADDERS,
    build_approval_receipt,
)
from omh.wrapper import contract as wrapper_contract  # noqa: E402
from omh.wrapper.contract import build_chat_response_from_delegation  # noqa: E402


_MESSAGE = "fix the broken login flow in src/auth.py and add a regression test"
_ALLOW_VERDICT = {
    "schema_version": "omh_safety_preflight_verdict/v1",
    "status": "allow",
    "rule_id": "",
    "field": "",
    "correction": "",
    "safety_profile_revision": "rev-frozen",
}
_DENY_VERDICT = {
    **_ALLOW_VERDICT,
    "status": "deny",
    "rule_id": "target_paths_bounded",
    "field": "target_paths[0]",
    "correction": "Use a project-relative target path.",
}

# A request that declares a write over more paths than an operator can read
# from the request itself. Every value here is a *declaration*, which is the
# whole point: nothing about the message produced it.
_BROAD_WRITE_REQUEST = {
    "access_intents": ["read", "write"],
    "target_paths": [f"src/module{index}/thing.py" for index in range(MAX_UNCONFIRMED_TARGET_PATHS + 4)],
    "approved_destinations": [],
    "remote_targets": [],
}
_NARROW_REQUEST = {
    "access_intents": ["read", "write"],
    "target_paths": ["src/auth.py"],
    "approved_destinations": [],
    "remote_targets": [],
}
_PUBLISHING_REQUEST = {**_NARROW_REQUEST, "access_intents": ["read", "share"]}
_DESTINATION_REQUEST = {
    **_NARROW_REQUEST,
    "approved_destinations": [{"kind": "git_remote", "ref": "origin"}],
}

_T0 = "2026-08-06T00:00:00Z"
_T_PLUS_10M = "2026-08-06T00:10:00Z"
_T_PAST_WINDOW = "2026-08-06T09:00:00Z"


def _gate(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "message": _MESSAGE,
        "delegation_action": "delegate",
        "intent": "coding",
        "review_required": False,
        "work_owner_mode": "external_executor",
        "selected_executor_profile": "codex",
        "dispatch_policy": "ask_before_dispatch",
        "dispatchable": True,
        "choice_required": False,
        "executor_selection_status": "handoff_prepared",
        "isolation_plan": {"strategy": "same_workspace_ok"},
        "safety_preflight": _ALLOW_VERDICT,
        "run_id": "run-800",
    }
    arguments.update(overrides)
    return evaluate_action_gate(**arguments)  # type: ignore[arg-type]


def _receipt(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "approved_action": "repo_edit",
        "scope_class": "permission_profile",
        "scope_ref": "execute_with_gates",
        "owner": "codex",
        "run_id": "run-800",
        "safety_profile_revision": "rev-frozen",
        "confirmation_ladder": "risky_action",
        "decision": "granted",
        "decided_at": _T0,
    }
    arguments.update(overrides)
    return build_approval_receipt(**arguments)  # type: ignore[arg-type]


def _envelope(*, grants: tuple[str, ...] = (), **overrides: object) -> dict[str, object]:
    envelope = build_task_authority_envelope(
        denied=False,
        delegation_action="delegate",
        intent="coding",
        review_required=False,
        work_owner_mode="external_executor",
        selected_executor_profile="codex",
        dispatchable=True,
        choice_required=False,
        isolation_plan={"strategy": "same_workspace_ok"},
        message=_MESSAGE,
        safety_profile_revision="rev-frozen",
    )
    if grants:
        # `required_actions_for` never yields merge, a pull-request action, or
        # external_posting, so the only way to exercise those classes is an
        # envelope a caller handed in. It is widened *consistently* — every
        # derived field moved with the action set — because an envelope whose
        # `merge_authority` disagrees with its allowed actions is one the
        # validator refuses, and a test built on one would be testing a shape
        # that cannot exist.
        allowed = sorted(set(envelope["allowed_actions"]) | set(grants))  # type: ignore[arg-type]
        blocked = sorted(set(loop_actions()) - set(allowed))
        envelope["allowed_actions"] = allowed
        envelope["blocked_actions"] = blocked
        envelope["exclusions"] = [
            entry for entry in envelope["exclusions"] if entry["action"] in blocked  # type: ignore[index]
        ]
        envelope["mutation_rights"] = sorted(set(allowed) & set(MUTATING_ACTIONS))
        envelope["merge_authority"] = "granted" if "merge" in allowed else "disabled"
        envelope["external_action_authority"] = (
            "publish_allowed" if "external_posting" in allowed else "prepare_only"
        )
    envelope.update(overrides)
    return envelope


class LadderRegistrationTests(unittest.TestCase):
    """The ladder is registered, not bolted on beside the others."""

    def test_the_risky_action_ladder_is_a_registered_ladder_with_an_action_id(self) -> None:
        self.assertIn("risky_action", CONFIRMATION_LADDERS)
        self.assertEqual(LADDER_ACTION_IDS["risky_action"], "confirm_risky_action")
        self.assertEqual(set(LADDER_ACTION_IDS), set(CONFIRMATION_LADDERS))

    def test_precedence_places_it_between_the_profile_question_and_the_go_ahead(self) -> None:
        # The tuple order *is* the documented precedence, so it is asserted
        # rather than left to the arbitration body to imply.
        self.assertEqual(
            CONFIRMATION_LADDERS,
            ("executor_selection", "permission_profile", "risky_action", "operator_confirmation"),
        )

    def test_the_receipt_vocabulary_moved_with_it(self) -> None:
        # A ladder the gate can arm and the receipt store cannot name would be a
        # confirmation whose answer is unmintable.
        self.assertEqual(set(RECEIPT_CONFIRMATION_LADDERS), set(CONFIRMATION_LADDERS))
        self.assertEqual(_receipt()["confirmation_ladder"], "risky_action")

    def test_the_wrapper_ladder_list_is_derived_from_the_gate_rather_than_retyped(self) -> None:
        """The two lists had already drifted; now one is derived from the other.

        `send_to_codex` was in the wrapper's copy and not in the gate's map, and
        nothing failed. The wrapper list is now the gate's values plus the two
        groups this lane really owns, so the same drift cannot recur.
        """
        self.assertTrue(set(LADDER_ACTION_IDS.values()) <= set(wrapper_contract._LADDER_ACTION_IDS))
        self.assertIn("send_to_codex", wrapper_contract._LADDER_ACTION_IDS)
        self.assertEqual(wrapper_contract._LADDER_ACTION_ALIASES["send_to_codex"], "send_to_executor")
        for confirm_id in wrapper_contract._OPERATOR_CARD_CONFIRM_ACTION_IDS:
            with self.subTest(confirm_id=confirm_id):
                self.assertIn(confirm_id, wrapper_contract._LADDER_ACTION_IDS)
                self.assertIn(confirm_id, wrapper_contract.VISIBLE_ACTIONS)
        source = inspect.getsource(wrapper_contract)
        self.assertIn("_LADDER_ACTION_IDS = tuple(", source)
        self.assertIn("LADDER_ACTION_IDS.values()", source)

    def test_the_armed_action_is_renderable(self) -> None:
        self.assertIn("confirm_risky_action", wrapper_contract.VISIBLE_ACTIONS)
        self.assertEqual(wrapper_contract._LADDER_ACTION_LABELS["confirm_risky_action"], "Confirm risky action")


class OnePromptTests(unittest.TestCase):
    """One intent, one prompt — over every combination that can co-occur."""

    def _verdict(
        self,
        *,
        denied: bool,
        choice_required: bool,
        expansion: bool,
        risky: bool,
        approved: bool,
        dispatchable: bool,
    ) -> dict[str, object]:
        return _gate(
            work_owner_mode="external_executor" if dispatchable or choice_required else "prompt_only_handoff",
            selected_executor_profile=None if choice_required else ("codex" if dispatchable else "claude-code"),
            dispatch_policy="ask_before_dispatch" if dispatchable else "prepare_only",
            dispatchable=dispatchable,
            choice_required=choice_required,
            executor_selection_status="executor_choice_required" if choice_required else "handoff_prepared",
            safety_preflight=_DENY_VERDICT if denied else _ALLOW_VERDICT,
            safety_preflight_request=_BROAD_WRITE_REQUEST if risky else _NARROW_REQUEST,
            requested_actions=["merge"] if expansion else [],
            approval_receipts=[_receipt(owner="codex" if dispatchable else "claude-code")] if approved else [],
            now=_T_PLUS_10M,
        )

    def test_one_intent_arms_at_most_one_ladder_over_every_combination(self) -> None:
        for denied in (False, True):
            for choice_required in (False, True):
                for expansion in (False, True):
                    for risky in (False, True):
                        for approved in (False, True):
                            for dispatchable in (False, True):
                                if choice_required and dispatchable:
                                    continue  # a choice-required selection is never dispatchable
                                with self.subTest(
                                    denied=denied,
                                    choice_required=choice_required,
                                    expansion=expansion,
                                    risky=risky,
                                    approved=approved,
                                    dispatchable=dispatchable,
                                ):
                                    verdict = self._verdict(
                                        denied=denied,
                                        choice_required=choice_required,
                                        expansion=expansion,
                                        risky=risky,
                                        approved=approved,
                                        dispatchable=dispatchable,
                                    )
                                    confirmation = verdict["confirmation"]
                                    armed = confirmation["armed_ladders"]
                                    self.assertLessEqual(len(armed), 1)
                                    self.assertEqual(confirmation["required"], bool(armed))
                                    suppressed = [entry["ladder"] for entry in confirmation["suppressed_ladders"]]
                                    self.assertEqual(sorted(armed + suppressed), sorted(CONFIRMATION_LADDERS))
                                    for entry in confirmation["suppressed_ladders"]:
                                        self.assertTrue(entry["reason"].strip())
                                    gate, _ = split_handoff_safety_contract(verdict)
                                    self.assertEqual(validate_action_gate_verdict(gate), [])

    def test_precedence_is_deny_then_selection_then_profile_then_risk_then_operator(self) -> None:
        def ladder(**kwargs: object) -> str:
            return self._verdict(**kwargs)["confirmation"]["ladder"]  # type: ignore[arg-type,index]

        base = {"denied": False, "choice_required": False, "expansion": False, "risky": False, "approved": False}
        self.assertEqual(ladder(**{**base, "denied": True, "risky": True, "dispatchable": False}), "none")
        self.assertEqual(
            ladder(**{**base, "choice_required": True, "expansion": True, "risky": True, "dispatchable": False}),
            "executor_selection",
        )
        self.assertEqual(
            ladder(**{**base, "expansion": True, "risky": True, "dispatchable": True}), "permission_profile"
        )
        self.assertEqual(ladder(**{**base, "risky": True, "dispatchable": True}), "risky_action")
        self.assertEqual(ladder(**{**base, "dispatchable": True}), "operator_confirmation")
        self.assertEqual(ladder(**{**base, "dispatchable": False}), "none")

    def test_a_card_never_asks_a_second_authority_question_when_the_risk_ladder_wins(self) -> None:
        # The card renders the arbitrated ladder; it does not add one of its own.
        payload = build_coding_delegation_payload(_MESSAGE, executor_target="codex")
        payload["action_gate"] = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        payload["dispatchable"] = payload["action_gate"]["dispatchable"]
        response = build_chat_response_from_delegation(payload)
        enabled = [action["id"] for action in response["actions"] if action["enabled"]]
        self.assertEqual(response["state"]["next_action"], "confirm_risky_action")
        self.assertIn("confirm_risky_action", enabled)
        self.assertNotIn("send_to_executor", enabled)
        self.assertNotIn("send_to_codex", enabled)
        primaries = [
            action["id"]
            for action in response["actions"]
            if action["enabled"] and action["style"] == "primary"
        ]
        self.assertEqual(primaries, ["confirm_risky_action"])

    def test_drift_still_denies_before_any_arbitration(self) -> None:
        """The ordering invariant: a user is never asked to approve doomed work."""
        verdict = _gate(
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            live_safety_profile_revision="rev-moved",
        )
        self.assertEqual(verdict["outcome"], "deny")
        self.assertEqual(verdict["denial"]["rule_id"], "safety_profile_revision_drift")
        self.assertEqual(verdict["confirmation"]["ladder"], "none")
        self.assertEqual(verdict["confirmation"]["armed_ladders"], [])
        self.assertFalse(verdict["dispatchable"])
        # The denial withdrew the authority, so nothing risky is left to classify.
        self.assertEqual(verdict["action_risk"]["decision"], "allow")
        self.assertEqual(verdict["action_risk"]["classes"], [])


class RiskDerivationTests(unittest.TestCase):
    """What the classifier reads, and — precisely — what that does not promise.

    The earlier version of this class asserted that action risk "is not
    message-derived". That sentence is true at this function's boundary and
    false end to end: on the shipped lane the declared `target_paths` the
    `broad_write` rule counts are regex-scraped out of the user's message by
    `coding_delegation._safety_preflight_target_paths`. Both halves are now
    asserted, because a claim that only holds at a boundary a user never sees is
    the kind of claim this repo has had to correct twice.
    """

    def test_the_same_message_under_different_policy_inputs_yields_a_different_risk(self) -> None:
        narrow = _gate(safety_preflight_request=_NARROW_REQUEST)
        broad = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        self.assertEqual(narrow["action_risk"]["level"], "none")
        self.assertEqual(broad["action_risk"]["level"], "elevated")
        self.assertNotEqual(narrow["action_risk"]["decision"], broad["action_risk"]["decision"])

    def test_a_different_message_under_the_same_policy_inputs_yields_an_identical_risk(self) -> None:
        messages = (
            _MESSAGE,
            "delete every file in the repository and force push to main",
            "정말 위험한 리팩터링을 병렬로 진행해줘",
            "",
        )
        baseline = None
        for message in messages:
            with self.subTest(message=message):
                risk = _gate(message=message, safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
                if baseline is None:
                    baseline = json.dumps(risk, sort_keys=True)
                self.assertEqual(json.dumps(risk, sort_keys=True), baseline)

    def test_the_classifier_has_no_parameter_that_could_carry_message_text(self) -> None:
        parameters = set(inspect.signature(classify_action_risk).parameters)
        for text_surface in ("message", "context_pack", "memory_recall_pack", "text"):
            self.assertNotIn(text_surface, parameters)

    def test_it_does_not_reuse_the_message_derived_isolation_risk_level(self) -> None:
        """`isolation._risk_level` reads `message.lower()`; a safety decision may not.

        Read from the tree rather than asserted in prose, so the sentence cannot
        outlive the function it describes.
        """
        self.assertIn("lowered", inspect.getsource(isolation_module._risk_level))
        self.assertIn("message.lower()", inspect.getsource(isolation_module.build_isolation_plan))
        classifier = inspect.getsource(classify_action_risk) + inspect.getsource(risk_classes_present)
        # It never reads the key and never calls the function that computes it.
        self.assertNotIn('"risk_level"', classifier)
        self.assertNotIn("_risk_level(", classifier)
        self.assertNotIn(".lower()", classifier)

    def test_the_two_risk_levels_are_named_apart_and_their_relationship_is_written_down(self) -> None:
        payload = build_coding_delegation_payload("refactor the parallel worker pool", executor_target="codex")
        isolation_risk = payload["isolation_plan"]["risk_level"]
        action_risk = payload["action_gate"]["action_risk"]
        self.assertEqual(isolation_risk, "high")
        # They disagree, which is allowed, and the record says why in words.
        self.assertEqual(action_risk["level"], "none")
        self.assertIn("never compared", action_risk["isolation_risk_relationship"])
        self.assertIn("isolation_plan.risk_level", action_risk["isolation_risk_relationship"])

    def test_every_declared_input_is_a_policy_input(self) -> None:
        for declared in ACTION_RISK_INPUTS:
            with self.subTest(declared=declared):
                self.assertTrue(
                    declared.startswith(("isolation_plan.", "safety_preflight_request.", "task_authority_envelope."))
                )

    def test_the_broad_write_bound_is_a_count_of_declared_paths(self) -> None:
        envelope = _envelope()
        for count, expected in (
            (MAX_UNCONFIRMED_TARGET_PATHS, []),
            (MAX_UNCONFIRMED_TARGET_PATHS + 1, ["broad_write"]),
        ):
            with self.subTest(count=count):
                request = {
                    **_NARROW_REQUEST,
                    "target_paths": [f"src/f{index}.py" for index in range(count)],
                }
                self.assertEqual(risk_classes_present(envelope=envelope, safety_preflight_request=request), expected)
        # Well inside the bound at which the preflight denies outright, so the
        # ask is reachable rather than shadowed by a refusal.
        self.assertLess(MAX_UNCONFIRMED_TARGET_PATHS, MAX_TARGET_PATHS)

    def test_a_declared_share_intent_or_destination_alone_raises_no_class(self) -> None:
        """A declaration the envelope cannot act on is not a risk, it is a denial upstream.

        Reading either as a risky class produced a class whose approvable action
        the envelope never granted, so the confirmation asked about something no
        approval could ever match. The preflight's own destination and access
        intent rules are what refuse a reach nobody approved.
        """
        envelope = _envelope()
        self.assertNotIn("external_posting", envelope["allowed_actions"])
        self.assertEqual(risk_classes_present(envelope=envelope, safety_preflight_request=_PUBLISHING_REQUEST), [])
        self.assertEqual(risk_classes_present(envelope=envelope, safety_preflight_request=_DESTINATION_REQUEST), [])
        self.assertEqual(_gate(safety_preflight_request=_PUBLISHING_REQUEST)["action_risk"]["level"], "none")

    def test_a_granted_external_action_is_risky_with_no_request_at_all(self) -> None:
        for grant, expected in (("merge", "external_mutation"), ("external_posting", "publication")):
            with self.subTest(grant=grant):
                envelope = _envelope(grants=(grant,))
                self.assertEqual(validate_task_authority_envelope(envelope, parent_dispatchable=True), [])
                self.assertEqual(risk_classes_present(envelope=envelope), [expected])
                # Present only because the envelope grants an action that can
                # perform it, so the confirmation has something to ask about.
                self.assertEqual(granted_risk_actions(envelope, expected), [grant])

    def test_every_present_class_names_only_actions_the_envelope_granted(self) -> None:
        envelope = _envelope(grants=("merge", "external_posting"))
        risk = classify_action_risk(
            envelope=envelope,
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            owner="codex",
            run_id="run-800",
        )
        allowed = set(envelope["allowed_actions"])  # type: ignore[arg-type]
        for entry in risk["classes"]:
            with self.subTest(risk_class=entry["class"]):
                self.assertTrue(entry["approvable_actions"])
                self.assertTrue(set(entry["approvable_actions"]) <= allowed)
        for entry in risk["consent"]:
            self.assertIn(entry["approved_action"], allowed)

    def test_the_broad_write_class_is_message_sensitive_end_to_end_and_the_record_says_so(self) -> None:
        """The honest half. This is the property that is actually true.

        `broad_write` is `request_declared`, and on the shipped lane that
        declaration is scraped out of the message, so two phrasings of one
        intent classify differently and a request that names no path evades the
        class entirely. The text policy has to state that, in those terms.
        """
        listed = "refactor the auth module: update " + " ".join(
            f"src/module{index}/thing.py" for index in range(MAX_UNCONFIRMED_TARGET_PATHS + 2)
        )
        vague = "rewrite everything under src/"
        listed_risk = build_coding_delegation_payload(listed, executor_target="codex")["action_gate"]["action_risk"]
        vague_risk = build_coding_delegation_payload(vague, executor_target="codex")["action_gate"]["action_risk"]
        # One intent, two phrasings, two different classifications.
        self.assertEqual([entry["class"] for entry in listed_risk["classes"]], ["broad_write"])
        self.assertEqual(vague_risk["classes"], [])
        self.assertEqual(vague_risk["level"], "none")
        entry = listed_risk["classes"][0]
        self.assertEqual(entry["derivation"], "request_declared")
        policy = listed_risk["text_policy"]
        self.assertIn("_safety_preflight_target_paths", policy)
        self.assertIn("message-sensitive", policy)
        self.assertIn("rewrite everything under src/", policy)
        # And the classes the envelope decides alone are named as the ones a
        # phrasing cannot move.
        for name in ("external_mutation", "publication"):
            self.assertIn(name, policy)

    def test_the_derivation_vocabulary_matches_what_each_rule_reads(self) -> None:
        risk = classify_action_risk(
            envelope=_envelope(grants=("merge", "external_posting")),
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            owner="codex",
            run_id="run-800",
        )
        derivations = {entry["class"]: entry["derivation"] for entry in risk["classes"]}
        self.assertEqual(
            derivations,
            {
                "broad_write": "request_declared",
                "external_mutation": "policy_derived",
                "publication": "policy_derived",
            },
        )


class ExplainableVerdictTests(unittest.TestCase):
    """Allow, deny, or ask — each one says why, and each one is checkable."""

    def test_every_decision_is_explained_and_validates(self) -> None:
        cases = {
            "allow": _gate(safety_preflight_request=_NARROW_REQUEST),
            "ask": _gate(safety_preflight_request=_BROAD_WRITE_REQUEST),
            "deny": _gate(
                safety_preflight_request=_BROAD_WRITE_REQUEST,
                approval_receipts=[_receipt(decision="denied")],
                now=_T_PLUS_10M,
            ),
            "approved": _gate(
                safety_preflight_request=_BROAD_WRITE_REQUEST,
                approval_receipts=[_receipt()],
                now=_T_PLUS_10M,
            ),
        }
        expected = {"allow": "allow", "ask": "ask", "deny": "deny", "approved": "allow"}
        for label, verdict in cases.items():
            with self.subTest(label=label):
                risk = verdict["action_risk"]
                self.assertEqual(risk["decision"], expected[label])
                self.assertTrue(risk["reason"].strip())
                self.assertEqual(validate_action_risk(risk), [])
                gate, _ = split_handoff_safety_contract(verdict)
                self.assertEqual(validate_action_gate_verdict(gate), [])

    def test_the_five_risky_kinds_800_names_are_all_accounted_for(self) -> None:
        self.assertEqual(
            RISKY_ACTION_CLASSES,
            ("broad_write", "deletion", "external_mutation", "identity_change", "publication"),
        )
        self.assertEqual(set(RISK_CLASS_NAMES), set(RISKY_ACTION_CLASSES))
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        covered = {entry["class"] for entry in risk["classes"]} | {
            entry["class"] for entry in risk["subsumed_classes"]
        }
        # The vocabulary is covered in full: nothing is quietly dropped because
        # no declared input could assert it.
        self.assertTrue(set(RISKY_ACTION_CLASSES) <= covered | {"external_mutation", "publication"})
        for entry in risk["subsumed_classes"]:
            with self.subTest(entry=entry["class"]):
                self.assertEqual(entry["derivation"], "subsumed")
                self.assertIn(entry["carrier"], {"broad_write", "external_mutation"})
                self.assertTrue(entry["statement"].strip())

    def test_deletion_states_why_it_cannot_be_told_apart_from_a_write(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        deletion = next(entry for entry in risk["subsumed_classes"] if entry["class"] == "deletion")
        self.assertEqual(deletion["carrier"], "broad_write")
        # The reason is read from the vocabulary that causes it.
        self.assertEqual(ACCESS_INTENTS, ("read", "write", "share"))
        self.assertIn("read, write, and share", deletion["statement"])

    def test_identity_change_points_at_the_projection_that_would_derive_it(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        identity = next(entry for entry in risk["subsumed_classes"] if entry["class"] == "identity_change")
        self.assertEqual(identity["carrier"], "external_mutation")
        self.assertIn("account_authorization", identity["statement"])

    def test_a_verdict_that_allows_while_a_present_class_is_unapproved_is_rejected(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        risk["decision"] = "allow"
        errors = validate_action_risk(risk)
        self.assertTrue(
            any("cannot allow while a present class is unapproved" in error for error in errors), errors
        )

    def test_a_verdict_that_allows_one_class_and_ignores_another_is_rejected(self) -> None:
        """The collapse, as a validator case: one answer may not speak for two questions."""
        risk = classify_action_risk(
            envelope=_envelope(grants=("merge", "external_posting")),
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            owner="codex",
            run_id="run-800",
            approval_receipts=[_receipt()],
            now=_T_PLUS_10M,
        )
        self.assertEqual(risk["decision"], "ask")
        # Drop the classes that are still unapproved and claim an allow anyway.
        risk["decision"] = "allow"
        risk["consent"] = [entry for entry in risk["consent"] if entry["decision"] == "allow"]
        risk["withheld_actions"] = []
        errors = validate_action_risk(risk)
        self.assertTrue(any("must ask about every present class" in error for error in errors), errors)

    def test_a_verdict_naming_an_action_the_envelope_never_granted_is_rejected(self) -> None:
        """The phantom-action case: a confirmation nothing could ever satisfy."""
        verdict = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        gate, _ = split_handoff_safety_contract(verdict)
        for entry in gate["action_risk"]["consent"]:
            entry["approved_action"] = "merge"
            entry["approval_request"]["approved_action"] = "merge"
        gate["action_risk"]["withheld_actions"] = ["merge"]
        errors = validate_action_gate_verdict(gate)
        self.assertTrue(
            any("neither allows nor withheld" in error for error in errors), errors
        )

    def test_withheld_actions_must_be_exactly_the_unapproved_ones(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        risk["withheld_actions"] = []
        errors = validate_action_risk(risk)
        self.assertTrue(any("withheld_actions must be exactly" in error for error in errors), errors)

    def test_a_verdict_with_no_reason_is_rejected(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        risk["reason"] = "  "
        self.assertTrue(any("must be explained" in error for error in validate_action_risk(risk)))

    def test_a_subsumed_class_with_no_carrier_is_rejected(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        risk["subsumed_classes"][0]["carrier"] = ""
        errors = validate_action_risk(risk)
        self.assertTrue(any("must name a derivable carrier" in error for error in errors), errors)

    def test_a_present_class_pretending_to_be_carried_is_rejected(self) -> None:
        risk = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]
        risk["classes"][0]["carrier"] = "publication"
        errors = validate_action_risk(risk)
        self.assertTrue(any("must not name a carrier" in error for error in errors), errors)

    def test_a_non_object_risk_verdict_is_rejected(self) -> None:
        self.assertEqual(validate_action_risk("risky"), ["action_risk must be an object"])


class ApprovalBindingTests(unittest.TestCase):
    """The five dimensions, exercised through the gate rather than the receipt module."""

    def _decision(self, receipts: list[dict[str, object]], *, now: str = _T_PLUS_10M) -> dict[str, object]:
        return _gate(
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            approval_receipts=receipts,
            now=now,
        )

    def _only_consent(self, verdict: dict[str, object]) -> dict[str, object]:
        entries = verdict["action_risk"]["consent"]  # type: ignore[index]
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_an_approval_covers_exactly_what_it_named_and_nothing_beside_it(self) -> None:
        cases = (
            ("sibling action", _receipt(approved_action="merge"), "action_not_approved"),
            ("broader scope", _receipt(scope_ref="handoff_only"), "scope_not_approved"),
            ("another owner", _receipt(owner="claude-code"), "owner_not_approved"),
            ("another run", _receipt(run_id="run-801"), "run_not_approved"),
            ("stale revision", _receipt(safety_profile_revision="rev-old"), "safety_revision_not_approved"),
        )
        for label, receipt, reason_code in cases:
            with self.subTest(label=label):
                verdict = self._decision([receipt])
                self.assertEqual(verdict["action_risk"]["decision"], "ask")
                self.assertEqual(self._only_consent(verdict)["approval"]["reason_code"], reason_code)
                self.assertFalse(verdict["dispatchable"])
                self.assertEqual(verdict["confirmation"]["ladder"], "risky_action")

    def test_the_matching_approval_lets_the_work_proceed(self) -> None:
        verdict = self._decision([_receipt()])
        self.assertEqual(verdict["action_risk"]["decision"], "allow")
        self.assertTrue(self._only_consent(verdict)["approval"]["satisfied"])
        self.assertTrue(verdict["dispatchable"])
        self.assertEqual(verdict["confirmation"]["ladder"], "operator_confirmation")

    def test_a_missing_expired_or_revoked_approval_refuses_the_work(self) -> None:
        """The refusal the `confirmation_answered` boundary is declared against."""
        revoked = _receipt(decision="revoked", decided_at="2026-08-06T00:05:00Z")
        cases = {
            "missing": ([], _T_PLUS_10M, "ask", "approval_absent"),
            "expired": ([_receipt()], _T_PAST_WINDOW, "ask", "approval_expired"),
            "revoked": ([_receipt(), revoked], _T_PLUS_10M, "deny", "approval_revoked"),
            "denied": ([_receipt(decision="denied")], _T_PLUS_10M, "deny", "approval_denied"),
        }
        for label, (receipts, now, decision, reason_code) in cases.items():
            with self.subTest(label=label):
                verdict = self._decision(receipts, now=now)
                self.assertEqual(verdict["action_risk"]["decision"], decision)
                self.assertEqual(self._only_consent(verdict)["approval"]["reason_code"], reason_code)
                # Refused, not merely recorded: the escalated action is gone
                # from the envelope and the verdict is not dispatchable.
                self.assertFalse(verdict["dispatchable"])
                self.assertNotIn("repo_edit", verdict["authority_envelope"]["allowed_actions"])
                self.assertNotIn("executor_dispatch", verdict["authority_envelope"]["allowed_actions"])
                withheld = [
                    entry
                    for entry in verdict["authority_envelope"]["exclusions"]
                    if entry["reason_code"] == "withheld_pending_approval"
                ]
                self.assertTrue(withheld)
                for entry in withheld:
                    self.assertIn("until an approval on record covers it", entry["explanation"])

    def test_a_refused_approval_is_not_asked_again(self) -> None:
        verdict = self._decision([_receipt(decision="denied")])
        confirmation = verdict["confirmation"]
        self.assertEqual(confirmation["ladder"], "none")
        self.assertEqual(confirmation["armed_ladders"], [])
        self.assertIn("already refused or revoked", confirmation["reason"])
        for entry in confirmation["suppressed_ladders"]:
            self.assertEqual(entry["reason"], "suppressed_by:refused_approval")

    def test_a_refusal_takes_the_refused_action_off_the_card(self) -> None:
        """An operator who said no must not be offered the thing they refused."""
        payload = build_coding_delegation_payload(_MESSAGE, executor_target="codex")
        payload["action_gate"] = self._decision([_receipt(decision="denied")])
        payload["dispatchable"] = payload["action_gate"]["dispatchable"]
        response = build_chat_response_from_delegation(payload)
        enabled = [action["id"] for action in response["actions"] if action["enabled"]]
        self.assertNotIn("send_to_executor", enabled)
        self.assertNotIn("send_to_codex", enabled)
        self.assertNotEqual(response["state"]["next_action"], "send_to_executor")
        self.assertTrue(enabled, "a refusal must still leave the user somewhere to go")
        refused_actions = [
            action for action in response["actions"] if action["id"] == "send_to_executor"
        ]
        self.assertTrue(refused_actions)
        self.assertIn("refused or revoked", refused_actions[0]["payload"]["disabled_reason"])

    def test_a_report_only_classification_disables_nothing_on_the_card(self) -> None:
        """The overroute guard for the fix above: no run id means no refusal to render."""
        payload = build_coding_delegation_payload(_MESSAGE, executor_target="codex")
        payload["action_gate"] = _gate(
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            approval_receipts=[_receipt(run_id="run-800", decision="denied")],
            run_id="",
            now=_T_PLUS_10M,
        )
        self.assertEqual(payload["action_gate"]["action_risk"]["enforcement"], "declared_not_enforced")
        response = build_chat_response_from_delegation(payload)
        self.assertIn("send_to_executor", [action["id"] for action in response["actions"] if action["enabled"]])

    def test_the_approvals_the_gate_asks_for_are_the_ones_it_named(self) -> None:
        risk = self._decision([])["action_risk"]
        entry = risk["consent"][0]
        request = entry["approval_request"]
        self.assertEqual(entry["class"], "broad_write")
        self.assertEqual(request["approved_action"], "repo_edit")
        self.assertIn(request["approved_action"], APPROVABLE_ACTIONS)
        self.assertEqual(request["scope_class"], "permission_profile")
        self.assertEqual(request["scope_ref"], "execute_with_gates")
        self.assertEqual(request["owner"], "codex")
        self.assertEqual(request["run_id"], "run-800")
        self.assertEqual(request["safety_profile_revision"], "rev-frozen")
        self.assertEqual(entry["approval"]["expires_after_seconds"], APPROVAL_TTL_SECONDS)

    def test_a_receipt_for_one_class_never_releases_another(self) -> None:
        """The collapse, through the public API that produced it.

        One receipt naming `merge` used to release `broad_write`,
        `external_mutation`, and `publication` together, while a receipt for
        `repo_edit` — the action that actually performs the write — was refused
        outright because the collapsed question only ever named `merge`.
        """
        envelope = _envelope(grants=("merge", "external_posting"))

        def classify(receipts: list[dict[str, object]]) -> dict[str, object]:
            return classify_action_risk(
                envelope=envelope,
                safety_preflight_request=_BROAD_WRITE_REQUEST,
                approval_receipts=receipts,
                owner="codex",
                run_id="run-800",
                now=_T_PLUS_10M,
            )

        unanswered = classify([])
        self.assertEqual(
            [(entry["class"], entry["approved_action"]) for entry in unanswered["consent"]],
            [
                ("broad_write", "repo_edit"),
                ("external_mutation", "merge"),
                ("publication", "external_posting"),
            ],
        )
        self.assertEqual(unanswered["withheld_actions"], ["external_posting", "merge", "repo_edit"])

        merge_only = classify([_receipt(approved_action="merge")])
        self.assertEqual(merge_only["decision"], "ask")
        self.assertEqual(merge_only["withheld_actions"], ["external_posting", "repo_edit"])

        # And the receipt naming the action that performs the write is accepted.
        repo_only = classify([_receipt()])
        self.assertEqual(
            [entry["decision"] for entry in repo_only["consent"] if entry["class"] == "broad_write"], ["allow"]
        )
        self.assertEqual(repo_only["decision"], "ask")

        every = classify(
            [_receipt(), _receipt(approved_action="merge"), _receipt(approved_action="external_posting")]
        )
        self.assertEqual(every["decision"], "allow")
        self.assertEqual(every["withheld_actions"], [])
        self.assertEqual(validate_action_risk(every), [])

    def test_declaring_more_risk_never_withholds_less_authority(self) -> None:
        """The withhold gap: the multi-class verdict used to leave `repo_edit` granted."""
        single = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        single_withheld = {
            entry["action"]
            for entry in single["authority_envelope"]["exclusions"]
            if entry["reason_code"] == "withheld_pending_approval"
        }
        self.assertEqual(single_withheld, {"executor_dispatch", "repo_edit"})
        risk = classify_action_risk(
            envelope=_envelope(grants=("merge", "external_posting")),
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            owner="codex",
            run_id="run-800",
        )
        self.assertTrue({"repo_edit"} <= set(risk["withheld_actions"]))
        self.assertTrue(single_withheld - {"executor_dispatch"} <= set(risk["withheld_actions"]))

    def test_the_gate_never_reads_the_receipt_store_itself(self) -> None:
        """Approvals arrive already read, so the gate stays free of I/O."""
        _gate()  # warm the lazy imports the way the contract's own offline test does

        def _refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("the action gate must not perform I/O")

        with (
            mock.patch.object(builtins, "open", _refuse),
            mock.patch.object(socket, "socket", _refuse),
            mock.patch.object(socket, "create_connection", _refuse),
            mock.patch.object(subprocess, "run", _refuse),
            mock.patch.object(subprocess, "Popen", _refuse),
        ):
            verdict = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST, approval_receipts=[_receipt()], now=_T_PLUS_10M)
        self.assertEqual(verdict["action_risk"]["decision"], "allow")


class NarrowAnswerTests(unittest.TestCase):
    """#800's "narrow" answer, through the seam that already existed for it."""

    def test_the_narrowing_route_names_the_parameter_it_travels_on(self) -> None:
        route = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)["action_risk"]["narrowing_route"]
        self.assertEqual(route["parameter"], "requested_authority_actions")
        self.assertNotIn("repo_edit", route["narrowed_actions"])
        self.assertTrue(route["explanation"].strip())

    def test_the_narrowed_set_removes_every_carrier_and_not_just_one(self) -> None:
        """The promise is that re-running removes the question; one carrier is not enough.

        With three classes present the route used to return the envelope's own
        action set unchanged, because the single collapsed action it subtracted
        (`merge`) was one the envelope never granted. Re-running with it changed
        nothing at all.
        """
        envelope = _envelope(grants=("merge", "external_posting"))
        risk = classify_action_risk(
            envelope=envelope,
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            owner="codex",
            run_id="run-800",
        )
        route = risk["narrowing_route"]
        self.assertNotEqual(sorted(route["narrowed_actions"]), sorted(envelope["allowed_actions"]))
        for action in ("repo_edit", "merge", "external_posting"):
            self.assertNotIn(action, route["narrowed_actions"])
        # And the promise holds: the same envelope narrowed to that set carries
        # no risky class at all.
        narrowed_envelope = _envelope()
        narrowed_envelope["allowed_actions"] = sorted(
            set(route["narrowed_actions"]) & set(narrowed_envelope["allowed_actions"])  # type: ignore[arg-type]
        )
        narrowed_envelope["mutation_rights"] = sorted(
            set(narrowed_envelope["allowed_actions"]) & set(MUTATING_ACTIONS)  # type: ignore[arg-type]
        )
        self.assertEqual(
            risk_classes_present(
                envelope=narrowed_envelope, safety_preflight_request=_BROAD_WRITE_REQUEST
            ),
            [],
        )

    def test_feeding_the_narrowed_set_back_removes_the_question(self) -> None:
        asking = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        narrowed = _gate(
            safety_preflight_request=_BROAD_WRITE_REQUEST,
            requested_actions=asking["action_risk"]["narrowing_route"]["narrowed_actions"],
        )
        self.assertEqual(narrowed["action_risk"]["decision"], "allow")
        self.assertEqual(narrowed["confirmation"]["ladder"], "operator_confirmation")
        self.assertNotIn("repo_edit", narrowed["authority_envelope"]["allowed_actions"])
        narrowed_exclusions = [
            entry
            for entry in narrowed["authority_envelope"]["exclusions"]
            if entry["reason_code"] == "narrowed_by_request"
        ]
        self.assertTrue(narrowed_exclusions)

    def test_the_same_parameter_still_widens_when_it_asks_for_more(self) -> None:
        widening = _gate(safety_preflight_request=_NARROW_REQUEST, requested_actions=["merge"])
        self.assertEqual(widening["confirmation"]["ladder"], "permission_profile")
        self.assertNotIn("merge", widening["authority_envelope"]["allowed_actions"])

    def test_the_seam_has_a_production_caller_now(self) -> None:
        payload = build_coding_delegation_payload(
            _MESSAGE, executor_target="codex", requested_authority_actions=["research", "planning"]
        )
        envelope = payload["action_gate"]["authority_envelope"]
        self.assertEqual(sorted(envelope["allowed_actions"]), ["planning", "research"])
        self.assertTrue(
            any(entry["reason_code"] == "narrowed_by_request" for entry in envelope["exclusions"])
        )


class AccountAuthorizationTests(unittest.TestCase):
    """#799: the projection is implemented, the rest is declared."""

    def test_a_task_that_needs_account_backed_access_says_so_and_names_the_scopes(self) -> None:
        block = _gate()["account_authorization"]
        self.assertTrue(block["required"])
        self.assertEqual(block["accounts"][0]["minimum_scopes"], ["executor_dispatch"])
        self.assertTrue(set(block["accounts"][0]["minimum_scopes"]) <= set(ACCOUNT_BACKED_ACTIONS))
        self.assertEqual(validate_account_authorization(block), [])

    def test_a_task_that_reaches_no_account_says_that_too(self) -> None:
        block = _gate(
            delegation_action="clarify",
            dispatchable=False,
            work_owner_mode="retained_hermes",
            selected_executor_profile=None,
            dispatch_policy="prepare_only",
        )["account_authorization"]
        self.assertFalse(block["required"])
        self.assertEqual(block["accounts"], [])

    def test_the_four_states_are_derived_from_signals_the_caller_already_read(self) -> None:
        envelope = _envelope()
        cases = (
            ({}, "missing", "readiness_probe"),
            ({"login_marker": "present", "observed_at": _T0}, "authorized-unverified", "login_marker"),
            (
                {"login_marker": "present", "probe_status": "ready", "exit_code": 0, "observed_at": _T0},
                "observed-ready",
                "probe_exit_code",
            ),
            ({"login_marker": "present", "observed_at": "2026-08-05T00:00:00Z"}, "expired", "stored_timestamp"),
        )
        for signal, state, source in cases:
            with self.subTest(state=state):
                block = build_account_authorization(
                    envelope=envelope,
                    auth_signals={"profiles": {"codex": signal}} if signal else None,
                    now=_T_PLUS_10M,
                )
                self.assertEqual(block["accounts"][0]["state"], state)
                self.assertEqual(block["accounts"][0]["state_source"], source)
                self.assertIn(state, ACCOUNT_ACCESS_STATES)

    def test_a_ready_probe_that_did_not_exit_zero_is_not_ready(self) -> None:
        block = build_account_authorization(
            envelope=_envelope(),
            auth_signals={"profiles": {"codex": {"probe_status": "ready", "exit_code": 1, "observed_at": _T0}}},
            now=_T_PLUS_10M,
        )
        self.assertEqual(block["accounts"][0]["state"], "missing")

    def test_the_staleness_horizon_matches_the_signal_precedent_it_cites(self) -> None:
        from omh.coding.executor_auth_signals import LIMIT_SIGNAL_STALE_AFTER_SECONDS

        self.assertEqual(ACCOUNT_SIGNAL_STALE_AFTER_SECONDS, LIMIT_SIGNAL_STALE_AFTER_SECONDS)

    def test_only_safe_references_are_carried(self) -> None:
        envelope = _envelope()
        named = build_account_authorization(
            envelope=envelope, account_references={"codex": "CODEX_API_KEY"}
        )
        self.assertEqual(named["accounts"][0]["reference_kind"], "env_var_name")
        self.assertEqual(named["accounts"][0]["account_ref"], "CODEX_API_KEY")
        # A value-shaped reference is not an environment variable name, so it is
        # never accepted as one.
        for unsafe in ("sk-live-0123456789abcdef", "codex_api_key", "A", ""):
            with self.subTest(unsafe=unsafe):
                block = build_account_authorization(envelope=envelope, account_references={"codex": unsafe})
                self.assertEqual(block["accounts"][0]["reference_kind"], "opaque_handle")
                self.assertEqual(block["accounts"][0]["account_ref"], "codex")

    def test_a_credential_value_that_matches_the_name_shape_is_still_refused(self) -> None:
        """An AWS key id is upper-case alphanumerics; the shape alone accepted it verbatim."""
        envelope = _envelope()
        for value in (AWS_ACCESS_KEY_ID, AWS_TEMPORARY_ACCESS_KEY_ID):
            with self.subTest(value=value):
                self.assertTrue(is_secret_value_shaped(value))
                block = build_account_authorization(
                    envelope=envelope, account_references={"codex": value}
                )
                account = block["accounts"][0]
                self.assertEqual(account["reference_kind"], "opaque_handle")
                self.assertNotIn(value, json.dumps(block))
        # And the screen stays narrow: a *name* that mentions a secret is not a
        # secret, so the ordinary case keeps working.
        for name in ("GITHUB_TOKEN", "CODEX_API_KEY", "ANTHROPIC_API_KEY"):
            with self.subTest(name=name):
                self.assertFalse(is_secret_value_shaped(name))
                block = build_account_authorization(envelope=envelope, account_references={"codex": name})
                self.assertEqual(block["accounts"][0]["reference_kind"], "env_var_name")

    def test_required_tracks_the_authority_the_task_needs_not_the_authority_it_still_has(self) -> None:
        """`required` used to report false exactly when a risky action was withheld."""
        withheld = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        self.assertNotIn("executor_dispatch", withheld["authority_envelope"]["allowed_actions"])
        block = withheld["account_authorization"]
        self.assertTrue(block["required"])
        self.assertEqual(block["accounts"][0]["minimum_scopes"], ["executor_dispatch"])
        self.assertEqual(validate_account_authorization(block), [])

    def test_a_receipt_style_credential_value_never_reaches_the_record(self) -> None:
        block = _gate()["account_authorization"]
        self.assertNotIn("secret", json.dumps(block).lower())
        self.assertIn("credential", block["credential_boundary"].lower())

    def test_the_unimplementable_half_is_declared_rather_than_faked(self) -> None:
        block = _gate()["account_authorization"]
        self.assertEqual(block["enforcement"], "declared_not_enforced")
        self.assertEqual(block["enforced_by"], [])
        self.assertEqual(block["blocked_by"], ACCOUNT_AUTHORIZATION_BLOCKER)
        self.assertEqual([entry["blocker"] for entry in block["blockers"]], list(ACCOUNT_BLOCKER_NAMES))
        consent = block["blockers"][0]
        # The approval receipt closes the adjacent gap; the honest answer is
        # that it is a different question, and the record says which.
        self.assertIn("omh.workflows.approval_receipts.approval_satisfies_request_in", consent["cites"])
        self.assertIn("different question", consent["statement"])
        self.assertIn("rendered", block["blockers"][1]["statement"])

    def test_a_projection_that_claims_enforcement_is_rejected(self) -> None:
        block = _gate()["account_authorization"]
        block.update({"enforcement": "enforced", "enforced_by": ["omh.coding.action_gate.evaluate_action_gate"], "blocked_by": ""})
        errors = validate_account_authorization(block)
        self.assertTrue(any("must stay declared_not_enforced" in error for error in errors), errors)

    def test_a_credential_value_passed_off_as_a_name_is_rejected(self) -> None:
        block = _gate()["account_authorization"]
        block["accounts"] = [
            {
                "account_ref": "sk-live-secret",
                "reference_kind": "env_var_name",
                "minimum_scopes": ["executor_dispatch"],
                "state": "missing",
                "state_source": "readiness_probe",
            }
        ]
        errors = validate_account_authorization(block)
        self.assertTrue(any("never a value" in error for error in errors), errors)

    def test_no_module_under_commands_launches_a_browser_or_an_auth_cli(self) -> None:
        """The blocker says it can only ever be rendered instructions; that has to be true."""
        source = inspect.getsource(importlib.import_module("omh.coding.action_gate"))
        for forbidden in ("webbrowser", "subprocess", "os.system", "Popen"):
            self.assertNotIn(forbidden, source)


class ContractTests(unittest.TestCase):
    """The contract changes: a flipped boundary, and the data-boundary rows."""

    def _contract(self) -> dict[str, object]:
        return build_task_handoff_safety_contract(_envelope())

    def _boundary(self, name: str) -> dict[str, object]:
        for entry in self._contract()["boundaries"]:  # type: ignore[index]
            if entry["boundary"] == name:
                return entry
        raise AssertionError(f"no boundary named {name}")

    def test_confirmation_answered_is_declared_and_names_the_missing_mint_path(self) -> None:
        """The label the code backs, not the one the design wanted.

        The gate does refuse — but only for a caller holding a run an approval
        could bind to, and the shipped delegation lane has none. A boundary that
        refuses nothing on the path users travel is `declared_not_enforced`, and
        the blocker names why rather than pointing at an issue nobody filed.
        """
        entry = self._boundary("confirmation_answered")
        self.assertEqual(entry["enforcement"], "declared_not_enforced")
        self.assertEqual(entry["enforced_by"], [])
        self.assertEqual(entry["blocked_by"], RISK_CONSENT_BLOCKER)
        self.assertIn("Nothing is withheld on the shipped lane", entry["statement"])

    def test_the_refusal_the_declaration_describes_is_real_for_a_run_bearing_caller(self) -> None:
        refused = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        self.assertEqual(refused["action_risk"]["enforcement"], "enforced")
        self.assertEqual(refused["action_risk"]["enforced_by"], list(RISK_CONSENT_ENFORCERS))
        self.assertFalse(refused["dispatchable"])
        self.assertNotIn("repo_edit", refused["authority_envelope"]["allowed_actions"])

    def test_the_dispatchable_flag_cannot_survive_an_enforced_unapproved_risky_action(self) -> None:
        verdict = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST)
        gate, _ = split_handoff_safety_contract(verdict)
        gate["dispatchable"] = True
        errors = validate_action_gate_verdict(gate)
        self.assertTrue(any("cannot stay dispatchable" in error for error in errors), errors)

    def test_a_report_only_verdict_may_stay_dispatchable_and_must_say_why(self) -> None:
        verdict = _gate(safety_preflight_request=_BROAD_WRITE_REQUEST, run_id="")
        gate, _ = split_handoff_safety_contract(verdict)
        self.assertTrue(gate["dispatchable"])
        self.assertEqual(gate["action_risk"]["decision"], "ask")
        self.assertEqual(gate["action_risk"]["enforcement"], "declared_not_enforced")
        self.assertEqual(gate["action_risk"]["blocked_by"], RISK_CONSENT_BLOCKER)
        self.assertEqual(validate_action_gate_verdict(gate), [])

    def test_the_blocker_is_a_real_property_of_the_receipt_store_and_not_a_slogan(self) -> None:
        """The claim behind the declaration: with no run, no receipt can exist."""
        from omh.workflows.approval_receipts import mint_approval_receipt_at

        with TemporaryDirectory() as tmp:
            result = mint_approval_receipt_at(
                Path(tmp) / "approval_receipts.jsonl",
                approved_action="repo_edit",
                scope_class="permission_profile",
                scope_ref="execute_with_gates",
                owner="codex",
                run_id="",
                safety_profile_revision="rev-frozen",
                confirmation_ladder="risky_action",
            )
        self.assertFalse(result["minted"])
        self.assertEqual(result["outcome"], "refused")
        self.assertIn("run_id is required", result["error"])

    def test_the_data_boundary_rows_come_from_the_801_facts_and_not_a_second_label_set(self) -> None:
        facts = data_boundary_enforcement_facts()
        by_limit = {str(limit["limit"]): limit for limit in facts["limits"]}  # type: ignore[index]
        for limit_name in DATA_BOUNDARY_LIMIT_NAMES:
            with self.subTest(limit=limit_name):
                entry = self._boundary(f"data_{limit_name}")
                limit = by_limit[limit_name]
                self.assertEqual(entry["enforcement"], "enforced" if limit["enforced_here"] else "declared_not_enforced")
                self.assertEqual(entry["enforced_by"], list(limit["enforced_by"]))
                self.assertEqual(entry["blocked_by"], limit["blocked_by"])
                self.assertTrue(entry["statement"].strip())

    def test_the_advisory_row_reports_its_own_blocker_on_a_host_with_no_backend(self) -> None:
        """A missing OS sandbox explains a host_confinement limit and nothing else.

        On a host with no confinement backend the advisory row used to report
        `no_os_confinement_backend_on_this_platform` — an OS-confinement blocker
        for a limit no OS feature could ever enforce, and a host-dependent answer
        to a host-independent question.
        """

        def _rows(backend: tuple[str, bool, str]) -> dict[str, dict[str, object]]:
            with mock.patch.object(safety_preflight_module, "_host_confinement_backend", lambda: backend):
                facts = data_boundary_enforcement_facts()
            return {str(limit["limit"]): limit for limit in facts["limits"]}  # type: ignore[index]

        capable = _rows(("sandbox-exec", True, ""))
        bare = _rows(("unsupported", False, "no_os_confinement_backend_on_this_platform"))
        advisory = "executor_honours_declared_targets"
        self.assertEqual(capable[advisory]["enforcement_kind"], "advisory")
        self.assertEqual(bare[advisory]["blocked_by"], capable[advisory]["blocked_by"])
        self.assertNotIn("confinement_backend", str(bare[advisory]["blocked_by"]))
        # The host_confinement rows still do move, which is the distinction.
        self.assertEqual(
            capable["runtime_network_confinement"]["blocked_by"],
            "fanout_lane_does_not_request_network_confinement",
        )
        self.assertEqual(
            bare["runtime_network_confinement"]["blocked_by"],
            "no_os_confinement_backend_on_this_platform",
        )

    def test_the_limit_names_are_pinned_to_the_evaluator_that_owns_them(self) -> None:
        # Mirrored rather than imported at module scope so no probe runs at
        # import time; the pin is what stops the mirror drifting.
        self.assertEqual(set(DATA_BOUNDARY_LIMIT_NAMES), set(PREFLIGHT_DATA_BOUNDARY_LIMIT_NAMES))
        self.assertEqual(DATA_BOUNDARY_NAMES, tuple(f"data_{name}" for name in DATA_BOUNDARY_LIMIT_NAMES))

    def test_the_declared_boundary_set_is_what_a_complete_install_produces(self) -> None:
        self.assertEqual(safety_boundary_names(), SAFETY_BOUNDARY_NAMES)
        self.assertIn("account_authorization", SAFETY_BOUNDARY_NAMES)
        for name in DATA_BOUNDARY_NAMES:
            self.assertIn(name, SAFETY_BOUNDARY_NAMES)

    def test_the_host_probe_is_declared_as_an_input_source_rather_than_hidden(self) -> None:
        self.assertIn("data_boundary_enforcement_facts", self._contract()["input_sources"])
        self.assertTrue(self._contract()["produced_offline"])
        # Memoized, so a delegation build does not re-probe the host.
        self.assertIs(data_boundary_facts(), data_boundary_facts())

    def test_every_newly_cited_enforcer_resolves(self) -> None:
        cited = {
            symbol
            for entry in self._contract()["boundaries"]  # type: ignore[index]
            for symbol in entry["enforced_by"]
        }
        self.assertTrue(cited)
        for symbol in sorted(cited):
            with self.subTest(symbol=symbol):
                module_name, _, attribute = symbol.rpartition(".")
                module = importlib.import_module(module_name)
                self.assertTrue(hasattr(module, attribute), f"{symbol} does not exist")


class OrdinaryCodingWorkStillFlowsTests(unittest.TestCase):
    """The overroute guard: a normal request must not gain a new prompt."""

    def test_a_normal_coding_request_never_arms_the_risky_ladder(self) -> None:
        messages = (
            _MESSAGE,
            "add pagination to src/routing/chat.py and cover it with unit tests",
            "review the changes on this branch",
            "clean up the ai slop in src/wrapper/contract.py",
        )
        for message in messages:
            for target in ("codex", "claude-code", "hermes", "generic", "choose"):
                with self.subTest(message=message, target=target):
                    payload = build_coding_delegation_payload(message, executor_target=target)
                    gate = payload["action_gate"]
                    self.assertEqual(gate["action_risk"]["decision"], "allow")
                    self.assertEqual(gate["action_risk"]["level"], "none")
                    self.assertNotEqual(gate["confirmation"]["ladder"], "risky_action")

    def test_a_request_naming_more_files_than_the_bound_is_reported_not_blocked(self) -> None:
        """No user request may end permanently non-dispatchable with no route forward.

        The class is classified and reported. The ladder is *not* armed, because
        the delegation lane has no run id and `build_approval_receipt` refuses
        an empty one, so nothing an operator could do would ever produce a
        receipt that releases the work. Arming there did not gate the request,
        it ended it.
        """
        message = "fix the broken login flow and add a regression test across " + " ".join(
            f"src/module{index}/thing.py" for index in range(MAX_UNCONFIRMED_TARGET_PATHS + 3)
        )
        payload = build_coding_delegation_payload(message, executor_target="codex")
        self.assertEqual(payload["delegation"]["action"], "delegate")
        gate = payload["action_gate"]
        risk = gate["action_risk"]
        self.assertEqual([entry["class"] for entry in risk["classes"]], ["broad_write"])
        self.assertEqual(risk["decision"], "ask")
        self.assertEqual(risk["enforcement"], "declared_not_enforced")
        self.assertEqual(risk["blocked_by"], RISK_CONSENT_BLOCKER)
        self.assertNotEqual(gate["confirmation"]["ladder"], "risky_action")
        self.assertTrue(gate["dispatchable"])
        self.assertIn("repo_edit", gate["authority_envelope"]["allowed_actions"])
        response = build_chat_response_from_delegation(payload)
        self.assertNotEqual(response["state"]["next_action"], "confirm_risky_action")

    def test_no_ordinary_request_ends_with_nothing_the_user_can_do(self) -> None:
        messages = (
            _MESSAGE,
            "refactor the auth module: update "
            + " ".join(f"src/module{index}/thing.py" for index in range(12)),
            "rewrite everything under src/",
        )
        for message in messages:
            with self.subTest(message=message[:40]):
                payload = build_coding_delegation_payload(message, executor_target="codex")
                response = build_chat_response_from_delegation(payload)
                self.assertTrue([action for action in response["actions"] if action["enabled"]])


if __name__ == "__main__":
    unittest.main()
