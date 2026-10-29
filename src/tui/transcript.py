"""The transcript of one OMH TUI session, and the rule for when its lines may leave the live region.

Inline scrollback: a line printed above the live region lives in
the terminal's own scrollback and is never repainted; only the live region
repaints. So the model answers three questions for the app loop:

- `take_stable_lines`: lines that will never change again. Each is returned
  once and then belongs to the terminal.
- `live_lines`: everything not yet taken, as it looks now (painted inside the
  live region every frame).
- `history_lines`: every block held, as `/history` shows them (its pager
  renders them a page at a time, with `block_rows`). At most `BLOCK_CAP`
  blocks are held; past it the oldest ones already taken are dropped
  (`dropped` counts them).

The invariant the tests hold: at any moment, the lines already taken followed
by `live_lines()` equal `history_lines(details=False)` at the same width
(unless `toggle_details` expanded the live block, or the cap dropped blocks).
Only the LAST block can still change; appending any block first closes the
one before it, so a block is flushed only after every block above it.

Assistant text opens with a bold `● ` in the text colour on its first row, and
every later row of that reply, however many flushes it arrives in, is indented
to match, so a reply reads as one block beside the dim `❯ ` of the prompt above
it. Three kinds of block hang on a rail in the left gutter (`RAIL`: one cell
painted in the block's colour and a space; a painted cell meets the ones above
and below it, so a block's rail is one line, and each cell holds a space, so a
terminal's selection copies no bar with the text): your prompt's in dim grey,
each tool call's in the launch look's `Theme.accent` (a failed or denied one's
red, as its band is; its mark says every other state), and a reply's in the
skin's accent, the banner's colour (`Theme.brand`). Nothing has a band behind it.

A slash command the person runs is a block of its own: `❯ /name arg` on the prompt's dim
rail, in the hint colour, then what it printed under `⎿`, each part in its level's colour
and, for a warning or an error, its glyph. Its echo stays live while the
command may still print (`close_command` ends that); what it says meanwhile
is its output (`command` names the command speaking). Typed while a block
is live (a running tool, a streaming reply), the echo is held under that
block, as a steer is, and written at the next boundary once the command is
over. A long output shows its first `OUTPUT_PREVIEW_ROWS` rows and a count
of the rest, which names Ctrl+O (`/history` shows it too).

Flush policy: a user or notice block flushes at once; assistant text flushes
per completed source line (a trailing blank line waits for the text after it,
so a reply that ends there leaves nothing to take back) and fully at
`message.complete`; the markdown state (an open fence) carries across the
flush boundary; thinking flushes as ONE collapsed row ("▸ thought for 4.2s");
a tool group flushes when the next block arrives (message text, thinking) or
at `message.complete`, as one row per call (`● name(argument summary)`, the
mark a shape and a colour per state, `TOOL_MARKS`, and the name bold in its
tool family's hue, `TOOL_FAMILIES`) with what it printed under `⎿`, a blank row
between two calls, no header over them; a read or a load says in one line what
it read instead (`_read_summary`), and an `omh_memory` recall that found
records lists them, a line each (`_recall_lines`), which one band of the
dag-ulw aura sweeps as the call completes, while its group is live and only
where the aura moves (`_glint_band`). A run of consecutive plumbing calls
(`PLUMBING_TOOLS`: loading a skill, reading tool details) folds into one row,
`● Loaded 4 skills + tool details · a, b, c, d  3.5s` (a failed one keeps its own
row, and the details view unfolds the run), and a shell call that
feeds a script through a heredoc reads `terminal(python3 script · 23 lines)`
(`_heredoc_summary`). A
`tool.generating` row (`◌`) is a draft: a `tool.start` takes over the first
unclaimed draft of its name, or else the first unclaimed draft of the
`tool_call` bridge (`gateway_contract.TOOL_CALL_BRIDGE`), whose call starts
under the name of the tool it reached. A draft no start took is dropped when
its group closes, so it is never written or counted, and a group left with no
calls shows nothing. An edit tool whose `tool.complete` carries
an `inline_diff` shows that diff under its row's `⎿` (`diff_view.py`): the first
`PREVIEW_LINES` diff lines and a count of the rest, which Ctrl+O's details
view (and `history_lines` with details) shows in full. Lines rendered at one width stay as they were taken; a
resize changes only what has not been taken yet.

Two events do not mean what their names suggest, measured against Hermes
6c61c3e27d (the recorded fixtures and the gateway source):

- `thinking.delta` is the agent's spinner and wait text ("(⌐■_■) analyzing...",
  "" clears it; `tui_gateway/agent_callbacks.py::_agent_thinking_update` says
  "They are not reasoning blocks"). It sets `activity`, never a block.
- `reasoning.available` relays the assistant's own content, cut to 500 chars
  (`agent/turn_response_intake.py::_relay_thinking`); in every recorded turn it
  repeats the answer. It is ignored. Real reasoning arrives as `reasoning.delta`.

A MoA turn (`moa.*`) asks reference models before the aggregator answers.
Each `moa.reference` is a block of its own, a thinking row labelled
`◇ Reference 1/3 — <model>` whose text the details view shows, as Hermes' Ink
TUI keeps it; `moa.progress` and an aggregator `moa.phase` set `moa`, the
words the working row adds (`MoA: refs 2/3`, `MoA: aggregating…`), until the
turn ends.

Nothing here is written to disk.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import json
import re
import time
from typing import Any

from ..plugin_bundle.omh.hud_text import compact_count, elapsed_text
from .dag_block import DagBlock, rows as dag_rows
from .diff_view import DIFF_FILE, FILE_ARROW, DiffLine, diff_rows, parse_inline_diff
from .gateway import Event
from . import gateway_contract as contract
from .gateway_contract import TOOL_CALL_BRIDGE
from .markdown import MarkdownState, clean_text, render_lines, wrap_prefixed
from .style import NO_COLOR, Line, Span, Style, fill
from .slash import slash_spans, slash_token_ranges
from .theme import TOOL_FAMILIES, Theme, kind_style, on_band
from .width import cell_width, line_width, truncate, truncate_left, truncate_line

TOOL_GENERATING = "generating"
TOOL_RUNNING = "running"
TOOL_OK = "ok"
TOOL_ERROR = "error"
TOOL_DENIED = "denied"
TOOL_INTERRUPTED = "interrupted"  # still open when its group closed: it never reported a result
TOOL_RECORDED = "recorded"  # a resumed session's call: Hermes' record says what ran, not how it ended

NOTICE_INFO = "info"
NOTICE_OK = "ok"  # something the person allowed went ahead
NOTICE_WARN = "warn"
NOTICE_ERROR = "error"
# What a command that failed printed: on the red band in the error colour, as a failed tool's output lines are,
# with no mark of its own (the command's `✗` line under it has the one mark).
OUTPUT_FAILED = "failed"

INTERRUPTED_NOTICE = "Interrupted."
FAILED_NOTICE = "The turn ended with an error."
# The first row a full redraw prints when `retake_tail` left the session's earlier blocks out; once the cap
# below has dropped blocks, /history no longer holds them all, and the row says how many it does.
LEFT_OUT_NOTICE = "⋯ {earlier} · /history shows all"
LEFT_OUT_DROPPED_NOTICE = "⋯ {earlier} · /history shows the last {held}"
# /history's first row once the cap below has dropped blocks.
DROPPED_NOTICE = "⋯ {earlier} no longer held"
# The most blocks a transcript holds (Hermes' own TUI keeps 800 messages). Past it the oldest blocks already
# printed are dropped: they stay in the terminal's scrollback until a full redraw clears it, and /history no
# longer has them.
BLOCK_CAP = 2000

USER_MARK = "❯ "  # the composer's mark (`composer.PROMPT`), dim, before your prompt's dim text, on its band
FROM_QUEUE_TAG = "⧗ from queue"  # on a prompt the queue sent once the turn before it ended
# A steer the person sent: SENT until Hermes answers, then QUEUED (Hermes took it: it reads it after its next
# tool call, or sends it as the next prompt while compressing, and says the same for both) or REFUSED.
STEER_MARK = "↪ "
STEER_SENT = "sent"
STEER_QUEUED = "queued"
STEER_REFUSED = "refused"
STEER_REFUSED_MARK = "⧗ "
COMMAND_MARK = USER_MARK  # a command the person ran, echoed in the hint colour above what it printed
# What a call or a command printed hangs under its row behind `  ⎿  `, and its later rows line up with the words.
OUTPUT_MARK = "⎿  "
OUTPUT_INDENT = "  "
# The rows a command's output shows under its echo; past them one row counts the rest (rows at that width, so the
# count changes with it), which Ctrl+O's details view shows.
OUTPUT_PREVIEW_ROWS = 12
OUTPUT_MORE = "… +{count} {noun} · ctrl+o shows all"
# What a tool's output or a diff cut short says after its count: the key whose view shows the rest.
SHOWS_ALL = " · ctrl+o shows all"
COLLAPSED_MARK = "▸"
EXPANDED_MARK = "▾"
ASSISTANT_MARK = "● "
ASSISTANT_INDENT = "  "
# Who a reply is from: a header row `⚚ Hermes · <model>` over the reply (owner's variant B of 2026-10-28); with
# ASSISTANT_HEADER False, variant A: `⚚ ` in the `● `'s place on the reply's first row and no header.
AGENT_MARK = "⚚"
AGENT_NAME = "Hermes"
ASSISTANT_HEADER = True
# A call's mark by its state: a shape of its own for each, in its state's colour, so the colour is never the only
# signal. Running in `running` (the delegation view's running blue), done green, failed or denied red; dim for a
# call cut off, one still being written, and a resumed session's call, whose outcome its record does not keep.
TOOL_MARKS = {
    TOOL_RUNNING: "○", TOOL_OK: "●", TOOL_ERROR: "✗", TOOL_DENIED: "✗", TOOL_INTERRUPTED: "▪", TOOL_RECORDED: "●",
    TOOL_GENERATING: "◌",
}
RAIL = "  "  # the left rail of a prompt, a tool call or a reply: a cell painted in the block's colour, and a space
GUTTER = Style(gutter=True)  # a rail's or a reply margin's cells, which the pager's copy leaves out
# A running tool's mark alternates the running blue and dim this often, counted from its own start, so calls that run
# side by side pulse each on its own. Only the live region is drawn with a clock; scrollback gets the settled mark.
PULSE_SECONDS = 0.5
# An `omh_memory` call that recalled something sweeps one band of the dag-ulw aura across its output rows as it
# completes, while its group is still live; it moves only where the aura does (`Transcript.live_lines`'s `glint`), and
# a row in scrollback is drawn as it always is.
MEMORY_TOOL = "omh_memory"
RECALL_GLINT_SECONDS = 0.9
RECALL_GLINT_CELLS = 8
RECALL_TYPE_CELLS = 12  # a recalled record's type column at most: its summary is what the row is for
DETAIL_INDENT = "  "
COLUMN_GAP = "  "


@dataclass
class UserBlock:
    text: str
    done: bool = True
    from_queue: bool = False
    # The command and skill names a `/name` token in `text` resolved to as it was sent, drawn bold in their colour;
    # for a prompt from the session's history (`recorded`), the names its catalog has (`resolve_recorded_prompts`).
    known: frozenset[str] = frozenset()
    recorded: bool = False
    images: tuple[str, ...] = ()  # the labels of the images it went with, `[Image #1]`, one `⎿` row each under it


@dataclass
class SteerBlock:
    """A steer the person sent (`text`) and what came of it (`state`; for STEER_REFUSED, `outcome` says what).

    `agent` names the subagent it was for; "" is the main turn.
    """

    text: str
    state: str = STEER_SENT
    outcome: str = ""
    agent: str = ""
    done: bool = True


@dataclass
class NoticeBlock:
    text: str
    level: str = NOTICE_INFO
    done: bool = True
    one_line: bool = False  # a background notice (`review_line`): one dim row, cut with `…`, never wrapped
    mark: str = ""  # a catch row's `✦ OMH`, drawn before `text` in the launch look's colours (`Theme.catch_mark`)


@dataclass
class CommandBlock:
    """A command the person ran (`command`, as typed), and what it printed under it, each part with its level.

    Open (`done` False) while the command may still print; the app closes it
    once the command's calls are answered, and appending any other block
    closes it too. `whole` keeps the output uncut.
    """

    command: str
    parts: list[tuple[str, str]] = field(default_factory=list)
    whole: bool = False
    done: bool = False


@dataclass
class AssistantBlock:
    text: str = ""
    done: bool = False
    model: str | None = ""  # the session's model as it began (`Transcript.model`); None: not known (a resumed reply)


@dataclass
class TurnSummaryBlock:
    """The line that closes a turn: how long it took, its tool calls, and what it wrote (None when unknown)."""

    seconds: float
    tools: int
    output_tokens: int | None = None
    done: bool = True
    waited: float = 0.0  # the part of `seconds` a question Hermes asked waited on the person


@dataclass
class ThinkingBlock:
    text: str = ""
    done: bool = False
    started_at: float | None = None
    ended_at: float | None = None
    label: str = ""  # a MoA reference's header, shown in place of "thought for"; "" for the model's own reasoning


@dataclass
class ToolRow:
    tool_id: str
    name: str
    args_summary: str = ""
    status: str = TOOL_GENERATING
    started_at: float | None = None
    duration_s: float | None = None
    summary: str = ""
    # An edit's `inline_diff` as Hermes sent it, UTF-8 encoded, parsed when drawn (`diff_lines`). Encoded, because
    # a str holding one character past Latin-1 (every Hermes diff has `┊` and `→`) takes two bytes for each of
    # its characters, which made the diff held as a str larger than the parsed lines; as bytes it is about half.
    # `surrogatepass` both ways: JSON can carry a lone surrogate, which plain UTF-8 refuses to encode.
    inline_diff: bytes = b""
    diff_root: str = ""  # the session's working directory, which the diff's file names are shown relative to
    # The parsed diff, kept while the row's group is live (it is drawn again on every change); None otherwise.
    held_lines: tuple[DiffLine, ...] | None = field(default=None, repr=False, compare=False)
    # The first lines of what the tool printed (`TOOL_OUTPUT_KEEP` at most), and how many more it printed; for a
    # failed tool, its error's first line.
    output: tuple[str, ...] = ()
    output_more: int = 0
    # What the person answered a question this call asked, as (words, notice level), drawn under its row.
    answers: list[tuple[str, str]] = field(default_factory=list)
    # An interpreter fed its script through a heredoc, `python3 script · 23 lines` (`_heredoc_summary`): shown in its
    # row instead of `args_summary`, which the details view shows.
    script: str = ""
    # When an `omh_memory` recall that found records completed (`_recall`), on the transcript's clock; else None.
    recalled_at: float | None = None

    def diff_lines(self, hold: bool = False) -> tuple[DiffLine, ...]:
        """The diff colour-stripped and classified, its file names relative to `diff_root`.

        With `hold` the lines are kept for the next call that holds; without,
        any kept lines are let go and the diff is parsed from its bytes.
        """
        if hold and self.held_lines is not None:
            return self.held_lines
        lines = tuple(
            DiffLine(line.kind, FILE_ARROW.join(_relative(self.diff_root, side) for side in line.text.split(FILE_ARROW)))
            if line.kind == DIFF_FILE
            else line
            for line in parse_inline_diff(self.inline_diff.decode("utf-8", "surrogatepass"))
        )
        self.held_lines = lines if hold else None
        return lines

    def answer_refused(self) -> bool:
        """Whether an answer under the row says the call was refused or its question closed unanswered
        (`✗ denied · …`, `✗ timed out · …`: one at `NOTICE_ERROR`)."""
        return any(level == NOTICE_ERROR for _text, level in self.answers)


@dataclass
class ToolGroup:
    tools: list[ToolRow] = field(default_factory=list)
    done: bool = False


Block = (
    UserBlock | AssistantBlock | ThinkingBlock | ToolGroup | NoticeBlock | CommandBlock | TurnSummaryBlock | SteerBlock
    | DagBlock
)


# ── payload reading ───────────────────────────────────────────────────────


def as_text(value: object) -> str:
    """`value` when it is a string, else "": how every gateway payload field is read."""
    return value if isinstance(value, str) else ""


def _first_line(text: str) -> str:
    for line in text.split("\n"):
        cleaned = clean_text(line).strip()
        if cleaned:
            return cleaned
    return ""


def _last_line(text: str) -> str:
    for line in reversed(text.split("\n")):
        cleaned = clean_text(line).strip()
        if cleaned:
            return cleaned
    return ""


def _is_blank(line: str) -> bool:
    return not clean_text(line).strip()


def _source_lines(text: str) -> list[str]:
    """`text` split into lines without the blank lines it opens with (a segment starts "\\n\\n")."""
    lines = text.split("\n")
    while len(lines) > 1 and _is_blank(lines[0]):
        lines.pop(0)
    return lines


def _without_trailing_blanks(lines: list[str]) -> list[str]:
    while lines and _is_blank(lines[-1]):
        lines.pop()
    return lines


def _display_lines(text: str) -> list[str]:
    """Every source line as it shows now, the unfinished last one included."""
    return _without_trailing_blanks(_source_lines(text))


def _stable_lines(text: str) -> list[str]:
    """The source lines that can no longer change: complete ones, minus trailing blanks."""
    return _without_trailing_blanks(_source_lines(text)[:-1])


def _is_bare_error(text: str, error: str) -> bool:
    """True when the reply slot holds nothing but the backend's "Error: …" fallback (Ink's rule)."""
    stripped = text.strip()
    return not stripped or stripped == f"Error: {error}".strip() or stripped == error.strip()


def tool_result_status(result: object) -> str:
    """ok / error / denied from a `tool.complete` result (the wire carries no status flag of its own).

    An approval the user denied comes back from the terminal tool as `status: "blocked"`
    (recorded: exit_code -1, `user_summary` "You denied this command — it did not run.");
    the approval gates' own dicts say `approved: false` / `user_consent: false`. A clarify
    question that went unanswered says how its wait ended in `outcome` (`UNANSWERED_OUTCOMES`).
    """
    if not isinstance(result, dict):
        return TOOL_OK
    if (
        result.get("status") == "blocked" or result.get("approved") is False or result.get("user_consent") is False
        or result.get("outcome") in UNANSWERED_OUTCOMES
    ):
        return TOOL_DENIED
    if result.get("error") or result.get("success") is False or result.get("status") == "error":
        return TOOL_ERROR
    exit_code = result.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        return TOOL_ERROR
    return TOOL_OK


def _recall(name: str, result: object) -> dict[str, Any] | None:
    """The result of a completed call that recalled something, else None: an `omh_memory` recall whose result says it
    found records, read from the fields the tool writes (`action`, `status`, `record_count`), never from its words.
    Hermes hands a plugin tool's JSON over decoded; a string is decoded here."""
    if name != MEMORY_TOOL:
        return None
    try:
        found = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    count = found.get("record_count")
    if (found.get("action") == "recall" and found.get("status") == "found" and isinstance(count, int)
            and not isinstance(count, bool) and count > 0):
        return found
    return None


