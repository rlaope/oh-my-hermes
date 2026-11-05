"""The rail and kind colours (2026-10-22): what the owner picked from the redesign captures, pinned.

A tool call's name is bold in its family's hue (`TOOL_FAMILIES`, `Theme.kinds`)
and each hue reads at 4.5:1 on a dark and on a light terminal, measured on what
`build_theme` hands out. A run of plumbing calls (loading skills, reading tool
details) is one row, and any other call ends the run; a shell call that feeds a
script through a heredoc names the script and counts its lines. An agent row
reads a short title, and the model leads its figures. A `/name` that resolves
to a command or a skill is bold in the skill hue in the composer, in the echoed
prompt and on the sticky `↳ you:` row; a path, an unknown `/foo` and a slash
inside a word stay plain.
"""

from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from _tui_lines import line_text, lines_text
from test_tui_modes import FakePoller, RecordingClient, ScriptedTerminal, make_app
from test_tui_panels import agent_row, hud_payload, with_agents
from test_tui_prompts import CLARIFY, slot
from test_tui_subagents import feed
from omh.skin_pack import SKIN_THEMES
from omh.tui.app import STATE_WAITING, WAITING_GLYPH, App
from omh.tui.composer import Composer
from omh.tui.diff_view import diff_rows, parse_inline_diff
from omh.tui.frame import build_frame, sticky_line
from omh.tui.gateway import Event, Response
from omh.tui.history import SEARCH_LABEL, HistorySearch
from omh.tui.keys import CHAR, Key
from omh.tui.markdown import MarkdownState, render_lines
from omh.tui.panels import panel_lines
from omh.tui.screen import CLEAR_SCREEN_AND_SCROLLBACK
from omh.tui.shortcuts import shortcut_lines
from omh.tui.slash import known_names, slash_token_ranges
from omh.tui.style import Span
from omh.tui.subagents import FIELD_LABELS, MAIN_ID, TITLE_ABBREVIATIONS, Roster, short_title
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.theme import KIND_FAMILIES, TEXT_CONTRAST, build_theme, contrast_ratio, kind_style, surface_for, tool_family
from omh.tui.transcript import (
    NOTICE_INFO,
    STEER_QUEUED,
    TOOL_ERROR,
    TOOL_GENERATING,
    TOOL_INTERRUPTED,
    TOOL_OK,
    TOOL_RUNNING,
    AssistantBlock,
    CommandBlock,
    SteerBlock,
    ToolGroup,
    ToolRow,
    Transcript,
    UserBlock,
    block_rows,
)
from omh.tui.width import line_width

SID = "s"
DARK = ("#0D1117", "#1E1E1E", "#000000")
LIGHT = ("#FFFFFF", "#F6F8FA")
KNOWN = frozenset({"dag-ulw", "model"})


def calls(*tools: ToolRow, expanded: bool = False, width: int = 150) -> list[str]:  # the owner's terminal
    return lines_text(block_rows(ToolGroup(list(tools), done=True), width, THEME, expanded))


def loaded(tool_id: str, skill: str, status: str = TOOL_OK, duration: float | None = 0.7) -> ToolRow:
    return ToolRow(tool_id, "skill_view", skill, status, duration_s=duration, output=(f"loaded skill {skill}",))


def resumed(messages: list[dict]) -> tuple[App, RecordingClient]:
    """An app started on `HERMES_TUI_RESUME`, its history drawn and `commands.catalog` not answered yet."""

    class Resuming(RecordingClient):
        def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
            return {"session_id": SID, "stored_session_id": "stored", "messages": messages, "info": {"model": "m"}}

    client = Resuming()
    environ = {"HERMES_TUI_RESUME": "stored"}
    app = App(ScriptedTerminal(40, 100), client, environ, poller=FakePoller())  # type: ignore[arg-type]
    app.startup()
    return app, client


def answer_catalog(app: App, client: RecordingClient, pairs: list[list[str]]) -> None:
    app._on_response(Response(1 + [method for method, _params in client.calls].index("commands.catalog"),
                              {"pairs": pairs}, None))


def prompt_tokens(app: App) -> list[list[str]]:
    """The `/name` tokens drawn bold in each prompt row the next frame prints."""
    rows = [line for line in app.transcript.take_stable_lines(100, THEME) if line_text(line).startswith("┃ ❯")]
    return [[span.text for span in row if span.style == THEME.slash] for row in rows]


