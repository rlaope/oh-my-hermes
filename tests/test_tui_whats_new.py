"""What's new (owner, 2026-11-02): a few lines on what changed, under the launch card on the first fresh launch
after the version changed, once; `/whats-new` says them again."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from _test_temp_root import make_test_tempdir
from omh.tui import slash
from omh.tui.app import WHATS_NEW_NONE_NOTICE
from omh.tui.keys import ENTER, Key
from omh.tui.whats_new import (
    EARLIER_TUI_STATE, SHOWN_SCHEMA, WHATS_NEW, is_due, read_shown, record_shown, shown_path, whats_new_text,
)
from omh.version import __version__
from test_tui_launch_card import Launched
from test_tui_modes import make_app, notices, type_text

VERSION = "9.9.9"  # the running version every launch here pins, so nothing moves with a release
ITEMS = ("The first change", "The second change", "The third change")


class Pinned(unittest.TestCase):
    """Launches of version 9.9.9, which has ITEMS for its What's new, in a temporary OMH home."""

    def setUp(self) -> None:
        self.home = Path(self.enterContext(make_test_tempdir("omh-whats-new-"))) / ".omh"
        self.enterContext(mock.patch("omh.tui.app.__version__", VERSION))
        self.enterContext(mock.patch.dict(WHATS_NEW, {VERSION: ITEMS}))

    def record(self, version: str) -> None:
        shown_path(self.home).parent.mkdir(parents=True, exist_ok=True)
        shown_path(self.home).write_text(json.dumps({"schema_version": SHOWN_SCHEMA, "version": version}),
                                         encoding="utf-8")

    def earlier(self, name: str) -> None:
        """Leave what an OMH TUI from before the record existed wrote under the home."""
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    def launch(self, rows: int = 42, cols: int = 150, **env: str) -> list[str]:
        run = Launched(rows=rows, cols=cols, env={"OMH_HOME": str(self.home), **env})
        run.info()
        return run.screen()


class LaunchTests(Pinned):
    def test_the_first_launch_after_an_update_says_it_under_the_card_once(self) -> None:
        self.record("9.9.8")
        screen = self.launch()
        heading = screen.index("What's new in v9.9.9")
        card_end = max(index for index, line in enumerate(screen) if line.startswith("╰"))
        self.assertEqual(heading, card_end + 2, screen)  # under the card, a blank row between
        self.assertEqual(screen[card_end + 1], "")
        self.assertEqual(screen[heading + 1 : heading + 4], [f"  · {item}" for item in ITEMS])
        self.assertEqual(read_shown(self.home), VERSION)
        self.assertNotIn("What's new in v9.9.9", self.launch())  # the next launch: said once

    def test_a_new_install_is_not_told_what_is_new_and_the_version_is_recorded(self) -> None:
        self.earlier("setup-profile.json")  # `omh setup` writes it before a new install's first launch
        self.assertNotIn("What's new in v9.9.9", self.launch())
        self.assertEqual(read_shown(self.home), VERSION)

    def test_an_install_from_before_the_record_is_told_once(self) -> None:
        # Owner, 2026-11-02: an upgrade from a version that kept no record still sees What's new.
        self.assertEqual(EARLIER_TUI_STATE, ("tui/launch-skills.json",))  # only the TUI writes it
        self.earlier("tui/launch-skills.json")
        self.assertIn("What's new in v9.9.9", self.launch())
        self.assertEqual(read_shown(self.home), VERSION)
        self.assertNotIn("What's new in v9.9.9", self.launch())

    def test_a_theme_saved_from_the_shell_alone_is_a_new_install(self) -> None:
        self.earlier("setup-profile.json")
        self.earlier("tui/theme.json")  # `omh theme use` before the first launch
        self.assertNotIn("What's new in v9.9.9", self.launch())
        self.assertEqual(read_shown(self.home), VERSION)

    def test_a_card_with_no_room_for_it_does_not_spend_it(self) -> None:
        self.record("9.9.8")
        screen = self.launch(cols=36)  # under 40 columns the card is not drawn, nor the block under it
        self.assertFalse(any(line.startswith("What's new") for line in screen), screen)
        self.assertEqual(read_shown(self.home), "9.9.8")
        self.assertIn("What's new in v9.9.9", self.launch())

    def test_a_resumed_session_shows_it_not_and_leaves_it_for_the_next_fresh_launch(self) -> None:
        self.record("9.9.8")
        self.launch(HERMES_TUI_RESUME="stored-1")
        self.assertEqual(read_shown(self.home), "9.9.8")
        self.assertIn("What's new in v9.9.9", self.launch())

    def test_a_version_with_no_entry_shows_nothing_and_is_recorded(self) -> None:
        self.record("9.9.8")
        with mock.patch.dict(WHATS_NEW, clear=True):
            screen = self.launch()
        self.assertFalse(any(line.startswith("What's new") for line in screen), screen)
        self.assertEqual(read_shown(self.home), VERSION)

    def test_a_short_terminal_keeps_the_heading_and_names_the_command(self) -> None:
        self.record("9.9.8")
        run = Launched(rows=24, cols=120, env={"OMH_HOME": str(self.home)})
        run.info()
        screen = run.screen()
        self.assertIn("What's new in v9.9.9 · /whats-new lists it", screen)
        self.assertTrue(any(line.startswith("╭─ session") for line in screen), screen)  # beside the card

    def test_due_reads_the_record_and_the_earlier_state_and_writes_nothing(self) -> None:
        self.assertFalse(is_due(self.home, VERSION))  # no record and no TUI state: a new install
        self.assertFalse(shown_path(self.home).exists())
        self.record("9.9.8")
        self.assertTrue(is_due(self.home, VERSION))  # changed from 9.9.8
        self.assertFalse(is_due(self.home, "9.9.7"))  # changed, but 9.9.7 has no entry
        self.assertTrue(record_shown(self.home, VERSION))
        self.assertFalse(is_due(self.home, VERSION))  # said once
        shown_path(self.home).write_text("[" * 100_000, encoding="utf-8")  # too deep to parse: no record
        self.assertIsNone(read_shown(self.home))


