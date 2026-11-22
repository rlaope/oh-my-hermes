"""The completion menus' keys: Enter on an open `/` or `@` menu, Esc on the `/` menu, the ends of both lists.

Every case drives an `App` over the recording client from `test_tui_modes`.
Enter follows Ink's rule (`completionToApplyOnSubmit` in ui-tui
`domain/slash.ts`): it takes the highlighted row when that changes what is
typed, and runs the line when the row only adds the space after a command
typed in full, or when the typed word is already a command's whole name.
"""

from __future__ import annotations

import unittest

from test_tui_catalog import CATALOG, catalog_app
from test_tui_modes import SID, make_app, notices, type_text
from omh.tui.app import App, PathItem
from omh.tui.keys import BACKSPACE, DOWN, ENTER, ESCAPE, LEFT, TAB, UP, Key, Paste

PATHS = [PathItem("@src/foo.py", "foo.py", ""), PathItem("@src/fold/", "fold/", "dir")]


def path_app(typed: str = "fix @src/fo") -> App:
    app, _client = make_app()
    type_text(app, typed)
    app._track_path_token()
    app.path_items = list(PATHS)
    return app


class EnterOnTheSlashMenuTests(unittest.TestCase):
    def test_enter_takes_the_highlighted_command_and_sends_nothing(self) -> None:
        app, client = catalog_app()
        type_text(app, "/mo")
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "/model ")
        self.assertEqual(client.calls, [])
        self.assertEqual(app.transcript.blocks, [])

    def test_a_second_enter_runs_the_command_taken(self) -> None:
        app, client = catalog_app()
        type_text(app, "/con")
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "/config ")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("slash.exec", {"command": "config", "session_id": SID})])

    def test_enter_takes_the_row_the_arrows_moved_to(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/t")
        names = [label for label, _summary in app._menu_rows()]
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, f"{names[1]} ")

    def test_a_command_typed_in_full_runs_on_the_first_enter(self) -> None:
        # The highlighted row would only add the trailing space, or the typed word is a command's whole name (an alias
        # too, though the menu lists a longer name first: `/q` is /queue, the menu starts with /quit).
        for typed, sent in (("/config", ("slash.exec", {"command": "config", "session_id": SID})),
                            ("/tools", ("slash.exec", {"command": "tools", "session_id": SID}))):
            with self.subTest(typed=typed):
                app, client = catalog_app()
                type_text(app, typed)
                self.assertTrue(app._menu_rows())
                app._on_input(Key(ENTER))
                self.assertEqual(client.calls, [sent])
                self.assertEqual(app.composer.text, "")
        app, client = catalog_app()
        type_text(app, "/q")
        self.assertEqual(app._menu_rows()[0][0], "/quit")
        app._on_input(Key(ENTER))
        self.assertIsNone(app.exit_code)
        self.assertEqual(app.composer.text, "")
        self.assertEqual(notices(app), ["Nothing is queued."])

    def test_a_whole_name_still_takes_the_row_the_arrows_moved_to(self) -> None:
        app, client = catalog_app()
        type_text(app, "/q")
        app._on_input(Key(DOWN))
        taken = app._menu_rows()[1][0]
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, f"{taken} ")
        self.assertEqual(client.calls, [])

    def test_alt_and_shift_enter_add_a_line_over_the_menu(self) -> None:
        for key in (Key(ENTER, alt=True), Key(ENTER, shift=True)):
            with self.subTest(key=key):
                app, _client = catalog_app()
                type_text(app, "/mo")
                app._on_input(key)
                self.assertEqual(app.composer.text, "/mo\n")

    def test_with_no_menu_open_enter_sends_what_is_typed(self) -> None:
        app, client = catalog_app()
        type_text(app, "/nosuchthing")
        self.assertEqual(app._menu_rows(), [])
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("slash.exec", {"command": "nosuchthing", "session_id": SID})])


