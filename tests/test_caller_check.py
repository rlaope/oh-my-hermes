"""The round-end caller check: calls a turn's signature change broke, named by file and line.

The measured miss (2026-10-31 and 2026-11-02 head-to-heads): every OMH `I-SIGNATURE` failure left
`cli.py`'s `fee(int(argv[0]), 50)` broken, a call that reaches `compute_fee` through the package
re-export `from .pricing import compute_fee as fee`. The round-end consistency check fired and named no
line; the model grepped `compute_fee` and stopped. These tests pin what the check names, where it stays
silent, and where its note sits in the one `pre_verify` message.
"""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import caller_check  # noqa: E402
from omh.plugin_bundle.omh import consistency_trigger as ct  # noqa: E402
from omh.plugin_bundle.omh.consistency_trigger import Verdict  # noqa: E402
from omh.plugin_bundle.omh.hooks import nudge_budget, verify_hooks  # noqa: E402
from omh.plugin_bundle.omh.impact_check import format_note as impact_format_note  # noqa: E402

SESSION = "caller-check-session"
PRICING = ('"""Fee arithmetic."""\n\n\ndef compute_fee(amount_cents: int, rate_bp: int) -> int:\n'
           "    return amount_cents * rate_bp // 10000\n")
OLD_DEF = "def compute_fee(amount_cents: int, rate_bp: int) -> int:"
NEW_DEF = "def compute_fee(amount_cents: int, rate_bp: int, minimum_cents: int) -> int:"
NEW_SIGNATURE = "`compute_fee(amount_cents: int, rate_bp: int, minimum_cents: int)` in src/benchapp/pricing.py"
FIXTURE = {
    "pyproject.toml": "[project]\nname='benchapp'\n",
    "src/benchapp/__init__.py": 'from .pricing import compute_fee as fee\n\n__all__ = ["fee"]\n',
    "src/benchapp/pricing.py": PRICING,
    "src/benchapp/billing.py": ("from benchapp.pricing import compute_fee\n\n\n"
                                "def bill_total(amount_cents: int) -> int:\n"
                                "    return amount_cents + compute_fee(amount_cents, 250)\n"),
    "src/benchapp/invoices.py": ("from benchapp.pricing import compute_fee as calc_fee\n\n\n"
                                 "def invoice_fee(amount_cents: int) -> int:\n    return calc_fee(amount_cents, 500)\n"),
    "src/benchapp/report.py": ("from benchapp import pricing\n\n\n"
                               'def fee_line(amount_cents: int) -> str:\n'
                               '    return f"fee={pricing.compute_fee(amount_cents, 100)}"\n'),
    "src/benchapp/cli.py": ("from benchapp import fee\n\n\n"
                            "def cli_fee(argv: list[str]) -> int:\n    return fee(int(argv[0]), 50)\n"),
}