def _recall_lines(found: dict[str, Any]) -> tuple[str, ...]:
    """What a recall found, one line a record, from the records in its own result and nothing read anywhere else: its
    type, then its summary's first line (`decision  rotate refresh tokens per session`), the types padded to one
    column in terminal cells, a type cut to `RECALL_TYPE_CELLS` so the summary stays in sight. Both are written by a
    person or a model, so each goes through `_first_line` (escapes and control characters dropped, as for any tool
    output) and the row is cut to the width like any output row. A record with no summary is left out, and records
    that are not a list are none."""
    found_records = found.get("records")
    records = [(truncate(_first_line(as_text(record.get("record_type"))), RECALL_TYPE_CELLS),
                _first_line(as_text(record.get("summary"))))
               for record in (found_records if isinstance(found_records, list) else []) if isinstance(record, dict)]
    records = [(kind, summary) for kind, summary in records if summary]
    column = max((cell_width(kind) for kind, _summary in records), default=0)
    return tuple(f"{kind}{' ' * (column - cell_width(kind))}  {summary}" if column else summary
                 for kind, summary in records)


def _result_summary(payload: dict[str, Any]) -> str:
    summary = _first_line(as_text(payload.get("summary")))
    if summary:
        return summary
    result = payload.get("result")
    if isinstance(result, dict):
        for key in ("user_summary", "error", "output"):
            line = _first_line(as_text(result.get(key)))
            if line:
                return line
        return ""
    return _first_line(as_text(result))


# Hermes' tool bridge previews a call as a label, `<what> · <detail>` (6c61c3e27d `tools/tool_labels.py`), whose
# separator is the one the transcript puts between its own fields (`✻ 30s · 1 tool`).
BRIDGE_TOOLS = frozenset({"tool_call", "tool_search", "tool_describe"})
LABEL_SEPARATOR = " · "
# A dag-ulw node's goal and an omh_team helper's goal end with the marker that binds the child (`delegation_ledger`;
# a goal from before an update opens with it). Hermes' preview of a `delegate_task` call joins the goals, each cut to
# 40 characters (`2 tasks: Export API [dag:export/api] | Wire the export button to API [dag:ex...`), and a person
# reads the label: a whole marker goes wherever it is (a model may add text after it), and so does one the cut left a
# head of at the end of a goal, up to and including its `...`; the goal can end the row, or be followed by the `...` of
# Hermes' 80-character cut of the whole row. A head too short to name its kind (`[`, `[d`, `[omh`) goes only after the
# space OMH writes before a marker.
_GOAL_MARKERS = re.compile(
    r"\s?\[(?:dag:[a-z0-9][a-z0-9-]{0,31}/[a-z0-9][a-z0-9-]{0,31}|omh-team:[^\]|]{1,200})\]"
    r"|\s?\[(?:dag:[a-z0-9/-]*|omh-team:[a-z0-9/_-]*)\.\.\.(?=\s*\||[\s.]*\Z)"
    r"|\s\[(?:omh-team|omh-tea|omh-te|omh-t|omh-|omh|om|o|dag|da|d)?\.\.\.(?=\s*\||[\s.]*\Z)"
)


# The shell tools, and the interpreters among their commands that read a whole script from a heredoc on their stdin
# (`python3 - <<'PY'`): such a call is summarised by its interpreter and the script's length.
SHELL_TOOLS = TOOL_FAMILIES["shell"]
SCRIPT_INTERPRETERS = frozenset({"python", "python3", "node", "bash", "sh", "zsh", "ruby", "perl"})
_VERSIONED_PYTHON = re.compile(r"python3\.\d+")
# A heredoc's opener at the end of its line (`<<'PY'`, `<<-EOF`), never a here-string (`<<<`: no `<` before the
# two, and the word after them refuses a third) or a shift (`$((1<<3))`); `dash` is `<<-`'s (its terminator may be
# indented with tabs), `word` the terminator.
_HEREDOC = r"(?<!<)<<(?P<dash>-?)\s*(?P<quote>['\"]?)(?P<word>[A-Za-z_]\w*)(?P=quote)"
_HEREDOC_OPENER = re.compile(_HEREDOC + r"\s*$")
# A line as `_command_lines` reads it, left to right: arithmetic (`$(( 1 << n ))`, `((x << y))`) and a quoted string
# (`"a << b c"`, `'<<EOF'`), where `<<` is never a heredoc, then an `opener` anywhere (`cat <<'EOF' > notes.md`).
_SHELL_SPANS = re.compile(r"\$?\(\(.*?\)\)|'[^']*'|\"(?:[^\"\\]|\\.)*\"|(?P<opener>" + _HEREDOC + ")")
_COMMAND_SEPARATOR = re.compile(r"&&|\|\||;|\|")
_ENV_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=\S*")
UV_RUN_VALUE_OPTIONS = frozenset({"--with", "--python", "-p", "--project", "--directory", "--group", "--extra",
                                  "--env-file"})


