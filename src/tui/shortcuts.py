"""Every key the OMH TUI binds, in one table.

`SHORTCUTS` is the only list of what each key does. `?` on an empty composer
and `/keys` draw it (`shortcut_lines`), and the Keys table in
docs/INSTALLATION.md is held to the same rows, in the same order, by
`tests/test_tui_shortcuts.py`: a key that gains a row here without its doc
row, or the reverse, fails there. The doc table writes the same text with
backticks around literals; nothing else may differ.

A row is `(keys, what they do)`. Keys that only work in one place say where.
"""

from __future__ import annotations

from .style import Line, Span
from .theme import Theme
from .width import cell_width, wrap_line

SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Enter", "Sends the composer"),
    ("\\ then Enter, Alt+Enter, Shift+Enter, Ctrl+J", "Adds a line"),
    ("Ctrl+Enter", "While a turn runs, sends the composer's text into it now as a steer (/steer <text> too); idle, "
                   "sends as Enter does"),
    ("Ctrl+Enter, Ctrl+J", "While a turn runs, on an empty composer, send the oldest queued prompt into it now as a "
                           "steer; the row under the queue names the key (Ctrl+J where the terminal has not shown it "
                           "tells Ctrl+Enter from Enter). A queued ! line, skill prompt or plan prompt waits its turn"),
    ("Tab", "Completes a slash command, or the @ reference being typed; on an open menu, Enter takes the "
             "highlighted row too, and sends a command already typed in full"),
    ("Shift+Tab", "Cycles the input mode: normal, accept all (Hermes asks no approvals in this session), plan "
                  "(prompts go as /plan); while Hermes itself has approvals off, turns plan on and off"),
    ("Ctrl+T", "Steps the reasoning effort: low, medium, high, xhigh, max; the info line shows it as effort medium"),
    ("@", "Starts a file or folder reference; Hermes offers matches above the composer"),
    ("!", "At the start of a line, makes it a shell command Hermes runs when you send it (30 s at most); "
          "it and its output are not sent to the model"),
    ("?", "On an empty composer, shows this list; /keys does too"),
    ("↑ / ↓", "Move between the composer's rows, walk the input history at its first and last row "
              "(earlier sessions' too, shared with hermes --tui), or move through an open completion menu"),
    ("Ctrl+R", "Searches the input history; Ctrl+R again finds an older match, Enter puts it in the composer, "
               "Esc leaves the composer as it was"),
    ("Ctrl+X", "Opens the /sessions picker"),
    ("Ctrl+S", "Opens the bot board, as /bots does: this machine's Hermes profiles, their gateways and sessions, "
               "read-only"),
    ("Ctrl+P", "Folds the plan above the composer to its header and the item it is on, or expands it again, while "
               "a turn runs or between turns; the header says which on its right"),
    ("↑", "On an empty composer with prompts queued, takes them back into the composer to edit; a queued shell line comes back on its own"),
    ("↓", "On an empty composer while the agent view under the info line shows subagents, gives its rows the keys "
          "as the agent list; in a DAG run, to its folding tree"),
    ("← / →", "Move by a character; with Ctrl or Alt, by a word (Alt+B and Alt+F too)"),
    ("Home / End, Ctrl+A / Ctrl+E", "Go to the start or the end of the line"),
    ("Backspace / Delete", "Delete a character, or a paste chip or an [Image #N] token whole; deleting a token "
                           "removes its image"),
    ("Ctrl+W, Alt+Backspace, Ctrl+Backspace", "Deletes the word before the caret (Ctrl+Backspace where the terminal reports it apart from Backspace)"),
    ("Ctrl+U / Ctrl+K", "Delete to the start or the end of the line"),
    ("Ctrl+_ / Ctrl+Y", "Undo or redo an edit in the composer (Ctrl+_ is what Ctrl+- and Ctrl+/ send on most terminals); "
                        "a run of typed characters is one edit"),
    ("Esc", "Closes the / or @ menu; on an empty composer, interrupts a running turn "
            "(the activity row shows how long it has run, then interrupting…, and what you queued comes back to the "
            "composer unsent); cancels a rewind you picked; "
            "cancels an agent steer you picked and keeps what you typed; after an approval's tell row, "
            "sends nothing more and brings your draft back"),
    ("Esc Esc", "With text, clears it and keeps it in this session's history; on an empty composer between turns, "
                "lists your prompts to rewind to (/rewind does too)"),
    ("Ctrl+V", "Attaches the clipboard image as an [Image #N] token at the caret"),
    ("Ctrl+O", "Opens the whole transcript with every detail (thinking, tool output, whole diffs) at its end, or, "
               "while Hermes asks something, the whole question (it answers nothing); q leaves it"),
    ("Ctrl+L", "Redraws the screen"),
    ("Ctrl+Z", "Suspends the OMH TUI to the shell, as Ctrl+Z does in any terminal program (Hermes stops with it); "
               "fg brings it back"),
    ("Ctrl+C", "Clears the composer, else interrupts a running turn; a second press within 2 s exits, "
               "mid-turn too; a prompt held for its pasted image comes back to the composer"),
    ("Ctrl+D", "On an empty composer, exits; with text, deletes the character ahead"),
    ("↑ / ↓ or ← / → then Enter", "On an approval, highlight allow once, allow this session or (when Hermes "
                                  "offers it) always allow, and allow it, or the last row to deny and tell Hermes "
                                  "what to do instead; Enter alone denies and stops the running turn"),
    ("d, n", "On an approval, deny and stop the running turn"),
    ("1 to 9", "On a clarify question's list, pick that choice, or the last number opens the field for your own "
               "answer; ↑ / ↓ then Enter picks too, and any other character starts your own answer"),
    ("Space", "On a clarify question that takes several choices, ticks or unticks the highlighted one; Enter sends "
              "the ticked ones, or the highlighted one when none is ticked, and a digit ticks its choice"),
    ("Esc, Ctrl+C", "On a question Hermes asked, decline it (an approval is denied and the running turn stops); "
                    "Ctrl+C first clears an answer being typed"),
    ("↑ / ↓, PageUp / PageDown, Enter, Esc", "In the /sessions, /rewind or /model list, move, take the highlighted "
                                             "row (switch to that session, put that prompt in the composer to send "
                                             "again, or switch this session to that model), or close it; typing "
                                             "filters the list"),
    ("↑ / ↓, Enter, Esc, ←, q, Ctrl+C", "In the agent list, move, open the highlighted agent's log (on main, "
                                        "only leave), or go back; any other key does nothing there"),
    ("x, s", "In the agent list, on an agent: x twice interrupts it; s steers it with the next line you send "
             "(Esc cancels)"),
    ("↑ / ↓ or a click, Enter, Esc", "In the /theme picker, preview a launch look (spectrum, violet, gold, graphite, sakura, moonlit, aurora, ember) on the logo, the card and the chrome, keep it, or put the one in use back; /theme <look> keeps one at once"),
    ("Click", "On a row of the agent list, opens that agent's log (on main, only leaves the list)"),
    ("← / →, q or Esc", "In an agent's log, show the agent before or after, or go back; the pager's keys scroll it"),
    ("Tab / n, Shift+Tab / p, Space / Enter, d", "In /dag, highlight the next or the previous box, fold or unfold "
                                                 "the highlighted one, or show or hide Node details; ↑ / ↓, "
                                                 "PageUp / PageDown and g / G scroll, q or Esc leaves"),
    ("↑ / ↓, Enter or →, ← or Esc or q, r", "On the bot board, move, open a profile's sessions or a session's last "
                                            "messages, go back (on the profiles, close the board), or read it again "
                                            "now; it reads again every 5 s by itself"),
    ("j / k, Space / b, g / G, q or Esc", "In a pager (/history, /logs, an agent's log, this list), "
                                          "move a line, a page, or to either end, or leave"),
    ("Drag, double click, triple click, wheel", "In a pager (/dag and the bot board too), select text and copy it "
                                                "when you let go (without the rails), copy a word, copy a row, or "
                                                "scroll three lines; the footer says what the copy did"),
)

TITLE = "OMH TUI keys"
_COLUMN_GAP = 2
_MIN_TEXT_CELLS = 24  # under this the description goes on the rows below its keys


def shortcut_lines(width: int, theme: Theme) -> list[Line]:
    """`SHORTCUTS` as pager rows at `width`: keys in a column, the description wrapped beside them.

    A terminal too narrow for both stacks them: the keys on one row, the
    description indented under them.
    """
    column = max(cell_width(keys) for keys, _does in SHORTCUTS) + _COLUMN_GAP
    beside = width - column >= _MIN_TEXT_CELLS
    indent = column if beside else _COLUMN_GAP
    lines: list[Line] = [(Span(TITLE, theme.heading),), ()]
    for keys, does in SHORTCUTS:
        text = wrap_line((Span(does, theme.text),), max(width - indent, 1))
        if beside:
            lines.append((Span(keys, theme.user), Span(" " * (column - cell_width(keys))), *text[0]))
            text = text[1:]
        else:
            lines.extend(wrap_line((Span(keys, theme.user),), max(width, 1)))
        lines.extend((Span(" " * indent), *row) for row in text)
    return lines
