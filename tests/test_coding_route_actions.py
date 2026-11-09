from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unicodedata
import unittest

from _local_package import load_local_package
from _standalone_bundle import _load_standalone_bundle_awareness

load_local_package()

from omh.paths import resolve_paths
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.profiles.setup import write_setup_profile
from omh.routing.action_copy import NEXT_ACTION_LABELS
from omh.routing.executor_cues import (
    CODING_DELIVERY_REQUEST_PHRASES,
    NAMED_CODING_AGENT_PHRASES,
    PI_FAMILY_CODING_AGENT_PHRASES,
    SUBSTRING_NAMED_CODING_AGENT_PHRASES,
)
from omh.routing.coding_route_actions import (
    CODING_ROUTE_DECISION_SOURCES,
    CODING_ROUTE_LANE_NEXT_ACTION,
    CODING_ROUTE_NEXT_ACTIONS,
    COMPATIBLE_ROUTE_NEXT_ACTION,
    NAMED_EXECUTOR_NEXT_ACTION,
    RECORDED_OWNER_NEXT_ACTION,
    USER_CHOICE_NEXT_ACTION,
    named_coding_agent_phrase_parity,
    named_executor_owners,
    resolve_coding_route_decision,
)
from omh.routing.localization import normalized_phrase
from omh.routing.owner_preference import (
    empty_owner_preference_state,
    record_accepted_explicit_choice,
)
from omh.wrapper.contract import build_chat_interaction_payload
from omh.coding.pi_family_interop import PI_DISTRIBUTION_HOST, RUNTIME_USER_PHRASE


# One message per coding-delivery route-hint site. Direct `ultraprocess`, broad
# `coding_delivery`, and `test_until_pass_delivery` have to answer the coding-owner
# question the same way, so they are asserted together rather than one by one.
CODING_DELIVERY_SITE_MESSAGES: tuple[tuple[str, str], ...] = (
    ("direct_workflow_invocation", "Use OMH ultraprocess for: improve README and open PR"),
    ("coding_delivery", "implement the dark mode toggle and open a pr"),
    ("test_until_pass_delivery", "테스트 통과할때까지 고쳐줘"),
)

# Overroute guards: advisor, customer-signal, and executor-comparison requests. None of
# them is an unambiguous delivery request, so none of them may auto-select a coding owner.
NON_CODING_DELIVERY_MESSAGES: tuple[tuple[str, str], ...] = (
    ("advisor", "ask claude for a second opinion on this plan"),
    ("customer_signal", "users report a bug in the checkout page"),
    ("customer_signal_ko", "고객들이 결제 실패 이슈를 계속 제보해요"),
    ("executor_comparison", "should i use codex or claude code for this?"),
)

# Customer-signal work stays on the feedback lane, so it never reaches a coding-owner
# decision at all. Kept separate because awareness has no advisor lane of its own.
CUSTOMER_SIGNAL_MESSAGES: tuple[str, ...] = (
    "users report a bug in the checkout page",
    "고객들이 결제 실패 이슈를 계속 제보해요",
)


def _decision(message: str, **kwargs: str):
    return resolve_coding_route_decision(normalized_phrase(message), **kwargs)


def _learned_owner_state(owner: str = "codex") -> dict[str, object]:
    state = empty_owner_preference_state()
    for index in range(3):
        state = record_accepted_explicit_choice(
            state,
            route_family="ulw-coding-delivery",
            selected_owner=owner,
            occurred_at=f"2026-08-13T00:00:0{index + 1}Z",
        )
    return state



