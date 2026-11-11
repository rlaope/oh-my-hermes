"""Semantic dot-repeat acceptance checks; no synthetic App event replay.

The real-terminal journey in the acceptance plan is a separate manual check;
``test_real_app_routes_and_pty`` covers its automated App-routing component.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from test_tui_vim_mode import ESC, FAMILY, CHIP_TEXT, keys, normal, state, vim_app
from test_tui_modes import type_text
from test_tui_shortcuts import documented_keys
from omh.tui.composer import Composer, VIM_NORMAL
from omh.tui.keys import BACKSPACE, CHAR, END, ENTER, HOME, LEFT, RIGHT, Key, Paste
from omh.tui.shortcuts import SHORTCUTS


def visible(c: Composer) -> tuple:
    return c.text, c.caret, dict(c.pastes), dict(c.images)


def finish(c: Composer, command: str) -> None:
    keys(c, command)
    c.handle(ESC)


class DotRepeatTests(unittest.TestCase):
    def test_insert_and_change_replay(self) -> None:
        c = normal("abc", 0)
        finish(c, "iZ")
        self.assertEqual(state(c), ("Zabc", 0, VIM_NORMAL))
        keys(c, "l.")
        self.assertEqual(state(c), ("ZZabc", 1, VIM_NORMAL))
        keys(c, "u")
        self.assertEqual(state(c), ("Zabc", 1, VIM_NORMAL))
        keys(c, "u")
        self.assertEqual(state(c), ("abc", 0, VIM_NORMAL))
        c = normal("one two", 0)
        finish(c, "cwZ")
        keys(c, "w.")
        self.assertEqual(state(c), ("Z Z", 2, VIM_NORMAL))
        keys(c, "u")
        self.assertEqual(c.text, "Z two")
        keys(c, "u")
        self.assertEqual(c.text, "one two")

    def test_count_override_inventory(self) -> None:
        c = normal("abcdefg", 0)
        for command, expected in (("2x", "cdefg"), ("3.", "fg"), (".", "")):
            keys(c, command)
            self.assertEqual(c.text, expected)
        for command, expected in (("i", "ZZabc"), ("a", "aZZbc"),
                                  ("I", "ZZabc"), ("A", "abcZZ"),
                                  ("o", "abc\nZ\nZ"), ("O", "Z\nZ\nabc")):
            with self.subTest(command=command):
                c = normal("abc", 0)
                finish(c, "2" + command + "Z")
                self.assertEqual(c.text, expected)
        for command, expected in (("2s", "Zc"), ("2cw", "Z"), ("9C", "Z")):
            with self.subTest(command=command):
                c = normal("abc", 0)
                finish(c, command + "Z")
                self.assertEqual(c.text, expected)
        c = normal("one two three four five six seven eight nine ten", 0)
        keys(c, "2d3w")
        self.assertEqual(c.text, "seven eight nine ten")
        keys(c, "2.")
        self.assertEqual(c.text, "nine ten")
        keys(c, ".")
        self.assertEqual(c.text, "")
        c = normal("abc", 0)
        keys(c, "x99999.")
        self.assertEqual(c.text, "")

    def test_operator_descriptors_resolve_at_current_position(self) -> None:
        # Original and replay operate on distinct but equivalent logical lines.
        cases = [("dh", "abcd", 2), ("dl", "abcd", 1), ("d0", "abcd", 2),
                 ("d^", "  abcd", 4), ("d$", "abcd", 1),
                 ("dw", "one two", 0), ("db", "one two", 4), ("de", "one two", 0),
                 ("diw", "one two", 1), ("daw", "one two", 1),
                 ('di"', 'a "bc" d', 3), ("da'", "a 'bc' d", 3),
                 ("di`", "a `bc` d", 3), ("di(", "a (bc) d", 3),
                 ("da]", "a [bc] d", 3), ("di}", "a {bc} d", 3),
                 ("dfc", "abcd", 0), ("dtc", "abcd", 0),
                 ("dFa", "abcd", 3), ("dTa", "abcd", 3),
                 ("x", "abcd", 1), ("X", "abcd", 2),
                 ("rZ", "abcd", 1), ("D", "abcd", 1)]
        for command, line, offset in cases:
            with self.subTest(command=command):
                c = normal(line + "\n" + line, offset)
                keys(c, command)
                first, second = c.text.split("\n")
                self.assertNotEqual(first, line)
                self.assertEqual(second, line)
                c.caret = len(first) + 1 + offset
                keys(c, ".")
                self.assertEqual(c.text, first + "\n" + first)
                self.assertTrue(c.normal)

    def test_insert_recipe_one_undo(self) -> None:
        c = normal("abc", 0)
        before = visible(c)
        keys(c, "iXY")
        c.handle(Key(LEFT))
        c.handle(Key(BACKSPACE))
        finish(c, "Z")
        after = visible(c)
        self.assertEqual(state(c), ("ZYabc", 0, VIM_NORMAL))
        keys(c, "u")
        self.assertEqual(visible(c), before)
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(visible(c), after)
        keys(c, ".")
        self.assertEqual(c.text, "ZYZYabc")
        keys(c, "u")
        self.assertEqual(visible(c), after)
        for trailing, caret in ((None, 0), (RIGHT, 1), (LEFT, 0), (HOME, 0), (END, 3)):
            with self.subTest(trailing=trailing):
                c = normal("abc", 0)
                keys(c, "iZ")
                if trailing:
                    c.handle(Key(trailing))
                c.handle(ESC)
                self.assertEqual(state(c), ("Zabc", caret, VIM_NORMAL))
        for trailing, expected, caret in ((RIGHT, "ZaZbc", 3), (LEFT, "ZZabc", 0)):
            c = normal("abc", 0)
            keys(c, "2iZ")
            c.handle(Key(trailing))
            c.handle(ESC)
            self.assertEqual(state(c), (expected, caret, VIM_NORMAL))
        c = normal("abc", 0)
        keys(c, "iX")
        c.handle(Key(ENTER, shift=True))
        finish(c, "Y")
        keys(c, "u")
        self.assertEqual(state(c), ("abc", 0, VIM_NORMAL))
        c = normal("abc", 0)
        finish(c, "o")
        self.assertEqual(c.text, "abc\n")
        keys(c, "u")
        self.assertEqual(c.text, "abc")

    def test_failed_cancelled_noop_preserves_state(self) -> None:
        for command in ("df~", "di!", "3rZ", "?", "d", "i", "rb", "iQ\b"):
            with self.subTest(command=command):
                c = normal("abc", 0)
                keys(c, "x")
                before = visible(c)
                if command == "iQ\b":
                    keys(c, "iQ")
                    c.handle(Key(BACKSPACE))
                else:
                    keys(c, command)
                c.handle(ESC)
                self.assertEqual(visible(c), before)
                keys(c, ".")
                self.assertEqual(c.text, "c")
        c = normal("abc", 0)
        keys(c, "p.")
        self.assertEqual(c.text, "abc")

    def test_put_uses_captured_payload(self) -> None:
        for put in ("p", "P"):
            for count in ("", "2"):
                with self.subTest(put=put, count=count):
                    c = normal("A B", 0)
                    keys(c, "yl" + count + put)
                    c.caret = c.text.index("B")
                    keys(c, "yl")
                    before = c.text
                    keys(c, ".")
                    self.assertEqual(c.text.count("A"), before.count("A") + (2 if count else 1))
                    keys(c, "u")
                    self.assertEqual(c.text, before)
                    keys(c, "p")
                    self.assertEqual(c.text.count("B"), 2)
            c = normal("A\nB", 0)
            keys(c, "yy" + put)
            c.caret = c.text.index("B")
            keys(c, "yy.")
            self.assertEqual(c.text.count("A"), 3)
            self.assertEqual(c.text.count("B"), 1)

    def test_graphemes_chips_images(self) -> None:
        c = normal("e\u0301" + FAMILY + "界", 0)
        keys(c, "x.")
        self.assertEqual(c.text, "界")
        keys(c, "u")
        self.assertEqual(c.text, FAMILY + "界")
        c = Composer(vim=True)
        c.handle(Paste(CHIP_TEXT))
        c.handle(ESC)
        keys(c, "0ylp.")
        self.assertEqual(c.expanded(), CHIP_TEXT * 3)
        self.assertTrue(c.pastes)
        image = object()
        c = Composer(vim=True)
        c.insert_image("[Image #1]", image)
        c.handle(ESC)
        keys(c, "0ylp.")
        self.assertEqual(len(c.images), 3)
        self.assertTrue(all(payload[1] is image for payload in c.images.values()))
        after = visible(c)
        keys(c, "u")
        self.assertEqual(len(c.images), 2)
        c.handle(Key(CHAR, "r", ctrl=True))
        self.assertEqual(visible(c), after)

    def test_reset_external_and_budget(self) -> None:
        for reset in (lambda c: c.replace(0, len(c.text), "abc"),
                      lambda c: c.restore("Q", []),
                      lambda c: c.set_vim(False), lambda c: c.set_vim(True)):
            with self.subTest(reset=reset):
                c = normal("abcd", 0)
                keys(c, "x")
                reset(c)
                if not c.vim:
                    c.set_vim(True)
                if not c.normal:
                    c.handle(ESC)
                before = visible(c)
                keys(c, ".")
                self.assertEqual(visible(c), before)
        c = normal("abcd", 0)
        keys(c, "x")
        c.handle(Paste("Q"))
        c.caret = 0
        keys(c, ".")
        self.assertEqual(c.text, "bcd")
        c = normal("abcd", 0)
        keys(c, "xiZ")
        c.handle(Paste("Q"))
        c.handle(ESC)
        keys(c, "u")
        self.assertEqual(c.text, "bcd")
        c.caret = 0
        keys(c, ".")
        self.assertEqual(c.text, "cd")
        # Retained text above 1 MiB must not replace the preceding x descriptor.
        c = normal("abcd", 0)
        keys(c, "xi")
        c.handle(Key(CHAR, "Z" * (1024 * 1024 + 1)))
        c.handle(ESC)
        keys(c, "u0.")
        self.assertEqual(c.text, "cd")

    def test_real_app_routes_and_pty(self) -> None:
        for busy in (False, True):
            with self.subTest(busy=busy):
                app, client, _clock = vim_app(busy=busy)
                type_text(app, "abc")
                app._on_input(ESC)
                type_text(app, "0iZ")
                app._on_input(ESC)
                type_text(app, "l.")
                self.assertEqual(app.composer.text, "ZZabc")
                self.assertEqual(client.calls, [])
                type_text(app, "u")
                self.assertEqual(app.composer.text, "Zabc")
                for pending in ("d", "r", "f", " "):
                    type_text(app, pending)
                    app._on_input(ESC)
                    self.assertFalse(app.composer.pending)
                self.assertEqual(client.calls, [])
        app, client, _clock = vim_app()
        type_text(app, ".")
        self.assertEqual(app.composer.text, ".")
        self.assertEqual(client.calls, [])

    def test_aggregate_budget_failure_is_atomic(self) -> None:
        # A retained 257-byte recipe is legal, but 9999 copies exceed 2 MiB.
        c = normal("abc", 0)
        finish(c, "i" + "Z" * 257)
        before = visible(c)
        keys(c, "9999.")
        self.assertEqual(visible(c), before)
        self.assertTrue(c.normal)
        self.assertFalse(c.pending)
        # Rejection does not overwrite the legal descriptor or consume undo.
        keys(c, ".")
        self.assertEqual(c.text.count("Z"), 514)
        keys(c, "u")
        self.assertEqual(visible(c), before)
        keys(c, "u")
        self.assertEqual(c.text, "abc")

    def test_history_and_submit_reset_repeat(self) -> None:
        c = normal("abc", 0)
        keys(c, "x")
        c.handle(Key(ENTER))
        self.assertEqual(c.text, "")
        if not c.normal:
            c.handle(ESC)
        keys(c, ".")
        self.assertEqual(c.text, "")
        # Public replacement starts a fresh draft, including after undo.
        c.restore("xyz", [])
        if not c.normal:
            c.handle(ESC)
        before = visible(c)
        keys(c, ".")
        self.assertEqual(visible(c), before)

    def test_help_dot_parity(self) -> None:
        self.assertEqual(documented_keys(), list(SHORTCUTS))
        modal = dict(SHORTCUTS)["Esc (vim mode)"]
        for phrase in ("[n].", "captured", "Escape", "oversized", "visual"):
            self.assertIn(phrase, modal)
        docs = (Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8")
        self.assertIn("[n].", docs)


class DotRepeatRuntimeLimitsTests(unittest.TestCase):
    """Runtime boundaries, not just the standalone admission API."""

    def test_bell_is_delivered_once_and_muted_failures_are_consumed(self) -> None:
        from omh.tui.app import BELL
        from omh.tui.composer import _RepeatChange
        for muted in (False, True):
            with self.subTest(muted=muted):
                app, client, _clock = vim_app(environ={"OMH_TUI_BELL": "0" if muted else "1"})
                type_text(app, "abc")
                app._on_input(ESC)
                c = app.composer
                c._repeat_change = _RepeatChange("i", 1, ((0, 0, "Z"),), 999)
                before = visible(c), c._register, list(c._undo), list(c._redo), c._token_count
                app.terminal.writes.clear()
                type_text(app, "2.")
                self.assertEqual((visible(c), c._register, c._undo, c._redo, c._token_count), before)
                self.assertEqual(app.terminal.writes, [] if muted else [BELL])
                self.assertFalse(c.take_bell())
                app.environ["OMH_TUI_BELL"] = "1"
                type_text(app, "h")
                self.assertEqual(app.terminal.writes, [] if muted else [BELL])
                self.assertEqual(client.calls, [])
                self.assertTrue(c.normal)
                self.assertEqual((c._count, c._operator, c._prefix), ("", "", ""))

    def test_masked_transitions_invalidate_without_an_input_event(self) -> None:
        c = normal("abc", 0)
        keys(c, "x")
        self.assertIsNotNone(c._repeat_change)
        c.masked = True
        self.assertIsNone(c._repeat_change)
        c.masked = False
        before = visible(c)
        keys(c, ".")
        self.assertEqual(visible(c), before)
        keys(c, "iZ")
        self.assertIsNotNone(c._insert_change)
        c.masked = True
        self.assertIsNone(c._insert_change)
        c.masked = False
        c.handle(ESC)
        self.assertIsNone(c._repeat_change)

    def test_retained_record_byte_and_image_limits_are_inclusive(self) -> None:
        from omh.tui.composer import _Register, _RepeatChange, _TOKEN_FIRST
        cases = (
            (_RepeatChange("i", 1, ((0, 0, ""),) * 9999),
             _RepeatChange("i", 1, ((0, 0, ""),) * 10000)),
            (_RepeatChange("i", 1, ((0, 0, "Z" * (1024 * 1024)),)),
             _RepeatChange("i", 1, ((0, 0, "Z" * (1024 * 1024 + 1)),))),
        )
        token = chr(_TOKEN_FIRST)
        image = object()
        cases += ((_RepeatChange("p", 1, register=_Register(token * 256, {}, {token: ("image", image)}, False)),
                   _RepeatChange("p", 1, register=_Register(token * 257, {}, {token: ("image", image)}, False))),)
        for allowed, rejected in cases:
            with self.subTest(command=allowed.command, records=len(allowed.recipe)):
                c = normal("abc", 0)
                c._retain_repeat(allowed)
                self.assertIs(c._repeat_change, allowed)
                self.assertFalse(c.take_bell())
                c._retain_repeat(rejected)
                self.assertIs(c._repeat_change, allowed)
                self.assertTrue(c.take_bell())
                self.assertFalse(c.take_bell())

    def test_rejected_capture_releases_private_image_references(self) -> None:
        import gc
        import weakref
        from omh.tui.composer import _Register, _RepeatChange, _TOKEN_FIRST
        class Image:
            pass
        c = normal("abc", 0)
        keys(c, "x")
        saved = c._repeat_change
        image = Image()
        ref = weakref.ref(image)
        token = chr(_TOKEN_FIRST)
        candidate = _RepeatChange("p", 1, register=_Register(token * 257, {}, {token: ("image", image)}, False))
        c._retain_repeat(candidate)
        del candidate, image
        gc.collect()
        self.assertIsNone(ref())
        self.assertIs(c._repeat_change, saved)

    def test_runtime_rejection_precedes_snapshot_and_token_allocation(self) -> None:
        from unittest.mock import patch
        from omh.tui.composer import _RepeatChange
        c = normal("abc", 0)
        c._repeat_change = _RepeatChange("i", 1, ((0, 0, "Z" * 257),), 257)
        before = dict(c.__dict__)
        keys(c, "9999")
        with patch.object(Composer, "_state", side_effect=AssertionError("snapshot before admission")), \
             patch.object(Composer, "_new_token", side_effect=AssertionError("token before admission")), \
             patch.object(Composer, "_set", side_effect=AssertionError("mutation before admission")):
            keys(c, ".")
        expected = {**before, "_bell": True}
        self.assertEqual(c.__dict__, expected)


class DotRepeatPreflightTests(unittest.TestCase):
    """T03/T04/T06/T07: admission must finish before live allocation/editing.

    Limits deliberately isolate one resource; rejection asserts its reason, not
    just ValueError. The fail-fast patches are negative controls for the explicit
    no-snapshot/no-token/no-mutation admission contract, not execution fakes.
    """

    @staticmethod
    def _insert(payload: str = "Z", *, terminal: int = 1):
        from omh.tui.composer import _RepeatChange
        return _RepeatChange("i", 1, ((0, 0, payload),), terminal)

    @staticmethod
    def _image_put(command: str = "p", *, linewise: bool = False):
        from omh.tui.composer import _Register, _RepeatChange, _TOKEN_FIRST
        token = chr(_TOKEN_FIRST)
        register = _Register(token, {}, {token: ("[Image #1]", object())}, linewise)
        return _RepeatChange(command, 1, register=register)

    def _preflight(self, c, change, count=1, *, error=None,
                   message=None, before_source=False, **kwargs):
        from contextlib import ExitStack
        from unittest import mock
        from omh.tui import vim_repeat

        # Preserve every live field, including undo/redo, saved descriptor,
        # allocation cursor, caches, mode and grammar, not just visible text.
        before = {name: value.copy() if isinstance(value, (dict, list, set)) else value
                  for name, value in vars(c).items()}
        containers = {name: value for name, value in vars(c).items()
                      if isinstance(value, (dict, list, set))}
        with ExitStack() as stack:
            for method in ("_new_token", "_state", "_set"):
                stack.enter_context(mock.patch.object(
                    Composer, method, side_effect=AssertionError(
                        f"preflight called Composer.{method}")))
            if before_source:
                stack.enter_context(mock.patch.object(
                    vim_repeat, "_source", side_effect=AssertionError(
                        "arithmetic rejection scanned source")))
            if error is None:
                result = vim_repeat.preflight(c, change, count, **kwargs)
            else:
                with self.assertRaisesRegex(error, message or ".") as caught:
                    vim_repeat.preflight(c, change, count, **kwargs)
                result = caught.exception
        self.assertEqual(vars(c), before)
        for name, value in containers.items():
            self.assertIs(getattr(c, name), value, name)
        return result

    def _limit_failure(self, c, change, count, limits, resource, attempted,
                       *, before_source=False):
        from omh.tui.vim_repeat import LimitExceeded
        visits = []
        failure = self._preflight(
            c, change, count, limits=limits, on_visit=visits.append,
            error=LimitExceeded, message=resource, before_source=before_source)
        self.assertEqual((failure.resource, failure.limit, failure.attempted),
                         (resource, getattr(limits, resource), attempted))
        if before_source:
            self.assertEqual(visits, [])
        return visits

    def test_preflight_step_limit_is_inclusive_and_counts_opened_lines(self):
        from omh.tui.composer import _RepeatChange
        from omh.tui.vim_repeat import Limits
        # o/O each add their own newline in addition to the recipe replacement.
        for command in ("i", "o", "O"):
            with self.subTest(command=command):
                change = _RepeatChange(command, 1, ((0, 0, "Z"),), 1)
                steps = 2 if command == "i" else 4
                c = normal("abc", 0)
                plan = self._preflight(c, change, 2, limits=Limits(steps=steps))
                self.assertEqual(plan.work.steps, steps)
                self.assertEqual(plan.work.materialized_bytes, steps)
                self.assertEqual(plan.work.fresh_images, 0)
                self._limit_failure(c, change, 2, Limits(steps=steps - 1),
                                    "steps", steps, before_source=True)

    def test_preflight_bytes_are_utf8_not_character_count(self):
        from omh.tui.vim_repeat import Limits
        c = normal("abc", 0)
        change = self._insert("界")
        plan = self._preflight(c, change, 2, limits=Limits(materialized_bytes=6))
        self.assertEqual((plan.work.steps, plan.work.materialized_bytes,
                          plan.work.fresh_images), (2, 6, 0))
        self._limit_failure(c, change, 2, Limits(materialized_bytes=5),
                            "materialized_bytes", 6, before_source=True)

    def test_preflight_put_bytes_include_delimiters_and_image_labels(self):
        from omh.tui.composer import _Register, _RepeatChange
        from omh.tui.vim_repeat import Limits
        cases = [(_RepeatChange("p", 1, register=_Register("界", {}, {}, True)), 8),
                 (self._image_put(), 28)]
        for change, byte_count in cases:
            with self.subTest(command=change.command, byte_count=byte_count):
                c = normal("abc", 0)
                plan = self._preflight(c, change, 2, limits=Limits(
                    materialized_bytes=byte_count))
                self.assertEqual(plan.work.materialized_bytes, byte_count)
                self.assertEqual(plan.work.steps, 1)
                self._limit_failure(c, change, 2, Limits(
                    materialized_bytes=byte_count - 1), "materialized_bytes", byte_count)

    def test_preflight_chip_bytes_include_expansion_and_remapped_label(self):
        from omh.tui.composer import _Register, _RepeatChange
        from omh.tui.vim_repeat import Limits
        label = "[Pasted text #1 · 1 chars]"
        for collision, expected in ((False, 60), (True, 62)):
            with self.subTest(collision=collision):
                c = normal("abc", 0)
                if collision:
                    c.pastes[label] = "different payload"
                    c._paste_count = 9  # remapping grows #1 to #10
                register = _Register(label, {label: "界"}, {}, False)
                change = _RepeatChange("P", 1, register=register)
                plan = self._preflight(c, change, 2, limits=Limits(
                    materialized_bytes=expected))
                self.assertEqual(plan.work.materialized_bytes, expected)
                self._limit_failure(c, change, 2, Limits(
                    materialized_bytes=expected - 1), "materialized_bytes", expected)

    def test_preflight_fresh_image_limits_are_independent_and_inclusive(self):
        from omh.tui.vim_repeat import Limits
        for command in ("p", "P"):
            for linewise in (False, True):
                with self.subTest(command=command, linewise=linewise):
                    c = normal("abc", 0)
                    change = self._image_put(command, linewise=linewise)
                    plan = self._preflight(c, change, 2, limits=Limits(fresh_images=2))
                    self.assertEqual(plan.work.fresh_images, 2)
                    self.assertEqual(plan.work.steps, 1)
                    self._limit_failure(c, change, 3, Limits(fresh_images=2),
                                        "fresh_images", 3, before_source=True)

    def test_preflight_real_512_images_admits_513_rejects_without_allocation(self):
        c = normal("abc", 0)
        change = self._image_put()
        plan = self._preflight(c, change, 512)
        self.assertEqual((plan.work.steps, plan.work.materialized_bytes,
                          plan.work.fresh_images), (1, 7168, 512))
        from omh.tui.vim_repeat import Limits
        self._limit_failure(c, change, 513, Limits(), "fresh_images", 513,
                            before_source=True)

    def test_preflight_token_capacity_uses_union_of_text_and_stale_maps(self):
        from omh.tui.composer import _TOKEN_FIRST, _TOKEN_LAST
        from omh.tui.vim_repeat import PreflightError
        c = normal("abc", 0)
        # An unmapped token in text also occupies a slot. A mapped duplicate
        # must count once, and mapped tokens absent from text still occupy slots.
        first = chr(_TOKEN_FIRST)
        c.text = first
        c.images = {chr(code): ("stale", object())
                    for code in range(_TOKEN_FIRST, _TOKEN_LAST - 1)}
        change = self._image_put()
        plan = self._preflight(c, change, 2)
        self.assertEqual(plan.work.fresh_images, 2)
        self._preflight(c, change, 3, error=PreflightError,
                        message="image token pool exhausted")
        del c.images[first]
        plan = self._preflight(c, change, 2)
        self.assertEqual(plan.work.fresh_images, 2)
        self._preflight(c, change, 3, error=PreflightError,
                        message="image token pool exhausted")

    def test_preflight_exhausted_65534_token_pool_rejects_before_allocation(self):
        from omh.tui.composer import _TOKEN_FIRST, _TOKEN_LAST
        from omh.tui.vim_repeat import PreflightError
        c = normal("abc", 0)
        payload = ("stale", object())
        c.images = {chr(code): payload
                    for code in range(_TOKEN_FIRST, _TOKEN_LAST + 1)}
        self.assertEqual(len(c.images), 65534)
        self._preflight(c, self._image_put(), error=PreflightError,
                        message="image token pool exhausted")

    def test_preflight_failed_change_target_never_admits_following_recipe(self):
        from omh.tui.composer import _RepeatChange
        from omh.tui.vim_repeat import PreflightError
        for command, message in (("cf~", "find target unavailable"),
                                 ('ci"', "motion/object unavailable"),
                                 ("ci(", "motion/object unavailable")):
            with self.subTest(command=command):
                c = normal("abc", 0)
                keys(c, "x")  # a live saved repeat and deletion register to protect
                change = _RepeatChange(command, 1, ((0, 0, "Z"),), 1)
                self._preflight(c, change, error=PreflightError, message=message)
        # An empty *valid* change differs from an unavailable target: it enters
        # INSERT and counts its empty leading replacement before the recipe.
        c = normal("", 0)
        change = _RepeatChange("cw", 1, ((0, 0, "Z"),), 1)
        plan = self._preflight(c, change)
        self.assertEqual((plan.work.steps, plan.work.materialized_bytes,
                          plan.final_atoms, plan.final_caret), (2, 1, 1, 0))

    def test_preflight_rejects_recipe_bounds_and_terminal_endpoint_atomically(self):
        from omh.tui.composer import _RepeatChange
        from omh.tui.vim_repeat import PreflightError
        for recipe, terminal, message in (
                (((-1, 1, ""),), 0, "recipe out of bounds"),
                (((0, 4, ""),), 0, "recipe out of bounds"),
                (((0, -1, "Z"),), 0, "recipe out of bounds"),
                (((0, 0, "Z"),), -1, "endpoint out of bounds"),
                (((0, 0, "Z"),), 5, "endpoint out of bounds")):
            with self.subTest(recipe=recipe, terminal=terminal):
                c = normal("abc", 0)
                change = _RepeatChange("i", 1, recipe, terminal)
                self._preflight(c, change, error=PreflightError, message=message)
        # Capture an actual trailing-End descriptor; it cannot transplant its
        # saved terminal endpoint into a shorter current draft.
        source = normal("abcdef", 0)
        keys(source, "iZ")
        source.handle(Key(END))
        source.handle(ESC)
        self.assertEqual(source._repeat_change.terminal, 7)
        self._preflight(normal("a", 0), source._repeat_change,
                        error=PreflightError, message="endpoint out of bounds")

    def test_preflight_exact_atom_visits_stop_before_excess_read(self):
        from omh.tui.vim_repeat import Limits
        # One atom inserted into empty text: emit, payload accounting, payload
        # read, two endpoint reads, INSERT->NORMAL read, NORMAL clamp read = 7.
        # Neither UTF-8 width nor a multi-codepoint grapheme adds atom visits.
        for payload in ("Z", "界", FAMILY):
            with self.subTest(payload=payload):
                c = normal("", 0)
                change = self._insert(payload)
                visits = []
                plan = self._preflight(c, change, limits=Limits(atom_visits=7),
                                       on_visit=visits.append)
                self.assertEqual(plan.work.atom_visits, 7)
                self.assertEqual(visits, [1, 2, 3, 4, 5, 6, 7])
                self.assertEqual((plan.final_atoms, plan.final_caret_atom), (1, 0))
                rejected = self._limit_failure(c, change, 1, Limits(atom_visits=6),
                                               "atom_visits", 7)
                self.assertEqual(rejected, [1, 2, 3, 4, 5, 6])

    def test_preflight_arithmetic_limits_win_before_any_source_scanning(self):
        from omh.tui.composer import _Register, _RepeatChange
        from omh.tui.vim_repeat import Limits
        c = normal("a" * 100, 0)
        cases = [
            (self._insert(), 2, Limits(steps=1, atom_visits=0), "steps", 2),
            (self._insert("界"), 2, Limits(materialized_bytes=5, atom_visits=0),
             "materialized_bytes", 6),
            (_RepeatChange("o", 1), 2, Limits(materialized_bytes=1, atom_visits=0),
             "materialized_bytes", 2),
            (_RepeatChange("r界", 1), 2, Limits(materialized_bytes=5, atom_visits=0),
             "materialized_bytes", 6),
            (_RepeatChange("p", 1, register=_Register("界", {}, {}, True)), 2,
             Limits(materialized_bytes=7, atom_visits=0), "materialized_bytes", 8),
            (self._image_put(), 3, Limits(fresh_images=2, atom_visits=0),
             "fresh_images", 3),
        ]
        for change, count, limits, resource, attempted in cases:
            with self.subTest(command=change.command, resource=resource):
                self._limit_failure(c, change, count, limits, resource, attempted,
                                    before_source=True)

    def test_preflight_plan_and_work_are_immutable(self):
        from dataclasses import FrozenInstanceError
        plan = self._preflight(normal("", 0), self._insert())
        with self.assertRaises(FrozenInstanceError):
            plan.final_caret = 99
        for field in ("steps", "materialized_bytes", "fresh_images", "atom_visits"):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                plan.work.__setattr__(field, 99)


if __name__ == "__main__":
    unittest.main()
