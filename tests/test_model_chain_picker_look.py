"""The chain picker's look: painted through the OMH TUI's `Theme` roles.

`omh model-chains` and `/omh-model` draw the same frame. It has no fill: the
cursor row is the `❯` pointer and its name bold in `menu_current`, the rules
are the launch look's, words are the neutral greys, and the frame follows the
background, the launch look and the colour depth the way the TUI does. These
tests read the SGR the frame carries, never a terminal.
"""

from __future__ import annotations

from dataclasses import replace
import io
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.catalogs.model_chain_table import CHAIN_SURFACE_PURPOSES, MODEL_DISPLAY_LABELS
from omh.coding.model_contracts import contract_effort_option
from omh.commands.model_chain_picker import render_frame
from omh.plugin_bundle.omh.model_chain_picker import chain_from_entries, picker_rows
from omh.skin_pack import default_theme, theme_for_name, write_launch_choice
from omh.tui.style import COLOR_256, NO_COLOR, TRUECOLOR
from omh.tui.theme import DEFAULT_LAUNCH, DEFAULT_THEME, build_theme, with_launch_look

SGR = re.compile(r"\x1b\[[0-9;]*m")
BACKGROUND = re.compile(r"\x1b\[(?:[0-9]+;)*48;")


def _payload(root: Path) -> dict:
    return picker_rows(
        root / ".omh",
        hermes_home=root / ".hermes",
        labels=MODEL_DISPLAY_LABELS,
        purposes=CHAIN_SURFACE_PURPOSES,
        contract_option=contract_effort_option,
    )


def _chains(payload) -> dict:
    return {row.get("key", row["category"]): chain_from_entries(row["chain"]) for row in payload["rows"]}


class FrameLookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory()))
        (self.root / ".hermes").mkdir()
        self.payload = _payload(self.root)
        self.names = [row["category"] for row in self.payload["rows"]]

    def frame(self, theme=DEFAULT_THEME, *, cursor: int = 1, depth: str = TRUECOLOR, use_color: bool = True) -> list[str]:
        return render_frame(
            self.payload, _chains(self.payload), cursor, use_color=use_color, width=160, theme=theme, depth=depth
        )

    def test_the_cursor_row_is_the_pointer_and_its_name_in_menu_current(self) -> None:
        lines = self.frame()
        current = DEFAULT_THEME.menu_current.sgr()
        cursor_row = next(line for line in lines if SGR.sub("", line).startswith(f" ❯ {self.names[1]} "))
        self.assertIn(f"{current} ❯ ", cursor_row)
        self.assertIn(f"{current}{self.names[1]} ", cursor_row)
        other = next(line for line in lines if SGR.sub("", line).startswith(f"   {self.names[2]} "))
        self.assertNotIn(f"{current}{self.names[2]}", other)
        self.assertEqual(sum(SGR.sub("", line).startswith(" ❯ ") for line in lines), 1)

    def test_no_line_carries_a_background(self) -> None:
        for cursor in (0, 1, len(self.names) - 1):
            for line in self.frame(cursor=cursor):
                self.assertIsNone(BACKGROUND.search(line), repr(line))

    def test_rules_key_words_and_the_effort_label_take_their_roles(self) -> None:
        lines = self.frame()
        rule = DEFAULT_THEME.rule.sgr()
        self.assertTrue(DEFAULT_THEME.rule.fg)
        self.assertEqual(sum(line.startswith(f"{rule}──") for line in lines), 3)
        hints = lines[-1]
        self.assertIn(f"{DEFAULT_THEME.hint.sgr()}category", hints)
        self.assertIn(f"{DEFAULT_THEME.user.sgr()}↑↓", hints)
        effort = next(line for line in lines if SGR.sub("", line).startswith("   effort "))
        self.assertIn(f"{DEFAULT_THEME.muted.sgr()}effort ", effort)
        self.assertNotEqual(DEFAULT_THEME.muted.sgr(), DEFAULT_THEME.text.sgr())

    def test_a_light_background_paints_another_frame(self) -> None:
        skin = default_theme()
        light = with_launch_look(build_theme(skin, "#FFFFFF"), skin, "#FFFFFF", DEFAULT_LAUNCH)
        self.assertNotEqual(self.frame(light), self.frame())
        self.assertEqual([SGR.sub("", line) for line in self.frame(light)], [SGR.sub("", line) for line in self.frame()])

    def test_the_launch_look_paints_the_rules(self) -> None:
        skin = default_theme()
        spectrum = with_launch_look(build_theme(skin), skin, None, "spectrum")
        ember = with_launch_look(build_theme(skin), skin, None, "ember")
        self.assertNotEqual(spectrum.rule.sgr(), ember.rule.sgr())
        self.assertTrue(self.frame(spectrum)[2].startswith(f"{spectrum.rule.sgr()}──"))
        self.assertTrue(self.frame(ember)[2].startswith(f"{ember.rule.sgr()}──"))

    def test_a_256_colour_frame_carries_no_truecolor_parameter(self) -> None:
        lines = self.frame(depth=COLOR_256)
        self.assertTrue(any("\x1b[" in line for line in lines))
        for line in lines:
            self.assertNotIn("38;2;", line)
            self.assertNotIn("48;2;", line)

    def test_no_colour_is_the_coloured_frame_without_its_escapes(self) -> None:
        plain = self.frame(use_color=False)
        self.assertFalse(any("\x1b" in line for line in plain))
        self.assertEqual(plain, [SGR.sub("", line) for line in self.frame()])


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


