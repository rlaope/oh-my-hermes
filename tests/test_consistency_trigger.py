"""The trigger that decides whether the round-end consistency check is worth its extra round.

`pre_tool_call` keeps the pre-edit text of each Python file a turn edits; at the turn's first stop
`pre_verify` asks `round_end_trigger` whether a copy or a reference of the edit exists outside the
edited files. No signal skips the check; anything undecidable fires it, as it fired before.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package
from _platform_support import requires_symlinks

load_local_package()

from omh.plugin_bundle.omh import consistency_trigger as ct  # noqa: E402
from omh.plugin_bundle.omh.hooks import nudge_budget, verify_hooks  # noqa: E402

SESSION = "trigger-session"
INVOICE = (
    '"""Invoice totals."""\nfrom decimal import Decimal, ROUND_HALF_EVEN\n\nCENT = Decimal("0.01")\n\n\n'
    "def _to_cents(amount: str) -> Decimal:\n    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_EVEN)\n\n\n"
    "def invoice_total(amounts: list[str]) -> Decimal:\n"
    '    return sum((_to_cents(amount) for amount in amounts), Decimal("0.00"))\n'
)
RECEIPT = (
    '"""Receipt totals."""\nimport decimal\n\n\n'
    "def _to_cents(amount: str) -> decimal.Decimal:\n"
    '    return decimal.Decimal(amount).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_EVEN)\n'
)
UNITS = (
    '"""Units."""\nimport re\n\n_DURATION_SECONDS = {"s": 60, "m": 60, "h": 3600}\n\n\n'
    "def parse_duration(text: str) -> int:\n    return int(text[:-1]) * _DURATION_SECONDS[text[-1]]\n"
)
TO_CENTS = '"""Money units."""\n\n\ndef to_cents(amount: float) -> int:\n    return int(round(amount * 100))\n'
CART = "from benchapp.units import to_cents\n\n\ndef cart_total(prices: list[float]) -> int:\n    return sum(map(to_cents, prices))\n"


class _Workspace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        patcher = mock.patch.object(ct, "_workspace_root", lambda task_id: str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        ct.reset()
        self.addCleanup(ct.reset)
        self.turn = "t1"

    def write(self, relative: str, text: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return relative

    def edit(self, relative: str, old: str, new: str, session: str = SESSION) -> str:
        """Snapshot through the `pre_tool_call` entry point, then land a replace-mode `patch`."""
        args = {"path": relative, "old_string": old, "new_string": new}
        ct.snapshot_before_edit({"tool_name": "patch", "session_id": session, "turn_id": self.turn}, args)
        path = self.root / relative
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
        return str(path)

    def create(self, relative: str, text: str) -> str:
        ct.snapshot_before_edit({"tool_name": "write_file", "session_id": SESSION, "turn_id": self.turn},
                                {"path": relative, "content": text})
        return str(self.root / self.write(relative, text))

    def verdict(self, *paths: str) -> ct.Verdict:
        return ct.round_end_trigger(SESSION, tuple(paths))


class CopySignalTest(_Workspace):
    def test_a_second_copy_of_the_edited_helper_fires(self):
        self.write("src/app/invoice.py", INVOICE)
        self.write("src/app/receipt.py", RECEIPT)
        changed = self.edit("src/app/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n")
        verdict = self.verdict(changed)
        self.assertEqual((verdict.fire, verdict.reason), (True, "copy"))
        self.assertIn("_to_cents in src/app/receipt.py", verdict.detail)

    def test_both_copies_already_edited_skips(self):
        self.write("src/app/invoice.py", INVOICE)
        self.write("src/app/receipt.py", RECEIPT)
        first = self.edit("src/app/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n")
        second = self.edit("src/app/receipt.py", "rounding=decimal.ROUND_HALF_EVEN", "rounding=decimal.ROUND_HALF_UP")
        self.assertEqual(self.verdict(first, second), ct.Verdict(False, "no_copy_or_reference"))

    def test_an_edit_with_no_copy_or_reference_elsewhere_skips(self):
        self.write("src/app/units.py", UNITS)
        self.write("src/app/other.py", "def unrelated() -> int:\n    return 1\n")
        changed = self.edit("src/app/units.py", '{"s": 60,', '{"s": 1,')
        test = self.create("tests/test_units.py", "from app.units import parse_duration\n\n\n"
                           "def test_seconds():\n    assert parse_duration('90s') == 90\n")
        verdict = self.verdict(changed, test)
        self.assertFalse(verdict.fire)
        self.assertEqual(verdict.reason, "no_copy_or_reference")

    def test_a_common_or_dunder_name_defined_elsewhere_is_not_a_copy(self):
        self.write("src/app/a.py", '__all__ = ["main"]\n\n\ndef main() -> int:\n    return 1\n')
        self.write("src/app/b.py", '__all__ = ["main"]\n\n\ndef main() -> int:\n    return 2\n')
        changed = self.edit("src/app/a.py", "return 1", "return 3")
        self.assertFalse(self.verdict(changed).fire)

    def test_a_replaced_line_that_also_appears_elsewhere_fires(self):
        line = "    total = sum(item.price * item.quantity for item in basket)\n"
        self.write("src/app/a.py", f"def cost(basket):\n{line}    return total\n")
        self.write("src/app/b.py", f"def cost_with_tax(basket, rate):\n{line}    return total * rate\n")
        changed = self.edit("src/app/a.py", "item.price * item.quantity", "item.unit_price * item.quantity")
        verdict = self.verdict(changed)
        self.assertEqual((verdict.fire, verdict.reason, verdict.detail), (True, "line_copy", "src/app/b.py"))


class ReferenceSignalTest(_Workspace):
    def test_a_renamed_definition_still_named_in_an_unedited_file_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/cart.py", CART)
        changed = self.edit("src/app/units.py", "def to_cents(", "def amount_to_cents(")
        verdict = self.verdict(changed)
        self.assertEqual((verdict.fire, verdict.reason), (True, "renamed"))
        self.assertIn("to_cents in src/app/cart.py", verdict.detail)

    def test_a_rename_carried_into_every_reference_skips(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/cart.py", CART)
        first = self.edit("src/app/units.py", "def to_cents(", "def amount_to_cents(")
        second = self.edit("src/app/cart.py", "import to_cents", "import amount_to_cents")
        second = self.edit("src/app/cart.py", "map(to_cents,", "map(amount_to_cents,")
        self.assertFalse(self.verdict(first, second).fire)

    def test_a_changed_signature_with_a_caller_elsewhere_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/cart.py", CART)
        changed = self.edit("src/app/units.py", "(amount: float)", "(amount: float, *, places: int)")
        self.assertEqual(self.verdict(changed)[:2], (True, "signature"))

    def test_a_body_only_change_with_callers_elsewhere_skips(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/cart.py", CART)
        changed = self.edit("src/app/units.py", "    return int(", "    if amount < 0:\n        raise ValueError('negative amount')\n    return int(")
        self.assertEqual(self.verdict(changed)[:2], (False, "no_copy_or_reference"))


class FailOpenTest(_Workspace):
    def test_no_snapshot_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        self.assertEqual(self.verdict(str(self.root / "src/app/units.py"))[:2], (True, "no_snapshot"))

    def test_a_reported_file_without_its_own_snapshot_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/cart.py", CART)
        changed = self.edit("src/app/units.py", "return int(", "return int(")
        self.assertEqual(self.verdict(changed, str(self.root / "src/app/cart.py")),
                         ct.Verdict(True, "opaque_edit", "src/app/cart.py"))

    def test_a_non_python_source_file_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        changed = self.edit("src/app/units.py", "100", "1000")
        self.assertEqual(self.verdict(changed, "web/app.ts")[:2], (True, "not_python"))

    def test_a_file_that_no_longer_parses_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        changed = self.edit("src/app/units.py", "return int(", "return int((")
        self.assertEqual(self.verdict(changed)[:2], (True, "parse_error"))

    def test_the_scan_budget_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/cart.py", CART)
        changed = self.edit("src/app/units.py", "100", "1000")
        with mock.patch.object(ct, "MAX_SCAN_ENTRIES", 1):
            self.assertEqual(self.verdict(changed)[:2], (True, "scan_budget"))
        self.edit("src/app/units.py", "1000", "100")
        with mock.patch.object(ct, "SCAN_SECONDS", -1.0):
            self.assertEqual(self.verdict(changed)[:2], (True, "scan_budget"))

    def test_an_error_inside_the_decision_fires(self):
        self.write("src/app/units.py", TO_CENTS)
        changed = self.edit("src/app/units.py", "100", "1000")
        with mock.patch.object(ct, "_collect", side_effect=RuntimeError("boom")):
            self.assertEqual(self.verdict(changed), ct.Verdict(True, "error", "RuntimeError"))


class SnapshotStateTest(_Workspace):
    def test_the_first_pre_edit_text_of_the_turn_is_kept(self):
        self.write("src/app/units.py", TO_CENTS)
        self.edit("src/app/units.py", "100", "1000")
        self.edit("src/app/units.py", "1000", "10")
        path = os.path.realpath(self.root / "src/app/units.py")
        self.assertEqual(ct._sessions[SESSION]["before"][path], TO_CENTS)

    def test_a_new_turn_starts_over_and_a_verdict_consumes_the_turn(self):
        self.write("src/app/units.py", TO_CENTS)
        self.edit("src/app/units.py", "100", "1000")
        self.turn = "t2"
        changed = self.edit("src/app/units.py", "1000", "10")
        path = os.path.realpath(self.root / "src/app/units.py")
        self.assertIn("1000", ct._sessions[SESSION]["before"][path])
        self.verdict(changed)
        self.assertNotIn(SESSION, ct._sessions)

    def test_a_new_file_snapshots_as_empty_and_non_python_or_other_tools_are_ignored(self):
        self.create("src/app/new.py", "def fresh() -> int:\n    return 1\n")
        ct.snapshot_before_edit({"tool_name": "write_file", "session_id": SESSION, "turn_id": "t1"},
                                {"path": "README.md", "content": "x"})
        ct.snapshot_before_edit({"tool_name": "read_file", "session_id": SESSION, "turn_id": "t1"},
                                {"path": "src/app/other.py"})
        self.assertEqual(ct._sessions[SESSION]["before"], {os.path.realpath(self.root / "src/app/new.py"): ""})

    def test_v4a_patch_headers_are_snapshotted(self):
        self.write("src/app/units.py", TO_CENTS)
        body = "*** Begin Patch\n*** Update File: src/app/units.py\n@@\n-x\n+y\n*** Add File: src/app/added.py\n+z\n*** End Patch\n"
        ct.snapshot_before_edit({"tool_name": "patch", "session_id": SESSION, "turn_id": "t1"}, {"mode": "patch", "patch": body})
        self.assertEqual(sorted(ct._sessions[SESSION]["before"].values()), ["", TO_CENTS])

    def test_snapshots_are_bounded_per_session_and_across_sessions(self):
        for index in range(ct.MAX_SNAPSHOT_FILES + 3):
            self.create(f"src/app/m{index}.py", "")
        self.assertEqual(len(ct._sessions[SESSION]["before"]), ct.MAX_SNAPSHOT_FILES)
        for index in range(ct._MAX_SESSIONS + 2):
            ct.snapshot_before_edit({"tool_name": "write_file", "session_id": f"s{index}", "turn_id": "t1"},
                                    {"path": "src/app/m0.py"})
        self.assertEqual(len(ct._sessions), ct._MAX_SESSIONS)

    def test_a_malformed_call_never_raises_and_keeps_no_snapshot(self):
        ct.snapshot_before_edit({"tool_name": "patch", "session_id": SESSION}, None)
        ct.snapshot_before_edit({"tool_name": "patch", "session_id": SESSION}, {"path": 7})
        self.assertEqual(ct._sessions[SESSION]["before"], {})
        with mock.patch.object(ct, "_workspace_root", side_effect=RuntimeError("no root")):
            ct.snapshot_before_edit({"tool_name": "patch", "session_id": "other"}, {"path": "a.py"})
        self.assertNotIn("other", ct._sessions)


class OpaqueEditTest(_Workspace):
    """Python files a turn changed without `patch` / `write_file`, which Hermes's changed_paths omit."""

    def tool(self, name: str = "terminal", session: str = SESSION) -> None:
        """A non-edit tool call; the turn's first one takes the workspace index."""
        ct.snapshot_before_edit({"tool_name": name, "session_id": session, "turn_id": self.turn}, {"command": "x"})

    def test_a_sed_rename_in_another_file_fires(self):
        self.write("src/app/a.py", "def old_name(a):\n    return a\n")
        self.write("src/app/b.py", "def other():\n    return 1\n")
        self.write("src/app/use.py", "from app.a import old_name\nold_name(1)\n")
        self.tool()
        self.write("src/app/a.py", "def renamed_name(a):\n    return a\n")  # sed -i, through `terminal`
        changed = self.edit("src/app/b.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/a.py"))

    def test_a_sed_rename_then_a_patch_of_the_same_file_fires(self):
        self.write("src/app/a.py", "def old_name(a):\n    return a\n\n\ndef other():\n    return 1\n")
        self.write("src/app/use.py", "from app.a import old_name\nold_name(1)\n")
        self.tool()
        self.write("src/app/a.py", "def renamed_name(a):\n    return a\n\n\ndef other():\n    return 1\n")
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/a.py"))

    def test_a_file_execute_code_created_fires(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.tool("execute_code")
        self.write("src/app/generated.py", "def made() -> int:\n    return 1\n")
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/generated.py"))

    def test_a_delegated_childs_edit_fires_for_the_parent(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.write("src/app/b.py", "def helper():\n    return 1\n")
        self.tool("delegate_task")
        self.edit("src/app/b.py", "return 1", "return 3", session="child-session")
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/b.py"))

    def widen_racy_window(self) -> None:
        """An hour-wide racy window: a runner stalled between a fixture write and the index must not
        turn a fresh file stale and decide the test (the window itself is not what these tests pin)."""
        patcher = mock.patch.object(ct, "RACY_WINDOW_NS", 3600 * 1_000_000_000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rewrite_in_one_clock_tick(self, relative: str, text: str) -> None:
        """A same-size rewrite that keeps the file's mtime, as two writes inside one tick of a coarse
        filesystem clock do (Windows CI, where this let a sed pass unseen)."""
        path = self.root / relative
        before = os.stat(path)
        self.write(relative, text)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.stat(path)
        self.assertEqual((after.st_mtime_ns, after.st_size), (before.st_mtime_ns, before.st_size),
                         "precondition: the rewrite must leave (mtime, size) where the index saw it")

    def test_a_same_size_sed_inside_one_clock_tick_fires(self):
        self.widen_racy_window()
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.write("src/app/b.py", "def old_step():\n    return 1\n")
        self.tool()
        self.rewrite_in_one_clock_tick("src/app/b.py", "def new_step():\n    return 1\n")
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        entry = ct._sessions[SESSION]["index"].get(str(self.root / "src/app/b.py"))
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/b.py"),
                         f"b.py indexed as {entry!r}: a third field is the digest of a file the index "
                         "saw as racy; without one the racy window did not cover it")

    def test_a_same_size_sed_then_a_patch_of_the_same_file_inside_one_clock_tick_fires(self):
        self.widen_racy_window()
        self.write("src/app/a.py", "def old_name(a):\n    return a\n\n\ndef other():\n    return 1\n")
        self.write("src/app/use.py", "from app.a import old_name\nold_name(1)\n")
        self.tool()
        self.rewrite_in_one_clock_tick("src/app/a.py",
                                       "def new_name(a):\n    return a\n\n\ndef other():\n    return 1\n")
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/a.py"))

    def test_only_a_file_inside_the_racy_window_is_digested(self):
        self.widen_racy_window()
        old = self.write("src/app/old.py", "def old():\n    return 1\n")
        fresh = self.write("src/app/fresh.py", "def fresh():\n    return 1\n")
        long_ago = time.time_ns() - 2 * ct.RACY_WINDOW_NS
        os.utime(self.root / old, ns=(long_ago, long_ago))
        with mock.patch.object(ct, "_digest", wraps=ct._digest) as digests:
            self.tool()
        index = ct._sessions[SESSION]["index"]
        self.assertEqual(len(index[str(self.root / old)]), 2)
        self.assertEqual(len(index[str(self.root / fresh)]), 3)
        digests.assert_called_once_with(str(self.root / fresh))

    def test_a_racy_file_that_could_not_be_digested_fires(self):
        self.widen_racy_window()
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.write("src/app/locked.py", "def locked():\n    return 1\n")
        digest = ct._digest
        with mock.patch.object(ct, "_digest", lambda path: None if path.endswith("locked.py") else digest(path)):
            self.tool()
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/locked.py"))

    def test_an_oversized_racy_file_is_not_read_and_fires(self):
        self.widen_racy_window()
        self.write("src/app/a.py", "def other():\n    return 1\n")
        big = str(self.root / self.write("src/app/big.py", "#" * 256))
        reads: list[tuple[str, int]] = []
        real_open = open

        class Recording:
            def __init__(self, path, mode="r"):
                self.path, self.handle = path, real_open(path, mode)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.handle.close()

            def fileno(self):
                return self.handle.fileno()

            def read(self, size=-1):
                reads.append((self.path, size))
                return self.handle.read(size)

        with mock.patch.object(ct, "MAX_FILE_BYTES", 200), \
                mock.patch.object(ct, "open", Recording, create=True):
            self.tool()
        self.assertEqual([size for path, size in reads if path == big], [],
                         "the oversized file was read for a digest instead of refused on its size")
        self.assertEqual(ct._sessions[SESSION]["index"][big][2:], (None,))
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "src/app/big.py"))

    def test_a_tool_call_that_changes_no_python_file_does_not_fire(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.tool()
        self.write("src/app/__pycache__/a.cpython-311.pyc", "x")  # a test run's bytecode
        self.write("notes.txt", "ran the tests")
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed)[:2], (False, "no_copy_or_reference"))

    def test_an_index_past_its_budget_fires(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        with mock.patch.object(ct, "MAX_SCAN_ENTRIES", 1):
            self.tool()
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed)[:2], (True, "index_budget"))

    def test_the_session_byte_cap_leaves_the_next_file_without_a_snapshot(self):
        self.write("src/app/a.py", "def a():\n    return 1\n")
        self.write("src/app/b.py", "def b():\n    return 1\n")
        with mock.patch.object(ct, "MAX_SNAPSHOT_BYTES", 30):
            first = self.edit("src/app/a.py", "return 1", "return 2")
            second = self.edit("src/app/b.py", "return 1", "return 2")
        self.assertEqual(self.verdict(first, second), ct.Verdict(True, "opaque_edit", "src/app/b.py"))