class CodingRouteActionVocabularyTests(unittest.TestCase):
    def test_four_states_resolve_to_four_distinct_next_actions(self) -> None:
        named = _decision("use codex to fix the login bug")
        recorded = _decision("implement the dark mode toggle and open a pr", recorded_owner="claude-code")
        automatic = _decision("implement the dark mode toggle in a worktree with parallel workers")
        fallback = _decision("implement the dark mode toggle and open a pr")

        self.assertEqual(named.next_action, NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(recorded.next_action, RECORDED_OWNER_NEXT_ACTION)
        self.assertEqual(automatic.next_action, COMPATIBLE_ROUTE_NEXT_ACTION)
        self.assertEqual(fallback.next_action, USER_CHOICE_NEXT_ACTION)

        actions = {named.next_action, recorded.next_action, automatic.next_action, fallback.next_action}
        self.assertEqual(len(actions), 4)
        self.assertEqual(actions, set(CODING_ROUTE_NEXT_ACTIONS))

    def test_every_coding_route_action_has_a_route_label(self) -> None:
        for action in CODING_ROUTE_NEXT_ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, NEXT_ACTION_LABELS)
                self.assertTrue(NEXT_ACTION_LABELS[action].strip())
        self.assertIn(CODING_ROUTE_LANE_NEXT_ACTION, NEXT_ACTION_LABELS)

    def test_owner_phrase_groups_still_cover_the_policy_executor_names(self) -> None:
        self.assertTrue(named_coding_agent_phrase_parity())

    def test_control_plane_and_bundle_read_one_definition_of_the_phrase_groups(self) -> None:
        # The groups are defined once in the bundle; the control plane
        # re-exports them and awareness imports them unconditionally, so there
        # is no copy left to drift -- the names are the same objects.
        from omh.plugin_bundle.omh import awareness
        from omh.plugin_bundle.omh import executor_cues as bundle_cues
        from omh.routing import executor_cues as routing_cues

        for name in (
            "SUBSTRING_NAMED_CODING_AGENT_PHRASES",
            "PI_FAMILY_CODING_AGENT_PHRASES",
            "NAMED_CODING_AGENT_PHRASES",
            "CODING_DELIVERY_REQUEST_PHRASES",
            "CODING_DELIVERY_REQUEST_TOKENS",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(routing_cues, name), getattr(bundle_cues, name))
                if hasattr(awareness, f"_{name}"):
                    self.assertIs(getattr(awareness, f"_{name}"), getattr(bundle_cues, name))
        awareness_source = Path(awareness.__file__).read_text(encoding="utf-8")
        for name in ("_SUBSTRING_NAMED_CODING_AGENT_PHRASES", "_CODING_DELIVERY_REQUEST_PHRASES"):
            with self.subTest(no_copy=name):
                self.assertNotIn(f"{name} = ", awareness_source)

    def test_phrase_groups_keep_their_documented_members_and_absences(self) -> None:
        # Bare "claude" and "gemini" are advisor names as often as executor
        # names; bare "pi" (and "with pi" / "pi로") hides inside "api", "pip",
        # "pipeline"; bare "클로드" stays out the same way bare "claude" does.
        for absent in ("claude", "gemini", "pi", "with pi", "pi로", "클로드"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, NAMED_CODING_AGENT_PHRASES)
        for present in ("pi한테", "pi에게", "클로드 코드", "헤르메스 코딩"):
            with self.subTest(present=present):
                self.assertIn(present, NAMED_CODING_AGENT_PHRASES)
        for present in ("해줘", "맡겨", "実装", "直して", "修复"):
            with self.subTest(present=present):
                self.assertIn(present, CODING_DELIVERY_REQUEST_PHRASES)
        # Japanese entries avoid dakuten/handakuten because `normalized_phrase`
        # strips combining marks.
        for phrase in CODING_DELIVERY_REQUEST_PHRASES:
            with self.subTest(phrase=phrase):
                decomposed = unicodedata.normalize("NFKD", phrase)
                self.assertNotIn("゙", decomposed)
                self.assertNotIn("゚", decomposed)
        self.assertEqual(
            NAMED_CODING_AGENT_PHRASES,
            (*SUBSTRING_NAMED_CODING_AGENT_PHRASES, *PI_FAMILY_CODING_AGENT_PHRASES),
        )

    def test_vendored_awareness_delivery_signal_applies_the_boundary_rule(self) -> None:
        # The vendored delivery signal must reject the same embedded-substring
        # shapes the source surfaces reject, and keep the pi-family positives,
        # in both the standalone bundle load and in-repo modules.
        from omh.plugin_bundle.omh import awareness as bundled

        for awareness in (_load_standalone_bundle_awareness(), bundled):
            signal = awareness._named_coding_agent_delivery_signal
            self.assertTrue(signal("tell pi to fix the flaky test", {"fix"}))
            self.assertTrue(signal("opencode로 이 버그 고쳐줘", set()))
            self.assertFalse(signal("promo runtime 로그 확인하는 코드 짜줘", set()))
            self.assertFalse(signal("api한테 요청 보내는 코드 짜줘", set()))

    def test_automatic_route_carries_source_reason_and_confidence(self) -> None:
        automatic = _decision("implement the dark mode toggle in a worktree with parallel workers")

        self.assertEqual(automatic.source, "request_capability_match")
        self.assertEqual(automatic.confidence, "medium")
        self.assertEqual(automatic.selected_route_family, "runtime_handoff")
        self.assertTrue(automatic.reason.strip())
        self.assertTrue(automatic.matched_cues)
        self.assertFalse(automatic.choice_required)
        # An automatic route names a compatible handoff shape, never a vendor to dispatch.
        self.assertEqual(automatic.selected_owner, "")

    def test_named_and_recorded_states_report_the_owner_and_its_source(self) -> None:
        named = _decision("codex로 이 버그 고쳐줘")
        recorded = _decision("implement the dark mode toggle and open a pr", recorded_owner="omx-runtime")

        self.assertEqual(named.selected_owner, "codex")
        self.assertEqual(named.source, "request_named_executor")
        self.assertEqual(named.confidence, "high")
        self.assertEqual(recorded.selected_owner, "omx-runtime")
        self.assertEqual(recorded.source, "recorded_setup_preference")
        self.assertEqual(recorded.confidence, "high")

    def test_caller_fixed_executor_target_is_a_named_executor_state(self) -> None:
        decision = _decision("implement the dark mode toggle and open a pr", requested_owner="claude-code")

        self.assertEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(decision.selected_owner, "claude-code")
        self.assertFalse(decision.choice_required)

    def test_pi_family_cues_resolve_the_pi_family_runtime_owner(self) -> None:
        for message in (
            "have pi implement the retry fix",
            "ask pi to fix the login bug",
            "tell pi to fix the flaky test",
            "delegate to pi: fix the login bug",
            "pi한테 이 버그 고치라고 해줘",
            "pi에게 이 이슈 맡겨서 고쳐줘",
            f"have {PI_DISTRIBUTION_HOST} fix the login bug",
            "opencode로 이 버그 고쳐줘",
            f"{RUNTIME_USER_PHRASE}으로 이 버그 고쳐줘",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "pi-family-runtime")
                self.assertFalse(decision.choice_required)


