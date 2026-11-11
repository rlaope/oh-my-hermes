"""The OMH TUI's key table: one list for the `?` overlay, `/keys` and the docs.

The Keys table in docs/INSTALLATION.md is compared row for row with
`shortcuts.SHORTCUTS`, so the two cannot drift. The Ctrl letters the table
names are compared with the Ctrl letters that do anything in the app, in both
directions, so a key bound without a row, or a row for a key nothing reads,
fails here too.
"""

from __future__ import annotations

from pathlib import Path
import re
import signal
import string
import unittest
from unittest.mock import patch

from _tui_lines import line_text
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import RecordingClient, drawn, make_app, type_text
from omh.tui.app import App
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, TAB, UP, Key, Paste, list_nav_step
from omh.tui.pager import ALT_SCREEN_OFF, ALT_SCREEN_ON
from omh.tui.shortcuts import SHORTCUTS, TITLE, shortcut_lines
from omh.tui.theme import DEFAULT_THEME
from omh.tui.width import line_width

INSTALLATION = Path(__file__).resolve().parents[1] / "docs" / "INSTALLATION.md"
TABLE_HEADER = "| Key | Does |"
QUESTION_MARK = Key(CHAR, "?")


def documented_keys() -> list[tuple[str, str]]:
    """The rows of INSTALLATION's Keys table, backticks removed."""
    lines = INSTALLATION.read_text(encoding="utf-8").splitlines()
    start = lines.index(TABLE_HEADER) + 2  # the header and its rule
    rows: list[tuple[str, str]] = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        keys, does = (cell.strip().replace("`", "") for cell in line.strip().strip("|").split("|"))
        rows.append((keys, does))
    return rows


def ctrl_letters_named() -> set[str]:
    return {letter.lower() for keys, _does in SHORTCUTS for letter in re.findall(r"Ctrl\+([A-Z])\b", keys)}


def observed(app: App, client: RecordingClient) -> tuple[object, ...]:
    """Everything a key can change that a person or Hermes would notice, once the frame after it is drawn (a full
    redraw's erase goes out with that frame)."""
    terminal: ScriptedTerminal = app.terminal  # type: ignore[assignment]
    app._render()
    return (
        app.composer.text,
        app.composer.caret,
        len(client.calls),
        len(app.transcript.blocks),
        app.transcript.details_expanded,
        app.exit_code,
        app.pager is not None,
        app.search is not None,
        len(terminal.writes),
        terminal.suspended,
    )


class TableTests(unittest.TestCase):
    def test_the_installation_keys_table_is_the_code_table(self) -> None:
        self.assertEqual(documented_keys(), list(SHORTCUTS))

    def test_composer_rows_explain_focused_navigation_exceptions(self) -> None:
        for source, table in (("overlay", SHORTCUTS), ("installation", documented_keys())):
            with self.subTest(source=source):
                rows = dict(table)
                newline = rows["\\ then Enter, Alt+Enter, Shift+Enter, Ctrl+J"]
                self.assertIn("with a list or menu focused, Ctrl+J moves down instead", newline)
                self.assertIn("Alt+Enter and Shift+Enter still add a line in an open menu", newline)
                self.assertIn("backslash then Enter may accept a completion", newline)
                self.assertIn("with a list or menu focused, Ctrl+K moves up instead", rows["Ctrl+U / Ctrl+K"])

    def test_every_row_names_keys_and_what_they_do_once(self) -> None:
        keys = [keys for keys, _does in SHORTCUTS]
        self.assertEqual(len(keys), len(set(keys)))
        for row in SHORTCUTS:
            with self.subTest(row=row):
                self.assertTrue(all(cell.strip() == cell and cell for cell in row))
                self.assertNotIn("|", "".join(row))  # a pipe would split the doc table's cell
                self.assertNotIn("`", "".join(row))

    def test_the_list_row_names_every_picker_that_takes_its_keys(self) -> None:
        # The session, rewind and bare /model pickers each say these keys on the info line; the list names all three.
        from omh.tui.model_picker import KEYS as MODEL_KEYS
        from omh.tui.rewind_picker import KEYS as REWIND_KEYS
        from omh.tui.session_picker import KEYS as SESSION_KEYS

        (row,) = [does for keys, does in SHORTCUTS if keys == "↑ / ↓, PageUp / PageDown, Enter, Esc"]
        for command, said in (("/sessions", SESSION_KEYS), ("/rewind", REWIND_KEYS), ("/model", MODEL_KEYS)):
            with self.subTest(picker=command):
                self.assertIn(command, row)
                self.assertTrue(said[0].startswith("↑↓ move · enter ") and said[0].endswith(" · esc closes"), said)

    def test_the_steer_row_names_the_key_and_the_command_that_works_everywhere(self) -> None:
        # Ctrl+Enter steers typed text where it is a key; /steer <text> works everywhere; the list names both, and
        # the send-now row names Ctrl+J, which every terminal sends apart from Enter.
        (steer,) = [does for keys, does in SHORTCUTS if keys == "Ctrl+Enter"]
        self.assertIn("/steer <text>", steer)
        (send_now,) = [does for keys, does in SHORTCUTS if keys == "Ctrl+Enter, Ctrl+J"]
        self.assertIn("oldest queued prompt", send_now)

    def test_the_ctrl_letters_named_are_the_ones_that_do_something(self) -> None:
        named = ctrl_letters_named()
        self.assertEqual(named, set("acdejklnprstouvwxyz"))
        for letter in string.ascii_lowercase:
            changed = False
            for draft, undone in (("", False), ("one two", False), ("one two", True)):  # Ctrl+Y redoes the undone draft
                app, client = make_app()
                if letter == "n":  # Ctrl+N navigates only when a list owns input
                    from omh.tui.session_picker import SessionPicker, SessionRow

                    app.picker = SessionPicker([SessionRow("one", "One", "", 0, 0), SessionRow("two", "Two", "", 0, 0)], current="")
                if letter == "p":  # Ctrl+P folds the plan: it does something only while a plan shows
                    from omh.tui.panels import HudSnapshot
                    from test_tui_panels import hud_payload

                    app.hud = HudSnapshot(app.stored_id, hud_payload([{"text": "Ship it", "state": "active"}]), 0.0)
                type_text(app, draft)
                app._on_input(Key(LEFT))
                if undone:
                    app._on_input(Key(CHAR, "_", ctrl=True))
                before = observed(app, client)
                app._on_input(Key(CHAR, letter, ctrl=True))
                changed = changed or observed(app, client) != before
            with self.subTest(letter=letter):
                # Ctrl+Z suspends only where there is job control (no SIGTSTP on Windows).
                self.assertEqual(changed, letter in named and (letter != "z" or hasattr(signal, "SIGTSTP")))


class OverlayLinesTests(unittest.TestCase):
    def test_every_key_and_description_is_on_the_overlay_at_any_width(self) -> None:
        for width in (20, 36, 60, 80, 120, 200):
            lines = shortcut_lines(width, DEFAULT_THEME)
            text = " ".join(" ".join(line_text(line).split()) for line in lines)
            with self.subTest(width=width):
                self.assertEqual(line_text(lines[0]), TITLE)
                self.assertTrue(all(line_width(line) <= width for line in lines))
                for keys, does in SHORTCUTS:
                    self.assertIn(" ".join(keys.split()), text)
                    self.assertIn(" ".join(does.split()), text)

    def test_a_wide_terminal_puts_the_description_beside_the_keys_and_a_narrow_one_under_them(self) -> None:
        wide = [line_text(line) for line in shortcut_lines(120, DEFAULT_THEME)]
        self.assertTrue(any(line.startswith("Enter" + " " * 41 + "Sends the composer;") for line in wide))
        narrow = [line_text(line) for line in shortcut_lines(40, DEFAULT_THEME)]
        at = narrow.index("Enter")
        self.assertTrue(narrow[at + 1].startswith("  Sends the composer;"))

    def test_the_keys_are_bold_and_the_text_is_text(self) -> None:
        line = next(line for line in shortcut_lines(120, DEFAULT_THEME) if line_text(line).startswith("Ctrl+T"))
        self.assertEqual(line[0].style, DEFAULT_THEME.user)  # bold, no hue: a key is no state
        self.assertEqual(line[-1].style, DEFAULT_THEME.text)


