from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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
        self.assertEqual(self.named("CLAUDE-CODE and CODEX and codex"), ("codex", "claude-code"))

    def test_existing_executor_aliases_are_owner_names(self) -> None:
        groups = (
            ("codex", "claude code", "claude-code", "claudecode"),
            ("codex", "claude code"),
            ("코덱스", "클로드 코드", "클로드코드"),
        )
        for phrases in groups:
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    expected = "codex" if phrase in ("codex", "코덱스") else "claude-code"
                    self.assertEqual(self.named(phrase), (expected,))

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


class NamedOwnerPersistenceTests(unittest.TestCase):
    NOW = "2026-11-06T00:00:00Z"
    LATER = "2026-11-06T01:00:00Z"
    MESSAGE = "/dag-ulw build the private-customer-widget with codex and claude code"

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.path = self.home / "routing" / "owner-preference.json"

    def record(self, text: str = MESSAGE, now: str = NOW) -> tuple[str, ...]:
        module = importlib.import_module("omh.plugin_bundle.omh.named_owner_choice")
        self.assertTrue(hasattr(module, "record_named_owner_choices"), "named owner writer is missing")
        return module.record_named_owner_choices(self.home, text, now_iso=now)

    def test_both_choices_are_private_valid_and_readable_by_router(self) -> None:
        from omh.paths import resolve_paths
        from omh.plugin_bundle.omh.owner_preference_record import explicit_choice, validate_owner_preference
        from omh.routing.owner_preference import read_owner_preference, explicit_choice_provenance

        self.assertEqual(self.record(), ("codex", "claude-code"))
        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(validate_owner_preference(state), [])
        self.assertEqual(set(state["routes"]), {"ulw-coding-delivery.codex", "ulw-coding-delivery.claude-code"})
        loaded = read_owner_preference(resolve_paths(self.home, self.home / "hermes"))
        self.assertEqual(loaded, state)
        for owner in ("codex", "claude-code"):
            family = "ulw-coding-delivery." + owner
            self.assertEqual(explicit_choice(state, route_family=family), ("in_message_naming", owner))
            self.assertEqual(explicit_choice_provenance(loaded, route_family=family), "in_message_naming")
        self.assertNotIn("private-customer-widget", self.path.read_text(encoding="utf-8"))
        self.assertNotIn(self.MESSAGE, self.path.read_text(encoding="utf-8"))
        if os.name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_non_invocations_and_no_owner_do_not_create_state(self) -> None:
        for text in ("build the API with codex", "/dag-ulw build the API with claude only reviewing",
                     "/dag-ulw what is it, codex?", "/dag-ulw build it without codex"):
            with self.subTest(text=text):
                self.assertEqual(self.record(text), ())
                self.assertFalse(self.path.exists())

    def test_invalid_present_files_are_left_byte_identical(self) -> None:
        from omh.routing.owner_preference import empty_owner_preference_state
        invalid_schema = empty_owner_preference_state()
        invalid_schema["privacy"]["mode"] = "raw_text"
        self.path.parent.mkdir()
        for original in (b"{not json", b"[]", b"null", b"\xff", json.dumps(invalid_schema).encode()):
            with self.subTest(original=original):
                self.path.write_bytes(original)
                self.assertEqual(self.record(), ())
                self.assertEqual(self.path.read_bytes(), original)

    def test_main_and_unrelated_routes_keep_identical_fields(self) -> None:
        from omh.routing.owner_preference import empty_owner_preference_state, record_in_message_explicit_naming
        state = empty_owner_preference_state()
        for family in ("ulw-coding-delivery", "other-family"):
            state = record_in_message_explicit_naming(
                state, route_family=family, selected_owner="hermes", naming_cue="named_executor:hermes",
                occurred_at=self.NOW,
            )
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(state), encoding="utf-8")
        originals = {family: json.dumps(route, sort_keys=True).encode() for family, route in state["routes"].items()}
        self.record(now=self.LATER)
        updated = json.loads(self.path.read_text(encoding="utf-8"))
        for family, original in originals.items():
            self.assertEqual(json.dumps(updated["routes"][family], sort_keys=True).encode(), original)

    def test_refresh_matches_router_without_advancing_learning(self) -> None:
        from omh.routing.owner_preference import record_in_message_explicit_naming
        self.record()
        before = json.loads(self.path.read_text(encoding="utf-8"))
        expected = before
        for owner in ("codex", "claude-code"):
            expected = record_in_message_explicit_naming(
                expected, route_family="ulw-coding-delivery." + owner, selected_owner=owner,
                naming_cue="named_executor:" + owner, occurred_at=self.LATER,
            )
        self.record(now=self.LATER)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), expected)
        self.assertEqual(expected["routes"]["ulw-coding-delivery.codex"]["consecutive_accepted_explicit_choices"], 1)

    def test_changed_owner_and_learned_streak_match_router_transitions(self) -> None:
        from omh.routing.owner_preference import (
            empty_owner_preference_state, record_accepted_explicit_choice, record_in_message_explicit_naming,
        )
        family = "ulw-coding-delivery.codex"
        for previous in ("hermes", "codex"):
            with self.subTest(previous=previous):
                state = empty_owner_preference_state()
                for _ in range(3):
                    state = record_accepted_explicit_choice(
                        state, route_family=family, selected_owner=previous, occurred_at=self.NOW,
                    )
                self.path.parent.mkdir(exist_ok=True)
                self.path.write_text(json.dumps(state), encoding="utf-8")
                expected = record_in_message_explicit_naming(
                    state, route_family=family, selected_owner="codex", naming_cue="named_executor:codex",
                    occurred_at=self.LATER,
                )
                self.assertEqual(self.record("/dag-ulw build it with codex", now=self.LATER), ("codex",))
                self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), expected)

    def test_invalid_timestamp_and_failed_replace_preserve_existing_file(self) -> None:
        self.record()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.record(now="not-a-timestamp")
        self.assertEqual(self.path.read_bytes(), original)
        with patch("omh.plugin_bundle.omh.named_owner_choice.os.replace", side_effect=OSError("write refused")):
            with self.assertRaises(OSError):
                self.record(now=self.LATER)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])


