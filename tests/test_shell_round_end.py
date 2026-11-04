"""The round end for a turn that edits only through commands.

Hermes calls `pre_verify` only after a `patch` / `write_file` landed in the turn
(`agent/turn_stop_gates.py`, `_turn_file_mutation_paths`), so a turn that edits
with `sed -i` or a heredoc script got no round-end note at all. The measured
miss (OPT-L, Sonnet 5.5, L-RENAME-ALIAS): a `sed` rename left
`__all__ = ["compute_quota"]` in `api.py`, the tests passed, and the turn
stopped; on the `patch` path the export check names that line. These tests pin
that the same notes now ride the result of the command that changed a Python
file, and that every turn the files do not show changed behaves as before.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import consistency_trigger as ct  # noqa: E402
from omh.plugin_bundle.omh import test_expectation_check as tc  # noqa: E402
from omh.plugin_bundle.omh.hooks import verify_hooks  # noqa: E402
from omh.plugin_bundle.omh.hooks.result_transforms import transform_tool_result  # noqa: E402
from omh.plugin_bundle.omh.remote_wait_nudge import REMOTE_WAIT_NUDGE_KEY, reset_remote_wait_state  # noqa: E402

SESSION = "shell-round-end-session"
KEY = verify_hooks.SHELL_ROUND_END_KEY
RESULT = json.dumps({"output": "4 passed in 0.01s", "exit_code": 0, "error": None})
QUOTA = '"""Quota helpers."""\n\n\ndef compute_quota(units: int) -> int:\n    return units * 5\n'
RENAME = {
    "pyproject.toml": "[project]\nname='benchapp'\n",
    "src/benchapp/__init__.py": "",
    "src/benchapp/quota.py": QUOTA,
    "src/benchapp/api.py": 'from .quota import compute_quota\n\n__all__ = ["compute_quota"]\n',
    "src/benchapp/service.py": ("from benchapp.quota import compute_quota as cq_fn\n\n\n"
                                "def plan_units(units: int) -> int:\n    return cq_fn(units) + 1\n"),
}
# The measured run's `sed`: the definition and the import renamed, `__all__` left as it was.
STALE_RENAME = {"src/benchapp/quota.py": QUOTA.replace("compute_quota", "allocate_quota"),
                "src/benchapp/api.py": 'from .quota import allocate_quota\n\n__all__ = ["compute_quota"]\n'}
PRICING = '"""Fee arithmetic."""\n\n\ndef compute_fee(amount_cents: int, rate_bp: int) -> int:\n    return amount_cents * rate_bp // 10000\n'
SIGNATURE = {
    "pyproject.toml": "[project]\nname='benchapp'\n",
    "src/benchapp/__init__.py": 'from .pricing import compute_fee as fee\n\n__all__ = ["fee"]\n',
    "src/benchapp/pricing.py": PRICING,
    "src/benchapp/cli.py": ("from benchapp import fee\n\n\n"
                            "def cli_fee(argv: list[str]) -> int:\n    return fee(int(argv[0]), 50)\n"),
}


class _ShellTurn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        patcher = mock.patch.object(ct, "_workspace_root", lambda task_id: str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        ct.reset()
        tc.reset()
        self.addCleanup(ct.reset)
        self.addCleanup(tc.reset)

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def fixture(self, files: dict[str, str]) -> None:
        for relative, text in files.items():
            self.write(relative, text)

    def before(self, tool: str, args: dict[str, object], turn: str = "t1") -> None:
        ct.snapshot_before_edit({"tool_name": tool, "session_id": SESSION, "turn_id": turn}, args)

    def after(self, result: str = RESULT, turn: str = "t1", tool: str = "terminal") -> str | None:
        return verify_hooks.annotate_shell_round_end(tool_name=tool, result=result, session_id=SESSION, turn_id=turn)

    def command(self, command: str, edits: dict[str, str], turn: str = "t1") -> str | None:
        """One `terminal` call: `pre_tool_call`, the command's file changes, then its result transform."""
        self.before("terminal", {"command": command}, turn)
        for relative, text in edits.items():
            self.write(relative, text)
        return self.after(turn=turn)

    def note(self, carried: str | None) -> str:
        self.assertIsNotNone(carried, "expected the round-end note on the command's result")
        return str(json.loads(str(carried))[KEY])


