"""A setup-profile default coding owner is a setting, never an owner named in the request.

A profile default must reach the wrapper as `setup_profile`: the route
decision is the recorded-owner one, no explicit-choice record is written, and
it never bypasses the genre veto. An owner named with `--executor` or in the
message is still a choice made in this request, and it beats the profile
default on every entry point.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.profiles.setup import write_setup_profile  # noqa: E402
from omh.routing.owner_preference import owner_preference_decision  # noqa: E402
from omh.wrapper import contract  # noqa: E402

CODING = "fix the login bug and open a pr"
NAMED_CODEX = "fix the login bug with codex and open a pr"
RESEARCH_BRIEF = "Research the best pricing model for our SaaS tier and summarize the findings for the team."


class _Homes:
    def __init__(self, root: Path, default_executor: str = "claude-code") -> None:
        self.omh, self.hermes = root / ".omh", root / ".hermes"
        self.paths = resolve_paths(self.omh, self.hermes)
        write_setup_profile(self.paths, default_executor=default_executor)
        self.store = self.omh / "routing" / "owner-preference.json"

    def cli(self, *args: str) -> dict:
        status, stdout, stderr = run_cli(["--omh-home", str(self.omh), "--hermes-home", str(self.hermes), *args])
        if status != 0:
            raise AssertionError(stderr)
        return json.loads(stdout)


def _interaction(payload: dict) -> dict:
    return payload.get("interaction", payload)


class ProfileDefaultEntryPointTests(unittest.TestCase):
    def assert_profile_default(self, payload: dict, homes: _Homes) -> None:
        interaction = _interaction(payload)
        resolution = interaction["executor_resolution"]
        decision = interaction["coding_route_decision"]
        self.assertEqual(resolution["source"], "setup_profile")
        self.assertEqual(resolution["resolved_executor_target"], "claude-code")
        self.assertEqual(interaction["delegation"]["selected_executor_profile"], "claude-code")
        self.assertEqual(decision["source"], "recorded_setup_preference")
        self.assertEqual(decision["next_action"], "prepare_recorded_owner_handoff")
        self.assertEqual(decision["owner_preference_reason_code"], "owner_set_in_setup_profile")
        self.assertFalse(homes.store.exists(), "a profile default must not be recorded as an explicit choice")

    def test_chat_interact_labels_a_profile_default_as_the_profile(self) -> None:
        # Mutation: resolve the profile default in the CLI again; the wrapper then labels it `explicit`.
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            self.assert_profile_default(homes.cli("chat", "interact", "--json", "--source", "discord", CODING), homes)

    def test_chat_session_start_labels_a_profile_default_as_the_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            self.assert_profile_default(homes.cli("chat", "session", "start", "--source", "discord", CODING), homes)

    def test_an_executor_flag_is_still_an_explicit_choice(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            payload = homes.cli("chat", "interact", "--json", "--source", "discord", "--executor", "codex", CODING)
            stored = homes.store.exists()
        self.assertEqual(payload["executor_resolution"]["source"], "explicit")
        self.assertEqual(payload["executor_resolution"]["resolved_executor_target"], "codex")
        self.assertEqual(payload["coding_route_decision"]["source"], "request_named_executor")
        self.assertEqual(payload["coding_route_decision"]["owner_preference_reason_code"], "owner_named_in_request")
        self.assertTrue(stored)

    def test_a_profile_default_never_bypasses_the_genre_veto(self) -> None:
        # The wrapper hands the builder `explicit_owner_choice`; only an owner named for this run may set it.
        # The builder test `test_named_owner_without_the_explicit_flag_still_clarifies` pins what it holds back.
        seen: list[bool] = []
        real = contract.build_coding_delegation_payload

        def spy(*args, **kwargs):
            seen.append(bool(kwargs.get("explicit_owner_choice")))
            return real(*args, **kwargs)

        with TemporaryDirectory() as tmp, patch.object(contract, "build_coding_delegation_payload", side_effect=spy):
            homes = _Homes(Path(tmp))
            homes.cli("chat", "interact", "--json", "--source", "discord", CODING)
            profile, seen[:] = list(seen), []
            homes.cli("chat", "interact", "--json", "--source", "discord", "--executor", "claude-code", CODING)
            named = list(seen)
        self.assertTrue(profile)
        self.assertEqual(set(profile), {False})
        self.assertIn(True, named)

    def test_the_plugin_interact_tool_labels_a_profile_default_as_the_profile(self) -> None:
        from omh.plugin_bundle.omh.tools import chat_tool

        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            with patch.dict(os.environ, {"OMH_HOME": str(homes.omh), "HERMES_HOME": str(homes.hermes)}):
                payload = json.loads(chat_tool.omh_interact_handler({
                    "message": CODING, "source": "discord", "record_session": False,
                    "omh_home": str(homes.omh), "hermes_home": str(homes.hermes),
                }))
            self.assert_profile_default(payload, homes)

    def test_coding_delegate_keeps_a_profile_default_inside_the_genre_veto(self) -> None:
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            coding = homes.cli("coding", "delegate", CODING)
            research = homes.cli("coding", "delegate", RESEARCH_BRIEF)
            stored = homes.store.exists()
        self.assertEqual(coding["selected_executor_profile"], "claude-code")
        self.assertEqual(research["delegation"]["action"], "clarify")
        self.assertFalse(stored)


    def test_an_owner_named_in_the_message_beats_the_profile_default_in_chat(self) -> None:
        # This changes which owner runs: main resolved the profile default in the CLI and ran claude-code here.
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            for entry, payload in (
                ("chat interact", homes.cli("chat", "interact", "--json", "--source", "discord", NAMED_CODEX)),
                ("chat session start", homes.cli("chat", "session", "start", "--source", "discord", NAMED_CODEX)),
            ):
                interaction = _interaction(payload)
                with self.subTest(entry=entry):
                    self.assertEqual(interaction["executor_resolution"]["source"], "message_mention")
                    self.assertEqual(interaction["executor_resolution"]["resolved_executor_target"], "codex")
                    self.assertEqual(interaction["delegation"]["selected_executor_profile"], "codex")

    def test_coding_delegate_takes_an_owner_named_in_the_message_over_the_profile_default(self) -> None:
        # Mutation: drop the message mention in `coding delegate`; the profile default (claude-code) runs instead.
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            named = homes.cli("coding", "delegate", NAMED_CODEX)
            flagged = homes.cli("coding", "delegate", "--executor", "claude-code", NAMED_CODEX)
        self.assertEqual(named["selected_executor_profile"], "codex")
        self.assertEqual(flagged["selected_executor_profile"], "claude-code")


class ProfileOwnerRouteHintTests(unittest.TestCase):
    MESSAGE = "implement the dark mode toggle and open a pr"

    def _decisions(self, payload: dict) -> list[dict]:
        return [hint["coding_route_decision"] for hint in payload["hints"] if "coding_route_decision" in hint]

    def test_the_hint_reports_a_profile_owner_as_the_profile(self) -> None:
        from omh.plugin_bundle.omh.awareness import awareness_route_hint

        asked = self._decisions(awareness_route_hint(self.MESSAGE))
        held = self._decisions(awareness_route_hint(self.MESSAGE, profile_owner="claude-code"))
        self.assertTrue(asked and held)
        self.assertEqual({d["owner_preference_reason_code"] for d in asked}, {"explicit_choice_required"})
        self.assertEqual({d["source"] for d in held}, {"recorded_setup_preference"})
        self.assertEqual({d["owner_preference_reason_code"] for d in held}, {"owner_set_in_setup_profile"})

    def test_the_turn_hook_reads_the_profile_owner_for_the_hint(self) -> None:
        # Mutation: call the hint without the profile owner; the hook then hands it "" and the hint asks.
        from omh.plugin_bundle.omh.hooks import llm_hooks

        seen: list[str] = []
        real = llm_hooks.awareness_route_hint

        def spy(*args, **kwargs):
            seen.append(kwargs.get("profile_owner", ""))
            return real(*args, **kwargs)

        with TemporaryDirectory() as tmp, patch.object(llm_hooks, "awareness_route_hint", side_effect=spy):
            homes = _Homes(Path(tmp))
            llm_hooks.pre_llm_call(omh_home=str(homes.omh), hermes_home=str(homes.hermes), session_id="profile-owner",
                                   user_message=self.MESSAGE, is_first_turn=True)
        self.assertEqual(seen[:1], ["claude-code"])

    def test_the_profile_reader_names_only_an_executor_id_read_as_the_wrapper_reads_it(self) -> None:
        # Mutation: drop the legacy mapping or the executor-id check; the hint then names an owner the wrapper does not.
        from omh.coding.executors import canonical_executor_profile, legacy_executor_profile_ids
        from omh.plugin_bundle.omh.owner_preference_record import setup_profile_owner

        legacy = legacy_executor_profile_ids("pi-family-runtime")
        self.assertTrue(legacy)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(setup_profile_owner(root), "")
            for value, expected in (
                ("codex", "codex"), (legacy[0], "pi-family-runtime"), ("notarealowner", ""), ("Codex", ""),
                ("choose", ""),
            ):
                with self.subTest(value=value):
                    (root / "setup-profile.json").write_text(json.dumps({"default_executor": value}), encoding="utf-8")
                    self.assertEqual(setup_profile_owner(root), expected)
                    wrapper = canonical_executor_profile(value)
                    self.assertEqual(expected, wrapper if wrapper in contract.CODING_EXECUTOR_TARGETS
                                     and wrapper != "choose" else "")
            for raw in ("[]", "{broken"):
                with self.subTest(raw=raw):
                    (root / "setup-profile.json").write_text(raw, encoding="utf-8")
                    self.assertEqual(setup_profile_owner(root), "")

    def test_the_bundle_executor_ids_are_the_wrappers(self) -> None:
        from omh.plugin_bundle.omh.owner_preference_record import SETUP_PROFILE_EXECUTORS

        self.assertEqual(SETUP_PROFILE_EXECUTORS, set(contract.CODING_EXECUTOR_TARGETS) - {"choose"})


class OwnerCueEntryPointTests(unittest.TestCase):
    """A CLI named as what the work is about is not an owner choice on any entry point (#2679 review)."""

    SUBJECT = "fix the codex adapter tests and open a pr"

    def test_a_cli_named_as_the_subject_leaves_the_profile_default_in_charge(self) -> None:
        # Mutation: read a bare product word as an owner again; Codex then runs and is recorded as chosen.
        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            for entry, payload in (
                ("chat interact", homes.cli("chat", "interact", "--json", "--source", "discord", self.SUBJECT)),
                ("chat session start", homes.cli("chat", "session", "start", "--source", "discord", self.SUBJECT)),
            ):
                interaction = _interaction(payload)
                with self.subTest(entry=entry):
                    self.assertEqual(interaction["executor_resolution"]["source"], "setup_profile")
                    self.assertEqual(interaction["delegation"]["selected_executor_profile"], "claude-code")
            delegated = homes.cli("coding", "delegate", self.SUBJECT)
            stored = homes.store.exists()
        self.assertEqual(delegated["selected_executor_profile"], "claude-code")
        self.assertFalse(stored)

    def test_the_plugin_tool_reads_the_same_cue(self) -> None:
        from omh.plugin_bundle.omh.tools import chat_tool

        with TemporaryDirectory() as tmp:
            homes = _Homes(Path(tmp))
            with patch.dict(os.environ, {"OMH_HOME": str(homes.omh), "HERMES_HOME": str(homes.hermes)}):
                payload = json.loads(chat_tool.omh_interact_handler({
                    "message": self.SUBJECT, "source": "discord", "record_session": False,
                    "omh_home": str(homes.omh), "hermes_home": str(homes.hermes),
                }))
        self.assertEqual(_interaction(payload)["executor_resolution"]["source"], "setup_profile")
        self.assertEqual(_interaction(payload)["delegation"]["selected_executor_profile"], "claude-code")


class ProfileOwnerDecisionTests(unittest.TestCase):
    def test_a_profile_owner_bypasses_the_question_and_says_why(self) -> None:
        decision = owner_preference_decision(None, route_family="ulw-coding-delivery", profile_owner=True)
        self.assertEqual(decision.action, "bypass_owner_learning")
        self.assertEqual(decision.reason_code, "owner_set_in_setup_profile")
        self.assertEqual(decision.selected_owner, "")

    def test_safety_gates_outrank_a_profile_owner(self) -> None:
        decision = owner_preference_decision(
            None, route_family="ulw-coding-delivery", profile_owner=True, authority_blocked=True)
        self.assertEqual(decision.action, "ask_explicit_owner")
        self.assertEqual(decision.reason_code, "authority_requires_choice")


if __name__ == "__main__":
    unittest.main()