class NamedFileSnapshotTest(_Workspace):
    """A `terminal` or `execute_code` call keeps the text of the Python files it names before it runs."""

    def command(self, command: str, tool: str = "terminal") -> None:
        key = "command" if tool == "terminal" else "code"
        ct.snapshot_before_edit({"tool_name": tool, "session_id": SESSION, "turn_id": self.turn}, {key: command})

    def test_a_test_appended_through_the_shell_is_diffed_not_opaque(self):
        test = "from app.units import parse_duration\n\n\ndef test_minutes():\n    assert parse_duration('5m') == 300\n"
        self.write("src/app/units.py", UNITS)
        self.write("tests/test_units.py", test)
        changed = self.edit("src/app/units.py", '{"s": 60,', '{"s": 1,')
        self.command("printf '\\n\\ndef test_seconds():\\n    assert parse_duration(\"90s\") == 90\\n' >> tests/test_units.py")
        self.write("tests/test_units.py", test + "\n\ndef test_seconds():\n    assert parse_duration('90s') == 90\n")
        self.assertEqual(self.verdict(changed), ct.Verdict(False, "no_copy_or_reference"))

    def test_a_sed_rename_of_a_named_file_is_judged_by_its_diff(self):
        self.write("src/app/a.py", "def old_name(a):\n    return a\n")
        self.write("src/app/use.py", "from app.a import old_name\nold_name(1)\n")
        self.command("sed -i '' 's/old_name/renamed_name/' src/app/a.py")
        self.write("src/app/a.py", "def renamed_name(a):\n    return a\n")
        self.assertEqual(self.verdict(), ct.Verdict(True, "renamed", "old_name in src/app/use.py"))

    def test_a_file_execute_code_names_and_creates_is_diffed(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.command("open('src/app/generated.py', 'w').write('def made():\\n    return 1\\n')", tool="execute_code")
        self.write("src/app/generated.py", "def made() -> int:\n    return 1\n")
        self.assertEqual(self.verdict(), ct.Verdict(False, "nothing_changed"))

    def test_only_whole_python_paths_are_named_and_the_count_is_bounded(self):
        self.assertEqual(ct._named_python_files({"command": "cat a.pyc b.py.bak c.pyi 'd/e.py' f.py. x ~/g.py *.py src/*.pyi",
                                                 "n": 3}), ["c.pyi", "d/e.py"])
        many = " ".join(f"m{index}.py" for index in range(20))
        self.assertEqual(len(ct._named_python_files({"command": many})), ct.MAX_NAMED_FILES)

    def test_files_read_only_commands_name_never_take_the_edits_budget(self):
        # Review of #2494: five `cat` calls naming 40 files filled the 32 slots, and a later patch fired
        # `opaque_edit` where main said `no_copy_or_reference`.
        for index in range(40):
            self.write(f"src/app/m{index}.py", f"def f{index}():\n    return {index}\n")
        self.write("src/app/units.py", UNITS)
        for batch in range(5):
            self.command("cat " + " ".join(f"src/app/m{index}.py" for index in range(batch * 8, batch * 8 + 8)))
        changed = self.edit("src/app/units.py", '{"s": 60,', '{"s": 1,')
        self.assertEqual(ct._sessions[SESSION]["named"], {})
        self.assertEqual(self.verdict(changed), ct.Verdict(False, "no_copy_or_reference"))

    def test_the_named_budget_is_its_own_and_bounded(self):
        for index in range(ct.MAX_NAMED_SNAPSHOTS + 4):
            self.write(f"src/app/m{index}.py", "x = 1\n")
        self.command("cat " + " ".join(f"src/app/m{index}.py" for index in range(8)))
        self.command("cat " + " ".join(f"src/app/m{index}.py" for index in range(8, 16)))
        self.assertLessEqual(len(ct._sessions[SESSION]["named"]), ct.MAX_NAMED_SNAPSHOTS)
        self.assertEqual(ct._sessions[SESSION]["before"], {})

    def test_a_stop_with_no_edited_path_keeps_no_snapshot(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.command("cat src/app/a.py")
        self.assertIn(SESSION, ct._sessions)
        self.assertIsNone(verify_hooks.pre_verify(session_id=SESSION, coding=True, attempt=0, changed_paths=[]))
        self.assertNotIn(SESSION, ct._sessions)

    def test_a_file_changed_before_the_call_that_names_it_is_still_opaque(self):
        self.write("src/app/a.py", "def other():\n    return 1\n")
        self.command("true")
        # An unnamed change first, of the same size: the racy-file digest sees it even when the clock
        # leaves (mtime, size) unmoved.
        self.write("src/app/a.py", "def other():\n    return 2\n")
        self.command("cat src/app/a.py")
        self.assertEqual(self.verdict(), ct.Verdict(True, "opaque_edit", "src/app/a.py"))


DECOY = (
    '"""Duty amounts. The duty rules require half-to-even (banker\'s) rounding to the cent,\n'
    'so this rounding is intentionally different from invoice.py."""\nimport decimal\n\n\n'
    "def _to_cents(amount: str) -> decimal.Decimal:\n"
    '    return decimal.Decimal(amount).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_EVEN)\n'
)


class DeclaredDivergenceTest(_Workspace):
    """A look-alike that says it differs from the edited file on purpose is not a copy to update."""

    def fix_invoice(self) -> str:
        self.write("src/app/invoice.py", INVOICE)
        return self.edit("src/app/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n")

    def test_a_module_docstring_naming_the_edited_file_declares_it(self):
        self.write("src/app/duty.py", DECOY)
        self.assertEqual(self.verdict(self.fix_invoice()),
                         ct.Verdict(False, "declared_divergent", "_to_cents in src/app/duty.py"))

    def test_a_copy_kept_in_step_still_fires(self):
        self.write("src/app/receipt.py", RECEIPT.replace('"""Receipt totals."""',
                                                         '"""Receipt totals. Cent rounding here is kept in step with invoice.py."""'))
        self.assertEqual(self.verdict(self.fix_invoice())[:2], (True, "copy"))

    def test_a_module_docstring_naming_another_file_declares_nothing(self):
        self.write("src/app/duty.py", DECOY.replace("from invoice.py", "from orders.py"))
        self.assertEqual(self.verdict(self.fix_invoice()), ct.Verdict(True, "copy", "_to_cents in src/app/duty.py"))

    def test_a_definition_docstring_or_comment_declares_it_without_naming_a_file(self):
        body = '    return decimal.Decimal(amount).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_EVEN)\n'
        variants = {
            "docstring": ('import decimal\n\n\ndef _to_cents(amount: str) -> decimal.Decimal:\n'
                          '    """Half to even, deliberately different from the other totals."""\n' + body),
            "comment above": ("import decimal\n\n\n# Banker's rounding: this intentionally differs from the totals.\n"
                              "def _to_cents(amount: str) -> decimal.Decimal:\n" + body),
            "first-line comment": ("import decimal\n\n\ndef _to_cents(amount: str) -> decimal.Decimal:  # by design it diverges\n"
                                   + body),
        }
        for label, text in variants.items():
            with self.subTest(label):
                ct.reset()
                self.write("src/app/duty.py", text)
                self.assertEqual(self.verdict(self.fix_invoice())[:2], (False, "declared_divergent"))

    def test_a_note_that_the_copy_must_not_differ_declares_nothing(self):
        # Review of #2494: each of these once read as a declared divergence and hid a real copy.
        notes = (
            "Intentionally duplicated from invoice.py, so it must not differ.",
            "Deliberately kept identical to invoice.py; never let the two diverge.",
            "A deliberate copy of invoice.py, with no difference in rounding.",
            "Same rounding as invoice.py by design: any difference is a bug.",
            "Not intentionally different from invoice.py: keep the two in step.",
            "By design this mirrors invoice.py and should never differ.",
            "Intentionally different? No: it is kept in step with invoice.py.",
        )
        for note in notes:
            for where in ("module", "definition", "comment"):
                with self.subTest(note=note, where=where):
                    ct.reset()
                    if where == "module":
                        text = RECEIPT.replace('"""Receipt totals."""', f'"""Receipt totals. {note}"""')
                    elif where == "definition":
                        text = RECEIPT.replace("decimal.Decimal:\n", f'decimal.Decimal:\n    """{note}"""\n', 1)
                    else:
                        text = RECEIPT.replace("def _to_cents", f"# {note}\ndef _to_cents", 1)
                    self.write("src/app/receipt.py", text)
                    self.assertEqual(self.verdict(self.fix_invoice())[:2], (True, "copy"))

    def test_a_module_sentence_must_name_the_edited_file_and_speaks_only_for_what_it_names(self):
        variants = {
            # The stem as an ordinary word is not the file.
            "bare stem": DECOY.replace("from invoice.py", "from the invoice totals"),
            # A module sentence naming another definition of this module does not speak for `_to_cents`.
            "names another definition": DECOY.replace("so this rounding is", "so duty_total is") +
            "\n\ndef duty_total(amounts):\n    return [_to_cents(a) for a in amounts]\n",
        }
        for label, text in variants.items():
            with self.subTest(label):
                ct.reset()
                self.write("src/app/duty.py", text)
                self.assertEqual(self.verdict(self.fix_invoice())[:2], (True, "copy"))
        ct.reset()
        self.write("src/app/duty.py", DECOY.replace("so this rounding is", "so _to_cents is").replace(
            "from invoice.py", "from benchapp.invoice"))
        self.assertEqual(self.verdict(self.fix_invoice())[:2], (False, "declared_divergent"))

    def test_a_module_sentence_naming_no_definition_needs_a_single_shared_definition(self):
        # Re-review of #2494: a file sentence that names no definition covered the whole module, so a
        # real copy of `invoice_total` beside the declared `_to_cents` was hidden.
        total = ("\n\ndef invoice_total(amounts: list[str]) -> decimal.Decimal:\n"
                 '    return sum((_to_cents(amount) for amount in amounts), decimal.Decimal("0.00"))\n')
        for note in ("The rounding here is intentionally different from invoice.py.",
                     "Unlike invoice.py, receipts deliberately round differently."):
            with self.subTest(note=note):
                ct.reset()
                self.write("src/app/receipt.py", RECEIPT.replace('"""Receipt totals."""', f'"""Receipt totals. {note}"""')
                           + total)
                self.write("src/app/invoice.py", INVOICE)
                changed = self.edit("src/app/invoice.py", 'Decimal("0.00"))', 'Decimal("0"))')
                self.assertEqual(self.verdict(changed), ct.Verdict(True, "copy", "invoice_total in src/app/receipt.py"))
        # One shared definition: the module sentence speaks for it.
        ct.reset()
        self.write("src/app/receipt.py", RECEIPT.replace(
            '"""Receipt totals."""', '"""Receipt totals. Unlike invoice.py, receipts deliberately round differently."""'))
        self.assertEqual(self.verdict(self.fix_invoice())[:2], (False, "declared_divergent"))

    def test_a_note_that_limits_the_difference_declares_nothing(self):
        notes = (
            "Deliberately written to differ from invoice.py only in its imports.",
            "Intentionally differs from invoice.py only in naming; the arithmetic is equal.",
            "Purposely diverges from invoice.py in logging, while the rounding must match it exactly.",
            "Purposely diverges from invoice.py in logging only; the rounding must track it.",
            "Intentionally called with different inputs than invoice.py; the rounding is shared.",
            "Deliberately different in its error messages, but equivalent in its arithmetic.",
        )
        for note in notes:
            for where in ("module", "definition"):
                with self.subTest(note=note, where=where):
                    ct.reset()
                    if where == "module":
                        text = RECEIPT.replace('"""Receipt totals."""', f'"""Receipt totals. {note}"""')
                    else:
                        text = RECEIPT.replace("decimal.Decimal:\n", f'decimal.Decimal:\n    """{note}"""\n', 1)
                    self.write("src/app/receipt.py", text)
                    self.assertEqual(self.verdict(self.fix_invoice())[:2], (True, "copy"))

    def test_the_difference_word_must_follow_the_intent_word(self):
        for note in ("It is deliberately written so that it can differ from invoice.py.",
                     "Intentionally kept apart; it then diverges from invoice.py."):
            with self.subTest(note=note):
                ct.reset()
                self.write("src/app/receipt.py", RECEIPT.replace("decimal.Decimal:\n", f'decimal.Decimal:\n    """{note}"""\n', 1))
                self.assertEqual(self.verdict(self.fix_invoice())[:2], (True, "copy"))

    def test_an_intent_word_alone_or_a_note_elsewhere_declares_nothing(self):
        variants = {
            "intent only": DECOY.replace("intentionally different from", "intentionally written next to"),
            "differ only": DECOY.replace("intentionally different from", "different from"),
            "differ before intent": DECOY.replace("is intentionally different from", "differs, on purpose, from"),
            "string in a body": ('import decimal\n\n\ndef _to_cents(amount: str) -> decimal.Decimal:\n'
                                 '    note = "this is intentionally different"\n'
                                 '    return decimal.Decimal(amount).quantize(decimal.Decimal("0.01"))\n'),
        }
        for label, text in variants.items():
            with self.subTest(label):
                ct.reset()
                self.write("src/app/duty.py", text)
                self.assertEqual(self.verdict(self.fix_invoice())[:2], (True, "copy"))

    def test_a_real_copy_beside_a_declared_one_still_fires(self):
        self.write("src/app/duty.py", DECOY)
        self.write("src/app/receipt.py", RECEIPT)
        self.assertEqual(self.verdict(self.fix_invoice()), ct.Verdict(True, "copy", "_to_cents in src/app/receipt.py"))

    def test_a_declared_look_alike_still_counts_for_a_changed_signature(self):
        self.write("src/app/duty.py", DECOY + "\n\ndef duty_total(amounts):\n    return [_to_cents(a) for a in amounts]\n")
        self.write("src/app/invoice.py", INVOICE)
        changed = self.edit("src/app/invoice.py", "def _to_cents(amount: str)", "def _to_cents(amount: str, places: int = 2)")
        self.assertEqual(self.verdict(changed)[:2], (True, "signature"))


class IndexCostTest(_Workspace):
    def first_call(self, session: str = SESSION) -> None:
        ct.snapshot_before_edit({"tool_name": "read_file", "session_id": session, "turn_id": self.turn}, {"path": "x"})

    def test_an_over_budget_root_is_not_walked_again_within_the_ttl(self):
        self.write("src/app/a.py", "def a():\n    return 1\n")
        with mock.patch.object(ct, "MAX_SCAN_ENTRIES", 1):
            self.first_call()
        self.assertIsNone(ct._sessions[SESSION]["index"])
        self.turn = "t2"
        with mock.patch.object(ct, "_index", wraps=ct._index) as walks:
            self.first_call()
        walks.assert_not_called()
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed)[:2], (True, "index_budget"))
        self.turn = "t3"
        with mock.patch.object(ct, "OVER_BUDGET_SECONDS", 0.0), mock.patch.object(ct, "_index", wraps=ct._index) as walks:
            self.first_call()
        walks.assert_called_once()

    def test_a_session_on_a_no_check_platform_takes_no_index(self):
        from omh.plugin_bundle.omh.hooks.verify_hooks import _NO_CHECKLIST_PLATFORMS

        self.assertEqual(ct.NO_CHECK_PLATFORMS, _NO_CHECKLIST_PLATFORMS)
        self.write("src/app/a.py", "def a():\n    return 1\n")
        ct.note_turn_posture(SESSION, "subagent")
        ct.note_turn_posture("cli-session", "cli")
        with mock.patch.object(ct, "_index", wraps=ct._index) as walks:
            self.first_call()
            walks.assert_not_called()
            self.first_call("cli-session")
            walks.assert_called_once()
        changed = self.edit("src/app/a.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed)[:2], (True, "no_check_session"))

    def test_pre_llm_call_records_the_platform_before_any_binding(self):
        from omh.plugin_bundle.omh.hooks import llm_hooks

        with mock.patch.object(llm_hooks.runtime_paths, "plugin_home", side_effect=RuntimeError("no home")):
            llm_hooks.pre_llm_call(session_id=SESSION, platform="subagent", turn_id="t1", user_message="hi")
        self.assertIs(ct._posture[SESSION], False)


class ClassShapeTest(_Workspace):
    CALLER = "from app.m import Foo\n\n\ndef build():\n    return Foo(1)\n"

    def shape(self, module: str, old: str, new: str) -> ct.Verdict:
        self.write("src/app/m.py", module)
        self.write("src/app/use.py", self.CALLER)
        return self.verdict(self.edit("src/app/m.py", old, new))

    def test_a_constructor_gaining_a_parameter_fires_on_the_class(self):
        verdict = self.shape("class Foo:\n    def __init__(self, a):\n        self.a = a\n",
                             "def __init__(self, a):", "def __init__(self, a, b):")
        self.assertEqual(verdict, ct.Verdict(True, "signature", "Foo in src/app/use.py"))

    def test_new_and_call_signatures_fire_on_the_class(self):
        for method in ("__new__", "__call__"):
            with self.subTest(method):
                verdict = self.shape(f"class Foo:\n    def {method}(self, a):\n        return a\n",
                                     f"def {method}(self, a):", f"def {method}(self, a, b):")
                self.assertEqual(verdict[:2], (True, "signature"))

    def test_a_dataclass_field_added_or_removed_fires(self):
        module = "from dataclasses import dataclass\n\n\n@dataclass\nclass Foo:\n    a: int\n    bee: int = 0\n"
        self.assertEqual(self.shape(module, "    a: int\n", "    a: int\n    c: int\n")[:2], (True, "signature"))
        ct.reset()
        self.assertTrue(self.shape(module, "    bee: int = 0\n", "").fire)

    def test_an_abstract_method_added_fires(self):
        module = "import abc\n\n\nclass Foo(abc.ABC):\n    @abc.abstractmethod\n    def get(self, k): ...\n"
        verdict = self.shape(module, "    def get(self, k): ...\n",
                             "    def get(self, k): ...\n\n    @abc.abstractmethod\n    def put(self, k, v): ...\n")
        self.assertEqual(verdict[:2], (True, "signature"))

    def test_a_method_body_change_or_a_plain_new_method_does_not_fire(self):
        module = "class Foo:\n    def __init__(self, a):\n        self.a = a\n\n    def size(self):\n        return 1\n"
        self.assertFalse(self.shape(module, "return 1", "return 2").fire)
        ct.reset()
        self.assertFalse(self.shape(module, "        return 1\n",
                                    "        return 1\n\n    def extra(self):\n        return 2\n").fire)
        ct.reset()
        self.assertFalse(self.shape(module, "        self.a = a\n", "        self.a = int(a)\n").fire)


class BlockAndAttributionTest(_Workspace):
    USE = "from app.m import load_cfg, norm, f\n"

    def test_a_def_inside_try_or_if_renamed_fires(self):
        self.write("src/app/m.py", "try:\n    import ujson as json\nexcept ImportError:\n    import json\n\n"
                                   "if True:\n    def load_cfg(p):\n        return json.load(open(p))\n")
        self.write("src/app/use.py", self.USE)
        changed = self.edit("src/app/m.py", "def load_cfg(p):", "def read_cfg(p):")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "renamed", "load_cfg in src/app/use.py"))

    def test_one_of_two_platform_variants_changing_its_signature_fires(self):
        self.write("src/app/m.py", "import sys\nif sys.platform == 'win32':\n    def norm(p):\n        return p.lower()\n"
                                   "else:\n    def norm(p):\n        return p\n")
        self.write("src/app/use.py", self.USE)
        changed = self.edit("src/app/m.py", "    def norm(p):\n        return p\n", "    def norm(p, strict):\n        return p\n")
        self.assertEqual(self.verdict(changed)[:2], (True, "signature"))

    def test_an_overload_implementation_changing_its_signature_fires(self):
        self.write("src/app/m.py", "from typing import overload\n\n\n@overload\ndef f(x: int) -> int: ...\n\n\n"
                                   "@overload\ndef f(x: str) -> str: ...\n\n\ndef f(x):\n    return x\n")
        self.write("src/app/use.py", self.USE)
        changed = self.edit("src/app/m.py", "def f(x):\n    return x", "def f(x, y):\n    return x")
        self.assertEqual(self.verdict(changed)[:2], (True, "signature"))

    def test_a_change_touching_no_definition_fires_as_unattributed(self):
        self.write("src/app/m.py", "def run():\n    return 1\n\n\nprint(run())\n")
        changed = self.edit("src/app/m.py", "print(run())", "print(run() + 1)")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "unattributed", "src/app/m.py"))

    def test_docstring_edits_are_attributed(self):
        self.write("src/app/m.py", '"""Module notes."""\n\n\nclass Box:\n    """Holds a value."""\n\n\n'
                                   'def run():\n    """Run it."""\n    return 1\n')
        changed = self.edit("src/app/m.py", '"""Module notes."""', '"""Module notes, revised."""')
        self.assertEqual(self.verdict(changed)[:2], (False, "nothing_changed"))
        ct.reset()
        changed = self.edit("src/app/m.py", '"""Holds a value."""', '"""Holds one value."""')
        self.assertFalse(self.verdict(changed).fire)
        ct.reset()
        changed = self.edit("src/app/m.py", "\n\n\nclass Box:", "\n\n'not a docstring'\n\n\nclass Box:")
        self.assertEqual(self.verdict(changed)[:2], (True, "unattributed"))

    def test_a_tuple_assignment_defines_each_name(self):
        self.write("src/app/m.py", "LOW, HIGH = 1, 2\n")
        self.write("src/app/use.py", "from app.m import LOW\n")
        changed = self.edit("src/app/m.py", "LOW, HIGH = 1, 2", "MIN, HIGH = 1, 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "renamed", "LOW in src/app/use.py"))
        ct.reset()
        changed = self.edit("src/app/m.py", "MIN, HIGH = 1, 2\n", "MIN, HIGH = 1, 2\nA, B = 3, 4\n")
        self.assertFalse(self.verdict(changed).fire)

    def test_starred_and_nested_targets_define_their_names(self):
        cases = (("FIRST, *REST_ITEMS = [1, 2, 3]\n", "*REST_ITEMS", "*TAIL_ITEMS", "REST_ITEMS"),
                 ("A, (B_VAL, C_VAL) = 1, (2, 3)\n", "(B_VAL, C_VAL)", "(B_NEW, C_VAL)", "B_VAL"),
                 ("[X_ONE, [Y_TWO]] = [1, [2]]\n", "Y_TWO]]", "Y_NEW]]", "Y_TWO"))
        for module, old, new, name in cases:
            with self.subTest(name):
                ct.reset()
                self.write("src/app/m.py", module)
                self.write("src/app/use.py", f"from app.m import {name}\n")
                changed = self.edit("src/app/m.py", old, new)
                self.assertEqual(self.verdict(changed), ct.Verdict(True, "renamed", f"{name} in src/app/use.py"))

    def test_attribute_and_subscript_targets_bind_no_name(self):
        self.write("src/app/m.py", "import types\n\nCFG = types.SimpleNamespace()\nCFG.level = 1\n")
        changed = self.edit("src/app/m.py", "CFG.level = 1", "CFG.level = 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "unattributed", "src/app/m.py"))

    def test_comment_only_and_import_changes_are_attributed(self):
        self.write("src/app/m.py", "import os\n\n# a note\n\n\ndef run():\n    return 1\n")
        changed = self.edit("src/app/m.py", "# a note", "# a better note")
        self.assertEqual(self.verdict(changed)[:2], (False, "nothing_changed"))
        ct.reset()
        changed = self.edit("src/app/m.py", "import os\n", "import os\nimport sys\n")
        self.assertFalse(self.verdict(changed).fire)


class ConfigReferenceTest(_Workspace):
    def test_a_renamed_entry_point_named_in_pyproject_fires(self):
        self.write("src/app/m.py", "def main_cli():\n    return 0\n")
        self.write("pyproject.toml", "[project.scripts]\nx = 'app.m:main_cli'\n")
        changed = self.edit("src/app/m.py", "def main_cli():", "def run_cli():")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "renamed", "main_cli in pyproject.toml"))

    def test_prose_and_non_rename_signals_do_not_read_config(self):
        self.write("src/app/m.py", "def main_cli():\n    return 0\n")
        self.write("README.md", "Run `main_cli` to start.\n")
        changed = self.edit("src/app/m.py", "def main_cli():", "def run_cli():")
        self.assertFalse(self.verdict(changed).fire)
        ct.reset()
        self.write("src/app/n.py", "def tool(a):\n    return a\n")
        self.write("setup.cfg", "[tool]\nentry = tool\n")
        changed = self.edit("src/app/n.py", "def tool(a):", "def tool(a, b):")
        self.assertFalse(self.verdict(changed).fire)