class NamesWhatTheShellEditBroke(_ShellTurn):
    def test_the_measured_miss_a_stale_all_after_a_sed_rename(self):
        self.fixture(RENAME)
        self.assertIsNone(self.command("cat src/benchapp/api.py", {}))
        carried = self.command(
            "sed -i '' 's/compute_quota/allocate_quota/' src/benchapp/quota.py src/benchapp/api.py ...",
            {"src/benchapp/quota.py": QUOTA.replace("compute_quota", "allocate_quota"),
             "src/benchapp/api.py": 'from .quota import allocate_quota\n\n__all__ = ["compute_quota"]\n',
             "src/benchapp/service.py": RENAME["src/benchapp/service.py"].replace("compute_quota", "allocate_quota")})
        note = self.note(carried)
        self.assertIn("OMH export check", note)
        self.assertIn("src/benchapp/api.py:3", note)
        self.assertIn("compute_quota", note)
        payload = json.loads(str(carried))
        self.assertEqual(payload["output"], "4 passed in 0.01s")  # the host's fields are kept

    def test_a_call_left_broken_through_a_re_export_is_named(self):
        self.fixture(SIGNATURE)
        old = "def compute_fee(amount_cents: int, rate_bp: int) -> int:"
        new = "def compute_fee(amount_cents: int, rate_bp: int, minimum_cents: int) -> int:"
        note = self.note(self.command("sed -i '' 's/rate_bp: int)/rate_bp: int, minimum_cents: int)/' "
                                      "src/benchapp/pricing.py", {"src/benchapp/pricing.py": PRICING.replace(old, new)}))
        self.assertIn("OMH caller check", note)
        self.assertIn("src/benchapp/cli.py:5", note)

    def test_a_file_the_command_did_not_name_still_counts_as_changed(self):
        # `cd src/benchapp; python3 - <<E ... open('api.py','w')`: no path the snapshot can resolve. The
        # export check reads the file as it is now, so it needs no turn-start text.
        self.fixture(RENAME)
        note = self.note(self.command(
            "cd src/benchapp && python3 - <<'E'\n...\nE",
            {"src/benchapp/quota.py": QUOTA.replace("compute_quota", "allocate_quota"),
             "src/benchapp/api.py": 'from .quota import allocate_quota\n\n__all__ = ["compute_quota"]\n'}))
        self.assertIn("src/benchapp/api.py:3", note)

    def test_a_result_that_is_not_json_gets_the_note_appended(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "sed -i '' ... src/benchapp/api.py"})
        self.fixture(STALE_RENAME)
        carried = self.after(result="plain output")
        self.assertIsNotNone(carried)
        self.assertTrue(str(carried).startswith("plain output\n\nOMH export check"))

    def test_execute_code_is_watched_too(self):
        self.fixture(RENAME)
        self.before("execute_code", {"code": "open('src/benchapp/quota.py','w').write(...)"})
        self.fixture(STALE_RENAME)
        self.assertIn("api.py:3", self.note(self.after(tool="execute_code")))


class BehavesAsBeforeWithoutEvidence(_ShellTurn):
    def test_a_command_that_changes_no_python_file_gets_nothing(self):
        self.fixture(RENAME)
        self.assertIsNone(self.command("cat src/benchapp/api.py; git status", {}))
        self.assertIsNone(self.command("echo '{}' > .omh-benchmark-answer.json",
                                       {".omh-benchmark-answer.json": '{"changed_paths": []}'}))
        self.assertIsNone(self.command("echo x > notes.md", {"notes.md": "x\n"}))

    def test_a_shell_edit_that_breaks_nothing_gets_nothing(self):
        self.fixture(RENAME)
        renamed = {relative: text.replace("compute_quota", "allocate_quota") for relative, text in RENAME.items()}
        self.assertIsNone(self.command("sed -i '' 's/compute_quota/allocate_quota/g' src/benchapp/*.py", renamed))

    def test_the_defaulted_control_says_nothing(self):
        # I-DEFAULTED's shape: a parameter with a default leaves every call valid.
        self.fixture(SIGNATURE)
        old = "def compute_fee(amount_cents: int, rate_bp: int) -> int:"
        new = "def compute_fee(amount_cents: int, rate_bp: int, *, minimum_cents: int = 0) -> int:"
        self.assertIsNone(self.command("sed -i '' '...' src/benchapp/pricing.py",
                                       {"src/benchapp/pricing.py": PRICING.replace(old, new)}))

    def test_a_turn_with_a_patch_is_left_to_pre_verify(self):
        self.fixture(RENAME)
        self.before("patch", {"path": "README.md", "old_string": "a", "new_string": "b"})
        self.assertIsNone(self.command("sed -i '' ... src/benchapp/quota.py",
                                       STALE_RENAME))

    def test_a_turn_without_an_index_gets_nothing(self):
        # A delegated child never gets the round-end check, so no index is taken for it.
        self.fixture(RENAME)
        ct.note_turn_posture(SESSION, "subagent")
        with self.assertNoLogs("omh.consistency_trigger", level="WARNING"):
            self.assertIsNone(self.command("sed -i '' ... src/benchapp/quota.py", STALE_RENAME))

    def test_another_turns_state_is_never_read(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "sed -i '' ... src/benchapp/quota.py"}, turn="t1")
        self.fixture(STALE_RENAME)
        self.assertIsNone(self.after(turn="t2"))

    def test_a_result_that_is_json_but_not_an_object_is_left_alone(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "sed -i '' ... src/benchapp/quota.py"})
        self.fixture(STALE_RENAME)
        self.assertIsNone(self.after(result="[1, 2]"))
        self.assertIsNone(self.after(result=json.dumps({KEY: "already"})))

    def test_other_tools_are_never_touched(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "sed -i '' ... src/benchapp/quota.py"})
        self.fixture(STALE_RENAME)
        self.assertIsNone(self.after(tool="read_file"))
        self.assertIsNone(self.after(tool="patch"))