class EnterOnThePathMenuTests(unittest.TestCase):
    def test_enter_takes_the_highlighted_path_and_starts_no_turn(self) -> None:
        app = path_app()
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "fix @src/foo.py")
        self.assertEqual(app.client.calls, [])  # type: ignore[attr-defined]
        self.assertFalse(app.turn_pending)
        app._on_input(Key(ENTER))
        self.assertEqual(app.client.named("prompt.submit"), [{"session_id": SID, "text": "fix @src/foo.py"}])  # type: ignore[attr-defined]

    def test_enter_on_a_folder_takes_it_and_the_menu_lists_it_next(self) -> None:
        app = path_app()
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "fix @src/fold/")
        app._track_path_token()
        self.assertEqual(app.path_word, "@src/fold/")

    def test_a_path_typed_in_full_sends_on_the_first_enter(self) -> None:
        app = path_app("fix @src/foo.py")
        app._on_input(Key(ENTER))
        self.assertEqual(app.client.named("prompt.submit"), [{"session_id": SID, "text": "fix @src/foo.py"}])  # type: ignore[attr-defined]


class EscOnTheSlashMenuTests(unittest.TestCase):
    def test_esc_closes_the_slash_menu_without_arming_a_clear(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/mo")
        app._on_input(Key(ESCAPE))
        self.assertEqual(app._menu_rows(), [])
        self.assertEqual(app.composer.text, "/mo")
        self.assertIsNone(app.escape_armed)
        app._on_input(Key(ENTER))  # the menu is closed: Enter sends what is typed
        self.assertEqual(app.client.calls, [("slash.exec", {"command": "mo", "session_id": SID})])  # type: ignore[attr-defined]

    def test_a_second_esc_after_closing_arms_the_clear_as_ever(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/mo")
        app._on_input(Key(ESCAPE))
        app._on_input(Key(ESCAPE))
        self.assertIsNotNone(app.escape_armed)
        app._on_input(Key(ESCAPE))
        self.assertEqual(app.composer.text, "")

    def test_typing_opens_it_again(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/mo")
        app._on_input(Key(ESCAPE))
        type_text(app, "d")
        self.assertEqual(app._menu_rows()[0][0], "/model")

    def test_the_path_menu_still_closes_on_esc(self) -> None:
        app = path_app()
        app._on_input(Key(ESCAPE))
        self.assertEqual(app._menu_rows(), [])
        self.assertIsNone(app.escape_armed)


class MidLineSlashMenuTests(unittest.TestCase):
    """A `/` after whitespace opens a menu of the catalog's skills for the token at the caret, as Claude Code names a
    skill after other text; a built-in command means something only at the line's start, and a path opens nothing.

    A mid-line menu never takes a key the line needs: Enter sends the line and Up stays history and the caret until
    Down moves into the menu; Tab always takes the highlighted row. It opens only over the person's own typing.
    """

    SKILLS = ["/omh-codebase-uml", "/ulw-review"]  # the test catalog's skills: the pairs no category lists

    def test_a_slash_after_a_space_lists_the_skills_filtered_by_what_follows_it(self) -> None:
        skills = self.SKILLS
        for typed, rows in (("asdf /", skills), ("asdf /ul", ["/ulw-review"]), ("asdf /uml", ["/omh-codebase-uml"]),
                            ("one\n/ulw", ["/ulw-review"]), ("asdf /U", ["/ulw-review", "/omh-codebase-uml"])):
            with self.subTest(typed=typed):
                app, _client = catalog_app()
                head, newline, tail = typed.partition("\n")
                type_text(app, head)
                if newline:
                    app._on_input(Key(ENTER, alt=True))
                    type_text(app, tail)
                self.assertEqual(app.composer.text, typed)
                self.assertEqual([label for label, _summary in app._menu_rows()], rows)

    def test_no_built_in_command_is_offered_mid_line(self) -> None:
        # The TUI's own (/model, /compact, /help, /theme, /whats-new) and Hermes' (/config, /tools) alike.
        for typed in ("asdf /mo", "asdf /comp", "asdf /he", "asdf /theme", "asdf /wh", "asdf /con", "asdf /too"):
            with self.subTest(typed=typed):
                app, _client = catalog_app()
                type_text(app, typed)
                self.assertEqual(app._menu_rows(), [])
        app, _client = catalog_app()
        type_text(app, "asdf /")
        self.assertTrue(all(label in self.SKILLS for label, _summary in app._menu_rows()))

    def test_a_path_like_slash_opens_no_menu(self) -> None:
        for typed in ("./", "see ./x", "../", "~/", "go ~/x", "a/b", "see http://", "//", "x //", "x /usr/"):
            with self.subTest(typed=typed):
                app, _client = catalog_app()
                type_text(app, typed)
                self.assertEqual(app._menu_rows(), [])

    def test_a_mid_line_word_matches_by_prefix_or_substring_never_by_scattered_letters(self) -> None:
        # `/opt` holds o..p..t in order in names the leading `/` menu offers; mid-line, a path word offers nothing.
        lead, _client = catalog_app()
        type_text(lead, "/opt")
        self.assertTrue(lead._menu_rows())
        for typed in ("path /opt", "cd /tmp", "see /usr", "in /etc", "fix /urv"):
            with self.subTest(typed=typed):
                app, _client = catalog_app()
                type_text(app, typed)
                self.assertEqual(app._menu_rows(), [])

    def test_enter_sends_a_mid_line_line_unchanged(self) -> None:
        for typed in ("path /opt", "fix /a", "a /", "please /ul"):
            with self.subTest(typed=typed):
                app, client = catalog_app()
                type_text(app, typed)
                app._on_input(Key(ENTER))
                self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": typed}])
                self.assertEqual([call for call in client.calls if call[0] == "slash.exec"], [])

    def test_down_then_enter_takes_the_row_it_moved_to(self) -> None:
        app, client = catalog_app()
        type_text(app, "please /")
        app._on_input(Key(DOWN))
        self.assertEqual(app.menu_index, 1)
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "please /ulw-review ")
        self.assertEqual(client.calls, [])

    def test_up_on_an_engaged_menu_moves_its_highlight(self) -> None:
        app, _client = catalog_app()
        type_text(app, "please /")
        app._on_input(Key(DOWN))
        app._on_input(Key(UP))
        self.assertEqual(app.menu_index, 0)
        self.assertEqual(app.composer.text, "please /")

    def test_tab_takes_the_highlighted_row_without_moving_into_the_menu(self) -> None:
        app, _client = catalog_app()
        type_text(app, "please /ul")
        app._on_input(Key(TAB))
        self.assertEqual(app.composer.text, "please /ulw-review ")

    def test_up_walks_history_whose_entries_end_in_a_slash_word(self) -> None:
        app, _client = catalog_app()
        app.composer.history = ["old one", "earlier /ulw", "newest /ulw"]
        seen = []
        for _ in range(3):
            app._on_input(Key(UP))
            seen.append(app.composer.text)
            self.assertEqual(app._menu_rows(), [])  # recalled text opens no menu
        self.assertEqual(seen, ["newest /ulw", "earlier /ulw", "old one"])

    def test_up_moves_the_caret_over_a_typed_mid_line_menu(self) -> None:
        app, _client = catalog_app()
        type_text(app, "first")
        app._on_input(Key(ENTER, alt=True))
        type_text(app, "fix /ulw")
        self.assertTrue(app._menu_rows())
        app._on_input(Key(UP))
        self.assertLess(app.composer.caret, len("first\n"))
        self.assertEqual(app.menu_index, 0)

    def test_a_paste_ending_in_a_slash_word_opens_no_menu_and_enter_sends_it(self) -> None:
        app, client = catalog_app()
        app._on_input(Paste("say hi /ulw"))
        self.assertEqual(app._menu_rows(), [])
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "say hi /ulw"}])

    def test_the_next_typed_key_after_a_paste_opens_it(self) -> None:
        app, _client = catalog_app()
        app._on_input(Paste("say hi /u"))
        type_text(app, "l")
        self.assertEqual(app._menu_rows()[0][0], "/ulw-review")

    def test_backspace_after_a_paste_opens_it_too(self) -> None:
        app, _client = catalog_app()
        app._on_input(Paste("say hi /ulx"))
        self.assertEqual(app._menu_rows(), [])
        app._on_input(Key(BACKSPACE))
        self.assertEqual(app._menu_rows()[0][0], "/ulw-review")

    def test_the_caret_inside_the_line_opens_the_menu_for_the_token_under_it(self) -> None:
        app, _client = catalog_app()
        type_text(app, "fix /ul then more")
        self.assertEqual(app._menu_rows(), [])
        for _ in range(len(" then more")):
            app._on_input(Key(LEFT))
        self.assertEqual(app._menu_rows()[0][0], "/ulw-review")
        app._on_input(Key(TAB))
        self.assertEqual(app.composer.text, "fix /ulw-review then more")
        self.assertEqual(app.composer.caret, len("fix /ulw-review "))

    def test_a_pick_before_a_newline_adds_no_space(self) -> None:
        app, _client = catalog_app()
        type_text(app, "two /ulw")
        app._on_input(Key(ENTER, alt=True))
        type_text(app, "next")
        for _ in range(len("next") + 1):
            app._on_input(Key(LEFT))
        app._on_input(Key(TAB))
        self.assertEqual(app.composer.text, "two /ulw-review\nnext")

    def test_esc_closes_the_mid_line_menu_until_the_text_changes(self) -> None:
        app, _client = catalog_app()
        type_text(app, "asdf /ul")
        app._on_input(Key(ESCAPE))
        self.assertEqual(app._menu_rows(), [])
        type_text(app, "w")
        self.assertEqual(app._menu_rows()[0][0], "/ulw-review")


