"""A setup-profile default coding owner is a setting, never an owner named in the request.

Every entry point keeps the owner that runs, but a profile default must reach
the wrapper as `setup_profile`: the route decision is the recorded-owner one,
no explicit-choice record is written, and it never bypasses the genre veto.
An owner named with `--executor` or in the message is still explicit.
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
