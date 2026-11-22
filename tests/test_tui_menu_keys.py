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
from omh.tui.keys import DOWN, ENTER, ESCAPE, LEFT, TAB, UP, Key

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
    """A `/` after whitespace opens the menu for the token at the caret, as Claude Code's does; a path does not."""

    def test_a_slash_after_a_space_opens_the_menu_filtered_by_what_follows_it(self) -> None:
        for typed, first in (("asdf /", None), ("asdf /mo", "/model"), ("/mo", "/model"), ("asdf /con", "/config"),
                             ("one\n/mo", "/model")):
            with self.subTest(typed=typed):
                app, _client = catalog_app()
                if "\n" in typed:
                    head, tail = typed.split("\n")
                    type_text(app, head)
                    app._on_input(Key(ENTER, alt=True))
                    type_text(app, tail)
                else:
                    type_text(app, typed)
                self.assertEqual(app.composer.text, typed)
                rows = [label for label, _summary in app._menu_rows()]
                self.assertTrue(rows)
                if first is not None:
                    self.assertEqual(rows[0], first)

    def test_a_bare_slash_after_a_space_offers_what_a_bare_leading_slash_does(self) -> None:
        mid, _client = catalog_app()
        type_text(mid, "asdf /")
        lead, _client = catalog_app()
        type_text(lead, "/")
        self.assertEqual(mid._menu_rows(), lead._menu_rows())

    def test_a_path_like_slash_opens_no_menu(self) -> None:
        for typed in ("./", "see ./x", "../", "~/", "go ~/x", "a/b", "see http://", "//", "x //", "x /usr/"):
            with self.subTest(typed=typed):
                app, _client = catalog_app()
                type_text(app, typed)
                self.assertEqual(app._menu_rows(), [])

    def test_the_caret_inside_the_line_opens_the_menu_for_the_token_under_it(self) -> None:
        app, _client = catalog_app()
        type_text(app, "fix /mo then more")
        self.assertEqual(app._menu_rows(), [])
        for _ in range(len(" then more")):
            app._on_input(Key(LEFT))
        self.assertEqual(app._menu_rows()[0][0], "/model")
        app._on_input(Key(TAB))
        self.assertEqual(app.composer.text, "fix /model then more")
        self.assertEqual(app.composer.caret, len("fix /model "))

    def test_taking_a_row_mid_line_replaces_only_the_token(self) -> None:
        app, client = catalog_app()
        type_text(app, "please /con")
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "please /config ")
        self.assertEqual(client.calls, [])
        app, _client = catalog_app()
        type_text(app, "one")
        app._on_input(Key(ENTER, alt=True))
        type_text(app, "two /ulw")
        app._on_input(Key(TAB))
        self.assertEqual(app.composer.text, "one\ntwo /ulw-review ")

    def test_a_line_not_starting_with_a_slash_still_goes_as_a_prompt(self) -> None:
        app, client = catalog_app()
        type_text(app, "please /con")
        app._on_input(Key(ENTER))  # takes /config
        type_text(app, "now")
        self.assertEqual(app._menu_rows(), [])
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "please /config now"}])
        self.assertEqual([call for call in client.calls if call[0] == "slash.exec"], [])

    def test_a_whole_name_mid_line_sends_the_line_on_the_first_enter(self) -> None:
        app, client = catalog_app()
        type_text(app, "please /config")
        self.assertTrue(app._menu_rows())
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "please /config"}])

    def test_esc_closes_the_mid_line_menu_until_the_text_changes(self) -> None:
        app, _client = catalog_app()
        type_text(app, "asdf /mo")
        app._on_input(Key(ESCAPE))
        self.assertEqual(app._menu_rows(), [])
        type_text(app, "d")
        self.assertEqual(app._menu_rows()[0][0], "/model")


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