class CommandTests(Pinned):
    def test_whats_new_says_it_again_whenever_asked(self) -> None:
        app, _client = make_app(environ={"OMH_HOME": str(self.home)})
        for typed in ("/whats-new", "/whatsnew"):
            with self.subTest(typed=typed):
                type_text(app, typed)
                app._on_input(Key(ENTER, ""))
                self.assertEqual(notices(app)[-1], whats_new_text(VERSION))
        self.assertEqual(whats_new_text(VERSION), "What's new in v9.9.9\n· The first change\n· The second change\n"
                                                  "· The third change")
        self.assertFalse(shown_path(self.home).exists())  # the command records nothing

    def test_whats_new_without_an_entry_says_there_is_none(self) -> None:
        app, _client = make_app()
        with mock.patch.dict(WHATS_NEW, clear=True):
            app._local_handlers()["whats-new"]("")
        self.assertEqual(notices(app)[-1], WHATS_NEW_NONE_NOTICE.format(version=VERSION))

    def test_it_is_the_tui_s_own_command_under_both_names(self) -> None:
        for name in ("whats-new", "whatsnew"):
            with self.subTest(name=name):
                invocation = slash.parse_slash(f"/{name}")
                self.assertEqual((invocation.command.name, invocation.command.route), ("whats-new", slash.LOCAL))


class ReleaseTests(unittest.TestCase):
    def test_the_running_version_has_a_whats_new(self) -> None:
        # A release adds its entry in the release prep PR (docs/RELEASE.md): three to five lines from its CHANGELOG.
        items = WHATS_NEW.get(__version__)
        self.assertIsNotNone(items, f"src/tui/whats_new.py has no WHATS_NEW entry for {__version__}")
        assert items is not None
        self.assertTrue(3 <= len(items) <= 5, items)
        for item in items:
            with self.subTest(item=item):
                self.assertNotIn("\n", item)
                self.assertLessEqual(len(item), 72)  # one row under the card on an 80-column terminal
                self.assertEqual(item, item.strip())


if __name__ == "__main__":
    unittest.main()
