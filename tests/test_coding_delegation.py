from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.coding_delegation import (  # noqa: E402
    _coding_status_request_applies,
    build_coding_delegation_payload,
)


class CodingStatusAgentTermTests(unittest.TestCase):
    """pi-family executor names reach the coding status board classification.

    `_CODING_STATUS_AGENT_TERMS` matches by substring on the lowered message,
    and bare "pi" hides inside "api" and "pipeline" while the token itself is
    owned by Raspberry-Pi physical-device routing — so pi only counts through
    right-bounded forms matched at word boundaries ("raspi status" hides
    "pi status"), and never in raspberry/api context.
    """

    POSITIVE = (
        "how far along is senpi?",
        "pi 진행상황?",
        "pi 세션 상태 알려줘",
        "opencode 진행상황 알려줘",
        "omo runtime status?",
        # The incumbent names keep working alongside the pi family.
        "how far along is codex?",
        "claude code 작업 어디까지 됐어?",
    )
    NEGATIVE = (
        "raspberry pi 진행상황?",
        "raspberry pi status check",
        "api 진행상황 알려줘",
        # Word-boundary guard: "raspi status" and "spi status" contain
        # "pi status" as a raw substring without any raspberry/api blocker term.
        "raspi status check",
        "check spi status",
    )

    def test_pi_family_status_questions_apply_on_the_status_workflow(self) -> None:
        for message in self.POSITIVE:
            with self.subTest(message=message):
                self.assertTrue(_coding_status_request_applies(message.lower(), "ultrawork"))

    def test_raspberry_pi_and_api_context_never_applies(self) -> None:
        for message in self.NEGATIVE:
            with self.subTest(message=message):
                self.assertFalse(_coding_status_request_applies(message.lower(), "ultrawork"))

    def test_status_terms_only_apply_on_the_status_workflow(self) -> None:
        self.assertFalse(_coding_status_request_applies("how far along is senpi?", "loop"))

    def test_an_agent_name_without_a_status_request_never_applies(self) -> None:
        self.assertFalse(_coding_status_request_applies("senpi is a nice tool", "ultraprocess"))