class OncePerTurn(_ShellTurn):
    def test_it_speaks_once_and_a_new_turn_starts_over(self):
        self.fixture(RENAME)
        self.note(self.command("sed ... quota.py api.py", STALE_RENAME))
        # `service.py` now imports a name `quota.py` no longer defines: named in a new turn, not in this one.
        self.assertIsNone(self.command("echo >> src/benchapp/service.py",
                                       {"src/benchapp/service.py": RENAME["src/benchapp/service.py"] + "\n"}))
        self.assertIn("service.py:1", self.note(self.command(
            "echo >> src/benchapp/service.py",
            {"src/benchapp/service.py": RENAME["src/benchapp/service.py"] + "\n\n"}, turn="t2")))

    def test_a_quiet_change_is_checked_again_at_the_next_change(self):
        self.fixture(RENAME)
        self.assertIsNone(self.command("echo >> src/benchapp/service.py",
                                       {"src/benchapp/service.py": RENAME["src/benchapp/service.py"] + "\n"}))
        with self.assertNoLogs("omh.verify_hooks", level="INFO"):  # changed nothing since: not checked again
            self.assertIsNone(self.command("pytest -q", {}))
        self.assertIn("api.py:3", self.note(self.command("sed ... quota.py api.py", STALE_RENAME)))


class WaitsForTheMessagesLastCommand(_ShellTurn):
    """Hermes hands each command's result to the hook as it lands, but the model reads a message's results
    together. Measured (OPT-M, Haiku, I-KWARG-583919): a note computed after the first of four `sed` calls
    named two callers the next calls of the same message had already updated."""

    def batch(self, *calls: tuple[str, str]) -> None:
        verify_hooks.post_api_request(session_id=SESSION, response={"assistant_message": {"tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}
            for call_id, name in calls]}})

    def call(self, call_id: str, edits: dict[str, str]) -> str | None:
        self.before("terminal", {"command": "sed ..."})
        self.fixture(edits)
        return verify_hooks.annotate_shell_round_end(tool_name="terminal", result=RESULT, session_id=SESSION,
                                                     turn_id="t1", tool_call_id=call_id)

    def test_a_note_a_later_command_of_the_message_makes_stale_is_not_given(self):
        self.fixture(RENAME)
        self.batch(("c1", "terminal"), ("c2", "terminal"))
        with self.assertNoLogs("omh.verify_hooks", level="INFO"):  # not even looked at
            self.assertIsNone(self.call("c1", STALE_RENAME))
        fixed = 'from .quota import allocate_quota\n\n__all__ = ["allocate_quota"]\n'
        self.assertIsNone(self.call("c2", {"src/benchapp/api.py": fixed}))

    def test_the_last_command_sees_every_change_of_the_message(self):
        self.fixture(RENAME)
        self.batch(("c1", "terminal"), ("c2", "terminal"))
        self.assertIsNone(self.call("c1", {"src/benchapp/quota.py": STALE_RENAME["src/benchapp/quota.py"]}))
        self.assertIn("api.py:3", self.note(self.call("c2", {"src/benchapp/api.py": STALE_RENAME["src/benchapp/api.py"]})))

    def test_reads_after_the_last_command_do_not_hold_the_note_back(self):
        self.fixture(RENAME)
        self.batch(("c1", "terminal"), ("c2", "read_file"), ("c3", "search_files"))
        self.assertIn("api.py:3", self.note(self.call("c1", STALE_RENAME)))

    def test_a_call_id_the_message_does_not_hold_is_looked_at(self):
        self.fixture(RENAME)
        self.batch(("c1", "terminal"), ("c2", "terminal"))
        self.assertIn("api.py:3", self.note(self.call("other", STALE_RENAME)))

    def test_a_codex_call_is_matched_by_its_call_id(self):
        self.fixture(RENAME)
        verify_hooks.post_api_request(session_id=SESSION, response={"assistant_message": {"tool_calls": [
            {"call_id": "call_a", "name": "terminal"}, {"call_id": "call_b", "name": "terminal"}]}})
        self.assertIsNone(self.call("call_a", STALE_RENAME))

    def test_a_payload_without_tool_calls_keeps_nothing(self):
        self.fixture(RENAME)
        verify_hooks.post_api_request(session_id=SESSION, response=None)
        verify_hooks.post_api_request(session_id=SESSION, response={"assistant_message": {"tool_calls": None}})
        self.assertIn("api.py:3", self.note(self.call("c1", STALE_RENAME)))