class KindHueTests(unittest.TestCase):
    def test_each_family_names_its_tools(self) -> None:
        cases = {
            "skill_view": "skill", "tool_describe": "skill", "todo_list": "skill", "clarify": "skill",
            "terminal": "shell", "process": "shell", "execute_code": "shell",
            "read_file": "file", "write_file": "file", "patch": "file", "search_files": "file",
            "web_search": "web", "web_extract": "web", "browser_navigate": "web", "browser_click": "web",
            "delegate_task": "dag", "omh_dag": "dag",
            "send_message": "", "my_plugin_tool": "",
        }
        for name, family in cases.items():
            with self.subTest(name=name):
                self.assertEqual(tool_family(name), family)

    def test_a_name_is_bold_in_its_familys_hue_and_one_in_none_keeps_the_text_colour(self) -> None:
        for name, family in (("skill_view", "skill"), ("terminal", "shell"), ("read_file", "file"),
                             ("web_search", "web"), ("delegate_task", "dag")):
            with self.subTest(name=name):
                style = kind_style(name, THEME)
                self.assertEqual(style, THEME.kinds[KIND_FAMILIES.index(family)])
                self.assertTrue(style.bold)
                spans = block_rows(ToolGroup([ToolRow("t", name, "x", TOOL_OK)], done=True), 80, THEME, True)[0]
                self.assertEqual([span.style for span in spans if span.text == name], [style])
        self.assertEqual(kind_style("my_plugin_tool", THEME), THEME.tool)
        self.assertEqual((THEME.tool.fg, THEME.tool.bold), (None, True))

    def test_the_five_hues_are_apart_from_each_other_and_from_the_state_colours(self) -> None:
        for skin in SKIN_THEMES:
            for background in (*DARK, *LIGHT):
                theme = build_theme(skin, background)
                hues = [style.fg for style in theme.kinds]
                with self.subTest(theme=skin.short_name, background=background):
                    self.assertEqual(len(set(hues)), len(KIND_FAMILIES))
                    self.assertFalse({theme.ok.fg, theme.error.fg, theme.running.fg} & set(hues))


class ContrastTests(unittest.TestCase):
    def test_every_hue_the_rail_look_adds_reads_at_text_contrast_on_dark_and_light(self) -> None:
        for skin in SKIN_THEMES:
            for background in (*DARK, *LIGHT, None):
                theme = build_theme(skin, background)
                surface = surface_for(skin, background)
                roles = {**{f"kind:{family}": style for family, style in zip(KIND_FAMILIES, theme.kinds)},
                         "slash": theme.slash, "brand": theme.brand, "faint": theme.faint, "muted": theme.muted,
                         "running": theme.running}
                for role, style in roles.items():
                    with self.subTest(theme=skin.short_name, background=background, role=role):
                        self.assertGreaterEqual(contrast_ratio(style.fg, surface), TEXT_CONTRAST)

    def test_the_owner_terminal_and_white_measured(self) -> None:
        # The default palette on the owner's dark background and on white: (skill, shell, file, web, dag).
        for background, expected in (("#0D1117", (7.97, 9.72, 9.82, 12.67, 7.53)),
                                     ("#FFFFFF", (4.62, 4.67, 4.63, 4.7, 4.75))):
            theme = build_theme(SKIN_THEMES[0], background)
            with self.subTest(background=background):
                self.assertEqual(tuple(round(contrast_ratio(style.fg, background), 2) for style in theme.kinds),
                                 expected)