class NamedCodingAgentDelegationTests(unittest.TestCase):
    """The ask bare-token retirement's prerequisite fix, now executor-neutral.

    `ask`'s bare `claude`/`gemini` catalog triggers used to be the only reason a
    request naming Claude Code outranked the retained `executor-runtime-readiness`
    workflow and produced action=delegate. Dropping those tokens without a
    replacement would silently downgrade "Claude Code로 바로 열어줘" to
    action=clarify. The delegation path now detects the named executor directly
    through `routing.coding_route_actions.named_executor_owners` -- and only
    when a single `EXTERNAL_CLI_PROFILES` member (Claude Code or Codex) is the
    sole named owner -- independent of any catalog trigger score. A user who
    names one external CLI with an imperative has already made the explicit
    owner choice, so Codex now reaches the same delegate outcome Claude Code
    always has (#1163's Directive). Naming two owners, a runtime owner such as
    Hermes coding or the omo-runtime family (pi/senpi/opencode), or asking a
    status/diagnostic question about the named executor all keep the clarify
    outcome.
    """

    def test_naming_codex_now_delegates(self) -> None:
        # Renamed from `test_naming_codex_still_clarifies`: naming Codex alone
        # with an imperative now reaches the same delegate outcome naming
        # Claude Code alone always has.
        payload = build_coding_delegation_payload("Codex로 바로 열어줘")
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(delegation["intent"], "coding")

    def test_naming_codex_with_a_coding_verb_now_delegates(self) -> None:
        payload = build_coding_delegation_payload("codex로 구현해줘")
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(delegation["intent"], "coding")

    def test_naming_two_owners_still_clarifies(self) -> None:
        payload = build_coding_delegation_payload("claude code랑 codex 중에 골라서 열어줘")
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_naming_runtime_owner_still_clarifies(self) -> None:
        # Runtime owners (Hermes coding, the omo-runtime family) are not
        # external CLIs -- `EXTERNAL_CLI_PROFILES` is only `("claude-code",
        # "codex")` -- so naming one alone keeps the retained-workflow clarify
        # outcome even with an identical imperative shape to the Codex/Claude
        # Code cases above.
        hermes_payload = build_coding_delegation_payload("Hermes coding으로 구현해줘")
        self.assertEqual(hermes_payload["delegation"]["action"], "clarify")
        omo_runtime_payload = build_coding_delegation_payload("omo runtime으로 구현해줘")
        self.assertEqual(omo_runtime_payload["delegation"]["action"], "clarify")

    def test_status_question_about_named_codex_still_clarifies(self) -> None:
        # A status/diagnostic question about the named executor is not an
        # imperative delivery request, so it must not gain the delegate
        # outcome the imperative cases above now get.
        for message in (
            "is codex broken",
            "codex 상태 어때",
            "코덱스가 지금 어디까지 했는지 알려줘",
        ):
            with self.subTest(message=message):
                payload = build_coding_delegation_payload(message)
                self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_naming_claude_code_without_a_code_reference_still_delegates(self) -> None:
        payload = build_coding_delegation_payload("Claude Code로 바로 열어줘")
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(delegation["intent"], "coding")
        self.assertEqual(delegation["recommended_workflow"], "plan")

    def test_naming_claude_code_with_a_coding_verb_still_delegates(self) -> None:
        payload = build_coding_delegation_payload("claude code로 구현해줘")
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(delegation["intent"], "coding")
        self.assertEqual(delegation["recommended_workflow"], "plan")

    def test_advisor_phrase_triggers_still_reach_ask(self) -> None:
        payload = build_coding_delegation_payload("ask claude about this design")
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(delegation["recommended_workflow"], "ask")

    def test_claude_code_hyphenated_folder_name_never_delegates(self) -> None:
        # #1163 review P3-6: plain containment on "claude-code"/"claudecode"
        # fired inside an ordinary hyphenated word, so a message that merely
        # mentions a folder name reached action=delegate off a false owner
        # detection. `named_executor_owners` now boundary-matches this group.
        payload = build_coding_delegation_payload("my repo has a folder called claudecode-notes")
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_claude_code_dotted_filename_never_delegates(self) -> None:
        payload = build_coding_delegation_payload("read the claude-code.md file")
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_bare_claude_word_never_delegates(self) -> None:
        # #1163 PR risk note: with `ask`'s bare `claude`/`gemini` triggers
        # retired, a bare one-word "claude" message no longer inflates a
        # score that used to outrank the retained workflow. Bare "claude" is
        # not the sole-named-Claude-Code-owner case (`named_executor_owners`
        # requires "claude code"/"claude-code"/"claudecode", not bare
        # "claude"), so the retained-workflow clarify outcome applies.
        payload = build_coding_delegation_payload("claude")
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_bare_gemini_word_never_delegates(self) -> None:
        payload = build_coding_delegation_payload("gemini")
        self.assertEqual(payload["delegation"]["action"], "clarify")