class _Turn(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        patcher = mock.patch.object(ct, "_workspace_root", lambda task_id: str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        ct.reset()
        self.addCleanup(ct.reset)

    def write(self, relative: str, text: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return str(path)

    def edit(self, relative: str, old: str, new: str) -> str:
        ct.snapshot_before_edit({"tool_name": "patch", "session_id": SESSION, "turn_id": "t1"},
                                {"path": relative, "old_string": old, "new_string": new})
        text = (self.root / relative).read_text(encoding="utf-8")
        self.assertIn(old, text)
        return self.write(relative, text.replace(old, new, 1))

    def fixture(self, **overrides: str) -> None:
        for relative, text in {**FIXTURE, **overrides}.items():
            self.write(relative, text)

    def note(self, reported: str = "") -> str:
        return caller_check.round_end_note(SESSION, ct.turn_root(SESSION), reported)


class NamedCallsTest(_Turn):
    def test_the_measured_miss_is_named_through_the_package_re_export(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.edit("src/benchapp/billing.py", "compute_fee(amount_cents, 250)", "compute_fee(amount_cents, 250, minimum_cents=0)")
        self.edit("src/benchapp/invoices.py", "calc_fee(amount_cents, 500)", "calc_fee(amount_cents, 500, minimum_cents=0)")
        self.edit("src/benchapp/report.py", "compute_fee(amount_cents, 100)", "compute_fee(amount_cents, 100, minimum_cents=0)")
        self.assertEqual(self.note().splitlines(), [
            "OMH caller check: a function you changed this turn is still called the old way, and these calls now fail:",
            f"src/benchapp/cli.py:5: `fee(int(argv[0]), 50)`: missing `minimum_cents`; it is now {NEW_SIGNATURE}",
            "Update each call to the new signature.",
        ])

    def test_an_alias_a_module_attribute_and_a_direct_call_are_each_named(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        rows = [line.split(": ", 1)[0] for line in self.note().splitlines()[1:-1]]
        self.assertEqual(rows, ["src/benchapp/billing.py:5", "src/benchapp/cli.py:5", "src/benchapp/invoices.py:5",
                                "src/benchapp/report.py:5"])

    def test_a_call_in_the_edited_module_itself_is_named(self):
        self.fixture(**{"src/benchapp/pricing.py": PRICING + "\n\ndef flat_fee() -> int:\n    return compute_fee(100, 5)\n"})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.assertIn("src/benchapp/pricing.py:9: `compute_fee(100, 5)`: missing `minimum_cents`", self.note())

    def test_a_renamed_keyword_names_each_call_still_passing_the_old_one(self):
        client = ("def fetch(url: str, *, timeout: float = 5.0, retries: int = 1) -> dict:\n"
                  '    return {"url": url, "timeout": timeout}\n')
        self.write("pyproject.toml", "[project]\nname='benchapp'\n")
        self.write("src/benchapp/__init__.py", "")
        self.write("src/benchapp/http_client.py", client)
        self.write("src/benchapp/sync.py", "from benchapp.http_client import fetch\n\n\ndef sync(u):\n    return fetch(u, timeout=2.0)\n")
        self.write("src/benchapp/health.py", "from benchapp import http_client as hc\n\n\ndef ping(u):\n"
                                             "    return hc.fetch(u, timeout=1.0, retries=0)\n")
        self.write("src/benchapp/crawler.py", "from benchapp.http_client import fetch\n\nOPTIONS = {'timeout': 3.0}\n\n\n"
                                              "def crawl(u):\n    return fetch(u, **OPTIONS)\n")
        self.edit("src/benchapp/http_client.py", "timeout: float = 5.0", "timeout_s: float = 5.0")
        note = self.note()
        self.assertIn("src/benchapp/sync.py:5: `fetch(u, timeout=2.0)`: unexpected keyword `timeout`; it is now "
                      "`fetch(url: str, *, timeout_s: float=5.0, retries: int=1)` in src/benchapp/http_client.py", note)
        self.assertIn("src/benchapp/health.py:5: `hc.fetch(u, timeout=1.0, retries=0)`: unexpected keyword `timeout`", note)
        # `**OPTIONS` cannot be bound without knowing the dict: silent, never guessed.
        self.assertNotIn("crawler.py", note)

    def test_binding_rules_follow_python(self):
        shape = caller_check._shape(_args("def f(a, /, b, c=1, *, d, e=2): pass"))
        self.assertEqual(caller_check._bind(shape, _call("f(1, 2, d=3)")), "")
        self.assertEqual(caller_check._bind(shape, _call("f(1, b=2, d=3, e=4)")), "")
        self.assertEqual(caller_check._bind(shape, _call("f(a=1, b=2, d=3)")), "positional-only `a` passed by keyword")
        self.assertEqual(caller_check._bind(shape, _call("f(1, 2, 3, 4, d=5)")), "4 positional arguments, but it takes 3")
        self.assertEqual(caller_check._bind(shape, _call("f(1, 2, b=2, d=3)")), "`b` given twice")
        self.assertEqual(caller_check._bind(shape, _call("f(1)")), "missing `b`, `d`")
        self.assertIsNone(caller_check._bind(shape, _call("f(*xs)")))
        self.assertIsNone(caller_check._bind(shape, _call("f(1, **kw)")))
        open_shape = caller_check._shape(_args("def f(a, *rest, **kw): pass"))
        self.assertEqual(caller_check._bind(open_shape, _call("f(1, 2, 3, anything=4)")), "")

    def test_the_rows_found_are_logged(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        with self.assertLogs("omh.caller_check", "INFO") as logs:
            self.note()
        self.assertRegex(logs.output[0], rf"caller_check round_end session={SESSION} functions=1 files=6 rows=4 "
                                         r"deadline=0 ms=\d+$")


class SilentTest(_Turn):
    def test_calls_the_edit_leaves_valid_are_silent(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", OLD_DEF,
                  "def compute_fee(amount_cents: int, rate_bp: int, *, minimum_cents: int = 0) -> int:")
        self.assertEqual(self.note(), "")

    def test_an_unchanged_signature_or_an_annotation_change_is_silent(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", "    return amount_cents * rate_bp // 10000",
                  "    return max(0, amount_cents * rate_bp // 10000)")
        self.edit("src/benchapp/pricing.py", "rate_bp: int)", "rate_bp: float)")
        self.assertEqual(self.note(), "")

    def test_a_call_that_did_not_bind_before_the_edit_is_not_the_edit_s(self):
        self.fixture(**{"src/benchapp/cli.py": "from benchapp import fee\n\n\ndef cli_fee(argv):\n    return fee(1)\n"})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.assertNotIn("cli.py", self.note())

    def test_a_call_written_to_fail_is_not_named(self):
        # Measured on gpt-6.1-sol I-KWARG: its new test pins that the old keyword is rejected.
        self.fixture(**{"tests/test_pricing.py": (
            "import unittest\nimport pytest\nfrom benchapp.pricing import compute_fee\n\n\n"
            "def test_old_call_is_rejected():\n    with pytest.raises(TypeError):\n        compute_fee(1, 2)\n"
            "    pytest.raises(TypeError, lambda: compute_fee(3, 4))\n"
            "    try:\n        compute_fee(5, 6)\n    except (TypeError, ValueError):\n        pass\n\n\n"
            "class T(unittest.TestCase):\n    def test_old(self):\n        with self.assertRaises(TypeError):\n"
            "            compute_fee(7, 8)\n"
            "        try:\n            compute_fee(9, 10)\n        except KeyError:\n            pass\n")})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        rows = [line.split(": ", 1)[0] for line in self.note().splitlines() if line.startswith("tests/")]
        # Only the call under a handler that does not catch TypeError is still named.
        self.assertEqual(rows, ["tests/test_pricing.py:21"])

    def test_a_shadowed_name_is_not_resolved(self):
        self.fixture(**{"src/benchapp/cli.py": ("from benchapp import fee\n\n\ndef cli_fee(argv, fee=fee):\n"
                                                "    return fee(int(argv[0]), 50)\n")})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.assertNotIn("cli.py", self.note())

    def test_a_fallback_import_binds_the_name_twice_and_is_silent(self):
        self.fixture(**{"src/benchapp/cli.py": ("try:\n    from benchapp import fee\nexcept ImportError:\n    fee = None\n\n\n"
                                                "def cli_fee(argv):\n    return fee(int(argv[0]), 50)\n")})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.assertNotIn("cli.py", self.note())

    def test_a_star_import_or_a_reassigned_attribute_is_silent(self):
        self.fixture(**{"src/benchapp/cli.py": ("from benchapp import fee\nfrom benchapp.extra import *\n\n\n"
                                                "def cli_fee(argv):\n    return fee(int(argv[0]), 50)\n"),
                        "src/benchapp/report.py": ("from benchapp import pricing\n\npricing.compute_fee = lambda *a: 0\n\n\n"
                                                   "def fee_line(a):\n    return pricing.compute_fee(a, 100)\n")})
        self.write("src/benchapp/extra.py", "")
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        note = self.note()
        self.assertNotIn("cli.py", note)
        self.assertNotIn("report.py", note)

    def test_a_decorated_or_twice_defined_function_is_silent(self):
        decorated = PRICING.replace("def compute_fee", "@cache\ndef compute_fee")
        self.fixture(**{"src/benchapp/pricing.py": "from functools import cache\n" + decorated})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.assertEqual(self.note(), "")
        ct.reset()
        self.fixture(**{"src/benchapp/pricing.py": PRICING + "\n\nif True:\n    compute_fee = compute_fee\n"})
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        self.assertEqual(self.note(), "")

    def test_without_a_turn_start_snapshot_nothing_is_said(self):
        self.fixture()
        ct.snapshot_before_edit({"tool_name": "read_file", "session_id": SESSION, "turn_id": "t1"}, {"path": "x.py"})
        self.write("src/benchapp/pricing.py", PRICING.replace(OLD_DEF, NEW_DEF))
        self.assertEqual(self.note(), "")
        self.assertEqual(caller_check.round_end_note(SESSION, None), "")

    def test_a_line_another_note_names_is_not_named_again(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        impact = impact_format_note([("src/benchapp/cli.py", 5, "Argument missing")], recheck_tool=False)
        note = self.note(impact)
        self.assertNotIn("cli.py:5", note)
        self.assertIn("billing.py:5", note)

    def test_a_failure_says_nothing_and_logs_a_warning(self):
        self.fixture()
        self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)
        with mock.patch.object(caller_check, "find_importers", side_effect=RuntimeError("boom")), \
                self.assertLogs("omh.caller_check", "WARNING") as logs:
            self.assertEqual(self.note(), "")
        self.assertIn("failed=RuntimeError", logs.output[0])


class PreVerifyCompositionTest(_Turn):
    def setUp(self):
        super().setUp()
        nudge_budget.reset_nudge_budget()
        self.addCleanup(nudge_budget.reset_nudge_budget)
        verify_hooks.reset_stashed_answers()
        self.addCleanup(verify_hooks.reset_stashed_answers)
        self.fixture()
        self.pricing = self.edit("src/benchapp/pricing.py", OLD_DEF, NEW_DEF)

    def fire(self, **overrides):
        payload = {"session_id": SESSION, "coding": True, "attempt": 0, "final_response": "{}",
                   "changed_paths": [self.pricing], "omh_home": str(self.root / ".omh-home")}
        payload.update(overrides)
        return verify_hooks.pre_verify(**payload)

    def test_the_note_continues_the_turn_and_asks_for_the_full_answer(self):
        caller = self.note()
        result = self.fire()
        self.assertEqual(result["action"], "continue")
        self.assertEqual(result["message"], "\n".join((caller, verify_hooks.ROUND_END_CHECKLIST,
                                                       verify_hooks.ROUND_END_CLOSING_UNSTASHED)))
        # A fix is still owed, so no "nothing more changed" line is offered and nothing is stashed.
        self.assertNotIn(verify_hooks.ROUND_END_SENTINEL, result["message"])
        self.assertNotIn(SESSION, verify_hooks._STASHED_ANSWERS)

    def test_outside_coding_the_note_alone_continues(self):
        message = self.fire(coding=False)["message"]
        self.assertTrue(message.startswith("OMH caller check:"))
        self.assertTrue(message.endswith(verify_hooks.ROUND_END_CLOSING_UNSTASHED))

    def test_the_note_needs_no_trigger_verdict_and_sits_after_the_impact_note(self):
        def trigger(session_id, code_paths):
            raise AssertionError("beside the caller note the check needs no verdict")

        impact = impact_format_note([("src/benchapp/billing.py", 5, "Argument missing")], recheck_tool=False)
        with mock.patch.object(verify_hooks, "round_end_trigger", trigger), \
                mock.patch.object(verify_hooks, "round_end_note", lambda session_id, changed_paths: impact):
            message = self.fire()["message"]
        self.assertLess(message.index("OMH impact check"), message.index("OMH caller check"))
        self.assertLess(message.index("OMH caller check"), message.index("OMH round-end consistency check"))
        self.assertEqual(message.count("src/benchapp/billing.py:5"), 1)
        self.assertEqual(message.count("When you are done"), 1)

    def test_a_later_stop_and_a_fixed_tree_say_nothing_new(self):
        self.assertIsNone(self.fire(attempt=1, coding=False))
        for relative, call in (("billing.py", "compute_fee(amount_cents, 250)"), ("invoices.py", "calc_fee(amount_cents, 500)"),
                               ("report.py", "compute_fee(amount_cents, 100)"), ("cli.py", "fee(int(argv[0]), 50)")):
            path = self.root / "src/benchapp" / relative
            path.write_text(path.read_text(encoding="utf-8").replace(call, call[:-1] + ", minimum_cents=0)"),
                            encoding="utf-8")
        with mock.patch.object(verify_hooks, "round_end_trigger",
                               lambda session_id, code_paths: Verdict(False, "no_copy_or_reference")):
            self.assertIsNone(self.fire())


def _args(source: str) -> ast.arguments:
    return ast.parse(source).body[0].args


def _call(source: str) -> ast.Call:
    return ast.parse(source, mode="eval").body


if __name__ == "__main__":
    unittest.main()