class GuideKeyTests(unittest.TestCase):
    def open(self, app: App) -> bool:
        return app.pager is not None  # a bool: a failed assertion must not print the whole pager

    def paged(self, app: App) -> str:
        assert app.pager is not None
        return "\n".join(line_text(line) for line in app.pager.lines)

    def test_a_question_mark_on_an_empty_composer_opens_the_key_list(self) -> None:
        app, client = make_app()
        app._on_input(QUESTION_MARK)
        self.assertTrue(self.open(app))
        self.assertEqual(app.composer.text, "")
        self.assertIn(ALT_SCREEN_ON, app.terminal.writes)  # type: ignore[attr-defined]
        paged = self.paged(app)
        self.assertIn(TITLE, paged)
        self.assertIn("Shift+Tab", paged)
        self.assertEqual(client.calls, [])

    def test_esc_and_q_close_it(self) -> None:
        for key in (Key(ESCAPE), Key(CHAR, "q")):
            with self.subTest(key=key):
                app, _client = make_app()
                app._on_input(QUESTION_MARK)
                app._on_input(key)
                self.assertFalse(self.open(app))
                self.assertIn(ALT_SCREEN_OFF, "".join(app.terminal.writes))  # type: ignore[attr-defined]
                self.assertEqual(app.composer.text, "")

    def test_a_question_mark_in_a_composer_with_text_is_text(self) -> None:
        for draft in ("why", " ", "what\n"):
            with self.subTest(draft=draft):
                app, _client = make_app()
                app.composer.replace(0, 0, draft)
                app._on_input(QUESTION_MARK)
                self.assertFalse(self.open(app))
                self.assertEqual(app.composer.text, draft + "?")

    def test_a_pasted_or_modified_question_mark_is_not_the_key(self) -> None:
        for event in (Paste("?"), Key(CHAR, "?", alt=True), Key(CHAR, "?", ctrl=True), Key(CHAR, "？")):
            with self.subTest(event=event):
                app, _client = make_app()
                app._on_input(event)
                self.assertFalse(self.open(app))

    def test_a_question_mark_typed_as_an_answer_is_the_answer(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._on_server_request(ServerRequest("srq-1", "vault.code", {}))
        now[0] += 1.0
        app._on_input(QUESTION_MARK)
        self.assertFalse(self.open(app))
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"value": "?"}})])

    def test_a_question_mark_on_an_approval_opens_nothing_and_allows_nothing(self) -> None:
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        now[0] += 1.0
        app._on_input(QUESTION_MARK)
        self.assertFalse(self.open(app))
        self.assertEqual(client.answers, [])

    def test_the_keys_command_opens_the_same_list(self) -> None:
        by_key, _client = make_app()
        by_key._on_input(QUESTION_MARK)
        by_command, client = make_app()
        type_text(by_command, "/keys")
        by_command._on_input(Key(ENTER))
        self.assertEqual(self.paged(by_command), self.paged(by_key))
        self.assertEqual(client.calls, [])

    def test_help_points_at_the_key_list_instead_of_keeping_its_own(self) -> None:
        app, _client = make_app()
        type_text(app, "/help")
        app._on_input(Key(ENTER))
        self.assertFalse(self.open(app))  # its output is the transcript's, however long
        text = app.transcript.blocks[-1].parts[0][0]
        self.assertIn("Keys: ? on an empty composer, or /keys, lists every key.", text)
        self.assertIn("/keys ", text)  # and the command is listed with the TUI's own
        self.assertNotIn("Ctrl+D", text)  # the key rows themselves are gone from /help
        self.assertNotIn("Alt+Enter", text)

    def test_an_app_without_a_terminal_size_surprise_still_builds_its_list(self) -> None:
        app = App(ScriptedTerminal(rows=6, cols=20), RecordingClient(), {}, poller=FakePoller())  # type: ignore[arg-type]
        app._on_input(QUESTION_MARK)
        assert app.pager is not None
        self.assertTrue(all(line_width(line) <= 20 for line in app.pager.lines))


