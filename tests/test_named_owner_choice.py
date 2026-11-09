from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()


class NamedOwnersTests(unittest.TestCase):
    def named(self, text: str) -> tuple[str, ...]:
        module_name = "omh.plugin_bundle.omh.named_owner_choice"
        self.assertIsNotNone(importlib.util.find_spec(module_name), "named owner reader is missing")
        return importlib.import_module(module_name).named_owners(text)

    def test_both_owners_have_fixed_order_in_each_language(self) -> None:
        messages = (
            "/dag-ulw build the API with codex and the UI with claude code",
            "/dag-ulw APIはcodexで、UIはclaude codeで実装して",
            "/dag-ulw API는 codex로 UI는 claude code로 구현해줘",
        )
        for text in messages:
            with self.subTest(text=text):
                self.assertEqual(self.named(text), ("codex", "claude-code"))
        self.assertEqual(self.named("use CLAUDE-CODE and CODEX and codex"), ("codex", "claude-code"))

    def test_existing_executor_aliases_are_owner_names_with_an_owner_cue(self) -> None:
        for phrase in ("codex", "claude code", "claude-code", "claudecode", "코덱스", "클로드 코드", "클로드코드"):
            expected = ("codex",) if phrase in ("codex", "코덱스") else ("claude-code",)
            for text in (f"/dag-ulw build it with {phrase}", f"/dag-ulw {phrase}로 구현해줘"):
                with self.subTest(text=text):
                    self.assertEqual(self.named(text), expected)
            with self.subTest(bare=phrase):
                # A bare name is what the work is about as often as who does it.
                self.assertEqual(self.named(phrase), ())

    def test_a_cli_named_as_the_subject_is_not_a_choice(self) -> None:
        # Mutation: drop the owner-cue check; each of these then exports a node to the CLI it only names.
        for text in ("/dag-ulw fix the codex adapter tests", "/dag-ulw codex 어댑터 테스트 고쳐줘",
                     "/dag-ulw update the claude code docs", "/dag-ulw check the codex-utils.py script"):
            with self.subTest(text=text):
                self.assertEqual(self.named(text), ())

    def test_the_bundle_reads_the_cue_the_router_reads(self) -> None:
        from omh.plugin_bundle.omh import owner_cues
        from omh.routing import executor_cues

        self.assertIs(executor_cues.owner_named_as_doer, owner_cues.owner_named_as_doer)

    def test_bare_advisor_names_and_embedded_words_are_not_choices(self) -> None:
        for text in ("/dag-ulw build it; claude only reviews", "claude and gemini", "precodex codexify"):
            with self.subTest(text=text):
                self.assertEqual(self.named(text), ())

    def test_adjacent_negation_drops_only_that_owner_in_each_language(self) -> None:
        templates = (
            ("no {name}", "not {name}", "without {name}", "don't use {name}",
             "except {name}", "do not use {name}", "don’t use {name}"),
            ("{name}以外", "{name}なし", "{name}を使わず"),
            ("{name} 말고", "{name} 빼고", "{name} 없이", "{name} 제외", "{name}는 말고"),
        )
        for forms in templates:
            for form in forms:
                for phrase, other in (("codex", "claude-code"), ("claude code", "codex")):
                    with self.subTest(form=form, phrase=phrase):
                        self.assertEqual(self.named(form.format(name=phrase) + "; use " + other), (other,))
        self.assertEqual(self.named("no latency regressions; use codex"), ("codex",))


class TurnOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from omh.plugin_bundle.omh import named_owner_choice

        self.module = named_owner_choice
        named_owner_choice.reset_turn_owners()
        self.addCleanup(named_owner_choice.reset_turn_owners)

    def test_each_turn_replaces_the_sessions_owners(self) -> None:
        note, owners = self.module.note_turn_owners, self.module.turn_owners
        self.assertEqual(note("s1", "/dag-ulw build it with codex and claude code"), ("codex", "claude-code"))
        self.assertEqual(note("s2", "/dag-ulw build it with claude code"), ("claude-code",))
        self.assertEqual(owners("s1"), ("codex", "claude-code"))
        self.module.clear_turn_owners("s1")
        self.assertEqual((owners("s1"), owners("s2")), ((), ("claude-code",)))
        self.assertEqual(owners(""), ())

    def test_non_invocations_and_negated_owners_record_none(self) -> None:
        for text in ("build the API with codex", "/dag-ulw build the API with claude only reviewing",
                     "/dag-ulw what is it, codex?", "/dag-ulw build it without codex"):
            with self.subTest(text=text):
                self.module.note_turn_owners("s1", "/dag-ulw build it with codex")
                self.assertEqual(self.module.note_turn_owners("s1", text), ())
                self.assertEqual(self.module.turn_owners("s1"), ())

    def test_the_oldest_session_is_forgotten_first(self) -> None:
        for index in range(self.module.MAX_TRACKED_SESSIONS + 1):
            self.module.note_turn_owners(f"s{index}", "/dag-ulw build it with codex")
        self.assertEqual(self.module.turn_owners("s0"), ())
        self.assertEqual(self.module.turn_owners(f"s{self.module.MAX_TRACKED_SESSIONS}"), ("codex",))


