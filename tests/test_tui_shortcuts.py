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

from _tui_lines import line_text
from test_tui_app import FakePoller, ScriptedTerminal
from test_tui_modes import RecordingClient, drawn, make_app, type_text
from omh.tui.app import App
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, UP, Key, Paste, list_nav_step
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
        self.assertEqual(named, set("acdejklprstouvwxyz"))
        for letter in string.ascii_lowercase:
            changed = False
            for draft, undone in (("", False), ("one two", False), ("one two", True)):  # Ctrl+Y redoes the undone draft
                app, client = make_app()
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
        self.assertIn("Enter" + " " * 41 + "Sends the composer", wide)
        narrow = [line_text(line) for line in shortcut_lines(40, DEFAULT_THEME)]
        at = narrow.index("Enter")
        self.assertEqual(narrow[at + 1], "  Sends the composer")

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


if __name__ == "__main__":
    unittest.main()
