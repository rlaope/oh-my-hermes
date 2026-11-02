"""The round-end test check: a changed test expectation in a turn asked to keep behaviour.

`pre_llm_call` records what the request said (`note_request`); at the turn's first stop
`round_end_note` compares each test file's turn-start snapshot with the disk and names an assertion
whose expected value is gone, unless the request named that test or asked to update a test.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import consistency_trigger as ct  # noqa: E402
from omh.plugin_bundle.omh import test_expectation_check as tc  # noqa: E402
from omh.plugin_bundle.omh.hooks import nudge_budget, verify_hooks  # noqa: E402

SESSION = "test-check-session"
KWARG = ("Rename the keyword-only parameter timeout of fetch in src/benchapp/http_client.py to timeout_s (do not keep "
         "timeout as an alias). What fetch returns stays the same, and every caller must keep its behaviour.")
CLIENT = ('def fetch(url: str, *, timeout: float = 5.0, retries: int = 1) -> dict[str, object]:\n'
          '    return {"url": url, "timeout": timeout, "retries": retries}\n')
CLIENT_TEST = ('from benchapp.http_client import fetch\n\n\ndef test_fetch_defaults():\n'
               '    assert fetch("u") == {"url": "u", "timeout": 5.0, "retries": 1}\n')


class _Turn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        patcher = mock.patch.object(ct, "_workspace_root", lambda task_id: str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        for module in (ct, tc):
            module.reset()
            self.addCleanup(module.reset)

    def write(self, relative: str, text: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return str(path)

    def edit(self, relative: str, old: str, new: str) -> str:
        args = {"path": relative, "old_string": old, "new_string": new}
        ct.snapshot_before_edit({"tool_name": "patch", "session_id": SESSION, "turn_id": "t1"}, args)
        text = (self.root / relative).read_text(encoding="utf-8")
        self.assertIn(old, text)
        return self.write(relative, text.replace(old, new, 1))

    def kwarg_turn(self, request: str = KWARG, test_old: str = '"timeout": 5.0', test_new: str = '"timeout_s": 5.0') -> str:
        tc.note_request(SESSION, request)
        self.write("src/benchapp/http_client.py", CLIENT)
        self.write("tests/test_http_client.py", CLIENT_TEST)
        self.edit("src/benchapp/http_client.py", 'timeout: float = 5.0', 'timeout_s: float = 5.0')
        self.edit("src/benchapp/http_client.py", '"timeout": timeout', '"timeout_s": timeout_s')
        if test_old:
            self.edit("tests/test_http_client.py", test_old, test_new)
        return tc.round_end_note(SESSION, str(self.root))


class TestExpectationNoteTest(_Turn):
    def test_a_rewritten_expectation_in_a_keep_behaviour_turn_is_named(self):
        note = self.kwarg_turn()
        self.assertEqual(note.splitlines(), [
            "OMH test check: the request asked for behaviour to stay the same, and this turn changed what an existing "
            "test expects:",
            'tests/test_http_client.py:5: was `assert fetch("u") == {"url": "u", "timeout": 5.0, "retries": 1}`',
            "Unless the request asked for that change, put the expected values back and change the code until the "
            "original test passes.",
        ])

    def test_a_request_that_does_not_ask_to_keep_behaviour_gets_no_note(self):
        self.assertEqual(self.kwarg_turn("Rename timeout to timeout_s in fetch, keys included."), "")

    def test_a_request_naming_the_test_or_asking_to_update_one_gets_no_note(self):
        for request in (KWARG + " Update tests/test_http_client.py to match.",
                        KWARG + " See test_http_client.",
                        KWARG + " The test_fetch_defaults case may change.",
                        KWARG + " Update the existing test to expect the new key."):
            with self.subTest(request=request):
                ct.reset()
                self.assertEqual(self.kwarg_turn(request), "")

    def test_a_test_that_only_gained_assertions_or_renamed_a_keyword_gets_no_note(self):
        for old, new in (('"retries": 1}\n', '"retries": 1}\n    assert fetch("u", timeout_s=2.0)["timeout"] == 2.0\n'),
                         ('fetch("u")', 'fetch("u", timeout_s=5.0)'),
                         ("def test_fetch_defaults", "def test_fetch_default_values")):
            with self.subTest(new=new):
                ct.reset()
                self.assertEqual(self.kwarg_turn(test_old=old, test_new=new), "")

    def test_an_untouched_test_or_a_new_test_file_gets_no_note(self):
        self.assertEqual(self.kwarg_turn(test_old=""), "")
        ct.reset()
        tc.note_request(SESSION, KWARG)
        self.write("src/benchapp/http_client.py", CLIENT)
        self.edit("src/benchapp/http_client.py", '"timeout": timeout', '"timeout_s": timeout')
        ct.snapshot_before_edit({"tool_name": "write_file", "session_id": SESSION, "turn_id": "t1"},
                                {"path": "tests/test_new.py", "content": "x"})
        self.write("tests/test_new.py", 'def test_new():\n    assert 1 == 1\n')
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_a_turn_that_changed_only_tests_gets_no_note(self):
        tc.note_request(SESSION, KWARG)
        self.write("tests/test_http_client.py", CLIENT_TEST)
        self.edit("tests/test_http_client.py", '"timeout": 5.0', '"timeout_s": 5.0')
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_a_test_edited_without_a_snapshot_is_not_judged(self):
        tc.note_request(SESSION, KWARG)
        self.write("src/benchapp/http_client.py", CLIENT)
        self.write("tests/test_http_client.py", CLIENT_TEST)
        self.edit("src/benchapp/http_client.py", '"timeout": timeout', '"timeout_s": timeout')
        self.write("tests/test_http_client.py", CLIENT_TEST.replace('"timeout"', '"timeout_s"'))
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_a_subscript_key_turned_into_an_attribute_is_not_an_expectation(self):
        tc.note_request(SESSION, "Make build_quote faster; behaviour stays the same.")
        self.write("src/app/quotes.py", "def build_quote(units):\n    return {'total_cents': units * 3}\n")
        self.write("tests/test_quotes.py", "def test_build_quote():\n    quote = build_quote(2)\n"
                                           "    assert quote['total_cents'] == 2 * 3\n")
        self.edit("src/app/quotes.py", "return {'total_cents': units * 3}", "return Quote(units * 3)")
        self.edit("tests/test_quotes.py", "quote['total_cents']", "quote.total_cents")
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_unittest_assert_calls_count_as_expectations(self):
        tc.note_request(SESSION, "Speed up total without changing behaviour.")
        self.write("src/app/calc.py", "def total(xs):\n    return sum(xs)\n")
        self.write("tests/test_calc.py", "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                         "    def test_total(self):\n        self.assertEqual(total([1, 2]), 3)\n")
        self.edit("src/app/calc.py", "return sum(xs)", "return sum(xs) + 1")
        self.edit("tests/test_calc.py", "total([1, 2]), 3)", "total([1, 2]), 4)")
        note = tc.round_end_note(SESSION, str(self.root))
        self.assertIn("tests/test_calc.py:6: was `self.assertEqual(total([1, 2]), 3)`", note)

    def test_a_test_directory_above_the_workspace_root_does_not_make_a_test_file(self):
        self.assertFalse(tc._is_test_file("/home/tests/project/src/app.py", "/home/tests/project"))
        self.assertTrue(tc._is_test_file("/home/tests/project/tests/helpers.py", "/home/tests/project"))
        self.assertTrue(tc._is_test_file("/home/project/src/app_test.py", "/home/project"))

    def test_no_record_for_the_session_gets_no_note(self):
        self.write("src/benchapp/http_client.py", CLIENT)
        self.assertEqual(tc.round_end_note("never-noted", str(self.root)), "")

    def test_request_phrases(self):
        keeps = ("What fetch returns stays the same.", "Results remain the same.", "Leave the API unchanged.",
                 "Fix it without changing its signature.", "Keep its behaviour.", "preserving the existing behavior")
        asks = ("Update the test.", "fix the failing tests", "Change the existing kib assertion to 2048.",
                "adjust its expected value", "Change build_quote to return a frozen dataclass.",
                "parse_duration('90s') returns 5400, but it must return 90.")
        neither = ("Fix it and add a regression test.", "Rename X in production and tests.", "Add regression tests.")
        for text in keeps:
            tc.note_request(SESSION, text)
            self.assertEqual(tc._requests[SESSION][:2], (True, False), text)
        for text in asks:
            tc.note_request(SESSION, text)
            self.assertTrue(tc._requests[SESSION].asks_test_edit, text)
        for text in neither:
            tc.note_request(SESSION, text)
            self.assertEqual(tc._requests[SESSION][:2], (False, False), text)

    def test_review_phrases_for_scope_negation_and_wider_asks(self):
        # Review of #2494. A scoped keep keeps nothing about the part the request changes.
        for text in ("Make a kib 1024 bytes; everything else stays the same.",
                     "Rename the key and leave the other keys unchanged.",
                     "Add a seconds argument and keep the existing behaviour for callers that pass none."):
            tc.note_request(SESSION, text)
            self.assertFalse(tc._requests[SESSION].keeps_behaviour, text)
        # A wider ask to edit a test.
        for text in ("Rename it and update its docstring and tests.", "Refresh the kib test.",
                     "Revise the existing tests for the new unit."):
            tc.note_request(SESSION, text)
            self.assertTrue(tc._requests[SESSION].asks_test_edit, text)
        # A negated ask, or a result that must stay as it is, keeps behaviour and asks for nothing.
        for text in ("Speed it up; do not change the tests.", "Rename the flag and don't update any tests.",
                     "fetch must return the same dict as before.",
                     "It should return exactly what it returns today."):
            tc.note_request(SESSION, text)
            self.assertEqual(tc._requests[SESSION][:2], (True, False), text)

    def test_a_scoped_keep_with_a_correct_test_update_gets_no_note(self):
        request = "parse_size must count a kib as 1024 bytes; everything else stays the same."
        tc.note_request(SESSION, request.replace("must count", "counts"))
        self.write("src/app/sizes.py", "UNIT = {'kib': 1000}\n")
        self.write("tests/test_sizes.py", "def test_kib():\n    assert parse_size('2kib') == 2000\n")
        self.edit("src/app/sizes.py", "1000", "1024")
        self.edit("tests/test_sizes.py", "2000", "2048")
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_an_assertion_moved_to_another_test_file_loses_nothing(self):
        tc.note_request(SESSION, KWARG)
        self.write("src/benchapp/http_client.py", CLIENT)
        self.write("tests/test_http_client.py", CLIENT_TEST)
        self.write("tests/test_fetch.py", "from benchapp.http_client import fetch\n")
        self.edit("src/benchapp/http_client.py", 'timeout: float = 5.0', 'timeout_s: float = 5.0')
        moved = '    assert fetch("u") == {"url": "u", "timeout": 5.0, "retries": 1}\n'
        self.edit("tests/test_http_client.py", moved, "    pass\n")
        self.edit("tests/test_fetch.py", "import fetch\n", "import fetch\n\n\ndef test_defaults():\n" + moved)
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")
        ct.reset()
        # Moved into a test file the turn created, too.
        tc.note_request(SESSION, KWARG)
        self.write("src/benchapp/http_client.py", CLIENT)
        self.write("tests/test_http_client.py", CLIENT_TEST)
        self.edit("src/benchapp/http_client.py", 'timeout: float = 5.0', 'timeout_s: float = 5.0')
        self.edit("tests/test_http_client.py", moved, "    pass\n")
        ct.snapshot_before_edit({"tool_name": "write_file", "session_id": SESSION, "turn_id": "t1"},
                                {"path": "tests/test_new.py", "content": "x"})
        self.write("tests/test_new.py", "def test_defaults():\n" + moved)
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_a_unittest_message_is_not_an_expected_value(self):
        tc.note_request(SESSION, "Speed up total without changing behaviour.")
        self.write("src/app/calc.py", "def total(xs):\n    return sum(xs)\n")
        self.write("tests/test_calc.py", "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_total(self):\n"
                                         "        self.assertEqual(total([1, 2]), 3, 'sum of two')\n"
                                         "        self.assertTrue(total([]) == 0, msg='empty is zero')\n")
        self.edit("src/app/calc.py", "return sum(xs)", "return sum(list(xs))")
        self.edit("tests/test_calc.py", "'sum of two'", "'sum of both'")
        self.edit("tests/test_calc.py", "msg='empty is zero'", "msg='empty sums to zero'")
        self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")

    def test_requests_are_bounded_across_sessions(self):
        for index in range(tc._MAX_SESSIONS + 5):
            tc.note_request(f"s{index}", KWARG)
        self.assertEqual(len(tc._requests), tc._MAX_SESSIONS)
        self.assertNotIn("s0", tc._requests)

    def test_every_stop_logs_its_reason(self):
        with self.assertLogs("omh.test_expectation_check", "INFO") as logs:
            self.kwarg_turn()
            ct.reset()
            self.kwarg_turn(KWARG + " See test_http_client.")
            ct.reset()
            self.kwarg_turn("Add a feature.")
            tc.round_end_note("never-noted", str(self.root))
        reasons = [line.split("reason=")[1].split()[0] for line in logs.output]
        self.assertEqual(reasons, ["lost_expectation", "test_named", "no_keep_request", "no_request"])
        self.assertIn("fire=True", logs.output[0])

    def test_a_broken_read_says_nothing(self):
        tc.note_request(SESSION, KWARG)
        with mock.patch.object(tc, "turn_snapshots", side_effect=RuntimeError("boom")):
            self.assertEqual(tc.round_end_note(SESSION, str(self.root)), "")


class PreVerifyTestNoteTest(_Turn):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "omh"
        self.hermes = Path(tmp.name) / "hermes"
        self.hermes.mkdir(parents=True)
        nudge_budget.reset_nudge_budget()
        self.addCleanup(nudge_budget.reset_nudge_budget)
        verify_hooks.reset_stashed_answers()
        self.addCleanup(verify_hooks.reset_stashed_answers)

    def stop(self, *paths: str):
        return verify_hooks.pre_verify(session_id=SESSION, coding=True, attempt=0, final_response='{"changed_paths": []}',
                                       changed_paths=list(paths), omh_home=str(self.home), hermes_home=str(self.hermes))

    def test_the_note_continues_the_turn_with_the_check_beside_it(self):
        note = self.kwarg_turn()
        result = self.stop(str(self.root / "src/benchapp/http_client.py"), str(self.root / "tests/test_http_client.py"))
        self.assertEqual(result["message"], "\n".join(
            [note, verify_hooks.ROUND_END_CHECKLIST_BESIDE_A_RECHECK, verify_hooks.ROUND_END_CLOSING]))
        self.assertNotIn(SESSION, ct._sessions)

    def test_without_a_changed_expectation_nothing_new_is_said(self):
        self.write("src/app/units.py", "def parse(text):\n    return int(text) * 60\n")
        tc.note_request(SESSION, "Fix parse without changing its signature.")
        changed = self.edit("src/app/units.py", "* 60", "* 1")
        self.assertIsNone(self.stop(changed))

    def test_pre_llm_call_records_the_request_before_any_binding(self):
        from omh.plugin_bundle.omh.hooks import llm_hooks

        with mock.patch.object(llm_hooks.runtime_paths, "plugin_home", side_effect=RuntimeError("no home")):
            llm_hooks.pre_llm_call(session_id=SESSION, platform="cli", user_message=KWARG)
        self.assertTrue(tc._requests[SESSION].keeps_behaviour)
        with mock.patch.object(llm_hooks.runtime_paths, "plugin_home", side_effect=RuntimeError("no home")):
            llm_hooks.pre_llm_call(session_id=SESSION, platform="cli", user_message="Add a feature.")
        self.assertFalse(tc._requests[SESSION].keeps_behaviour)


if __name__ == "__main__":
    unittest.main()