class LeadingSlashMenuUnchangedTests(unittest.TestCase):
    """The leading `/` menu behaves as before the mid-line menu came."""

    def test_a_leading_slash_still_offers_the_built_in_commands(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/mo")
        self.assertEqual(app._menu_rows()[0][0], "/model")
        app, _client = catalog_app()
        type_text(app, "/comp")
        self.assertIn("/compact", [label for label, _summary in app._menu_rows()])

    def test_enter_takes_a_partial_name_and_runs_a_whole_one(self) -> None:
        app, client = catalog_app()
        type_text(app, "/mo")
        app._on_input(Key(ENTER))
        self.assertEqual((app.composer.text, client.calls), ("/model ", []))
        app, client = catalog_app()
        type_text(app, "/config")
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("slash.exec", {"command": "config", "session_id": SID})])

    def test_theme_lists_the_launch_looks(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/theme ")
        looks = [label for label, _summary in app._menu_rows()]
        self.assertTrue(looks)
        self.assertTrue(all(label.startswith("/theme ") for label in looks))
        typed = looks[0].removeprefix("/theme ")[:2]
        type_text(app, typed)
        self.assertTrue(all(label.startswith(f"/theme {typed}") for label, _summary in app._menu_rows()))

    def test_up_moves_the_leading_menu_at_once(self) -> None:
        app, _client = catalog_app()
        type_text(app, "/t")
        app._on_input(Key(DOWN))
        app._on_input(Key(UP))
        self.assertEqual(app.menu_index, 0)
        app._on_input(Key(DOWN))
        self.assertEqual(app.menu_index, 1)


class MenuEndsTests(unittest.TestCase):
    def test_both_menus_stop_at_either_end(self) -> None:
        slash, _client = catalog_app({**CATALOG})
        type_text(slash, "/t")
        for app in (slash, path_app()):
            with self.subTest(app=app.composer.text):
                last = len(app._menu_rows()) - 1
                app._on_input(Key(UP))
                self.assertEqual(app.menu_index, 0)
                for _ in range(last + 3):
                    app._on_input(Key(DOWN))
                self.assertEqual(app.menu_index, last)


if __name__ == "__main__":
    unittest.main()