class OwnerCueTests(unittest.TestCase):
    """An owner named in a message counts only as the doer, on positive evidence (#2679 review).

    Each negative names a CLI as what the work is about; each positive names it with an owner cue. A new cue
    form joins `routing/executor_cues.py` with a case here on each side.
    """

    NOT_AN_OWNER = (
        # The CLI is the subject of the work, not who does it.
        "fix the codex adapter tests and open a pr",
        "codex 어댑터 테스트 고쳐줘",
        "update the claude code docs",
        "rename the opencode config loader",
        "fix the bug in codex adapter",
        # Filenames and hyphenated words were never owner names.
        "check the codex-utils.py script",
        "read the claude-code.md file",
        # A negated cue chooses nothing.
        "don't use codex for this",
        "codex로 하지 마",
        # A status question names the CLI it asks about; the wrapper keeps it as the card's subject only.
        "codex 세션 지금 실행 중이야?",
        # Beside each addressed form (#2679 r3): a question, a noun after "get", a capability, a topic.
        "codex가 왜 죽어",
        "codex, is it free?",
        "get the codex logs",
        "can codex read pdfs?",
        "codexに関する資料",
        # Where the work is, not who does it: the safety net asks when a different CLI would run.
        "fix the login bug in codex",
        "codex에서 로그인 버그 고쳐줘",
    )
    OWNER = (
        ("use codex to fix the login bug", ("codex",)),
        ("fix the login bug with codex and open a pr", ("codex",)),
        ("using claude code, fix the login bug", ("claude-code",)),
        ("have claude code fix the login bug", ("claude-code",)),
        ("let codex handle the parser fix", ("codex",)),
        ("open this in codex and prepare the coding handoff", ("codex",)),
        ("codex 세션 켜서 작업 시작하게 해줘", ("codex",)),
        ("claude code 작업 세션 열어줘", ("claude-code",)),
        ("open a codex session for the parser fix", ("codex",)),
        ("codex로 이 버그 고쳐줘", ("codex",)),
        ("codex한테 맡겨줘", ("codex",)),
        ("codex 써서 고쳐줘", ("codex",)),
        ("클로드 코드로 구현해줘", ("claude-code",)),
        ("claude-code로 열어줘", ("claude-code",)),
        ("opencode로 이 버그 고쳐줘", ("pi-family-runtime",)),
        ("use codex or claude code to fix the login bug", ("codex", "claude-code")),
        ("codex 말고 claude code로 구현해줘", ("claude-code",)),
        # The CLI addressed as the one to act (#2679 r3).
        ("codex가 로그인 버그 고쳐줘", ("codex",)),
        ("codex가 해줘", ("codex",)),
        ("claude code가 이거 구현해줘", ("claude-code",)),
        ("codex, fix the login bug and open a pr", ("codex",)),
        ("get codex to fix the login bug", ("codex",)),
        ("codex please fix the login bug", ("codex",)),
        ("can codex fix the login bug", ("codex",)),
        ("codexにログインバグを直させて", ("codex",)),
    )

    def test_a_cli_named_as_the_subject_is_not_an_owner(self) -> None:
        # Mutation: match a bare owner name again (`contains_boundary_phrase`); every case here then names one.
        for message in self.NOT_AN_OWNER:
            with self.subTest(message=message):
                self.assertEqual(named_executor_owners(normalized_phrase(message)), ())

    def test_an_owner_cue_names_the_owner(self) -> None:
        for message, owners in self.OWNER:
            with self.subTest(message=message):
                self.assertEqual(named_executor_owners(normalized_phrase(message)), owners)

    def test_a_mention_that_is_not_the_doer_never_runs_a_different_profile_cli(self) -> None:
        # Mutation: drop the safety net; the profile default (claude-code) then runs with codex named in the request.
        for message in ("fix the login bug in codex", "codex에서 로그인 버그 고쳐줘", "fix the codex adapter tests"):
            with self.subTest(message=message):
                decision = _decision(message, recorded_owner="claude-code")
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertEqual(decision.offered_owner, "codex")
        # No conflict: the profile names the mentioned CLI, or Hermes, which starts no CLI.
        self.assertEqual(_decision("fix the login bug in codex", recorded_owner="codex").next_action,
                         RECORDED_OWNER_NEXT_ACTION)
        self.assertEqual(_decision("fix the login bug in codex", recorded_owner="hermes").next_action,
                         RECORDED_OWNER_NEXT_ACTION)

    def test_the_wrapper_reads_the_same_cue(self) -> None:
        from omh.wrapper.contract import executor_target_named_in_message

        for message in self.NOT_AN_OWNER:
            with self.subTest(message=message):
                self.assertEqual(executor_target_named_in_message(message), "")
        for message, owners in self.OWNER:
            # The wrapper's own name table spells the pi family by its runtime names, not by "opencode".
            if owners != ("pi-family-runtime",):
                with self.subTest(message=message):
                    # Two owners named as the doer are the user's choice: the wrapper names neither.
                    self.assertEqual(executor_target_named_in_message(message), owners[0] if len(owners) == 1 else "")