class AfterTheTurnsRoundEnd(_ShellTurn):
    """`pre_verify` consumes the turn's state at its first stop. Measured (OPT-M, Haiku, I-KWARG-347911):
    the state rebuilt after that continue took the mid-turn text as the turn's start, and the test check
    then asked to put back the model's own first-round edit."""

    def test_the_same_turn_gets_no_second_shell_round_end_after_pre_verify(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "ls"})
        ct.discard_snapshots(SESSION)  # pre_verify, attempt 0
        with self.assertNoLogs("omh.verify_hooks", level="INFO"):
            self.assertIsNone(self.command("sed ... quota.py api.py", STALE_RENAME))

    def test_the_trigger_verdict_ends_the_turn_too(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "ls"})
        ct.round_end_trigger(SESSION, ("src/benchapp/quota.py",))
        self.assertIsNone(self.command("sed ... quota.py api.py", STALE_RENAME))

    def test_the_next_turn_starts_over(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "ls"})
        ct.discard_snapshots(SESSION)
        self.assertIn("api.py:3", self.note(self.command("sed ... quota.py api.py", STALE_RENAME, turn="t2")))


class ComposesWithTheOtherTerminalPass(_ShellTurn):
    def setUp(self):
        super().setUp()
        reset_remote_wait_state()
        self.addCleanup(reset_remote_wait_state)
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = home.name

    def test_unarmed_remote_waits_still_reads_the_hosts_object(self):
        self.fixture(RENAME)
        self.before("terminal", {"command": "sed -i '' ... src/benchapp/quota.py && git push"})
        self.fixture(STALE_RENAME)
        carried = transform_tool_result(
            tool_name="terminal", args={"command": "sed -i '' ... src/benchapp/quota.py && git push"},
            result=json.dumps({"status": "ok", "exit_code": 0, "output": "Everything up-to-date"}),
            session_id=SESSION, turn_id="t1", hermes_home=self.home, duration_ms=3, status="ok")
        payload = json.loads(str(carried))
        self.assertIn(REMOTE_WAIT_NUDGE_KEY, payload)
        self.assertIn("api.py:3", payload[KEY])
        self.assertEqual(payload["exit_code"], 0)

    def test_the_hook_passes_the_call_id_through(self):
        self.fixture(RENAME)
        verify_hooks.post_api_request(session_id=SESSION, response={"assistant_message": {"tool_calls": [
            {"id": "c1", "function": {"name": "terminal"}}, {"id": "c2", "function": {"name": "terminal"}}]}})
        self.before("terminal", {"command": "sed ..."})
        self.fixture(STALE_RENAME)
        carried = transform_tool_result(tool_name="terminal", args={"command": "sed ..."}, result=RESULT,
                                        session_id=SESSION, turn_id="t1", tool_call_id="c1",
                                        hermes_home=self.home, duration_ms=3, status="ok")
        self.assertNotIn(KEY, json.loads(str(carried)) if carried else {})


if __name__ == "__main__":
    unittest.main()