class CtrlNPNavigationTests(unittest.TestCase):
    def test_helper_mapping(self) -> None:
        """A6: list_nav_step mapping logic and exact modifier rejection."""
        self.assertEqual(list_nav_step(Key(DOWN)), 1)
        self.assertEqual(list_nav_step(Key(UP)), -1)
        self.assertEqual(list_nav_step(Key(CHAR, "n", ctrl=True)), 1)
        self.assertEqual(list_nav_step(Key(CHAR, "p", ctrl=True)), -1)

        # Modifiers and chords rejected
        self.assertEqual(list_nav_step(Key(CHAR, "n")), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "p")), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "n", ctrl=True, alt=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "p", ctrl=True, shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "n", ctrl=True, reported_shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "p", ctrl=True, reported_shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "n", alt=True)), 0)
        self.assertEqual(list_nav_step(Key(DOWN, alt=True)), 0)
        self.assertEqual(list_nav_step(Key(DOWN, ctrl=True)), 0)
        self.assertEqual(list_nav_step(Key(UP, shift=True)), 0)
        self.assertEqual(list_nav_step(Paste("n")), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "x", ctrl=True)), 0)

    def test_ctrl_np_step_matches_arrows(self) -> None:
        """A1: Parity across ModelPicker, SessionPicker, RewindPicker, LaunchPicker, and AgentView (both modes)."""
        from omh.tui.launch_picker import LaunchPicker, LAUNCH_PRESETS
        from omh.tui.model_picker import ModelPicker, ModelRow
        from omh.tui.rewind_picker import RewindPicker, RewindRow
        from omh.tui.session_picker import SessionPicker, SessionRow
        from omh.tui.subagents import MAIN_ID, Roster

        # 1. ModelPicker
        m_rows = [ModelRow("m1", "p1", "Provider 1", True), ModelRow("m2", "p2", "Provider 2", False), ModelRow("m3", "p3", "Provider 3", False)]
        mp_arrow = ModelPicker(m_rows, current="m1")
        mp_ctrl = ModelPicker(m_rows, current="m1")
        mp_arrow.handle_key(Key(DOWN))
        mp_ctrl.handle_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(mp_arrow.index, mp_ctrl.index)
        self.assertEqual(mp_ctrl.index, 1)
        mp_arrow.handle_key(Key(UP))
        mp_ctrl.handle_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(mp_arrow.index, mp_ctrl.index)
        self.assertEqual(mp_ctrl.index, 0)

        # 2. SessionPicker
        s_rows = [SessionRow("s1", "Session 1", "preview 1", 100.0, 5), SessionRow("s2", "Session 2", "preview 2", 90.0, 3), SessionRow("s3", "Session 3", "preview 3", 80.0, 1)]
        sp_arrow = SessionPicker(s_rows, current="s1")
        sp_ctrl = SessionPicker(s_rows, current="s1")
        sp_arrow.handle_key(Key(DOWN))
        sp_ctrl.handle_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(sp_arrow.index, sp_ctrl.index)
        self.assertEqual(sp_ctrl.index, 1)
        sp_arrow.handle_key(Key(UP))
        sp_ctrl.handle_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(sp_arrow.index, sp_ctrl.index)
        self.assertEqual(sp_ctrl.index, 0)

        # 3. RewindPicker
        r_rows = [RewindRow(1, "prompt 1", 1, 0, 100.0), RewindRow(2, "prompt 2", 2, 1, 101.0), RewindRow(3, "prompt 3", 3, 2, 102.0)]
        rp_arrow = RewindPicker(r_rows)
        rp_ctrl = RewindPicker(r_rows)
        rp_arrow.handle_key(Key(DOWN))
        rp_ctrl.handle_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(rp_arrow.index, rp_ctrl.index)
        self.assertEqual(rp_ctrl.index, 1)
        rp_arrow.handle_key(Key(UP))
        rp_ctrl.handle_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(rp_arrow.index, rp_ctrl.index)
        self.assertEqual(rp_ctrl.index, 0)

        # 4. LaunchPicker
        lp_arrow = LaunchPicker(LAUNCH_PRESETS[0])
        lp_ctrl = LaunchPicker(LAUNCH_PRESETS[0])
        lp_arrow.handle_key(Key(DOWN))
        lp_ctrl.handle_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(lp_arrow.index, lp_ctrl.index)
        self.assertEqual(lp_ctrl.index, 1)
        lp_arrow.handle_key(Key(UP))
        lp_ctrl.handle_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(lp_arrow.index, lp_ctrl.index)
        self.assertEqual(lp_ctrl.index, 0)

        # LaunchPicker preserves legacy modified-arrow navigation
        for mod in ("ctrl", "alt", "shift"):
            lp_mod = LaunchPicker(LAUNCH_PRESETS[1])
            lp_mod.handle_key(Key(DOWN, **{mod: True}))
            self.assertEqual(lp_mod.index, 2)
            lp_mod.handle_key(Key(UP, **{mod: True}))
            self.assertEqual(lp_mod.index, 1)

        # 5. AgentView - Ordinary roster
        app_arrow, _ = make_app()
        app_ctrl, _ = make_app()
        for a in (app_arrow, app_ctrl):
            a.roster = Roster()
            a.roster.apply("subagent.start", {"subagent_id": "sub1", "goal": "Sub1"}, 1.0)
            a.roster.apply("subagent.start", {"subagent_id": "sub2", "goal": "Sub2"}, 2.0)
            a.list_selected = MAIN_ID

        app_arrow._agent_list_key(Key(DOWN))
        app_ctrl._agent_list_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app_arrow.list_selected, app_ctrl.list_selected)
        self.assertEqual(app_ctrl.list_selected, "sub1")

        app_arrow._agent_list_key(Key(UP))
        app_ctrl._agent_list_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(app_arrow.list_selected, app_ctrl.list_selected)
        self.assertEqual(app_ctrl.list_selected, MAIN_ID)

        # 6. AgentView - DAG tree mode
        from test_tui_dag_tree import tree_app
        app_tree_arrow, _ = tree_app()
        app_tree_ctrl, _ = tree_app()
        app_tree_arrow._on_input(Key(DOWN))
        app_tree_ctrl._on_input(Key(DOWN))
        self.assertEqual(app_tree_arrow.tree_selected, app_tree_ctrl.tree_selected)

        app_tree_arrow._tree_key(Key(DOWN))
        app_tree_ctrl._tree_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app_tree_arrow.tree_selected, app_tree_ctrl.tree_selected)
        self.assertIsNotNone(app_tree_ctrl.tree_selected)

        app_tree_arrow._tree_key(Key(UP))
        app_tree_ctrl._tree_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(app_tree_arrow.tree_selected, app_tree_ctrl.tree_selected)

    def test_ctrl_np_history_skip_moves_match(self) -> None:
        """A2: HistorySearch skip oracle parity."""
        from omh.tui.history import HistorySearch

        entries = ["cmd 1", "cmd 2", "cmd 3", "cmd 4"]
        hs_arrow = HistorySearch(entries, "")
        hs_ctrl = HistorySearch(entries, "")

        self.assertEqual(hs_arrow.skip, 0)
        self.assertEqual(hs_ctrl.skip, 0)

        # Move forward/down (older)
        hs_arrow.handle_key(Key(DOWN))
        hs_ctrl.handle_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(hs_arrow.skip, hs_ctrl.skip)
        self.assertEqual(hs_ctrl.skip, 1)

        hs_arrow.handle_key(Key(DOWN))
        hs_ctrl.handle_key(Key(CHAR, "n", ctrl=True))
        self.assertEqual(hs_arrow.skip, hs_ctrl.skip)
        self.assertEqual(hs_ctrl.skip, 2)

        # Move backward/up (newer)
        hs_arrow.handle_key(Key(UP))
        hs_ctrl.handle_key(Key(CHAR, "p", ctrl=True))
        self.assertEqual(hs_arrow.skip, hs_ctrl.skip)
        self.assertEqual(hs_ctrl.skip, 1)

    def test_ctrl_np_boundary_keys_consumed(self) -> None:
        """A3: Boundary presses consumed without leaking to composer or toggling plan_folded."""
        from omh.tui.model_picker import ModelPicker, ModelRow
        from omh.tui.subagents import MAIN_ID, Roster

        app, _ = make_app()
        app.plan_folded = False
        m_rows = [ModelRow("m1", "p1", "Provider 1", True), ModelRow("m2", "p2", "Provider 2", False)]
        app.model_picker = ModelPicker(m_rows, current="m1")

        # Top boundary Ctrl+P
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(app.model_picker.index, 0)
        self.assertFalse(app.plan_folded)
        self.assertEqual(app.composer.text, "")

        # Bottom boundary Ctrl+N
        app._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app.model_picker.index, 1)
        app._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app.model_picker.index, 1)
        self.assertFalse(app.plan_folded)
        self.assertEqual(app.composer.text, "")

        # Agent roster boundary
        app.model_picker = None
        app.roster = Roster()
        app.roster.apply("subagent.start", {"subagent_id": "sub1", "goal": "Sub1"}, 1.0)
        app.list_selected = MAIN_ID
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(app.list_selected, MAIN_ID)
        self.assertFalse(app.plan_folded)

        app._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app.list_selected, "sub1")
        app._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app.list_selected, "sub1")
        self.assertFalse(app.plan_folded)

        # Agent tree boundary
        from test_tui_dag_tree import tree_app
        tree_a, _ = tree_app()
        tree_a._on_input(Key(DOWN))  # open tree
        # Move up to top boundary
        for _ in range(10):
            tree_a._on_input(Key(CHAR, "p", ctrl=True))
        top_node = tree_a.tree_selected
        self.assertIsNotNone(top_node)
        tree_a._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(tree_a.tree_selected, top_node)
        self.assertFalse(tree_a.plan_folded)

        # Move to end
        for _ in range(50):
            tree_a._on_input(Key(CHAR, "n", ctrl=True))
        end_node = tree_a.tree_selected
        tree_a._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(tree_a.tree_selected, end_node)
        self.assertFalse(tree_a.plan_folded)

    def test_no_list_ctrl_p_folds_plan(self) -> None:
        """A4: No-list Ctrl+P toggles plan_folded; Ctrl+N ignored; open menu yields to navigation."""
        from omh.tui.panels import HudSnapshot
        from test_tui_panels import hud_payload

        plan = [{"text": f"Step {n}", "state": "done" if n < 5 else "active" if n == 5 else "pending"} for n in range(7)]
        app, _ = make_app(rows=30, cols=80)
        app.hud = HudSnapshot(app.stored_id, hud_payload(plan), 0.0)
        drawn(app)

        self.assertFalse(app.plan_folded)
        # No list: Ctrl+P toggles plan_folded
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertTrue(app.plan_folded)
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertFalse(app.plan_folded)

        # Ctrl+N does nothing to plan_folded or composer text
        app._on_input(Key(CHAR, "n", ctrl=True))
        self.assertFalse(app.plan_folded)
        self.assertEqual(app.composer.text, "")

    def test_ctrl_np_menu_moves(self) -> None:
        """A4: Completion menu moves with Ctrl+N/Ctrl+P and takes precedence over plan fold."""
        from omh.tui.panels import HudSnapshot
        from omh.tui.app import PathItem
        from test_tui_panels import hud_payload

        plan = [{"text": f"Step {n}", "state": "done" if n < 5 else "active" if n == 5 else "pending"} for n in range(7)]
        # 1. Slash command menu
        app, _ = make_app(rows=30, cols=80)
        app.hud = HudSnapshot(app.stored_id, hud_payload(plan), 0.0)
        type_text(app, "/")
        drawn(app)
        self.assertTrue(bool(app._menu_rows()))
        initial_index = app.menu_index

        # Ctrl+N moves menu down
        app._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app.menu_index, initial_index + 1)
        self.assertFalse(app.plan_folded)

        # Ctrl+P moves menu up and DOES NOT fold plan
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(app.menu_index, initial_index)
        self.assertFalse(app.plan_folded)

        # 2. Path completion menu (@)
        app_path, _ = make_app()
        app_path.hud = HudSnapshot(app_path.stored_id, hud_payload([{"text": "Ship it", "state": "active"}]), 0.0)
        app_path.path_items = [PathItem("f1.txt", "f1.txt", "file"), PathItem("f2.txt", "f2.txt", "file")]
        self.assertTrue(bool(app_path._menu_rows()))
        self.assertEqual(app_path.menu_index, 0)

        app_path._on_input(Key(CHAR, "n", ctrl=True))
        self.assertEqual(app_path.menu_index, 1)
        self.assertFalse(app_path.plan_folded)

        app_path._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(app_path.menu_index, 0)
        self.assertFalse(app_path.plan_folded)

    def test_plain_np_types_into_filter(self) -> None:
        """A5: Plain n and p type into picker filter / composer without triggering navigation."""
        from omh.tui.model_picker import ModelPicker, ModelRow

        m_rows = [ModelRow("m1", "p1", "Provider 1", True), ModelRow("m2", "p2", "Provider 2", False)]
        picker = ModelPicker(m_rows, current="m1")

        picker.handle_key(Key(CHAR, "n"))
        self.assertEqual(picker.query, "n")
        self.assertEqual(picker.index, 0)

        picker.handle_key(Key(CHAR, "p"))
        self.assertEqual(picker.query, "np")
        self.assertEqual(picker.index, 0)

        # In composer
        app, _ = make_app()
        app._on_input(Key(CHAR, "n"))
        app._on_input(Key(CHAR, "p"))
        self.assertEqual(app.composer.text, "np")

    def test_ctrl_jk_step_matches_arrows(self) -> None:
        """B1: Across all pickers, Ctrl+J and Ctrl+K step like Down and Up."""
        from omh.tui.launch_picker import LAUNCH_PRESETS, LaunchPicker
        from omh.tui.model_picker import ModelPicker, ModelRow
        from omh.tui.rewind_picker import RewindPicker, RewindRow
        from omh.tui.session_picker import SessionPicker, SessionRow
        from omh.tui.history import HistorySearch
        from omh.tui.subagents import MAIN_ID, Roster

        # 1. ModelPicker
        m_rows = [ModelRow("m1", "p1", "Provider 1", True), ModelRow("m2", "p2", "Provider 2", False), ModelRow("m3", "p3", "Provider 3", False)]
        mp_arrow = ModelPicker(m_rows, current="m1")
        mp_ctrl = ModelPicker(m_rows, current="m1")
        mp_arrow.handle_key(Key(DOWN))
        mp_ctrl.handle_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(mp_arrow.index, mp_ctrl.index)
        self.assertEqual(mp_ctrl.index, 1)
        mp_arrow.handle_key(Key(UP))
        mp_ctrl.handle_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(mp_arrow.index, mp_ctrl.index)
        self.assertEqual(mp_ctrl.index, 0)

        # 2. SessionPicker
        s_rows = [SessionRow("s1", "Session 1", "preview 1", 100.0, 5), SessionRow("s2", "Session 2", "preview 2", 90.0, 3), SessionRow("s3", "Session 3", "preview 3", 80.0, 1)]
        sp_arrow = SessionPicker(s_rows, current="s1")
        sp_ctrl = SessionPicker(s_rows, current="s1")
        sp_arrow.handle_key(Key(DOWN))
        sp_ctrl.handle_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(sp_arrow.index, sp_ctrl.index)
        self.assertEqual(sp_ctrl.index, 1)
        sp_arrow.handle_key(Key(UP))
        sp_ctrl.handle_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(sp_arrow.index, sp_ctrl.index)
        self.assertEqual(sp_ctrl.index, 0)

        # 3. RewindPicker
        r_rows = [RewindRow(1, "prompt 1", 1, 0, 100.0), RewindRow(2, "prompt 2", 2, 1, 101.0), RewindRow(3, "prompt 3", 3, 2, 102.0)]
        rp_arrow = RewindPicker(r_rows)
        rp_ctrl = RewindPicker(r_rows)
        rp_arrow.handle_key(Key(DOWN))
        rp_ctrl.handle_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(rp_arrow.index, rp_ctrl.index)
        self.assertEqual(rp_ctrl.index, 1)
        rp_arrow.handle_key(Key(UP))
        rp_ctrl.handle_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(rp_arrow.index, rp_ctrl.index)
        self.assertEqual(rp_ctrl.index, 0)

        # 4. LaunchPicker
        lp_arrow = LaunchPicker(LAUNCH_PRESETS[0])
        lp_ctrl = LaunchPicker(LAUNCH_PRESETS[0])
        lp_arrow.handle_key(Key(DOWN))
        lp_ctrl.handle_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(lp_arrow.index, lp_ctrl.index)
        self.assertEqual(lp_ctrl.index, 1)
        lp_arrow.handle_key(Key(UP))
        lp_ctrl.handle_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(lp_arrow.index, lp_ctrl.index)
        self.assertEqual(lp_ctrl.index, 0)

        # 5. HistorySearch
        entries = ["cmd 1", "cmd 2", "cmd 3", "cmd 4"]
        hs_arrow = HistorySearch(entries, "")
        hs_ctrl = HistorySearch(entries, "")
        hs_arrow.handle_key(Key(DOWN))
        hs_ctrl.handle_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(hs_arrow.skip, hs_ctrl.skip)
        self.assertEqual(hs_ctrl.skip, 1)
        hs_arrow.handle_key(Key(UP))
        hs_ctrl.handle_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(hs_arrow.skip, hs_ctrl.skip)
        self.assertEqual(hs_ctrl.skip, 0)

        # 6. AgentView - Ordinary roster
        app_arrow, _ = make_app()
        app_ctrl, _ = make_app()
        for a in (app_arrow, app_ctrl):
            a.roster = Roster()
            a.roster.apply("subagent.start", {"subagent_id": "sub1", "goal": "Sub1"}, 1.0)
            a.roster.apply("subagent.start", {"subagent_id": "sub2", "goal": "Sub2"}, 2.0)
            a.list_selected = MAIN_ID

        app_arrow._agent_list_key(Key(DOWN))
        app_ctrl._agent_list_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app_arrow.list_selected, app_ctrl.list_selected)
        self.assertEqual(app_ctrl.list_selected, "sub1")

        app_arrow._agent_list_key(Key(UP))
        app_ctrl._agent_list_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(app_arrow.list_selected, app_ctrl.list_selected)
        self.assertEqual(app_ctrl.list_selected, MAIN_ID)

        # 7. AgentView - DAG tree mode
        from test_tui_dag_tree import tree_app
        app_tree_arrow, _ = tree_app()
        app_tree_ctrl, _ = tree_app()
        app_tree_arrow._on_input(Key(DOWN))
        app_tree_ctrl._on_input(Key(DOWN))
        self.assertEqual(app_tree_arrow.tree_selected, app_tree_ctrl.tree_selected)

        app_tree_arrow._tree_key(Key(DOWN))
        app_tree_ctrl._tree_key(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app_tree_arrow.tree_selected, app_tree_ctrl.tree_selected)
        self.assertIsNotNone(app_tree_ctrl.tree_selected)

        app_tree_arrow._tree_key(Key(UP))
        app_tree_ctrl._tree_key(Key(CHAR, "k", ctrl=True))
        self.assertEqual(app_tree_arrow.tree_selected, app_tree_ctrl.tree_selected)

    def test_ctrl_jk_menu_moves(self) -> None:
        """B2: Slash and @path completion menus move with Ctrl+J/Ctrl+K matching Down/Up."""
        from omh.tui.app import PathItem

        # 1. Slash command menu
        app, _ = make_app(rows=30, cols=80)
        type_text(app, "/")
        drawn(app)
        self.assertTrue(bool(app._menu_rows()))
        initial_index = app.menu_index

        app._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app.menu_index, initial_index + 1)

        app._on_input(Key(CHAR, "k", ctrl=True))
        self.assertEqual(app.menu_index, initial_index)

        # 2. Path completion menu (@)
        app_path, _ = make_app()
        app_path.path_items = [PathItem("f1.txt", "f1.txt", "file"), PathItem("f2.txt", "f2.txt", "file")]
        self.assertTrue(bool(app_path._menu_rows()))
        self.assertEqual(app_path.menu_index, 0)

        app_path._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app_path.menu_index, 1)

        app_path._on_input(Key(CHAR, "k", ctrl=True))
        self.assertEqual(app_path.menu_index, 0)

    def test_no_list_ctrl_j_inserts_newline_and_steers(self) -> None:
        """B3: No-list Ctrl+J preserves byte-identical newline addition and send-now / steer precedence."""
        from omh.tui.app import QueuedLine

        app, _ = make_app()
        type_text(app, "hello")
        app._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app.composer.text, "hello\n")

        # Steer queue precedence on empty composer while turn runs
        app_turn, _ = make_app()
        app_turn.transcript.running = True  # make _busy() True
        app_turn.queued.append(QueuedLine("steer me"))
        steered = []
        app_turn._steer = lambda text, line: steered.append(text)
        app_turn._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(steered, ["steer me"])
        self.assertEqual(len(app_turn.queued), 0)

    def test_no_list_ctrl_k_deletes_to_eol(self) -> None:
        """B4: No-list Ctrl+K preserves byte-identical delete-to-EOL and image removal."""
        app, _ = make_app()
        type_text(app, "hello world")
        # Move caret to index 5 ("hello| world")
        app.composer.caret = 5
        app._on_input(Key(CHAR, "k", ctrl=True))
        self.assertEqual(app.composer.text, "hello")

    def test_legacy_decode_preserved(self) -> None:
        """B5: Raw 0x0a and 0x0b decode to Ctrl+J and Ctrl+K, STEER_FALLBACK_KEY equality holds."""
        from omh.tui.app import STEER_FALLBACK_KEY
        from omh.tui.keys import KeyDecoder

        decoder = KeyDecoder()
        k_0a = decoder.feed(b"\x0a")
        k_0b = decoder.feed(b"\x0b")
        self.assertEqual(k_0a, [Key(CHAR, "j", ctrl=True)])
        self.assertEqual(k_0b, [Key(CHAR, "k", ctrl=True)])
        self.assertEqual(STEER_FALLBACK_KEY, Key(CHAR, "j", ctrl=True))

        # Unfocused 0x0a feeds into app as newline
        app, _ = make_app()
        type_text(app, "line1")
        app._on_input(k_0a[0])
        self.assertEqual(app.composer.text, "line1\n")

    def test_menu_precedence_over_composer_and_escape_hatches(self) -> None:
        """B6: Menu open navigates menu instead of editing composer; Alt+Enter / Shift+Enter insert newline."""
        app, _ = make_app(rows=30, cols=80)
        type_text(app, "/")
        drawn(app)
        self.assertTrue(bool(app._menu_rows()))
        init_index = app.menu_index

        # Ctrl+J steps menu, doesn't add newline to composer
        app._on_input(Key(CHAR, "j", ctrl=True))
        self.assertEqual(app.menu_index, init_index + 1)
        self.assertEqual(app.composer.text, "/")

        # Ctrl+K steps menu, doesn't delete to EOL
        app._on_input(Key(CHAR, "k", ctrl=True))
        self.assertEqual(app.menu_index, init_index)
        self.assertEqual(app.composer.text, "/")

        # Alt+Enter and Shift+Enter are guaranteed newline escape hatches
        app._on_input(Key(ENTER, alt=True))
        self.assertEqual(app.composer.text, "/\n")

        app._on_input(Key(ENTER, shift=True))
        self.assertEqual(app.composer.text, "/\n\n")

    def test_modifier_purity_plain_jk_and_modified(self) -> None:
        """B7: Exact modifier gate: plain j/k type into filters; alt/shift chords return 0 step."""
        from omh.tui.keys import list_nav_step
        from omh.tui.model_picker import ModelPicker, ModelRow

        # Plain j and k in picker filter
        m_rows = [ModelRow("m1", "p1", "Provider 1", True), ModelRow("m2", "p2", "Provider 2", False)]
        picker = ModelPicker(m_rows, current="m1")
        picker.handle_key(Key(CHAR, "j"))
        self.assertEqual(picker.query, "j")
        self.assertEqual(picker.index, 0)
        picker.handle_key(Key(CHAR, "k"))
        self.assertEqual(picker.query, "jk")
        self.assertEqual(picker.index, 0)

        # Plain j and k in composer
        app, _ = make_app()
        app._on_input(Key(CHAR, "j"))
        app._on_input(Key(CHAR, "k"))
        self.assertEqual(app.composer.text, "jk")

        # Helper rejects plain j/k, alt+j/k, shift+j/k, ctrl+alt+j, ctrl+shift+j, reported_shift
        self.assertEqual(list_nav_step(Key(CHAR, "j")), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "k")), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "j", alt=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "k", alt=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "j", shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "k", shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "j", ctrl=True, alt=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "k", ctrl=True, shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "j", ctrl=True, reported_shift=True)), 0)
        self.assertEqual(list_nav_step(Key(CHAR, "k", ctrl=True, reported_shift=True)), 0)

    def test_menu_open_protocol_ctrl_shift_j_inserts_newline(self) -> None:
        """Decision pin: a Shift-reported Ctrl+J does not step an open menu; it falls through to a newline.

        Legacy 0x0A still steps the menu because a legacy byte cannot carry Shift.
        """
        from omh.tui.keys import KeyDecoder

        app, _ = make_app(rows=30, cols=80)
        type_text(app, "/")
        drawn(app)
        self.assertTrue(bool(app._menu_rows()))
        init_index = app.menu_index
        (event,) = KeyDecoder().feed(b"\x1b[106;6u")
        self.assertTrue(event.reported_shift)
        app._on_input(event)
        self.assertEqual(app.menu_index, init_index)
        self.assertEqual(app.composer.text, "/\n")

    def test_protocol_keys_navigation_and_reported_shift_rejection(self) -> None:
        """Protocol-fed CSI-u and modifyOtherKeys navigation vs reported Shift rejection."""
        from omh.tui.keys import KeyDecoder
        from omh.tui.model_picker import ModelPicker, ModelRow

        m_rows = [
            ModelRow("m1", "p1", "Provider 1", True),
            ModelRow("m2", "p2", "Provider 2", False),
            ModelRow("m3", "p3", "Provider 3", False),
        ]

        # Modifier codes:
        # 5 = 1 + 4 (Ctrl)
        # 6 = 1 + 1 (Shift) + 4 (Ctrl) -> Ctrl+Shift
        # 7 = 1 + 2 (Alt) + 4 (Ctrl) -> Ctrl+Alt
        # 8 = 1 + 1 + 2 + 4 -> Ctrl+Alt+Shift

        for prefix, template in (
            ("csi_u", lambda code, mod: f"\x1b[{code};{mod}u".encode()),
            ("modify_other_keys", lambda code, mod: f"\x1b[27;{mod};{code}~".encode()),
        ):
            # Unshifted Ctrl+n / Ctrl+j navigates down
            for code in (ord("n"), ord("j")):
                decoder = KeyDecoder()
                events = decoder.feed(template(code, 5))
                self.assertEqual(len(events), 1)
                event = events[0]
                self.assertEqual(list_nav_step(event), 1)
                picker = ModelPicker(m_rows, current="m1")
                picker.handle_key(event)
                self.assertEqual(picker.index, 1)

            # Unshifted Ctrl+p / Ctrl+k navigates up
            for code in (ord("p"), ord("k")):
                decoder = KeyDecoder()
                events = decoder.feed(template(code, 5))
                self.assertEqual(len(events), 1)
                event = events[0]
                self.assertEqual(list_nav_step(event), -1)
                picker = ModelPicker(m_rows, current="m1")
                picker.index = 2
                picker.handle_key(event)
                self.assertEqual(picker.index, 1)

            # Modified: Ctrl+Shift (mod 6), Ctrl+Alt (mod 7), Ctrl+Alt+Shift (mod 8)
            # must return 0 and NOT navigate picker
            for key_char, code in (("n", ord("n")), ("p", ord("p")), ("j", ord("j")), ("k", ord("k"))):
                for mod in (6, 7, 8):
                    decoder = KeyDecoder()
                    events = decoder.feed(template(code, mod))
                    self.assertEqual(len(events), 1)
                    event = events[0]
                    self.assertEqual(
                        list_nav_step(event),
                        0,
                        f"{prefix} char={key_char} mod={mod} must reject navigation",
                    )
                    picker = ModelPicker(m_rows, current="m1")
                    picker.index = 1  # Interior row: neither direction can hide behind boundary clamping.
                    picker.handle_key(event)
                    self.assertEqual(
                        picker.index,
                        1,
                        f"{prefix} char={key_char} mod={mod} must not change picker index",
                    )