class GroupingTests(unittest.TestCase):
    def test_consecutive_plumbing_calls_fold_into_one_row(self) -> None:
        rows = calls(
            loaded("a", "github-development-workflows"), loaded("b", "dag-ulw"), loaded("c", "hermes-agent"),
            ToolRow("d", "skill_view", "omh-routing → references/skill-common-rail.md", TOOL_OK, duration_s=0.7),
            ToolRow("e", "tool_describe", "Reading tool details · 3 tools", TOOL_OK, duration_s=0.0),
        )
        self.assertEqual(rows, ["┃ ● Loaded 4 skills + tool details · github-development-workflows, dag-ulw, hermes-agent, "
                                "omh-routing/skill-common-rail.md  2.8s"])

    def test_any_other_call_breaks_the_run(self) -> None:
        rows = calls(loaded("a", "dag-ulw"), ToolRow("b", "terminal", "pwd", TOOL_OK, duration_s=0.1),
                     loaded("c", "hermes-agent"), loaded("d", "omh-terminal"))
        self.assertEqual(rows, ["┃ ● Loaded 1 skill · dag-ulw  0.7s", "", "┃ ● terminal(pwd)  0.1s", "",
                                "┃ ● Loaded 2 skills · hermes-agent, omh-terminal  1.4s"])

    def test_tool_details_alone_and_a_folded_name_in_the_skill_hue(self) -> None:
        tool = ToolRow("e", "tool_describe", "Reading tool details · 1 tool", TOOL_OK, duration_s=0.4)
        self.assertEqual(calls(tool), ["┃ ● Read tool details  0.4s"])
        row = block_rows(ToolGroup([loaded("a", "dag-ulw")], done=True), 80, THEME)[0]
        self.assertEqual([span.style for span in row if span.text == "Loaded 1 skill"], [kind_style("skill_view", THEME)])

    def test_a_running_member_makes_the_row_run_and_a_failed_one_keeps_its_own(self) -> None:
        running = calls(loaded("a", "dag-ulw"), loaded("b", "hermes-agent", TOOL_RUNNING, None))
        self.assertEqual(running, ["┃ ○ Loaded 2 skills · dag-ulw, hermes-agent"])  # no time until each has one
        failed = ToolRow("b", "skill_view", "nope", TOOL_ERROR, duration_s=0.1, output=("Skill not found: nope",))
        rows = calls(loaded("a", "dag-ulw"), failed, loaded("c", "hermes-agent"))
        self.assertEqual(rows, ["┃ ● Loaded 1 skill · dag-ulw  0.7s", "", "┃ ✗ skill_view(nope)  0.1s",
                                "┃   ⎿  Skill not found: nope", "", "┃ ● Loaded 1 skill · hermes-agent  0.7s"])

    def test_a_draft_or_a_cut_off_call_is_not_counted_as_loaded(self) -> None:
        # #2223 review 6: a draft names nothing yet (an empty label left `· x, ,`), a cut-off call loaded nothing.
        draft = ToolRow("b", "skill_view", "", TOOL_GENERATING)
        self.assertEqual(calls(loaded("a", "dag-ulw"), loaded("c", "hermes-agent"), draft),
                         ["┃ ● Loaded 2 skills · dag-ulw, hermes-agent  1.4s", "", "┃ ◌ skill_view"])
        cut = ToolRow("b", "skill_view", "omh-docs", TOOL_INTERRUPTED)
        self.assertEqual(calls(loaded("a", "dag-ulw"), cut),
                         ["┃ ● Loaded 1 skill · dag-ulw  0.7s", "", "┃ ▪ skill_view(omh-docs)"])
        nameless = ToolRow("d", "skill_view", "", TOOL_OK, duration_s=0.1)
        self.assertEqual(calls(loaded("a", "dag-ulw"), nameless), ["┃ ● Loaded 2 skills · dag-ulw  0.8s"])

    def test_the_details_view_unfolds_the_run(self) -> None:
        rows = calls(loaded("a", "dag-ulw"), loaded("b", "hermes-agent"), expanded=True)
        self.assertEqual(rows, ["┃ ● skill_view(dag-ulw)  0.7s", "┃   ⎿  loaded skill dag-ulw", "",
                                "┃ ● skill_view(hermes-agent)  0.7s", "┃   ⎿  loaded skill hermes-agent"])

    def test_a_turn_counts_every_folded_call(self) -> None:
        transcript = Transcript(clock=lambda: 0.0)
        transcript.apply(Event("message.start", SID, {}))
        for tool_id in ("a", "b", "c"):
            transcript.apply(Event("tool.start", SID, {"tool_id": tool_id, "name": "skill_view", "context": tool_id}))
            transcript.apply(Event("tool.complete", SID, {"tool_id": tool_id, "name": "skill_view", "duration_s": 0.1,
                                                          "result": {"success": True, "name": tool_id}}))
        transcript.apply(Event("message.complete", SID, {"text": "", "status": "complete"}))
        self.assertEqual(lines_text(transcript.take_stable_lines(80, THEME)), ["┃ ● Loaded 3 skills · a, b, c  0.3s"])
        (group,) = transcript.blocks
        self.assertEqual(len(group.tools), 3)  # folded on the screen, each still a call