class NamedOwnerHookTests(unittest.TestCase):
    MESSAGE = "/dag-ulw build the API with codex"

    def setUp(self) -> None:
        from omh.plugin_bundle.omh.named_owner_choice import reset_turn_owners

        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "omh"
        self.hermes = Path(self.tmp.name) / "hermes"
        self.path = self.home / "routing" / "owner-preference.json"
        self.session = "named-owner-test"
        reset_turn_owners()
        self.addCleanup(reset_turn_owners)

    def hook(self, message: str = MESSAGE, **kwargs):
        from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
        return pre_llm_call(
            omh_home=str(self.home), hermes_home=str(self.hermes), session_id=self.session,
            user_message=message, is_first_turn=False, **kwargs,
        ) or {}

    def owners(self) -> tuple[str, ...]:
        from omh.plugin_bundle.omh.named_owner_choice import turn_owners
        return turn_owners(self.session)

    def test_person_request_names_codex_for_this_turn_only(self) -> None:
        self.hook()
        self.assertEqual(self.owners(), ("codex",), "person's dag-ulw naming did not reach the turn marker")
        self.assertFalse(self.path.exists(), "a turn's naming is not a stored choice")
        self.hook("/dag-ulw build the next feature")
        self.assertEqual(self.owners(), ())

    def test_delegated_child_cannot_name_its_own_owner(self) -> None:
        from omh.plugin_bundle.omh.hooks.nudge_budget import note_delegated_session
        note_delegated_session(self.session, omh_home=str(self.home))
        self.hook()
        self.assertEqual(self.owners(), ())

    def test_host_synthesized_turn_cannot_name_an_owner(self) -> None:
        self.hook(conversation_history=[{"role": "user", "content": self.MESSAGE,
                                         "display_kind": "internal_notification"}])
        self.assertEqual(self.owners(), ())

    def test_command_turn_cannot_name_an_owner(self) -> None:
        from omh.plugin_bundle.omh.dag_ulw_cues import invokes_dag_ulw
        from omh.plugin_bundle.omh.hermes_session_commands import host_command_turn
        message = "[Heartbeat — recurring instruction, fires every 5m]\nBuild the API with dag ulw and codex"
        self.assertTrue(host_command_turn(message))
        self.assertTrue(invokes_dag_ulw(message))
        self.hook(message)
        self.assertEqual(self.owners(), ())

    def test_tracker_event_cannot_name_an_owner(self) -> None:
        self.hook(tracker_event={"provider": "github", "tracker_content": self.MESSAGE})
        self.assertEqual(self.owners(), ())

    def test_only_person_request_can_name_the_owner(self) -> None:
        message = '[Replying to Alex: "use codex"]\n\n/dag-ulw build the API'
        self.hook(message, platform="discord")
        self.assertEqual(self.owners(), ())

    def test_a_host_written_turn_clears_the_previous_requests_owner(self) -> None:
        self.hook()
        self.hook(tracker_event={"provider": "github", "tracker_content": "ci finished"})
        self.assertEqual(self.owners(), ())

    def test_a_dag_ulw_request_about_a_cli_exports_nothing_to_it(self) -> None:
        from _delegation_state import PARENT, homes
        from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
        from test_dag_tool import call, node, slots_table

        with homes() as home:
            slots_table(home)
            pre_llm_call(omh_home=str(home.omh), hermes_home=str(home.hermes), session_id=PARENT,
                         user_message="/dag-ulw fix the codex adapter tests", is_first_turn=False)
            result = call(action="define", run="feat", nodes=[node("api", scope=("api.py",), owner="codex")])
            refused = call(action="export", run="feat", owner="codex")
        self.assertEqual(result["exports"], [], result)
        self.assertEqual(refused["reason"], "owner_not_chosen")

    def test_the_hooks_turn_marker_reaches_omh_dag_define(self) -> None:
        from _delegation_state import PARENT, homes
        from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
        from test_dag_tool import call, node, slots_table

        with homes() as home:
            slots_table(home)
            pre_llm_call(omh_home=str(home.omh), hermes_home=str(home.hermes), session_id=PARENT,
                         user_message=self.MESSAGE, is_first_turn=False)
            result = call(action="define", run="feat", nodes=[node("api", scope=("api.py",), owner="codex")])
            self.assertEqual(result["export"]["nodes"], ["api"], result)
            pre_llm_call(omh_home=str(home.omh), hermes_home=str(home.hermes), session_id=PARENT,
                         user_message="/dag-ulw build the docs", is_first_turn=False)
            later = call(action="define", run="docs", nodes=[node("doc", scope=("doc.py",), owner="codex")])
            self.assertEqual(later["exports"], [], later)

if __name__ == "__main__":
    unittest.main()