class ExplicitOwnerChoiceOverrideTests(unittest.TestCase):
    """An explicitly-chosen owner's brief is theirs to run regardless of genre.

    A research-shaped brief with no coding verb or file reference used to be
    refused for an already-named external owner (the retained-workflow
    clarify branch in `_action_for`), even when the operator passed
    `--executor claude-code` or the message named the owner. The override is
    additive and gated narrowly on genuine per-run provenance:
    `explicit_owner_choice=True` bypasses the genre veto only when combined
    with a real external `executor_target`; a resolved default
    (`executor_target="choose"`) never bypasses it, matching the "never a
    default" boundary in AGENTS.md.
    """

    # Deliberately free of every `coding_terms_for_intent("coding")` token
    # (add/build/change/code/fix/implement/modify/write/...) so `_intent_for`
    # falls through to the catalog's own "planning" intent for this workflow
    # instead of accidentally reading as coding-shaped -- the override is
    # scoped to `intent != "coding"`, so a fixture that collides with a
    # coding term would silently stop exercising it.
    _RESEARCH_BRIEF = (
        "Research the best pricing model for our SaaS tier and summarize the findings for the team."
    )

    def test_explicit_owner_choice_delegates_a_research_brief(self) -> None:
        payload = build_coding_delegation_payload(
            self._RESEARCH_BRIEF,
            executor_target="claude-code",
            explicit_owner_choice=True,
        )
        delegation = payload["delegation"]
        # Confirms the fixture actually exercises the genre-mismatch branch:
        # a coding-term collision would silently intent="coding" this and
        # route through a different (unrelated) branch instead.
        self.assertEqual(delegation["intent"], "planning")
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(payload["work_owner_mode"], "prompt_only_handoff")
        # The prepared RECORD stays exactly as honest as before: still
        # non-dispatchable. The override changes classification, never the
        # dispatchability contract.
        self.assertFalse(payload["dispatchable"])

    def test_explicit_owner_choice_delegates_a_research_brief_to_codex(self) -> None:
        payload = build_coding_delegation_payload(
            self._RESEARCH_BRIEF,
            executor_target="codex",
            explicit_owner_choice=True,
        )
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        self.assertEqual(payload["work_owner_mode"], "external_executor")
        self.assertTrue(payload["dispatchable"])

    def test_implicit_research_brief_still_clarifies(self) -> None:
        """Negative control: no owner named, same brief -- unchanged refusal."""
        payload = build_coding_delegation_payload(self._RESEARCH_BRIEF)
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_named_owner_without_the_explicit_flag_still_clarifies(self) -> None:
        """Negative control: an executor_target alone is not per-run provenance."""
        payload = build_coding_delegation_payload(
            self._RESEARCH_BRIEF,
            executor_target="claude-code",
        )
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_a_resolved_default_never_bypasses_the_veto(self) -> None:
        """Negative control: `executor_target="choose"` is never a choice for this run."""
        payload = build_coding_delegation_payload(
            self._RESEARCH_BRIEF,
            executor_target="choose",
            explicit_owner_choice=True,
        )
        self.assertEqual(payload["delegation"]["action"], "clarify")

    def test_a_thin_coding_shaped_message_still_clarifies_even_with_an_explicit_owner(self) -> None:
        """Negative control pinning `tests/test_cli.py`'s
        `test_runtime_delegation_status_does_not_dispatch_fallback_or_clarify`:
        a message that already reads as coding-shaped (`intent == "coding"`)
        but is too thin to name a real task keeps clarifying even with an
        explicit owner -- the override is scoped to the genre mismatch
        (`intent != "coding"`), not to every retained-workflow clarify.
        """
        payload = build_coding_delegation_payload(
            "fix maybe",
            executor_target="codex",
            explicit_owner_choice=True,
        )
        delegation = payload["delegation"]
        self.assertEqual(delegation["intent"], "coding")
        self.assertEqual(delegation["action"], "clarify")


class VerificationPathEscalationTests(unittest.TestCase):
    """Integration coverage for `verification_tiering.sensitive_path_escalation`
    wired into `_verification` (`coding_delegation.py`): a change that names a
    security-sensitive target path escalates to the thorough verification lane
    regardless of change size, and an ordinary path does not.
    """

    def test_a_named_auth_path_escalates_verification(self) -> None:
        payload = build_coding_delegation_payload(
            "fix src/auth/login.py to validate tokens correctly",
            executor_target="claude-code",
            explicit_owner_choice=True,
        )
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        verification = delegation["verification"]
        self.assertTrue(
            any("thorough verification lane" in line for line in verification),
            verification,
        )
        self.assertTrue(any("src/auth/login.py" in line for line in verification), verification)

    def test_an_ordinary_path_does_not_escalate_verification(self) -> None:
        payload = build_coding_delegation_payload(
            "fix src/foo.py to log the response body",
            executor_target="claude-code",
            explicit_owner_choice=True,
        )
        delegation = payload["delegation"]
        self.assertEqual(delegation["action"], "delegate")
        verification = delegation["verification"]
        self.assertFalse(any("thorough verification lane" in line for line in verification), verification)