class NamedOwnerHookTests(unittest.TestCase):
    MESSAGE = "/dag-ulw build the API with codex"

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "omh"
        self.hermes = Path(self.tmp.name) / "hermes"
        self.path = self.home / "routing" / "owner-preference.json"
        self.session = "named-owner-test"

    def hook(self, message: str = MESSAGE, **kwargs):
        from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
        return pre_llm_call(
            omh_home=str(self.home), hermes_home=str(self.hermes), session_id=self.session,
            user_message=message, is_first_turn=False, **kwargs,
        ) or {}

    def test_person_request_writes_codex_choice(self) -> None:
        from omh.plugin_bundle.omh.owner_preference_record import explicit_choice
        self.hook()
        self.assertTrue(self.path.exists(), "person's dag-ulw naming did not reach the choice record")
        self.assertEqual(explicit_choice(json.loads(self.path.read_text(encoding="utf-8")),
                                         route_family="ulw-coding-delivery.codex"), ("in_message_naming", "codex"))

    def test_delegated_child_cannot_write_its_own_choice(self) -> None:
        from omh.plugin_bundle.omh.hooks.nudge_budget import note_delegated_session
        note_delegated_session(self.session, omh_home=str(self.home))
        self.hook()
        self.assertFalse(self.path.exists())

    def test_host_synthesized_turn_cannot_write_choice(self) -> None:
        self.hook(conversation_history=[{"role": "user", "content": self.MESSAGE,
                                         "display_kind": "internal_notification"}])
        self.assertFalse(self.path.exists())

    def test_command_turn_cannot_write_choice(self) -> None:
        from omh.plugin_bundle.omh.dag_ulw_cues import invokes_dag_ulw
        from omh.plugin_bundle.omh.hermes_session_commands import host_command_turn
        message = "[Heartbeat — recurring instruction, fires every 5m]\nBuild the API with dag ulw and codex"
        self.assertTrue(host_command_turn(message))
        self.assertTrue(invokes_dag_ulw(message))
        self.hook(message)
        self.assertFalse(self.path.exists())

    def test_tracker_event_cannot_write_choice(self) -> None:
        self.hook(tracker_event={"provider": "github", "tracker_content": self.MESSAGE})
        self.assertFalse(self.path.exists())

    def test_only_person_request_can_name_the_owner(self) -> None:
        message = '[Replying to Alex: "use codex"]\n\n/dag-ulw build the API'
        self.hook(message, platform="discord")
        self.assertFalse(self.path.exists())

    def test_write_faults_surface_degradation_without_exception_prose(self) -> None:
        for error in (OSError("private error text"), ValueError("private error text")):
            with self.subTest(error=type(error).__name__), patch(
                "omh.plugin_bundle.omh.hooks.llm_hooks.record_named_owner_choices", side_effect=error,
            ):
                payload = self.hook()
                self.assertIn({"component": "runtime_status_read", "error_type": type(error).__name__},
                              payload["omh_degradation"]["components"])
                self.assertNotIn("private error text", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
