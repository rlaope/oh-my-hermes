"""The todo record drops whole terminal escape sequences, not just their ESC byte.

A plan item is written by the model through `omh_todo` and drawn by every
renderer: the OMH TUI plan panel, the Hermes status widget and the Desktop
pane. Dropping only the ESC left `[31m` in the record as text, so each of them
showed it. The bundle cannot import `omh.tui.escapes`, so it carries its own
stripper; the parity case below holds the two to one grammar.
"""

from __future__ import annotations

import inspect
import json
import random
import tempfile
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.runtime_reader import read_omh_hud  # noqa: E402
from omh.plugin_bundle.omh.todo_store import (  # noqa: E402
    _CONTROL_CHARACTERS,
    PLAN_STAGE_ACCEPTED,
    build_todo_record,
    strip_control_characters,
    validate_todo_items,
    write_todo,
)
from omh.plugin_bundle.omh.todo_templates import TODO_TEMPLATES  # noqa: E402
from omh.tui.escapes import strip_escapes  # noqa: E402


def _stored_text(text: str) -> str:
    return validate_todo_items([{"text": text}])[0]["text"]


class WholeSequenceTest(unittest.TestCase):
    def test_a_colour_sequence_leaves_no_parameters_behind(self) -> None:
        self.assertEqual(_stored_text("\x1b[31mred\x1b[0m"), "red")

    def test_an_osc_8_hyperlink_keeps_only_its_label(self) -> None:
        self.assertEqual(_stored_text("see \x1b]8;;https://example.com\x1b\\the docs\x1b]8;;\x1b\\"), "see the docs")
        self.assertEqual(_stored_text("see \x1b]8;;https://example.com\x07the docs\x1b]8;;\x07"), "see the docs")

    def test_a_lone_esc_goes_and_the_text_around_it_stays(self) -> None:
        self.assertEqual(_stored_text("done\x1b"), "done")
        self.assertEqual(_stored_text("a\x1b[\x1b"), "a")

    def test_a_c1_csi_is_a_csi_too(self) -> None:
        self.assertEqual(_stored_text("\x9b31mred\x9b0m"), "red")

    def test_every_text_field_gets_the_same_treatment(self) -> None:
        # Every argument of `build_todo_record` but the item and drop lists is text, so a new one fails the
        # first assertion until it is wrapped here too. `template` needs a record of its own: with a template
        # and no items, the items come from the template.
        wrapped = {
            "title": ("Foundation", "\x1b[1mFoundation\x1b[0m"),
            "source": ("cli", "\x1b]0;title\x07cli"),
            "session_ref": ("20261014_114709_5eba2a", "\x1b[1m20261014_114709_5eba2a\x1b[0m"),
            "deferred_reason": ("waiting on review", "\x1b[33mwaiting on review\x1b[0m"),
            "plan_stage": (PLAN_STAGE_ACCEPTED, f"\x1b[2m{PLAN_STAGE_ACCEPTED}\x1b[0m"),
        }
        template = sorted(TODO_TEMPLATES)[0]
        self.assertEqual(
            set(inspect.signature(build_todo_record).parameters) - {"items", "dropped"}, {*wrapped, "template"}
        )
        # The item's own text fields are keys `validate_todo_items` reads; there is no list to derive them from.
        item = {"text": "\x1b[31mx\x1b[0m", "phase": "\x1b[2mphase\x1b[0m", "blocked_reason": "\x1b[33mwaiting\x1b[0m"}
        record = build_todo_record(
            wrapped["title"][1], [item], **{name: raw for name, (_clean, raw) in wrapped.items() if name != "title"}
        )
        for name, (clean, _raw) in wrapped.items():
            with self.subTest(field=name):
                self.assertEqual(record[name], clean)
        self.assertEqual(
            {key: record["items"][0][key] for key in item}, {"text": "x", "phase": "phase", "blocked_reason": "waiting"}
        )
        templated = build_todo_record("t", [], source="cli", template=f"\x1b[1m{template}\x1b[0m")
        self.assertEqual(templated["template"], template)


class OrdinaryBracketsTest(unittest.TestCase):
    """Without an escape introducer there is no sequence, so nothing is removed."""

    def test_checkbox_index_and_typed_parameters_stay(self) -> None:
        for text in ("[x] done", "a[0]", "[31m", "see ]8;; and \\ too", "[?25l is a cursor code"):
            with self.subTest(text=text):
                self.assertEqual(_stored_text(text), text)


class ParityWithTheTuiStripperTest(unittest.TestCase):
    def test_the_bundle_and_the_tui_read_one_grammar(self) -> None:
        # Seeded, so a failure names the same input on every run.
        alphabet = [
            "\x1b", "\x07", "\x9b", "\x9c", "\x90", "\x98", "\x9d", "\x9e", "\x9f",
            "[", "]", "\\", "P", "X", "^", "_", "(", " ", "!", "/", "0", "1", "3", ";", "?",
            "m", "a", "~", "@", "\x7f", "\n", "é",
        ]
        rng = random.Random(2095)
        for _ in range(20000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
            expected = strip_escapes(text).translate(_CONTROL_CHARACTERS).strip()
            self.assertEqual(strip_control_characters(text), expected, repr(text))


class RecordAtRestTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.omh_home = Path(tmp.name) / "omh"
        self.hermes_home = Path(tmp.name) / "hermes"
        self.omh_home.mkdir()
        self.hermes_home.mkdir()

    def test_the_hud_projection_carries_the_text_without_the_sequence(self) -> None:
        write_todo(
            self.omh_home,
            build_todo_record("plan", [{"text": "\x1b[31mred\x1b[0m item", "state": "active"}], source="test"),
        )
        payload = read_omh_hud(self.omh_home, self.hermes_home)

        self.assertEqual(payload["todo"]["items"][0]["text"], "red item")
        self.assertFalse(any("[31m" in line for line in payload["display"]["todo_lines"]))

    def test_a_record_written_before_reads_back_as_the_text_it_holds(self) -> None:
        # An earlier write dropped only the ESC; what is left cannot be told
        # apart from typed brackets, so it is shown as text rather than guessed at.
        record = build_todo_record("plan", [{"text": "x", "state": "active"}], source="test")
        record["items"][0]["text"] = "[31mred[0m item"
        runtime = self.omh_home / "runtime"
        runtime.mkdir()
        (runtime / "todo.json").write_text(json.dumps(record), encoding="utf-8")

        payload = read_omh_hud(self.omh_home, self.hermes_home)

        self.assertEqual(payload["todo"]["items"][0]["text"], "[31mred[0m item")


if __name__ == "__main__":
    unittest.main()