class CodingRouteActionGuardTests(unittest.TestCase):
    """Negative guards: the explicit user-choice path must survive every unsafe case."""

    def test_unset_recorded_owner_is_not_a_preference(self) -> None:
        for recorded_owner in ("", "choose", "  ", "CHOOSE"):
            with self.subTest(recorded_owner=recorded_owner):
                decision = _decision("implement the dark mode toggle and open a pr", recorded_owner=recorded_owner)
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertTrue(decision.choice_required)

    def test_two_named_executors_stay_a_user_choice(self) -> None:
        decision = _decision("use codex or claude code to fix the login bug")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision.choice_required)
        self.assertEqual(decision.selected_owner, "")

    def test_two_route_families_stay_a_user_choice(self) -> None:
        decision = _decision("give me the prompt and also run parallel workers in a worktree")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertEqual(decision.selected_route_family, "")

    def test_merge_and_production_authority_outranks_a_named_executor(self) -> None:
        for message in (
            "use codex to implement this and merge to main",
            "codex로 고치고 프로덕션에 배포해줘",
            "have claude code fix this and force push the branch",
        ):
            with self.subTest(message=message):
                decision = _decision(message)
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertTrue(decision.choice_required)

    def test_authority_cue_outranks_a_recorded_preference(self) -> None:
        decision = _decision("implement this and merge to main", recorded_owner="codex")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision.choice_required)

    def test_authority_cue_outranks_a_caller_fixed_executor_target(self) -> None:
        decision = _decision("implement this and merge to main", requested_owner="codex")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision.choice_required)

    def test_raspberry_pi_and_pip_context_never_name_the_pi_family_runtime_owner(self) -> None:
        # Bare "pi" belongs to Raspberry-Pi physical-device routing, and "pi"
        # is a substring of "pip"; neither may name the pi-family-runtime executor.
        for message in (
            "raspberry pi relay",
            "deploy to my pi 5",
            "raspberry pi에 배포",
            "fix the build with pip install",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertNotEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "")

    def test_hyphenated_and_dotted_filenames_never_name_the_claude_code_owner(self) -> None:
        # #1163 review P3-6: plain containment on "claude-code"/"claudecode"
        # fired inside an ordinary hyphenated word or filename, so a message
        # that only mentions a folder or file falsely named the executor.
        for message in (
            "my repo has a folder called claudecode-notes",
            "read the claude-code.md file",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertNotEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "")

    def test_hyphenated_and_dotted_filenames_never_name_the_codex_owner(self) -> None:
        # Same hole, same fix, for the codex owner group.
        for message in (
            "my repo has a folder called codexnotes",
            "check the codex-utils.py script",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertNotEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "")

    def test_claude_code_and_codex_boundary_positives_still_resolve_the_owner(self) -> None:
        # The boundary fix must not regress the legitimate mentions, including
        # Korean particles attached directly to the Latin name.
        for message, owner in (
            ("Claude Code로 바로 열어줘", "claude-code"),
            ("claude code로 구현해줘", "claude-code"),
            ("claude-code로 열어줘", "claude-code"),
            ("use codex to fix the login bug", "codex"),
            ("codex로 이 버그 고쳐줘", "codex"),
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, owner)

    def test_three_accepted_choices_then_a_fourth_request_still_asks(self) -> None:
        # Mutation: restore `use_learned_default`; the fourth request then picks codex without asking.
        state = empty_owner_preference_state()

        for index in range(3):
            decision = _decision(
                "implement the dark mode toggle and open a pr",
                owner_preference_state=state,
            )
            self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
            self.assertEqual(decision.owner_preference_action, "ask_explicit_owner")
            self.assertEqual(decision.owner_preference_evidence_count, index)
            state = record_accepted_explicit_choice(
                state,
                route_family="ulw-coding-delivery",
                selected_owner="codex",
                occurred_at=f"2026-08-13T00:00:0{index + 1}Z",
            )

        fourth = _decision(
            "implement the dark mode toggle and open a pr",
            owner_preference_state=state,
        )

        self.assertEqual(fourth.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertEqual(fourth.source, "user_choice_required")
        self.assertTrue(fourth.choice_required)
        self.assertEqual(fourth.selected_owner, "")
        self.assertEqual(fourth.owner_preference_action, "ask_explicit_owner")
        self.assertEqual(fourth.owner_preference_reason_code, "explicit_choice_required")
        self.assertEqual(fourth.owner_preference_evidence_count, 3)
        self.assertFalse(fourth.owner_preference_override_available)
        self.assertFalse(fourth.owner_preference_reset_available)
        self.assertNotIn("learned_owner_preference", CODING_ROUTE_DECISION_SOURCES)

    def test_explicit_owner_and_safety_gates_outrank_learned_default(self) -> None:
        state = _learned_owner_state()
        named = _decision(
            "have claude code fix the login bug",
            owner_preference_state=state,
        )
        self.assertEqual(named.next_action, NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(named.selected_owner, "claude-code")
        self.assertEqual(named.owner_preference_reason_code, "owner_named_in_request")

        cases = (
            (
                "use codex or claude code to fix the login bug",
                {},
                "multiple_owners_named",
            ),
            (
                "implement this and merge to main",
                {},
                "authority_requires_choice",
            ),
            (
                "implement the dark mode toggle and open a pr",
                {"owner_ready": False},
                "owner_unready",
            ),
            (
                "implement the dark mode toggle and open a pr",
                {"capability_fit": False},
                "capability_gap",
            ),
        )
        for message, flags, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                decision = _decision(
                    message,
                    owner_preference_state=state,
                    **flags,
                )
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertTrue(decision.choice_required)
                self.assertEqual(decision.owner_preference_reason_code, reason_code)

        bypass = _decision(
            "summarize this paragraph",
            owner_preference_state=state,
            coding_delivery=False,
        )
        self.assertEqual(bypass.owner_preference_action, "bypass_owner_learning")
        self.assertEqual(bypass.owner_preference_reason_code, "non_coding_workflow")
        self.assertEqual(bypass.selected_owner, "")

    def test_embedded_pi_family_substrings_never_name_the_pi_family_runtime_owner(self) -> None:
        # Word-boundary guard: as raw substrings a word ending in the runtime's
        # short name contains its runtime phrase, and "api한테" contains "pi한테", so containment alone
        # named an executor these messages never mention.
        for message in (
            "promo runtime 로그 확인하는 코드 짜줘",
            "api한테 요청 보내는 코드 짜줘",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertNotEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "")


class CodingRouteHintTests(unittest.TestCase):
    def test_every_coding_delivery_site_reports_the_same_lane_and_decision_shape(self) -> None:
        for site, message in CODING_DELIVERY_SITE_MESSAGES:
            with self.subTest(site=site, message=message):
                hint = awareness_route_hint(message)
                decision = hint["primary_coding_route_decision"]

                self.assertEqual(hint["primary_workflow"], "ulw-work")
                self.assertEqual(hint["primary_next_action"], CODING_ROUTE_LANE_NEXT_ACTION)
                self.assertEqual(hint["hints"][0]["coding_route_decision"], decision)
                self.assertEqual(decision["schema_version"], "coding_route_decision/v1")
                self.assertIn(decision["next_action"], CODING_ROUTE_NEXT_ACTIONS)
                self.assertEqual(decision["lane_next_action"], CODING_ROUTE_LANE_NEXT_ACTION)
                self.assertEqual(decision["user_choice_next_action"], USER_CHOICE_NEXT_ACTION)
                self.assertIn("not executor dispatch", decision["claim_boundary"])

    def test_named_executor_request_reports_the_named_executor_state(self) -> None:
        hint = awareness_route_hint("claude code로 이 이슈 해결해줘")
        decision = hint["primary_coding_route_decision"]

        self.assertEqual(hint["primary_next_action"], CODING_ROUTE_LANE_NEXT_ACTION)
        self.assertEqual(decision["next_action"], NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(decision["selected_owner"], "claude-code")
        self.assertFalse(decision["choice_required"])

    def test_unresolved_request_keeps_the_explicit_user_choice_path(self) -> None:
        hint = awareness_route_hint("테스트 통과할때까지 고쳐줘")
        decision = hint["primary_coding_route_decision"]

        self.assertEqual(decision["next_action"], USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision["choice_required"])
        self.assertEqual(hint["hints"][0]["fallback_action"], "choose_coding_agent_or_runtime")

    def test_route_hints_stay_prepared_and_never_claim_execution(self) -> None:
        for _site, message in CODING_DELIVERY_SITE_MESSAGES:
            with self.subTest(message=message):
                hint = awareness_route_hint(message)

                self.assertTrue(hint["hints"][0]["not_evidence_yet"])
                self.assertIn("not workflow execution", hint["claim_boundary"])

    def test_non_delivery_requests_never_auto_select_a_coding_owner(self) -> None:
        for guard, message in NON_CODING_DELIVERY_MESSAGES:
            with self.subTest(guard=guard, message=message):
                for item in awareness_route_hint(message)["hints"]:
                    decision = item.get("coding_route_decision")
                    if decision is None:
                        continue
                    self.assertEqual(decision["next_action"], USER_CHOICE_NEXT_ACTION)
                    self.assertTrue(decision["choice_required"])
                    self.assertEqual(decision["selected_owner"], "")
                    self.assertEqual(decision["selected_route_family"], "")

    def test_customer_signal_requests_never_reach_a_coding_owner_decision(self) -> None:
        for message in CUSTOMER_SIGNAL_MESSAGES:
            with self.subTest(message=message):
                hint = awareness_route_hint(message)

                self.assertEqual(hint["primary_workflow"], "feedback-triage")
                self.assertIsNone(hint["primary_coding_route_decision"])
                for item in hint["hints"]:
                    self.assertNotIn("coding_route_decision", item)

    def test_coding_status_requests_are_not_coding_delivery_decisions(self) -> None:
        hint = awareness_route_hint("codex 세션 지금 실행 중이야?")

        self.assertEqual(hint["primary_next_action"], "show_coding_handoff_status")
        self.assertIsNone(hint["primary_coding_route_decision"])


class CodingRouteDecisionWrapperTests(unittest.TestCase):
    def test_recorded_setup_preference_is_its_own_wrapper_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="codex")

            payload = build_chat_interaction_payload(
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="discord",
                mode="delegate",
                paths=paths,
            )

        decision = payload["coding_route_decision"]
        self.assertEqual(decision["next_action"], RECORDED_OWNER_NEXT_ACTION)
        self.assertEqual(decision["source"], "recorded_setup_preference")
        self.assertEqual(decision["selected_owner"], "codex")
        self.assertFalse(decision["choice_required"])
        self.assertEqual(payload["delegation"]["coding_route_decision"], decision)
        # The decision explains ownership; it never upgrades the handoff into dispatch.
        self.assertIn(payload["delegation"]["dispatch_policy"], {"prepare_only", "ask_before_dispatch"})

    def test_wrapper_without_a_recorded_owner_keeps_the_user_choice_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            payload = build_chat_interaction_payload(
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="discord",
                mode="delegate",
                paths=paths,
            )

        decision = payload["coding_route_decision"]
        self.assertEqual(decision["next_action"], USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision["choice_required"])


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