class ScanBoundsTest(_Workspace):
    def test_every_entry_counts_toward_the_budget(self):
        self.write("src/app/units.py", TO_CENTS)
        for index in range(20):
            self.write(f"assets/f{index}.png", "x")
        changed = self.edit("src/app/units.py", "100", "1000")
        with mock.patch.object(ct, "MAX_SCAN_ENTRIES", 15):
            self.assertEqual(self.verdict(changed), ct.Verdict(True, "scan_budget", "index"))

    @requires_symlinks
    def test_a_python_symlink_out_of_the_workspace_fires_unread(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "receipt.py").write_text(RECEIPT, encoding="utf-8", newline="\n")
        self.write("src/app/invoice.py", INVOICE)
        os.symlink(Path(outside.name, "receipt.py"), self.root / "src/app/receipt.py")
        changed = self.edit("src/app/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n")
        with mock.patch.object(ct, "_read", wraps=ct._read) as reads:
            verdict = self.verdict(changed)
        self.assertEqual(verdict, ct.Verdict(True, "outside_link", "src/app/receipt.py"))
        self.assertNotIn(os.path.realpath(Path(outside.name, "receipt.py")), [call.args[0] for call in reads.call_args_list])

    @requires_symlinks
    def test_a_symlinked_directory_out_of_the_workspace_fires(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.write("src/app/units.py", TO_CENTS)
        os.symlink(outside.name, self.root / "src/vendor")
        changed = self.edit("src/app/units.py", "100", "1000")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "outside_link", "src/vendor"))

    def test_build_and_dist_copies_are_not_copies(self):
        self.write("src/app/invoice.py", INVOICE)
        self.write("build/lib/app/receipt.py", RECEIPT)
        self.write("dist/app/receipt.py", RECEIPT)
        changed = self.edit("src/app/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n")
        self.assertEqual(self.verdict(changed)[:2], (False, "no_copy_or_reference"))
        ct.reset()
        self.write("src/app/nested/build/lib/receipt.py", RECEIPT)  # nested build output, no __init__.py
        changed = self.edit("src/app/invoice.py", "ROUND_HALF_UP)\n\n\n", "ROUND_HALF_DOWN)\n\n\n")
        self.assertFalse(self.verdict(changed).fire)

    def test_a_package_named_build_or_dist_is_scanned(self):
        for package in ("build", "dist"):
            with self.subTest(package):
                ct.reset()
                top, name = f"app_{package}", f"make_{package}"
                self.write(f"{top}/m.py", f"def {name}(a):\n    return a\n")
                self.write(f"{top}/{package}/__init__.py", "")
                self.write(f"{top}/{package}/steps.py", f"from {top}.m import {name}\n{name}(1)\n")
                changed = self.edit(f"{top}/m.py", f"def {name}(a):", f"def renamed_{package}(a):")
                self.assertEqual(self.verdict(changed),
                                 ct.Verdict(True, "renamed", f"{name} in {top}/{package}/steps.py"))

    def test_a_sed_inside_a_build_package_is_seen(self):
        self.write("app/m.py", "def other():\n    return 1\n")
        self.write("app/build/__init__.py", "")
        self.write("app/build/steps.py", "def old_step():\n    return 1\n")
        ct.snapshot_before_edit({"tool_name": "terminal", "session_id": SESSION, "turn_id": self.turn}, {"command": "sed"})
        self.write("app/build/steps.py", "def newer_step():\n    return 1\n")
        changed = self.edit("app/m.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "app/build/steps.py"))

    def test_a_namespace_build_or_dist_subpackage_is_scanned(self):
        # #2435 review: a `build`/`dist` with no `__init__.py` was pruned at any depth, so a caller in a
        # namespace subpackage of that name was never seen.
        for package in ("build", "dist"):
            with self.subTest(package):
                ct.reset()
                top, name = f"ns_{package}", f"make_{package}"
                self.write(f"{top}/m.py", f"def {name}(a):\n    return a\n")
                self.write(f"{top}/{package}/steps.py", f"from {top}.m import {name}\n{name}(1)\n")
                changed = self.edit(f"{top}/m.py", f"def {name}(a):", f"def renamed_{package}(a):")
                self.assertEqual(self.verdict(changed),
                                 ct.Verdict(True, "renamed", f"{name} in {top}/{package}/steps.py"))

    def test_a_root_build_scripts_directory_is_scanned(self):
        self.write("app/m.py", "def make_wheel(a):\n    return a\n")
        self.write("build/gen_docs.py", "from app.m import make_wheel\nmake_wheel(1)\n")
        changed = self.edit("app/m.py", "def make_wheel(a):", "def build_wheel(a):")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "renamed", "make_wheel in build/gen_docs.py"))

    def test_a_sed_inside_a_namespace_build_directory_is_seen(self):
        self.write("app/m.py", "def other():\n    return 1\n")
        self.write("app/build/steps.py", "def old_step():\n    return 1\n")
        self.write("app/use.py", "from app.build.steps import old_step\n")
        ct.snapshot_before_edit({"tool_name": "terminal", "session_id": SESSION, "turn_id": self.turn}, {"command": "sed"})
        self.write("app/build/steps.py", "def new_step():\n    return 1\n")
        changed = self.edit("app/m.py", "return 1", "return 2")
        self.assertEqual(self.verdict(changed), ct.Verdict(True, "opaque_edit", "app/build/steps.py"))

    def test_each_build_tool_work_directory_marks_build_output(self):
        for work in ("lib", "lib.macosx-15.0-arm64-cpython-311", "bdist.macosx-15.0-arm64",
                     "temp.macosx-15.0-arm64-cpython-311", "__editable__.oh_my_hermes-4.0.2"):
            with self.subTest(work):
                ct.reset()
                top = "app"
                shutil.rmtree(self.root / top, ignore_errors=True)
                self.write(f"{top}/invoice.py", INVOICE)
                self.write(f"{top}/build/{work}/receipt.py", RECEIPT)
                self.write(f"{top}/build/gen_docs.py", RECEIPT)  # a stray script beside it is still output
                changed = self.edit(f"{top}/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n")
                self.assertEqual(self.verdict(changed)[:2], (False, "no_copy_or_reference"))

    def test_a_build_tree_with_no_python_in_its_first_two_levels_is_not_walked(self):
        # #2454 review: a CMake or JS `build/` was walked once the `__init__.py` rule went, and its
        # entries could run the index out of budget, a fire origin/main never paid.
        self.write("src/app/units.py", TO_CENTS)
        self.write("build/CMakeCache.txt", "x")
        for index in range(20):
            self.write(f"build/CMakeFiles/obj{index}.o", "x")
        self.write("build/src/generated/receipt.py", RECEIPT)  # three levels down: still output
        changed = self.edit("src/app/units.py", "100", "1000")
        with mock.patch.object(ct, "MAX_SCAN_ENTRIES", 15):
            self.assertEqual(self.verdict(changed)[:2], (False, "no_copy_or_reference"))

    def test_an_oversized_unedited_python_file_fires_and_an_oversized_config_does_not(self):
        self.write("src/app/units.py", TO_CENTS)
        self.write("src/app/big.py", "#" * 256)
        # Older than the racy window, so the scan rules on it: a racy oversized file is refused before
        # the scan (`test_an_oversized_racy_file_is_not_read_and_fires`).
        long_ago = time.time_ns() - 2 * ct.RACY_WINDOW_NS
        os.utime(self.root / "src/app/big.py", ns=(long_ago, long_ago))
        self.write("package-lock.json", "x" * 256)
        self.write("src/app/use.py", CART)
        changed = self.edit("src/app/units.py", "def to_cents(", "def amount_to_cents(")
        with mock.patch.object(ct, "MAX_FILE_BYTES", 200):
            self.assertEqual(self.verdict(changed), ct.Verdict(True, "unreadable", "src/app/big.py"))
        os.remove(self.root / "src/app/big.py")
        os.remove(self.root / "src/app/use.py")
        ct.reset()
        self.write("src/app/units.py", TO_CENTS)
        changed = self.edit("src/app/units.py", "def to_cents(", "def amount_to_cents(")
        with mock.patch.object(ct, "MAX_FILE_BYTES", 200):
            self.assertEqual(self.verdict(changed)[:2], (False, "no_copy_or_reference"))