class HeredocTests(unittest.TestCase):
    """Only a heredoc that feeds an interpreter its script is summarised (#2223 review R1), the commands around it
    counted; every other command keeps its own first line, as on main, and the details view shows the command."""

    def started(self, name: str, command: str, expanded: bool = False) -> list[str]:
        transcript = Transcript(clock=lambda: 0.0)
        transcript.apply(Event("message.start", SID, {}))
        transcript.apply(Event("tool.start", SID, {"tool_id": "t", "name": name, "args": {"command": command},
                                                   "context": command[:60]}))
        if expanded:
            return lines_text(block_rows(transcript.blocks[-1], 120, THEME, expanded=True))
        return lines_text(transcript.live_lines(120, THEME))

    def test_an_interpreter_fed_its_script_is_named_and_the_script_counted(self) -> None:
        cases = {
            "python3 - <<'PY'\nimport subprocess, json\nroot = '/x'\nprint(root)\nPY": "python3 script · 3 lines",
            "bash <<EOF\necho hi\nEOF": "bash script · 1 line",
            "node - <<'JS'\nconsole.log(1)\nJS": "node script · 1 line",
            "/usr/bin/python3 -u - <<PY\nx = 1\ny = 2\nPY": "python3 script · 2 lines",
            "sh <<-EOF\n\techo hi\n\tEOF": "sh script · 1 line",  # `<<-`: a tab-indented terminator
            "cd /repo && python3 - <<'PY'\na = 1\nb = 2\nPY": "python3 script · 2 lines + 1 command",
            "FOO=1 python3 - <<EOF\nx = 1\nEOF": "python3 script · 1 line",
            "uv run python - <<'PY'\nx = 1\nPY": "python script · 1 line",
            "uv run --with requests python3 -u - <<'PY'\nx = 1\nPY": "python3 script · 1 line",
            "env A=1 node - <<'JS'\nx\nJS": "node script · 1 line",
            "python3.12 - <<PY\nx = 1\nPY": "python3.12 script · 1 line",
            # The heredoc not on the first line, and a command after it: the script's own lines are counted.
            "set -e\npython3 - <<EOF\nx = 1\nEOF\necho done": "python3 script · 1 line + 2 commands",
        }
        for command, said in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.started("terminal", command), [f"┃ ○ terminal({said})"])

    def test_any_other_command_keeps_its_own_first_line(self) -> None:
        cases = {
            "gh pr create --title 'x' --body-file - <<'EOF'\nThe body.\nEOF":
                "gh pr create --title 'x' --body-file - <<'EOF'",
            "cd /repo && git commit -F - <<'MSG'\nfix: x\n\nThe body.\nMSG": "cd /repo && git commit -F - <<'MSG'",
            "cat > src/app.py <<'EOF'\nprint(1)\nEOF": "cat > src/app.py <<'EOF'",
            "python3 - <<< 'print(1)'\nls\npwd": "python3 - <<< 'print(1)'",  # a here-string
            # A here-string whose word is a terminator's: its last two `<` would open a heredoc `PY` closes.
            "python3 -<<<PY\nx = 1\nPY": "python3 -<<<PY",
            "echo $((1<<3))\nls\npwd": "echo $((1<<3))",  # a shift
            "python3 tool.py <<EOF\ndata\nEOF": "python3 tool.py <<EOF",  # a script file reading data
            "python3 - <<'PY'\nnever closed": "python3 - <<'PY'",  # no terminator: not a script
            "git status": "git status",
        }
        for command, said in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.started("terminal", command), [f"┃ ○ terminal({said})"])
        self.assertNotIn("script", "".join(self.started("read_file", "python3 - <<'PY'\nx\nPY")))  # not a shell

    def test_only_the_commands_around_the_script_are_counted(self) -> None:
        # #2223 follow-up: another heredoc's body, a continued line and a comment each counted as a command.
        script = "python3 - <<'PY'\nx = 1\nPY"
        cases = {
            f"{script}\ncat > notes.md <<'EOF'\nline 1\nline 2\nline 3\nEOF": " + 1 command",
            f"{script}\ncat <<EOF > out.txt\na\nEOF\nls": " + 2 commands",  # more of the command after its opener
            f"{script}\ngit add a \\\n  b \\\n  c": " + 1 command",
            "cd /repo && \\\n  " + script: " + 1 command",
            "uv run --with requests \\\n  " + script: "",  # the interpreter's own command, continued onto its line
            f"# check the repo\n\n{script}\n  # done": "",
            # No heredoc opens in arithmetic, however its shift is spaced, or in quotes (#2225 review F3).
            f"{script}\necho $((1<<3))\nls": " + 2 commands",
            f"{script}\necho $(( 1 << n ))\nls\npwd": " + 3 commands",
            f"{script}\necho $((a<<b))\nls": " + 2 commands",
            f"{script}\n(( z = x << y ))\nls": " + 2 commands",
            f"{script}\n(( x = 1 << n ))\nls\npwd": " + 3 commands",
            f"{script}\necho \"a << b c\"\nls\npwd": " + 3 commands",
            f"{script}\necho 'a << b c'\nls\npwd": " + 3 commands",
            f"{script}\necho 'x <<EOF'\nls\npwd": " + 3 commands",
            f"{script}\necho \"a \\\" << b\"\nls": " + 2 commands",  # an escaped quote does not close it
            f"{script}\necho \"feed it <<EOF\"\nls": " + 2 commands",
            f"{script}\necho 'x' && cat <<EOF\nbody\nEOF\nls": " + 2 commands",  # an opener after a quoted word
        }
        for command, said in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.started("terminal", command), [f"┃ ○ terminal(python3 script · 1 line{said})"])

    def test_the_details_view_shows_the_command_itself(self) -> None:
        command = "python3 - <<'PY'\nimport json\nprint(1)\nPY"
        self.assertEqual(self.started("terminal", command), ["┃ ○ terminal(python3 script · 2 lines)"])
        self.assertEqual(self.started("terminal", command, expanded=True), ["┃ ○ terminal(python3 - <<'PY')"])

    def test_the_documented_rows_are_the_rows_the_code_draws(self) -> None:
        prose = " ".join((Path(__file__).resolve().parents[1] / "docs" / "INSTALLATION.md").read_text(
            encoding="utf-8").split())
        folded = calls(
            loaded("a", "github-development-workflows"), loaded("b", "dag-ulw"), loaded("c", "hermes-agent"),
            ToolRow("d", "skill_view", "omh-routing → references/skill-common-rail.md", TOOL_OK, duration_s=0.7),
            ToolRow("e", "tool_describe", "Reading tool details · 3 tools", TOOL_OK, duration_s=0.0),
        )[0]
        self.assertIn(f"`{' '.join(folded.removeprefix('┃ ').split())}`", prose)
        script = "python3 - <<'PY'\n" + "x = 1\n" * 23 + "PY"
        (row,) = self.started("terminal", script)
        self.assertIn(f"`{row.removeprefix('┃ ○ ')}`", prose)