class CommandThemeTests(unittest.TestCase):
    """`omh model-chains` paints in the theme the OMH TUI opens with, in its saved launch look."""

    def theme(self, root: Path, environ: dict[str, str], stdout=None):
        from omh.commands.model_chains import _picker_theme
        from omh.paths import OmhPaths

        with patch.dict(os.environ, environ, clear=True), patch("sys.stdout", stdout or _Tty()):
            return _picker_theme(OmhPaths(root / ".omh", root / ".hermes"))

    def test_the_saved_launch_look_paints_the_picker(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            skin = default_theme()
            ember = with_launch_look(build_theme(skin), skin, None, "ember")
            spectrum = with_launch_look(build_theme(skin), skin, None, DEFAULT_LAUNCH)
            write_launch_choice(root / ".omh", "ember")
            theme, depth = self.theme(root, {"COLORTERM": "truecolor"})
            self.assertEqual(depth, TRUECOLOR)
            self.assertEqual(theme.rule, ember.rule)
            self.assertNotEqual(theme.rule, spectrum.rule)
            write_launch_choice(root / ".omh", "no-such-look")
            theme, _ = self.theme(root, {"COLORTERM": "truecolor"})
            self.assertEqual(theme.rule, spectrum.rule)

    def test_a_light_colorfgbg_measures_against_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            dark, _ = self.theme(root, {"COLORTERM": "truecolor"})
            light, _ = self.theme(root, {"COLORTERM": "truecolor", "COLORFGBG": "0;15"})
            self.assertNotEqual(dark.muted, light.muted)

    def test_no_color_and_a_pipe_paint_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            theme, depth = self.theme(root, {"COLORTERM": "truecolor", "NO_COLOR": "1"})
            self.assertEqual(depth, NO_COLOR)
            self.assertEqual(theme.menu_current.depth, NO_COLOR)
            self.assertEqual(theme.menu_current.sgr(), "\x1b[1m")
            _, piped = self.theme(root, {"COLORTERM": "truecolor"}, stdout=io.StringIO())
            self.assertEqual(piped, NO_COLOR)


class TuiThemeTests(unittest.TestCase):
    """`/omh-model` paints with the theme the app hands it, at the depth its environment takes."""

    def test_the_apps_theme_paints_the_frames(self) -> None:
        from omh.tui.app import run_model_chain_picker

        amber = theme_for_name("amber")
        assert amber is not None
        theme = with_launch_look(build_theme(amber, "#FFFFFF"), amber, "#FFFFFF", "ember")
        self.assertNotEqual(theme.menu_current.sgr(), DEFAULT_THEME.menu_current.sgr())
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            environ = {"OMH_HOME": str(root / "omh"), "HERMES_HOME": str(root / "hermes"), "COLORTERM": "truecolor"}
            keys = iter(["down", "quit"])
            written: list[str] = []
            message = run_model_chain_picker(environ, theme, read_key=lambda: next(keys), write=written.append, width=120)
            self.assertTrue(message.startswith("Cancelled;"), message)
            self.assertIn(f"{theme.menu_current.sgr()} ❯ ", written[-1])
            self.assertIn(f"{theme.rule.sgr()}──", written[-1])
            self.assertNotIn(DEFAULT_THEME.menu_current.sgr(), "".join(written))
            self.assertIsNone(BACKGROUND.search("".join(written)))

    def test_a_256_colour_environment_paints_at_that_depth(self) -> None:
        from omh.tui.app import run_model_chain_picker

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            environ = {"OMH_HOME": str(root / "omh"), "HERMES_HOME": str(root / "hermes"), "TERM": "xterm-256color"}
            keys = iter(["quit"])
            written: list[str] = []
            run_model_chain_picker(environ, DEFAULT_THEME, read_key=lambda: next(keys), write=written.append, width=120)
            self.assertIn(replace(DEFAULT_THEME.menu_current, depth=COLOR_256).sgr(), written[0])
            self.assertNotIn("38;2;", written[0])


if __name__ == "__main__":
    unittest.main()