class PendingCharSearchShortcutTests(unittest.TestCase):
    def pending_app(self, command: str) -> tuple[App, RecordingClient]:
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, "aXbXcXdXeXfXgX")
        app._on_input(Key(ESCAPE))
        app.composer.caret = 0
        type_text(app, command)
        self.assertTrue(app.composer.pending)
        self.assertEqual(client.calls, [])
        return app, client

    def test_pending_search_consumes_global_shortcuts_without_stale_edits(self) -> None:
        for search in ("f", "F", "t", "T"):
            for prefix in ("", "2", "2d", "2d3", "2c3", "2y3"):
                for event in (Key(CHAR, "t", ctrl=True), Key(TAB, shift=True),
                              Key(CHAR, "o", ctrl=True), Key(CHAR, "x", ctrl=True), Key(ENTER)):
                    with self.subTest(search=search, prefix=prefix, event=event):
                        app, client = self.pending_app(prefix + search)
                        before = (app.composer.text, app.composer.caret, app.composer.normal,
                                  app.composer._register, app.composer._last_search)
                        app._on_input(event)
                        self.assertEqual(client.calls, [])
                        self.assertEqual((app.composer._count, app.composer._operator, app.composer._op_count,
                                          app.composer._prefix, app.composer.leader), ("", "", "", "", False))
                        self.assertFalse(app.composer.pending)
                        self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal,
                                          app.composer._register, app.composer._last_search), before)
                        self.assertIsNone(app.pager)
                        self.assertIsNone(app.picker)
                        app._on_input(Key(CHAR, "X"))  # Fresh backward delete at column zero is a no-op.
                        self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal), before[:3])
                        self.assertFalse(app.composer.pending)
                        self.assertEqual(client.calls, [])

    def test_ctrl_c_and_esc_cancel_a_pending_search_and_do_nothing_else(self) -> None:
        # As in Vim: the key drops the half-typed search; the draft stays, nothing is sent or interrupted, and Esc
        # arms no rewind. The next Ctrl+C is an ordinary one again.
        for search in ("f", "F", "t", "T"):
            for event in (Key(CHAR, "c", ctrl=True), Key(ESCAPE)):
                with self.subTest(search=search, event=event):
                    app, client = self.pending_app("2d3" + search)
                    app._on_input(event)
                    self.assertFalse(app.composer.pending)
                    self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal),
                                     ("aXbXcXdXeXfXgX", 0, True))
                    self.assertIsNone(app.escape_armed)
                    self.assertIsNone(app.exit_code)
                    self.assertEqual(client.calls, [])
                    app._on_input(Key(CHAR, "X"))  # no stale target: a backward delete at column zero
                    self.assertEqual(app.composer.text, "aXbXcXdXeXfXgX")

    def test_pending_search_preserves_paste_and_shared_undo_redo(self) -> None:
        for event in (Paste("!"), Key(CHAR, "_", ctrl=True), Key(CHAR, "-", ctrl=True),
                      Key(CHAR, "y", ctrl=True), Key(CHAR, "r", ctrl=True)):
            with self.subTest(event=event):
                app, client = self.pending_app("2d3f")
                if isinstance(event, Key) and event.char in ("y", "r"):
                    app.composer._drop_pending()
                    app._on_input(Key(CHAR, "_", ctrl=True))
                    type_text(app, "2d3f")
                app._on_input(event)
                self.assertFalse(app.composer.pending)
                expected = "!aXbXcXdXeXfXgX" if isinstance(event, Paste) else (
                    "" if event.char in ("_", "-") else "aXbXcXdXeXfXgX"
                )
                self.assertEqual(app.composer.text, expected)
                self.assertTrue(app.composer.normal)
                self.assertEqual(client.calls, [])

    def test_pending_search_drops_before_path_paste_dispatch(self) -> None:
        app, client = self.pending_app("2df")
        app._on_input(Paste("/tmp/search-target.png"))
        self.assertFalse(app.composer.pending)
        self.assertEqual(client.calls, [("input.detect_drop", {
            "session_id": app.sid, "text": "/tmp/search-target.png",
        })])
        app._on_input(Key(CHAR, "X"))
        self.assertEqual((app.composer.text, app.composer.caret), ("aXbXcXdXeXfXgX", 0))

    def test_front_and_waiting_pickers_keep_search_input_precedence(self) -> None:
        from omh.tui.session_picker import SessionPicker, SessionRow

        for waiting in (False, True):
            with self.subTest(waiting=waiting):
                app, client = self.pending_app("2df")
                app.picker = SessionPicker([SessionRow("s1", "Session 1", "", 100.0, 1)], current=app.stored_id)
                app.picker.waiting = waiting
                original = app._picker_key

                def receive(event: Key | Paste) -> None:
                    self.assertFalse(app.composer.pending)
                    original(event)

                with patch.object(app, "_picker_key", side_effect=receive) as owned:
                    app._on_input(Key(DOWN))
                    owned.assert_called_once_with(Key(DOWN))
                self.assertFalse(app.composer.pending)
                self.assertFalse(app.picker.waiting)
                self.assertEqual(client.calls, [])

    def test_pending_g_owns_followers_other_commands_keep_global_shortcuts(self) -> None:
        for command in ("d", "2d", "g", "2g", "2d3g", "r", "di"):
            for event in (Key(CHAR, "t", ctrl=True), Key(TAB, shift=True)):
                with self.subTest(command=command, event=event):
                    app, client = self.pending_app(command)
                    before = app.composer.text, app.composer.caret, app.composer._register
                    app._on_input(event)
                    if command.endswith(("g", "r")):
                        # RS-1/WM-contract: g owns invalid followers, including
                        # modified global keys, and cancels the entire grammar.
                        self.assertEqual(client.calls, [])
                        self.assertFalse(app.composer.pending)
                        self.assertEqual((app.composer.text, app.composer.caret, app.composer._register), before)
                        self.assertFalse(app.plan_mode)
                    else:
                        self.assertEqual([method for method, _params in client.calls], ["config.set"])
                        self.assertTrue(app.composer.pending)