class ShortTitleTests(unittest.TestCase):
    def test_a_structured_goal_is_cut_at_its_first_field_label(self) -> None:
        # The owner's 2026-10-22 run: each row was the whole goal.
        goal = ("TASK: Maintain rlaope's open hermes-agent PRs, close the stale ones DELIVERABLE: handoff.json "
                "and handoff.md per PR CONTEXT: …")
        self.assertEqual(short_title(goal), "Maintain rlaope's open hermes-agent PRs, close the stale ones")

    def test_a_goal_is_cut_at_the_end_of_its_first_sentence(self) -> None:
        self.assertEqual(short_title("Fix the flaky test. Then run the whole suite and report."), "Fix the flaky test")
        self.assertEqual(short_title("Is the cache stale? Check it."), "Is the cache stale?")

    def test_only_the_node_prompts_own_field_labels_cut(self) -> None:
        # #2223 review R3: a capitalised word and a colon is not a field label; only the node prompt's are
        # (TASK, DELIVERABLE, SCOPE, VERIFY, STOP WHEN).
        self.assertEqual(short_title("Update the README: add the install steps"), "Update the README: add the install steps")
        self.assertEqual(short_title("Fix the JSON: parser crash"), "Fix the JSON: parser crash")
        self.assertEqual(short_title("TASK: Bump CHANGELOG: note the fix DELIVERABLE: a PR"), "Bump CHANGELOG: note the fix")
        self.assertEqual(short_title("List the API: every endpoint"), "List the API: every endpoint")
        for label in FIELD_LABELS:
            with self.subTest(label=label):
                self.assertEqual(short_title(f"Rebase PR 12 {label}: the rest"), "Rebase PR 12")

    def test_a_dot_inside_a_word_does_not_cut(self) -> None:
        self.assertEqual(short_title("Bump to v1.2.3 and tag it"), "Bump to v1.2.3 and tag it")
        self.assertEqual(short_title("Bump to v1.2 and tag it. Then announce"), "Bump to v1.2 and tag it")
        self.assertEqual(short_title("Release v1.2. Then announce"), "Release v1.2")  # a version can end one
        self.assertEqual(short_title("DELIVERABLE: a report"), "DELIVERABLE: a report")  # nothing before it to keep

    def test_an_abbreviation_does_not_end_the_sentence(self) -> None:
        # #2223 follow-up: `Fix e.g. the bug` read `Fix e.g`.
        for word in TITLE_ABBREVIATIONS:
            with self.subTest(word=word):
                self.assertEqual(short_title(f"Fix {word} the parser. Then run it"), f"Fix {word} the parser")
        self.assertEqual(short_title("E.g. the parser. Then run it"), "E.g. the parser")
        self.assertEqual(short_title("Pin numpy 1.26 vs. 2.0. Then test"), "Pin numpy 1.26 vs. 2.0")
        self.assertEqual(short_title("Ask the devs. Then fix it"), "Ask the devs")  # `vs.` only as its own word

    def test_a_dag_lane_keeps_its_whole_label(self) -> None:
        self.assertEqual(short_title("Audit auth. Then the tests [dag:r1/audit]"), "Audit auth. Then the tests")

    def test_an_agent_row_reads_its_short_title_and_the_model_first(self) -> None:
        roster = Roster()
        feed(roster, "start", 10.0, "sa-a", goal="TASK: Rebase PR 94647 DELIVERABLE: a green CI run",
             model="gpt-6.1-sol")
        feed(roster, "tool", 11.0, "sa-a", tool_count=3)
        row = line_text(roster.list_lines(80, THEME, MAIN_ID, 0, 6, 22.0)[0][1])
        self.assertTrue(row.startswith("  ") and "Rebase PR 94647" in row and "DELIVERABLE" not in row, row)
        self.assertTrue(row.endswith("  gpt-6.1-sol · 12s · 3 tools"), row)