class PreVerifyGateTest(_Workspace):
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

    def fire(self, *paths: str):
        return verify_hooks.pre_verify(session_id=SESSION, coding=True, attempt=0, final_response='{"changed_paths": []}',
                                       changed_paths=list(paths), omh_home=str(self.home), hermes_home=str(self.hermes))

    def test_alone_and_with_nothing_to_find_the_turn_ends(self):
        self.write("src/app/units.py", UNITS)
        self.assertIsNone(self.fire(self.edit("src/app/units.py", '{"s": 60,', '{"s": 1,')))
        self.assertNotIn(SESSION, ct._sessions)

    def test_alone_with_a_copy_the_check_fires_unchanged(self):
        self.write("src/app/invoice.py", INVOICE)
        self.write("src/app/receipt.py", RECEIPT)
        result = self.fire(self.edit("src/app/invoice.py", "ROUND_HALF_EVEN)\n\n\n", "ROUND_HALF_UP)\n\n\n"))
        self.assertEqual(result["message"], f"{verify_hooks.ROUND_END_CHECKLIST}\n{verify_hooks.ROUND_END_CLOSING}")

    def test_beside_another_nudge_the_check_rides_along_without_a_verdict(self):
        self.write("src/app/units.py", UNITS)
        changed = self.edit("src/app/units.py", '{"s": 60,', '{"s": 1,')
        with mock.patch.object(verify_hooks, "round_end_trigger") as trigger:
            result = self.fire(changed, "pyproject.toml")
        trigger.assert_not_called()
        self.assertIn(verify_hooks.ROUND_END_CHECKLIST_BESIDE_A_RECHECK, result["message"])
        self.assertNotIn(SESSION, ct._sessions)

    def test_a_later_attempt_asks_nothing(self):
        self.write("src/app/units.py", UNITS)
        changed = self.edit("src/app/units.py", '{"s": 60,', '{"s": 1,')
        with mock.patch.object(verify_hooks, "round_end_trigger") as trigger:
            verify_hooks.pre_verify(session_id=SESSION, coding=True, attempt=1, changed_paths=[changed],
                                    omh_home=str(self.home), hermes_home=str(self.hermes))
        trigger.assert_not_called()

    def test_pre_tool_call_snapshots_before_any_gate(self):
        from omh.plugin_bundle.omh.hooks import tool_hooks

        self.write("src/app/units.py", UNITS)
        with mock.patch.object(tool_hooks.runtime_paths, "plugin_home", side_effect=RuntimeError("no home")):
            tool_hooks.pre_tool_call(tool_name="patch", args={"path": "src/app/units.py", "old_string": "a", "new_string": "b"},
                                     session_id=SESSION, turn_id="t1")
        self.assertEqual(list(ct._sessions[SESSION]["before"].values()), [UNITS])


if __name__ == "__main__":
    unittest.main()