class LeaderShortcutTests(unittest.TestCase):
    def normal_app(self, text: str = "draft") -> tuple[App, RecordingClient]:
        app, client = make_app()
        app.composer.set_vim(True)
        type_text(app, text)
        app._on_input(Key(ESCAPE))
        return app, client

    def arm(self, app: App) -> None:
        app._on_input(Key(CHAR, " "))
        self.assertTrue(app.composer.leader)

    def test_leader_escape_discards_confirmation_without_changing_the_draft(self) -> None:
        from test_tui_rewind import Clock

        for text, busy, kind in (("draft", False, "clear"), ("", True, "interrupt"), ("", False, "rewind")):
            for prior in ("none", "current", "expired"):
                with self.subTest(kind=kind, prior=prior):
                    clock = Clock()
                    app, client = make_app(busy=busy, clock=clock)
                    app.composer.set_vim(True)
                    type_text(app, text)
                    app._on_input(Key(ESCAPE))  # INSERT -> NORMAL is not a confirmation.
                    self.assertIsNone(app.escape_armed)
                    if prior != "none":
                        app._on_input(Key(ESCAPE))
                        self.assertEqual(app.escape_armed, (kind, clock.now))
                        if prior == "expired":
                            clock.now += 1.0
                    armed = app.escape_armed
                    before = (app.composer.text, app.composer.caret, app.composer.normal, list(app.composer.history))
                    self.arm(app)
                    self.assertEqual(app.escape_armed, armed)  # Space alone must not reset it.
                    self.assertTrue(app.composer.pending)
                    app._on_input(Key(ESCAPE))
                    self.assertIsNone(app.escape_armed)
                    self.assertFalse(app.composer.leader)
                    self.assertFalse(app.composer.pending)
                    self.assertEqual(
                        (app.composer.text, app.composer.caret, app.composer.normal, app.composer.history), before,
                    )
                    self.assertEqual(client.calls, [])
                    self.assertIsNone(app.rewind_picker)

    def test_modified_escape_cancels_leader_before_modifier_filtering(self) -> None:
        from test_tui_rewind import Clock

        for modifier in ("ctrl", "alt", "shift", "reported_shift"):
            for text, busy, kind in (("draft", False, "clear"), ("", True, "interrupt"), ("", False, "rewind")):
                with self.subTest(modifier=modifier, kind=kind):
                    clock = Clock()
                    app, client = make_app(busy=busy, clock=clock)
                    app.composer.set_vim(True)
                    type_text(app, text)
                    app._on_input(Key(ESCAPE))
                    app._on_input(Key(ESCAPE))
                    self.assertEqual(app.escape_armed, (kind, clock.now))
                    before = (app.composer.text, app.composer.caret, app.composer.normal, list(app.composer.history))
                    self.arm(app)
                    app._on_input(Key(ESCAPE, **{modifier: True}))
                    self.assertIsNone(app.escape_armed)
                    self.assertFalse(app.composer.pending)
                    self.assertEqual(
                        (app.composer.text, app.composer.caret, app.composer.normal, app.composer.history), before,
                    )
                    self.assertEqual(client.calls, [])
                    self.assertIsNone(app.rewind_picker)

    def test_non_escape_leader_followers_preserve_confirmation(self) -> None:
        for event in (Key(CHAR, "?"), Key(CHAR, "m", ctrl=True), Key(DOWN)):
            with self.subTest(event=event):
                app, client = self.normal_app()
                app._on_input(Key(ESCAPE))
                armed = app.escape_armed
                self.assertIsNotNone(armed)
                before = (app.composer.text, app.composer.caret, app.composer.normal, list(app.composer.history))
                self.arm(app)
                self.assertEqual(app.escape_armed, armed)
                app._on_input(event)
                self.assertEqual(app.escape_armed, armed)
                self.assertFalse(app.composer.pending)
                self.assertEqual(
                    (app.composer.text, app.composer.caret, app.composer.normal, app.composer.history), before,
                )
                self.assertEqual(client.calls, [])

    def test_leader_s_opens_sessions(self) -> None:
        app, client = self.normal_app()
        self.arm(app)
        app._on_input(Key(CHAR, "s"))
        self.assertEqual(client.named("session.list"), [{"limit": 50}])
        self.assertFalse(app.composer.leader)
        self.assertEqual(app.composer.text, "draft")

    def test_leader_b_opens_bots(self) -> None:
        app, _ = self.normal_app()
        with patch.object(app, "_bots") as bots:
            self.arm(app)
            app._on_input(Key(CHAR, "b"))
            bots.assert_called_once_with("")
        self.assertFalse(app.composer.leader)

    def test_leader_p_toggles_plan_fold(self) -> None:
        from omh.tui.panels import HudSnapshot
        from test_tui_panels import hud_payload

        app, _ = self.normal_app()
        app.hud = HudSnapshot(app.stored_id, hud_payload([{"text": "Ship it", "state": "active"}]), 0.0)
        drawn(app)
        before = app.plan_folded
        for folded in (not before, before):
            self.arm(app)
            app._on_input(Key(CHAR, "p"))
            self.assertEqual(app.plan_folded, folded)
            self.assertFalse(app.composer.leader)

    def test_leader_p_without_visible_plan_is_consumed(self) -> None:
        app, _ = self.normal_app()
        before = app.plan_folded
        self.arm(app)
        self.assertTrue(app._plan_fold_key(Key(CHAR, "p")))
        self.assertEqual(app.plan_folded, before)
        self.assertFalse(app.composer.leader)
        self.assertEqual(app.composer.text, "draft")

    def test_leader_r_opens_search_in_normal_mode(self) -> None:
        for char in ("r", "/"):
            with self.subTest(char=char):
                app, client = self.normal_app()
                self.arm(app)
                app._on_input(Key(CHAR, char))
                self.assertIsNotNone(app.search)
                assert app.search is not None
                self.assertEqual(app.search.original, "draft")
                self.assertTrue(app.composer.normal)
                self.assertFalse(app.composer.leader)
                self.assertEqual(client.calls, [])

    def test_leader_m_cycles_mode(self) -> None:
        leader, leader_client = self.normal_app()
        control, control_client = self.normal_app()
        self.arm(leader)
        leader._on_input(Key(CHAR, "m"))
        from omh.tui.keys import TAB
        control._on_input(Key(TAB, shift=True))
        self.assertEqual(leader_client.calls, control_client.calls)
        self.assertEqual(leader_client.calls, [("config.set", {"key": "yolo", "session_id": leader.sid, "value": "on"})])
        self.assertFalse(leader.composer.leader)

    def test_leader_t_steps_effort(self) -> None:
        from omh.tui.modes import EFFORT_CYCLE

        app, client = self.normal_app()
        app.effort = EFFORT_CYCLE[0]
        self.arm(app)
        app._on_input(Key(CHAR, "t"))
        self.assertEqual(client.named("config.set"), [{"key": "reasoning", "session_id": app.sid, "value": EFFORT_CYCLE[1]}])
        self.assertFalse(app.composer.leader)

    def test_active_picker_preempts_leader_shortcuts(self) -> None:
        from omh.tui.history import HistorySearch

        for char in "sbpr/mt":
            with self.subTest(char=char):
                app, client = self.normal_app()
                self.arm(app)
                app.search = HistorySearch([], "")
                with patch.object(app, "_leader_key") as leader:
                    app._on_input(Key(CHAR, char))
                    leader.assert_not_called()
                self.assertIsNotNone(app.search)
                self.assertEqual(client.calls, [])

    def picker_fixture(self, app: App, kind: str) -> object:
        from omh.tui.history import HistorySearch
        from omh.tui.launch_picker import LAUNCH_PRESETS, LaunchPicker
        from omh.tui.model_picker import ModelPicker, ModelRow
        from omh.tui.rewind_picker import RewindPicker, RewindRow
        from omh.tui.session_picker import SessionPicker, SessionRow

        pickers = {
            "launch_picker": lambda: LaunchPicker(LAUNCH_PRESETS[0]),
            "picker": lambda: SessionPicker([SessionRow("s1", "Session 1", "", 100.0, 1)], current=app.stored_id),
            "search": lambda: HistorySearch(["earlier prompt"], app.composer.text),
            "rewind_picker": lambda: RewindPicker([RewindRow(1, "earlier prompt", 1, 0, 100.0)]),
            "model_picker": lambda: ModelPicker([ModelRow("m1", "p1", "Provider 1", True)], current="m1"),
        }
        picker = pickers[kind]()
        # Explicit assignments: the CI sharding inventory rejects non-literal setattr.
        if kind == "launch_picker":
            app.launch_picker = picker
        elif kind == "picker":
            app.picker = picker
        elif kind == "search":
            app.search = picker
        elif kind == "rewind_picker":
            app.rewind_picker = picker
        else:
            app.model_picker = picker
        return picker

    def sessions_answer(self, app: App, request_id: int) -> None:
        from omh.tui.gateway import Response

        app._on_response(Response(request_id, {"sessions": [
            {"id": "s1", "title": "Session 1", "preview": "", "started_at": 100.0, "message_count": 1},
        ]}, None))

    def waiting_picker(self) -> tuple[App, RecordingClient]:
        app, client = self.normal_app()
        self.arm(app)
        app._on_input(Key(CHAR, "s"))
        request_id = len(client.calls)
        type_text(app, "i!")
        app._on_input(Key(ESCAPE))
        self.sessions_answer(app, request_id)
        self.assertIsNotNone(app.picker)
        self.assertTrue(app.picker.waiting)
        self.assertIsNone(app._front_picker())
        return app, client

    def assert_fresh_mode_chord(self, app: App, client: RecordingClient) -> None:
        before = len(client.named("config.set"))
        app._on_input(Key(CHAR, "m"))
        self.assertEqual(len(client.named("config.set")), before)
        self.arm(app)
        app._on_input(Key(CHAR, "m"))
        self.assertEqual(client.named("config.set")[before:], [
            {"key": "yolo", "session_id": app.sid, "value": "on"},
        ])

    def test_delayed_session_answer_dismissal_cancels_rearmed_leader(self) -> None:
        app, client = self.normal_app()
        before = (app.composer.text, app.composer.caret, app.composer.normal)
        self.arm(app)
        app._on_input(Key(CHAR, "s"))
        self.arm(app)  # the list is in flight, so the composer still has the keys
        self.sessions_answer(app, len(client.calls))
        self.assertIsNotNone(app.picker)
        self.assertFalse(app.picker.waiting)
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.picker)
        self.assertFalse(app.composer.leader)
        self.assertFalse(app.composer.pending)
        self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal), before)
        self.assert_fresh_mode_chord(app, client)
        self.assertEqual(client.named("session.list"), [{"limit": 50}])

    def test_all_front_pickers_clear_every_pending_normal_command(self) -> None:
        for kind in ("launch_picker", "picker", "search", "rewind_picker", "model_picker"):
            for pending in (" ", "3", "d", "d2", "g", "r"):
                with self.subTest(kind=kind, pending=pending):
                    app, client = self.normal_app()
                    type_text(app, pending)
                    self.assertTrue(app.composer.pending)
                    before = (app.composer.text, app.composer.caret, app.composer.normal)
                    self.picker_fixture(app, kind)
                    app._on_input(Key(ESCAPE))
                    self.assertIsNone(getattr(app, kind))
                    self.assertFalse(app.composer.leader)
                    self.assertFalse(app.composer.pending)
                    self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal), before)
                    self.assert_fresh_mode_chord(app, client)

    def test_front_picker_display_early_returns_clear_pending(self) -> None:
        for kind in ("launch_picker", "picker", "search", "rewind_picker", "model_picker"):
            for char in ("l", "o"):
                with self.subTest(kind=kind, char=char):
                    app, client = self.normal_app()
                    self.arm(app)
                    picker = self.picker_fixture(app, kind)
                    app._on_input(Key(CHAR, char, ctrl=True))
                    self.assertFalse(app.composer.pending)
                    self.assertIs(getattr(app, kind), picker)
                    self.assertEqual(client.calls, [])
                    if app.pager is not None:
                        app._on_input(Key(CHAR, "q"))
                    app._on_input(Key(ESCAPE))
                    self.assert_fresh_mode_chord(app, client)

    def test_front_picker_events_are_delivered_once_after_reset(self) -> None:
        for kind, handler in (("launch_picker", "_launch_picker_key"), ("picker", "_picker_key"),
                              ("search", "_search_key"), ("rewind_picker", "_rewind_picker_key"),
                              ("model_picker", "_model_picker_key")):
            for event in (Key(DOWN), Key(CHAR, "m"), Key(CHAR, "m", alt=True), Paste("filter")):
                with self.subTest(kind=kind, event=event):
                    app, client = self.normal_app()
                    self.arm(app)
                    self.picker_fixture(app, kind)
                    original = getattr(app, handler)

                    def receive(event: Key | Paste) -> None:
                        self.assertFalse(app.composer.pending)
                        original(event)

                    with patch.object(app, handler, side_effect=receive) as owned:
                        app._on_input(event)
                        owned.assert_called_once_with(event)
                    self.assertFalse(app.composer.pending)
                    self.assertEqual(client.calls, [])

    def test_waiting_session_acquisition_clears_leader_before_same_event(self) -> None:
        for event in (Key(UP), Key(DOWN), Key(ESCAPE), Key(CHAR, "c", ctrl=True)):
            with self.subTest(event=event):
                app, client = self.waiting_picker()
                before = (app.composer.text, app.composer.caret, app.composer.normal)
                self.arm(app)
                original = app._picker_key

                def receive(event: Key | Paste) -> None:
                    self.assertFalse(app.composer.pending)
                    self.assertFalse(app.picker.waiting)
                    original(event)

                with patch.object(app, "_picker_key", side_effect=receive) as owned:
                    app._on_input(event)
                    owned.assert_called_once_with(event)
                if app.picker is not None:
                    app._on_input(Key(ESCAPE))
                self.assertIsNone(app.picker)
                self.assertFalse(app.composer.pending)
                self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal), before)
                self.assertEqual(client.named("session.resume"), [])
                self.assert_fresh_mode_chord(app, client)

    def test_waiting_session_keeps_leader_typing_and_enter_composer_owned(self) -> None:
        for busy in (False, True):
            for leader_enter in (False, True):
                with self.subTest(busy=busy, leader_enter=leader_enter):
                    app, client = self.waiting_picker()
                    app.turn_pending = busy
                    self.arm(app)
                    app._on_input(Key(CHAR, "m"))
                    self.assertEqual(client.named("config.set"), [
                        {"key": "yolo", "session_id": app.sid, "value": "on"},
                    ])
                    self.assertTrue(app.picker.waiting)
                    if leader_enter:
                        self.arm(app)
                    else:
                        type_text(app, "i more")
                        self.assertIn(" more", app.composer.text)
                    text = app.composer.text
                    self.assertTrue(app.picker.waiting)
                    self.assertEqual(app.picker.query, "")
                    app._on_input(Key(ENTER))
                    if busy and not leader_enter:
                        self.assertEqual(len(app.queued), 1)
                        self.assertEqual(app.queued[0].text, text)
                        self.assertEqual(client.named("prompt.submit"), [])
                        self.assertEqual(client.named("session.redirect"), [])
                    else:
                        method = "session.redirect" if busy else "prompt.submit"
                        self.assertEqual(client.named(method), [{"session_id": app.sid, "text": text}])
                    self.assertEqual(client.named("session.resume"), [])
                    self.assertTrue(app.picker.waiting)
                    self.assertEqual(app.picker.query, "")

    def test_list_failures_and_expiry_do_not_cancel_composer_leader(self) -> None:
        from omh.tui.app import CALL_ANSWER_SECONDS
        from omh.tui.gateway import Response

        for outcome in ("empty", "refused", "expired"):
            with self.subTest(outcome=outcome):
                app, client = self.normal_app()
                now = [100.0]
                app.clock = lambda: now[0]
                self.arm(app)
                app._on_input(Key(CHAR, "s"))
                request_id = len(client.calls)
                self.arm(app)
                if outcome == "expired":
                    now[0] += CALL_ANSWER_SECONDS + 1
                    app._expire_calls()
                    self.sessions_answer(app, request_id)  # an expired answer cannot seize ownership
                else:
                    error = {"code": 5006, "message": "database is locked"} if outcome == "refused" else None
                    app._on_response(Response(request_id, None if error else {"sessions": []}, error))
                self.assertIsNone(app.picker)
                self.assertTrue(app.composer.leader)
                self.assertEqual(app.composer.text, "draft")
                app._on_input(Key(CHAR, "m"))
                self.assertEqual(len(client.named("config.set")), 1)
                self.arm(app)
                app._on_input(Key(CHAR, "s"))
                retry_id = len(client.calls)
                self.assertEqual(len(client.named("session.list")), 2)
                self.sessions_answer(app, retry_id)
                self.assertIsNotNone(app.picker)
                app._on_input(Key(ESCAPE))
                self.assertFalse(app.composer.pending)

    def test_canceled_session_picker_can_be_reopened_without_stale_follower(self) -> None:
        app, client = self.normal_app()
        for _ in range(2):
            self.arm(app)
            app._on_input(Key(CHAR, "s"))
            request_id = len(client.calls)
            self.arm(app)
            self.sessions_answer(app, request_id)
            app._on_input(Key(ESCAPE))
            self.sessions_answer(app, request_id)  # duplicate response is stale after cancellation
            self.assertIsNone(app.picker)
            self.assertFalse(app.composer.pending)
            app._on_input(Key(CHAR, "m"))
            self.assertEqual(client.named("config.set"), [])
        self.assert_fresh_mode_chord(app, client)

    def test_picker_dismissal_preserves_insert_and_non_vim_drafts(self) -> None:
        for vim in (False, True):
            for kind in ("launch_picker", "picker", "search", "rewind_picker", "model_picker"):
                with self.subTest(vim=vim, kind=kind):
                    app, client = make_app()
                    app.composer.set_vim(vim)
                    type_text(app, " sbpr/mt")
                    before = (app.composer.text, app.composer.caret, app.composer.normal)
                    self.picker_fixture(app, kind)
                    app._on_input(Key(ESCAPE))
                    self.assertIsNone(getattr(app, kind))
                    self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal), before)
                    type_text(app, " more")
                    self.assertEqual(app.composer.text, " sbpr/mt more")
                    self.assertFalse(app.composer.pending)
                    self.assertEqual(client.calls, [])

    def test_late_list_answer_preserves_higher_priority_picker(self) -> None:
        from omh.tui.app import LIST_TAKEN_NOTICE
        from test_tui_modes import notices

        for kind in ("launch_picker", "search"):
            with self.subTest(kind=kind):
                app, client = self.normal_app()
                self.arm(app)
                app._on_input(Key(CHAR, "s"))
                request_id = len(client.calls)
                self.arm(app)
                owner = self.picker_fixture(app, kind)
                self.sessions_answer(app, request_id)
                self.assertIsNone(app.picker)
                self.assertIs(app._front_picker(), owner)
                self.assertIn(LIST_TAKEN_NOTICE.format(command="/resume"), notices(app))
                app._on_input(Key(ESCAPE))
                self.assertFalse(app.composer.pending)
                self.assert_fresh_mode_chord(app, client)

    def test_front_picker_priority_delivers_enter_once(self) -> None:
        kinds = ("launch_picker", "picker", "search", "rewind_picker", "model_picker")
        handlers = ("_launch_picker_key", "_picker_key", "_search_key", "_rewind_picker_key", "_model_picker_key")
        for offset, kind in enumerate(kinds):
            with self.subTest(kind=kind):
                app, client = self.normal_app()
                self.arm(app)
                owners = [self.picker_fixture(app, candidate) for candidate in kinds[offset:]]
                self.assertIs(app._front_picker(), owners[0])
                original = getattr(app, handlers[offset])

                def receive(event: Key | Paste) -> None:
                    self.assertFalse(app.composer.pending)
                    original(event)

                with patch.object(app, handlers[offset], side_effect=receive) as owned:
                    app._on_input(Key(ENTER))
                    owned.assert_called_once_with(Key(ENTER))
                self.assertEqual(client.named("prompt.submit"), [])

    def test_prompt_slot_preempts_leader_shortcuts(self) -> None:
        app, client = self.normal_app()
        self.arm(app)
        app._on_server_request(ServerRequest("srq-leader", "vault.code", {}))
        self.assertFalse(app.composer.leader)
        with patch.object(app, "_leader_key") as leader:
            app._on_input(Key(CHAR, "s"))
            leader.assert_not_called()
        self.assertEqual(client.calls, [])

    def test_unmapped_and_modified_followers_do_not_leak(self) -> None:
        from omh.tui.keys import TAB

        events = [Key(CHAR, c) for c in "?ixud q"] + [Key(ESCAPE), Key(DOWN), Key(TAB, shift=True)]
        events += [
            Key(CHAR, c, **{mod: True}) for c in "sbpr/mtxovl" for mod in ("ctrl", "alt", "shift", "reported_shift")
            if not (mod == "ctrl" and c in "ol")  # display keys keep working (test_display_keys_work_over_an_armed_leader)
        ]
        for event in events:
            with self.subTest(event=event):
                app, client = self.normal_app()
                before = (app.composer.text, app.composer.caret, app.composer.normal)
                self.arm(app)
                app._on_input(event)
                self.assertEqual((app.composer.text, app.composer.caret, app.composer.normal), before)
                self.assertFalse(app.composer.leader)
                self.assertEqual(client.calls, [])
                self.assertIsNone(app.pager)
                self.assertIsNone(app.search)
                self.assertIsNone(app.exit_code)

    def test_display_keys_work_over_an_armed_leader(self) -> None:
        for char, method in (("o", "_details_view"), ("l", "_redraw"), ("z", "_suspend")):
            with self.subTest(key=f"ctrl+{char}"):
                app, _ = self.normal_app()
                self.arm(app)
                with patch.object(app, method) as called:
                    app._on_input(Key(CHAR, char, ctrl=True))
                called.assert_called_once()
                self.assertFalse(app.composer.leader)

    def test_ctrl_c_over_an_armed_leader_matches_the_unarmed_press(self) -> None:
        def run(arm: bool, case: str) -> tuple[object, ...]:
            app, client = make_app(busy=case == "busy")
            app.composer.set_vim(True)
            if case != "empty":
                type_text(app, "ans")
            app._on_input(Key(ESCAPE))
            for _ in range(2 if case == "empty" else 1):  # the second press on an empty composer leaves
                if arm:
                    self.arm(app)
                app._on_input(Key(CHAR, "c", ctrl=True))
                self.assertFalse(app.composer.leader)
            return app.composer.text, app.exit_code, client.calls

        for case in ("draft", "busy", "empty"):
            with self.subTest(case=case):
                self.assertEqual(run(True, case), run(False, case))
        self.assertEqual(run(True, "empty")[1], 0)

    def test_insert_and_non_vim_spaces_still_type(self) -> None:
        for vim in (False, True):
            with self.subTest(vim=vim):
                app, client = make_app()
                app.composer.set_vim(vim)
                type_text(app, " sbpr/mt")
                self.assertEqual(app.composer.text, " sbpr/mt")
                self.assertFalse(app.composer.leader)
                self.assertEqual(client.calls, [])

    def test_ctrl_r_keeps_redo_without_leader(self) -> None:
        app, client = self.normal_app()
        app._on_input(Key(CHAR, "x"))
        self.assertEqual(app.composer.text, "draf")
        app._on_input(Key(CHAR, "u"))
        self.assertEqual(app.composer.text, "draft")
        app._on_input(Key(CHAR, "r", ctrl=True))
        self.assertEqual(app.composer.text, "draf")
        self.assertIsNone(app.search)
        self.assertEqual(client.calls, [])

    def test_paste_keeps_existing_behavior(self) -> None:
        app, _ = self.normal_app()
        self.arm(app)
        app._on_input(Paste("pasted"))
        self.assertFalse(app.composer.leader)
        self.assertIn("pasted", app.composer.text)

    def test_server_request_invalidates_leader_across_focus_transfer(self) -> None:
        # Approval request
        app, client = self.normal_app()
        self.arm(app)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "test"}))
        app.slot_opened_at = app.clock() - 10.0
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.slot)
        self.assertFalse(app.composer.leader)
        app._on_input(Key(CHAR, "m"))
        self.assertEqual(client.calls, [])

        # Text question
        app, client = self.normal_app()
        self.arm(app)
        app._on_server_request(ServerRequest("srq-2", "vault.code", {}))
        type_text(app, "1234")
        app.slot_opened_at = app.clock() - 10.0
        app._on_input(Key(ENTER))
        self.assertIsNone(app.slot)
        self.assertFalse(app.composer.leader)
        app._on_input(Key(CHAR, "m"))
        self.assertEqual(client.calls, [])

    def test_paste_after_space_preserves_attachment_drop(self) -> None:
        app, client = self.normal_app()
        self.arm(app)
        app._on_input(Paste("/Users/example/image.png"))
        self.assertFalse(app.composer.leader)
        self.assertEqual(app.composer.text, "draft")
        self.assertEqual(client.named("input.detect_drop"), [{"session_id": "live-1", "text": "/Users/example/image.png"}])



if __name__ == "__main__":
    unittest.main()