class SlashTokenTests(unittest.TestCase):
    def test_a_known_name_is_a_token_wherever_it_stands_alone(self) -> None:
        self.assertEqual(slash_token_ranges("/dag-ulw go", KNOWN), [(0, 8)])
        self.assertEqual(slash_token_ranges("then /model, no: /model now", KNOWN), [(17, 23)])
        self.assertEqual(slash_token_ranges("run /dag-ulw\n/model", KNOWN), [(4, 12), (13, 19)])

    def test_a_path_an_unknown_name_and_a_slash_inside_a_word_are_not(self) -> None:
        for text in ("src/a.py", "/usr/bin/env", "/dag-ulw/x", "/foo bar", "a/dag-ulw", "x /dagulw", "//dag-ulw"):
            with self.subTest(text=text):
                self.assertEqual(slash_token_ranges(text, KNOWN), [])

    def test_a_known_name_in_any_case_is_a_token_since_it_runs_as_typed(self) -> None:
        # Hermes lowercases a typed name before it routes it and finds a skill by its lowercased name
        # (methods_tools.py `slash.exec`, `_dispatch_skill`), and the TUI resolves its own commands the same way.
        self.assertEqual(slash_token_ranges("/Dag-ulw go", KNOWN), [(0, 8)])
        self.assertEqual(slash_token_ranges("then /REWIND", known_names()), [(5, 12)])
        self.assertEqual(slash_token_ranges("/Foo bar", known_names()), [])

    def test_the_names_are_what_runs_here(self) -> None:
        names = known_names([("/dag-ulw", "Graph work"), ("/update", "Hermes' own")])
        self.assertTrue({"dag-ulw", "model", "help"} <= names)
        self.assertNotIn("update", names)  # Hermes' own TUI runs it, not this one

    def test_a_cut_through_a_token_leaves_no_half_of_it_coloured(self) -> None:
        # #2223 review 14: the sticky row cuts its words before it colours them; `/dag-ulw` cut to `/dag` is not
        # the `/dag` command either.
        known = frozenset({"dag-ulw", "dag"})
        for width in range(9, 16):
            sticky = sticky_line("/dag-ulw go on", width, THEME, known)
            with self.subTest(width=width, row=line_text(sticky)):
                self.assertTrue(line_text(sticky).endswith("…"))
                self.assertFalse([span for span in sticky if span.style == THEME.slash])
        whole = sticky_line("/dag-ulw go on and on", 18, THEME, known)
        self.assertEqual([span.text for span in whole if span.style == THEME.slash], ["/dag-ulw"])

    def test_a_resumed_prompt_keeps_the_highlight(self) -> None:
        # #2223 review 9: a resumed session's prompt rows read `known` as a live prompt's do.
        app, _client = make_app(rows=40, cols=100)
        app.known_slash = known_names([("/dag-ulw", "Graph work")])
        app._draw_history([{"role": "user", "text": "/dag-ulw go"}])
        (row,) = [line for line in app.transcript.take_stable_lines(100, THEME) if line_text(line).startswith("┃ ❯")]
        self.assertEqual([span.text for span in row if span.style == THEME.slash], ["/dag-ulw"])

    def test_a_prompt_resumed_before_the_catalog_answers_is_redrawn_once_it_does(self) -> None:
        # #2223 follow-up: a startup resume prints the history before `commands.catalog` answers, so a resumed
        # `/dag-ulw go` stayed plain while the TUI's own `/model` was bold.
        app, client = resumed([{"role": "user", "text": "/dag-ulw go"}, {"role": "user", "text": "/model x"}])
        self.assertEqual(prompt_tokens(app), [[], ["/model"]])  # what the first frame prints
        app.transcript.add_user("/dag-ulw now", known=app.known_slash)  # a live prompt keeps what it was sent with
        answer_catalog(app, client, [["/dag-ulw", "Graph work"]])
        tokens = prompt_tokens(app)  # read before the frame below prints them
        app._render()  # the redraw's erase goes out with its first frame
        self.assertIn(CLEAR_SCREEN_AND_SCROLLBACK, "".join(app.terminal.writes))
        self.assertEqual(tokens, [["/dag-ulw"], ["/model"], []])

    def test_a_catalog_that_resolves_no_resumed_prompt_otherwise_redraws_nothing(self) -> None:
        app, client = resumed([{"role": "user", "text": "/model x"}, {"role": "user", "text": "read src/dag-ulw"}])
        self.assertEqual(prompt_tokens(app), [["/model"], []])
        answer_catalog(app, client, [["/dag-ulw", "Graph work"]])
        tokens = prompt_tokens(app)  # read before the frame below prints them
        app._render()  # a redraw's erase would go out with this frame
        self.assertNotIn(CLEAR_SCREEN_AND_SCROLLBACK, "".join(app.terminal.writes))
        self.assertEqual(tokens, [])  # nothing is printed again

    def test_a_moved_prompt_above_the_redrawn_tail_redraws_nothing(self) -> None:
        # #2225 review F1: a full redraw reprints only the last `REDRAW_TAIL_ROWS` rows; one for a prompt above them
        # reprinted the tail and changed nothing on the screen.
        history = [{"role": "user", "text": "/dag-ulw go"}, *({"role": "assistant", "text": f"reply {number}"}
                                                              for number in range(8))]
        with patch("omh.tui.app.REDRAW_TAIL_ROWS", 10):
            app, client = resumed(history)
            self.assertEqual(prompt_tokens(app), [])  # the tail the first frame prints holds no prompt
            answer_catalog(app, client, [["/dag-ulw", "Graph work"]])
        app._render()  # a redraw's erase would go out with this frame
        self.assertNotIn(CLEAR_SCREEN_AND_SCROLLBACK, "".join(app.terminal.writes))
        (prompt,) = [block for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertIn("dag-ulw", prompt.known)  # /history draws it with the catalog's names

    def test_a_moved_prompt_in_the_tail_redraws_though_one_above_it_moved_first(self) -> None:
        # #2225 review D2: whichever moved prompt comes first, one the redraw reprints decides.
        replies = [{"role": "assistant", "text": f"reply {number}"} for number in range(8)]
        history = [{"role": "user", "text": "/dag-ulw go"}, *replies, {"role": "user", "text": "/dag-ulw again"}]
        with patch("omh.tui.app.REDRAW_TAIL_ROWS", 10):
            app, client = resumed(history)
            self.assertEqual(prompt_tokens(app), [[]])  # only the second prompt is in the tail
            answer_catalog(app, client, [["/dag-ulw", "Graph work"]])
            tokens = prompt_tokens(app)  # read before the frame below prints them
            app._render()  # the redraw's erase goes out with its first frame
            self.assertIn(CLEAR_SCREEN_AND_SCROLLBACK, "".join(app.terminal.writes))
            self.assertEqual(tokens, [["/dag-ulw"]])

    def test_the_composer_draws_a_known_name_bold_in_the_skill_hue(self) -> None:
        # `/dag-ulw` itself is drawn in the aura (`test_tui_aura`), over its `/name` colour: `/model` stands for the rest.
        frame = build_frame(cols=60, rows=24, composer=Composer(text="/model go /foo src/a.py"),
                            info=(Span("info"),), known_slash=KNOWN)
        (row,) = [line for line in frame.lines if line_text(line).startswith("❯ /model")]
        self.assertEqual([span.text for span in row if span.style == THEME.slash], ["/model"])
        self.assertEqual(THEME.slash, THEME.kinds[KIND_FAMILIES.index("skill")])  # a skill reads as its loads do
        plain = build_frame(cols=60, rows=24, composer=Composer(text="/model go"), info=(Span("info"),))
        self.assertFalse([span for line in plain.lines for span in line if span.style == THEME.slash])

    def test_the_echoed_prompt_and_the_sticky_row_draw_it_too(self) -> None:
        (echo,) = block_rows(UserBlock("/dag-ulw go a/dag-ulw", known=KNOWN), 60, THEME)
        self.assertEqual(line_text(echo), "┃ ❯ /dag-ulw go a/dag-ulw")
        self.assertEqual([span.text for span in echo if span.style == THEME.slash], ["/dag-ulw"])
        sticky = sticky_line("/dag-ulw go /foo", 60, THEME, KNOWN)
        self.assertEqual(line_text(sticky), "↳ you: /dag-ulw go /foo")
        self.assertEqual([span.text for span in sticky if span.style == THEME.slash], ["/dag-ulw"])
        self.assertFalse([span for span in sticky_line("/dag-ulw go", 60, THEME) if span.style == THEME.slash])


class TinyWidthTests(unittest.TestCase):
    def test_no_railed_row_is_wider_than_a_tiny_terminal(self) -> None:
        # #2223 review 15: the rail takes two cells, so a terminal of a few columns cut rows to its width.
        blocks = (
            UserBlock("hello /dag-ulw there", known=KNOWN),
            CommandBlock("/usage", [("Session cost: $0.01", NOTICE_INFO)], done=True),
            ToolGroup([ToolRow("t", "terminal", "ls -la", TOOL_OK, duration_s=0.1, output=("a", "b"))], done=True),
            AssistantBlock("hello there\n\nsecond paragraph", done=True),
        )
        for width in range(1, 9):
            for block in blocks:
                with self.subTest(width=width, block=type(block).__name__):
                    self.assertTrue(all(line_width(row) <= width for row in block_rows(block, width, THEME)))


class RunningBlueTests(unittest.TestCase):
    """The running blue (`Theme.running`) says "running" and nothing else (#2223 review): a list bullet, a diff's
    hunks, a key, a question's bar, the waiting row, an attached image, the history search's label, a paste chip, a
    steer's mark, a finished agent's goal and a kanban lane's row in any other state are drawn without it."""

    def spans(self, lines: list) -> list[Span]:
        return [span for line in lines for span in line]

    def test_no_state_is_drawn_in_the_running_blue(self) -> None:
        rows, _state = render_lines(["- a bullet", "```diff", "@@ -1 +1 @@", "-old", "+new", "```"], MarkdownState(),
                                    60, THEME)
        # Two hunks: their starts number the gutter and the second leaves its `⋮` (a hunk header is no row).
        hunks = parse_inline_diff("a/x.py → b/x.py\n@@ -1,2 +1,2 @@\n-old\n+new\n same\n@@ -40 +40 @@\n-late\n+later")
        question = slot("clarify", CLARIFY).lines(60, THEME, max_rows=6)
        app, _client = make_app(busy=True)
        app.waiting_since = app.clock()
        search = HistorySearch(["git push"], "")
        search.handle_key(Key(CHAR, "g"))
        chip = "[Pasted text #1 +60 lines]"
        composer = Composer(text=chip, pastes={chip: "x\n" * 60})
        token = Composer()
        token.insert_image("[Image #1]", "/x/shot.png")
        steers = [SteerBlock("look at b"), SteerBlock("look at c", STEER_QUEUED)]
        sites = {  # each site, and what it draws that the running blue once coloured
            "markdown": (rows, "• a bullet"),
            "diff": (diff_rows(hunks, 60, THEME), "⋮"),
            "keys": (shortcut_lines(100, THEME), "Ctrl+R"),
            "question": (question, "?"),
            "waiting": (app._tail(80), WAITING_GLYPH + STATE_WAITING),
            "image token": (build_frame(cols=60, rows=24, composer=token, info=(Span("info"),)).lines, "[Image #1]"),
            "history search": (search.lines(60, THEME, 4), SEARCH_LABEL),
            "paste chip": (build_frame(cols=60, rows=24, composer=composer, info=(Span("info"),)).lines, chip),
            "steer": ([row for steer in steers for row in block_rows(steer, 60, THEME)], "❯ look at c"),
        }
        for name, (lines, drawn) in sites.items():
            with self.subTest(site=name):
                self.assertIn(drawn, "\n".join(lines_text(lines)))
                self.assertNotIn(THEME.running, {span.style for span in self.spans(lines)})

    def test_an_agents_goal_in_its_log_is_its_own_state(self) -> None:
        roster = Roster()
        for subagent_id, status in (("sa-r", ""), ("sa-d", "completed"), ("sa-f", "failed")):
            feed(roster, "start", 10.0, subagent_id, goal=f"goal {subagent_id}")
            if status:
                feed(roster, "complete", 12.0, subagent_id, status=status)
        header = {sid: roster.log_lines(sid, 80, THEME, 20.0)[0][0].style for sid in ("sa-r", "sa-d", "sa-f")}
        self.assertEqual(header, {"sa-r": THEME.running, "sa-d": THEME.muted, "sa-f": THEME.error})

    def test_a_kanban_lane_row_is_its_rows_state(self) -> None:
        states = ("running", "done", "queued", "blocked")
        rows = [agent_row(0, lane_backend="kanban", state=state, task_id=f"t{index}") for index, state in enumerate(states)]
        lines = panel_lines(with_agents(hud_payload([{"text": "a", "state": "active"}]), rows), 120, 20, THEME, 0.0)
        marks = {line_text(line).split()[2]: line[0].style for line in lines if "kanban/" in line_text(line)}
        self.assertEqual(marks, {"t0": THEME.running, "t1": THEME.ok, "t2": THEME.dim, "t3": THEME.error})
        for line in lines:
            if "kanban/" in line_text(line) and "running" not in line_text(line):
                with self.subTest(row=line_text(line)):
                    self.assertNotIn(THEME.running, {span.style for span in line})


if __name__ == "__main__":
    unittest.main()