class StrictSecurityPostureVerificationTests(unittest.TestCase):
    """`OMH_SECURITY=strict` escalates every request's verification, not only
    the ones `sensitive_path_escalation` recognizes by path pattern -- the
    `verification_escalate_always` row in `system.security_posture.POSTURE_MAPPING`.
    """

    def test_default_posture_leaves_an_ordinary_path_unescalated(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OMH_SECURITY", None)
            payload = build_coding_delegation_payload(
                "fix src/foo.py to log the response body",
                executor_target="claude-code",
                explicit_owner_choice=True,
            )
        verification = payload["delegation"]["verification"]
        self.assertFalse(any("thorough verification lane" in line for line in verification), verification)

    def test_strict_posture_escalates_an_ordinary_path_too(self) -> None:
        with patch.dict(os.environ, {"OMH_SECURITY": "strict"}):
            payload = build_coding_delegation_payload(
                "fix src/foo.py to log the response body",
                executor_target="claude-code",
                explicit_owner_choice=True,
            )
        verification = payload["delegation"]["verification"]
        self.assertTrue(
            any("thorough verification lane" in line for line in verification),
            verification,
        )

    def test_strict_posture_does_not_duplicate_an_already_escalated_path(self) -> None:
        with patch.dict(os.environ, {"OMH_SECURITY": "strict"}):
            payload = build_coding_delegation_payload(
                "fix src/auth/login.py to validate tokens correctly",
                executor_target="claude-code",
                explicit_owner_choice=True,
            )
        verification = payload["delegation"]["verification"]
        escalations = [line for line in verification if "thorough verification lane" in line]
        self.assertEqual(len(escalations), 1, verification)
        self.assertIn("src/auth/login.py", escalations[0])

    def test_an_unrecognized_posture_value_is_rejected_loudly(self) -> None:
        with patch.dict(os.environ, {"OMH_SECURITY": "paranoid"}):
            with self.assertRaises(ValueError) as ctx:
                build_coding_delegation_payload(
                    "fix src/foo.py to log the response body",
                    executor_target="claude-code",
                    explicit_owner_choice=True,
                )
        self.assertIn("OMH_SECURITY", str(ctx.exception))
        self.assertIn("default", str(ctx.exception))
        self.assertIn("strict", str(ctx.exception))


class CategoryPropagationTests(unittest.TestCase):
    def test_natural_ulw_category_reaches_root_and_hermes_handoff(self) -> None:
        payload = build_coding_delegation_payload(
            "Use ulw-visual-engineering to implement the dashboard",
            executor_target="hermes",
        )

        self.assertEqual(payload["model_route_category"], "visual-engineering")
        self.assertEqual(
            payload["runtime_handoff"]["model_route_category"],
            "visual-engineering",
        )

    def test_natural_alias_reaches_external_handoff_without_becoming_a_role(self) -> None:
        payload = build_coding_delegation_payload(
            "Implement a risky documentation refactor with /ulw-write",
            executor_target="codex",
        )

        self.assertEqual(payload["model_route_category"], "writing")
        self.assertEqual(payload["executor_handoff"]["model_route_category"], "writing")


class HermesNativeModelBindingTests(unittest.TestCase):
    def test_resolved_recommendation_binds_native_alias_kanban_and_delegate_metadata(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v2",
            "owner": "hermes",
            "status": "resolved",
            "source": "recommendation_chain",
            "selected": {
                "model_alias": "qwen3-coder",
                "provider": "qwen-oauth",
                "model_id": "qwen3-coder",
                "recommendation_source": "shipped_catalog",
            },
            "projection": {
                "kind": "hermes_native_binding",
                "alias": "deep",
                "provider": "qwen-oauth",
                "model_id": "qwen3-coder",
                "binding": "qwen-oauth/qwen3-coder",
                "apply_state": "approval_required",
            },
        }

        payload = build_coding_delegation_payload(
            "implement a risky refactor with Hermes",
            executor_target="hermes",
            model_recommendation=recommendation,
        )

        handoff = payload["runtime_handoff"]
        binding = handoff["hermes_native_model_binding"]
        self.assertEqual(binding["status"], "prepared_not_observed")
        self.assertEqual(binding["alias"], "deep")
        self.assertEqual(binding["provider"], "qwen-oauth")
        self.assertEqual(binding["model_id"], "qwen3-coder")
        self.assertEqual(binding["binding"], "qwen-oauth/qwen3-coder")
        self.assertEqual(binding["provenance"], "shipped_catalog")
        self.assertEqual(binding["kanban_task_override"]["command"], "set-model qwen-oauth/qwen3-coder")
        self.assertEqual(
            binding["delegate_task_override"],
            {
                "model": "qwen-oauth/qwen3-coder",
                "status": "prepared_not_observed",
            },
        )
        self.assertNotIn("maestro", str(payload).casefold())
        self.assertIn("runtime observation", binding["claim_boundary"].casefold())

    def test_last_resort_resolution_provenance_reaches_native_handoff(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v3",
            "owner": "hermes",
            "status": "resolved",
            "source": "last_resort_chain",
            "selected": {
                "model_alias": "claude-opus-5",
                "provider": "ccapi",
                "model_id": "claude-opus-5",
                "recommendation_source": "shipped_editorial",
            },
            "projection": {
                "kind": "hermes_native_binding",
                "alias": "quick",
                "provider": "ccapi",
                "model_id": "claude-opus-5",
                "binding": "ccapi/claude-opus-5",
                "apply_state": "approval_required",
            },
        }

        payload = build_coding_delegation_payload(
            "implement a risky refactor with Hermes",
            executor_target="hermes",
            model_recommendation=recommendation,
        )
        binding = payload["runtime_handoff"]["hermes_native_model_binding"]
        self.assertEqual(binding["provenance"], "last_resort_chain")

    def test_owner_default_recommendation_keeps_native_default_without_model_pin(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v2",
            "owner": "hermes",
            "status": "owner_default",
            "source": "owner_default",
            "selected": None,
            "projection": None,
            "inactive_candidates": ["gemini-3.1-pro"],
        }

        payload = build_coding_delegation_payload(
            "implement a risky refactor with Hermes",
            executor_target="hermes",
            model_recommendation=recommendation,
        )

        binding = payload["runtime_handoff"]["hermes_native_model_binding"]
        self.assertEqual(binding["status"], "owner_default")
        self.assertEqual(binding["next_action"], "use_hermes_default_model")
        self.assertEqual(binding["inactive_candidates"], ["gemini-3.1-pro"])
        self.assertNotIn("kanban_task_override", binding)
        self.assertNotIn("delegate_task_override", binding)

    def test_explicit_unavailable_recommendation_still_requires_native_setup(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v2",
            "owner": "hermes",
            "status": "choice_required",
            "source": "explicit_model",
            "selected": None,
            "projection": None,
            "inactive_candidates": ["gpt-5.6-sol"],
        }

        payload = build_coding_delegation_payload(
            "implement a risky refactor with Hermes",
            executor_target="hermes",
            model_recommendation=recommendation,
        )

        binding = payload["runtime_handoff"]["hermes_native_model_binding"]
        self.assertEqual(binding["status"], "choice_required")
        self.assertEqual(binding["next_action"], "configure_hermes_native_alias")


class DelegationContinuityBlockTests(unittest.TestCase):
    """The `delegation_continuity` block appears only under a merge/deploy directive.

    Goal 2 rides on Goal 1's `post_completion_directive`: when the user asked to
    merge or deploy, the payload carries an OMH-owned continuity block naming the
    goal-ledger record and the OMH-state-root write policy; otherwise the key is
    omitted entirely so a plain coding delegation stays byte-identical.
    """

    _MESSAGE = "fix the broken login flow in src/auth.py and add a regression test"

    def test_a_merge_directive_attaches_the_continuity_block(self) -> None:
        payload = build_coding_delegation_payload(
            f"{self._MESSAGE} then merge it", executor_target="codex"
        )
        block = payload["delegation_continuity"]
        self.assertEqual(block["schema_version"], "omh_delegation_continuity/v1")
        self.assertEqual(block["obligation"], "merge")
        self.assertEqual(block["overall_outcome_state"], "open")
        self.assertIs(block["subtask_is_not_goal"], True)
        self.assertEqual(block["durable_record"]["kind"], "goal_ledger")
        self.assertTrue(block["durable_record"]["goal_id"])
        self.assertIn(".omo", block["write_location_policy"]["forbidden_targets"])
        self.assertIn(".omx", block["write_location_policy"]["forbidden_targets"])

    def test_a_deploy_directive_attaches_a_deploy_obligation(self) -> None:
        payload = build_coding_delegation_payload(
            f"{self._MESSAGE} then deploy it", executor_target="codex"
        )
        self.assertEqual(payload["delegation_continuity"]["obligation"], "deploy")

    def test_a_plain_coding_delegation_omits_the_block(self) -> None:
        payload = build_coding_delegation_payload(self._MESSAGE, executor_target="codex")
        self.assertNotIn("delegation_continuity", payload)

    def test_the_seam_coexists_with_goal_1_directive(self) -> None:
        # Goal 1's post_completion_directive (on the handoff envelope) and Goal
        # 2's delegation_continuity (top-level) must both be present, neither
        # overwriting the other.
        payload = build_coding_delegation_payload(
            f"{self._MESSAGE} then merge it", executor_target="codex"
        )
        self.assertEqual(payload["delegation_continuity"]["obligation"], "merge")
        for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
            handoff = payload.get(key)
            if isinstance(handoff, dict):
                envelope = handoff["task_authority_envelope"]
                self.assertEqual(
                    envelope["post_completion_directive"]["action"], "merge"
                )
                break
        else:  # pragma: no cover - a dispatchable codex handoff always exists here
            self.fail("no handoff carried the authority envelope")


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