def _script_interpreter(segment: str) -> str:
    """The interpreter one command runs to read its script from stdin (`python3` in `FOO=1 uv run python3 -u -`),
    or "" when the command is anything else (`cat > a.py`, `git commit -F -`, `python3 tool.py`)."""
    words = segment.split()
    while words and _ENV_ASSIGNMENT.fullmatch(words[0]):
        words.pop(0)
    if words[:1] == ["env"]:
        words.pop(0)
        while words and (_ENV_ASSIGNMENT.fullmatch(words[0]) or words[0].startswith("-")):
            words.pop(0)
    if words[:2] == ["uv", "run"]:
        words = words[2:]
        while words and words[0].startswith("-"):
            if words.pop(0) in UV_RUN_VALUE_OPTIONS and words:
                words.pop(0)
    if not words or not all(word.startswith("-") for word in words[1:]):  # a script file is no stdin script
        return ""
    name = words[0].rsplit("/", 1)[-1]
    return name if name in SCRIPT_INTERPRETERS or _VERSIONED_PYTHON.fullmatch(name) else ""


def _ends_heredoc(line: str, opener: re.Match[str]) -> bool:
    """Whether `line` is the terminator `opener` names (tab-indented after `<<-`)."""
    return (line.lstrip("\t") if opener["dash"] else line).rstrip() == opener["word"]


def _command_lines(lines: list[str]) -> int:
    """The commands among shell lines, one a line: a line ending in `\\` and the next are one, and a blank line, a `#`
    comment and a heredoc's body (up to its terminator) are none."""
    count = at = 0
    while at < len(lines):
        line, at = lines[at], at + 1
        while line.endswith("\\") and at < len(lines):
            line, at = line[:-1] + lines[at], at + 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        count += 1
        for opener in (span for span in _SHELL_SPANS.finditer(line) if span["opener"]):
            while at < len(lines) and not _ends_heredoc(lines[at], opener):
                at += 1
            at += 1
    return count


def _heredoc_summary(payload: dict[str, Any]) -> str:
    """`python3 script · 23 lines` for a shell call whose heredoc feeds an interpreter its script, with
    `+ N commands` for the commands around it; "" for any other call, which shows its own command (`_call_summary`).

    The heredoc's opener may be on any line (`set -e` before it, `cd /repo &&`
    before the interpreter); the script is the lines between it and its
    terminator. The commands counted are those chained before the interpreter
    and the lines around the script as `_command_lines` counts them, so another
    heredoc's body, a continued line and a comment add none. Another command
    fed a heredoc (`cat > a.py <<'EOF'`, `git commit -F - <<'MSG'`,
    `gh pr create --body-file - <<'EOF'`), a here-string (`<<<`) and a shift
    (`$((1<<3))`) are not scripts.
    """
    args = payload.get("args")
    command = as_text(args.get("command")) if isinstance(args, dict) else ""
    if as_text(payload.get("name")) not in SHELL_TOOLS:
        return ""
    lines = command.rstrip("\n").split("\n")
    found = next(((index, opener) for index, line in enumerate(lines) if (opener := _HEREDOC_OPENER.search(line))),
                 None)
    if found is None:
        return ""
    index, opener = found
    head = index
    while head and lines[head - 1].endswith("\\"):  # the opener's command, continued from the lines above
        head -= 1
    continued = "".join(line[:-1] for line in lines[head:index])
    segments = _COMMAND_SEPARATOR.split(continued + lines[index][: opener.start()])
    interpreter = _script_interpreter(segments[-1])
    terminator = next((at for at in range(index + 1, len(lines)) if _ends_heredoc(lines[at], opener)), None)
    if not interpreter or terminator is None:
        return ""
    body = terminator - index - 1
    others = len(segments) - 1 + _command_lines(lines[:head]) + _command_lines(lines[terminator + 1 :])
    around = f" + {others} command{'' if others == 1 else 's'}" if others else ""
    return f"{interpreter} script · {body} line{'' if body == 1 else 's'}{around}"


def _args_summary(payload: dict[str, Any]) -> str:
    summary = _call_summary(payload)
    return _GOAL_MARKERS.sub("", summary).strip() if as_text(payload.get("name")) == "delegate_task" else summary


def _call_summary(payload: dict[str, Any]) -> str:
    context = _first_line(as_text(payload.get("context")))
    if context and as_text(payload.get("name")) in BRIDGE_TOOLS:
        return context.replace(LABEL_SEPARATOR, ": ", 1)  # the transcript's own field separator: `· 1 tool` is a count
    if context:
        return context
    args = payload.get("args")
    if isinstance(args, dict):
        for value in args.values():
            line = _first_line(as_text(value))
            if line:
                return line
    return ""


def _duration(payload: dict[str, Any], row: ToolRow, now: float, waited: float = 0.0) -> float | None:
    """How long the tool ran: Hermes' `duration_s`, else since its start, less the `waited` seconds a question
    it was blocked on waited on the person (both clocks count that wait; `Transcript.waited_within`)."""
    value = payload.get("duration_s")
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return max(0.0, float(value) - waited)
    if row.started_at is not None:
        return max(0.0, now - row.started_at - waited)
    return None


def _earlier(count: int) -> str:
    return f"{count} earlier {'message' if count == 1 else 'messages'}"


# Where a tool's printed text is in its result, in order; a failed tool's error first.
_OUTPUT_KEYS = ("output", "stdout", "content", "text")
_ERROR_KEYS = ("error", "stderr", "user_summary", "output")
# A denied call says so in the person's words first; `error` there is what Hermes told the model.
_DENIED_KEYS = ("user_summary", "error", "output")
DENIED_LINE = "denied"  # a denied call whose result says nothing more
CLARIFY_TOOL = "clarify"  # the Hermes tool a clarify question comes from
# Hermes' clarify `outcome` for a question that went unanswered (beside `submitted`), worded for the row under its ✗.
UNANSWERED_OUTCOMES = {"cancelled": "cancelled", "timed_out": "timed out", "undelivered": "not delivered"}
TOOL_OUTPUT_ROWS = 3  # shown under a tool row; the details view shows up to TOOL_OUTPUT_KEEP
TOOL_OUTPUT_KEEP = 40


def _tool_output(result: object, status: str, closed_said: bool = False) -> tuple[tuple[str, ...], int]:
    """(lines, how many more) of what a tool printed: its first lines; for a failed or denied tool, one line, its
    reason's first.

    A failed tool whose result names no reason, only what it printed (Hermes' terminal tool reports a non-zero
    exit that way: `output` and `exit_code`, `error` None), gives the end of that instead, blank lines left out:
    a test run's summary is its last lines. `_output_rows` shows a failed tool's lines from their end.
    With `closed_said` (an answer under the row says how the question closed) an unanswered clarify gives no
    outcome word (`timed out`); a notice of Hermes' saying why is still its line.
    """
    if isinstance(result, str):
        found = [("text", result)]
    elif isinstance(result, dict):
        keys = _ERROR_KEYS if status == TOOL_ERROR else _DENIED_KEYS if status == TOOL_DENIED else _OUTPUT_KEYS
        found = [(key, as_text(result.get(key))) for key in keys]
        if status == TOOL_DENIED:  # a clarify question's: why its wait ended, else how
            outcome = "" if closed_said else UNANSWERED_OUTCOMES.get(as_text(result.get("outcome")), "")
            found.append(("notice", as_text(result.get("notice")) or outcome))
    else:
        return (), 0
    key, text = next(((key, candidate) for key, candidate in found if candidate.strip()), ("", ""))
    lines = [clean_text(line).rstrip() for line in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    if status == TOOL_ERROR and key == "output":
        printed = [line for line in lines if line.strip()]
        return tuple(printed[-TOOL_OUTPUT_KEEP:]), max(len(printed) - TOOL_OUTPUT_KEEP, 0)
    if status in (TOOL_ERROR, TOOL_DENIED):
        return tuple(lines[:1]), 0
    return tuple(lines[:TOOL_OUTPUT_KEEP]), max(len(lines) - TOOL_OUTPUT_KEEP, 0)


# The file Hermes' `skill_view` names when it read the skill itself (its repeat-view stub says so too).
SKILL_FILE = "SKILL.md"


def _read_summary(name: str, result: object) -> tuple[str, ...]:
    """One line for what a read or a load returned, shown in place of its first lines; () for any other call.

    `read_file` counts the lines of its `content` (a binary or image read has
    none to count); `skill_view` names the skill, and the file in it when it
    read one; `search_files` gives its `total_count`, with `+` when that is a
    lower bound, as files when it listed only files, and the first line of
    Hermes' `warning` under it when it gave one.
    """
    if not isinstance(result, dict):
        return ()
    if name == "read_file":
        content = result.get("content")
        if not isinstance(content, str) or result.get("is_binary") or result.get("is_image"):
            return ()
        lines = content.split("\n")
        if lines[-1] == "":
            lines.pop()
        return (f"Read {len(lines)} line{'' if len(lines) == 1 else 's'}",)
    if name == "skill_view":
        skill = _first_line(as_text(result.get("name")))
        file = _first_line(as_text(result.get("file")))
        if not skill:
            return ()
        return (f"loaded {file} from skill {skill}" if file and file != SKILL_FILE else f"loaded skill {skill}",)
    if name == "search_files":
        total = result.get("total_count")
        if not isinstance(total, int) or isinstance(total, bool):
            return ()
        files = "files" in result and "matches" not in result and "matches_text" not in result
        noun = ("file" if total == 1 else "files") if files else ("match" if total == 1 else "matches")
        count = f"{total}{'+' if result.get('total_count_is_lower_bound') else ''} {noun}"
        warning = _first_line(as_text(result.get("warning")))
        return (count, warning) if warning else (count,)
    return ()


def _relative(root: str, path: str) -> str:
    """`path` relative to the directory `root` when it lies inside it."""
    root = root.rstrip("/")
    prefix = root + "/" if root else ""  # "/" itself is no prefix: every absolute path stays absolute
    return path[len(prefix):] if prefix and path.startswith(prefix) and len(path) > len(prefix) else path


def _find_row(group: ToolGroup, tool_id: str) -> ToolRow | None:
    for row in group.tools:
        if tool_id and row.tool_id == tool_id:
            return row
    return None


def _drafted_row(group: ToolGroup, name: str) -> ToolRow | None:
    """The first `tool.generating` row for `name` that no `tool.start` has claimed yet, else the first unclaimed
    draft of Hermes' `tool_call` bridge, whose call starts under the name of the tool it reached."""
    drafts = [row for row in group.tools if row.status == TOOL_GENERATING and not row.tool_id]
    named = next((row for row in drafts if row.name == name), None)
    return named or next((row for row in drafts if row.name == TOOL_CALL_BRIDGE), None)


# ── rendering ─────────────────────────────────────────────────────────────


def _text_rows(
    text: str, style: Style, first: Line, rest: Line, width: int, max_rows: int | None = None
) -> list[Line]:
    """Plain text (no markdown), each source line wrapped, `first` before the very first row.

    Each source line wraps on its own, so with `max_rows` only the last lines
    that cover that many rows are wrapped; the rows end as all of them would.
    """
    wrapped: list[list[Line]] = []  # each source line's rows, the last line first
    count = 0
    lines = _without_trailing_blanks(_source_lines(text))
    for index in range(len(lines) - 1, -1, -1):
        if max_rows is not None and count >= max_rows:
            break
        source = lines[index]
        if _is_blank(source):
            rows: list[Line] = [()]  # never the first row: leading blank lines were dropped
        else:
            rows = wrap_prefixed((Span(clean_text(source), style),), first if index == 0 else rest, rest, width)
        wrapped.append(rows)
        count += len(rows)
    return [row for rows in reversed(wrapped) for row in rows]


def _user_rows(block: UserBlock, width: int, theme: Theme) -> list[Line]:
    """Your prompt on a dim rail, behind a dim `❯`, in the muted colour; a `/name` that resolved to a command or skill
    bold in its colour (`slash_spans`); `⧗ from queue` when the queue sent it; under it `  ⎿  [Image #1]` for each
    image it went with. Every row, a wrapped or blank one too, runs on `theme.prompt_band` to the right edge, its words
    measured against the band (`on_band`)."""
    band = theme.prompt_band
    theme = on_band(theme, band) if band.bg is not None else theme
    inner = max(width - len(RAIL), 1)
    first, rest = (Span(USER_MARK, theme.dim),), (Span(" " * len(USER_MARK)),)
    rows: list[Line] = []
    for index, source in enumerate(_display_lines(block.text)):
        if _is_blank(source):
            rows.append(())
            continue
        spans = slash_spans(clean_text(source), block.known, theme.muted, theme.slash)
        rows.extend(wrap_prefixed(spans, first if index == 0 else rest, rest, inner))
    if block.from_queue and rows:
        tag: Line = (Span(COLUMN_GAP + FROM_QUEUE_TAG, theme.muted),)
        if line_width(rows[0]) + line_width(tag) <= inner:
            rows[0] = (*rows[0], *tag)
    rows.extend((*_output_leads(theme)[0], Span(label, theme.muted)) for label in block.images)
    rows = [_within((*_rail(theme.dim, faint=True), *row), width) for row in rows]
    return _banded(rows, band) if band.bg is not None else rows


def _awaits_answer(block: Block) -> bool:
    """A held block that is not finished yet: a steer Hermes has not answered, a command still printing."""
    if isinstance(block, CommandBlock):
        return not block.done
    return isinstance(block, SteerBlock) and block.state == STEER_SENT


def _steer_rows(block: SteerBlock, width: int, theme: Theme) -> list[Line]:
    """`↪ steer · <text>` while it waits for Hermes, `↪ steer queued by Hermes · <text>` once taken, or the refusal.

    A subagent's steer names it before the text: `<agent>: <text>`.
    """
    text = _first_line(block.text)
    if block.agent:
        text = f"{block.agent}: {text}"
    if block.state == STEER_REFUSED:
        return [truncate_line((Span(f"{STEER_REFUSED_MARK}{block.outcome} · {text}", theme.warn),), width)]
    words = "steer queued by Hermes · " if block.state == STEER_QUEUED else "steer · "
    band = theme.prompt_band  # a message you sent mid-turn runs on your sent prompt's band, as the prompt does
    roles = on_band(theme, band) if band.bg is not None else theme
    row = truncate_line((Span(STEER_MARK, roles.muted), Span(words, roles.muted), Span(text, roles.text)), width)
    return _banded([row], band) if band.bg is not None else [row]


def _notice_style(level: str, theme: Theme) -> tuple[str, Style]:
    if level == NOTICE_OK:
        return "✓ ", theme.ok
    if level == NOTICE_ERROR:
        return "✗ ", theme.error
    if level == NOTICE_WARN:
        return "⚠ ", theme.warn
    return "· ", theme.muted


def _banded(rows: list[Line], band: Style) -> list[Line]:
    """`rows` on `band`: every span on its background and an erase to the right edge, so a copy has no trailing spaces."""
    return [(*(Span(span.text, replace(span.style, bg=band.bg, depth=band.depth)) for span in row), fill(band)) for row in rows]


def _outcome_band(level: str, theme: Theme) -> Style | None:
    """The band behind a row of `level`: green for what the person allowed, red for an error; None for the rest,
    or when the theme paints no band (no background was reported)."""
    band = {NOTICE_OK: theme.ok_band, NOTICE_ERROR: theme.error_band, OUTPUT_FAILED: theme.error_band}.get(level)
    return band if band is not None and band.bg is not None else None


def _catch_mark(mark: str, theme: Theme) -> tuple[Span, ...]:
    """A catch row's mark and the space after it: each cell in turn through `theme.catch_mark` (the logo's colours),
    or all in `brand` for a theme that carries none."""
    steps = theme.catch_mark or (theme.brand,)
    return tuple(Span(cell, steps[min(index, len(steps) - 1)]) for index, cell in enumerate(f"{mark} "))


def _catch_words(theme: Theme) -> Style:
    """What a catch row says: the launch look's label colour, or `muted` for a theme that carries none."""
    return theme.catch_words if theme.catch_mark else theme.muted


def _notice_rows(block: NoticeBlock, width: int, theme: Theme) -> list[Line]:
    if block.one_line:
        if block.mark:
            words = Span(" ".join(block.text.split()), _catch_words(theme))
            return [truncate_line((*_catch_mark(block.mark, theme), words), width)]
        return [truncate_line((Span(" ".join(block.text.split()), theme.faint),), width)]
    band = _outcome_band(block.level, theme)
    roles = on_band(theme, band) if band is not None else theme
    mark, style = _notice_style(block.level, roles)
    rows = _text_rows(block.text, style, (Span(mark, style),), (Span(" " * len(mark)),), width)
    return _banded(rows, band) if band is not None else rows


# Hermes' background review summary (`review.summary`): "💾 Self-improvement review: Skill 'x' created · Skill 'x'
# written (references/a.md) · Memory updated", in Hermes' English wording (`locales/en.yaml` display.review).
REVIEW_PREFIX = "💾"
REVIEW_LABEL = "Self-improvement review"  # Hermes' English label (`display.review.summary_callback`)
REVIEW_SKILL_RESULT = re.compile(r"Skill '(?P<name>[^']+)' (?P<verb>\w+)(?: \((?P<path>[^)]*)\))?$")
REVIEW_FILE_VERBS = {"written": "wrote", "removed": "removed"}


def review_line(text: str) -> str:
    """A background review summary as one row: what each skill went through, its name once, then the rest as Hermes
    worded it, `💾 skill x · created · wrote references/a.md · patched · Memory updated`. Hermes' English label
    (`REVIEW_LABEL`) is left out and parts that are only separators are dropped; text in another shape (another
    language) is otherwise kept as Hermes sent it."""
    body = text.strip().removeprefix(REVIEW_PREFIX).strip()
    head, colon, rest = body.partition(": ")
    said_by_hermes = colon and head.strip() == REVIEW_LABEL  # any other text before a colon is part of what it says
    parts = [part.strip() for part in (rest if said_by_hermes else body).split(" · ") if part.strip(" ·")]
    skills: dict[str, list[str]] = {}
    said: list[str] = []
    for part in parts:
        match = REVIEW_SKILL_RESULT.match(part)
        if match is None:
            said.append(part)
            continue
        verb, path = match["verb"], match["path"]
        done = f"{REVIEW_FILE_VERBS.get(verb, verb)} {path}" if path else verb
        if match["name"] not in skills:
            skills[match["name"]] = []
            said.append(match["name"])  # where the skill's words go, in the order Hermes said them
        if done not in skills[match["name"]]:
            skills[match["name"]].append(done)
    words = [f"skill {part} · {' · '.join(skills[part])}" if part in skills else part for part in said]
    return f"{REVIEW_PREFIX} {' · '.join(dict.fromkeys(words))}" if words else ""  # "" when it says nothing


TURN_DONE_MARK = "✻ "
# After a turn's wall-clock time, the part of it a question waited on the person, when that is a second or more.
TURN_WAITED = " ({elapsed} waiting on you)"


def _summary_rows(block: TurnSummaryBlock, width: int, theme: Theme) -> list[Line]:
    """`  ✻ 34s · 3 tools · ↓1.2k`: the turn's facts in one dim line under the reply's words (no tool count for none).

    The time is the turn's wall clock, with the wait on the person beside it
    (`✻ 30s (27s waiting on you)`) when that is a second or more. A line too
    narrow for all of it drops whole facts, the tokens first, then the tools,
    then the wait; the time stays, and is cut at the edge only where it does
    not fit alone.
    """
    elapsed = elapsed_text(block.seconds)
    waited = TURN_WAITED.format(elapsed=elapsed_text(block.waited)) if int(block.waited) >= 1 else ""
    tools = f"{block.tools} tool{'' if block.tools == 1 else 's'}" if block.tools else ""
    written = f"↓{compact_count(block.output_tokens)}" if block.output_tokens else ""
    lead: Line = (Span(ASSISTANT_INDENT), Span(TURN_DONE_MARK, theme.dim))
    done: Line = ()
    for facts in ((elapsed + waited, tools, written), (elapsed + waited, tools), (elapsed + waited,), (elapsed,)):
        done = (*lead, Span(" · ".join(fact for fact in facts if fact), theme.muted))
        if line_width(done) <= width:
            break
    return [truncate_line(done, width)]


_OUTPUT_GLYPHS = {NOTICE_WARN: "⚠ ", NOTICE_ERROR: "✗ "}


def _output_leads(theme: Theme) -> tuple[Line, Line]:
    """What goes before the first row of a call's or a command's output (`  ⎿  `), and before every later one."""
    return (Span(OUTPUT_INDENT), Span(OUTPUT_MARK, theme.dim)), (Span(OUTPUT_INDENT + " " * len(OUTPUT_MARK)),)


def _command_rows(block: CommandBlock, width: int, theme: Theme, expanded: bool) -> list[Line]:
    """`❯ /name arg` on the prompt's dim rail (a bare `❯` on the left edge is only ever the composer), then each part
    of its output under `⎿` in its level's colour (and glyph), cut unless `expanded`."""
    full, width = width, max(width - len(RAIL), 1)
    rows = wrap_prefixed((Span(block.command, theme.hint),), (Span(COMMAND_MARK, theme.dim),), (Span("  "),), width)
    rest = _output_leads(theme)[1]
    output: list[Line] = []
    for text, level in block.parts:
        band = _outcome_band(level, theme)
        roles = on_band(theme, band) if band is not None else theme
        style = {NOTICE_WARN: roles.warn, NOTICE_ERROR: roles.error, OUTPUT_FAILED: roles.error}.get(level, roles.text)
        lead = rest if output else _output_leads(roles)[0]
        part = _text_rows(_OUTPUT_GLYPHS.get(level, "") + text, style, lead, rest, width)
        output.extend(_banded(part, band) if band is not None else part)
    if not expanded and not block.whole and len(output) > OUTPUT_PREVIEW_ROWS:
        hidden = len(output) - OUTPUT_PREVIEW_ROWS
        more = OUTPUT_MORE.format(count=hidden, noun="row" if hidden == 1 else "rows")  # rows at this width
        output = [*output[:OUTPUT_PREVIEW_ROWS], truncate_line((*rest, Span(more, theme.muted)), width)]
    return [_within((*_rail(theme.dim, faint=True), *row), full) for row in rows + output]


def _marked(rows: list[Line], opens_block: bool, theme: Theme, width: int, model: str | None = "") -> list[Line]:
    """Assistant rows on the reply's rail in the skin's accent, every row at the reply's indent and the rail alone on
    a blank row, so a reply's rail is one line; none wider than `width`. A block opens with who wrote it: the header
    `⚚ Hermes · <model>` (bold in the rail's hue, the model muted, its last path segment), or with
    ASSISTANT_HEADER False a `⚚ ` on its first row."""
    rest: Line = (Span(ASSISTANT_INDENT, GUTTER),)
    rail = _rail(theme.brand)
    name = replace(theme.brand, bold=True)
    first, head = rest, []
    if opens_block and ASSISTANT_HEADER and rows:
        said = (Span(f" · {model.rsplit('/', 1)[-1]}", theme.muted),) if model else ()
        head = [_within((*rail, Span(f"{AGENT_MARK} {AGENT_NAME}", name), *said), width)]
    elif opens_block:
        first = (Span(f"{AGENT_MARK} ", name),)
    return head + [_within((*rail, *(first if opens_block and index == 0 else rest), *row), width) if row else rail[:1]
                   for index, row in enumerate(rows)]


def _reply_width(width: int) -> int:
    """The cells left for reply text beside its rail and margin."""
    return max(1, width - len(RAIL) - len(ASSISTANT_INDENT))


def _assistant_rows(block: AssistantBlock, width: int, theme: Theme) -> list[Line]:
    rows = render_lines(_display_lines(block.text), MarkdownState(), _reply_width(width), theme)[0]
    return _marked(rows, True, theme, width, block.model)


def _seconds(value: float) -> str:
    return f"{value:.1f}s"


def _thinking_rows(
    block: ThinkingBlock, width: int, theme: Theme, expanded: bool, max_rows: int | None = None
) -> list[Line]:
    mark = EXPANDED_MARK if expanded else COLLAPSED_MARK
    if block.label:
        head: Line = (Span(f"{mark} {block.label}", theme.thinking),)
    elif block.done:
        header = f"{mark} thought"
        if block.started_at is not None and block.ended_at is not None:
            header += f" for {_seconds(max(0.0, block.ended_at - block.started_at))}"
        head = (Span(header, theme.thinking),)
    elif expanded:
        head = (Span(f"{mark} thinking…", theme.thinking),)
    else:
        head = (Span(f"{mark} thinking… ", theme.thinking), Span(_last_line(block.text), theme.muted))
    rows = [truncate_line(head, width)]
    if expanded:
        indent: Line = (Span(DETAIL_INDENT),)
        rows.extend(_text_rows(block.text, theme.thinking, indent, indent, width, max_rows))
    return rows


def _pulse_dim(tool: ToolRow, now: float | None) -> bool:
    """Whether a running tool's mark is in its dim half at `now`; never without a clock (scrollback, reduced motion)."""
    if now is None or tool.started_at is None:
        return False
    return int(max(0.0, now - tool.started_at) / PULSE_SECONDS) % 2 == 1


def _glint_band(tool: ToolRow, now: float | None) -> float | None:
    """How far the band sweeping a recall's output rows has gone at `now`, from 0 as the call completes to 1
    `RECALL_GLINT_SECONDS` later. None with no clock, for any other call, and once the sweep is over."""
    if now is None or tool.recalled_at is None:
        return None
    elapsed = now - tool.recalled_at
    return elapsed / RECALL_GLINT_SECONDS if 0 <= elapsed < RECALL_GLINT_SECONDS else None


def _glinted(text: str, style: Style, band: int, theme: Theme) -> list[Span]:
    """`text` in `style`, but its cells under the band (`RECALL_GLINT_CELLS` from `band`) in the aura's steps across
    the band, not bold: the words stay the words."""
    spans: list[Span] = []
    at = 0
    for char in text:
        offset = at - band
        painted = style
        if 0 <= offset < RECALL_GLINT_CELLS and theme.aura:
            painted = replace(theme.aura[offset * (len(theme.aura) - 1) // (RECALL_GLINT_CELLS - 1)], bold=False)
        if spans and spans[-1].style == painted:
            spans[-1] = Span(spans[-1].text + char, painted)
        else:
            spans.append(Span(char, painted))
        at += cell_width(char)
    return spans


def rail_cell(style: Style, faint: bool = False) -> Span:
    """A rail's painted cell: a space in `style`'s colour, reversed so it shows without colour too. It holds no bar
    glyph, so a terminal's selection copies none. Without colour a `faint` one (your prompt's, which its `❯` marks
    anyway) is left unpainted, so a reply's bar still differs from it: dim on a reversed space showed no difference
    in Terminal.app (measured for #2371)."""
    plain = faint and style.depth == NO_COLOR
    return Span(RAIL[0], Style(fg=style.fg, reverse=not plain, depth=style.depth, gutter=True))


def _rail(style: Style, faint: bool = False) -> Line:
    """The rail's cells: the painted one (`rail_cell`) and the space before the text."""
    return (rail_cell(style, faint), Span(RAIL[1:], GUTTER))


def _within(row: Line, width: int) -> Line:
    """`row` as it is, or cut to `width` on a terminal too narrow for the rail and what hangs on it."""
    return row if line_width(row) <= width else truncate_line(row, width)


def _state_style(status: str, theme: Theme, dim: bool = False) -> Style:
    """A call's state as a colour: its mark's (its rail is `_rail_style`'s)."""
    if status == TOOL_OK:
        return theme.ok
    if status in (TOOL_ERROR, TOOL_DENIED):
        return theme.error  # the line under a denial says it was denied
    if status == TOOL_RUNNING:
        return theme.dim if dim else theme.running
    return theme.dim


def _rail_style(status: str, theme: Theme) -> Style:
    """A call's rail: red when it failed or was denied, as its band is, else the launch look's accent."""
    return theme.error if status in (TOOL_ERROR, TOOL_DENIED) else theme.accent


def _tool_mark(status: str, theme: Theme, dim: bool = False) -> Span:
    return Span(TOOL_MARKS.get(status, TOOL_MARKS[TOOL_GENERATING]), _state_style(status, theme, dim))


def _is_path(text: str) -> bool:
    """A single path argument (`/abs/x.py`, `~/x`, `./x`): its end names the file, so it is cut from the left."""
    return " " not in text and text.startswith(("/", "~/", "./", "../"))


def _tool_row(tool: ToolRow, width: int, theme: Theme, now: float | None = None, expanded: bool = False) -> Line:
    """One line per call: `● name(args summary)` and its duration; the mark pulses while it runs, given `now`, and
    the summary is cut first (a path from the left). An interpreter's heredoc script reads as its `script` summary,
    and as the command itself when `expanded`."""
    mark = _tool_mark(tool.status, theme, tool.status == TOOL_RUNNING and _pulse_dim(tool, now))
    head: Line = (mark, Span(" "), Span(tool.name, kind_style(tool.name, theme)))
    tail: Line = ()
    if tool.duration_s is not None:
        tail = (Span(COLUMN_GAP + _seconds(tool.duration_s), theme.faint),)
    room = width - line_width(head) - line_width(tail) - len("()")
    args: Line = ()
    shown = tool.script if tool.script and not expanded else tool.args_summary
    if shown and room > 1:
        cut = truncate_left if _is_path(shown) else truncate
        args = (Span(f"({cut(shown, room)})", theme.muted),)
    return truncate_line((*head, *args, *tail), width)


def _output_rows(tool: ToolRow, width: int, theme: Theme, expanded: bool, now: float | None = None) -> list[Line]:
    """The tool's printed lines under its name, each cut to the width: three of them, or all kept with `expanded`.

    A failed tool's are its last ones, with the count of the rest above them
    (`_tool_output`). A denied call whose result gave no reason says
    `denied`, so a denial reads apart from a failure without colour, unless
    an answer under its row already says so (`ToolRow.answer_refused`).
    Given `now` (the live region, where the aura moves), a recall's rows
    carry the band that sweeps them once (`_glint_band`).
    """
    output = tool.output or ((DENIED_LINE,) if tool.status == TOOL_DENIED and not tool.answer_refused() else ())
    if not output:
        return []
    failed = tool.status in (TOOL_ERROR, TOOL_DENIED)
    shown = output if expanded else output[-TOOL_OUTPUT_ROWS:] if failed else output[:TOOL_OUTPUT_ROWS]
    hidden = len(output) - len(shown) + tool.output_more
    first, rest = _output_leads(theme)  # a failure's lines too: its mark and its rail say it failed
    texts = [Span(line, theme.faint) for line in shown]
    more = [Span(f"… +{hidden} line{'' if hidden == 1 else 's'}{SHOWS_ALL}", theme.faint)] if hidden else []
    ordered = [*more, *texts] if failed else [*texts, *more]
    swept = _glint_band(tool, now)
    band = None
    if swept is not None:  # it enters at the left of the words and leaves past the end of the longest
        extent = min(width - line_width(first), max(line_width((span,)) for span in ordered))
        band = int(swept * (extent + RECALL_GLINT_CELLS)) - RECALL_GLINT_CELLS
    return [truncate_line((*(rest if index else first),
                           *(_glinted(span.text, span.style, band, theme) if band is not None else (span,))), width)
            for index, span in enumerate(ordered)]


def _answer_rows(text: str, level: str, width: int, theme: Theme, marked: bool = True) -> list[Line]:
    """`  ⎿  ✓ allowed once · <command>`: what the person answered, under the call that asked, on its outcome's band;
    with no mark when not `marked` (the call's own row already says it failed: one `✗` per denial, round 2)."""
    band = _outcome_band(level, theme)
    roles = on_band(theme, band) if band is not None else theme
    mark, style = _notice_style(level, roles)
    mark = mark if marked else ""
    first, rest = _output_leads(roles)
    rows = _text_rows(text, style, (*first, Span(mark, style)), (*rest, Span(" " * len(mark))), width)
    return _banded(rows, band) if band is not None else rows


# The plumbing calls a run of which folds into one row: loading a skill (or a file in one), reading tool details.
PLUMBING_TOOLS = frozenset({"skill_view", "tool_describe"})
SKILL_TOOL = "skill_view"
FOLD_LABEL_SEPARATOR = " → "  # how Hermes labels a skill_view that read a file in a skill: `skill → references/x.md`


# The states of a plumbing call that loaded, or is loading, what it names: only these join a run. A failed or
# refused call keeps its row and says why; a draft names nothing yet and a cut-off call loaded nothing.
FOLDED_STATUSES = frozenset({TOOL_OK, TOOL_RECORDED, TOOL_RUNNING})


def _folds(tool: ToolRow) -> bool:
    """Whether a call joins a run of plumbing calls (`FOLDED_STATUSES`)."""
    return tool.name in PLUMBING_TOOLS and tool.status in FOLDED_STATUSES


def _units(tools: list[ToolRow], fold: bool = True) -> list[list[ToolRow]]:
    """The calls as rows: each run of consecutive plumbing calls one unit (`fold`), every other call a unit of its
    own."""
    units: list[list[ToolRow]] = []
    for tool in tools:
        if fold and _folds(tool) and units and _folds(units[-1][-1]):
            units[-1].append(tool)
        else:
            units.append([tool])
    return units


def _unit_status(unit: list[ToolRow]) -> str:
    """A unit's state: a folded run's is running while a member runs, else its last member's."""
    return TOOL_RUNNING if any(tool.status == TOOL_RUNNING for tool in unit) else unit[-1].status


def _loaded_label(tool: ToolRow) -> str:
    """A skill_view's skill, and the file it read in it: `omh-routing/skill-common-rail.md`."""
    skill, _arrow, file = tool.args_summary.partition(FOLD_LABEL_SEPARATOR)
    return f"{skill}/{file.rsplit('/', 1)[-1]}" if file else skill


def _folded_row(unit: list[ToolRow], width: int, theme: Theme, now: float | None) -> Line:
    """One row for a run of plumbing calls: `● Loaded 4 skills + tool details · a, b, c, d  3.5s`.

    The time is the members' summed, once none is running; the names are
    cut first. What each member printed (`loaded skill …`) is not repeated.
    """
    status = _unit_status(unit)
    running = next((tool for tool in unit if tool.status == TOOL_RUNNING), None)
    mark = _tool_mark(status, theme, running is not None and _pulse_dim(running, now))
    skills = [tool for tool in unit if tool.name == SKILL_TOOL]
    words = f"Loaded {len(skills)} skill{'' if len(skills) == 1 else 's'}" if skills else "Read tool details"
    if skills and any(tool.name != SKILL_TOOL for tool in unit):
        words += " + tool details"
    head: Line = (mark, Span(" "), Span(words, kind_style(SKILL_TOOL, theme)))
    durations = [tool.duration_s for tool in unit if tool.duration_s is not None]
    tail: Line = (Span(COLUMN_GAP + _seconds(sum(durations)), theme.faint),) if durations and running is None else ()
    names = ", ".join(label for label in (_loaded_label(tool) for tool in skills) if label)
    room = width - line_width(head) - line_width(tail) - len(LABEL_SEPARATOR)
    args: Line = (Span(LABEL_SEPARATOR + truncate(names, room), theme.muted),) if names and room > 1 else ()
    return truncate_line((*head, *args, *tail), width)


def _tool_rows(
    group: ToolGroup, width: int, theme: Theme, expanded: bool, now: float | None = None, glint: bool = False,
) -> list[Line]:
    """Each call on a rail (`_rail_style`): its own row (what ran, on what), what the person answered it right
    under that, and what it printed under them, a blank row between two calls; a run of plumbing calls is one row,
    unfolded again by `expanded`. A group with no call shows nothing. With `glint` (the aura moves) and `now`, a
    recall's output rows carry the band that sweeps them once."""
    inner = max(width - len(RAIL), 1)
    rows: list[Line] = []
    for unit in _units(group.tools, fold=not expanded):
        status = _unit_status(unit)
        if not expanded and _folds(unit[0]):
            own = [_folded_row(unit, inner, theme, now)]
        else:
            tool = unit[0]
            own = [_tool_row(tool, inner, theme, now, expanded)]
            said = tool.status in (TOOL_ERROR, TOOL_DENIED)  # its own `✗` says it: the answer under it adds none
            own += [row for text, level in tool.answers
                    for row in _answer_rows(text, level, inner, theme, marked=not (said and level == NOTICE_ERROR))]
            if expanded and tool.summary and tool.summary not in tool.output[:1]:  # a failure's line is said once
                summary_first, summary_rest = _output_leads(theme)
                own.extend(wrap_prefixed((Span(tool.summary, theme.faint),), summary_first, summary_rest, inner))
            lines = tool.diff_lines(hold=not group.done) if tool.inline_diff else ()
            if lines:  # a diff keeps its own bands
                own.extend(diff_rows(lines, inner, theme, full=expanded, lead=_output_leads(theme)[0]))
            else:
                own.extend(_output_rows(tool, inner, theme, expanded, now if glint else None))
        rail = _rail(_rail_style(status, theme))
        rows.extend([*([()] if rows else []), *(_within((*rail, *row), width) for row in own)])
    return rows


def block_rows(
    block: Block, width: int, theme: Theme, expanded: bool = False, max_rows: int | None = None,
    now: float | None = None, glint: bool = False,
) -> list[Line]:
    """The rows one block shows at `width`; `expanded` adds thinking text, tool result summaries, whole diffs.

    `max_rows` lets a block whose rows end the same either way (thinking
    text) render only its last rows; the rows returned may start lower.
    `now` pulses running tools' marks; without it every mark is settled.
    With `glint` too, a recall's output rows carry their one band.
    """
    width = max(1, width)
    if isinstance(block, UserBlock):
        return _user_rows(block, width, theme)
    if isinstance(block, NoticeBlock):
        return _notice_rows(block, width, theme)
    if isinstance(block, CommandBlock):
        return _command_rows(block, width, theme, expanded)
    if isinstance(block, TurnSummaryBlock):
        return _summary_rows(block, width, theme)
    if isinstance(block, SteerBlock):
        return _steer_rows(block, width, theme)
    if isinstance(block, AssistantBlock):
        return _assistant_rows(block, width, theme)
    if isinstance(block, ThinkingBlock):
        return _thinking_rows(block, width, theme, expanded, max_rows)
    if isinstance(block, DagBlock):
        return dag_rows(block, width, theme)
    return _tool_rows(block, width, theme, expanded, now, glint)


# ── the model ─────────────────────────────────────────────────────────────


class Transcript:
    """Blocks in order, the turn's transient state, and how far the terminal has been handed lines."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, under_output: bool = False) -> None:
        """`under_output`: its first lines go under lines already printed (another session's), so they open with
        the spacer every block opens with."""
        self.cwd = ""  # the session's working directory; paths inside it are shown relative to it
        self.model = ""  # the session's model, named on the header of each reply begun under it
        self.blocks: list[Block] = []
        self.activity = ""  # spinner / wait text from thinking.delta; "" when none
        self.status = ""  # the last status.update text of the running turn; "" when none
        self.moa = ""  # a MoA turn's progress (`MoA: refs 2/3`), added to the working row; "" when none
        self.running = False
        self.details_expanded = False
        self._clock = clock
        self._waits: list[tuple[float, float]] = []  # questions' waits on the person that ended: (began, ended)
        self._waiting_since: float | None = None  # when the wait open now began
        self._turn_start = 0
        self._cursor = 0  # first block not fully taken
        self._cursor_lines = 0  # source lines of blocks[_cursor] already taken (assistant text)
        self._cursor_state = MarkdownState()  # markdown state after those lines
        self._taken_any = under_output  # whether any line has been taken (a spacer goes above the next block)
        self._left_out = 0  # blocks `retake_tail` left out: the next take opens with LEFT_OUT_NOTICE
        # The rows `retake_tail` measured for the blocks it keeps, from `_cursor` on, so the take after it does not
        # render them again: (version, width, theme, rows per block), good only while nothing has changed since.
        self._measured: tuple[int, int, Theme, list[list[Line]]] | None = None
        self.dropped = 0  # blocks BLOCK_CAP dropped from the front
        # Where the last take's lines hold the first row of the newest prompt in them (not the blank row above it);
        # None when that take held no prompt.
        self.prompt_row: int | None = None
        # Blocks about a live one (a steer, an answer to Hermes, a command's echo), waiting for a block boundary
        # (`add_steer`, `add_command`).
        self._held: list[Block] = []
        # The command whose output is being written: a notice or an output lands under its echo while it is open.
        # `add_command` sets it; the app points it at the command whose handler or call answer is running.
        self.command: CommandBlock | None = None
        # Moves with every change to what `live_lines` draws; its last answer is kept with the version, width,
        # row limit and theme it was for, so a frame that changed nothing (a spinner tick) renders nothing.
        self._version = 0
        self._live_held: tuple[tuple[int, int, int | None, tuple[bool, ...]], Theme, list[Line]] | None = None
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "message.start": self._on_message_start,
            "message.delta": self._on_message_delta,
            "message.interim": self._on_message_interim,
            "message.complete": self._on_message_complete,
            "thinking.delta": self._on_thinking_delta,
            "reasoning.delta": self._on_reasoning_delta,
            "reasoning.available": self._on_reasoning_available,
            "tool.generating": self._on_tool_generating,
            "tool.start": self._on_tool_start,
            "tool.complete": self._on_tool_complete,
            "status.update": self._on_status_update,
            "moa.reference": self._on_moa_reference,
            "moa.progress": self._on_moa_progress,
            "moa.phase": self._on_moa_phase,
        }

    # ── input ──

    def apply(self, event: Event) -> None:
        """Fold one gateway event into the transcript; other event types are not the transcript's."""
        handler = self._handlers.get(event.type)
        if handler is not None:
            handler(event.payload if isinstance(event.payload, dict) else {})
            self._version += 1

    def add_user(
        self, text: str, from_queue: bool = False, known: frozenset[str] = frozenset(), recorded: bool = False,
        images: tuple[str, ...] = (),
    ) -> None:
        """Your prompt; `known` names the commands and skills a `/name` in it is drawn for (`slash.known_names`);
        `recorded` for one from the session's history; `images` the labels of the images it went with."""
        self._append(UserBlock(text, from_queue=from_queue, known=known, recorded=recorded, images=images))

    def resolve_recorded_prompts(self, known: frozenset[str], width: int, theme: Theme, max_rows: int) -> bool:
        """The history's prompts take `known`, the session's catalog, which answers after they are drawn (`App.startup`
        draws a resumed session's history at once); True when a `/name` resolves otherwise now in one that
        `retake_tail(width, theme, max_rows)` prints again, so a full redraw shows it. One above that tail is
        only in /history, which draws it with `known` from now on."""
        moved = -1
        for index, block in enumerate(self.blocks):
            if isinstance(block, UserBlock) and block.recorded and block.known != known:
                if slash_token_ranges(block.text, block.known) != slash_token_ranges(block.text, known):
                    moved = index
                block.known = known
                self._version += 1
        return moved >= 0 and moved >= self._tail_start(width, theme, max_rows)

    def add_steer(self, text: str, agent: str = "") -> SteerBlock:
        """A steer the person just sent, held until Hermes answers and the transcript reaches a block boundary.

        A steer never closes a live block (closing a tool group would mark its
        running calls cut off, and a streaming reply would split): it is shown
        under the live blocks and written into the transcript at the next
        boundary after Hermes answered, which for a steer Hermes reads after
        its next tool call is where it reads it. Change its `state` with
        `steer_answered`. `agent` names the subagent a steer from the agent
        list is for.
        """
        block = SteerBlock(text, agent=agent)
        self._held.append(block)
        self._write_held()
        self._version += 1
        return block

    def add_answer(self, text: str, level: str, clarify: bool = False) -> None:
        """What the person answered Hermes (`✓ allowed once · <command>`), under the tool call it was about.

        A request does not name the call that asked, so the answer goes under
        the live group's last running call: its last running `clarify` for a
        clarify question's answer (`clarify`), its last running other call for
        the rest. With no such call it is a row of its own: a tool group still
        live has printed nothing yet, so it goes in above it; above any other
        live block it waits for the next boundary, as a steer does, rather than
        closing it.
        """
        group = self._live(ToolGroup)
        tools = group.tools if group is not None else []
        asked = [row for row in tools if row.status == TOOL_RUNNING and (row.name == CLARIFY_TOOL) == clarify]
        if asked:
            asked[-1].answers.append((text, level))
            self._version += 1
            return
        block = NoticeBlock(text, level)
        last = self.blocks[-1] if self.blocks else None
        if isinstance(last, ToolGroup) and not last.done and len(self.blocks) - 1 >= self._cursor:
            self.blocks.insert(len(self.blocks) - 1, block)
            self._version += 1
        else:
            self.add_aside(block)

    def steer_answered(self, block: SteerBlock, state: str, outcome: str = "") -> None:
        block.state, block.outcome = state, outcome
        self._write_held()
        self._version += 1

    def add_notice(self, text: str, level: str = NOTICE_INFO) -> None:
        """A notice; while `command` is set, that command's output instead: under its echo while the echo is open,
        else under a repeat of the echo, held like any aside (as `add_output` with `command`)."""
        command = self._open_command()
        if command is not None:
            command.parts.append((text, level))
            self._version += 1
        elif self.command is not None:
            self.add_aside(CommandBlock(self.command.command, [(text, level)], done=True))
        else:
            self._append(NoticeBlock(text, level))

    def add_command(self, command: str) -> CommandBlock:
        """Echo a command the person ran and make it `command`: what it prints lands under it until `close_command`.

        Over a live block (a running tool, a streaming reply) the echo is held
        under it, as a steer is, and written into the transcript at the next
        boundary once the command is over: a command typed during a turn never
        closes what is running.
        """
        block = CommandBlock(command)
        self.add_aside(block)
        self.command = block
        return block

    def add_output(self, text: str, level: str = NOTICE_INFO, *, command: str = "", whole: bool = False) -> None:
        """A command's output: under its open echo, or, once that echo has closed, under a repeat of `command`.

        With no echo open and no `command` named, it is a notice.
        """
        open_command = self._open_command()
        if open_command is not None:
            open_command.parts.append((text, level))
            open_command.whole = open_command.whole or whole
            self._version += 1
        elif command:
            self.add_aside(CommandBlock(command, [(text, level)], whole, done=True))
        else:
            self._append(NoticeBlock(text, level))

    def add_turn_summary(self, seconds: float, output_tokens: int | None, waited: float = 0.0) -> None:
        """Close the turn that just ended with its done line; its tool calls are counted from the turn's blocks.

        `waited` is the part of `seconds` questions waited on the person.

        A command typed during the turn whose echo is still held for Hermes'
        answer is written above the done line with what has arrived, and
        closed: what it prints later goes under a repeat of its echo.
        """
        tools = sum(len(block.tools) for block in self.blocks[self._turn_start :] if isinstance(block, ToolGroup))
        for block in self._held:
            if isinstance(block, CommandBlock):
                block.done = True
        self._append(TurnSummaryBlock(max(seconds, 0.0), tools, output_tokens, waited=max(waited, 0.0)))

    def set_waiting(self, waiting: bool) -> None:
        """Whether a question Hermes asked waits on the person from now: a tool's duration leaves that time out."""
        now = self._clock()
        if waiting and self._waiting_since is None:
            self._waiting_since = now
        elif not waiting and self._waiting_since is not None:
            self._waits.append((self._waiting_since, now))
            self._waiting_since = None

    def waited_within(self, start: float, end: float) -> float:
        """Seconds of the waits on the person that began at or after `start` and ended by `end`.

        A request does not say which tool asked, and Hermes runs some calls
        side by side: only a wait a tool ran through whole can be one it was
        blocked on. One that began before it started, or ended after it
        finished, was another call's.
        """
        return sum(ended - began for began, ended in self._waits if began >= start and ended <= end)

    def close_command(self, block: CommandBlock | None = None) -> None:
        """A command is over (`block`, or the open `command`): its echo and output leave the live region at the next take."""
        command = block if block is not None else self._open_command()
        if command is not None and not command.done:
            command.done = True
            self._write_held()  # a steer sent with /steer goes under its echo; a held echo goes at a boundary
            self._version += 1

    def withdraw_command(self) -> CommandBlock | None:
        """Take back the open command's echo, with nothing printed under it, for the row the command turned into.

        An open echo is never taken, so it has not reached scrollback. None,
        and the echo stays, when none is open or it holds output.
        """
        block = self._open_command()
        if block is None or block.parts:
            return None
        if self.blocks and self.blocks[-1] is block:
            self.blocks.pop()
        else:
            self._held = [held for held in self._held if held is not block]  # by identity: echoes of one line are equal
        self._version += 1
        return block

    def add_assistant(self, text: str) -> None:
        """A finished reply (a resumed session's history), rendered like a streamed one. The record does not say
        which model wrote it, so its header names none rather than the session's model now."""
        if text.strip():
            self._append(AssistantBlock(text, done=True, model=None))

    def add_recorded_tools(self, messages: list[dict[str, Any]]) -> None:
        """A resumed session's tool calls (its history's `role: tool` messages) as one settled group, each drawn as a
        live call is (`● name(args)`) with a dim mark, since the record keeps no outcome, and an edit's diff under
        it where Hermes kept the one it showed live (`display_metadata.tool_result_metadata.inline_diff`)."""
        rows = []
        for message in messages:
            metadata = message.get("display_metadata")
            shown = metadata.get("tool_result_metadata") if isinstance(metadata, dict) else None
            diff = as_text(shown.get("inline_diff")) if isinstance(shown, dict) else ""
            name, args = _first_line(as_text(message.get("name"))) or "tool", self._display_args(_args_summary(message))
            row = ToolRow(as_text(message.get("tool_call_id")), name, args, TOOL_RECORDED,
                          script=_heredoc_summary(message))
            row.inline_diff, row.diff_root = diff.encode("utf-8", "surrogatepass"), self.cwd
            rows.append(row)
        if rows:
            self._append(ToolGroup(rows, done=True))

    def fail_turn(self, message: str) -> None:
        """A turn the gateway ended with a bare `error` event instead of `message.complete`.

        The live block closes as it stands, the error follows it, and the turn
        state clears, as `message.complete` with `status: error` would leave it.
        """
        self._close_live()
        self._append(NoticeBlock(message, NOTICE_ERROR))
        self.running = False
        self.activity = ""
        self.status = ""
        self.moa = ""

    def toggle_details(self) -> bool:
        """Expand or collapse the live block's details; blocks already taken never repaint."""
        self.details_expanded = not self.details_expanded
        self._version += 1
        return self.details_expanded

    # ── block bookkeeping ──

    def _live(self, kind: type) -> Any:
        last = self.blocks[-1] if self.blocks else None
        if isinstance(last, kind) and not last.done:
            return last
        return None

    def _open_command(self) -> CommandBlock | None:
        """`command` while its echo is open and this transcript's; None otherwise."""
        block = self.command
        if block is None or block.done:
            return None
        if (self.blocks and self.blocks[-1] is block) or any(held is block for held in self._held):
            return block
        return None

    def add_aside(self, block: Block) -> None:
        """A block about what is live (a command's echo, a row the agent list writes): held under the live blocks
        until the next boundary, as a steer is; appended when nothing is live, so it never closes a running tool
        group or splits a streaming reply."""
        last = self.blocks[-1] if self.blocks else None
        if last is not None and not last.done:
            self._held.append(block)
            self._version += 1
        else:
            self._append(block)

    def _close_live(self) -> None:
        last = self.blocks[-1] if self.blocks else None
        if last is None or last.done:
            return
        last.done = True
        if isinstance(last, ThinkingBlock):
            last.ended_at = self._clock()
        if isinstance(last, ToolGroup):
            # A draft no `tool.start` took never became a call: Hermes discarded that streamed attempt, or the turn
            # ended while the model was still writing it. Only a call that started can be cut off.
            last.tools = [row for row in last.tools if row.status != TOOL_GENERATING]
            for row in last.tools:
                if row.status == TOOL_RUNNING:
                    row.status = TOOL_INTERRUPTED

    def _append(self, block: Block) -> None:
        if isinstance(block, AssistantBlock) and block.model == "":
            block.model = self.model
        self._close_live()
        self._write_held()
        self.blocks.append(block)
        self._version += 1
        self._drop_past_cap()

    def _write_held(self) -> None:
        """The held blocks that wait for nothing more (an answered steer, a finished command), into the transcript,
        when its last block is no longer live."""
        if self.blocks and not self.blocks[-1].done:
            return
        answered = [block for block in self._held if not _awaits_answer(block)]
        if answered:
            self._held = [block for block in self._held if _awaits_answer(block)]
            self.blocks.extend(answered)

    def _drop_past_cap(self) -> None:
        """Past `BLOCK_CAP`, drop the oldest blocks already taken (or left out); one not taken yet stays until it is.

        Runs after an append, a take and a retake, so a resumed session's
        history longer than the cap goes as soon as it is printed.
        """
        drop = min(len(self.blocks) - BLOCK_CAP, self._cursor)
        if drop > 0:
            del self.blocks[:drop]
            self._cursor -= drop
            self._turn_start = max(self._turn_start - drop, 0)
            self.dropped += drop
            self._version += 1

    def _tool_group(self) -> ToolGroup:
        group = self._live(ToolGroup)
        if group is None:
            group = ToolGroup()
            self._append(group)
        return group

    def _taken_lines_of(self, block: Block) -> int:
        at_cursor = self._cursor < len(self.blocks) and self.blocks[self._cursor] is block
        return self._cursor_lines if at_cursor else 0

    def _settle_text(self, block: AssistantBlock, text: str) -> None:
        """Adopt the gateway's authoritative text unless it contradicts lines already taken."""
        new_lines = _display_lines(text)
        old_lines = _display_lines(block.text)
        if not new_lines or new_lines == old_lines:
            return
        taken = self._taken_lines_of(block)
        if new_lines[:taken] == old_lines[:taken]:
            block.text = text

    def _repeats_turn_answer(self, text: str) -> bool:
        lines = _display_lines(text)
        return any(
            isinstance(block, AssistantBlock) and _display_lines(block.text) == lines
            for block in self.blocks[self._turn_start :]
        )

    # ── event handlers ──

    def _on_message_start(self, payload: dict[str, Any]) -> None:
        self._close_live()
        self._turn_start = len(self.blocks)
        self.running = True

    def _on_message_delta(self, payload: dict[str, Any]) -> None:
        text = as_text(payload.get("text"))
        if not text:
            return
        block = self._live(AssistantBlock)
        if block is None:
            block = AssistantBlock()
            self._append(block)
        block.text += text

    def _on_message_interim(self, payload: dict[str, Any]) -> None:
        """Commentary the model wrote alongside tool calls: seal it as its own block."""
        text = as_text(payload.get("text"))
        block = self._live(AssistantBlock)
        if block is not None:
            if not payload.get("already_streamed"):
                self._settle_text(block, text)
            block.done = True
            return
        if text.strip() and not self._repeats_turn_answer(text):
            self._append(AssistantBlock(text, done=True))

    def _on_message_complete(self, payload: dict[str, Any]) -> None:
        text = as_text(payload.get("text"))
        status = as_text(payload.get("status")) or "complete"
        error = as_text(payload.get("error"))
        bare_error = status == "error" and _is_bare_error(text, error)
        block = self._live(AssistantBlock)
        if block is not None and not bare_error:
            self._settle_text(block, text)
        elif block is None and not bare_error and text.strip() and not self._repeats_turn_answer(text):
            self._append(AssistantBlock(text))
        self._close_live()
        if status == "interrupted":
            self._append(NoticeBlock(INTERRUPTED_NOTICE, NOTICE_WARN))
        if status == "error":
            self._append(NoticeBlock(error.strip() or FAILED_NOTICE, NOTICE_ERROR))
        warning = as_text(payload.get("warning")).strip()
        if warning:
            self._append(NoticeBlock(warning, NOTICE_WARN))
        self.running = False
        self.activity = ""
        self.status = ""
        self.moa = ""

    def _on_thinking_delta(self, payload: dict[str, Any]) -> None:
        self.activity = _first_line(as_text(payload.get("text")))

    def _on_reasoning_delta(self, payload: dict[str, Any]) -> None:
        text = as_text(payload.get("text"))
        if not text:
            return
        block = self._live(ThinkingBlock)
        if block is None:
            block = ThinkingBlock(started_at=self._clock())
            self._append(block)
        block.text += text

    def _on_moa_reference(self, payload: dict[str, Any]) -> None:
        label = _first_line(as_text(payload.get(contract.MOA_LABEL))) or "reference"
        index, count = payload.get(contract.MOA_INDEX), payload.get(contract.MOA_COUNT)
        known = all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (index, count))
        header = f"◇ Reference {index}/{count} — {label}" if known else f"◇ Reference — {label}"
        self._append(ThinkingBlock(text=as_text(payload.get(contract.MOA_TEXT)).strip(), done=True, label=header))

    def _on_moa_progress(self, payload: dict[str, Any]) -> None:
        done, total = payload.get(contract.MOA_REFS_DONE), payload.get(contract.MOA_REFS_TOTAL)
        if all(isinstance(value, int) and not isinstance(value, bool) for value in (done, total)):
            self.moa = f"MoA: refs {done}/{total}"

    def _on_moa_phase(self, payload: dict[str, Any]) -> None:
        if payload.get(contract.MOA_PHASE) == contract.MOA_PHASE_AGGREGATOR:
            self.moa = "MoA: aggregating…"

    def _on_reasoning_available(self, payload: dict[str, Any]) -> None:
        """Ignored: it relays the assistant's own content, so it would repeat the answer as thought."""

    def _on_tool_generating(self, payload: dict[str, Any]) -> None:
        name = _first_line(as_text(payload.get("name")))
        if name:
            self._tool_group().tools.append(ToolRow(tool_id="", name=name))

    def _on_tool_start(self, payload: dict[str, Any]) -> None:
        tool_id = as_text(payload.get("tool_id"))
        name = _first_line(as_text(payload.get("name"))) or "tool"
        group = self._tool_group()
        row = _find_row(group, tool_id) or _drafted_row(group, name)
        if row is None:
            row = ToolRow(tool_id=tool_id, name=name)
            group.tools.append(row)
        row.tool_id = tool_id
        row.name = name
        row.status = TOOL_RUNNING
        row.started_at = self._clock()
        row.args_summary = self._display_args(_args_summary(payload))
        row.script = _heredoc_summary(payload)

    def _on_tool_complete(self, payload: dict[str, Any]) -> None:
        tool_id = as_text(payload.get("tool_id"))
        group = self._tool_group()
        row = _find_row(group, tool_id)
        if row is None:
            name = _first_line(as_text(payload.get("name"))) or "tool"
            row = ToolRow(tool_id=tool_id, name=name, args_summary=self._display_args(_args_summary(payload)),
                          script=_heredoc_summary(payload))
            group.tools.append(row)
        row.status = tool_result_status(payload.get("result"))
        now = self._clock()
        waited = self.waited_within(row.started_at, now) if row.started_at is not None else 0.0
        row.duration_s = _duration(payload, row, now, waited)
        row.summary = _result_summary(payload)
        recall = _recall(row.name, payload.get("result")) if row.status == TOOL_OK else None
        read = _recall_lines(recall) if recall is not None else (
            _read_summary(row.name, payload.get("result")) if row.status == TOOL_OK else ())
        row.output, row.output_more = (read, 0) if read else _tool_output(
            payload.get("result"), row.status, closed_said=row.answer_refused()
        )
        row.inline_diff, row.diff_root = as_text(payload.get("inline_diff")).encode("utf-8", "surrogatepass"), self.cwd
        row.held_lines = None
        row.recalled_at = now if recall is not None else None

    def _display_args(self, summary: str) -> str:
        return _relative(self.cwd, summary) if _is_path(summary) else summary

    def _on_status_update(self, payload: dict[str, Any]) -> None:
        text = _first_line(as_text(payload.get("text")))
        if text:
            self.status = text

    # ── output ──

    def take_stable_lines(self, width: int, theme: Theme) -> list[Line]:
        """Lines that will never change, each returned once: print them above the live region.

        `prompt_row` says where among them the newest prompt's first row is.
        """
        taken: list[Line] = []
        start = (self._cursor, self._cursor_lines)
        self.prompt_row = None
        measured, self._measured = self._measured, None
        held = measured[3] if measured and measured[:2] == (self._version, width) and measured[2] is theme else []
        first = self._cursor  # the block `held` starts at
        if self._left_out:
            earlier, self._left_out = _earlier(self._left_out), 0
            notice = (
                LEFT_OUT_DROPPED_NOTICE.format(earlier=earlier, held=len(self.blocks))
                if self.dropped
                else LEFT_OUT_NOTICE.format(earlier=earlier)
            )
            taken.append(truncate_line((Span(notice, theme.muted),), width))
            self._taken_any = True
            self._version += 1
        while self._cursor < len(self.blocks):
            block = self.blocks[self._cursor]
            index = self._cursor - first
            if isinstance(block, AssistantBlock) and not (block.done and index < len(held)):
                taken.extend(self._take_assistant(block, width, theme))
            elif block.done:
                # A done reply taken from its first line is the rows `block_rows` gives it, as measured.
                rows = held[index] if index < len(held) else block_rows(block, width, theme)
                if isinstance(block, UserBlock) and rows:
                    self.prompt_row = len(taken) + (1 if self._taken_any else 0)  # after the spacer `_spaced` adds
                taken.extend(self._spaced(rows, opens_block=True))
            if not block.done:
                break
            self._cursor += 1
            self._cursor_lines = 0
            self._cursor_state = MarkdownState()
        if (self._cursor, self._cursor_lines) != start:
            self._version += 1
        self._drop_past_cap()
        return taken

    def _take_assistant(self, block: AssistantBlock, width: int, theme: Theme) -> list[Line]:
        sources = _display_lines(block.text) if block.done else _stable_lines(block.text)
        fresh = sources[self._cursor_lines :]
        if not fresh:
            return []
        rows, self._cursor_state = render_lines(fresh, self._cursor_state, _reply_width(width), theme)
        opens_block = self._cursor_lines == 0
        self._cursor_lines = len(sources)
        return self._spaced(_marked(rows, opens_block, theme, width, block.model), opens_block)

    def _spaced(self, rows: list[Line], opens_block: bool) -> list[Line]:
        if not rows:
            return []
        spacer: list[Line] = [()] if opens_block and self._taken_any else []
        self._taken_any = True
        return spacer + rows

    def retake(self) -> None:
        """Forget which lines were taken: the next `take_stable_lines` returns the transcript from the top.

        For a full redraw at a new width, after the terminal's copy has been
        erased. Blocks are untouched; only the bookkeeping of what left the live
        region is reset, so every line is rendered again at the new width.
        """
        self._cursor = 0
        self._cursor_lines = 0
        self._cursor_state = MarkdownState()
        self._taken_any = False
        self._left_out = 0
        self._version += 1

    @property
    def taken_any(self) -> bool:
        """Whether any line has been taken, so what is shown next under them opens with a spacer row."""
        return self._taken_any

    @property
    def left_out(self) -> int:
        """How many blocks the next take counts in its opening row instead of showing (`retake_tail`)."""
        return self._left_out

    def retake_tail(self, width: int, theme: Theme, max_rows: int) -> None:
        """`retake`, keeping to the session's last `max_rows` rows at `width`: a full redraw costs that, not the session.

        The blocks are measured from the last finished one up, each with the
        blank row above it, and the next take starts at the first block that
        fits, so the cut always falls between blocks (a reply's markdown state
        starts over there, as it does for every reply). The last finished
        block is kept however tall it is, and the live block is never left
        out: it is the live region's. When blocks are left out, the next take
        opens with one row counting them, blocks `BLOCK_CAP` dropped included.
        """
        self.retake()
        cut, kept = self._measure_tail(width, theme, max_rows)
        self._cursor = cut
        self._left_out = cut + self.dropped
        self._drop_past_cap()  # before the take, so the row names how many /history still holds
        self._measured = (self._version, width, theme, kept)  # what was dropped lay above the cut

    def _tail_start(self, width: int, theme: Theme, max_rows: int) -> int:
        """The first block `retake_tail(width, theme, max_rows)` keeps."""
        return self._measure_tail(width, theme, max_rows)[0]

    def _measure_tail(self, width: int, theme: Theme, max_rows: int) -> tuple[int, list[list[Line]]]:
        """`_tail_start`, and the rows of each block from there to the live one, in order, as measuring rendered them."""
        end = len(self.blocks) - (1 if self.blocks and not self.blocks[-1].done else 0)
        cut, rows, kept = end, 0, []
        while cut > 0:
            block_lines = block_rows(self.blocks[cut - 1], width, theme)
            height = len(block_lines) + 1
            if rows + height > max_rows and cut < end:
                break
            rows += height
            cut -= 1
            kept.append(block_lines)
        kept.reverse()
        return cut, kept

    def live_lines(
        self, width: int, theme: Theme, max_rows: int | None = None, now: float | None = None, glint: bool = False,
    ) -> list[Line]:
        """Everything not yet taken, as it shows now: the streaming tail, live thinking, running tools.

        With `max_rows`, only the blocks that reach into the last `max_rows`
        rows are rendered, and of live thinking text only its last rows: the
        rows returned end exactly as the whole tail does, and may start below
        its top. With `now` a running tool's mark pulses (`PULSE_SECONDS`),
        and with `glint` too (the dag-ulw aura moves on this terminal) a
        recall's output rows carry the band that sweeps them once.
        The answer is kept until the transcript changes, a mark turns or a band
        moves, so asking again with the same width, limit and theme renders nothing.
        """
        key = (self._version, width, max_rows, self._pulses(now), self._glints(now if glint else None))
        held = self._live_held
        if held is None or held[0] != key or held[1] is not theme:
            held = self._live_held = (key, theme, self._render_live(width, theme, max_rows, now, glint))
        return list(held[2])

    def _pulses(self, now: float | None) -> tuple[bool, ...]:
        """The pulse half of every running tool not yet taken: what a live render depends on beyond the version."""
        if now is None:
            return ()
        return tuple(
            _pulse_dim(tool, now)
            for block in self.blocks[self._cursor :]
            if isinstance(block, ToolGroup)
            for tool in block.tools
            if tool.status == TOOL_RUNNING
        )

    def _glints(self, now: float | None) -> tuple[float | None, ...]:
        """How far the band over every recall not yet taken has gone: what a live render depends on beyond the
        pulses."""
        if now is None:
            return ()
        return tuple(
            _glint_band(tool, now)
            for block in self.blocks[self._cursor :]
            if isinstance(block, ToolGroup)
            for tool in block.tools
            if tool.recalled_at is not None
        )

    def _render_live(
        self, width: int, theme: Theme, max_rows: int | None, now: float | None = None, glint: bool = False,
    ) -> list[Line]:
        """`live_lines` rendered, from the last block up until `max_rows` rows are covered (all of them for None)."""
        rendered: list[tuple[bool, list[Line]]] = []  # (opens a block, its rows), the last block first
        held = [(True, block_rows(block, width, theme)) for block in reversed(self._held)]  # under the live blocks
        rendered.extend(held)
        count = sum(len(rows) for _opens, rows in held)
        whole = True
        for index in range(len(self.blocks) - 1, self._cursor - 1, -1):
            if max_rows is not None and count >= max_rows:
                whole = False  # the blocks above are above the rows asked for
                break
            block = self.blocks[index]
            opens_block = True
            if index == self._cursor and isinstance(block, AssistantBlock):
                rest = _display_lines(block.text)[self._cursor_lines :]
                opens_block = self._cursor_lines == 0
                block_lines = _marked(render_lines(rest, self._cursor_state, _reply_width(width), theme)[0], opens_block,
                                      theme, width, block.model)
            else:  # only the last block can be live thinking, the one kind the limit shortens, so it gets all of it
                block_lines = block_rows(block, width, theme, self.details_expanded and not block.done, max_rows, now,
                                         glint)
            if block_lines:
                rendered.append((opens_block, block_lines))
                count += len(block_lines)
        rows: list[Line] = []
        seen = self._taken_any if whole else True  # a spacer above the first block shown is past the limit
        for opens_block, block_lines in reversed(rendered):
            if opens_block and seen:
                rows.append(())
            rows.extend(block_lines)
            seen = True
        return rows

    def dropped_rows(self, width: int, theme: Theme, dropped: int | None = None) -> list[Line]:
        """/history's opening rows once `BLOCK_CAP` has dropped blocks (one counting them, then a blank one); else none.

        `dropped` is the count to name, `self.dropped` when None: a pager
        opened earlier names the count of the blocks it holds.
        """
        count = self.dropped if dropped is None else dropped
        if not count:
            return []
        return [truncate_line((Span(DROPPED_NOTICE.format(earlier=_earlier(count)), theme.muted),), width), ()]

    def history_lines(self, width: int, theme: Theme, details: bool = True) -> list[Line]:
        """Every block held at `width`; `details` adds full thinking text, tool result summaries, whole diffs."""
        rows: list[Line] = []
        for block in self.blocks:
            block_lines = block_rows(block, width, theme, expanded=details)
            if block_lines:
                if rows:
                    rows.append(())
                rows.extend(block_lines)
        return rows
