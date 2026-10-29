"""The OMH TUI's event loop and entry point.

`main` is what `python -m omh.tui` runs once Hermes' launcher has handed the
frontend its environment. Everything that can stop the TUI from starting is
settled before the first byte is drawn, and each such failure exits through
`request_fallback` (the file `omh` named, then `FALLBACK_EXIT`), so `omh`
opens Hermes' own terminal instead: a terminal that cannot run the TUI, a
gateway that does not start, and a session call (create or resume) this
Hermes refuses or no longer understands. The busy mode and the command
catalog are asked for without waiting; drift in either is met in the loop,
as drift in any call is. An attach hand-off is refused with exit 1 and a
line naming `hermes --tui --resume <id>` (0 would make `omh` print a resume
hint for a session this TUI never opened). SIGTERM and SIGHUP leave through
`SystemExit(128 + signum)`, so the terminal is restored and the gateway reaped
as on any other exit.

`App` is the loop. One thread owns the terminal and every model: it waits
for input, a wake-up from the gateway client or a resize (`_read_timeout`
says until when), routes keys (the pager while it is open, then
Ctrl+O and Ctrl+L, an open prompt slot, the session picker, the agent list,
the mode, effort and key-list keys, the attachment keys and Esc, the
completion menu, the queue's Up, then the composer), takes everything the
gateway sent since the last step, takes the newest HUD snapshot, and
repaints when something changed or a spinner is due. For `MIN_FRAME_SECONDS`
after a frame it does not wait on the gateway, so a burst of events shares
the next frame while a key still draws at once. Calls made from the
loop go out with `GatewayClient.request` and their answers come back through
`poll`, so a slow slash command never freezes the screen.

Protocol rules, measured against Hermes' gateway and enforced here: every
server request is answered (a slot, or an immediate decline with a notice),
because over stdio the gateway otherwise waits out its whole deadline; events
whose envelope `session_id` is not the live session are dropped, except
`gateway.*` and withdrawals, which match by request id; the stored session id
is tracked from every `session.info` and written (id only, mode 0600) to
`HERMES_TUI_ACTIVE_SESSION_FILE`; input sent while a turn runs is queued in
memory unless Hermes' config explicitly asks for `interrupt` or `steer`.
The queue is the TUI's own (the gateway has no call that withdraws a prompt):
its prompts are listed above the composer's top rule, and Up on an empty
composer takes them back into the composer (a `!` line on its own, never
joined to a prompt: `_recall_queue`). A turn the person interrupts does not
start the next queued prompt: the queue comes back into the composer the
same way, and what stays queued waits for the person (`_hold_queue`).
Ctrl+Enter and `/steer <text>` send what the person typed into the running
turn (`session.steer`); on an empty composer Ctrl+Enter, or Ctrl+J, sends the
oldest queued prompt instead, the person's own choice (`_send_queued_now`),
and the TUI steers nothing on its own. Text Hermes does not take as a steer
joins the TUI's queue while the turn runs, whatever the busy mode, and goes
as a prompt once it ends; sent at once, it would interrupt or redirect the
turn it was meant to steer.
A steer answered after its session was left goes back to the composer
instead: the session now live never receives it.

When the gateway child exits on its own with a failure, the loop spawns it
again from the environment the launcher handed the TUI (`gateway_spawn`) and
resumes the session that was open, at most `RESPAWN_LIMIT` times in
`RESPAWN_WINDOW_SECONDS` (`App._respawn_gateway`); a normal exit, the
person's quit, an attach hand-off, or a crash past the limit ends the TUI as
described above.

The input modes and the reasoning effort are `modes.ModesMixin`'s, and the
subagent view, list and log are `agent_view.AgentViewMixin`'s; each
module's docstring holds their rules. `App` mixes both in.

The transcript, attachments, secrets, server-request frames and the
gateway's stderr stay in memory and on the person's own terminal; nothing
here writes them anywhere. Prompt text goes to one file only: each line the
person sends from the composer is appended to Hermes' own input history
(`history.py`), never an answer to a question Hermes asked. The other files
the TUI writes are metadata: that session file, what OMH's HUD reader (`panels.HudPoller`, its fan-out cache
under `<omh_home>/runtime/`) and the model-chain picker (`/omh-model`'s saved
chains) write under the OMH home, and an empty fallback marker at the path
`omh` named, which `omh` removes. An attached image is a file the
gateway resolves and stages itself (`image.attach`, `clipboard.paste`,
`input.detect_drop`); the TUI reads its bytes into memory once, has Hermes
let go of it at once (`image.detach`), and the composer holds an
`[Image #N]` token for it (`composer.py`). Hermes takes every image it holds
when it admits a turn, so it holds an image only while the prompt that goes
with it is sent: that prompt stages its own images from the TUI's bytes
(`image.attach_bytes`) once Hermes has taken the last prompt's, and nothing
else is staged until Hermes admits it (`_submit_prompt`, `_claimed`). A
deletion that takes a token takes its image with it, since nothing else
holds it.
"""

from __future__ import annotations

import base64
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import errno
from functools import partial
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
from types import FrameType
import unicodedata
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol, TextIO

from ..plugin_bundle.omh.hud_text import elapsed_text
from ..commands.theme_picker import (
    KEY_DOWN,
    KEY_ENTER,
    KEY_LEFT,
    KEY_NONE,
    KEY_QUIT,
    KEY_RIGHT,
    KEY_UP,
    plain_key,
)
from ..skin_pack import (
    SkinTheme,
    default_theme,
    effective_theme,
    read_glow_choice,
    read_launch_choice,
    skin_colors,
    theme_for_name,
    theme_for_skin_name,
    theme_names,
    theme_store_path,
    write_glow_choice,
    write_launch_choice,
)
from . import gateway_contract as contract
from .composer import COMPLETE, EXIT, IMAGE_LABEL, INTERRUPT, SUBMIT, Composer, ComposerAction
from .frame import INFO_INSET, MODE_NORMAL, MODE_SHELL, Frame, badge_forms, branch_forms, build_frame, sticky_line
from .git_status import GitWatcher
from .history import SEARCH_ACCEPT, SEARCH_CANCEL, SEARCH_HINTS, HistorySearch, append_entry, history_path, load_history
from .gateway import (
    Event,
    GatewayCallError,
    GatewayCancelled,
    GatewayClient,
    GatewayExited,
    GatewayTimeout,
    GatewayUnavailable,
    Response,
    ServerRequest,
    attach_refused,
    gateway_spawn,
)
from .herdr import HerdrReporter
from .keys import (
    BUTTON_LEFT,
    CHAR,
    DOWN,
    END,
    ENTER,
    ESCAPE,
    LEFT,
    MOUSE_REPORT_SECONDS,
    RIGHT,
    UP,
    Key,
    KeyDecoder,
    Mouse,
    Paste,
)
from .launch import CLOSED_EXIT, SESSION_FILE_ENV, request_fallback
from .agent_view import AGENT_STEER_LEFT_UNANSWERED_NOTICE, STEER_SAY, TAIL_ANSWER_SECONDS, AgentViewMixin
from .aura import aura_ranges
from .layout import Budget, choice_cap, is_tiny, slot_cap
from .markdown import clean_text
from .modes import (
    HERMES_OWN_CYCLE,
    INFO_SEPARATOR,
    LABEL_SEPARATOR,
    NO_SESSION_NOTICE,
    ModesMixin,
    chip_column,
    configured_effort,
    effort_words,
    info_line,
    model_forms,
)
from .pager import ALT_SCREEN_OFF, ALT_SCREEN_ON, HistoryPager, Pager
from .model_picker import KEYS as MODEL_PICKER_KEYS
from .model_picker import PICK as MODEL_PICK
from .model_picker import ModelPicker, model_rows, typed_switch_value
from . import dag_block
from .dag_tree import TreeState
from .panels import (
    CATCH_MARK,
    HudPoller,
    HudSnapshot,
    catch_lines,
    dag_page_lines,
    hud_chips,
    panel_lines,
    plan_room_collapsed,
    plan_state,
    plan_text,
)
from .dag_pager import DagPager
from .background import BackgroundProcess, askable, finished_line, report_prompt, running_line, tool_call
from .clipboard import COPY_OSC52, COPY_PBCOPY, copy_route, pbcopy, tmux_client_over_ssh
from .prompts import CLOSED_CHOICES, Answer, ImmediateAnswer, PromptSlot, TypeIt, open_request
from .edge_glow import EDGE_MARGIN, Edge, edge, edge_fits
from .edge_glow import TICK_SECONDS as EDGE_TICK_SECONDS
from .screen import (
    CARRIAGE_RETURN,
    CLEAR_SCREEN_AND_SCROLLBACK,
    CURSOR_HOME,
    ERASE_SCROLLBACK,
    HIDE_CURSOR,
    SHOW_CURSOR,
    LiveRegion,
    cursor_up,
)
from .session_picker import KEYS as SESSION_PICKER_KEYS
from .session_picker import PICK, SessionPicker, pointer, session_rows
from .rewind_picker import KEYS as REWIND_PICKER_KEYS
from .rewind_picker import PICK as REWIND_PICK
from .rewind_picker import RewindPicker, rewind_rows
from .shortcuts import shortcut_lines
from .launch_card import Facts as LaunchFacts
from .launch_card import Paint as LaunchPaint
from .launch_card import Skills, launch_card, preview, read_snapshot, skill_rows, write_snapshot
from .launch_picker import CLOSE as LAUNCH_CLOSE
from .launch_picker import KEYS as LAUNCH_PICKER_KEYS
from .launch_picker import MOVE as LAUNCH_MOVE
from .launch_picker import PICK as LAUNCH_PICK
from .launch_picker import SUMMARIES as LAUNCH_SUMMARIES
from .launch_picker import LaunchPicker
from .slash import (
    CLASSIC,
    COMMANDS,
    DROPPED,
    HERMES,
    LOCAL,
    RENAMED,
    TURN_BACK_COMMANDS,
    Completion,
    SlashCommand,
    SlashInvocation,
    catalog_categories,
    catalog_pairs,
    catalog_skill_count,
    completions,
    dropped_notice,
    known_names,
    hermes_notice,
    parse_slash,
    plan_invocation,
)
from .style import CSI, NO_COLOR, TRUECOLOR, Line, Span, Style, color_depth
from .subagents import Hit, Roster
from .terminal import Terminal, background_from_colorfgbg, colorfgbg_names_dark, terminal_name, terminal_supported
from .theme import (
    BLACK,
    DEFAULT_LAUNCH,
    DEFAULT_THEME,
    EDGE_CONTRAST,
    LAUNCH_PRESETS,
    LIGHT_STAND_IN,
    TEXT_CONTRAST,
    WHITE,
    LaunchStyles,
    LogoPalette,
    Theme,
    aura_moves,
    build_theme,
    with_launch_look,
    with_prompt_band,
    is_light,
    launch_palette,
    launch_styles,
    launch_wordmark,
    lifted_colour,
    logo_lines,
    surface_for,
    theme_named,
    without_colour,
)
from .transcript import (
    NOTICE_ERROR,
    NOTICE_INFO,
    NOTICE_OK,
    NOTICE_WARN,
    OUTPUT_FAILED,
    OUTPUT_INDENT,
    OUTPUT_MARK,
    STEER_QUEUED,
    STEER_REFUSED,
    AssistantBlock,
    CommandBlock,
    NoticeBlock,
    SteerBlock,
    Transcript,
    as_text,
    block_rows,
    compact_count,
    review_line,
)
from .width import cell_width, clusters, line_width, truncate, truncate_left, truncate_line
from ..version import __version__

if TYPE_CHECKING:  # the bot board loads when it is opened (`_bots`), not with the TUI
    from .bot_board import BoardReader

# While the key decoder holds bytes (a lone ESC, half a sequence, an open paste), the loop reads with this
# timeout, and an empty read settles what is held only once input has been quiet for `FLUSH_SILENCE_SECONDS`:
# a wake-up for the gateway right after an ESC must not decide it before the rest of its sequence arrives.
READ_TIMEOUT_SECONDS = 0.05
FLUSH_SILENCE_SECONDS = 0.04
TICK_SECONDS = 0.1
# With reduced motion nothing on screen moves but the elapsed time, which changes once a second.
REDUCED_TICK_SECONDS = 1.0
# The highlight that sweeps across what Hermes is doing on the working row, in clusters, one cluster a tick.
SWEEP_CLUSTERS = 3
# The working row's glyph, one a tick: Claude Code's `· ✢ ✳ ✶ ✻ ✽` up and back down, starting at the `✻` that
# reduced motion holds (frame 0).
WORKING_GLYPHS = "✻✽✻✶✳✢·✢✳✶"
WORKING_VERB = "Working"  # the verb while Hermes says nothing it is doing
# The end of Hermes' own spinner text, `f"{face} {verb}..."` (6c61c3e27d `agent/turn_iteration_prep.py`).
SPINNER_DOTS = "..."
THINKING_EFFORT = "thinking with {} effort"
# The working row's tokens between Hermes' usage blocks: what the turn streamed, four characters a token and one per
# wide (CJK) character (`streamed_tokens`). Against the usage counter on deepseek-v4.1-flash and kimi-k3 it read
# 0.75-1.15 of English and Korean prose and about half of a turn of tool calls, whose framing never streams; each
# usage block puts the row back on the counter, and the done line is the counter's.
CHARS_PER_TOKEN = 4
CYCLE_TIP = "⇧⇥ turns on accept all, then plan mode"  # one of TIPS
# CYCLE_TIP's words while Hermes has approvals off on its own: Shift+Tab then turns plan mode on and off, nothing else.
HERMES_OWN_CYCLE_TIP = "⇧⇥ turns plan mode on and off"
# One under the working row a turn, in turn, from the keys table; on a terminal of TIP_MIN_ROWS rows or more.
TIPS = (
    "ctrl+o shows the whole transcript",
    CYCLE_TIP,
    "ctrl+t steps the reasoning effort",
    "esc esc between turns rewinds to an earlier prompt",
    "start a line with ! to run it in the shell",
    "ctrl+r searches your input history",
    "ctrl+p folds the plan to one row",
)
PLAN_FOLD_KEY = "ctrl+p"  # named on the plan's header; Ctrl+P is free in the composer and every mode
TIP_MIN_ROWS = 16
# Nothing due, nothing held: the loop still wakes this often. Gateway news and a new HUD snapshot wake it sooner.
IDLE_READ_SECONDS = 1.0
# For this long after a frame the loop does not wake for the gateway: what arrives meanwhile shares the next
# frame. Input still wakes it at once.
MIN_FRAME_SECONDS = 0.016
# A window drag sends a burst of SIGWINCH; redraw once the size has held this long.
RESIZE_SETTLE_SECONDS = 0.15
# A full redraw (a resize, Ctrl+L, /redraw, a switch, a resumed session) prints the transcript's last this many
# rows; the blocks above them are counted on one row instead (`Transcript.retake_tail`) and /history shows them.
REDRAW_TAIL_ROWS = 3000
EXIT_CONFIRM_SECONDS = 2.0
# Esc pressed twice within this long: with text, clears it into this session's history; on an empty composer
# between turns, opens the rewind picker. The info line says what the second press will do.
DOUBLE_ESCAPE_SECONDS = 0.8
ESCAPE_CLEAR = "clear"
ESCAPE_REWIND = "rewind"
ESCAPE_AGAIN = "esc again to {}"
# What the info line says while a picked rewind waits to be sent, longest first: a narrow line takes the first that fits,
# so what sending it replaces and how to cancel it survive.
REWIND_SAY = (
    "⏪ rewind: sending replaces prompt #{ordinal} and everything after it · esc cancels",
    "⏪ sending replaces #{ordinal} and everything after it · esc cancels",
    "⏪ replaces #{ordinal} and later · esc cancels",
    "⏪ replaces #{ordinal}+ · esc",
)
REWIND_BUSY_NOTICE = "Rewind works between turns: let this one end, or interrupt it with Esc."
CHAINS_CLOSED_NOTICE = "Hermes asked you something, so /omh-model closed:"
# What the info line says while the draft spans lines on a terminal that has sent no key report, where Shift+Enter
# arrives as Enter and sends; longest first.
NEWLINE_KEYS = ("⏎ sends · \\⏎, alt+⏎ or ctrl+j adds a line", "\\⏎ or alt+⏎ adds a line", "alt+⏎ adds a line")
# Ctrl+J: a line feed from every terminal in raw mode, where Enter is a carriage return, so the send-now key no
# terminal folds into Enter: on an empty composer with a prompt queued during a turn it is `SEND_NOW_KEY`; anywhere
# else it adds a line.
STEER_FALLBACK_KEY = Key(CHAR, "j", ctrl=True)
SEND_NOW_KEY = Key(ENTER, ctrl=True)
# A composer line that starts with this is the person's own shell command (`shell.exec`), never a prompt.
SHELL_PREFIX = "!"
SHELL_USAGE = "Usage: !<command> runs it in Hermes' shell (30 s at most); its output is not sent to the model."
SHELL_REFUSED = 4005  # Hermes' answer to a dangerous or hardline command
REWIND_NONE_NOTICE = "No prompt to rewind to in this session yet."
REWIND_REFUSED_NOTICE = "Hermes did not rewind: {reason}. The screen shows the session as Hermes still has it."
# Said as Hermes refuses, over the screen from before the send, until Hermes' history redraws it.
REWIND_KEPT_NOTICE = "Hermes did not rewind: {reason}. The screen is back to how it was before you sent."
# Said when the session was cut but the prompt that replaces the cut part did not go (only attached to a shared gateway).
REWIND_CUT_NOTICE = "Hermes cut the session there but did not take the prompt: {reason}. The prompt is back in the composer."
REWIND_UNREAD_NOTICE ="Hermes did not send the session's history ({reason}), so the screen stays as it was before you sent."
REWIND_TURN_BACK_NOTICE = "/{name} went back in the session itself, so the rewind is cancelled."
MODEL_BUSY_NOTICE = "Hermes switches the model between turns: let this one end, or interrupt it with Esc."
# `/model --refresh` as Hermes' own TUI reads it: the picker, over a list Hermes asks the providers for again.
MODEL_REFRESH_ARG = "--refresh"
# What a `config.set model` answer says, for `/model` and its picker.
MODEL_SWITCHED_NOTICE = "This session now runs {model}."
MODEL_DEFERRED_NOTICE = "This session switches to {model} when its next turn starts."
# A guarded model (cost, data policy, a large context): Hermes answers `confirm_required` and switches nothing, and
# the TUI asks in the prompt slot as Hermes' own TUI asks (`openModelConfirmation`), keeping the session's model the
# first choice and the one selected. Only "switch anyway" sends the switch again, with `confirm_expensive_model`.
MODEL_CONFIRM_QUESTION = "{intro}{message}\nSwitch this session to {model}?"
MODEL_CONFIRM_QID = "confirm"
MODEL_KEEP_CHOICE = "Keep {current}"
MODEL_SWITCH_CHOICE = "Switch to {model} anyway"
MODEL_KEPT_NOTICE = "Model not switched: this session stays on {current}."
MODEL_CONFIRM_STALE_NOTICE = "Model not switched: the session changed before the confirmation landed; run /model again."
# A question the TUI asks itself goes through the slot like Hermes' own; its answer stays here (`_respond`).
LOCAL_QUESTION_PREFIX = "omh-local-"
MODEL_UNNAMED_NOTICE = "Hermes answered the switch without naming a model; the session runs what Hermes says next."
# Hermes' configured default changed while this session ran (`_check_default`); `route` is " (<provider>)" or "".
DEFAULT_SWITCHED_NOTICE = "Hermes' default model is now {model}{route}; this session switched to it."
DEFAULT_DEFERRED_NOTICE = "Hermes' default model is now {model}{route}; this session switches to it at its next turn."
DEFAULT_KEPT_NOTICE = "Hermes' default model is now {model}{route}; this session stays on {current}.{reason}"
DEFAULT_UNSAFE_NOTICE = (
    "Hermes' default model is now {model}{route}, a name the OMH TUI does not send as one word; this session stays "
    "on {current}. Pick it with /model."
)
# `/model` with a flag Hermes' shared gateway does not take from a session, in place of the refusal's code.
MODEL_OPTIONS_REFUSED = (
    "Hermes' shared gateway switches only this session's model, by name: `/model <name>` or "
    "`/model <name> --provider <slug>`, and /model alone lists them. It takes no --global or --once from a session: "
    "to change the default for new sessions, run `hermes model` in a terminal, and this session switches to it "
    "when its turn ends."
)
# Refusals that only say a turn came first: a switch to a moved default (`_switch_to_default`) is due again then.
TURN_CAME_FIRST_REASONS = frozenset({"revision_conflict", "stale_generation", "session_busy"})
SESSION_MOVED_SENTENCE = "The session changed while Hermes applied this (a turn or another edit came first): run it again."
# Hermes' refusal reasons (`data.reason`, else the message), each in words that say what to do instead. A shared
# gateway's refusal can carry a hint of its own (`data.detail`), which follows the sentence.
REFUSAL_SENTENCES = {
    "unsupported_command": (
        "Hermes' shared gateway does not run this command in a TUI session. Type / to see the ones it does, "
        "or run this one in Hermes' classic CLI (`hermes --cli`)."
    ),
    "unsupported_model_options": MODEL_OPTIONS_REFUSED,
    "model_resolution_failed": (
        "Hermes found no provider it is set up for that serves this model. Pick one from /model, or name the "
        "provider with `/model <name> --provider <slug>`."
    ),
    "session_busy": "A turn is running: try again once it ends, or interrupt it with Esc.",
    "revision_conflict": SESSION_MOVED_SENTENCE,
    "stale_generation": SESSION_MOVED_SENTENCE,
    "unknown_execution": "Hermes no longer knows the turn this was for: run it again.",
    "permission_denied": (
        "Hermes does not let this connection change that session: open it in Hermes' own TUI (`hermes --tui`) instead."
    ),
    "invalid_params": "Hermes did not take the arguments: /help lists what each command takes.",
    "nothing_to_compress": "There is nothing to compress yet: the session is still short.",
    "invalid_checkpoint": "No checkpoint has that number or hash: /rollback lists them.",
    "unsupported_terminal_backend": (
        "This session runs its commands in a container, so Hermes' checkpoints of this machine's files do not apply."
    ),
    "mcp_servers_unavailable": "No MCP server Hermes reconciled could connect.",
    "unsupported_compress_options": (
        "Hermes' /compress does not take that option: use /compress, /compress <focus>, /compress here [N] "
        "or /compress --preview."
    ),
}
TODOS_NONE_NOTICE = "No plan in this session yet: Hermes' todo tool writes one."
QUESTION_VIEW_TITLE = "the open question (q goes back to it)"  # Ctrl+O's pager while Hermes asks something
# `/compress` (and `/compact`, its alias) while it runs: Hermes summarizes the older turns with a model call.
COMPRESS_COMMANDS = frozenset({"compress", "compact"})
COMPRESS_PREVIEW_FLAGS = frozenset({"--preview", "--dry-run"})
COMPRESS_STARTED_NOTICE = "Compressing: Hermes summarizes the older turns with a model call, so this can take a while."
# How long a `/compress` is waited for: Hermes' own budget for it (`hermes_cli/gateway_client.py` COMPRESS_RPC_TIMEOUT,
# the compression ceiling plus slack), in place of `CALL_ANSWER_SECONDS`.
COMPRESS_ANSWER_SECONDS = 660.0
# The longest any call is waited for while a `/compress` is out (`App._compression_left`): the compression's whole
# budget, then the usual one, so no call waits on it without end.
HELD_ANSWER_SECONDS = COMPRESS_ANSWER_SECONDS + 120.0
# Past that the compression may still commit, so running /compress again could compress twice.
COMPRESS_UNANSWERED_NOTICE = (
    "Hermes has not answered /compress in {seconds:g} s; the OMH TUI stopped waiting, but the compression may still "
    "land. /context shows whether it did: run /compress again only if it did not."
)
# A command Hermes refused because a compression of this session is still running (`data.field`, as Ink reads it).
COMPRESSION_BUSY_NOTICE = "Hermes is compressing this session's context: run /{name} again once that ends."
COMPRESSION_FIELD = "compression"
# A command typed while a `/compress` this TUI sent is out: Hermes' shared gateway holds it until the compression
# commits, then runs it.
COMPRESSION_HELD_NOTICE = "Hermes runs /{name} once this session's compression ends."
# A `/bg` or `/btw` answer for a session other than the one shown: one started there before a switch.
SIDE_ANSWER_ELSEWHERE = "From session {session}: {line}"
# Leaving a session closes this connection's view of it, and the gateway sends a side answer to that view only.
SIDE_ANSWERS_LEFT_NOTICE = (
    "The answer of {tasks}, started in {session}, will not show here: leaving that session closed the view Hermes "
    "sends it to."
)
# The new session a `/branch` answer names (the gateway child's answer, after the owner's `session.mutate branch`).
BRANCHED_SESSION = "branched_session_id"
BRANCHED_NOTICE = "⑂ Branched: this is a new session copied from {parent}; `/sessions {parent}` goes back."
# Claude Code's /export saves the conversation; Hermes' writes a profile archive. Said once, then it runs.
EXPORT_NOTE = (
    "Hermes' /export writes a profile archive (config, skills, theme), not this transcript; /export again runs it. "
    "/history pages the transcript and /copy copies the last reply."
)
# While a prompt slot is open, every key is ignored when its first byte arrived
# before the slot opened (or its current question appeared) or less than this
# long after, so Enter, Esc, an arrow, a digit or text typed for the composer as
# the request arrives cannot answer it (an approval, a clarify, a value prompt)
# or go into its answer field, however late the decoder decides the key.
SLOT_ARM_SECONDS = 0.4
# The delay instead, counted from the slot's opening, when reports were on as it
# opened or went off less than `keys.MOUSE_REPORT_SECONDS` before: a report sent
# before the off can start arriving that long after it, and its ESC, stalled
# past the decoder's wait, is read as Esc.
REPORTING_SLOT_ARM_SECONDS = max(SLOT_ARM_SECONDS, MOUSE_REPORT_SECONDS)
STARTUP_TAIL_LINES = 10
INTERRUPTED_EXIT = 130
# Closing the gateway on exit: stdin EOF, then terminate, then kill. The live
# region is already cleared and the terminal restored before this wait starts.
CLOSE_GRACE_SECONDS = 0.5
TERMINATE_GRACE_SECONDS = 2.0
# By default these end the process without unwinding: the shell stays raw and the
# gateway is orphaned. Raised as SystemExit, they restore and reap on the way out.
EXIT_SIGNALS = ("SIGTERM", "SIGHUP")

BANNER_BRAND = "⚚ OH-MY-HERMES"
NATIVE_WORD = "Native"  # the last word of the badge that starts the info line, in the launch look's colours
# The block logo goes above the banner from this many rows (and as many columns as it is wide): its six rows and
# the blank under it leave the composer region its room there.
LOGO_MIN_ROWS = 24
# A fresh session says where the last one is (`session.list`), while nothing has been sent yet.
LAST_SESSION_LIMIT = 3
LAST_SESSION_NOTICE = "last session: {label} · /resume {id} reopens it"
PLACEHOLDER = "Ask Hermes anything"
# The launch card (`launch_card`): none (a resumed session, or after /new or a switch), live in the region until the
# first prompt is sent, then kept in scrollback above it, and printed again under the banner by a full redraw.
CARD_NONE = "none"
CARD_LIVE = "live"
CARD_KEPT = "kept"
LAUNCH_UNKNOWN_NOTICE = "The launch look {name!r} saved in {path} is not one OMH has; spectrum is used."
LAUNCH_NO_NAME_NOTICE = "No theme or launch look named {name}. Themes: {themes}. Launch looks: {looks}."
LAUNCH_KEPT_NOTICE = "Launch look {name}, kept in {path}."
GLOW_KEPT_NOTICE = "Working glow {state}, kept in {path}."
GLOW_SESSION_NOTICE = "Working glow {state} for this session; there is no OMH home to keep it in."
GLOW_SAVE_FAILED_NOTICE = "Working glow {state} for this session; it could not be saved to {path}: {error}"
GLOW_ENV_NOTICE = "Working glow kept {state}; OMH_TUI_GLOW=0 holds it off in this terminal."
GLOW_UNAVAILABLE_NOTICE = "Working glow kept {state}; it shows only with motion on, at truecolor, on a screen 20×8 or larger."
GLOW_USAGE_NOTICE = "Use /glow on or /glow off; /glow alone switches it."
LAUNCH_SESSION_NOTICE = "Launch look {name} for this session; there is no OMH home to keep it in."
LAUNCH_SAVE_FAILED_NOTICE = "Launch look {name} for this session; it could not be saved to {path}: {error}"
LAUNCH_SWATCH_STEPS = 6  # the colours a look's swatch shows in the /theme picker
# The composer after an approval's tell row: what is sent goes into the running turn as a steer (`App._tell`).
TELL_PLACEHOLDER = "tell Hermes what to do instead"
TELL_SAY = (
    "↪ tell Hermes what to do instead · enter sends · esc cancels",
    "↪ tell Hermes what to do instead · esc cancels",
    "↪ tell Hermes · esc cancels",
    "↪ tell · esc",
)
BARE_HERMES_NOTE = "Bare `hermes` opens Hermes' own terminal."

# The context figure turns warn, then bad, on the info line.
CONTEXT_WARN_PERCENT = 80
CONTEXT_BAD_PERCENT = 95

# What `/theme auto|light|dark` measures the roles against: the background the terminal reported (auto), or a
# light or a dark one whatever it reported.
BACKGROUND_AUTO = "auto"
BACKGROUND_LIGHT = "light"
BACKGROUND_DARK = "dark"
BACKGROUND_MODES = (BACKGROUND_AUTO, BACKGROUND_LIGHT, BACKGROUND_DARK)

BUSY_QUEUE = "queue"
BUSY_MODES = frozenset({"queue", "steer", "interrupt"})

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_WAITING = "waiting on you"
# What each state is in herdr's agent list, when the TUI runs in a herdr pane (`herdr.py`).
HERDR_STATES = {STATE_IDLE: "idle", STATE_RUNNING: "working", STATE_WAITING: "blocked"}
WAITING_GLYPH = "? "  # in place of the spinner while a question waits on the person

# The prompts waiting for the running turn, listed above the composer's top rule.
QUEUE_GLYPH = "⧗ "
QUEUE_ROWS = 3
QUEUE_EDIT_HINT = "↑ edit"
QUEUE_HELD_HINT = "held · ↑ edit"
QUEUE_HINT_GAP = 2
# While a turn runs, the row under the queued prompts says the key that sends the oldest into the turn now, as a
# steer, the way Claude Code says it: Ctrl+Enter where the terminal tells it from Enter, else Ctrl+J.
SEND_NOW_HINT = "{key} to send now · ↑ to edit"
SEND_NOW_KEYS = ("ctrl+j", "ctrl+enter")  # by `App.keyboard_protocol`
# After the person interrupts a turn the queue does not go on by itself: what Up would take back goes back into the
# composer, and what it would not (a queued `!` line and what follows it) stays queued, held, until the next prompt
# the person sends starts a turn, or Up takes it back.
QUEUE_BACK_NOTICE = "{why}: what you queued is back in the composer, not sent."
# The same while the draft is set aside behind a field (the tell row's, a question's answer): that is where it went.
QUEUE_BACK_HIDDEN_NOTICE = "{why}: what you queued is in your draft, which comes back when this field closes; not sent."
QUEUE_HELD_NOTICE = "{why}: what you queued waits, not sent, until your next prompt; ↑ takes it back."
INTERRUPTED_WHY = "Interrupted"
RESPAWNED_WHY = "The Hermes gateway was restarted"
# Gateway crash recovery, bounded as Hermes' own TUI bounds it (ui-tui `app/gatewayRecovery.ts`): at most
# RESPAWN_LIMIT respawns in a sliding RESPAWN_WINDOW_SECONDS, each resuming the session that was open. Past that,
# or with no stored session to resume, the TUI leaves as it would without recovery.
RESPAWN_LIMIT = 3
RESPAWN_WINDOW_SECONDS = 60.0
# A respawn runs inside one loop step, so keys wait while the new gateway starts. Hermes' own TUI reports a gateway
# that sent no `gateway.ready` after 15 s (ui-tui `gatewayClient.ts` STARTUP_TIMEOUT_MS), and a gateway started again
# moments after the first one is warm, so an attempt gives up after that long, not the first start's minute. Hermes'
# TUI takes the time from STARTUP_TIMEOUT_ENV when it is set (milliseconds, at least 5 s, unset or 0 the default), and
# so does a respawn here (`respawn_ready_seconds`).
RESPAWN_READY_SECONDS = 15.0
STARTUP_TIMEOUT_ENV = "HERMES_TUI_STARTUP_TIMEOUT_MS"
STARTUP_TIMEOUT_MIN_SECONDS = 5.0
RESPAWN_NOTICE = (
    "{reason}: starting it again and resuming session {session} ({attempt} of {limit} in {window:g} s); "
    "what you type waits until it is back, and ctrl+c leaves."
)
RESPAWNED_NOTICE = "Resumed session {session} on a new Hermes gateway."
RESPAWN_LEFT_REASON = "you left while the Hermes gateway was starting again"
LEAVE_CHARS = ("c", "d")  # with Ctrl, read while a respawn waits: the person leaves (`App._respawn_cancel`)
TURN_LOST_NOTICE = "The running turn was lost when the Hermes gateway exited; it was not sent again."
QUESTION_LOST_NOTICE = "Hermes' {method} request closed unanswered: the gateway that asked has exited."
# Between the interrupt key and the end of the turn, the working row says so in place of the spinner.
INTERRUPTING = "interrupting…"

# Hermes answers `queued` both when the running turn takes the steer (at its next tool call) and when it
# queues the text as the next prompt because it is compressing the context; the transcript's
# `↪ steer queued by Hermes` is true of both. A steer it refuses says what became of the text instead.
STEER_REFUSED_OUTCOME = "{fallback} — Hermes refused the steer ({reason})"
STEER_FALLBACK_QUEUED = "queued"  # a turn still runs: the text waits in the TUI's queue for it to end
STEER_FALLBACK_SENT = "sent as a prompt"
STEER_FALLBACK_HEAD = "back at the head of the queue"  # a sent-now steer: the line it was, in its place
# A sent-now steer Hermes took but had not read when the turn stopped: Hermes dropped it, so its line is queued again.
SENT_NOW_DROPPED_OUTCOME = "back in the queue — the turn stopped before Hermes read it"
SENT_NOW_DROPPED_NOTICE = "The turn stopped before Hermes read {count} prompt{s} you sent now; back in the queue."
# A sent-now steer Hermes refused after the turn it was meant for ended and the next one started: queued again, it
# would run after a prompt sent later, so it goes back to the person instead.
STEER_FALLBACK_COMPOSER = "back in the composer"
SENT_NOW_LATE_NOTICE = (
    "Hermes refused a prompt you sent now after its turn had ended and the next one started; it is back in the "
    "composer, not sent."
)
STEER_REJECTED_REASON = "its turn had ended"  # Hermes' `rejected`: the agent was idle
# A steer with no answer is no refusal: Hermes may have taken it, so its text is never sent again but given back.
STEER_UNANSWERED_OUTCOME = "back in the composer — Hermes did not answer the steer in {seconds:g} s"
# One the gateway exited without answering is given back the same way, at once, as the respawn starts.
STEER_LOST_OUTCOME = "back in the composer — the Hermes gateway exited before it answered"
TELL_LOST_NOTICE = (
    "The Hermes gateway exited while you were telling it what to do instead; "
    "what you typed is back in the composer, not sent."
)
STEER_LOST_NOTICE = (
    "The Hermes gateway exited before it answered {count} steer{s}; the text is back in the composer, not sent again."
)
# What an approval's answer reads as in the transcript, and its colour: allowed in green, denied in red.
APPROVAL_OUTCOMES = {
    "once": ("allowed once", NOTICE_OK),
    "session": ("allowed for this session", NOTICE_OK),
    "always": ("always allow sent (Hermes saves it)", NOTICE_OK),  # the TUI sees the choice go, not the save
    "deny": ("denied", NOTICE_ERROR),
}
STEER_USAGE = "Usage: /steer <text to add to the running turn>"
STEER_LEFT_NOTICE = (
    "Hermes answered a steer after you left its session. "
    "Its text is back in the composer and was not sent to this one."
)
STEER_LEFT_UNANSWERED_NOTICE = (
    "Hermes did not answer a steer in {seconds:g} s, and you had left its session. "
    "Its text is back in the composer and was not sent to this one."
)

# On the way out while mouse reports may still be on their way (reporting on, or off for less than
# `keys.MOUSE_REPORT_SECONDS`): a cursor position request written after the off is answered after all of
# them (a terminal handles what it is sent in order), so input is read and dropped up to that answer,
# `ESC[<row>;<col>R`, instead of landing on the shell's prompt; for at most this long. The drain stops at
# the answer, so the bound costs nothing on a fast link and covers a round trip of up to a second.
EXIT_DRAIN_SECONDS = 1.0
CURSOR_POSITION_REQUEST = f"{CSI}6n"
# How long a call made from the loop is waited for: Hermes' own TUI gives every request 120 s
# (`HERMES_TUI_RPC_TIMEOUT_MS`), and a `subagent.tail` is asked again after `TAIL_ANSWER_SECONDS` anyway. Past
# it the call is forgotten (`App._expire_calls`) and an answer that still comes is dropped. Only the calls in
# QUIET_EXPIRY_METHODS, which a person never waits on, are forgotten without a notice.
CALL_ANSWER_SECONDS = 120.0
CALL_ANSWER_SECONDS_BY_METHOD = {"subagent.tail": TAIL_ANSWER_SECONDS}
QUIET_EXPIRY_METHODS = frozenset({"subagent.tail", "complete.path", "config.get"})
CALL_EXPIRED_NOTICE = "Hermes has not answered {method} in {seconds:g} s; the OMH TUI stopped waiting for it."
CURSOR_REPORT_START = b"\x1b["
CURSOR_REPORT_FINAL = b"R"

# One BEL when a question opens, so a terminal in the background can flag the tab or bounce.
BELL = "\a"
QUESTION_ALERT_CHARS = 80  # the most of what Hermes asks that a question's notification says
BELL_ENV = "OMH_TUI_BELL"
BELL_OFF = "0"
# The working glow round the screen (`edge_glow`) is on wherever it can move; `/glow off` (kept under the OMH home) or
# OMH_TUI_GLOW=0 turns it off, and with it the margin and the blank last row it keeps.
GLOW_ENV = "OMH_TUI_GLOW"
GLOW_OFF = "0"
# A turn that ran this long ends with the terminal's attention signal (`attention_sequence`).
TURN_ALERT_SECONDS = 10.0
TURN_ALERT_TEXT = "Hermes finished a turn ({elapsed})"
# Terminals that show OSC 9 as a notification, and the TERM names whose form is OSC 777; elsewhere the bell.
OSC9_TERMINALS = frozenset({"iTerm.app", "WezTerm", "ghostty"})
OSC777_TERMS = ("foot", "rxvt")
# The terminal title (OSC 2), pushed onto xterm's title stack before the first one and popped on the way out.
TITLE_PUSH = f"{CSI}22;0t"
TITLE_POP = f"{CSI}23;0t"
# Every OSC string written here ends with ST, not BEL, so a BEL on the wire is only ever the bell itself.
STRING_TERMINATOR = "\x1b\\"
TITLE_SET = "\x1b]2;{}" + STRING_TERMINATOR
TITLE_DEFAULT = "Hermes"
TITLE_CHARS = 80
# How many earlier sessions of this launch `omh`'s session file names (`opened`), newest kept.
OPENED_IDS_KEPT = 16
INFO_TITLE_CELLS = 24  # the session title at the head of the info line's right side, cut with `…` past this

# What a session id and a profile name have to look like before a farewell names them in a command to type back
# (Hermes' ids are `YYYYMMDD_HHMMSS_<hex>` or `local-<hex>`; its profile rule is `hermes_cli/profiles.py`'s).
RESUMABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
EXIT_HINT = "ctrl+c again to exit"  # on the info line while a second Ctrl+C would exit
INTERRUPT_HINT = "esc to interrupt"
OSC52_COPY = "\x1b]52;c;{}\x07"
# What a drag in the pager copied, on the footer's last row for COPY_NOTE_SECONDS. A copy that went out as OSC 52 to a
# terminal not known to honour it says it was sent, never that it was copied: no terminal answers one.
COPY_NOTE_SECONDS = 2.0
COPIED_NOTE = "copied {count} chars to clipboard"
COPY_SENT_NOTE = "copy sent ({why})"
OSC52_UNCONFIRMED = "terminal may not support OSC 52"
OSC52_IN_TMUX = "tmux passes it on only with set-clipboard on"
# The completion menu's name column: at least this wide, wider for the longest name it lists (OMH skills are
# `omh-*` and `ulw-*` slugs) up to half the terminal; a name longer than that pushes only its own summary.
MENU_NAME_CELLS = 16
SESSION_LIST_LIMIT = 50
# The owner's own refusal code (`attach/gateway_attach.py` REFUSED). Hermes' shared gateway answers it to a
# `session.resume` of a title, which it does not resolve, so `/sessions <title>` looks the title up after it.
RESUME_REFUSED = 4001
# What `/sessions <title>` says when the listed sessions hold no one session with that title: the picker opens
# filtered by it.
TITLE_SHARED_NOTICE = '{count} sessions are titled "{title}": pick one.'
TITLE_UNKNOWN_NOTICE = 'No session is titled "{title}": pick one, or change the filter.'
# The shapes of Hermes' session ids: a stored one (`20261028_101538_a1b2c3`) and a canonical local one
# (`local-` and hex, whole or as the 16-character hint). A typed target of that shape that no lookup finds is an id
# the owner refused, so its refusal is said rather than a title notice.
SESSION_ID_SHAPE = re.compile(r"\d{8}_\d{6}_[0-9a-f]+|local-[0-9a-f]{16,}")
# `complete.path` goes out once the `@` token has held still this long.
PATH_COMPLETE_DEBOUNCE_SECONDS = 0.12
# An image Hermes queued for a session the TUI has since left: the gateway holds it there, so no chip shows here.
ATTACH_LEFT_NOTICE = "Hermes queued {name} in the session you left, so it is not attached here."
# The most bytes of one image the TUI keeps for its token: what the gateway child stages at most (`gateway_attach`).
IMAGE_KEEP_BYTES = 20 * 1024 * 1024
IMAGE_LABEL_NUMBERS = re.compile(r"\[Image #(\d+)\]")  # the numbers a resumed session's prompts already gave
IMAGE_UNREADABLE_NOTICE = "{name} could not be read for its token (over 20 MB, or gone), so it is not attached."
IMAGE_NOT_SENT_NOTICE = "{label} did not go with the prompt: Hermes did not take it ({reason})."
IMAGES_KEPT_NOTICE = "{what} takes no image: {labels} stay in the composer for a prompt."
DETACH_FAILED_NOTICE = "Hermes did not let go of an image ({reason}); it may go with the next prompt."
# A prompt taken but not sent yet (its images were being staged) when the gateway or the session changed.
UNSENT_BACK_NOTICE = "{why}, so the prompt you sent did not go: it is back in the composer with its images."
UNSENT_BACK_RESPAWN = "Hermes' gateway restarted"
UNSENT_BACK_SWITCH = "The session changed"
# Under the queued prompts while a submit is held for the paste it was typed with, with the seconds from this on.
IMAGE_WAIT_LINE = "waiting for the image…"
IMAGE_WAIT_ELAPSED_SECONDS = 3.0
# Where the prompt that stages images stands (`App.claim`).
CLAIM_OPEN = "open"
CLAIM_STAGING = "staging"
CLAIM_SUBMITTED = "submitted"
CONNECTION_NOTICE = (
    "Hermes is waiting for an app connection, which only Hermes' Desktop app or `hermes --tui` can complete. "
    "Esc interrupts the turn."
)
# The events that show a submitted turn is one the TUI can follow: the first of them ends the drift watch
# (`App._watch_turn`). `session.info` and `session.usage` are left out: Hermes sends `session.info` after each
# `message.complete`, and on a session's first turn one also arrives after the prompt and before
# `message.start`, so it says nothing about whether this Hermes still sends the turn events the TUI reads.
TURN_PROGRESS_EVENTS = frozenset((*contract.TRANSCRIPT_EVENTS, *contract.SUBAGENT_EVENTS, "error"))
# Events of types the gateway contract does not declare that a submitted turn may bring, before any of
# TURN_PROGRESS_EVENTS, without a word; the next one shows UNKNOWN_EVENTS_NOTICE, unless every type the turn
# brought was named in an earlier notice of this run. Two, so one or two events of a new type that Hermes sends
# ahead of the usual ones say nothing.
UNKNOWN_EVENTS_BEFORE_NOTICE = 2
UNKNOWN_EVENT_NAME_CHARS = 40
UNKNOWN_EVENTS_NOTICE = (
    "This turn has brought no event the OMH TUI shows, only types it does not know ({types}), so Hermes may have "
    "changed its protocol; `omh doctor` shows the installed Hermes next to the one the TUI was built against. "
    "Esc interrupts the turn."
)
YOLO_NOTE = (
    "Hermes commands go to Hermes as you type them, /yolo included: it turns off Hermes' approval prompts, "
    "so the OMH TUI then has none to show."
)
# The commands only Hermes' classic CLI runs, which completion leaves out (`slash.CLASSIC`).
CLASSIC_HELP = "Only Hermes' classic CLI (`hermes --cli`) runs {names}; typed here, Hermes says where to run each."
# The keys themselves are `shortcuts.SHORTCUTS`, drawn by `?` and /keys; /help only points there.
HELP_KEYS = "Keys: ? on an empty composer, or /keys, lists every key."
SKILL_COMMANDS_NOTE = "{count} skill commands available: type / and part of a skill's name to find one."
# Hermes 6c61c3e27d's note for a skill whose name a built-in command takes (`agent/skill_commands.py`,
# `skill_command_collision_note`): the skill has no `/<name>` and runs as `/skill <name>`. `commands.catalog` joins
# the notes with "; " into its `warning`, and only when no discovery failed. `/help` lists them; no notice says them.
COLLISION_NOTE = re.compile(r"slash command /[^\s;]+ unavailable — name taken by built-in; use /skill [^;]+?(?=; slash command /|$)")
COLLISION_NOTES_HEADING = "Skills a built-in command's name takes:"
RELOAD_REFUSED_NOTICE = (
    "Hermes did not rescan its skills ({code}: {message}); a skill installed since the OMH TUI started runs as "
    "/<name> once it is restarted."
)
SETTINGS_REFUSED_NOTICE = (
    "Hermes did not send its settings ({code}: {message}), so a prompt sent during a turn queues until the turn "
    "ends (busy_input_mode queue, Hermes' default)."
)
CATALOG_REFUSED_NOTICE = (
    "Hermes did not send its command list ({code}: {message}), so completion and /help show only what the "
    "OMH TUI already knew; Hermes commands still run when typed."
)
GUIDE_KEY = "?"
# A notification's glyph by level, unless its text opens with a glyph of its own (Hermes writes most of them so).
NOTIFICATION_GLYPHS = {"info": "ℹ ", "warn": "⚠ ", "error": "✗ ", "success": "✓ "}
# What a refused call outside a command failed to do, in the words a person reads; the method and the JSON-RPC
# code stay out of the transcript. A refusal inside a command is Hermes' own words under the command's echo.
CALL_FAILED_PHRASES = {
    "prompt.submit": "take the prompt",
    "session.interrupt": "interrupt the turn",
    "image.detach": "remove the image",
    "slash.exec": "run the command",
    "command.dispatch": "run the command",
    "session.list": "list the stored sessions",
}


class TerminalLike(Protocol):
    mouse_reporting: bool

    def __enter__(self) -> Any: ...
    def __exit__(self, *exc: object) -> Any: ...
    def size(self) -> tuple[int, int]: ...
    def query_background(self) -> tuple[str | None, bytes, int | None]: ...
    def query_cursor_row(self) -> tuple[bytes, int | None]: ...
    def resized(self) -> bool: ...
    def read(self, timeout: float, wake: int | None = None) -> bytes: ...
    def write(self, text: str) -> None: ...
    def set_mouse(self, enabled: bool, drag: bool = False) -> None: ...
    def suspend(self) -> bool: ...


class PollerLike(Protocol):
    def start(self, wake: Callable[[], None] | None = None) -> None: ...
    def stop(self) -> None: ...
    def set_session(self, stored_id: str) -> None: ...
    def take(self) -> HudSnapshot | None: ...
    def refresh(self) -> int: ...
    def watch_tokens(self, session_ids: Sequence[str]) -> None: ...


@dataclass(frozen=True)
class _Pending:
    """A call sent from the loop: what to do with its result, and (optionally) with its error.

    `on_error` returns True when it handled the error; otherwise the error becomes a notice.
    """

    method: str
    on_result: Callable[[dict[str, Any]], None]
    on_error: Callable[[dict[str, Any]], bool] | None = None
    expires_at: float = math.inf  # on the app's clock: `_expire_calls` forgets the call then
    # The command it was made for (its handler, or the answer to one of its calls, was running): what its answer
    # says lands under that command's echo, which stays open until every call made for it is answered.
    command: CommandBlock | None = None
    # What an answer that never came settles, given the seconds it was waited for; None: a notice says so.
    on_expiry: Callable[[float], None] | None = None
    steer: SteerBlock | None = None  # the steer row it settles, given back at once if the gateway exits first
    seconds: float = CALL_ANSWER_SECONDS  # how long it is waited for, as its expiry notice says
    # A `/compress` call: Hermes' shared gateway serves this connection's calls one at a time, so every call sent
    # while it is out waits until the compression ends.
    compressing: bool = False


@dataclass
class SentNow:
    """A queued prompt the send-now key steered into the turn and Hermes took, until the turn reads it."""

    line: QueuedLine
    block: SteerBlock


class QueuedLine(NamedTuple):
    """A line waiting for the running turn: what is sent, what the queue rows show, what Up puts back.

    `shell` says it is a `!` line the person sent, which runs with `shell.exec`; only `_shell_line` sets it, so
    a prompt whose text starts with `!` (a refused steer, a message Hermes composed) stays a prompt.
    """

    text: str
    shown: str = ""  # "" shows `text`
    typed: str = ""  # "" puts `text` back
    shell: bool = False
    chips: tuple[tuple[str, str], ...] = ()  # the paste chips in `shown` (label, text), for Up to put back as chips
    notice: str = ""  # what the skill command that sent it said (Hermes' dispatch notice), shown under its row
    images: tuple[Attachment, ...] = ()  # the images it goes with, for Up to put back as tokens


@dataclass(frozen=True)
class Rewind:
    """A prompt picked to go back to: sending the composer truncates the session before `row_id`."""

    row_id: int
    ordinal: int
    before: tuple[dict[str, Any], ...]  # the history's messages before it: what the redraw shows above the new prompt


@dataclass(frozen=True)
class Notification:
    """One `notification.show` as the row above the composer shows it, until `expires_at` on the app's clock."""

    text: str
    level: str
    key: str
    expires_at: float = math.inf

    def style(self, theme: Theme) -> Style:
        return {"warn": theme.warn, "error": theme.error, "success": theme.ok}.get(self.level, theme.muted)

    def line(self, width: int, theme: Theme) -> Line:
        """The glyph (Hermes' own when the text opens with one) and the text, cut to `width`."""
        first = self.text[:1]
        own_glyph = bool(first) and not first.isalnum() and unicodedata.category(first)[0] in "SP"
        glyph = "" if own_glyph else NOTIFICATION_GLYPHS.get(self.level, NOTIFICATION_GLYPHS["info"])
        return truncate_line((Span(glyph + self.text, self.style(theme)),), width)


def notification_from(payload: Mapping[str, Any], now: float) -> Notification | None:
    """The row a `notification.show` payload shows; None without text. Only kind ttl expires, after `ttl_ms`."""
    text = " ".join(clean_text(as_text(payload.get(contract.NOTIFICATION_TEXT))).split())
    if not text:
        return None
    level = as_text(payload.get(contract.NOTIFICATION_LEVEL))
    ttl = payload.get(contract.NOTIFICATION_TTL_MS)
    expires_at = math.inf
    if as_text(payload.get(contract.NOTIFICATION_KIND)) == contract.NOTIFICATION_TTL_KIND and isinstance(ttl, int) \
            and not isinstance(ttl, bool) and ttl > 0:
        expires_at = now + ttl / 1000
    level = level if level in contract.NOTIFICATION_LEVELS else "info"
    return Notification(text, level, as_text(payload.get(contract.NOTIFICATION_KEY)), expires_at)


def respawn_ready_seconds(environ: Mapping[str, str]) -> float:
    """How long a respawned gateway may take to send `gateway.ready`: `STARTUP_TIMEOUT_ENV` read as Hermes' TUI reads
    it (`Math.max(5000, parseInt(value) || 15000)` ms), a whole number of milliseconds; anything else is the default."""
    try:
        milliseconds = int(environ.get(STARTUP_TIMEOUT_ENV, "").strip())
    except ValueError:
        milliseconds = 0
    return max(STARTUP_TIMEOUT_MIN_SECONDS, milliseconds / 1000 if milliseconds else RESPAWN_READY_SECONDS)


def goal_line(goal: Mapping[str, Any] | None, width: int, theme: Theme) -> Line | None:
    """Hermes' standing /goal on one row, worded as its Ink goal bar words it; None once it is done or cleared.

    `⊙ goal · 3/20 turns · <title>` while active; `⏳ goal parked · until 14:05
    · <reason> · 3/20 turns · <title>` (the time local, or `on session <id>`)
    while it waits on a barrier; `⏸ goal paused · <reason> · 3/20 turns ·
    <title>` while paused.
    """
    if not isinstance(goal, Mapping) or goal.get(contract.GOAL_STATUS) not in contract.GOAL_SHOWN_STATUSES:
        return None

    def whole(key: str) -> int:
        value = goal.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    def words(value: object) -> str:
        return " ".join(clean_text(as_text(value)).split())

    turns = f"{whole(contract.GOAL_TURNS_USED)}/{whole(contract.GOAL_MAX_TURNS)} turns"
    barrier = goal.get(contract.GOAL_WAIT_BARRIER) if goal.get(contract.GOAL_STATUS) == contract.GOAL_ACTIVE else None
    if isinstance(barrier, Mapping):
        until_at = barrier.get(contract.BARRIER_UNTIL_AT)
        if barrier.get(contract.BARRIER_TYPE) == contract.BARRIER_UNTIL and isinstance(until_at, int | float):
            wait = f"until {time.strftime('%H:%M', time.localtime(until_at))}"
        else:
            target = barrier.get(contract.BARRIER_TARGET)
            target_words = words(str(target)) if isinstance(target, str | int) else ""
            wait = f"on {words(barrier.get(contract.BARRIER_TYPE))} {target_words}"
        reason = words(barrier.get(contract.BARRIER_REASON))
        glyph, label, detail = "⏳", "goal parked", f"{wait}{f' · {reason}' if reason else ''} · {turns}"
    elif goal.get(contract.GOAL_STATUS) == contract.GOAL_PAUSED:
        reason = words(goal.get(contract.GOAL_PAUSED_REASON))
        glyph, label, detail = "⏸", "goal paused", f"{f'{reason} · ' if reason else ''}{turns}"
    else:
        glyph, label, detail = "⊙", "goal", turns
    line = (
        Span(f"{glyph} {label}", theme.running if glyph == "⊙" else theme.warn),  # an active goal runs
        Span(f" · {detail} · ", theme.muted),
        Span(words(goal.get(contract.GOAL_TITLE)), theme.text),
    )
    return truncate_line(line, width)


def goal_done_text(before: Mapping[str, Any] | None, goal: Mapping[str, Any] | None) -> str:
    """`goal done · 1h 20m · 7/20 turns · <title>` when a shown goal has just turned done, else "".

    The time is the goal's whole wall clock, from Hermes' own `created_at` to
    `updated_at`, so a goal that ran across many turns is not read off the
    last turn's `✻` line; it is left out when either stamp is missing or they
    run backwards. A goal first seen done (a resumed session) says nothing.
    """
    if not isinstance(before, Mapping) or before.get(contract.GOAL_STATUS) not in contract.GOAL_SHOWN_STATUSES:
        return ""
    if not isinstance(goal, Mapping) or goal.get(contract.GOAL_STATUS) != contract.GOAL_DONE:
        return ""

    def whole(key: str) -> int:
        value = goal.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    def stamp(key: str) -> float:
        value = goal.get(key)
        return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0

    started, ended = stamp(contract.GOAL_CREATED_AT), stamp(contract.GOAL_UPDATED_AT)
    took = elapsed_text(ended - started) if started > 0 and ended >= started else ""
    turns = f"{whole(contract.GOAL_TURNS_USED)}/{whole(contract.GOAL_MAX_TURNS)} turns"
    title = " ".join(clean_text(as_text(goal.get(contract.GOAL_TITLE))).split())
    return " · ".join(part for part in ("goal done", took, turns, title) if part)


def attention_sequence(environ: Mapping[str, str], message: str) -> str:
    """What asks for the person's attention on this terminal: OSC 9, OSC 777, or the bell, by its name."""
    text = clean_text(message)
    if terminal_name(environ) in OSC9_TERMINALS:
        return f"\x1b]9;{text}{STRING_TERMINATOR}"
    if environ.get("TERM", "").startswith(OSC777_TERMS):
        return f"\x1b]777;notify;OMH;{text}{STRING_TERMINATOR}"
    return BELL


def plain_sentence(message: str) -> str:
    """Hermes' message as a sentence: its first letter capitalised and a full stop when it ends without one."""
    text = message.strip() or "refused"
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def refusal_reason(error: Mapping[str, Any]) -> str:
    """A refusal's reason: the shared gateway's `data.reason`, else the message, which is the reason itself there."""
    data = error.get("data")
    reason = as_text(data.get("reason")) if isinstance(data, Mapping) else ""
    return reason or as_text(error.get("message")).strip()


def refusal_sentence(error: Mapping[str, Any]) -> str:
    """A refusal whose reason (`refusal_reason`) `REFUSAL_SENTENCES` knows, in those words and then Hermes' hint;
    "" for any other."""
    sentence = REFUSAL_SENTENCES.get(refusal_reason(error), "")
    data = error.get("data")
    detail = as_text(data.get("detail")).strip() if isinstance(data, Mapping) else ""
    return f"{sentence} {plain_sentence(detail)}" if sentence and detail else sentence


def side_answer_line(kind: str, payload: Mapping[str, Any], text: str) -> str:
    """A `/bg` or `/btw` answer as Ink shows it: `[bg <task>] <text>`, `[btw "<question>"] <text>`."""
    if kind == "background.complete":
        return f"[bg {as_text(payload.get(contract.SIDE_ANSWER_TASK))}] {text}"
    question = clean_text(as_text(payload.get(contract.SIDE_ANSWER_QUESTION))).strip()
    return f'[btw "{question}"] {text}' if question else f"[btw] {text}"


@dataclass(frozen=True)
class Attachment:
    """An image the person attached: the path Hermes first staged it at, its name, and the bytes the TUI keeps."""

    path: str
    name: str
    size: str  # "1280×720", or "" when the gateway could not read the dimensions
    label: str = ""  # its composer token, `[Image #3]` (`composer.IMAGE_LABEL`)
    data: bytes = field(default=b"", repr=False, compare=False)  # its bytes, which the TUI stages with each prompt


@dataclass
class UnsentPrompt:
    """A prompt taken to send whose images are being staged, or that waits to stage them: what comes back to the
    draft (`text`, with `images` as tokens) if it is given back before it goes, which `cancelled` then says."""

    text: str
    images: tuple[Attachment, ...]
    cancelled: bool = False


@dataclass
class HeldSubmit:
    """A composer submit made while a paste, drop or `/image` it was typed with was still out: held, its text and
    images as sent (`text`, `shown`, `chips`, `images`; `steer` for Ctrl+Enter), until each such intake is answered,
    whose image then joins it (`App._join_held`), since `since`; `cancelled` once given back."""

    text: str
    shown: str
    chips: tuple[tuple[str, str], ...]
    images: tuple[Attachment, ...]
    steer: bool
    since: float
    cancelled: bool = False


@dataclass
class Intake:
    """A call that has Hermes stage an image (`App._intake`): `running` once it went, and `held` the submit the
    person made while it was out, which its image joins."""

    running: bool = False
    held: HeldSubmit | None = None


@dataclass(frozen=True)
class PathItem:
    """One `complete.path` row: `text` replaces the `@` token, `display` and `meta` are what the menu shows."""

    text: str
    display: str
    meta: str


# ── small pure helpers ────────────────────────────────────────────────────


def model_switch_params(value: str, session_id: str, confirmed: bool = False) -> dict[str, Any]:
    """The `config.set model` call that switches `session_id` to `value`; `confirmed` once the person said to."""
    params: dict[str, Any] = {"key": contract.CONFIG_SET_MODEL, "value": value, "session_id": session_id}
    return {**params, "confirm_expensive_model": True} if confirmed else params


def config_mtime(result: Mapping[str, Any]) -> float | None:
    """The config file's mtime from a `config.get {key: "mtime"}` answer; None when it names none."""
    mtime = result.get("mtime")
    return float(mtime) if isinstance(mtime, (int, float)) and not isinstance(mtime, bool) else None


def busy_mode(config_result: Mapping[str, Any]) -> str:
    """`display.busy_input_mode` from a `config.get {key: "full"}` answer; queue unless it says otherwise.

    The `busy` getter cannot be used: it answers `interrupt` when the key is
    unset (the server's default), which hides exactly the case the TUI must
    read as `queue`, the default Hermes' own TUI applies.
    """
    config = config_result.get("config")
    display = config.get("display") if isinstance(config, dict) else None
    raw = display.get("busy_input_mode") if isinstance(display, dict) else None
    value = raw.strip().lower() if isinstance(raw, str) else ""
    return value if value in BUSY_MODES else BUSY_QUEUE


def context_percent(usage: object) -> float | None:
    """How full the context is, 0 to 100, from a `session.usage` / `session.info` usage block: its percent, else
    used over max; None when it has no context figures (a used and a max above 0)."""
    if not isinstance(usage, dict):
        return None
    used = usage.get("context_used")
    limit = usage.get("context_max")
    if not isinstance(used, int | float) or not isinstance(limit, int | float) or limit <= 0:
        return None
    percent = usage.get("context_percent")
    if isinstance(percent, int | float) and not isinstance(percent, bool):
        return float(percent)
    return used / limit * 100


def first_line(text: str) -> str:
    """The first line of a prompt, for the rows that name it in one line."""
    return text.strip().split("\n", 1)[0]


def queue_lines(
    prompts: Sequence[str], width: int, max_rows: int, theme: Theme, hint: str = QUEUE_EDIT_HINT, below: str = "",
) -> list[Line]:
    """The queued prompts, next to be sent first: `⧗ <first line>` each, never more than `max_rows` rows.

    At most `QUEUE_ROWS` prompts are named and `+N more` counts the rest;
    `hint` (`↑ edit`, the key that takes them back into the composer) ends the last row. `below`, when given and
    there are two rows or more, is a row of its own under them instead, under the prompts' text (while a turn runs:
    the send-now key and Up, `SEND_NOW_HINT`).
    """
    if not prompts or max_rows <= 0:
        return []
    if below and max_rows > 1:
        rows = queue_lines(prompts, width, max_rows - 1, theme, "")
        return [*rows, truncate_line((Span(" " * cell_width(QUEUE_GLYPH)), Span(below, theme.hint)), width)]
    named = min(len(prompts), QUEUE_ROWS, max_rows)
    if named < len(prompts):
        named = min(named, max_rows - 1)  # the last row counts the rest
    rows: list[Line] = [
        (Span(QUEUE_GLYPH, theme.muted), Span(clean_text(first_line(text)), theme.text)) for text in prompts[:named]
    ]
    if named < len(prompts):
        rows.append((Span(f"+{len(prompts) - named} more", theme.muted),))
    if hint:
        said: Line = (Span(hint, theme.hint),)
        last = truncate_line(rows[-1], max(width - line_width(said) - QUEUE_HINT_GAP, 0))
        rows[-1] = (*last, Span(" " * (width - line_width(last) - line_width(said))), *said)
    return [truncate_line(row, width) for row in rows]


def collision_notes(warning: str) -> tuple[str, ...]:
    """Hermes' built-in-name notes in a catalog `warning`, each as Hermes wrote it; () unless the warning is nothing
    but them (a discovery failure, or anything else, is not one)."""
    notes = tuple(match.group(0) for match in COLLISION_NOTE.finditer(warning))
    return notes if notes and "; ".join(notes) == warning else ()


def initial_theme(ready_payload: Mapping[str, Any], omh_home: str | None = None) -> Theme:
    """The theme `effective_theme` picks: saved under `omh_home`, else `gateway.ready`'s skin name, else sky."""
    skin = ready_payload.get("skin")
    name = as_text(skin.get("name")) if isinstance(skin, dict) else ""
    return build_theme(effective_theme(Path(omh_home) if omh_home else None, name)[0])


def short_path(path: str, home: str) -> str:
    """`path` with the home directory written as `~`."""
    home = home.rstrip("/")
    if home and path == home:
        return "~"
    if home and path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


# Below this many cells the working directory says too little to be worth a column.
_BANNER_MIN_PATH_CELLS = 12


def banner_lines(*, cwd: str, resumed: str, theme: Theme, width: int, brand: Style | None = None) -> list[Line]:
    """The header flushed to scrollback once, before the first frame, and a blank row under it.

    The header is one row at `width`: the brand, the version, the session it
    resumed and the working directory, shortened from the left to what is
    left over (and dropped when that is too little); whatever still
    overflows is cut at the edge rather than wrapped. The model and the keys
    are the info line's.
    """
    facts = [f"resumed {resumed}"] if resumed else []

    def header(path: str) -> Line:
        shown = [*facts, path] if path else facts
        return (
            Span(BANNER_BRAND, brand or theme.brand),
            Span(f" v{__version__}", theme.muted),
            *(span for fact in shown for span in (Span(" · ", theme.dim), Span(fact, theme.text))),
        )

    room = width - line_width(header("")) - len(" · ")
    path = truncate_left(cwd, room) if cwd and room >= _BANNER_MIN_PATH_CELLS else ""
    return [truncate_line(header(path), width), ()]


def banner_logo(
    skin: SkinTheme, background: str | None, width: int, rows: int, depth: str = TRUECOLOR,
    palette: LogoPalette | None = None,
) -> list[Line]:
    """The skin's block logo in a launch look's colours (the default look's without one) and a blank row, for above
    the banner; nothing narrower than the logo or under LOGO_MIN_ROWS. At the `NO_COLOR` depth the logo keeps its
    bold and drops its colours."""
    logo = logo_lines(skin, background, palette or launch_palette(DEFAULT_LAUNCH, surface_for(skin, background)))
    if depth == NO_COLOR:
        logo = [tuple(Span(span.text, replace(span.style, depth=NO_COLOR)) for span in row) for row in logo]
    if not logo or rows < LOGO_MIN_ROWS or width < max(line_width(row) for row in logo):
        return []
    return [*logo, ()]


def reduced_motion(environ: Mapping[str, str]) -> bool:
    """`OMH_TUI_REDUCED_MOTION` set to anything but 0, or `NO_COLOR` set: nothing pulses, sweeps or turns."""
    return environ.get("OMH_TUI_REDUCED_MOTION", "") not in ("", "0") or bool(environ.get("NO_COLOR"))


def usage_count(usage: object, key: str) -> int | None:
    """One counter of a Hermes usage block (`output`, `calls`); None when the block carries no such number."""
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def streamed_tokens(text: str) -> float:
    """About how many tokens a model wrote to stream `text`: CHARS_PER_TOKEN characters a token, one per wide one."""
    wide = sum(1 for char in text if unicodedata.east_asian_width(char) in ("W", "F"))
    return (len(text) - wide) / CHARS_PER_TOKEN + wide


def working_verb(text: str) -> str:
    """Hermes' activity text as the working row's verb, its first letter capitalised; "" when no words are left.

    Hermes' own spinner text is `"{face} {verb}..."`, a kaomoji and one or
    more words: of that shape only the words at its end made of letters alone
    are kept. It is that shape only when the words before them have no ASCII
    letter or digit, as no face Hermes or its skins ship has. Other text (a
    wait notice, `⏳ waiting on <model> — …`, a stall notice or a retry
    status that ends in dots too, a status) loses only the words before its
    first letter or digit. Trailing dots and ellipses go either way.
    """
    stripped = text.strip()
    words = stripped.rstrip(".…").split()
    start = len(words)  # where the words at the end made of letters alone begin
    while start and all(unicodedata.category(char)[0] in "LM" for char in words[start - 1]):
        start -= 1
    face = "".join(words[:start])
    if stripped.endswith(SPINNER_DOTS) and not any(char.isascii() and char.isalnum() for char in face):
        words = words[start:]
    else:
        while words and not any(char.isalnum() for char in words[0]):
            words.pop(0)
    verb = " ".join(words)
    return verb[:1].upper() + verb[1:]


def spinner_shaped(text: str) -> bool:
    """Whether `text` is Hermes' own spinner text, `"{face} {verb}..."`: words that are a verb, behind a face, or a
    notice of what the turn is doing now (a wait or a stall); a status that reports what happened is not."""
    stripped = text.strip()
    return bool(working_verb(stripped)) and stripped.endswith((SPINNER_DOTS, "…"))


def working_spans(text: str, frame: int, theme: Theme) -> list[Span]:
    """What Hermes is doing, muted, with a bright highlight `SWEEP_CLUSTERS` wide at `frame`'s place; it sweeps
    across and starts over after a pause as long as itself. Frame 0 falls in that pause, so the first frame,
    the one reduced motion holds, shows no highlight."""
    units = clusters(text)
    head = frame % (len(units) + SWEEP_CLUSTERS * 2) - SWEEP_CLUSTERS
    start, end = max(head, 0), max(head + SWEEP_CLUSTERS, 0)
    parts = (("".join(units[:start]), theme.muted), ("".join(units[start:end]), replace(theme.text, bold=True)),
             ("".join(units[end:]), theme.muted))
    return [Span(part, style) for part, style in parts if part]


def attachment_from(result: Mapping[str, Any]) -> Attachment | None:
    """The chip for an image the gateway queued (`image.attach`, `clipboard.paste`, an image drop); None without a path."""
    path = as_text(result.get("path"))
    if not path:
        return None
    width, height = result.get("width"), result.get("height")
    sized = all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (width, height))
    return Attachment(path, as_text(result.get("name")) or os.path.basename(path) or path, f"{width}×{height}" if sized else "")


def read_image(path: str) -> bytes | None:
    """The bytes of the image file Hermes staged at `path`, read once so the TUI holds it; None when it cannot be read,
    is no regular file (a link is not followed, a FIFO never blocks the loop), is empty, or is over
    `IMAGE_KEEP_BYTES`, as `history.load_history` guards its read. Windows has no `O_NOFOLLOW`, so a link or other
    reparse point is refused by its own entry first."""
    try:
        entry = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(entry.st_mode) or getattr(entry, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= IMAGE_KEEP_BYTES:
            return None
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            data = handle.read(IMAGE_KEEP_BYTES + 1)
    except OSError:
        return None
    finally:
        if fd >= 0:
            os.close(fd)
    return data if 0 < len(data) <= IMAGE_KEEP_BYTES else None


def with_label(text: str, label: str) -> str:
    """`text` with an image's `label` after it, a space between them unless it ends in one."""
    return f"{text}{'' if not text or text[-1].isspace() else ' '}{label}"


def _tokens(images: Iterable[Attachment]) -> list[tuple[str, Attachment]]:
    """`images` as the composer takes them back as tokens (`Composer.replace`): each with its label."""
    return [(image.label, image) for image in images]


def path_items(result: Mapping[str, Any]) -> list[PathItem]:
    """The rows of a `complete.path` answer; rows without a `text` are skipped."""
    items = result.get("items")
    if not isinstance(items, list):
        return []
    return [
        PathItem(as_text(item.get("text")), as_text(item.get("display")), as_text(item.get("meta")))
        for item in items
        if isinstance(item, dict) and as_text(item.get("text"))
    ]


def at_token(text: str, caret: int) -> tuple[int, str]:
    """(start, word) of the whitespace-delimited word that ends at the caret, when it starts with `@`; else (caret, "")."""
    start = caret
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    word = text[start:caret]
    return (start, word) if word.startswith("@") else (caret, "")


def resume_command(stored_id: str) -> str:
    return f"hermes --tui --resume {stored_id}" if stored_id else "hermes --tui"


def attach_message(environ: Mapping[str, str]) -> str:
    return (
        "omh: the OMH TUI does not attach to a gateway another runtime owns; "
        f"open it in Hermes' own terminal: {resume_command(environ.get('HERMES_TUI_RESUME', ''))}"
    )


def write_active_session(path: str, stored_id: str, extra: Mapping[str, Any] | None = None) -> None:
    """Write `{"session_id": <stored id>}` (mode 0600) for the launcher's exit epilogue. Best effort.

    The id is all Hermes' file holds; `omh`'s (`SESSION_FILE_ENV`) also
    carries `extra`: `hermes_home`, the home whose state database holds the
    session, and `opened`, the sessions this launch had open before it. A
    failure costs the launcher its exit lines and nothing else.
    """
    if not path or not stored_id:
        return
    record = {"session_id": stored_id, **(extra or {})}
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record))
        os.chmod(path, 0o600)
    except OSError:
        return


def _matches(request_id: str, params: Mapping[str, Any], ids: set[str]) -> bool:
    """Whether a withdrawal naming `ids` covers this request (its JSON-RPC id or an approval's own id)."""
    return request_id in ids or as_text(params.get("request_id")) in ids


def _slot_owns(slot: PromptSlot, event: Key | Paste, composer_text: str) -> bool:
    """Whether a key goes to the open slot rather than the composer.

    A slot answered by picking (an approval, a clarify question's list) takes
    every key; the composer is hidden then. A slot answered with text takes
    only what the composer has no use for: Esc and Up and Down always (Up and
    Down take a clarify question's text field back to its list), and Ctrl+C
    on empty input (decline). Everything else types the answer.
    """
    if slot.picking:
        return True
    if not isinstance(event, Key):
        return False
    if event.name in (ESCAPE, UP, DOWN):
        return True
    return not composer_text and event.name == CHAR and event.ctrl and event.char == "c"


def _menu_lines(entries: list[tuple[str, str]], index: int, width: int, max_rows: int, theme: Theme) -> list[Line]:
    """The completion menu (`(label, summary)` rows), scrolled so the highlighted entry is visible.

    No fill (`theme.menu`): the highlighted row has the pointer and its name bold in the accent, its summary in the
    text colour; every other name is in the command hue, not bold, and its summary muted, so the names read first.
    """
    if not entries or max_rows <= 0:
        return []
    start = min(max(index - max_rows + 1, 0), max(len(entries) - max_rows, 0))
    # Measured over every entry, not only the rows shown, so scrolling never moves the summary column.
    longest = max(cell_width(label) for label, _summary in entries) + 2
    name_cells = max(MENU_NAME_CELLS, min(longest, width // 2))
    rows: list[Line] = []
    for number in range(start, min(start + max_rows, len(entries))):
        label, summary = entries[number]
        current = number == index
        name = label + " " * max(name_cells - 1 - cell_width(label), 0)
        rows.append(truncate_line((
            pointer(current, theme),
            Span(name, theme.menu_current if current else replace(theme.menu_current, bold=False)),
            Span(f" {summary}", theme.text if current else theme.muted),
        ), width))
    return rows


_PICKER_KEYS = {UP: KEY_UP, DOWN: KEY_DOWN, LEFT: KEY_LEFT, RIGHT: KEY_RIGHT, ENTER: KEY_ENTER, ESCAPE: KEY_QUIT}


def picker_key(event: Key | Paste | Mouse) -> str:
    """One decoded key as an OMH picker's key token. Raw mode makes Ctrl+C a key, and it cancels like Esc."""
    if not isinstance(event, Key) or event.alt:
        return KEY_NONE
    if event.name != CHAR:
        return _PICKER_KEYS.get(event.name, KEY_NONE)
    if event.ctrl:
        return KEY_QUIT if event.char in ("c", "d") else KEY_NONE
    return plain_key(event.char)


def run_model_chain_picker(
    environ: Mapping[str, str], theme: Theme, *, read_key: Callable[[], str], write: Callable[[str], None], width: int
) -> str:
    """`omh model-chains`' picker, driven through the TUI's own terminal; returns a one-line result.

    The rows and the validated save of `plugin_bundle/omh/model_chain_picker.py`,
    the same ones `omh model-chains` uses, painted by the CLI picker.
    `read_key`, `write` and `width` are the picker's seams, so the terminal
    stays in the TUI's raw mode: no terminal setting changes, and Ctrl+C
    reaches the picker as a key that cancels instead of a signal.
    """
    from ..catalogs.model_chain_table import CHAIN_SURFACE_PURPOSES, MODEL_DISPLAY_LABELS
    from ..commands.model_chain_picker import run_picker
    from ..plugin_bundle.omh.model_chain_picker import apply_picker_changes, chain_entries, picker_rows

    omh_home = environ.get("OMH_HOME") or None
    hermes_home = environ.get("HERMES_HOME") or None
    try:
        payload = picker_rows(
            omh_home, hermes_home=hermes_home, labels=MODEL_DISPLAY_LABELS, purposes=CHAIN_SURFACE_PURPOSES
        )
    except (OSError, ValueError) as error:
        return f"/omh-model could not read the model chains: {error}"
    skin = theme_for_name(theme.name) or default_theme()
    changes = run_picker(
        payload,
        read_key=read_key,
        write=write,
        use_color=not environ.get("NO_COLOR"),
        width=width,
        palette=skin_colors(skin.skin_name),
    )
    if changes is None:
        return f"Cancelled; {payload['path']} was not changed."
    if not changes:
        return "No model-chain changes."
    result = apply_picker_changes(
        omh_home, {name: chain_entries(chain) for name, chain in changes.items()}, hermes_home=hermes_home
    )
    if "error" in result:
        return f"/omh-model did not save: {result['error']}"
    count = len(result["changed"])
    return (
        f"Saved {count} categor{'y' if count == 1 else 'ies'} to {result['path']}. "
        "New delegations use this order; running children keep theirs."
    )


# ── the loop ──────────────────────────────────────────────────────────────


class App(ModesMixin, AgentViewMixin):
    """The OMH TUI after its gateway started: `startup()` opens the session, `run()` is the loop."""

    def __init__(
        self,
        terminal: TerminalLike,
        client: GatewayClient,
        environ: Mapping[str, str],
        *,
        poller: PollerLike,
        theme: Theme = DEFAULT_THEME,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        pick_model_chains: Callable[..., str] = run_model_chain_picker,
        make_client: Callable[..., GatewayClient] | None = None,
        git: GitWatcher | None = None,
    ) -> None:
        self.terminal = terminal
        self.git = git  # the session directory's branch for the row under the info line; None draws no branch
        self.client = client
        # What spawns a gateway again after a crash (`_respawn_gateway`); None: a crash ends the TUI.
        self.make_client = make_client
        self.respawned_at: list[float] = []  # when each respawn in the window began, on `clock`
        self.respawn_reason = ""  # the gateway is gone, for this reason, and a respawn is due after this step
        self.environ = environ
        self.motion = not reduced_motion(environ)
        self.color_depth = color_depth(environ)  # the delegation graph's depth; at `NO_COLOR`, no colour anywhere
        self.poller = poller
        self.theme = self._painted(theme)
        self.clock = clock
        self.wall_clock = wall_clock
        self.pick_model_chains = pick_model_chains
        self.transcript = Transcript(clock)
        self.dag_ends: set[tuple[str, int]] = set()  # the dag-ulw run ends already printed (`dag_block.moment`)
        self.dag_end_due: dict[str, str] = {}  # run -> its end's title, printed when the turn ends (`_dag_moment`)
        self.read_dag_graph = dag_block.read_graph
        self.composer = Composer()
        # Hermes' own input history: read once here, and every line the person sends appended (`history.py`).
        self.history_file = history_path(environ)
        if self.history_file is not None:
            self.composer.history = load_history(self.history_file)
            self.composer.on_record = self._remember
        self.search: HistorySearch | None = None  # Ctrl+R's search, while it has the keys
        self.escape_armed: tuple[str, float] | None = None  # (what a second Esc does, when the first came)
        self.rewind_picker: RewindPicker | None = None
        self.rewind_messages: list[dict[str, Any]] = []  # the history the picker was opened over
        self.rewind: Rewind | None = None  # a picked prompt waiting to be sent again
        self.model_picker: ModelPicker | None = None  # bare /model's list of what Hermes offers
        # Hermes' configured default model and provider (a sessionless `model.options`) when last read, and the
        # config file's mtime then; None until read. A default that moves is switched to (`_check_default`).
        self.default_route: tuple[str, str] | None = None
        self.config_mtime: float | None = None
        self.default_due: tuple[str, str] | None = None  # a moved default not switched to yet: a turn ran
        self.default_asked = False  # a read or a switch for it is out
        # A prompt sent while no turn runs, held until the default is checked (`_start_turn`): its text, its send,
        # and the session it was typed in, the only one it may go to.
        self.starting: tuple[str, Callable[[], None], str] | None = None
        self.starting_images: tuple[Attachment, ...] = ()  # the images of the prompt `starting` holds
        self.local_questions: dict[str, Callable[[dict[str, Any]], None]] = {}  # asked in the slot, by request id
        self.local_serial = 0
        self.chains_open = False  # /omh-model's picker has the terminal (`_omh_model`)
        self.chains_closing = False  # a server request arrived while it was open: its next read cancels it
        self.export_said = False  # EXPORT_NOTE has been said: the next /export runs
        self.interrupt_armed: str | None = None  # the agent a first `x` in the list asked about
        self.agent_steer: str | None = None  # the agent `s` picked: the next line sent is its steer
        self.decoder = KeyDecoder(clock)
        self.glow = self._saved_glow()  # the working glow is wanted (`/glow`); `_edged` says whether it can show
        self._take_size()
        self.region = self._new_region()
        self.sid = ""
        self.stored_id = ""
        # Whether the session runs on Hermes' shared gateway (its answer named this connection's view), not the stdio
        # entry of an older Hermes.
        self.shared_gateway = False
        self.side_tasks: dict[str, str] = {}  # a `/bg` or `/btw` task whose answer has not arrived -> its session
        self.opened_ids: list[str] = []  # the sessions this launch had open before `stored_id`, oldest first
        self.model = ""
        self.context_percent: float | None = None
        # What the info line shows (`mode`): accept while Hermes has approvals off, the TUI's own plan flag.
        self.approvals_off = False
        self.plan_mode = False
        self.yolo_by_tui = False  # the approvals off shown are the TUI's own confirmed `on`, not Hermes' own
        self.hermes_approvals_said = False  # HERMES_APPROVALS_NOTICE was shown in this session
        self.effort = ""  # the reasoning effort the info line shows; "" shows none
        # The effort Hermes' config sets (`configured_effort`), from the last `config.get`: what a session that has
        # not said its own starts with, the launch session and each one opened later (`_adopt_session`).
        self.effort_configured = ""
        self.effort_said = False  # the shown effort is the session's own (its info, or a level set and confirmed)
        self.mode_request_open = False  # a yolo call is out: Shift+Tab waits for its answer
        self.yolo_reported: bool | None = None  # `session.info`'s yolo since the last yolo call went out
        self.yolo_confirmed_at: float | None = None  # when Hermes confirmed the TUI's on; None once one session.info was held
        self.effort_asked = ""  # the newest effort still waiting for Hermes' answer; the next Ctrl+T steps on from it
        self.busy_mode = BUSY_QUEUE
        # What `commands.catalog` last said, bound to the live session: completion and `/help` read it.
        self.catalog: list[tuple[str, str]] = []
        # Every name a typed `/name` resolves to (`slash.known_names`): drawn bold in its colour in the composer,
        # your prompt's row and the `↳ you:` reminder. The TUI's own commands until the catalog arrives.
        self.known_slash = known_names()
        self.catalog_categories: list[tuple[str, list[str]]] = []
        self.skill_count = 0
        self.catalog_warning = ""  # the last warning shown, so a re-read repeats none
        self.catalog_collisions: tuple[str, ...] = ()  # Hermes' built-in-name notes, which /help lists
        self.slot: PromptSlot | None = None
        self.slot_opened_at = 0.0
        self.slot_arm_seconds = SLOT_ARM_SECONDS  # the open slot's arm delay, fixed as it opened
        # The person's draft, set aside whole (text, caret, paste chips) while a slot answered with text has a
        # composer of its own; it is the composer again when that slot closes.
        self.slot_draft: Composer | None = None
        # The person's draft, set aside while the composer takes what to tell Hermes after an approval's tell row.
        self.tell_draft: Composer | None = None
        self.tell_turn_runs = False  # the turn whose approval the open tell field denied has not ended (`_tell`)
        self.waiting_requests: deque[ServerRequest] = deque()
        self.queued: deque[QueuedLine] = deque()
        self.sent_now: list[SentNow] = []  # sent-now steers Hermes took and the turn has not read yet
        self.turns_ended = 0  # turns of this TUI that ended: a steer remembers which turn it was meant for
        self.queue_held = False  # the queue waits for the person after an interrupt (`_hold_queue`)
        self.interrupting = False  # the person interrupted the running turn and Hermes has not ended it yet
        self.sticky = ""
        self.flushed_since_prompt = 0  # rows printed above the region from the last prompt's first row on
        self.turn_pending = False  # a prompt went out and its turn has not started (or ended) yet
        # The undeclared event types the submitted turn has brought before any of TURN_PROGRESS_EVENTS; None
        # before the first prompt, once the watch ends, and after the notice (`_watch_turn`).
        self.turn_unknown: list[str] | None = None
        self.turn_unknown_count = 0
        # Every undeclared type a notice has named, for the life of this TUI and its gateway, whatever the session.
        self.unknown_named: set[str] = set()
        # While a slash command the person typed runs (its handler, or the answer to a call made for it), a call made
        # is that command's (`Transcript.command` says which), and its echo stays open until every such call is
        # answered (`_run_slash`).
        self.pending: dict[int, _Pending] = {}
        # Keys read while something else had the loop (a respawn's waits, the cursor query after fg), acted on by the
        # next `_take_input` in the order they were typed.
        self.held_input: list[Key | Paste | Mouse] = []
        self.menu_index = 0
        self.menu_closed: str | None = None  # the composer text Esc closed the `/` menu on; it stays closed over that text
        # Where the open completion menu is drawn: under the composer (True) or in the slot above it (False); None
        # while no menu is open. Decided as it opens and kept while it stays open (`_place_menu`).
        self.menu_below: bool | None = None
        self.menu_under: list[Line] = []  # the menu's rows as `_slot_lines` last made them, while it is drawn under
        self.panel_shown = False  # the plan panel was in the slot `_slot_lines` last made: it gets its blank rows
        self.plan_folded = False  # Ctrl+P: the plan is its header alone, for the rest of the session
        self.plan_room_collapsed = False  # the plan the slot drew last was its header alone for want of rows
        self.tail_spacer = False  # `_tail` put a blank row above the working row, the first row to give way
        self.badge_cache: tuple[object, tuple[Line, ...]] = (None, ())  # `_badge_forms`' last forms and their key
        self.pager: Pager | None = None
        self.copy_noted_at: float | None = None  # when the pager's footer started saying what a copy did
        self.platform = sys.platform  # where `copy_route` looks for `pbcopy`
        self.pbcopy: Callable[[str], bool] = partial(pbcopy, environ=environ)
        self.tmux_over_ssh: Callable[[Mapping[str, str]], bool] = tmux_client_over_ssh  # `copy_route`'s tmux question
        self.question_view: Pager | None = None  # the pager Ctrl+O opened over the open question, while it is open
        # What reads the bot board (Ctrl+S, `/bots`) off this thread: made when it first opens, kept for the session
        # and paused while the board is closed, so a read stuck on a stalled file system never adds a thread.
        self.board_reader: BoardReader | None = None
        self.make_board_reader: Callable[..., BoardReader] | None = None  # `bot_board.BoardReader` when None
        self.redraw_after_pager = False  # a full redraw the main screen is owed once the pager is left
        self.hud: HudSnapshot | None = None
        self.goal: Mapping[str, Any] | None = None  # Hermes' standing /goal, as its last `session.control.update` said
        self.retired_plan = ""  # the text of a finished plan the panel no longer draws (`_retire_finished_plan`)
        self.plan_seen_open = False  # the panel has had a plan with an item left since the last one retired
        # The session and the highest catch `seq` this transcript has accounted for (`_print_catches`).
        self.catch_seen: tuple[str, int] | None = None
        # The background-process row (`background`): the session whose processes these are, the ones still running
        # (oldest first), when each was last seen with no turn running and nothing to wake the session on its exit
        # (on `clock`), and the ones that then ended unreported, in the order they ended, with when the first did
        # (on `wall_clock`).
        self.bg_session = ""
        self.bg_running: tuple[BackgroundProcess, ...] = ()
        self.bg_quiet: dict[str, float] = {}
        self.bg_done: tuple[tuple[BackgroundProcess, ...], float] | None = None
        # The poller's refresh count at the last turn's end: an older read may predate that end (`_take_background`).
        self.bg_after = 0
        self.notification: Notification | None = None  # Hermes' out-of-band notice, shown above the composer
        self.exit_armed_at: float | None = None
        self.exit_armed_by_interrupt = False  # whether the press that armed it interrupted a turn (`_exit_said`)
        self.exit_code: int | None = None
        self.farewell = ""
        self.banner_facts: dict[str, str] | None = None  # the header, flushed above the next frame
        self.banner_record: dict[str, str] | None = None  # kept, so a full redraw can print it again
        self.logo_due = False  # the block logo goes above the banner flushed next
        self.in_launch_session = True  # the logo is the start's: it is not repeated for /new or a switch
        self.launch_look = DEFAULT_LAUNCH  # the launch look the logo, the banner's title and the card are drawn in
        self.launch_picker: LaunchPicker | None = None  # /theme's picker, while open; its highlight is previewed
        self.card_state = CARD_NONE
        self.card_room = 0  # the rows the live card was last fitted to: the form it is kept in once the prompt goes
        # Hermes' skills, regrouped for the card: the last launch's (last-known) from startup, the session's once
        # `session.info` says.
        self.session_skills: Skills | None = None
        # The Hermes profile `session.create` named: the snapshot's key with the Hermes home; "" when it named none.
        self.launch_profile = ""
        self.snapshot_kept: Skills | None = None  # the skills this process last wrote to the snapshot
        self.last_session_row: Any = None  # the last stored session, for the card while it is live
        self.redraw_at: float | None = None  # when a settled resize redraws everything
        self.busy_since = 0.0  # when the running turn (or the prompt still waiting for it) started
        self.tip_turn: float | None = None  # the turn (its `busy_since`) whose working row shows TIPS[tip_index]
        self.tip_index = -1  # moves on as the next turn's working row first shows a tip
        self.turn_waited = 0.0  # the part of that turn questions waited on the person, the waits that ended
        self.waiting_since: float | None = None  # when the open question (or the first of those back to back) opened
        self.image_count = 0  # the highest `[Image #N]` this run gave or a resumed session's history holds
        # Hermes holds an image only from its staging for a prompt until it admits that prompt's turn: `staged` are
        # the paths it named for the last prompt.submit. `claim` says where the prompt that stages images stands: none
        # out (CLAIM_OPEN), its images being staged (CLAIM_STAGING), or sent and not yet taken (CLAIM_SUBMITTED); off
        # CLAIM_OPEN, what would stage another image or send another prompt waits in `after_claim` (`_after_claim`),
        # each with whether it sends a prompt, which also waits for the `intakes` (stagings a paste, a drop or
        # `/image` made, until their answers have sent the detach). `unsent` are the prompts taken that have not
        # gone as prompt.submit yet, which Esc, a session switch or a new gateway gives back (`_give_back_unsent`).
        self.staged: list[str] = []
        self.claim = CLAIM_OPEN
        self.after_claim: deque[tuple[bool, Callable[[], None]]] = deque()
        self.intakes: list[Intake] = []
        self.intake_answering: Intake | None = None  # the intake whose answer is being handled (`_take_attachment`)
        self.held_submits: list[HeldSubmit] = []  # submits waiting on the pastes they were typed with
        self.unsent: list[UnsentPrompt] = []
        self.image_epoch = 0  # moves on with each new gateway or session: a staging answered after it sends nothing
        self.picker: SessionPicker | None = None
        self.path_word = ""  # the `@` token `complete.path` was last scheduled for
        self.path_due: float | None = None  # when that call goes out (debounced)
        self.path_seq = 0  # the newest call; an answer to an older one is stale
        self.path_items: list[PathItem] = []
        self.connection_ops: set[str] = set()  # `connection.request` operations already named in a notice
        self.roster = Roster()  # the running turn's subagents
        self.list_selected: str | None = None  # the agent list's highlighted row while the list has the keys
        self.listed: tuple[str, ...] = ()  # the agent id of each list row as the agent view last drew them, top first
        self.tree_selected: str | None = None  # the dag tree's highlighted row while the tree has the keys
        self.tree_folds: dict[str, bool] = {}  # the dag tree's rows the person folded (False) or opened (True)
        self.tree_run = ""  # the run those folds belong to (`dag_tree.run_key`); a new run, or session, starts none
        self.tree_state: TreeState | None = None  # what the tree's keys need, as the agent view last drew it
        # The dag run that is over, which the view no longer draws, and when its graph had last moved (`_run_gone`)
        self.retired_run: tuple[str, float] | None = None
        self.tree_freed = 0  # the rows that run's tree gave up, kept blank under the info line (`_render`)
        self.tree_size = (0, 0)  # the width and the rows the agent view last drew the tree in
        self.log_agent = ""  # the agent whose log the pager shows; "" for every other pager
        self.tail_asked_at: float | None = None  # when the last `subagent.tail` went out
        self.tail_open = False  # that call has no answer yet
        self.tail_misses: dict[str, int] = {}  # agent id -> answers in a row without a tail
        # The cells a click opens, as last drawn: rows above the region's last row → the entries on that row.
        self.clickable: dict[int, tuple[Hit, ...]] = {}
        self.frame_budget: Budget | None = None  # the rows the last frame gave each part of the region
        self.frame_busy = False  # the last frame was drawn while a turn ran
        # The rows the agent view wanted, the rows it got and the tail's working rows in the last frame drawn while a
        # turn ran (`_held_view_rows`).
        self.view_hold: tuple[int, int, int] | None = None
        self.tree_hold = 0  # the most rows the dag tree took this turn on the bottom rows (`_tree_held_rows`)
        # Until the first prompt the region reaches the screen's last row (`_render`): the launch's logo and banner on
        # top, the composer on the bottom rows, the rows between them empty.
        self.launch_layout = True
        self.mouse_off_at: float | None = None  # when `_set_mouse` last turned reports off; None before that
        self.wake: int | None = None  # the gateway client's wake descriptor, which `run` selects on with the input
        self.input_at = 0.0  # when input last arrived, on `clock`
        self.background: str | None = None  # the terminal's background as it reported it; None when it did not
        self.background_named_dark = False  # no colour reported, but `COLORFGBG` named the background dark
        self.usage_output: int | None = None  # the session's `output` counter, as the last usage block said
        self.usage_calls: int | None = None  # its `calls` counter, from the same block
        self.turn_output_base: int | None = None  # that counter as the running turn began
        self.turn_calls_base: int | None = None  # and the calls counter then
        # The counter was seen starting over at a turn (`_take_usage`), so every later turn counts from 0.
        self.usage_restarts = False
        self.turn_streamed = 0.0  # what the turn streamed since the counter last moved, in tokens (`streamed_tokens`)
        self.turn_shown = 0  # the most tokens the working row has said this turn: it never goes back
        self.spinner_verb = ""  # Hermes' last spinner verb this turn: it stays in the verb slot while a status says more
        self.session_title = ""  # Hermes' auto-title for the session (`session.title`)
        self.shown_title: str | None = None  # the terminal title last written
        self.title_words = ""  # what that title was cut from: the same words need no new cut
        # The info line's right side last composed: what it showed, and the theme and HUD snapshot it was composed with.
        self.info_held: tuple[tuple[object, ...], Theme, HudSnapshot | None, tuple[Line, ...]] | None = None
        self.title_pushed = False
        self.herdr = HerdrReporter(self.environ)  # the title's state, told to herdr inside a herdr pane
        self.background_mode = BACKGROUND_AUTO
        self.dirty = True
        self.last_render = -math.inf

    # ── startup ──

    def startup(self) -> None:
        """Open or resume the session, then ask for the busy mode and for the session's command catalog.

        Only the session call is awaited: the first frame needs nothing else.
        The busy mode (`config.get`) and the catalog (asked for after the
        session and naming it, because Hermes discovers project-local skills
        for the session's workspace) are answered in the loop like any call
        made during the session; until the busy mode arrives it is
        `BUSY_QUEUE`, Hermes' own default. Raises `GatewayCallError`,
        `GatewayTimeout` or `GatewayUnavailable` from the session call; the
        caller turns each into `FALLBACK_EXIT`.
        """
        resume = self.environ.get("HERMES_TUI_RESUME", "")
        if resume:
            result = self.client.call("session.resume", {"session_id": resume, "cols": self.size[0]})
        else:
            result = self.client.call("session.create", self._create_params())
        info = result.get("info")
        self.launch_profile = as_text(info.get("profile_name")) if isinstance(info, dict) else ""
        home = self._snapshot_home()
        # Last-known until the session's own skills: its create answer's info (a shared gateway's carries them
        # all), or the session.info after Hermes' build (a lazy create's names none).
        self.session_skills = read_snapshot(home, *self._snapshot_key()) if home is not None else None
        self._adopt_session(result, fallback_stored=resume)
        self._request("config.get", {"key": "full"}, self._take_settings, self._on_settings_refused)
        self._refresh_catalog()
        if not resume:
            self._ask_last_session()
        self._read_default()
        self.banner_record = self._banner_record(result, resumed=self.stored_id if resume else "")
        self.banner_facts = dict(self.banner_record)
        self.logo_due = True
        self._load_launch_look()
        self.card_state = CARD_NONE if resume else CARD_LIVE
        if resume:
            self._draw_history(result.get("messages"))
        self._redeliver(result.get("open_requests"))

    def _snapshot_home(self) -> Path | None:
        """Where the launch card's skills snapshot is kept; None without an OMH home, or when `session.create` named
        no profile to key it by (then it is neither read nor written)."""
        return self._omh_home() if self.launch_profile else None

    def _snapshot_key(self) -> tuple[str, str]:
        """The Hermes home and profile the launch card's skills snapshot is for: another one's skills are never drawn."""
        return self.environ.get("HERMES_HOME", ""), self.launch_profile

    def _omh_home(self) -> Path | None:
        home = self.environ.get("OMH_HOME") or ""
        return Path(home) if home else None

    def _load_launch_look(self) -> None:
        """The launch look saved under the OMH home; a name OMH does not have is said once, and spectrum used."""
        home = self._omh_home()
        saved = read_launch_choice(home) if home is not None else None
        if saved is None:
            return
        if saved.strip().lower() in LAUNCH_PRESETS:  # a hand-edited `GRAPHITE` is graphite; it is written lowercase
            self.launch_look = saved.strip().lower()
            self.theme = self._themed()
        elif home is not None:
            self.transcript.add_notice(LAUNCH_UNKNOWN_NOTICE.format(name=saved, path=theme_store_path(home)), NOTICE_WARN)

    def _ask_last_session(self) -> None:
        """Ask for the stored sessions, to say under the banner where the last one is; a refusal says nothing."""
        self._request("session.list", {"limit": LAST_SESSION_LIMIT}, self._on_last_session, lambda error: True)

    def _on_last_session(self, result: Mapping[str, Any]) -> None:
        """Name the newest other session that has messages, unless the person has started already."""
        started = any(not isinstance(block, NoticeBlock) for block in self.transcript.blocks)
        row = next((row for row in session_rows(result) if row.id != self.stored_id and row.message_count > 0), None)
        if row is not None and not started and self.card_state == CARD_LIVE:
            self.last_session_row = row  # the card says it
            self.dirty = True
        elif row is not None and not started:
            self.transcript.add_notice(LAST_SESSION_NOTICE.format(label=row.label, id=row.id))

    def _banner_record(self, result: Mapping[str, Any], resumed: str) -> dict[str, str]:
        info = result.get("info")
        cwd = (as_text(info.get("cwd")) if isinstance(info, dict) else "") or self._create_params().get("cwd", "")
        return {"cwd": short_path(cwd, self.environ.get("HOME", "")), "resumed": resumed}

    def _redeliver(self, open_requests: object) -> None:
        """A resumed session's open requests, delivered as live ones."""
        for entry in open_requests if isinstance(open_requests, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("method"), str):
                params = entry.get("params")
                self._on_server_request(ServerRequest(entry["id"], entry["method"], params if isinstance(params, dict) else {}))

    def _draw_history(self, messages: object) -> None:
        """A resumed session's earlier turns as transcript blocks: prompts, replies, and each tool call one row as
        a live call draws it (`Transcript.add_recorded_tools`); the calls between two messages with words are one
        group, with no row between them.

        Only the last `REDRAW_TAIL_ROWS` rows of them are printed; /history shows the rest.
        """
        if not isinstance(messages, list):
            return
        tools: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "tool":
                tools.append(message)
                continue
            text = as_text(message.get("text"))
            if role not in ("user", "assistant") or not text.strip():
                continue
            if tools:
                self.transcript.add_recorded_tools(tools)
                tools = []
            if role == "user":
                self.transcript.add_user(text, known=self.known_slash, recorded=True)
                # Its `[Image #N]` labels are taken: the next image this run attaches is numbered past them.
                self.image_count = max([self.image_count, *map(int, IMAGE_LABEL_NUMBERS.findall(text))])
            else:
                self.transcript.add_assistant(text)
        if tools:
            self.transcript.add_recorded_tools(tools)
        self.transcript.retake_tail(self.size[0], self.theme, REDRAW_TAIL_ROWS)

    def _take_settings(self, result: dict[str, Any]) -> None:
        """`config.get`'s answer: the busy mode Hermes is set to, and the effort its config sets, shown until the
        session says its own (Hermes sends it once it has built the session's agent, which it starts as the session
        opens) and kept for the sessions opened later. A level the session said stays (`effort_said`), even one equal
        to the config's; one the config set before is replaced."""
        self.busy_mode = busy_mode(result)
        self.effort_configured = configured_effort(result)
        if not self.effort_said:
            self.effort = self.effort_configured

    def _on_settings_refused(self, error: dict[str, Any]) -> bool:
        """A refused `config.get`, drift included (`contract.OPTIONAL_METHODS`): `BUSY_QUEUE` stays, and a notice says so."""
        message = as_text(error.get("message")) or "refused"
        self.transcript.add_notice(SETTINGS_REFUSED_NOTICE.format(code=error.get("code"), message=message), NOTICE_WARN)
        return True

    def _catalog_params(self) -> dict[str, Any]:
        return {"session_id": self.sid} if self.sid else {}

    def _take_catalog(self, result: Mapping[str, Any]) -> None:
        """Keep what completion and `/help` read from a `commands.catalog` result; a new warning is a notice.

        Hermes' warning says skill, quick-command or plugin discovery failed,
        or, when nothing failed, names the skills that share a built-in
        command's name and run only as `/skill <name>` (`collision_notes`).
        Only a failure is a notice: those notes come with every catalog Hermes'
        own bundled skills collide in, so they are kept for `/help` instead.
        """
        self.catalog = catalog_pairs(result)
        self.known_slash = known_names(self.catalog)
        if self.transcript.resolve_recorded_prompts(self.known_slash, self.size[0], self.theme, REDRAW_TAIL_ROWS):
            self._full_redraw()  # a resumed prompt printed before the catalog answered draws its `/skill` now
        self.catalog_categories = catalog_categories(result)
        self.skill_count = catalog_skill_count(result)
        warning = as_text(result.get("warning")).strip()
        self.catalog_collisions = collision_notes(warning)
        if self.catalog_collisions:
            warning = ""
        if warning and warning != self.catalog_warning:
            self.transcript.add_notice(f"Hermes' command catalog: {warning}", NOTICE_WARN)
        self.catalog_warning = warning

    def _refresh_catalog(self) -> None:
        """Ask for the command catalog of the live session; an answer for a session since left is dropped.

        A refusal, drift included (`contract.OPTIONAL_METHODS`), keeps the
        catalog the TUI has and says so: completion and `/help` then list
        only what it already knew, and the session goes on.
        """
        sid = self.sid
        self._request(
            "commands.catalog",
            self._catalog_params(),
            lambda result: self._take_catalog(result) if sid == self.sid else None,
            lambda error: self._on_catalog_refused(sid, error),
        )

    def _on_catalog_refused(self, sid: str, error: dict[str, Any]) -> bool:
        if sid == self.sid:
            message = as_text(error.get("message")) or "refused"
            self.transcript.add_notice(CATALOG_REFUSED_NOTICE.format(code=error.get("code"), message=message), NOTICE_WARN)
        return True

    def _create_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"cols": self.size[0]}
        cwd = self.environ.get("HERMES_TUI_CWD") or self.environ.get("HERMES_CWD")
        if cwd:
            params["cwd"] = cwd
        return params

    def _adopt_session(self, result: Mapping[str, Any], fallback_stored: str = "") -> None:
        if self.starting is not None and self.starting[2] != as_text(result.get("session_id")):
            # A prompt held for the default check was typed in the session being left: back to the draft.
            self._give_back(self.starting[0], self.starting_images)
            self.starting, self.starting_images = None, ()
        self.sid = as_text(result.get("session_id"))
        self.shared_gateway = bool(as_text(result.get("subscription_id")))
        info = result.get("info")
        self.model = as_text(info.get("model")) if isinstance(info, dict) else ""
        self.context_percent = None  # the next session.usage says how full this session is
        # The token counter is the session's own. An answer with none opened a session in which no API call has ended
        # on this gateway yet (Hermes sends its first usage block after one), so the counter stands at 0.
        usage = info.get("usage") if isinstance(info, dict) else None
        self.usage_output = usage_count(usage, "output")
        self.usage_calls = usage_count(usage, "calls")
        if self.usage_output is None:
            self.usage_output = self.usage_calls = 0
        self.turn_output_base = self.turn_calls_base = None
        self.usage_restarts = False
        self.turn_streamed, self.turn_shown = 0.0, 0
        cwd = as_text(info.get("cwd")) if isinstance(info, dict) else ""
        self.transcript.cwd = cwd or str(self._create_params().get("cwd", ""))
        self.turn_pending = bool(result.get("running"))
        self.interrupting = self.queue_held = False  # both were about the session being left
        self.sent_now = []  # steers into the session being left: theirs to settle
        self.turn_unknown = None  # the drift watch was for a turn of the session being left
        self.busy_since = self.clock()
        self.turn_waited = 0.0
        # Accept belongs to the session being left; this one says its own, here or in its first session.info.
        # Plan is the TUI's flag and stays as it was.
        self.mode_request_open = False
        self.yolo_reported = None
        self.notification = None  # Hermes' notices are the session's
        self.session_title = ""
        self.rewind = self.rewind_picker = None  # a rewind names a row of the session being left
        self._leave_tell()  # what to tell Hermes was for a turn of the session being left
        self.approvals_off = self.yolo_by_tui = self.hermes_approvals_said = False
        self.effort_asked = ""
        self.effort = self.effort_configured  # until this session says its own (Hermes' lazy info names none)
        self.effort_said = False
        self._take_session_state(info if isinstance(info, dict) else {})
        self._take_skills(info if isinstance(info, dict) else {})
        self._take_title(info if isinstance(info, dict) else {})
        self._adopt_stored(as_text(result.get("stored_session_id")) or fallback_stored)

    def _adopt_stored(self, stored: str) -> None:
        if not stored or stored == self.stored_id:
            return
        if self.stored_id and self.stored_id not in self.opened_ids:
            self.opened_ids = [*self.opened_ids, self.stored_id][-OPENED_IDS_KEPT:]
        self.stored_id = stored
        write_active_session(self.environ.get("HERMES_TUI_ACTIVE_SESSION_FILE", ""), stored)
        hermes_home = self.environ.get("HERMES_HOME", "")
        if hermes_home:  # `omh` reads the session's row there once the TUI exits
            opened = [stored_id for stored_id in self.opened_ids if stored_id != stored]
            write_active_session(self.environ.get(SESSION_FILE_ENV, ""), stored,
                                 {"hermes_home": hermes_home, "opened": opened})
        self.poller.set_session(stored)

    # ── loop ──

    def adopt_background(self, answered: str | None, environ: Mapping[str, str] | None = None) -> None:
        """The background the terminal answered, else what `COLORFGBG` in `environ` names: the theme is measured
        against it from now on (`_surface`). None of either is no background reported."""
        named = environ or {}
        self.background = answered or background_from_colorfgbg(named)
        self.background_named_dark = self.background is None and colorfgbg_names_dark(named)
        self.theme = self._themed()

    def clear_launch_screen(self, row: int | None) -> None:
        """Push the rows above the cursor off the screen, erase the scrollback, and start the region on the top row.

        From the cursor's row, `rows - 1` line feeds reach the screen's last
        row and then scroll exactly the rows above the cursor off the top, into
        scrollback, whichever row the cursor was on; relative moves bring the
        cursor back to the top row, which is where the first frame starts (the
        row the cursor was on is erased by that frame, as at any launch). With
        `row` 1 (the launch's cursor position report put the cursor on the top
        row) nothing is above it, and nothing is pushed. Then ED 3 erases the
        scrollback, those rows and the shell's older output with them, so
        scrolling up stops at the session's top row (the owner, 2026-10-22),
        as it does after a full redraw (`_full_redraw`) and at the start of
        Hermes' own TUI in its default alternate-screen mode (its main-screen
        native mode, `display.tui_native`, writes only a line feed). A
        terminal that ignores ED 3 keeps them one scroll up.
        """
        rows = self.screen[1]
        if rows < 2 or self.region.height:
            return
        push = "" if row == 1 else "\n" * (rows - 1) + cursor_up(rows - 1) + CARRIAGE_RETURN
        self.terminal.write(push + ERASE_SCROLLBACK)
        self.region = self._new_region(at_top=True)

    def adopt_cursor_row(self, row: int | None) -> None:
        """The 1-based row the terminal reported its cursor on after a stop: the region knows its place from the next frame.

        None (no report) or a row outside the screen leaves the place unknown,
        as without the report, until output has pushed it to certainty.
        """
        if row is not None and 1 <= row <= self.screen[1] and not self.region.height:
            self.region = self._new_region(start_row=row - 1)

    @property
    def model(self) -> str:
        return self.model_name

    @model.setter
    def model(self, value: str) -> None:
        """The session's model; the transcript names it on each reply begun under it."""
        self.model_name = value
        self.transcript.model = value

    def _painted(self, theme: Theme) -> Theme:
        """`theme` as this terminal paints it: without colour at the `NO_COLOR` depth (`style.color_depth`)."""
        return without_colour(theme) if self.color_depth == NO_COLOR else theme

    def _themed(self) -> Theme:
        """The skin's theme against the background, with the shown launch look's band behind a sent prompt and the
        roles it owns (`with_launch_look`), painted."""
        skin, surface, look = self._skin(), self._surface(), self._shown_look()
        banded = with_prompt_band(build_theme(skin, surface), skin, surface, look)
        return self._painted(with_launch_look(banded, skin, surface, look))

    def _skin(self) -> SkinTheme:
        return theme_for_name(self.theme.name) or default_theme()

    def _surface(self) -> str | None:
        """What the theme is measured against: the reported background, a dark one `COLORFGBG` named, or a light or
        dark one `/theme` forced."""
        reported = self.background
        if self.background_mode == BACKGROUND_LIGHT:
            return reported if reported and is_light(reported) else LIGHT_STAND_IN
        if self.background_mode == BACKGROUND_DARK or self.background_named_dark:
            # The palette's status-bar background stands in for a dark one the person or `COLORFGBG` named: named, it
            # is no guess, so the bands that need a known background are painted (None would read as nothing reported).
            return reported if reported and not is_light(reported) else surface_for(self._skin(), None)
        return reported

    def run(self, typed: bytes = b"") -> int:
        """Run until the person quits or the gateway is gone for good (`_respawn_gateway`); the exit code.

        `typed` is input that arrived before the loop started (while the
        background query waited); it is read before the first frame. The live
        region is cleared before this returns; closing the gateway is the
        caller's, after it has handed the terminal back.
        """
        self.wake = self.client.wake_fd()
        self.poller.start(self._wake_loop)  # a new HUD snapshot wakes the loop as gateway news does
        if self.git is not None:
            self.git.start(self._wake_loop)  # so does a branch or a file count that moved
        try:
            if typed:
                self._take_input(typed)
            self._render_when_due()  # the first frame does not wait for a first read
            while self.exit_code is None:
                self._step()
        finally:
            self._shutdown()
        return self.exit_code

    def _step(self) -> None:
        if self.terminal.resized():
            self._on_resize()
        timeout, pace = self._read_timeout(), self.last_render + MIN_FRAME_SECONDS - self.clock()
        try:
            if pace > 0:  # a frame was just drawn: gateway news waits out the interval, input does not
                data = self.terminal.read(min(timeout, pace))
            else:
                data = self.terminal.read(timeout, self.wake)
        except EOFError:
            self.exit_code = 0
            return
        if self.terminal.resized():  # one that ended the read: nothing in this step is drawn at the old size
            self._on_resize()
        self._take_input(data)
        if self.exit_code is not None:
            return
        self._drain_gateway()
        if self.respawn_reason:
            self._respawn_gateway()
        if self.exit_code is not None:
            return
        self._expire_calls()
        self._expire_notification()
        self._expire_escape()
        self._expire_exit()
        self._track_path_token()
        self._ask_path_completion_when_due()
        self._ask_tail_when_due()
        self._take_hud()
        self._take_board()
        self._render_when_due()

    def _take_input(self, data: bytes) -> None:
        """Decode `data` and act on each key; an empty read settles held bytes once input has been quiet long enough.

        Keys a respawn read while it waited (`held_input`) come before the ones
        read now; keys read while one of these waited (the cursor query after
        fg) come after the keys before them.
        """
        if data:
            self.input_at = self.clock()
            events = self.decoder.feed(data)
        elif self.clock() - self.input_at >= FLUSH_SILENCE_SECONDS:
            # A report the terminal sent before an off may still be on its way: the decoder waits for it.
            events = self.decoder.flush(self.terminal.mouse_reporting, self.mouse_off_at)
        else:
            events = []
        pending, self.held_input = [*self.held_input, *events], []
        while pending:
            for event in pending:
                self.dirty = True
                self._on_input(event)
                if self.exit_code is not None:
                    return
            pending, self.held_input = self.held_input, []

    def _read_timeout(self) -> float:
        """How long the next read may wait: until the soonest thing the loop has to do without new input.

        Input, a wake-up from the gateway client and a resize end the wait
        sooner. Held key bytes, a spinner tick while a turn runs or the panel
        is live, the settled resize, the debounced path completion and the
        next agent tail call each set a deadline; without one it is
        `IDLE_READ_SECONDS`.
        """
        now = self.clock()
        due = [now + IDLE_READ_SECONDS]
        if self.decoder.holding:
            due.append(now + READ_TIMEOUT_SECONDS)
        if self.redraw_at is not None:
            due.append(self.redraw_at)
        elif self._busy() or self._panel_live() or self._aura_live() or self._background_live() or self.held_submits:
            due.append(self.last_render + self._tick_seconds())
        if self.path_due is not None and self.sid:
            due.append(self.path_due)
        tail = self._tail_due_at()
        if tail is not None:
            due.append(tail)
        if self.notification is not None and self.notification.expires_at < math.inf:
            due.append(self.notification.expires_at)
        if self.copy_noted_at is not None:
            due.append(self.copy_noted_at + COPY_NOTE_SECONDS)
        if self.escape_armed is not None:
            due.append(self.escape_armed[1] + DOUBLE_ESCAPE_SECONDS)
        if self.exit_armed_at is not None:
            due.append(self.exit_armed_at + EXIT_CONFIRM_SECONDS)
        return max(min(due) - now, 0.0)

    def _expire_notification(self) -> None:
        """Take a ttl notification off the screen once its time is up."""
        if self.notification is not None and self.clock() >= self.notification.expires_at:
            self.notification = None
            self.dirty = True
        if self.copy_noted_at is not None and self.clock() - self.copy_noted_at >= COPY_NOTE_SECONDS:
            self.copy_noted_at = None
            if self.pager is not None:
                self.pager.note = ()
            self.dirty = True

    def _shutdown(self) -> None:
        """Hand the screen back to the shell, then stop the HUD poller, turn off yolo the TUI set and release herdr.

        The terminal writes come first (reports off, the alternate screen
        left, the live region erased whatever the last lines' rendering
        raises), and the other steps run whatever those raise, so a failing
        step never leaves the shell on the alternate screen or with reports
        on. A hung-up terminal (SIGHUP, a closed window) refuses every write
        with EIO and has no screen to hand back: that ends the writes quietly,
        as in `Terminal._restore`, and the exit already under way (the
        signal's SystemExit) is the one that propagates.
        """
        reports_may_arrive = self._reports_may_arrive()  # read before the off below starts a new grace period
        try:
            self._set_mouse(False)
            if self.pager is not None:
                self.pager = None
                self._stop_board_reader()
                self.terminal.write(ALT_SCREEN_OFF + SHOW_CURSOR)
                if self.redraw_after_pager:  # owed while it showed: what is left is the session as it now stands
                    self.redraw_after_pager = False
                    self._full_redraw()
            cols = self.size[0]
            try:
                stable = self.transcript.take_stable_lines(cols, self.theme)
                if stable:
                    self.region.flush_above(stable, cols)
            finally:
                self.region.clear()
            if self.title_pushed:
                self.terminal.write(TITLE_POP)  # the title the shell had
                self.title_pushed = False
            if reports_may_arrive:
                self._discard_late_reports()
        except OSError as error:
            if error.errno != errno.EIO:
                raise
        finally:
            try:
                self.poller.stop()
                if self.git is not None:
                    self.git.stop()
                if self.board_reader is not None:
                    self.board_reader.close()
            finally:
                try:
                    if self.sid:  # the gateway may outlive the TUI by its close grace, or longer
                        self._turn_off_yolo_set_here(self.sid)
                finally:
                    self.herdr.release()  # herdr keeps the pane's agent after the TUI exits until told

    def _set_mouse(self, enabled: bool, drag: bool = False) -> None:
        """Turn mouse reports on or off (with a held button's motion, `drag`), noting when they went off: reports sent
        before the off still arrive after it."""
        was_on = self.terminal.mouse_reporting
        self.terminal.set_mouse(enabled, drag)
        if was_on and not self.terminal.mouse_reporting:
            self.mouse_off_at = self.clock()

    def _reports_may_arrive(self) -> bool:
        """Whether a mouse report may still arrive: reporting is on, or went off less than `MOUSE_REPORT_SECONDS` ago."""
        off_at = self.mouse_off_at
        return self.terminal.mouse_reporting or (off_at is not None and self.clock() - off_at < MOUSE_REPORT_SECONDS)

    def _discard_late_reports(self) -> None:
        """Ask for the cursor position, then read and drop input up to the answer, for at most `EXIT_DRAIN_SECONDS`.

        Runs only when a report may still be on its way as the TUI leaves:
        reporting was on as the shutdown began, or went off less than
        `MOUSE_REPORT_SECONDS` before it. Otherwise nothing is asked, so no
        answer can reach the shell. The terminal answers the request only
        once it has acted on everything sent before it, so every report comes
        ahead of the answer, and the drain stops the moment the answer is
        read. Keys typed in that window are discarded with the reports: they
        are bytes the closing TUI has already read, and it acts on no input
        any more. A terminal that does not answer within the bound ends the
        drain there, as a read that waited out the time left does, and its
        answer, if it comes later, reaches the shell as `ESC[<row>;<col>R`. A
        read a resize signal ends early with nothing read does not end it.
        That takes a round trip over a second just after a click, on a link
        where the reports the drain exists for would reach the shell too: one
        late answer is the price of dropping every report ahead of it.
        """
        self.terminal.write(CURSOR_POSITION_REQUEST)
        deadline = self.clock() + EXIT_DRAIN_SECONDS
        seen = b""
        while (left := deadline - self.clock()) > 0:
            try:
                data = self.terminal.read(left)
            except EOFError:
                return  # the terminal hung up: nothing more is coming
            if not data:
                continue  # waited out (the loop ends) or ended early by a resize signal (it reads on)
            seen = seen[-32:] + data  # the last read's tail too: an answer can be split across two reads
            if _holds_cursor_report(seen):
                return

    def _busy(self) -> bool:
        return self.transcript.running or self.turn_pending

    def _wake_loop(self) -> None:
        """Make the live gateway client's descriptor readable, from any thread: the HUD poller's wake-up."""
        self.client.wake()

    # ── gateway ──

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        on_result: Callable[[dict[str, Any]], None],
        on_error: Callable[[dict[str, Any]], bool] | None = None,
        on_expiry: Callable[[float], None] | None = None,
        steer: SteerBlock | None = None,
        seconds: float | None = None,
        compressing: bool = False,
    ) -> None:
        try:
            request_id = self.client.request(method, params)
        except GatewayUnavailable as error:
            self._gateway_gone(str(error))
            return
        except ValueError as error:  # the gateway contract refused the call (`contract.call_problem`): nothing went out
            self.transcript.add_notice(f"The OMH TUI did not send {method}: {error}.", NOTICE_ERROR)
            return
        seconds = seconds or CALL_ANSWER_SECONDS_BY_METHOD.get(method, CALL_ANSWER_SECONDS)
        held = self._compression_left()
        if held is not None:  # it waits behind the compression, then gets its own budget, never past HELD_ANSWER_SECONDS
            seconds = min(held + seconds, HELD_ANSWER_SECONDS)
        self.pending[request_id] = _Pending(
            method, on_result, on_error, self.clock() + seconds, self.transcript.command, on_expiry, steer, seconds,
            compressing,
        )

    def _expire_calls(self) -> None:
        """Forget every call unanswered past its `expires_at`, here and in the client, saying so for most.

        Neither of its handlers runs: an answer that never came is not a
        refusal, and state that waits on one (a yolo call still unanswered)
        stays as it was. A call with an `on_expiry` (a steer, whose row and
        text wait on the answer) is settled by it instead, given the seconds the
        call was waited for (more than its own budget when it was held behind a
        `/compress`), and says so itself.
        """
        now = self.clock()
        for request_id, call in [(rid, call) for rid, call in self.pending.items() if now >= call.expires_at]:
            del self.pending[request_id]
            self.client.forget(request_id)
            if call.on_expiry is not None:
                call.on_expiry(call.seconds)
            elif call.method not in QUIET_EXPIRY_METHODS:
                notice = CALL_EXPIRED_NOTICE.format(method=call.method, seconds=call.seconds)
                if call.command is None:
                    self.transcript.add_aside(NoticeBlock(notice, NOTICE_WARN))  # never closes what runs
                else:
                    with self._for_command(call.command):  # under the echo of the command it was made for
                        self.transcript.add_notice(notice, NOTICE_WARN)
            self._command_call_done(call)

    @contextmanager
    def _for_command(self, command: CommandBlock | None) -> Iterator[None]:
        """While inside, what is said lands under `command`'s echo while it is open, and a call made is its call."""
        transcript = self.transcript
        outer, transcript.command = transcript.command, command
        try:
            yield
        finally:
            transcript.command = outer

    def _command_call_done(self, call: _Pending) -> None:
        """A command's call is answered or forgotten: once none made for it is left, the command's echo closes."""
        command = call.command
        if command is not None and not any(pending.command is command for pending in self.pending.values()):
            self.transcript.close_command(command)

    def _respond(self, answer: Answer) -> None:
        local = self.local_questions.pop(answer.request_id, None)
        if local is not None:  # a question the TUI asked itself (`_ask_locally`): nothing goes to Hermes
            local(answer.frame)
            return
        try:
            self.client.respond(answer.request_id, answer.frame)
        except GatewayUnavailable as error:
            self._gateway_gone(str(error))

    def _gateway_gone(self, reason: str, code: int | None = None) -> None:
        """The gateway child is gone: a respawn is due once this step ends, where one is allowed, else the TUI leaves.

        Never after a normal exit (code 0), once the person is leaving, without
        a way to spawn one, or when the launcher handed over a gateway another
        runtime owns (`HERMES_TUI_GATEWAY_URL`, refused before any spawn).
        """
        if self.exit_code is not None or self.respawn_reason:
            return
        if self.make_client is None or code == 0 or attach_refused(self.environ):
            self._lose_gateway(reason)
            return
        self.respawn_reason = reason

    def _respawn_gateway(self) -> None:
        """Spawn the gateway again, as the launcher's environment says, and resume the session that was open.

        The open question and the ones waiting behind it close unanswered,
        since the gateway that asked is gone; a running turn is reported lost
        and never sent again; the queue is held as after an interrupt
        (`_hold_queue`). At most `RESPAWN_LIMIT` respawns in
        `RESPAWN_WINDOW_SECONDS`, each saying so; a gateway that does not start
        again, or exits before it resumed the session, uses one and the next is
        tried, as Hermes' own TUI keeps its recovery target (ui-tui
        `gatewayRecovery.ts`). Past the limit, without a stored session, or
        when the new gateway refuses the resume or does not answer it, the TUI
        leaves as it would without recovery (`_lose_gateway`). Calls the old gateway had
        not answered are settled at once (`_settle_lost_calls`), and the new
        client's request ids start past theirs.

        One child at a time: the old gateway is reaped before a new one is
        spawned (it may still run, after a write it refused or an exit whose
        code never came), and each new client is the app's `client` from the
        moment it is made, so whatever ends the TUI while it starts or resumes
        (SIGTERM, SIGHUP) leaves it to `_run`, which reaps it. While a new
        gateway starts or resumes, Ctrl+C or Ctrl+D ends the TUI as an exhausted
        respawn does (`_respawn_cancel`), the new child reaped; other keys read
        meanwhile wait for the loop.
        """
        reason, self.respawn_reason = self.respawn_reason, ""
        stored = self.stored_id
        self._close_questions_unanswered()
        if self._busy():
            self.transcript.fail_turn(TURN_LOST_NOTICE)
        self.turn_pending = self.interrupting = False
        self._lose_roster()  # they stay in the agent view, so the HUD's agents block does not take them up instead
        self.list_selected = None
        first_id = max(self.pending, default=0) + 1
        self._settle_lost_calls()
        self.default_asked = False  # a read or switch for Hermes' default went with the old gateway: ask again
        # The new gateway holds no image, and a staging the old one did not answer sends nothing; what waited for the
        # old one's admission goes with it, as its running turn does. The next send stages from the TUI's bytes.
        self._reset_staging(UNSENT_BACK_RESPAWN)
        if self.starting is not None:  # the prompt it held never went: back to the draft, never sent again
            self._give_back(self.starting[0], self.starting_images)
            self.starting, self.starting_images = None, ()
        self._give_back_tell()
        old: GatewayClient | None = self.client
        while True:
            now = self.clock()
            self.respawned_at = [at for at in self.respawned_at if now - at < RESPAWN_WINDOW_SECONDS]
            if not stored or len(self.respawned_at) >= RESPAWN_LIMIT:
                self._lose_gateway(reason)
                return
            self.respawned_at.append(now)
            self.transcript.add_notice(RESPAWN_NOTICE.format(
                reason=reason[:1].upper() + reason[1:], session=stored, attempt=len(self.respawned_at),
                limit=RESPAWN_LIMIT, window=RESPAWN_WINDOW_SECONDS,
            ), NOTICE_WARN)
            self.dirty = True
            self._render_when_due()  # the notice shows while the old gateway is reaped and the new one starts
            if self.redraw_at is not None:  # a resize waits to settle, and what follows blocks: redraw now instead
                self.redraw_at = self.clock()
                self._render_when_due()
            if old is not None:  # reaped before a new one is spawned, once the screen says why the TUI waits
                old.close(grace=CLOSE_GRACE_SECONDS, terminate_grace=TERMINATE_GRACE_SECONDS)
                old = None
            try:
                self.client = self.make_client(gateway_spawn(self.environ), first_id=first_id)
                self.client.start(ready_timeout=respawn_ready_seconds(self.environ), cancel=self._respawn_cancel)
            except GatewayCancelled:  # `start` reaped its child
                self._lose_gateway(RESPAWN_LEFT_REASON)
                return
            except (GatewayUnavailable, GatewayCallError) as error:
                reason = f"the new Hermes gateway did not start ({error})"
                continue
            try:
                result = self.client.call(
                    "session.resume", {"session_id": stored, "cols": self.size[0]}, cancel=self._respawn_cancel
                )
            except GatewayCancelled:
                self.client.close(grace=CLOSE_GRACE_SECONDS, terminate_grace=TERMINATE_GRACE_SECONDS)
                self._lose_gateway(RESPAWN_LEFT_REASON)
                return
            except GatewayUnavailable as error:  # it exited too: the next attempt resumes the same session
                self.client.close(grace=CLOSE_GRACE_SECONDS, terminate_grace=TERMINATE_GRACE_SECONDS)
                reason = f"the new Hermes gateway exited before it resumed session {stored} ({error})"
                continue
            except (GatewayCallError, GatewayTimeout) as error:
                self.client.close(grace=CLOSE_GRACE_SECONDS, terminate_grace=TERMINATE_GRACE_SECONDS)
                self._lose_gateway(f"the new Hermes gateway did not resume session {stored} ({error})")
                return
            break
        self.wake = self.client.wake_fd()
        self._adopt_session(result, fallback_stored=stored)
        self.transcript.add_notice(RESPAWNED_NOTICE.format(session=self.stored_id), NOTICE_OK)
        self._hold_queue(RESPAWNED_WHY)
        self._request("config.get", {"key": "full"}, self._take_settings, self._on_settings_refused)
        self._refresh_catalog()
        self._redeliver(result.get("open_requests"))

    def _settle_lost_calls(self) -> None:
        """The calls the exited gateway never answered, settled now rather than when their wait runs out.

        A steer's row closes and its text comes back to the draft, never sent
        again (Hermes may have taken it), with one notice for them all; every
        other call is forgotten without one, and the echo of a command it was
        made for closes.
        """
        calls = list(self.pending.values())
        self.pending.clear()
        steers = 0
        for call in calls:
            if call.steer is not None:
                self.transcript.steer_answered(call.steer, STEER_REFUSED, STEER_LOST_OUTCOME)
                self._give_back(call.steer.text)
                steers += 1
            if call.command is not None:
                self.transcript.close_command(call.command)
        if steers:
            self.transcript.add_notice(STEER_LOST_NOTICE.format(count=steers, s="" if steers == 1 else "s"), NOTICE_WARN)

    def _respawn_cancel(self) -> bool:
        """Asked while a respawn waits on the new gateway: True once the person pressed Ctrl+C or Ctrl+D, or the
        terminal hung up. Every other key read meanwhile is kept for the loop, in order (`held_input`)."""
        try:
            data = self.terminal.read(0.0)
        except EOFError:
            return True
        if not data:
            return False
        self.input_at = self.clock()
        for event in self.decoder.feed(data):
            leaves = isinstance(event, Key) and event.name == CHAR and event.ctrl and not event.alt
            if leaves and event.char in LEAVE_CHARS:
                return True
            self.held_input.append(event)
        return False

    def _give_back_tell(self) -> None:
        """An open tell field closes with the gateway its deny went to; what was typed in it goes back to the draft,
        never sent, with a notice, as a lost steer's text does."""
        if self.tell_draft is None:
            return
        typed = self.composer.expanded()
        self._leave_tell()
        if typed.strip():
            self._give_back(typed)
            self.transcript.add_notice(TELL_LOST_NOTICE, NOTICE_WARN)

    def _close_questions_unanswered(self) -> None:
        """Close the open question and drop the waiting ones without an answer: the gateway that asked is gone."""
        self.waiting_requests.clear()
        self.local_questions.clear()  # a model confirmation is about a switch the old gateway never made
        slot = self.slot
        if slot is not None:
            self._close_slot()
            self.transcript.add_notice(QUESTION_LOST_NOTICE.format(method=slot.method), NOTICE_WARN)

    def _lose_gateway(self, reason: str) -> None:
        if self.exit_code is not None:
            return
        self.transcript.add_notice(f"{reason}.", NOTICE_ERROR)
        omh_way = self._omh_resume_command()
        if omh_way:
            self.farewell = f"omh: {reason}. Resume the session: {omh_way}"
        else:
            self.farewell = f"omh: {reason}. Resume the session in Hermes' own terminal: {resume_command(self.stored_id)}"
        self.exit_code = 1

    def _omh_resume_command(self) -> str:
        """`omh --resume <id>` for the open session when `omh` launched the TUI (`SESSION_FILE_ENV`), with `-p` for a
        named profile; "" otherwise, or when the id or the profile could not be typed back as they are."""
        if not self.environ.get(SESSION_FILE_ENV) or not RESUMABLE_ID.fullmatch(self.stored_id):
            return ""
        profile = self.launch_profile
        if profile in ("", "default", "custom"):
            return f"omh --resume {self.stored_id}"
        return f"omh -p {profile} --resume {self.stored_id}" if PROFILE_NAME.fullmatch(profile) else ""

    def _drain_gateway(self) -> None:
        for item in self.client.poll():
            self.dirty = True
            if isinstance(item, Event):
                self._on_event(item)
            elif isinstance(item, ServerRequest):
                self._on_server_request(item)
            elif isinstance(item, Response):
                self._on_response(item)
            elif isinstance(item, GatewayExited):
                self._gateway_gone(f"the Hermes gateway exited (code {item.returncode})", item.returncode)
            if self.exit_code is not None or self.respawn_reason:
                return

    def _on_response(self, response: Response) -> None:
        pending = self.pending.pop(response.id, None)
        if pending is None:
            return
        try:
            with self._for_command(pending.command):  # a call made from here is the command's too
                self._answer_call(pending, response)
        finally:
            self._command_call_done(pending)

    def _answer_call(self, pending: _Pending, response: Response) -> None:
        if response.error is None:
            pending.on_result(response.result or {})
            return
        error = response.error
        if contract.is_drift_error(error) and pending.method not in contract.OPTIONAL_METHODS:
            self._lose_gateway(
                f"this Hermes refused {pending.method} ({error.get('code')}); "
                "it no longer speaks the protocol the OMH TUI was built for"
            )
            return
        if pending.on_error is not None and pending.on_error(error):
            return
        message = as_text(error.get("message")) or "refused"
        sentence = refusal_sentence(error)  # a reason code in words, never the code itself
        if pending.command is not None:
            self.transcript.add_notice(sentence or plain_sentence(message), NOTICE_ERROR)  # under the command's echo
            return
        phrase = CALL_FAILED_PHRASES.get(pending.method, f"complete {pending.method}")
        reason = message.strip().rstrip(".")
        said = f"Hermes did not {phrase}. {sentence}" if sentence else f"Hermes did not {phrase}: {reason}."
        self.transcript.add_notice(said, NOTICE_ERROR)

    def _on_event(self, event: Event) -> None:
        payload = event.payload
        if event.type in ("request.cancel", "approval.cancelled"):
            # Matched by request id whatever the envelope says: a request from a session this TUI is
            # leaving (a switch, `/new`) stays open here until its withdrawal arrives.
            self._on_withdrawn(payload)
            return
        if event.type in contract.SIDE_ANSWER_EVENTS and event.session_id != self.sid:
            self._side_answer(event.type, payload, event.session_id)  # a /bg started before a switch: never dropped
            return
        if not event.type.startswith(contract.GATEWAY_SCOPED_EVENT_PREFIX) and event.session_id != self.sid:
            return
        self._watch_turn(event.type)
        if event.type == "session.info":
            self._on_session_info(payload)
        elif event.type == "session.usage":
            self._take_usage(payload.get("usage"))
        elif event.type == "connection.request":
            self._on_connection_request(payload)
        elif event.type == "error":
            self._on_error_event(as_text(payload.get("message")) or "The gateway reported an error.")
        elif event.type == "notification.show":
            self.notification = notification_from(payload, self.clock()) or self.notification
        elif event.type == "review.summary":
            line = review_line(clean_text(as_text(payload.get(contract.REVIEW_SUMMARY_TEXT))))
            if line:  # one dim row, whenever it comes (it can come during the next turn): it closes nothing
                self.transcript.add_aside(NoticeBlock(line, one_line=True))
        elif event.type in contract.SIDE_ANSWER_EVENTS:
            self._side_answer(event.type, payload)
        elif event.type == "session.control.update":
            control = payload.get(contract.SESSION_CONTROL)
            goal = control.get(contract.CONTROL_GOAL) if isinstance(control, Mapping) else None
            done = goal_done_text(self.goal, goal if isinstance(goal, Mapping) else None)
            if done:
                self.transcript.add_aside(NoticeBlock(done, NOTICE_OK))  # the row goes; its total stays in the scrollback
            self.goal = goal if isinstance(goal, Mapping) else None
        elif event.type == "todo.updated":
            # Hermes' plan changed: the OMH plugin projected it into the session's record as the tool finished
            # (post_tool_call runs before Hermes emits this), so the HUD is read now instead of at its next poll.
            self.poller.refresh()
        elif event.type == "session.title":
            self.session_title = " ".join(clean_text(as_text(payload.get(contract.SESSION_TITLE))).split())
        elif event.type == "notification.clear":
            key = as_text(payload.get(contract.NOTIFICATION_KEY))
            if self.notification is not None and key and self.notification.key == key:
                self.notification = None  # a clear for another key, or a late one, leaves a newer notice
        elif event.type.startswith(contract.SUBAGENT_EVENT_PREFIX):
            self.roster.apply(event.type, payload, self.clock())  # folds what it knows; raises on nothing
            if isinstance(payload, Mapping):  # a new frame for an agent: its tail is asked for again
                self.tail_misses.pop(as_text(payload.get("subagent_id")), None)
        else:
            self.transcript.apply(event)
            self._track_sent_now(event.type)
            self._count_streamed(event.type, payload)
            if event.type == "tool.complete" and isinstance(payload, Mapping):
                self._dag_moment(payload)
            if event.type in ("tool.complete", "message.complete") and self.git is not None:
                self.git.refresh()  # a tool or the turn may have changed the files or the branch
            if event.type == "message.start":
                if self.claim == CLAIM_SUBMITTED:
                    self._claimed()  # Hermes admitted the turn, so it took what was staged for it
                self.bg_done = None  # the session is awake: the row's offer was for an idle one
                if not self.turn_pending:  # a turn this TUI did not start (a resumed one, a server queue)
                    self.busy_since = self.clock()
                    self.turn_waited = 0.0
                    self._count_from_here()
                self.turn_pending = False
            elif event.type == "message.complete":
                self.turn_pending = False
                self._take_usage(payload.get("usage"))
                self._dag_ends_due()
                self._retire_finished_plan()  # above the done line: the turn that finished the plan ends here
                seconds = self.clock() - self.busy_since
                self.transcript.add_turn_summary(seconds, self._turn_tokens(), self._turn_wait())
                self._alert_turn_end(seconds)
                self._turn_ended()

    def _dag_moment(self, payload: Mapping[str, Any]) -> None:
        """An `omh_dag` call that defined, repaired, extended or ended a run prints the run's graph (`dag_block`)."""
        found = dag_block.moment(payload, self.dag_ends)
        if found is None:
            return
        title, run, _added = found
        if title.startswith(dag_block.END):
            # The end waits for the turn's end: a goal check that extends the run in the same turn moves it on, and
            # the extend's block shows that instead of an end the person never saw happen.
            self.dag_end_due[run] = title
            return
        self.dag_end_due.pop(run, None)
        graph = self._read_dag_graph()
        if graph is not None:
            self.transcript.add_aside(dag_block.DagBlock(title, graph, added=tuple(_added)))

    def _dag_ends_due(self) -> None:
        """The run ends this turn reached, each printed once if its run is still over as the turn ends."""
        due, self.dag_end_due = self.dag_end_due, {}
        for title in due.values():
            graph = self._read_dag_graph()
            if graph is not None and not graph.get("dag_open"):
                self.transcript.add_aside(dag_block.DagBlock(title, graph))
                # The view under the composer goes in the frame that prints the end: this read is fresher than the
                # panel's payload, which can still show a lane running.
                self._retire_finished_run(graph)

    def _read_dag_graph(self) -> Mapping[str, Any] | None:
        return self.read_dag_graph(self.environ.get("OMH_HOME") or None, self.environ.get("HERMES_HOME") or None,
                                   self.stored_id)

    def _alert_question(self, slot: PromptSlot) -> None:
        """Once per request, as its slot opens (the wait is on the person), however many questions a clarify carries:
        the bell an approval always rang, and where the terminal shows the turn end's notification (OSC 9 or 777)
        that too, saying what Hermes asks; none with OMH_TUI_BELL=0."""
        if self.environ.get(BELL_ENV) == BELL_OFF:
            return
        signal = attention_sequence(self.environ, truncate(slot.attention(), QUESTION_ALERT_CHARS))
        self.terminal.write(BELL if signal == BELL else BELL + signal)

    def _alert_turn_end(self, seconds: float) -> None:
        """A turn of `TURN_ALERT_SECONDS` or more ends with the terminal's attention signal, unless OMH_TUI_BELL=0."""
        if seconds < TURN_ALERT_SECONDS or self.environ.get(BELL_ENV) == BELL_OFF:
            return
        self.terminal.write(attention_sequence(self.environ, TURN_ALERT_TEXT.format(elapsed=elapsed_text(seconds))))

    def _write_title(self) -> None:
        """The terminal title, `<session title> · <state>`, written only when it changed (the first one pushes the old)."""
        state = STATE_WAITING if self.slot is not None else STATE_RUNNING if self._busy() else STATE_IDLE
        self.herdr.report(HERDR_STATES[state])
        words = f"{self.session_title or TITLE_DEFAULT} · {state}"
        if words == self.title_words:
            return  # every frame asks; most change nothing here
        self.title_words = words
        title = truncate_left(words, TITLE_CHARS)
        if title == self.shown_title:
            return
        self.shown_title = title
        push = "" if self.title_pushed else TITLE_PUSH
        self.title_pushed = True
        self.terminal.write(push + TITLE_SET.format(title))  # the session title was cleaned as it arrived

    def _watch_turn(self, event_type: str) -> None:
        """Say once when a submitted turn has brought no event it shows, only types the contract does not declare.

        The first of TURN_PROGRESS_EVENTS ends the watch for the turn, and so
        does a turn that is no longer pending (refused) and a session change
        (`_adopt_session`); any other declared type, and a gateway-scoped one,
        neither counts nor ends it. The count starts again with every turn,
        but a turn whose undeclared types were all named before says nothing:
        a Hermes that streams a new harmless type ahead of every turn would
        otherwise repeat the notice on each one. A turn whose events Hermes
        renamed would otherwise only look like one that never finishes.
        """
        unknown = self.turn_unknown
        if unknown is None or event_type.startswith(contract.GATEWAY_SCOPED_EVENT_PREFIX):
            return
        if event_type in TURN_PROGRESS_EVENTS or not self.turn_pending:
            self.turn_unknown = None
            return
        if event_type in contract.HANDLED_EVENTS or event_type in contract.UNREAD_EVENTS:
            return
        if event_type not in unknown:
            unknown.append(event_type)
        self.turn_unknown_count += 1
        if self.turn_unknown_count > UNKNOWN_EVENTS_BEFORE_NOTICE:
            if not self.unknown_named.issuperset(unknown):
                types = ", ".join(clean_text(name)[:UNKNOWN_EVENT_NAME_CHARS] for name in unknown)
                self.transcript.add_notice(UNKNOWN_EVENTS_NOTICE.format(types=types), NOTICE_WARN)
                self.unknown_named.update(unknown)
            self.turn_unknown = None

    def _on_error_event(self, message: str) -> None:
        """A bare `error` event; during a turn it ends that turn.

        Hermes sends no `message.complete` after it refuses a turn (another
        process owns the session) or cancels one before the agent was ready, so
        the turn closes here and the queue moves on, as Ink's `recordError` does
        (unless the person interrupted the turn: `_turn_ended`).
        """
        if not self._busy():
            self.transcript.add_notice(message, NOTICE_ERROR)
            return
        self.transcript.fail_turn(message)
        self.turn_pending = False
        self._turn_ended()

    def _on_connection_request(self, payload: Mapping[str, Any]) -> None:
        """Hermes waits on an app connection the TUI cannot complete; say so once per operation."""
        operation = as_text(payload.get("op_id"))
        if operation in self.connection_ops:
            return
        self.connection_ops.add(operation)
        self.transcript.add_notice(CONNECTION_NOTICE, NOTICE_WARN)

    def _on_session_info(self, payload: Mapping[str, Any]) -> None:
        self._take_skills(payload)
        self._take_title(payload)
        self.model = as_text(payload.get("model")) or self.model
        self._take_usage(payload.get("usage"))
        self._take_session_state(payload)
        # `running` is not read: the previous turn's closing `running: false` arrives after
        # `message.complete`, by which time a queued prompt may already be pending.
        self._adopt_stored(as_text(payload.get("stored_session_id")))

    def _take_title(self, info: Mapping[str, Any]) -> None:
        """The title a session's info names (a resumed session's, or one Hermes named since); one naming none, as a
        lazy info does, leaves the shown one. `session.title` says a rename as it happens."""
        title = " ".join(clean_text(as_text(info.get(contract.SESSION_TITLE))).split())
        if title:
            self.session_title = title

    def _take_skills(self, info: Mapping[str, Any]) -> None:
        """The skills a session's info names replace the shown ones; an info naming none leaves them.

        Hermes' lazy info (a stdio `session.create`'s, its first `session.info`) names none and the full one after
        its build does; over a shared gateway the `session.create` answer already names them all and no
        `session.info` follows, so both are read.
        """
        skills = info.get("skills")
        if not isinstance(skills, dict) or not skills:
            return
        rows = skill_rows({key: value for key, value in skills.items() if isinstance(value, list)})
        home = self._snapshot_home()
        # What the next launch draws first, kept only when this info names the profile the launch opened on.
        same_profile = info.get("profile_name") == self.launch_profile
        if home is not None and same_profile and rows != self.snapshot_kept:
            write_snapshot(home, *self._snapshot_key(), rows)
            self.snapshot_kept = rows
        self.session_skills = rows
        self.dirty = True

    def _take_usage(self, usage: object) -> None:
        """A usage block with context figures replaces the shown ones; one without leaves them. Its `output` counts tokens.

        A turn's tokens are the `output` counter's rise from where it stood as
        the turn began. The counter has started over when a block reads less
        than that, or reads more with no more `calls` than then: the turn
        counts from 0, and so does every later turn of the session. Hermes
        bf0203a794's gateway starts both counters over at every turn (each
        turn's `calls` begins at 1 again), so a turn's first block can read 50
        after the last turn's 9. A turn that began with no counter known (one
        already running when its session was opened) counts from the first
        block it brings. A block that moves the counter replaces the estimate
        of what streamed before it.
        """
        percent = context_percent(usage)
        if percent is not None:
            self.context_percent = percent
        output, calls = usage_count(usage, "output"), usage_count(usage, "calls")
        if output is None:
            return
        base, calls_base = self.turn_output_base, self.turn_calls_base
        if base is None:
            if self._busy():
                self.turn_output_base, self.turn_calls_base = output, calls
        elif output < base or (output != base and calls is not None and calls_base is not None and calls <= calls_base):
            self.turn_output_base, self.turn_calls_base = 0, 0
            self.usage_restarts = True
        if output != self.usage_output:
            self.turn_streamed = 0.0
        self.usage_output, self.usage_calls = output, calls
        self._raise_shown()

    def _count_from_here(self) -> None:
        """A turn begins: its tokens count from the counter as it stands, or from 0 once the counter has started over."""
        self.turn_output_base = 0 if self.usage_restarts else self.usage_output
        self.turn_calls_base = 0 if self.usage_restarts else self.usage_calls
        self.turn_streamed, self.turn_shown = 0.0, 0
        self.spinner_verb = ""

    def _count_streamed(self, event_type: str, payload: object) -> None:
        """What the model wrote, as it reaches the TUI during a turn: the reply and the reasoning as they stream,
        commentary that did not stream, and a tool call's arguments as the call starts (Hermes streams only its name).

        With Hermes' `display.show_reasoning` off no reasoning streams, so a
        turn that thinks counts only at its next usage block.
        """
        if not self._busy() or not isinstance(payload, Mapping):
            return
        if event_type in ("message.delta", "reasoning.delta"):
            text = as_text(payload.get("text"))
        elif event_type == "message.interim" and not payload.get("already_streamed"):
            text = as_text(payload.get("text"))
        elif event_type == "tool.start" and payload.get("args"):
            text = json.dumps(payload.get("args"), ensure_ascii=False)
        else:
            return
        self.turn_streamed += streamed_tokens(text)
        self._raise_shown()

    def _raise_shown(self) -> None:
        """The working row's tokens: the counter's rise and what streamed since it last moved, never fewer than it said."""
        self.turn_shown = max(self.turn_shown, (self._turn_tokens() or 0) + math.ceil(self.turn_streamed))

    def _turn_tokens(self) -> int | None:
        """What the running (or just ended) turn has written, by the usage counter; None before it has written any."""
        if self.usage_output is None or self.turn_output_base is None:
            return None
        written = self.usage_output - self.turn_output_base
        return written if written > 0 else None

    def _on_withdrawn(self, payload: Mapping[str, Any]) -> None:
        ids = {as_text(payload.get("id"))} - {""}
        request_ids = payload.get("request_ids")
        if isinstance(request_ids, list):
            ids.update(value for value in request_ids if isinstance(value, str) and value)
        self.waiting_requests = deque(
            request for request in self.waiting_requests if not _matches(request.id, request.params, ids)
        )
        slot = self.slot
        if slot is not None and _matches(slot.request_id, slot.params, ids):
            self._close_slot()
            self.transcript.add_answer(slot.withdrawn_outcome(as_text(payload.get("reason"))), NOTICE_ERROR,
                                       clarify=slot.method == "clarify")

    # ── server requests and the prompt slot ──

    def _on_server_request(self, request: ServerRequest) -> None:
        """Open `request` in the slot, or queue it behind the open one; one the TUI cannot show is declined at once."""
        opened = open_request(request.id, request.method, request.params)
        if isinstance(opened, ImmediateAnswer):
            self._respond(opened.answer)
            self.transcript.add_notice(opened.notice, NOTICE_WARN)
            return
        if self.slot is not None:
            self.waiting_requests.append(request)
            return
        if self.pager is not None:
            self._leave_pager()
        if self.chains_open:
            self.chains_closing = True  # the picker cancels at its next read; the question shows once it has closed
        self.slot = opened
        self.slot_opened_at = self.clock()
        if self.waiting_since is None:
            self.waiting_since = self.slot_opened_at
            self.transcript.set_waiting(True)
        self.slot_arm_seconds = REPORTING_SLOT_ARM_SECONDS if self._reports_may_arrive() else SLOT_ARM_SECONDS
        self._settle_list()  # a question has the keys now: the agent list gives them up
        self._alert_question(opened)
        if opened.wants_text:
            # An answer to Hermes is typed into a composer of its own, which records no history.
            self.slot_draft, self.composer = self.composer, Composer(masked=opened.masked, records_history=False)

    def _answer(self, answer: Answer) -> None:
        self._respond(answer)
        if answer.stops and self._busy():
            self._interrupt()  # after the deny, so the tool Hermes holds wakes up denied before the turn stops
        self._note_approval(answer)
        self._note_question(answer)
        if answer.tell:
            self._open_tell()  # before the slot closes: a question waiting behind it then sets this composer aside
        self._close_slot()

    def _note_question(self, answer: Answer) -> None:
        """What the person answered a clarify, sudo or secret question, under the call it was about: in green
        what they gave, in red a cancel, a decline or a skip (`PromptSlot.outcomes`; never a value typed masked)."""
        if self.slot is not None:
            clarify = self.slot.method == "clarify"
            for answered, words in self.slot.outcomes(answer.frame):
                self.transcript.add_answer(words, NOTICE_OK if answered else NOTICE_ERROR, clarify=clarify)

    def _note_approval(self, answer: Answer) -> None:
        """An approval's answer, in green or red, under the tool call it was about: what the person decided."""
        slot = self.slot
        result = answer.frame.get("result")
        choice = result.get("choice") if slot is not None and slot.method == "approval" and isinstance(result, dict) else None
        if choice in APPROVAL_OUTCOMES:
            command = first_line(as_text(slot.params.get("command"))) if slot is not None else ""
            outcome, level = APPROVAL_OUTCOMES[choice]
            self.transcript.add_answer(f"{outcome} · {command}" if command else outcome, level)

    def _close_slot(self) -> None:
        """The slot goes and the draft comes back as it was; a request that waited behind it opens at once.

        Nothing draws a frame in between, so a waiting question that hides the
        composer opens with it still hidden.
        """
        slot, self.slot = self.slot, None
        if self.pager is not None and self.pager is self.question_view:
            self._leave_pager()  # it paged the question that just closed
        self.question_view = None
        if slot is not None and self.slot_draft is not None:
            self.composer, self.slot_draft = self.slot_draft, None
        while self.slot is None and self.waiting_requests:
            self._on_server_request(self.waiting_requests.popleft())
        if self.slot is None and self.waiting_since is not None:  # nothing waits on the person any more
            self.turn_waited += self.clock() - self.waiting_since
            self.waiting_since = None
            self.transcript.set_waiting(False)

    def _open_tell(self) -> None:
        """After an approval's tell row sent the deny: the draft is set aside and the composer, labelled on the mode
        row, takes what the person tells Hermes instead (`_tell`). It shares the draft's history.

        Picked while the field is already open (the turn went on and asked
        again), it keeps that field and what is typed in it: the composer
        there is the field, not the draft.
        """
        if self.tell_draft is not None:
            return
        self.tell_turn_runs = self._busy()
        draft = self.composer
        self.tell_draft = draft
        self.composer = Composer(history=draft.history, on_record=draft.on_record)

    def _leave_tell(self) -> None:
        """The draft comes back; what was typed to tell Hermes and not sent stays in this session's history (Up)."""
        if self.tell_draft is None:
            return
        typed = self.composer.expanded()
        self.composer, self.tell_draft = self.tell_draft, None
        self.composer.record(typed, sent=False)

    def _tell(
        self, text: str, shown: str = "", chips: tuple[tuple[str, str], ...] = (), images: Sequence[Attachment] = ()
    ) -> None:
        """What the person sent after the tell row: the draft comes back and the text goes into the turn whose
        approval was denied as a steer, the way Ctrl+Enter sends it (`_steer_or_submit`). Once that turn has ended
        it is an ordinary prompt, held behind any turn that started since (a queued prompt's) whatever the busy
        mode, so it never steers another turn. An empty send leaves the composer waiting for the text."""
        if not text.strip():
            return
        self._leave_tell()
        if self.tell_turn_runs:
            self._steer_or_submit(text, shown, chips, images)
        else:
            self._submit(text, shown, chips, hold=True, images=images)

    def _turn_wait(self) -> float:
        """Seconds questions have waited on the person in the running (or just ended) turn, the open wait included."""
        return self.turn_waited + (self.clock() - self.waiting_since if self.waiting_since is not None else 0.0)

    def _decline_all_requests(self) -> int:
        """Answer every open and waiting request with its decline frame (the session is going away); how many."""
        declined = 0
        # The waiting ones first: closing the open slot would open the next one.
        while self.waiting_requests:
            request = self.waiting_requests.popleft()
            opened = open_request(request.id, request.method, request.params)
            self._respond(opened.answer if isinstance(opened, ImmediateAnswer) else opened.decline())
            declined += 1
        if self.slot is not None:
            self._answer(self.slot.decline())
            declined += 1
        return declined

    # ── input ──

    def _set_composer(self, text: str) -> None:
        self.composer.replace(0, len(self.composer.text), text)

    def _on_input(self, event: Key | Paste | Mouse) -> None:
        if isinstance(event, Mouse):
            if self.launch_picker is not None:
                self._launch_picker_click(event)
            elif self.pager is not None:
                self._pager_mouse(event)
            else:
                self._on_mouse(event)  # never a key: whatever it is, it types nothing
            return
        if self.pager is not None:
            self.pager.clear_selection()  # it is of the page on the screen, which a key may move
            if self.log_agent and isinstance(event, Key) and event.name in (LEFT, RIGHT):
                self._step_agent_log(-1 if event.name == LEFT else 1)
            elif not self.pager.handle_key(event, self.screen[1]):
                self._leave_pager()
            return
        if self._display_key(event):
            return
        if self.slot is not None and self._slot_arming(event):
            return  # in the first moment of a question every key is ignored: nothing typed, cleared or sent
        if self.slot is not None and _slot_owns(self.slot, event, self.composer.text):
            question = self.slot.question_index
            answer = self.slot.handle_key(event)
            if isinstance(answer, TypeIt):
                self.composer.handle(answer.key)  # the key that opened the clarify's text field is its first text
            elif answer is not None:
                self._answer(answer)
            else:
                self._next_question(question)
            return
        if self.slot is None and self.picker is not None:
            self._picker_key(event)
            return
        if self.slot is None and self.search is not None:
            self._search_key(event)
            return
        if self.slot is None and self.rewind_picker is not None:
            self._rewind_picker_key(event)
            return
        if self.slot is None and self.model_picker is not None:
            self._model_picker_key(event)
            return
        if self.slot is None and self.launch_picker is not None:
            self._launch_picker_key(event)
            return
        if self.slot is None and self._agent_list_key(event):
            return
        if self.slot is None and (
            self._mode_key(event) or self._effort_key(event) or self._guide_key(event) or self._search_open_key(event)
            or self._sessions_key(event) or self._board_key(event) or self._plan_fold_key(event)
        ):
            return
        if self.slot is None and (self._attachment_input(event) or self._escape(event)):
            return
        if self.slot is None and isinstance(event, Key) and (self._menu_moves(event) or self._menu_enter(event)):
            return
        if self.slot is None and self._recall_queue(event):
            return
        # The send-now key, as Claude Code's: while a turn runs, on an empty composer with a prompt queued that can be
        # sent, Ctrl+Enter (or Ctrl+J, where Ctrl+Enter may arrive as Enter) sends the oldest queued prompt into the
        # turn. Anywhere else Ctrl+J adds a line, and Ctrl+Enter with text typed steers that text.
        if event in (SEND_NOW_KEY, STEER_FALLBACK_KEY) and not self.composer.text and self._steer_keys_live() and (
            self._queue_head_steers()
        ):
            self._send_queued_now()
            return
        # The second Ctrl+C leaves even over text while the info line names it (`_exit_said`): the queue an interrupt
        # gives back lands in the composer between the presses, and clearing it there would leave the TUI open. Any
        # Ctrl+C the composer would take (Shift or Alt too) counts. What the composer holds is not kept on exit; what
        # was sent or queued is in Hermes' history, where Up finds it. With a submit held for its paste the press
        # does not exit (`_exit_said`): it clears the draft as ever, and the held submit still goes.
        if isinstance(event, Key) and event.name == CHAR and event.ctrl and event.char == "c" and (
            self.composer.text and self._exit_said()
        ):
            self.exit_code = 0
            return
        before = self.composer.text
        action = self.composer.handle(event)
        if self.composer.text != before:
            self.menu_index = 0
            self.menu_closed = None
            self.escape_armed = None  # an edit takes back what a second Esc would have done
        self._on_composer(action, event, steer=isinstance(event, Key) and event.name == ENTER and event.ctrl)

    def _remember(self, text: str) -> None:
        """A line the composer recorded goes to the end of Hermes' history file too (best effort)."""
        if self.history_file is not None:
            append_entry(self.history_file, text)

    def _search_open_key(self, event: Key | Paste) -> bool:
        """Ctrl+R opens the search over the composer's history in the slot."""
        if not isinstance(event, Key) or event != Key(CHAR, "r", ctrl=True):
            return False
        self.search = HistorySearch(list(self.composer.history), self.composer.text)
        return True

    def _sessions_key(self, event: Key | Paste) -> bool:
        """Ctrl+X opens the session picker, the key Hermes' own TUI gives it; `/sessions` does the same."""
        if not isinstance(event, Key) or event != Key(CHAR, "x", ctrl=True):
            return False
        self._sessions("")
        return True

    def _plan_fold_key(self, event: Key | Paste) -> bool:
        """Ctrl+P folds the plan to its header or expands it, for the rest of the session (a new plan keeps the
        choice); a key that does nothing is the composer's while no plan shows, and while the plan is its header
        alone for want of rows, where neither folding nor expanding it changes what shows (its header offers no key)."""
        if not isinstance(event, Key) or event != Key(CHAR, "p", ctrl=True):
            return False
        payload = self.hud.payload if self.hud is not None else None
        if plan_state(payload) != "open" or not self.panel_shown:  # a menu over the plan: nothing to fold where seen
            return False
        if self.plan_room_collapsed:
            return False
        self.plan_folded = not self.plan_folded
        self.dirty = True
        return True

    def _board_key(self, event: Key | Paste) -> bool:
        """Ctrl+S opens the bot board; `/bots` does the same. Raw mode turns IXON off, so the key reaches the TUI."""
        if not isinstance(event, Key) or event != Key(CHAR, "s", ctrl=True):
            return False
        self._bots("")
        return True

    def _search_key(self, event: Key | Paste | Mouse) -> None:
        """A key for the open search: Enter puts the match in the composer, Esc leaves it as it was."""
        search = self.search
        if search is None or isinstance(event, Mouse):
            return
        action = search.handle_key(event)
        if action == SEARCH_ACCEPT:
            self._set_composer(search.current() or search.original)
        if action in (SEARCH_ACCEPT, SEARCH_CANCEL):
            self.search = None

    def _next_question(self, question: int) -> None:
        """After a key or a submit the open slot took, from its question number `question`: if it moved on.

        The next question's text field starts empty (what was typed for the
        last one is not its answer), and the question arms as a fresh slot
        does, so a key or an Enter meant for the last one cannot answer it.
        """
        if self.slot is not None and self.slot.question_index != question:
            self._set_composer("")
            self.slot_opened_at = self.clock()

    def _slot_arming(self, event: Key | Paste) -> bool:
        """Whether `event` came too early for the open slot (`SLOT_ARM_SECONDS`): it is then ignored, whatever it is.

        Timed from when the key's first byte arrived, not from when it was
        decided: an Esc waits up to `keys.REPORTING_ESCAPE_SECONDS` for a
        report's `[` after the question turned reports off, and an Esc pressed
        for the composer must not answer the question it then meets. A key
        that arrived before the slot opened, or before its current question
        appeared (`_next_question`), is early too. A key the decoder
        did not make carries no arrival and is timed from now. A slot that
        opened while a report could still arrive waits
        `REPORTING_SLOT_ARM_SECONDS` instead.
        """
        if self.slot is None:
            return False
        arrived_at = event.arrived_at if isinstance(event, Key) else None
        return (self.clock() if arrived_at is None else arrived_at) - self.slot_opened_at < self.slot_arm_seconds

    def _on_composer(self, action: ComposerAction, event: Key | Paste, steer: bool = False) -> None:
        """Act on what the composer made of `event`; `steer` says the key was Ctrl+Enter. A submit's image tokens go
        with it, to the prompt it sends."""
        if action.kind == SUBMIT:
            images = tuple(image for _label, image in action.images if isinstance(image, Attachment))
            if self.slot is None and self.tell_draft is None and self._hold_submit(action, images, steer):
                return  # it goes once the pastes it was typed with are answered, with their images
            if self.slot is not None:
                question = self.slot.question_index
                answer = self.slot.submit_text(action.text)
                if answer is not None:
                    self._answer(answer)
                else:
                    self._next_question(question)
            elif self.tell_draft is not None and self.agent_steer is None and self.rewind is None:
                self._tell(action.text, action.shown, action.chips, images)
            elif steer:
                self._steer_or_submit(action.text, action.shown, action.chips, images)
            elif not action.text and self.bg_done is not None and self.agent_steer is None and self.rewind is None:
                self._report_background()
            else:
                self._submit(action.text, action.shown, action.chips, images=images)
        elif action.kind == INTERRUPT:
            self._interrupt_or_exit()
        elif action.kind == EXIT:
            self.exit_code = 0
        elif action.kind == COMPLETE and self.slot is None:
            self._accept_completion()

    def _display_key(self, event: Key | Paste) -> bool:
        """Ctrl+O (the details view), Ctrl+L (redraw) and Ctrl+Z (suspend) work whatever has the keys; True when it
        was one.

        Ctrl+O while Hermes asks something pages that question whole instead
        and answers nothing (`_question_view`).
        """
        if not isinstance(event, Key) or event.name != CHAR or not event.ctrl or event.alt:
            return False
        if event.char == "o":
            if self.slot is None:
                self._details_view()
            else:
                self._question_view()
        elif event.char == "l":
            self._redraw("")
        elif event.char == "z":
            self._suspend()
        else:
            return False
        return True

    def _suspend(self) -> None:
        """Ctrl+Z: the live region is erased and the job stopped (`Terminal.suspend`); once the shell continues it,
        the region is drawn anew under whatever the shell printed meanwhile. Nothing happens without SIGTSTP.

        Scrollback is left as it is (no full redraw), so what the person did in
        the shell stays readable above the session's rows. The shell's window
        title is back while the job is stopped (popped, and pushed again by the
        next frame). Continued, the TUI asks the terminal for the cursor row
        (`adopt_cursor_row`), so the region knows its place from its first
        frame; keys typed while that query waited are read after
        the keys that came in the same read as the Ctrl+Z (`held_input`).
        """
        if getattr(signal, "SIGTSTP", None) is None:
            return
        self._set_mouse(False)
        self.region.clear()
        if self.title_pushed:
            self.terminal.write(TITLE_POP)
            self.title_pushed, self.shown_title, self.title_words = False, None, ""
        self.terminal.suspend()
        self._take_size()
        typed, row = self.terminal.query_cursor_row()
        self.region = self._new_region()
        self.adopt_cursor_row(row)
        self.dirty = True
        if typed:
            self.input_at = self.clock()
            self.held_input.extend(self.decoder.feed(typed))

    def _attachment_input(self, event: Key | Paste) -> bool:
        """Ctrl+V and a one-line paste (a drop); True when handled."""
        if isinstance(event, Paste):
            if "\n" in event.text or not event.text.strip() or not self.sid:
                return False
            sid, text = self.sid, event.text
            self._intake(  # an image drop stages: as `/image` waits, so does this
                "input.detect_drop",
                {"session_id": sid, "text": text},
                lambda result: self._on_drop(sid, text, result),
                lambda error: self._on_drop_refused(text),
            )
            return True
        if event.name == CHAR and event.ctrl and not event.alt and event.char == "v":
            self._paste("")
            return True
        return False

    def _escape(self, event: Key | Paste) -> bool:
        """Esc: closes the `/` or the `@` menu, cancels a picked agent steer (what was typed stays, a draft like any other),
        cancels a rewind, interrupts a running turn on an empty composer.

        Otherwise it arms a second press within `DOUBLE_ESCAPE_SECONDS`: with
        text, the second clears it into this session's history (a draft is no
        line sent, so it stays out of Hermes' history file); on an empty
        composer between turns, the second opens the rewind picker.
        """
        if not isinstance(event, Key) or event.name != ESCAPE:
            return False
        if self.path_items:
            self.path_items = []
            return True
        if self._menu_entries():
            self.menu_closed = self.composer.text
            return True
        if self.agent_steer is not None:
            self.agent_steer = None
            return True
        if self.rewind is not None:
            self.rewind = None
            self._set_composer("")
            return True
        if self.tell_draft is not None:
            self._leave_tell()  # the deny went as the row was picked; nothing more is sent
            return True
        if not self.composer.text and self._give_back_held():
            return True  # what was held for its paste comes back, unsent
        if not self.composer.text and self._busy():
            self._interrupt()
            return True
        kind = ESCAPE_CLEAR if self.composer.text else ESCAPE_REWIND
        armed, now = self.escape_armed, self.clock()
        if armed is None or armed[0] != kind or now - armed[1] > DOUBLE_ESCAPE_SECONDS:
            self.escape_armed = (kind, now)
            return True
        self.escape_armed = None
        if kind == ESCAPE_CLEAR:
            self.composer.record(self.composer.expanded(), sent=False)  # a chip's text, not its label
            self._set_composer("")
        else:
            self._rewind("")
        return True

    def _exit_said(self) -> bool:
        """Whether a Ctrl+C exits now, which is when the info line says `EXIT_HINT`: an exit armed inside its window,
        no submit held for its paste (Ctrl+C gives that back, or clears the draft, first), and no question, picker,
        agent list or tree open. A steer, rewind or tell names its own keys first, unless the press that armed
        the exit interrupted a turn: then the second press leaves from there too."""
        return (
            self.exit_armed_at is not None and self.clock() - self.exit_armed_at <= EXIT_CONFIRM_SECONDS
            and not self.held_submits and self.slot is None and not self._picker_keys()
            and self.list_selected is None and self.tree_selected is None
            and (self.exit_armed_by_interrupt or (
                self.roster.agents.get(self.agent_steer or "") is None and self.rewind is None
                and self.tell_draft is None
            ))
        )

    def _expire_exit(self) -> None:
        """Forget a first Ctrl+C once the second can no longer exit, so the info line stops naming it."""
        if self.exit_armed_at is not None and self.clock() - self.exit_armed_at > EXIT_CONFIRM_SECONDS:
            self.exit_armed_at = None
            self.dirty = True

    def _expire_escape(self) -> None:
        """Forget a first Esc once the second can no longer come, so the info line stops naming it."""
        if self.escape_armed is not None and self.clock() - self.escape_armed[1] > DOUBLE_ESCAPE_SECONDS:
            self.escape_armed = None
            self.dirty = True

    # ── rewind ──

    def _rewind(self, arg: str) -> None:
        """`/rewind` (and Esc Esc): between turns, list this session's prompts to go back to.

        It has no echo, so what it says during a turn waits under what runs rather than close it.
        """
        if self._busy():
            self.transcript.add_aside(NoticeBlock(REWIND_BUSY_NOTICE, NOTICE_WARN))
        elif not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
        else:
            sid = self.sid
            self._request("session.history", {"session_id": sid}, lambda result: self._open_rewind_picker(sid, result))

    def _open_rewind_picker(self, sid: str, result: dict[str, Any]) -> None:
        if sid != self.sid:
            return
        raw = result.get("messages")
        messages = [message for message in raw if isinstance(message, dict)] if isinstance(raw, list) else []
        rows = rewind_rows({"messages": messages})  # indexed over the very list a cut slices
        if not rows:
            self.transcript.add_notice(REWIND_NONE_NOTICE)
            return
        self.rewind_messages = messages
        self.rewind_picker = RewindPicker(rows)
        self._settle_list()

    def _rewind_picker_key(self, event: Key | Paste | Mouse) -> None:
        """A key for the open rewind picker: the prompt picked comes back into the composer, to edit and send."""
        picker = self.rewind_picker
        if picker is None or isinstance(event, Mouse):
            return
        action = picker.handle_key(event)
        if action is None:
            return
        self.rewind_picker = None
        if action.kind == REWIND_PICK and action.row is not None:
            row = action.row
            before = tuple(self.rewind_messages[: row.index]) if row.index <= len(self.rewind_messages) else ()
            self.rewind = Rewind(row.row_id, row.ordinal, before)
            self._set_composer(row.text)

    # ── Claude Code's commands: /todos, /model, /export ──

    def _todos(self, arg: str) -> None:
        """The whole plan the panel shows a window of, under the echo."""
        text = plan_text(self.hud.payload if self.hud is not None else None)
        if text:
            self._show_output("/todos", text, whole=True)
        else:
            self.transcript.add_notice(TODOS_NONE_NOTICE)

    def _model(self, arg: str) -> None:
        """`/model <name> [--provider <slug>]` switches this session as Hermes' own TUI does (`config.set model`).

        Bare, or with `--refresh` alone, it opens between turns a picker of
        what Hermes offers this session, asked again of the providers for
        `--refresh`. Any other flag (`--global`, `--once`) is Hermes' own
        `/model` as typed, which a shared gateway refuses (`_on_slash_refused`).
        """
        refresh = arg.strip() == MODEL_REFRESH_ARG
        value = typed_switch_value(arg) if arg and not refresh else ""
        if value:
            self._switch_model(value)
        elif arg and not refresh:
            self._route_slash(SlashInvocation("model", arg, None), 0)
        elif self._busy():
            # Bare /model has no echo to say this under, so it waits under what runs rather than close it.
            self.transcript.add_aside(NoticeBlock(MODEL_BUSY_NOTICE, NOTICE_WARN))
        elif not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
        else:
            sid = self.sid
            params: dict[str, Any] = {"session_id": sid, "refresh": True} if refresh else {"session_id": sid}
            self._request("model.options", params, lambda result: self._open_model_picker(sid, result))

    def _switch_model(self, value: str, confirmed: bool = False) -> None:
        """Switch this session to `value` (`gateway_contract.model_switch_value`); the answer says what Hermes did.

        `confirmed`: the person picked "switch anyway" for the guarded target Hermes asked about.
        """
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        sid = self.sid
        params = model_switch_params(value, sid, confirmed)
        self._request("config.set", params, lambda result: self._on_model_switched(sid, value, confirmed, result))

    def _on_model_switched(self, sid: str, value: str, confirmed: bool, result: dict[str, Any]) -> None:
        """A `config.set model` answer: switched, switched at the next turn, or not until the person confirms."""
        if result.get("confirm_required"):
            if confirmed:  # a turn or another switch landed between the ask and the yes
                self.transcript.add_notice(MODEL_CONFIRM_STALE_NOTICE, NOTICE_WARN)
            elif sid == self.sid:
                model = (contract.model_switch_parts(value) or (value, ""))[0]
                current = self.model or "its model"
                self._confirm_model(
                    result, "", model, current, lambda: self._switch_model(value, confirmed=True),
                    lambda: self.transcript.add_notice(MODEL_KEPT_NOTICE.format(current=current)),
                )
            return
        model = as_text(result.get("value")).strip()
        if not model:
            self.transcript.add_notice(MODEL_UNNAMED_NOTICE, NOTICE_WARN)
            return
        if result.get("deferred"):
            self.transcript.add_notice(MODEL_DEFERRED_NOTICE.format(model=model))
            return
        if sid == self.sid:
            self.model = model
            self.dirty = True
        self.transcript.add_notice(MODEL_SWITCHED_NOTICE.format(model=model))
        warning = as_text(result.get("warning")).strip()
        if warning:
            self.transcript.add_notice(warning, NOTICE_WARN)

    def _confirm_model(
        self, result: Mapping[str, Any], intro: str, model: str, current: str,
        switch: Callable[[], None], keep: Callable[[], None],
    ) -> None:
        """Ask in the slot whether to switch to the guarded `model` Hermes named, in Hermes' words; keep is first."""
        message = as_text(result.get("confirm_message")).strip() or "Hermes guards this model."
        keep_choice, switch_choice = MODEL_KEEP_CHOICE.format(current=current), MODEL_SWITCH_CHOICE.format(model=model)

        def decided(choice: str) -> None:
            if choice == switch_choice:
                switch()
            else:
                keep()

        question = MODEL_CONFIRM_QUESTION.format(intro=intro, message=message, model=model)
        self._ask_locally(question, (keep_choice, switch_choice), decided)

    def _ask_locally(self, question: str, choices: tuple[str, ...], decided: Callable[[str], None]) -> None:
        """Ask the person a question of the TUI's own in the prompt slot, with only `choices` to answer it.

        It opens, waits behind an open question and arms like any question
        Hermes asks; `decided` gets the choice picked, or "" for Esc (and for
        a session the person leaves, which declines what is open).
        """
        self.local_serial += 1
        request_id = f"{LOCAL_QUESTION_PREFIX}{self.local_serial}"

        def answered(frame: dict[str, Any]) -> None:
            result = frame.get("result")
            answers = result.get("answers") if isinstance(result, dict) else None
            decided(as_text(answers.get(MODEL_CONFIRM_QID)) if isinstance(answers, dict) else "")

        self.local_questions[request_id] = answered
        params = {"questions": [
            {"qid": MODEL_CONFIRM_QID, "question": question, "choices": list(choices), CLOSED_CHOICES: True},
        ]}
        self._on_server_request(ServerRequest(request_id, "clarify", params))

    # ── Hermes' configured default model ──

    def _read_default(self) -> None:
        """At the launch: the config file's mtime, and Hermes' configured default model, which a move is measured from.

        Hermes sends no event when its config changes, so the mtime
        (`config.get mtime`, which Hermes' own TUI polls) says when to read the
        default again (`_check_default`): a `model.options` that names no
        session, whose `model` and `provider` are then the profile's default.
        Both go at once, so the launch's calls do not wait on each other.
        """
        self.default_asked = True
        self._request("config.get", {"key": "mtime"}, self._seed_mtime, lambda _error: True)
        self._ask_default()

    def _ask_default(self) -> None:
        self._request("model.options", {}, self._take_default, self._default_unread, on_expiry=self._default_unread)

    def _seed_mtime(self, result: dict[str, Any]) -> None:
        self.config_mtime = config_mtime(result)

    def _default_unread(self, _error: object = None) -> bool:
        """A read refused or unanswered: the default stays as last read, and the next turn's end asks again."""
        self.default_asked = False
        self._default_settled()
        return True

    def _default_settled(self) -> None:
        """Nothing is out for the default any more: the prompt held for it (`_start_turn`) goes now.

        Only into the session it was typed in: once another is open, it goes back to the draft instead.
        """
        start, self.starting = self.starting, None
        images, self.starting_images = self.starting_images, ()
        if start is None:
            return
        text, send, sid = start
        if sid != self.sid:
            self._give_back(text, images)
        else:
            send()

    def _start_turn(
        self, text: str, start: Callable[[], None], line: QueuedLine | None = None, images: Sequence[Attachment] = ()
    ) -> None:
        """Start a turn with `start` once Hermes' default model is checked, so the turn runs on the default it has.

        A config edited while no turn ran (another terminal, an editor, a bot)
        would otherwise reach only the turn after this one. The check is the
        turn's end's (`_check_default`): the mtime, then the default and the
        switch only when the mtime moved. A guarded default's question holds
        the prompt until the person answers it, and the prompt then goes on
        the model they chose. Prompts sent meanwhile queue behind it
        (`_send_prompt`). Until the launch's read has answered there is nothing
        to measure a move from, so the first prompt never waits on it. The
        `images` it goes with come back with it if it never goes.

        A prompt already held there is never replaced: one asked to start
        meanwhile goes back to the head of the queue (`line`, the queue's
        line it came from, its images with it) or, with none, to the draft,
        its images tokens again.
        """
        if self.starting is not None:
            if line is not None:
                self.queued.appendleft(line)
            else:
                self._give_back(text, images)
            return
        if self.default_route is None:
            start()
            return
        self.starting = (text, start, self.sid)
        self.starting_images = tuple(images)
        if not self.default_asked:  # one that is out settles into this start
            self._check_default()

    def _take_default(self, result: dict[str, Any]) -> None:
        """The default as Hermes has it now; one that moved since the last read is switched to (`_switch_to_default`).

        The first read is only where later ones are measured from: a
        session that runs another model than the default (one picked with
        /model, or a resumed one) is left on it until the default itself moves.
        """
        self.default_asked = False
        route = (as_text(result.get("model")).strip(), as_text(result.get("provider")).strip())
        before, self.default_route = self.default_route, route
        if before is not None and route != before and route[0]:
            self.default_due = route
            self._switch_to_default()
        if not self.default_asked:
            self._default_settled()

    def _check_default(self) -> None:
        """At a turn's end, whether Hermes' default model moved during it, or the switch to it a turn held back.

        Off when the launch's read did not come back: there is nothing to
        measure a move from. A config file whose mtime did not move (or a
        Hermes that gives none) is not read again.
        """
        if self.default_asked:
            return
        if self.default_route is None:
            self._default_settled()
            return
        if self.default_due is not None:
            self._switch_to_default()
            if not self.default_asked:
                self._default_settled()
            return
        self.default_asked = True
        self._request(
            "config.get", {"key": "mtime"}, self._take_mtime, self._default_unread, on_expiry=self._default_unread
        )

    def _take_mtime(self, result: dict[str, Any]) -> None:
        mtime = config_mtime(result)
        if mtime == self.config_mtime:
            self.default_asked = False
            self._default_settled()
            return
        self.config_mtime = mtime
        self._ask_default()

    def _switch_to_default(self) -> None:
        """Switch the session to the default that moved, the way a /model pick does; never while a turn runs.

        A turn that runs keeps the switch due for its end. A session already
        on that model (a `/model --global` moved both) is left as it is.
        """
        due = self.default_due
        if due is None or self._busy() or not self.sid:
            return
        self.default_due = None
        model, provider = due
        current = self.model
        if model == current:
            return
        facts = {"model": model, "route": f" ({provider})" if provider else "", "current": current or "its model"}
        value = contract.model_switch_value(model, provider)
        if not value:
            self.transcript.add_aside(NoticeBlock(DEFAULT_UNSAFE_NOTICE.format(**facts), NOTICE_WARN))
            return
        self._send_default_switch(due, facts, value)

    def _send_default_switch(self, due: tuple[str, str], facts: dict[str, str], value: str, confirmed: bool = False) -> None:
        sid = self.sid
        self.default_asked = True
        self._request(
            "config.set",
            model_switch_params(value, sid, confirmed),
            lambda result: self._on_default_switched(sid, due, facts, value, confirmed, result),
            lambda error: self._on_default_refused(due, facts, error),
            on_expiry=self._default_unread,
        )

    def _on_default_switched(
        self, sid: str, due: tuple[str, str], facts: dict[str, str], value: str, confirmed: bool, result: dict[str, Any]
    ) -> None:
        """A switch to the moved default, answered: made, made at the next turn, or asked about first (guarded)."""
        self.default_asked = False
        model = as_text(result.get("value")).strip()
        if result.get("confirm_required"):
            if confirmed or sid != self.sid:
                reason = f" {MODEL_CONFIRM_STALE_NOTICE}" if confirmed else ""
                self.transcript.add_aside(NoticeBlock(DEFAULT_KEPT_NOTICE.format(**facts, reason=reason), NOTICE_WARN))
                self._default_settled()
                return

            def keep() -> None:
                self.transcript.add_aside(NoticeBlock(DEFAULT_KEPT_NOTICE.format(**facts, reason=""), NOTICE_WARN))
                self._default_settled()

            intro = f"Hermes' default model is now {facts['model']}{facts['route']}. "
            self._confirm_model(
                result, intro, facts["model"], facts["current"],
                lambda: self._send_default_switch(due, facts, value, confirmed=True), keep,
            )
            return  # a prompt held for the check waits for the answer
        if not model:
            self.transcript.add_aside(NoticeBlock(MODEL_UNNAMED_NOTICE, NOTICE_WARN))
        elif result.get("deferred"):
            self.transcript.add_aside(NoticeBlock(DEFAULT_DEFERRED_NOTICE.format(**facts)))
        else:
            if sid == self.sid:
                self.model = model
                self.dirty = True
            self.transcript.add_aside(NoticeBlock(DEFAULT_SWITCHED_NOTICE.format(**{**facts, "model": model})))
        self._default_settled()

    def _on_default_refused(self, due: tuple[str, str], facts: dict[str, str], error: dict[str, Any]) -> bool:
        """Hermes refused the switch: the session stays where it was, and the notice says why in words.

        A refusal that only says a turn came first (a prompt sent as the last
        one ended) says nothing, and the switch is due again at that turn's end.
        """
        self.default_asked = False
        if refusal_reason(error) in TURN_CAME_FIRST_REASONS:
            self.default_due = due
        else:
            reason = refusal_sentence(error) or plain_sentence(as_text(error.get("message")))
            self.transcript.add_aside(NoticeBlock(DEFAULT_KEPT_NOTICE.format(**facts, reason=f" {reason}"), NOTICE_WARN))
        self._default_settled()
        return True

    def _open_model_picker(self, sid: str, result: dict[str, Any]) -> None:
        if sid != self.sid:
            return
        self.model_picker = ModelPicker(model_rows(result), current=as_text(result.get("model")) or self.model)
        self._settle_list()

    def _model_picker_key(self, event: Key | Paste | Mouse) -> None:
        """A key for the open model picker: the model picked becomes this session's (`_switch_model`), one echo."""
        picker = self.model_picker
        if picker is None or isinstance(event, Mouse):
            return
        action = picker.handle_key(event)
        if action is None:
            return
        self.model_picker = None
        if action.kind == MODEL_PICK and action.row is not None:
            value = action.row.arg
            self._as_command(f"/model {value}", lambda: self._switch_model(value))

    def _export(self, arg: str) -> None:
        """Hermes' /export, once the person has been told it is a profile archive and not the transcript."""
        if not self.export_said:
            self.export_said = True
            self.transcript.add_notice(EXPORT_NOTE)
            return
        self._route_slash(SlashInvocation("export", arg, None), 0)

    def _send_rewind(
        self, text: str, shown: str = "", typed: str = "", notice: str = "", images: Sequence[Attachment] = ()
    ) -> None:
        """Send `text` in place of the picked prompt: Hermes drops it and what came after, and the screen restarts there.

        The transcript is rebuilt from the history above the cut (as a resumed
        session's is drawn), the new prompt goes as `prompt.submit` with
        `truncate_before_row_id` and `confirm_truncate`, and the screen is
        redrawn. Plan mode does not wrap it: a truncation is a `prompt.submit`.
        For a prompt a command sent, `typed` is the command and `notice` what
        it said, under the new row. When a turn started before it went, the
        text (the command, for a command's prompt) goes back after the draft
        and nothing is cut; when Hermes refuses the cut, the screen goes back
        to how it was before the send and nothing comes back to the draft.
        """
        rewind, self.rewind = self.rewind, None
        if rewind is None:
            return
        if self._busy():  # a turn started meanwhile: the row it names may be gone by its end
            self.transcript.add_notice(REWIND_BUSY_NOTICE, NOTICE_WARN)
            self._give_back(typed or text, images)
            return
        kept = self.transcript  # the screen before the cut, put back if Hermes refuses it
        self._restart_transcript(list(rewind.before))
        self._submit_prompt(text, shown, truncate=rewind.row_id, before_cut=kept, notice=notice, typed=typed,
                            images=images)
        self._full_redraw()

    def _restart_transcript(self, messages: list[dict[str, Any]]) -> None:
        """A fresh transcript holding `messages` as a resumed session's history is drawn."""
        cwd = self.transcript.cwd
        self.transcript = Transcript(self.clock)
        self.transcript.cwd = cwd
        self._draw_history(messages)

    def _on_rewind_refused(
        self, sid: str, kept: Transcript, error: dict[str, Any], text: str = "", images: Sequence[Attachment] = ()
    ) -> bool:
        """The rewound prompt did not start a turn: the screen goes back to `kept`, as it was before the send.

        Then it is redrawn from the history Hermes sends; if that read fails,
        or is not answered, the screen from before the send stays, and the
        notices say which. A prompt queued behind the rewind goes only once
        that is settled, so the redraw does not wipe its echo. Hermes still
        holds the images staged for it: they are detached (`_release_staged`). An error whose `data` says `rewound` (the shared-gateway
        child cut the session, then Hermes refused the prompt) is not
        "Hermes kept its history": the notice says the cut happened, and what
        the person typed (`text`: for a skill, the command, not the message it
        expanded to) goes back to the draft as a refused steer's does
        (`_give_back`), after a draft begun since rather than over it, its
        images tokens again.
        """
        if sid != self.sid:
            self._on_submit_error(error)
            return True
        reason = (as_text(error.get("message")) or "refused").strip().rstrip(".")
        data = error.get("data")
        cut = isinstance(data, dict) and data.get("rewound") is True
        self.transcript = kept
        self._full_redraw()
        self._release_staged()
        if cut:
            self._give_back(text, images)  # what the person typed, after any draft begun since: never over it
        self.transcript.add_notice((REWIND_CUT_NOTICE if cut else REWIND_KEPT_NOTICE).format(reason=reason), NOTICE_WARN)
        self.turn_pending = False  # no turn starts; the queue waits for the history read
        after = (REWIND_CUT_NOTICE if cut else REWIND_REFUSED_NOTICE).format(reason=reason)
        self._request(
            "session.history",
            {"session_id": sid},
            lambda result: self._redraw_from_history(sid, result, after),
            lambda history_error: self._history_unread(sid, history_error),
            lambda seconds: self._history_unread(sid, {"message": f"no answer in {seconds:g} s"}),
        )
        return True

    def _redraw_from_history(self, sid: str, result: Mapping[str, Any], notice: str) -> None:
        """The screen redrawn from the history Hermes sent, under `notice` (one without messages changes nothing);
        then the next queued line goes, unless a turn started meanwhile."""
        messages = result.get("messages")
        if sid != self.sid:
            return
        if isinstance(messages, list):
            self._restart_transcript([message for message in messages if isinstance(message, dict)])
            self._full_redraw()
            self.transcript.add_notice(notice, NOTICE_WARN)
        self._drain_unless_busy()

    def _history_unread(self, sid: str, error: Mapping[str, Any]) -> bool:
        """No history to redraw from (`error` says why): the screen stays, says so, and the next queued line goes."""
        if sid == self.sid:
            reason = (as_text(error.get("message")) or "refused").strip().rstrip(".")
            self.transcript.add_notice(REWIND_UNREAD_NOTICE.format(reason=reason), NOTICE_WARN)
            self._drain_unless_busy()
        return True

    def _drain_unless_busy(self) -> None:
        """Send the next queued line now, unless a turn runs: then it goes when that turn ends, as any queued line."""
        if not self._busy():
            self._drain_queue()

    def _interrupt(self) -> None:
        """Ask Hermes to stop the running turn; the working row says `interrupting…` until the turn ends.

        A prompt taken but not sent yet (its images still staging, or waiting
        to) is not sent: it comes back to the draft with its tokens
        (`_give_back_unsent`), and with no turn running or sent besides it,
        nothing is asked of Hermes.
        """
        if self._give_back_unsent() and not (self.transcript.running or self.claim == CLAIM_SUBMITTED):
            self.turn_pending = False
            return
        if self.sid:
            self.interrupting = True
            self._request("session.interrupt", {"session_id": self.sid}, lambda result: None, self._on_interrupt_refused)

    def _on_interrupt_refused(self, error: dict[str, Any]) -> bool:
        """Hermes did not stop the turn: the spinner comes back, and the refusal is said as any refused call is."""
        self.interrupting = False
        return False

    def _interrupt_or_exit(self) -> None:
        """Ctrl+C on empty input: interrupt a running turn, and exit on a second press within 2 s.

        With no turn running and a submit held for its paste, it gives that
        submit back instead, as Esc does, and arms nothing (`_give_back_held`);
        while a turn runs, the interrupt gives it back (`_give_back_unsent`).

        The press that interrupts arms the exit too, so the second one leaves
        whether or not the turn has stopped yet (`interrupting…` can last).
        """
        now = self.clock()
        if not self._busy() and self._give_back_held():
            self.dirty = True  # a submit held for its paste comes back, as Esc gives it; this press arms no exit
            return
        if self._exit_said():  # only while the info line says so
            self.exit_code = 0
            return
        busy = self._busy()
        if busy:
            self._interrupt()
        self.exit_armed_at = now  # the info line says so until the second press can no longer come
        self.exit_armed_by_interrupt = busy
        self.dirty = True

    def _menu_entries(self) -> list[Completion]:
        """Completions while the composer holds a leading `/word` and nothing else, unless Esc closed them over it."""
        text = self.composer.text
        if self.slot is not None or not text.startswith("/") or text == self.menu_closed:
            return []
        command, space, typed = text[1:].partition(" ")
        if space and command.lower() == "theme" and not any(ch.isspace() for ch in typed):
            # `/theme <look>`: the launch looks, by what is typed of one
            return [Completion(f"theme {name}", LAUNCH_SUMMARIES[name]) for name in LAUNCH_PRESETS
                    if name.startswith(typed.lower()) and name != typed.lower()]
        if any(ch.isspace() for ch in text):
            return []
        prefix = text[1:]
        if "/" in prefix:
            return []
        return completions(prefix, self.catalog)

    def _menu_rows(self) -> list[tuple[str, str]]:
        """The open completion menu as `(label, summary)` rows: slash commands, else `@` paths."""
        entries = self._menu_entries()
        if entries:
            return [(f"/{entry.name}", entry.summary) for entry in entries]
        return [(item.display or item.text, item.meta) for item in self.path_items]

    def _menu_moves(self, key: Key) -> bool:
        """Up and Down move the open completion menu's highlight, stopping at either end as every list does."""
        if key.name not in (UP, DOWN):
            return False
        rows = self._menu_rows()
        if not rows:
            return False
        self.menu_index = min(max(self.menu_index + (-1 if key.name == UP else 1), 0), len(rows) - 1)
        return True

    def _menu_enter(self, key: Key) -> bool:
        """Enter on an open completion menu takes the highlighted row, as Tab does, when that changes what is typed.

        Ink's rule (`completionToApplyOnSubmit`): the line is sent instead when
        the row would only add the space after a command typed in full, and
        when the typed word is a command's whole name (an alias included)
        while the highlight is still on the first row. Alt+Enter and
        Shift+Enter add a line, menu or not.
        """
        if key.name != ENTER or key.alt or key.shift or not self._menu_rows():
            return False
        entries = self._menu_entries()
        if entries:
            typed, invocation = self.composer.text[1:], parse_slash(self.composer.text)
            name = entries[min(self.menu_index, len(entries) - 1)].name
            whole = typed.lower() in {entry.name.lower() for entry in entries}  # a name in any case, as it resolves
            whole = whole or (invocation is not None and invocation.command is not None)
            if name.lower() == typed.lower() or (whole and self.menu_index == 0):
                return False
        else:
            word = at_token(self.composer.text, self.composer.caret)[1]
            if not word or self.path_items[min(self.menu_index, len(self.path_items) - 1)].text == word:
                return False
        self._accept_completion()
        return True

    def _accept_completion(self) -> None:
        entries = self._menu_entries()
        if entries:
            self._set_composer(f"/{entries[min(self.menu_index, len(entries) - 1)].name} ")
            return
        start, word = at_token(self.composer.text, self.composer.caret)
        if not self.path_items or not word:
            return
        item = self.path_items[min(self.menu_index, len(self.path_items) - 1)]
        self.composer.replace(start, self.composer.caret, item.text)
        self.path_items = []
        if not item.text.endswith("/"):
            self.path_word = item.text  # an accepted file closes the menu; a folder lists its contents next

    def _track_path_token(self) -> None:
        """Schedule `complete.path` for the `@` token at the caret once it holds still; drop the menu without one."""
        word = at_token(self.composer.text, self.composer.caret)[1] if self._composer_open() else ""
        if word == self.path_word:
            return
        self.path_word = word
        if word:
            self.path_due = self.clock() + PATH_COMPLETE_DEBOUNCE_SECONDS
        else:
            self.path_due = None
            self.path_items = []

    def _ask_path_completion_when_due(self) -> None:
        if self.path_due is None or self.clock() < self.path_due or not self.sid:
            return
        self.path_due = None
        self.path_seq += 1
        seq, word = self.path_seq, self.path_word
        self._request(
            "complete.path",
            {"word": word, "session_id": self.sid},
            lambda result: self._on_path_items(seq, word, result),
            lambda error: True,  # completion is advisory; a failed lookup offers nothing
        )

    def _on_path_items(self, seq: int, word: str, result: dict[str, Any]) -> None:
        if seq != self.path_seq or word != self.path_word:
            return  # the token moved on while this answer was on its way
        self.path_items = path_items(result)
        self.menu_index = 0

    # ── prompts ──

    def _submit(
        self, text: str, shown: str = "", chips: tuple[tuple[str, str], ...] = (), hold: bool = False,
        images: Sequence[Attachment] = (),
    ) -> None:
        """Send what the composer submitted; `shown` is its compact form (paste chips), which the transcript shows.

        `chips` are the chips in `shown` (label, text): a prompt queued behind the turn keeps them for Up. `hold`
        keeps a prompt behind a running turn whatever the busy mode (`_send_prompt`). `images` go with the prompt
        it sends; a line that sends none (a `!` line, a subagent's steer) gives their tokens back (`_keep_images`).

        Whether the line is a `!` shell line or a slash command is read from
        what the composer showed, never from a chip's text: a paste that
        starts with `!` or `/` is a prompt. Chips are expanded only in what is
        sent: a shell line's command, a command's argument. A chip glued to
        the command's name leaves the name as shown.
        """
        if not text.strip():
            return
        seen = shown or text
        if seen.startswith(SHELL_PREFIX):
            self._keep_images(images, SHELL_PREFIX + " line")
            self._shell_line(text, seen)  # a chip holds no `!` of its own, so the sent text starts with it too
            return
        invocation = parse_slash(seen)
        if invocation is not None:
            sent = parse_slash(text)
            if sent is None or sent.name != invocation.name:
                sent = invocation
            # A picked rewind or agent stays picked under a command; a prompt the command sends replaces the rewind's.
            self._run_slash(replace(sent, rewind=self.rewind, images=tuple(images)), echo=f"/{invocation.text}")
        elif self.agent_steer is not None:
            self._keep_images(images, "A subagent's steer")
            self._steer_agent(text)
        elif self.rewind is not None:
            self._send_rewind(text, shown, images=images)
        else:
            self._send_typed(text, hold=hold, shown=shown, chips=chips, images=images)

    def _send_typed(
        self, text: str, hold: bool = False, shown: str = "", chips: tuple[tuple[str, str], ...] = (),
        images: Sequence[Attachment] = (),
    ) -> None:
        """A prompt the person typed and sent: in plan mode as `/plan <text>`, the way a typed `/plan` goes.

        `hold` keeps it behind a running turn whatever the busy mode (`_send_prompt`).
        """
        if self.plan_mode:
            self._run_slash(replace(plan_invocation(text), held=hold, images=tuple(images)))
        else:
            self._send_prompt(text, shown=shown, hold=hold, chips=chips, images=images)

    def _keep_images(self, images: Sequence[Attachment], what: str) -> None:
        """`what` sends no prompt, so it takes no image: the tokens of `images` go back to the draft, and a notice
        says so."""
        if not images:
            return
        labels = " ".join(image.label for image in images)
        self._give_back(labels + " ", images)  # a space after them, as a token goes in
        self.transcript.add_notice(IMAGES_KEPT_NOTICE.format(what=what, labels=labels))

    def _send_prompt(
        self, text: str, shown: str = "", typed: str = "", hold: bool = False, chips: tuple[tuple[str, str], ...] = (),
        notice: str = "", images: Sequence[Attachment] = (),
    ) -> None:
        """Send `text`, or queue it behind the running turn; `typed` is what Up puts back in the composer.

        `hold` queues it behind a running turn whatever the busy mode. `notice` goes under its row (`_submit_prompt`).
        One that starts a turn waits for Hermes' default model to be checked (`_start_turn`), and one sent while
        that wait is on queues behind it. `images` go with it, queued too.
        """
        images = tuple(images)
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            self._keep_images(images, "A prompt with no session")
            return
        if (self._busy() and (hold or self.busy_mode == BUSY_QUEUE)) or self.starting is not None:
            self.queued.append(QueuedLine(text, shown, typed, chips=chips, notice=notice, images=images))
            return
        if self._busy():  # the busy mode sends it into the running turn: no turn starts
            self._submit_prompt(text, shown, notice=notice, images=images)
        else:
            self._start_turn(typed or text, lambda: self._submit_prompt(text, shown, notice=notice, images=images),
                             images=images)

    def _submit_prompt(
        self, text: str, shown: str = "", queued: bool = False, truncate: int | None = None,
        before_cut: Transcript | None = None, notice: str = "", typed: str = "", images: Sequence[Attachment] = (),
    ) -> None:
        """Send one prompt; `queued` says the queue sent it.

        `truncate` names the row a rewind cuts the session before, and
        `before_cut` the transcript from before that cut, which a refusal puts back.
        `notice` is what the skill command that sent it said, under its row whenever it goes. `typed` is
        what the person typed for it (a skill command, not the skill message it expanded to), which a
        rewind refused after its cut gives back.

        `images` are the ones it goes with. Hermes holds no image between
        sends, and takes every image it holds when it admits a turn, which can
        be well after `prompt.submit` (an agent still building) or at once (one
        built). So the prompt waits until no other prompt's images are out and
        no paste, drop or `/image` waits on its answer and detach
        (`_after_claim`); then its images are staged (`image.attach_bytes`),
        nothing else is staged or sent until Hermes has taken them, and it goes
        once each staging is answered. Its echo lists, as `⎿ [Image #N]`, the
        images whose staging Hermes answered. Until it goes it is `unsent`:
        Esc, a session switch or a new gateway gives it back to the draft.
        """
        self._settle_claim()
        self.turn_pending = True  # a prompt sent meanwhile goes behind this one
        self.busy_since = self.clock()
        unsent = UnsentPrompt(typed or text, tuple(images))
        self.unsent.append(unsent)
        self._after_claim(lambda: self._stage_images(
            unsent, lambda taken, paths: self._send_submit(text, shown, queued, truncate, before_cut, notice, typed,
                                                            taken, paths)), sends=True)

    def _send_submit(
        self, text: str, shown: str, queued: bool, truncate: int | None, before_cut: Transcript | None, notice: str,
        typed: str, images: Sequence[Attachment], paths: Sequence[str],
    ) -> None:
        """`prompt.submit`, with `images` staged in Hermes under `paths`; nothing else is staged until Hermes has
        taken them (`_claimed`)."""
        self.transcript.add_user(shown or text, from_queue=queued, known=self.known_slash,
                                 images=tuple(image.label for image in images))
        self.launch_layout = False
        if notice:
            self.transcript.add_aside(NoticeBlock(notice))
        if not queued:
            self.queue_held = False  # the person started a turn: the queue goes on behind it
        self.sticky = shown or text
        self.flushed_since_prompt = 0
        self._clear_roster()  # the agents shown were the last turn's
        self.bg_done = None  # a turn starts: the finished row's offer was for an idle session
        self.turn_pending = True
        self.turn_unknown, self.turn_unknown_count = [], 0
        self.busy_since = self.clock()
        self.turn_waited = 0.0
        self._count_from_here()
        self.staged, self.claim = list(paths), CLAIM_SUBMITTED
        params: dict[str, Any] = {"session_id": self.sid, "text": text}
        if queued:
            params["queued"] = True  # the busy path holds a drained prompt; it never redirects or steers it
        if truncate is not None:
            params.update(truncate_before_row_id=truncate, confirm_truncate=True)  # the person picked this row
            sid, kept = self.sid, before_cut or self.transcript
            self._request(
                "prompt.submit", params, self._on_submitted,
                lambda error: self._on_rewind_refused(sid, kept, error, typed or text, tuple(images)),
            )
            return
        self._request("prompt.submit", params, self._on_submitted, self._on_submit_error)

    def _after_claim(self, run: Callable[[], None], sends: bool = False) -> None:
        """Run `run`, which stages an image (or, `sends`, stages a prompt's images and sends it), now or once nothing
        it could mix with is out (`_pump_claims`), after whatever waits already."""
        self._settle_claim()
        self.after_claim.append((sends, run))
        self._pump_claims()

    def _pump_claims(self) -> None:
        """What waits goes, in order, while no prompt's images are out; a prompt also waits for the `intakes` out."""
        while self.after_claim and self.claim == CLAIM_OPEN:
            sends, run = self.after_claim[0]
            if sends and any(intake.running for intake in self.intakes):
                return
            self.after_claim.popleft()
            run()

    def _intake(
        self, method: str, params: dict[str, Any], on_result: Callable[[dict[str, Any]], None],
        on_error: Callable[[dict[str, Any]], bool],
    ) -> None:
        """A call that has Hermes stage an image (`clipboard.paste`, `image.attach`, `input.detect_drop`): it goes once
        no prompt's images are out, and no prompt goes until it is answered, its answer having sent the detach
        (`_take_attachment`), or until it has none in its time."""

        intake = Intake()
        self.intakes.append(intake)

        def run() -> None:
            intake.running = True

            def done() -> None:
                if intake in self.intakes:
                    self.intakes.remove(intake)
                    self._release_held()
                    self._pump_claims()

            def result(answer: dict[str, Any]) -> None:
                self.intake_answering = intake
                try:
                    on_result(answer)
                finally:
                    self.intake_answering = None
                done()

            def error(refusal: dict[str, Any]) -> bool:
                self.intake_answering = intake
                try:
                    handled = on_error(refusal)
                finally:
                    self.intake_answering = None
                done()
                return handled

            self._request(method, params, result, error, lambda _seconds: done())

        self._after_claim(run)

    def _settle_claim(self) -> None:
        """No turn is awaited any more (the person interrupted one Hermes never admitted, and nothing ended it): what
        was staged for it is detached, so nothing waits on an admission that will not come."""
        if self.claim == CLAIM_SUBMITTED and not self._busy():
            self._release_staged()

    def _claimed(self) -> None:
        """Hermes holds no image any more: the last prompt.submit's turn was admitted (`message.start`), its answer
        says it is queued with its images, it was refused (`_release_staged`), or a cancelled prompt's stagings were
        detached. What waited goes, in order, until a prompt is out again."""
        self.staged, self.claim = [], CLAIM_OPEN
        self._pump_claims()

    def _on_submitted(self, result: dict[str, Any]) -> None:
        """A turn that streams takes its images when Hermes admits it (`message.start`); any other answer (queued
        behind a turn, steered) took them already."""
        if as_text(result.get("status")) != "streaming" and self.claim == CLAIM_SUBMITTED:
            self._claimed()

    def _release_staged(self) -> None:
        """A prompt.submit that ended without Hermes admitting its turn: Hermes keeps what was staged for it, so it is
        detached, by the paths Hermes named. Nothing to do while a prompt is still staging: it is not sent yet."""
        if self.claim == CLAIM_STAGING:
            return
        self._detach(self.staged)
        self._claimed()

    def _detach(self, paths: Sequence[str]) -> None:
        for path in paths:
            self._request("image.detach", {"session_id": self.sid, "path": path}, lambda result: None,
                          self._detach_failed)

    def _stage_images(
        self, unsent: UnsentPrompt, then: Callable[[list[Attachment], list[str]], None]
    ) -> None:
        """Stage each of the prompt's images in Hermes from the bytes the TUI keeps (`image.attach_bytes`);
        `then(taken, paths)` once every one is answered, with the images Hermes took and the paths it named. A
        refusal or no answer is a notice, and that image is not sent. A prompt given back meanwhile sends nothing,
        and what Hermes took for it is detached."""
        if unsent.cancelled:
            return
        self.claim = CLAIM_STAGING
        sid, epoch, answers, images = self.sid, self.image_epoch, {}, unsent.images

        def answered(image: Attachment, path: str) -> None:
            answers[image.label] = path
            if len(answers) < len(images) or epoch != self.image_epoch:
                return  # a new gateway or session: it was given back, and the claim started again (`_reset_staging`)
            taken = [image for image in images if answers[image.label]]
            paths = [answers[image.label] for image in taken]
            if unsent.cancelled or sid != self.sid:
                self._detach(paths)
                self._claimed()
                return
            self.unsent.remove(unsent)
            then(taken, paths)

        if not images:
            self.unsent.remove(unsent)
            then([], [])
            return
        for image in images:
            self._request(
                "image.attach_bytes",
                {"session_id": sid, "filename": image.name,
                 "content_base64": base64.b64encode(image.data).decode("ascii")},
                lambda result, image=image: answered(image, as_text(result.get("path"))),
                lambda error, image=image: self._stage_refused(image, error, answered),
                lambda _seconds, image=image: self._stage_refused(image, {"message": "no answer"}, answered),
            )

    def _stage_refused(
        self, image: Attachment, error: dict[str, Any], answered: Callable[[Attachment, str], None]
    ) -> bool:
        self.transcript.add_notice(IMAGE_NOT_SENT_NOTICE.format(
            label=image.label, reason=(as_text(error.get("message")) or "refused").rstrip(".")), NOTICE_WARN)
        answered(image, "")
        return True

    def _give_back_unsent(self) -> bool:
        """Every prompt taken but not sent goes back to the draft, its images tokens again; True when one did. One
        staging is detached once its answers come (`_stage_images`)."""
        unsent, self.unsent = [prompt for prompt in self.unsent if not prompt.cancelled], []
        for prompt in unsent:
            prompt.cancelled = True
            self._give_back(prompt.text, prompt.images)
        return self._give_back_held() or bool(unsent)

    def _give_back_held(self) -> bool:
        """Every submit held for its pastes goes back to the draft, its images tokens again; True when one did."""
        held, self.held_submits = [submit for submit in self.held_submits if not submit.cancelled], []
        for submit in held:
            submit.cancelled = True
            self._give_back(submit.text, submit.images)
        return bool(held)

    def _hold_submit(self, action: ComposerAction, images: tuple[Attachment, ...], steer: bool) -> bool:
        """A submit made while a paste, drop or `/image` typed before it is still out, or behind one held so, waits
        (`held_submits`): the image each such intake answers joins it, and it goes once they are all answered
        (`_release_held`), as if sent then. True when it was held."""
        out = [intake for intake in self.intakes if intake.held is None]
        if not out and not self.held_submits:
            return False
        held = HeldSubmit(action.text, action.shown, action.chips, images, steer, self.clock())
        for intake in out:
            intake.held = held
        self.held_submits.append(held)
        return True

    def _join_held(self, intake: Intake | None, attachment: Attachment) -> bool:
        """Put `attachment` into the submit held for `intake`, its label after the submit's text; True when one is."""
        held = intake.held if intake is not None else None
        if held is None or held.cancelled or held not in self.held_submits:
            return False
        held.text = with_label(held.text, attachment.label)
        held.shown = with_label(held.shown, attachment.label) if held.shown else ""
        held.images = (*held.images, attachment)
        return True

    def _release_held(self) -> None:
        """Once no intake a held submit waits on is out, the held submits go, in order, as Enter or Ctrl+Enter sends."""
        if any(intake.held is not None and not intake.held.cancelled for intake in self.intakes):
            return
        held, self.held_submits = self.held_submits, []
        for submit in held:
            if submit.cancelled:
                continue
            if submit.steer:
                self._steer_or_submit(submit.text, submit.shown, submit.chips, submit.images)
            else:
                self._submit(submit.text, submit.shown, submit.chips, images=submit.images)

    def _image_wait_line(self, cols: int) -> Line | None:
        """`waiting for the image…`, muted, while a submit is held for a paste, drop or `/image` still out, with how
        long once it is `IMAGE_WAIT_ELAPSED_SECONDS` or more; None otherwise."""
        since = [submit.since for submit in self.held_submits if not submit.cancelled]
        if not since:
            return None
        seconds = self.clock() - min(since)
        text = IMAGE_WAIT_LINE if seconds < IMAGE_WAIT_ELAPSED_SECONDS else f"{IMAGE_WAIT_LINE} {seconds:.0f}s"
        return truncate_line((Span(" " * cell_width(QUEUE_GLYPH)), Span(text, self.theme.muted)), cols)

    def _reset_staging(self, why: str) -> None:
        """A new gateway or session holds no image: a staging answered after this sends nothing (`image_epoch`), what
        waited goes nowhere, and a prompt not sent yet comes back to the draft with a notice."""
        if self._give_back_unsent():
            self.transcript.add_notice(UNSENT_BACK_NOTICE.format(why=why), NOTICE_WARN)
        self.image_epoch += 1
        self.after_claim.clear()
        self.intakes = []
        self.staged, self.claim = [], CLAIM_OPEN

    def _detach_failed(self, error: dict[str, Any]) -> bool:
        self.transcript.add_notice(DETACH_FAILED_NOTICE.format(
            reason=(as_text(error.get("message")) or "refused").rstrip(".")), NOTICE_WARN)
        return True

    def _on_submit_error(self, error: dict[str, Any]) -> bool:
        """A refused prompt.submit: no turn will start, so the next queued prompt goes now, in order. Hermes keeps
        what was staged for it, which `_turn_ended` detaches."""
        self.turn_pending = False
        self._turn_ended()
        return False

    def _turn_ended(self) -> None:
        """The turn is over: the next queued line goes, unless the person interrupted it (`_hold_queue`).

        Then whether Hermes' default model moved (`_check_default`); a queued
        prompt that goes waits for that check before its turn starts (`_start_turn`).
        """
        self.tell_turn_runs = False  # an open tell field now says what to do after this turn, not in it
        self.turns_ended += 1
        # A turn ended before Hermes admitted it (refused, cancelled while the agent built) left what was staged for
        # it: detached. After `message.start` nothing is left (`_claimed` emptied `staged`).
        self._release_staged()
        self.bg_after = self.poller.refresh()  # the background row stamps what still runs now (`_take_background`)
        if self.interrupting:
            self.interrupting = False
            self._hold_queue(INTERRUPTED_WHY)
        else:
            self.sent_now = []  # the turn ended on its own: Hermes passes a steer it held on as the next turn
            self._drain_queue()
        self._check_default()

    def _hold_queue(self, why: str) -> None:
        """A turn ended that the person stopped (or that a gateway restart lost): the queue does not go on by itself,
        as Claude Code's does not after an interrupt. `why` opens the notice.

        With an empty draft (`_draft`, which may be set aside behind a field),
        what Up would take back goes back into it, in order
        (`_take_back_queue`); what is left, a queued `!` line and what
        follows it, or the whole queue when the person typed a draft
        meanwhile, stays queued and held until the next prompt they send
        starts a turn (`_submit_prompt`) or Up takes it back. A notice says
        which.
        """
        self._requeue_unread_steers()
        if not self.queued:
            return
        draft = self._draft()
        if not draft.text:
            self._take_back_queue(draft)
            notice = QUEUE_BACK_NOTICE if draft is self.composer else QUEUE_BACK_HIDDEN_NOTICE
            self.transcript.add_notice(notice.format(why=why))
        if self.queued:
            self.queue_held = True
            self.transcript.add_notice(QUEUE_HELD_NOTICE.format(why=why))

    def _drain_queue(self) -> None:
        """Send the next queued line: a prompt starts the next turn; a `!` line runs, and the one after waits for it.

        Which it is comes from the entry's `shell`, never from its text. A held queue waits (`_hold_queue`), and so
        does one behind a prompt held for the default-model check (`starting`): that prompt starts the next turn.
        """
        if self.queued and self.sid and not self.queue_held and self.starting is None:
            line = self.queued.popleft()
            if line.shell:
                self._run_shell(line.text[len(SHELL_PREFIX) :].strip(), drain_after=True, echo=line.shown)
            else:
                self._start_turn(line.typed or line.text,
                                 lambda: self._submit_prompt(line.text, line.shown, queued=True, notice=line.notice,
                                                             images=line.images), line, line.images)

    # ── `!` shell lines ──

    def _shell_line(self, text: str, shown: str = "") -> None:
        """A `!command` the person sent: run it now, or after the running turn, as a command waits in Claude Code.

        `shown` is the line as the composer showed it (paste chips), which the echo shows.
        """
        command = text[len(SHELL_PREFIX) :].strip()
        echo = SHELL_PREFIX + shown[len(SHELL_PREFIX) :].strip() if shown and shown != text else ""
        if not command:
            self.transcript.add_notice(SHELL_USAGE, NOTICE_WARN)
        elif self._busy():
            self.queued.append(QueuedLine(text, echo, shell=True))
        else:
            self._run_shell(command, echo=echo)

    def _run_shell(self, command: str, drain_after: bool = False, echo: str = "") -> None:
        """`shell.exec` with the command the person typed, echoed as `> !command`; its output lands under the echo.

        `echo` is the line as the composer showed it, when paste chips made it
        differ. `drain_after` sends the next queued line once Hermes answered,
        so a prompt queued behind it does not start a turn under its output.
        """
        echo = echo or f"{SHELL_PREFIX}{command}"

        def run() -> None:
            self._request(
                "shell.exec",
                {"command": command},
                lambda result: self._on_shell_result(echo, result, drain_after),
                lambda error: self._on_shell_refused(echo, error, drain_after),
            )

        self._as_command(echo, run)

    def _on_shell_result(self, echo: str, result: Mapping[str, Any], drain_after: bool) -> None:
        """What it printed (stdout, then stderr), then its exit code when it failed or printed nothing.

        A failure's printed lines are on the red band with its exit line, as a failed tool's output is.
        """
        printed = [text for text in (as_text(result.get("stdout")), as_text(result.get("stderr"))) if text.strip()]
        code = result.get("code")
        code = code if isinstance(code, int) and not isinstance(code, bool) else None
        for text in printed:
            self.transcript.add_output(text.rstrip("\n"), OUTPUT_FAILED if code != 0 else NOTICE_INFO, command=echo)
        if code != 0:
            self.transcript.add_output(f"exit {code if code is not None else '?'}", NOTICE_ERROR, command=echo)
        elif not printed:
            self.transcript.add_output("exit 0", command=echo)
        if drain_after:
            self._drain_queue()

    def _on_shell_refused(self, echo: str, error: Mapping[str, Any], drain_after: bool) -> bool:
        """Hermes' own words: a refusal of a dangerous command (4005) is a warning, a timeout or failure an error."""
        level = NOTICE_WARN if error.get("code") == SHELL_REFUSED else NOTICE_ERROR
        self.transcript.add_output(plain_sentence(as_text(error.get("message"))), level, command=echo)
        if drain_after:
            self._drain_queue()
        return True

    def _recall_queue(self, event: Key | Paste) -> bool:
        """Up on an empty composer takes the queued prompts back into it, one per line, up to a queued `!` line.

        Each comes back as what was typed for it: a prompt a slash command
        built as that command line, a prompt plan mode wrapped as the text
        typed in plan mode. Enter then submits the composer as one text, as it
        submits anything typed: if the text starts with a slash command it
        goes as that command, whose text is everything after the slash, later
        lines included; otherwise it goes as one prompt (in plan mode as
        `/plan <text>`), with a command on any later line as plain text in it.
        A `!` line is never merged with another line, since sent as one text
        the shell would run them all: when it is next in the queue it comes
        back alone, and otherwise the prompts before it come back and it stays
        queued, with everything after it. A line sent again while the turn
        still runs joins the queue at its end.
        The composer decides again what the text it gets back shows, as for
        anything typed. So a prompt that comes back first and was a paste chip
        whose text starts with `!` comes back as it was shown, its chips chips
        again (`Composer.restore`) and the words typed beside them text (one
        chip holding its text where the queue kept no chips), and the
        composer shows a prompt, as it did when it was sent; any other
        prompt whose text starts with `!` (a refused steer's) shows as a `!`
        line, and Enter then runs it as one.
        With nothing queued Up is the composer's: it walks the input history.
        """
        if not isinstance(event, Key) or event.name != UP or self.composer.text or not self.queued:
            return False
        self._take_back_queue(self.composer)
        return True

    def _take_back_queue(self, composer: Composer) -> None:
        """Put the queue's next lines into the empty `composer`, as `_recall_queue` says; the hold ends with the queue."""
        taken = [self.queued.popleft()]
        while self.queued and not taken[0].shell and not self.queued[0].shell:
            taken.append(self.queued.popleft())
        first = taken[0]
        if not first.shell and not first.typed and first.shown and first.text.startswith(SHELL_PREFIX):
            # Its chips again, never a `!` line the composer would run; without them, one chip holding its text.
            if first.chips:
                composer.restore(first.shown, first.chips, _tokens(first.images))
            else:
                composer.handle(Paste(first.text))
            for line in taken[1:]:
                composer.replace(composer.caret, composer.caret, "\n" + (line.typed or line.text), _tokens(line.images))
        else:
            composer.replace(0, len(composer.text), "\n".join(line.typed or line.text for line in taken),
                             _tokens(image for line in taken for image in line.images))
        if not self.queued:
            self.queue_held = False

    # ── steering ──

    def _steer_keys_live(self) -> bool:
        """Whether the send-now key can act now: a turn runs, and no question, picked agent steer or rewind, or tell
        row takes what is sent."""
        return self._busy() and self.slot is None and (
            self.agent_steer is None and self.rewind is None and self.tell_draft is None
        )

    def _queue_head_steers(self) -> bool:
        """Whether the oldest queued line is a prompt the person typed as it is, which the send-now key can steer with.

        A queued `!` line, a prompt a command built (a skill's) and one plan
        mode wrapped (a plan request must not land in a turn that can edit)
        wait for the turn's end, and the lines behind them too, so the queue
        keeps its order: each of those has a `typed` form or is a shell line.
        So does a prompt with images: a steer is text alone.
        """
        head = self.queued[0] if self.queued else None
        return head is not None and not head.shell and not head.typed and not head.images

    def _send_queued_now(self) -> None:
        """The send-now key: the oldest queued prompt leaves the queue and goes into the running turn as a steer.

        A steer Hermes does not take goes back to the head of the queue as
        it was (`_steer_refused`); one it took but had not read when the turn
        stopped goes back there too (`_requeue_unread_steers`).
        """
        line = self.queued.popleft()
        self._steer(line.text, line)

    def _steer_or_submit(
        self, text: str, shown: str = "", chips: tuple[tuple[str, str], ...] = (), images: Sequence[Attachment] = ()
    ) -> None:
        """Ctrl+Enter: steer the running turn with the typed text. Idle, or on a slash command, a `!` line or a line with
        images, it is Enter.

        As for Enter, what the line is comes from what the composer showed (`shown`, paste chips unexpanded).
        """
        seen = shown or text
        if (self._busy() and seen.strip() and parse_slash(seen) is None and not seen.startswith(SHELL_PREFIX)
                and not images):  # a steer is text alone: one with images goes as a prompt
            self._steer(text)
        else:
            self._submit(text, shown, chips, images=images)

    def _steer_command(self, arg: str) -> None:
        """`/steer <text>`: what Ctrl+Enter does, on any terminal. Idle, the text goes as a prompt: in place of the
        picked one when a rewind is picked, as Enter sends it."""
        if not arg:
            self.transcript.add_aside(NoticeBlock(STEER_USAGE, NOTICE_WARN))  # no echo: it must not close what runs
        elif self._busy():
            self._steer(arg)
        elif self.rewind is not None:
            self._send_rewind(arg)
        else:
            self._send_typed(arg)

    def _steer(self, text: str, queued: QueuedLine | None = None) -> None:
        """Send `text` into the running turn. Its only callers pass what the person typed and sent; `queued` is the
        queue's line the send-now key took it from."""
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        sid, turn = self.sid, self.turns_ended  # `turn`: which turn it was meant for, by the turns ended before it
        block = self.transcript.add_steer(text)  # `↪ steer · <text>` under the live blocks, until Hermes answers
        self._request(
            "session.steer",
            {"session_id": sid, "text": text},
            lambda result: self._on_steered(sid, block, result, queued, turn),
            lambda error: self._on_steer_refused(sid, block, error, queued, turn),
            lambda seconds: self._on_steer_unanswered(sid, block, seconds),
            steer=block,
        )

    def _on_steered(
        self, sid: str, block: SteerBlock, result: dict[str, Any], queued: QueuedLine | None = None, turn: int = 0
    ) -> None:
        if sid != self.sid:
            self._steer_back(block.text)
        elif as_text(result.get("status")) == contract.STEER_REJECTED:
            self._steer_refused(block, STEER_REJECTED_REASON, queued, turn)
        else:
            self.transcript.steer_answered(block, STEER_QUEUED)
            if queued is not None:  # Hermes holds it until a tool batch ends (`_track_sent_now`)
                self.sent_now.append(SentNow(queued, block))

    def _on_steer_refused(
        self, sid: str, block: SteerBlock, error: dict[str, Any], queued: QueuedLine | None = None, turn: int = 0
    ) -> bool:
        """Hermes could not steer (an agent still starting, or one that takes no steer): the text is the next prompt."""
        if sid != self.sid:
            self._steer_back(block.text)
            return True
        self._steer_refused(block, as_text(error.get("message")) or "refused", queued, turn)  # Hermes' words
        return True

    def _track_sent_now(self, event_type: str) -> None:
        """Forget a sent-now steer once the turn has read it: at the first tool that finishes after Hermes took it.

        Hermes joins a held steer to the results of the tool batch running
        when it came, when that batch is finalized, and finalizes it even when
        the batch is interrupted (bf0203a794 `_finalize_tool_batch`); it drops
        the steer only when the turn stops with no batch ended after it. A
        model delta before any tool finished says nothing: that request was
        under way before the steer came.
        """
        if event_type == "tool.complete":
            self.sent_now = []

    def _requeue_unread_steers(self) -> None:
        """The turn stopped: a sent-now steer Hermes took but had not read was dropped with it, so its line goes back
        to the head of the queue, in order, its row says so, and a notice names how many."""
        unread, self.sent_now = self.sent_now, []
        for sent in reversed(unread):
            self.queued.appendleft(sent.line)
            self.transcript.steer_answered(sent.block, STEER_REFUSED, SENT_NOW_DROPPED_OUTCOME)
        if unread:
            count = len(unread)
            self.transcript.add_notice(SENT_NOW_DROPPED_NOTICE.format(count=count, s="" if count == 1 else "s"),
                                       NOTICE_WARN)

    def _on_steer_unanswered(self, sid: str, block: SteerBlock, seconds: float) -> None:
        """No answer in the `seconds` the call was waited for: the text comes back to the person and the row leaves.

        Hermes may have taken the steer, so its text is never sent or queued again.
        """
        if sid != self.sid:
            self._steer_back(block.text, STEER_LEFT_UNANSWERED_NOTICE.format(seconds=seconds))
        else:
            self._steer_unanswered(block, seconds)

    def _on_agent_steer_unanswered(self, sid: str, session: str, block: SteerBlock, seconds: float) -> None:
        """An agent steer with no answer in `seconds`: as the main steer's, and if `sid`, the session it went to, was
        left, a notice names the agent and `session`."""
        if sid != self.sid:
            said = AGENT_STEER_LEFT_UNANSWERED_NOTICE.format(name=block.agent, seconds=seconds, session=session)
            self._steer_back(block.text, said)
        else:
            self._steer_unanswered(block, seconds)

    def _steer_unanswered(self, block: SteerBlock, seconds: float) -> None:
        """A steer, the main turn's or an agent's, unanswered in the `seconds` its call was waited for: its row says
        so and its text is given back."""
        self.transcript.steer_answered(block, STEER_REFUSED, STEER_UNANSWERED_OUTCOME.format(seconds=seconds))
        self._give_back(block.text)

    def _steer_refused(self, block: SteerBlock, reason: str, queued: QueuedLine | None = None, turn: int = 0) -> None:
        """The steer says what became of its text (with Hermes' `reason`), which goes as the next prompt.

        While a turn runs it waits in the TUI's queue, whatever the busy mode;
        only an idle session gets it as a prompt at once. A sent-now steer
        (`queued`) goes back to the head of the queue as the line it was, its
        wrapper and chips kept, never wrapped again by the mode now on;
        unless the turn it was meant for (`turn`, the turns ended before it was
        sent) has ended and the next has started, or is held for the
        default-model check (`starting`), a prompt sent after it:
        queued again it would run after that one, so it goes back to the
        composer, with a notice.
        """
        # A prompt held for the default-model check (`starting`) is the next turn already: as good as running.
        later = self._busy() or self.starting is not None
        if queued is not None and turn != self.turns_ended and later:
            self.transcript.steer_answered(
                block, STEER_REFUSED, STEER_REFUSED_OUTCOME.format(fallback=STEER_FALLBACK_COMPOSER, reason=reason)
            )
            self._give_back(queued.text)
            self.transcript.add_notice(SENT_NOW_LATE_NOTICE, NOTICE_WARN)
            return
        if queued is not None:
            self.queued.appendleft(queued)
            fallback = STEER_FALLBACK_HEAD if later or self.queue_held else STEER_FALLBACK_SENT
            self.transcript.steer_answered(block, STEER_REFUSED, STEER_REFUSED_OUTCOME.format(fallback=fallback, reason=reason))
            if not later:
                self._drain_queue()
            return
        fallback = STEER_FALLBACK_QUEUED if self._busy() else STEER_FALLBACK_SENT
        self.transcript.steer_answered(block, STEER_REFUSED, STEER_REFUSED_OUTCOME.format(fallback=fallback, reason=reason))
        self._send_typed(block.text, hold=True)

    def _steer_back(self, text: str, notice: str = STEER_LEFT_NOTICE) -> None:
        """A steer settled after its session was left: the text returns to the person, never to the live session."""
        self._give_back(text)
        self.transcript.add_notice(notice, NOTICE_WARN)

    def _draft(self) -> Composer:
        """The person's draft: the composer, or the one set aside while a question has a composer of its own.

        Text that arrives on its own (a steer given back, a drop's answer, an
        image's remainder, a command's prefill) goes here, never into an
        answer to Hermes.
        """
        if self.tell_draft is not None:
            return self.tell_draft
        return self.slot_draft if self.slot_draft is not None else self.composer

    def _give_back(self, text: str, images: Sequence[Attachment] = ()) -> None:
        """A steer's text back to the person, never into an answer to Hermes: on a line of its own after the draft
        (`_draft`), its `images` tokens again. Its paste chips stay, and so does its caret while the draft is not
        drawn."""
        draft = self._draft()
        caret, end = draft.caret, len(draft.text)
        draft.replace(end, end, f"\n{text}" if draft.text else text, _tokens(images))
        if draft is self.slot_draft or draft is self.tell_draft or self._composer_hidden():
            draft.caret = caret  # a hidden draft comes back as the person left it, the text after its end

    # ── slash commands ──

    def _run_slash(self, invocation: SlashInvocation, depth: int = 0, echo: str = "") -> None:
        """Run a slash command; one the person typed is echoed first, and stays open while its calls are out.

        Everything it says while open (a notice, its output) lands under the
        echo, which is `echo` when paste chips made the line shown differ. A
        command plan mode wrote around a prompt is no command the person ran,
        and an alias's target runs under the alias's echo.
        """
        command = invocation.command
        echoed = command is None or (command.echo and (bool(invocation.arg) or command.echo_bare))
        if depth or invocation.for_plan_mode or not echoed:
            self._route_slash(invocation, depth)
            return
        self._as_command(echo or f"/{invocation.text}", lambda: self._route_slash(invocation, depth))

    def _as_command(self, echo: str, run: Callable[[], None]) -> None:
        """Echo `echo` and run `run` as that command: its calls keep the echo open until they are answered."""
        transcript = self.transcript
        outer = transcript.command
        block = transcript.add_command(echo)
        try:
            run()
        finally:
            transcript.command = outer
        if not any(pending.command is block for pending in self.pending.values()):
            transcript.close_command(block)

    def _route_slash(self, invocation: SlashInvocation, depth: int) -> None:
        command = invocation.command
        if command is not None and command.route == RENAMED:
            self._route_slash(SlashInvocation(command.target, invocation.arg, None, rewind=invocation.rewind,
                                              images=invocation.images), depth)
            return
        if command is not None and command.route in (LOCAL, HERMES, DROPPED) or not self.sid:
            if command is not None and command.route == LOCAL:
                self._local_handlers()[command.name](invocation.arg)
            elif command is not None and command.route == HERMES:
                self.transcript.add_notice(hermes_notice(command))
            elif command is not None and command.route == DROPPED:
                self.transcript.add_notice(dropped_notice(command))
            else:
                self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            self._keep_images(invocation.images, f"/{invocation.name}")  # none of these sends a prompt
        else:
            compressing = invocation.name.lower() in COMPRESS_COMMANDS
            preview = bool(COMPRESS_PREVIEW_FLAGS & {word.lower() for word in invocation.arg.split()})
            if compressing and not preview and not self._busy():
                self.transcript.add_notice(COMPRESS_STARTED_NOTICE)  # under the echo, until Hermes' report
            held = not compressing and self._compression_left() is not None
            if held and self.shared_gateway:  # the stdio entry refuses a turn-back as busy instead
                self.transcript.add_notice(COMPRESSION_HELD_NOTICE.format(name=invocation.name))
            echo = self.transcript.command
            self._request(
                "slash.exec",
                {"command": invocation.text, "session_id": self.sid},
                lambda result: self._on_slash_result(invocation, result, depth),
                lambda error: self._on_slash_refused(invocation, error, depth),
                (lambda seconds: self._compress_unanswered(echo, seconds)) if compressing else None,
                seconds=COMPRESS_ANSWER_SECONDS if compressing else None,
                compressing=compressing and not preview,
            )

    def _compression_left(self) -> float | None:
        """The seconds left on the latest `/compress` this TUI sent and still waits on; None when none is out.

        Hermes' shared gateway serves a connection's calls one at a time and
        runs `/compress` inline, so a call sent meanwhile (a command, its
        `command.dispatch` fallback, a prompt, an interrupt) is answered only
        once the compression ends: it gets this much more, and an answer that
        still comes (/undo's draft, /retry's prompt) is shown rather than
        dropped while Hermes acts on it anyway."""
        ends = [call.expires_at for call in self.pending.values() if call.compressing]
        return float(math.ceil(max(0.0, max(ends) - self.clock()))) if ends else None

    def _compress_unanswered(self, echo: CommandBlock | None, seconds: float) -> None:
        """A `/compress` unanswered in the `seconds` it was waited for (more than `COMPRESS_ANSWER_SECONDS` when it
        was sent behind another one): said under its echo, and nothing is sent again."""
        with self._for_command(echo):
            self.transcript.add_notice(COMPRESS_UNANSWERED_NOTICE.format(seconds=seconds), NOTICE_WARN)

    def _on_slash_refused(self, invocation: SlashInvocation, error: dict[str, Any], depth: int) -> bool:
        """`slash.exec` refusing a command `command.dispatch` owns (4018) falls back to it, as Ink does.

        A shared gateway runs no `/model` through `slash.exec`: one with a flag
        it does not take from a session is refused there, in `/model`'s own words.
        """
        if invocation.name.lower() == "model" and refusal_reason(error) == "unsupported_command":
            self.transcript.add_notice(MODEL_OPTIONS_REFUSED, NOTICE_ERROR)
            self._keep_images(invocation.images, f"/{invocation.name}")
            return True
        data = error.get("data")
        field = data.get("field") if isinstance(data, Mapping) else None
        if refusal_reason(error) == "session_busy" and field == COMPRESSION_FIELD:
            self.transcript.add_notice(COMPRESSION_BUSY_NOTICE.format(name=invocation.name), NOTICE_WARN)
            self._keep_images(invocation.images, f"/{invocation.name}")
            return True
        if error.get("code") != contract.NOT_MINE:
            self._keep_images(invocation.images, f"/{invocation.name}")
            return False
        self._request(
            "command.dispatch",
            {"name": invocation.name, "arg": invocation.arg, "session_id": self.sid},
            lambda result: self._on_dispatch(invocation, result, depth),
        )
        return True

    def _side_answer(self, kind: str, payload: Mapping[str, Any], origin: str = "") -> None:
        """A `/bg` or `/btw` answer, its lines kept and each made safe to show; one for a session other than this one
        (started there before a switch) names that session."""
        self.side_tasks.pop(as_text(payload.get(contract.SIDE_ANSWER_TASK)), None)
        text = "\n".join(clean_text(line) for line in as_text(payload.get(contract.SIDE_ANSWER_TEXT)).splitlines())
        text = text.strip()
        if text:
            line = side_answer_line(kind, payload, text)
            self.transcript.add_aside(NoticeBlock(SIDE_ANSWER_ELSEWHERE.format(session=origin, line=line) if origin
                                                  else line))

    def _topup(self, arg: str) -> None:
        """Hermes' /topup: the balance and the portal link on a shared gateway, where it is a read. Hermes' stdio
        entry runs it in its CLI worker, whose top-up menus are interactive, so there it is Hermes' own terminal's."""
        if self.shared_gateway:
            self._route_slash(SlashInvocation("topup", arg, None), 0)
        else:
            self.transcript.add_notice(hermes_notice(SlashCommand("topup", HERMES, "")))

    def _on_slash_result(self, invocation: SlashInvocation, result: dict[str, Any], depth: int) -> None:
        if result.get("type"):
            self._on_dispatch(invocation, result, depth)
            return
        body = as_text(result.get("output")) or f"/{invocation.name}: no output"
        warning = as_text(result.get("warning"))
        self._show_output(f"/{invocation.text}", f"warning: {warning}\n{body}" if warning else body)
        self._keep_images(invocation.images, f"/{invocation.name}")  # it printed: no prompt took them

    def _on_dispatch(self, invocation: SlashInvocation, result: dict[str, Any], depth: int) -> None:
        """What `command.dispatch` (or `slash.exec`) made of a command: the prompt it sends takes the invocation's
        images; any other outcome gives their tokens back (`_keep_images`)."""
        kind = as_text(result.get("type"))
        if kind in ("exec", "plugin"):
            self._show_output(f"/{invocation.text}", as_text(result.get("output")) or "(no output)")
            self._keep_images(invocation.images, f"/{invocation.name}")
            task = as_text(result.get(contract.SIDE_ANSWER_TASK))
            if task and self.sid:
                self.side_tasks[task] = self.sid
            child = as_text(result.get(BRANCHED_SESSION))
            if child and self.sid:  # /branch made a new session: the TUI goes there, as Ink does
                self._switch_session(child, BRANCHED_NOTICE.format(parent=self.stored_id))
            return
        if kind == "alias":
            target = as_text(result.get("target")).lstrip("/")
            aliased = parse_slash(f"/{target} {invocation.arg}") if target and depth == 0 else None
            if aliased is not None:
                self._run_slash(replace(aliased, rewind=invocation.rewind, images=invocation.images), depth + 1)
            else:
                self.transcript.add_notice(f"/{invocation.name}: the alias did not resolve.", NOTICE_WARN)
                self._keep_images(invocation.images, f"/{invocation.name}")
            return
        notice = as_text(result.get("notice")).strip()
        message = as_text(result.get("message"))
        display = as_text(result.get("display")).strip()
        sends = kind in ("send", "skill") and bool(message.strip())
        shows_command = kind == "skill" or bool(display)  # a built-in's bare send (/plan, /retry) shows what it sends
        echo = self.transcript.withdraw_command() if sends and shows_command and self.sid else None
        rewinds = sends and invocation.rewind is not None and invocation.rewind is self.rewind  # the pick it went with
        if invocation.name.lower() in TURN_BACK_COMMANDS:  # Hermes lowercases a name before it routes it: /Retry too
            # An answer means Hermes' /retry or /undo took the last turn(s) back already, so a pick (the one it went
            # with, or one made while it was out) or an open picker names the session as it was before: both go, and
            # what it answers goes plain (/retry's prompt, /undo's draft), as without a rewind.
            if self.rewind is not None or self.rewind_picker is not None:
                self.transcript.add_notice(REWIND_TURN_BACK_NOTICE.format(name=invocation.name))
            rewinds, self.rewind, self.rewind_picker = False, None, None
        if echo is not None or rewinds:
            # One row for the skill the person ran: the prompt's, with Hermes' `display` for it (`/name arg`) or else
            # the echo's text, never the skill body sent; the dispatch's notice goes under it. The prompt is then the
            # person's, as a typed one is: its call is not the echo's. Sent with a rewind picked, it goes in place
            # of the picked prompt, as a typed one then does, and the screen restarts at the cut with it.
            with self._for_command(None):
                shown = display or (echo.command if echo is not None else invocation.shown)
                if rewinds:
                    self._send_rewind(message, shown, typed=invocation.typed, notice=notice, images=invocation.images)
                else:
                    self._send_prompt(message, shown, typed=invocation.typed, hold=invocation.held, notice=notice,
                                      images=invocation.images)
            return
        if notice:
            self.transcript.add_notice(notice)
        if sends:
            shown = display or invocation.shown
            self._send_prompt(message, shown, typed=invocation.typed, hold=invocation.held, images=invocation.images)
            return
        if kind in ("send", "skill"):
            self.transcript.add_notice(f"/{invocation.name}: empty message", NOTICE_WARN)
        elif kind == "prefill":
            if message:
                draft = self._draft()
                draft.replace(0, len(draft.text), message)
        else:
            other = as_text(result.get("output")) or as_text(result.get("display"))
            if other:
                self._show_output(f"/{invocation.text}", other)
        self._keep_images(invocation.images, f"/{invocation.name}")  # after a prefill, so it keeps them

    def _show_output(self, command: str, text: str, whole: bool = False) -> None:
        """A command's output, in the transcript under its echo (`command` repeats the echo once it has closed).

        However long it is: a long one shows its first rows and a count of the
        rest, which /history shows, unless `whole`. The pager opens only when
        the person asks for one, so output answered while a view has the
        alternate screen waits in the transcript until they leave it.
        """
        self.transcript.add_output(text, command=command, whole=whole)

    def _local_handlers(self) -> dict[str, Callable[[str], None]]:
        return {
            "help": self._help,
            "keys": self._keys,
            "quit": self._quit,
            "new": self._new_session,
            "redraw": self._redraw,
            "history": self._history,
            "rewind": self._rewind,
            "todos": self._todos,
            "model": self._model,
            "export": self._export,
            "details": self._details,
            "queue": self._show_queue,
            "steer": self._steer_command,
            "effort": self._effort_command,
            "logs": self._logs,
            "dag": self._dag,
            "bots": self._bots,
            "copy": self._copy,
            "theme": self._theme,
            "glow": self._glow,
            "omh-model": self._omh_model,
            "reload-skills": self._reload_skills,
            "topup": self._topup,
            "sessions": self._sessions,
            "image": self._image,
            "paste": self._paste,
        }

    def _help(self, arg: str) -> None:
        """The TUI's commands, Hermes' by category, how many skill commands there are and, in Hermes' words, which
        skills a built-in command's name takes; paged when long."""
        local = [command for command in COMMANDS if command.route in (LOCAL, RENAMED)]
        width = max(len(command.name) for command in local)
        rows = ["OMH TUI commands:"]
        rows += [f"/{command.name:<{width}} {command.summary}" for command in local]
        if self.catalog_categories:
            rows.append("Hermes commands:")
            rows += [f"  {category}: {' '.join(names)}" for category, names in self.catalog_categories]
        else:
            rows.append("Hermes commands: none listed.")
        rows.append(CLASSIC_HELP.format(names=" ".join(f"/{c.name}" for c in COMMANDS if c.route == CLASSIC)))
        if self.skill_count:
            rows.append(SKILL_COMMANDS_NOTE.format(count=self.skill_count))
        if self.catalog_collisions:
            rows.append(COLLISION_NOTES_HEADING)
            rows += [f"  {note}" for note in self.catalog_collisions]
        rows.append(YOLO_NOTE)
        rows.append(HELP_KEYS)
        rows.append(BARE_HERMES_NOTE)
        self._show_output("/help", "\n".join(rows), whole=True)

    def _reload_skills(self, arg: str) -> None:
        """Hermes re-scans its skills for this session, then the catalog is read again, as Ink's /reload-skills does.

        Runs here rather than through `slash.exec`: Hermes runs those in a
        separate per-session worker process, and only the gateway's own
        `skills.reload` clears the skill commands `command.dispatch` reads.
        """
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        self._request("skills.reload", {"session_id": self.sid}, self._on_skills_reloaded, self._on_reload_refused)

    def _on_skills_reloaded(self, result: dict[str, Any]) -> None:
        self._show_output("/reload-skills", as_text(result.get("output")) or "Skills reloaded.")
        self._refresh_catalog()

    def _on_reload_refused(self, error: dict[str, Any]) -> bool:
        """A refused rescan, drift included (`contract.OPTIONAL_METHODS`): a notice, and the session goes on."""
        message = as_text(error.get("message")) or "refused"
        self.transcript.add_notice(RELOAD_REFUSED_NOTICE.format(code=error.get("code"), message=message), NOTICE_WARN)
        return True

    def _guide_key(self, event: Key | Paste) -> bool:
        """`?` on an empty composer opens the key list; with anything typed it is a character."""
        plain = isinstance(event, Key) and event.name == CHAR and not event.ctrl and not event.alt
        if not plain or event.char != GUIDE_KEY or self.composer.text:
            return False
        self._keys("")
        return True

    def _keys(self, arg: str) -> None:
        """The key list on the alternate screen; q or Esc leaves, as in every pager."""
        self._open_pager("keys", shortcut_lines(self.screen[0], self.theme))

    def _quit(self, arg: str) -> None:
        """Close the session first, so Hermes ends its runtime before the gateway reads end of input."""
        if self.sid:
            self._turn_off_yolo_set_here(self.sid)
            self._request("session.close", {"session_id": self.sid}, lambda result: None, lambda error: True)
        self.exit_code = 0

    def _new_session(self, arg: str) -> None:
        """Create the new session first; the current one closes only once that worked."""
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        self._request("session.create", self._create_params(), self._on_new_session, self._on_create_refused)

    def _on_new_session(self, result: dict[str, Any]) -> None:
        declined = self._enter_session(result)
        self.banner_record = self._banner_record(result, resumed="")  # a later full redraw names this session
        self.transcript.add_notice(f"New session {self.stored_id}.")
        self._notice_declined(declined)
        self._refresh_catalog()

    def _on_create_refused(self, error: dict[str, Any]) -> bool:
        message = as_text(error.get("message")) or "refused"
        self.transcript.add_notice(
            f"Could not start a new session ({error.get('code')}): {message}. Still in {self.stored_id}.", NOTICE_WARN
        )
        return True

    def _enter_session(self, result: Mapping[str, Any], fallback_stored: str = "") -> int:
        """Leave the current session for the one `result` opened; how many of its requests were declined.

        The old session's open requests are declined, yolo the TUI set there
        is turned off, and its runtime closed; everything that belonged to it
        (transcript, queue, sticky prompt, attachments, HUD snapshot,
        subagents) is dropped before the new one is adopted.
        The caller says so in the new transcript, after its own notice.
        """
        old = self.sid
        self.in_launch_session = False
        self.card_state = CARD_NONE
        declined = self._decline_all_requests()
        leaving = bool(old) and old != as_text(result.get("session_id"))
        left = sorted(task for task, sid in self.side_tasks.items() if leaving and sid == old)
        if leaving:
            self._turn_off_yolo_set_here(old)
            self._request("session.close", {"session_id": old}, lambda result: None, lambda error: True)
        self.transcript = Transcript(self.clock, under_output=self.transcript.taken_any)
        if left:
            self.transcript.add_notice(SIDE_ANSWERS_LEFT_NOTICE.format(tasks=", ".join(left), session=old), NOTICE_WARN)
            for task in left:
                del self.side_tasks[task]
        self.queued.clear()
        self.sticky = ""
        self.flushed_since_prompt = 0  # rows printed above the region from the last prompt's first row on
        # Hermes held nothing of a draft's or the queue's images; what it staged for a prompt went with that session.
        self._reset_staging(UNSENT_BACK_SWITCH)
        self.hud = None
        self.goal = None
        self.retired_plan, self.plan_seen_open = "", False
        self._clear_roster()
        self.tree_folds, self.tree_run = {}, ""  # a run of the same name in the next session starts unfolded
        self.retired_run = None  # a run of the same name in the next session is drawn
        self.tree_freed = 0
        self._adopt_session(result, fallback_stored)
        return declined

    def _notice_declined(self, declined: int) -> None:
        if declined:
            noun = "request" if declined == 1 else "requests"
            self.transcript.add_notice(f"Declined {declined} open {noun} from the session you left.", NOTICE_WARN)

    # ── switching sessions ──

    def _sessions(self, arg: str) -> None:
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
        elif arg:
            self._switch_session(arg, by_title=True)
        else:
            self._request("session.list", {"limit": SESSION_LIST_LIMIT}, self._open_session_picker)

    def _open_session_picker(self, result: dict[str, Any]) -> None:
        rows = session_rows(result)
        if rows:
            self.picker = SessionPicker(rows, current=self.stored_id)
            self._settle_list()
        else:  # bare /sessions has no echo: during a turn this waits under what runs
            self.transcript.add_aside(NoticeBlock("Hermes has no stored sessions to switch to."))

    def _picker_key(self, event: Key | Paste) -> None:
        if self.picker is None:
            return
        action = self.picker.handle_key(event)
        if action is None:
            return
        self.picker = None
        if action.kind == PICK:
            self._switch_session(action.session_id)

    def _switch_session(self, target: str, notice: str = "", by_title: bool = False) -> None:
        """Resume `target` (a stored id or an exact title); the current session closes once that worked, and `notice`
        is said on the redrawn screen. `by_title`: the person typed `target`, so a refusal may be a title the gateway
        does not resolve (`_on_resume_refused`)."""
        if target == self.stored_id:
            self.transcript.add_notice(f"Already in session {target}.")
            return
        self._request(
            "session.resume",
            {"session_id": target, "cols": self.size[0]},
            lambda result: self._on_session_resumed(target, result, notice),
            lambda error: self._on_resume_refused(target, error, notice, by_title),
        )

    def _on_session_resumed(self, target: str, result: dict[str, Any], notice: str = "") -> None:
        """Leave the old session and redraw the screen as the resumed one.

        Hermes resolves a title or a compressed ancestor to the session
        already live and answers with that session's id. That is no switch:
        nothing is left, declined or reset, so the yolo the TUI set there is
        still the TUI's to turn off.
        """
        if as_text(result.get("session_id")) == self.sid:
            self.transcript.add_notice(f"Already in session {self.stored_id}.")
            return
        declined = self._enter_session(result, fallback_stored=target)
        self._draw_history(result.get("messages"))
        self._notice_declined(declined)
        self.banner_record = self._banner_record(result, resumed=self.stored_id)
        self._full_redraw()
        if notice:
            self.transcript.add_notice(notice)
        self._redeliver(result.get("open_requests"))
        self._refresh_catalog()  # its workspace may hold project-local skills the last one did not

    def _on_resume_refused(self, target: str, error: dict[str, Any], notice: str = "", by_title: bool = False) -> bool:
        """Say the refusal, and stay. A typed target the owner refused (`RESUME_REFUSED`) is looked up as a title
        first (`_resume_looked_up`): Hermes' shared gateway resumes ids only, where its stdio entry also took an exact
        title."""
        if by_title and error.get("code") == RESUME_REFUSED:
            self._request(
                "session.list", {"title": target},
                lambda result: self._resume_looked_up(target, error, result, notice),
                lambda _lookup: self._scan_titles(target, error, notice),
            )
            return True
        message = as_text(error.get("message")) or "refused"
        self.transcript.add_notice(
            f"Could not switch to {target} ({error.get('code')}): {message}. Still in {self.stored_id}.", NOTICE_WARN
        )
        return True

    def _resume_looked_up(self, target: str, error: dict[str, Any], result: dict[str, Any], notice: str) -> None:
        """The owner's exact-title lookup (`session.list` `title`, over its whole store), after it refused `target`
        as an id.

        The session that has `target` as its id was refused as itself, so the
        refusal is said. One session titled exactly `target` (or whose lineage
        is, `root_title`) is resumed by the id it answers with. Anything else,
        a gateway that ignored `title` and listed as usual included, goes to
        the listing's scan (`_scan_titles`).
        """
        rows = [row for row in result.get("sessions") or [] if isinstance(row, dict)]
        if any(target in (row.get("id"), row.get("resolved_id")) for row in rows):
            self._on_resume_refused(target, error)
            return
        titled = [row for row in rows if target in (row.get("title"), row.get("root_title"))]
        found = as_text(titled[0].get("resolved_id")) or as_text(titled[0].get("id")) if len(titled) == 1 else ""
        if found:
            self._switch_session(found, notice)
        else:
            self._scan_titles(target, error, notice)

    def _scan_titles(self, target: str, error: dict[str, Any], notice: str) -> None:
        """Look `target` up among the listed sessions (`_resume_titled`); a listing that fails says the refusal."""
        self._request(
            "session.list", {"limit": SESSION_LIST_LIMIT},
            lambda result: self._resume_titled(target, error, result, notice),
            lambda _listing: self._on_resume_refused(target, error),
        )

    def _resume_titled(self, title: str, error: dict[str, Any], result: dict[str, Any], notice: str) -> None:
        """`title` against the listed sessions, after the owner refused it as an id and found no one session with it.

        A listed session with that id was refused as itself, so the refusal
        is said. Otherwise the one session titled `title` is resumed by its
        id, matching case first and then ignoring it. Several with that title
        (they differ only in case: Hermes refuses an exact duplicate), or none,
        open the picker filtered by `title` and say how many matched; with no
        session listed at all, or none matching a target shaped as a session id
        (`SESSION_ID_SHAPE`), the refusal is said.
        """
        rows = session_rows(result)
        if not rows or any(row.id == title for row in rows):
            self._on_resume_refused(title, error)
            return
        matched = [row for row in rows if row.title == title] or [
            row for row in rows if row.title.casefold() == title.casefold()
        ]
        if len(matched) == 1:
            self._switch_session(matched[0].id, notice)
            return
        if not matched and SESSION_ID_SHAPE.fullmatch(title):
            self._on_resume_refused(title, error)
            return
        said = TITLE_SHARED_NOTICE if matched else TITLE_UNKNOWN_NOTICE
        self.transcript.add_notice(said.format(count=len(matched), title=title), NOTICE_WARN)
        self.picker = SessionPicker(rows, current=self.stored_id, query=title)
        self._settle_list()

    # ── attachments ──

    def _image(self, arg: str) -> None:
        if not arg:
            self.transcript.add_notice("Usage: /image <path to an image file>", NOTICE_WARN)
        elif not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
        else:
            sid = self.sid
            self._intake(
                "image.attach",
                {"session_id": sid, "path": arg},
                lambda result: self._on_image_attached(sid, result),
                lambda error: self._attach_failed("/image", error),
            )

    def _paste(self, arg: str) -> None:
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        sid = self.sid
        self._intake(
            "clipboard.paste",
            {"session_id": sid},
            lambda result: self._on_clipboard_pasted(sid, result),
            lambda error: self._attach_failed("/paste", error),
        )

    def _take_attachment(self, sid: str, attachment: Attachment) -> None:
        """An image Hermes staged for `sid` becomes the TUI's: its bytes are read from the path Hermes named, Hermes
        is told to let go of it (`image.detach`, by that path), and an `[Image #N]` token for it goes at the draft's
        caret, or, when the person sent while it was out, into that held submit (`_join_held`); for a session since
        left, or bytes the TUI cannot read, a notice instead."""
        data = read_image(attachment.path)
        self._request("image.detach", {"session_id": sid, "path": attachment.path}, lambda result: None,
                      self._detach_failed)
        if sid != self.sid:
            self.transcript.add_notice(ATTACH_LEFT_NOTICE.format(name=attachment.name), NOTICE_WARN)
            return
        if data is None:
            self.transcript.add_notice(IMAGE_UNREADABLE_NOTICE.format(name=attachment.name), NOTICE_WARN)
            return
        self.image_count += 1
        attachment = replace(attachment, label=IMAGE_LABEL.format(number=self.image_count), data=data)
        if not self._join_held(self.intake_answering, attachment):
            self._draft().insert_image(attachment.label, attachment)

    def _on_image_attached(self, sid: str, result: dict[str, Any]) -> None:
        attachment = attachment_from(result) if result.get("attached") is True else None
        if attachment is None:
            self.transcript.add_notice("/image: Hermes did not attach the file.", NOTICE_WARN)
            return
        self._take_attachment(sid, attachment)
        remainder = as_text(result.get("remainder")).strip()
        if remainder:  # `/image shot.png what is this?` keeps the question for the person to send
            self._draft().handle(Paste(remainder))

    def _on_clipboard_pasted(self, sid: str, result: dict[str, Any]) -> None:
        attachment = attachment_from(result) if result.get("attached") is True else None
        if attachment is None:
            self.transcript.add_notice(as_text(result.get("message")) or "No image found in the clipboard.")
        else:
            self._take_attachment(sid, attachment)

    def _attach_failed(self, command: str, error: dict[str, Any]) -> bool:
        message = as_text(error.get("message")) or "not attached"
        self.transcript.add_notice(f"{command}: {message} ({error.get('code')}).", NOTICE_WARN)
        return True

    def _on_drop(self, sid: str, text: str, result: dict[str, Any]) -> None:
        """An image drop is a token (`_take_attachment`), nothing typed; a file drop types its reference; else the paste.

        Text goes to the draft (`_draft`) whichever session is live: it is the
        person's paste, sent nowhere yet; or into the submit the person made
        while it was out (`_paste_back`). An image Hermes queued for a session
        since left is a notice (`_take_attachment`).
        """
        if result.get("matched") is True and result.get("is_image") is True:
            attachment = attachment_from(result)
            if attachment is not None:
                self._take_attachment(sid, attachment)
            return
        if result.get("matched") is True and as_text(result.get("text")):
            text = as_text(result.get("text"))
        self._paste_back(text)

    def _on_drop_refused(self, text: str) -> bool:
        self._paste_back(text)
        return True

    def _paste_back(self, text: str) -> None:
        """A one-line paste that was no image goes where it was typed: into the submit held for it when the person
        sent before it was answered (`_join_held`), else into the draft."""
        held = self.intake_answering.held if self.intake_answering is not None else None
        if held is not None and not held.cancelled and held in self.held_submits:
            held.text += text
            held.shown = held.shown + text if held.shown else ""
            return
        self._draft().handle(Paste(text))

    def _redraw(self, arg: str) -> None:
        self._full_redraw()

    def _history(self, arg: str) -> None:
        """The blocks held now in a pager that renders each one, details shown, only when a page reaches it."""
        transcript = self.transcript
        blocks, dropped = list(transcript.blocks), transcript.dropped  # what the pager holds, as it opens

        def rows(index: int, width: int, theme: Theme) -> list[Line]:
            shown = block_rows(blocks[index], width, theme, expanded=True)
            return [*transcript.dropped_rows(width, theme, dropped), *shown] if index == 0 else shown

        pager = HistoryPager("history", count=len(blocks), render=rows)
        # Stops at the first block with rows, the first one but for a reply that was only a line break, and
        # keeps what it rendered for the first frame.
        if pager.shows_nothing(self.screen[0], self.theme):
            transcript.add_notice("Nothing in this session's transcript yet.")
            return
        self._show_pager(pager)

    def _details_view(self) -> None:
        """The whole transcript with every detail (thinking, tool output, whole diffs) in the pager, at its end."""
        self._history("")
        if isinstance(self.pager, HistoryPager):
            self.pager.handle_key(Key(END), self.screen[1])

    def _question_view(self) -> None:
        """The open question in the pager, every row of it (a long command whole); q or Esc goes back to it as it
        was, with nothing answered, and the pager closes with the question (`_close_slot`)."""
        if self.slot is not None:
            lines = self.slot.whole_lines(self.screen[0], self.theme, len(self.waiting_requests))
            self._show_pager(Pager(QUESTION_VIEW_TITLE, lines))
            self.question_view = self.pager

    def _details(self, arg: str) -> None:
        # No notice: its echo is held under a live block (`Transcript.add_command`), the only block the toggle changes.
        self.transcript.toggle_details()

    def _show_queue(self, arg: str) -> None:
        if not self.queued:
            self.transcript.add_notice("Nothing is queued.")
            return
        rows = ["Queued (sent one at a time as each turn ends):"]
        rows += [f"{number}. {line.shown or line.text}" for number, line in enumerate(self.queued, start=1)]
        self.transcript.add_notice("\n".join(rows))

    def _logs(self, arg: str) -> None:
        tail = self.client.stderr_tail()
        if tail:
            self._open_pager("gateway stderr (memory only)", [(Span(line),) for line in tail])
        else:  # /logs has no echo: during a turn this waits under what runs
            self.transcript.add_aside(NoticeBlock("The gateway has written nothing to stderr."))

    def _dag(self, arg: str) -> None:
        """The session's delegation graph as boxes in the pager (`DagPager`), drawn from the HUD's newest read at
        every frame; it sends nothing anywhere."""
        if dag_page_lines(self.hud.payload if self.hud is not None else None, self.screen[0], self.theme) is None:
            # /dag has no echo: during a turn this waits under what runs
            self.transcript.add_aside(NoticeBlock("No delegation graph: this session has no recent delegated work."))
            return
        self._show_pager(DagPager(
            "delegation graph", payload=lambda: self.hud.payload if self.hud is not None else None,
            read_at=lambda: self.hud.received_at if self.hud is not None else None, depth=self.color_depth,
            clock=self.wall_clock,  # the HUD poller stamps its reads with the wall clock
            aura=self._aura_phase,
        ))

    def _bots(self, arg: str) -> None:
        """This machine's Hermes profiles, their gateways and sessions, read-only, in the pager (`BotBoard`).

        What it shows is read by a `BoardReader` thread for as long as the
        board is open; nothing it does is sent anywhere.
        """
        from .bot_board import BoardReader, BotBoard  # on demand: a session that never opens the board never loads it

        if self.board_reader is None:
            self.board_reader = (self.make_board_reader or BoardReader)(self.environ, clock=self.wall_clock)
        reader = self.board_reader
        self._show_pager(BotBoard("bots", show=reader.show, refresh=reader.refresh, clock=self.wall_clock))
        reader.start(self._wake_loop)

    def _take_board(self) -> None:
        reader = self.board_reader
        snapshot = reader.take() if reader is not None else None
        if snapshot is None:
            return
        from .bot_board import BotBoard  # loaded once `_bots` made the reader

        if isinstance(self.pager, BotBoard):
            self.pager.take(snapshot)
            self.dirty = True

    def _stop_board_reader(self) -> None:
        if self.board_reader is not None:
            self.board_reader.stop()

    def _copy(self, arg: str) -> None:
        last = next((block for block in reversed(self.transcript.blocks) if isinstance(block, AssistantBlock)), None)
        if last is None or not last.text.strip():
            self.transcript.add_notice("No reply to copy yet.")
            return
        # "replace", as `Terminal.write` encodes: a lone surrogate (JSON can carry one) is copied as the "?" the
        # screen shows, not as bytes that are no UTF-8 for the terminal to put on the clipboard.
        encoded = base64.b64encode(last.text.strip().encode("utf-8", "replace")).decode("ascii")
        self.terminal.write(OSC52_COPY.format(encoded))
        self.transcript.add_notice("Copied the last reply to the clipboard (OSC 52; the terminal must allow it).")

    def _pager_mouse(self, event: Mouse) -> None:
        """A report while the pager is open: the pager scrolls or selects, and what a drag or a double or triple click
        picked goes to the clipboard, its footer saying what happened (`_copy_selection`)."""
        pager = self.pager
        if pager is None:
            return
        text = pager.handle_mouse(event, self.screen[1], self.clock())
        self.dirty = True
        if text:
            pager.note = self._copy_selection(text)
            self.copy_noted_at = self.clock()

    def _copy_selection(self, text: str) -> Line:
        """Put `text` on the clipboard by `copy_route`, and the row that says so: copied when OSC 52 went to a terminal
        that honours it or `pbcopy` succeeded, sent otherwise (OSC 52 is never answered, so nothing confirms it)."""
        route = copy_route(self.environ, self.platform, self.tmux_over_ssh)
        if route == COPY_PBCOPY and self.pbcopy(text):
            confirmed = True
        else:
            # "replace", as `_copy` encodes: a lone surrogate is copied as the "?" the screen shows.
            self.terminal.write(OSC52_COPY.format(base64.b64encode(text.encode("utf-8", "replace")).decode("ascii")))
            confirmed = route == COPY_OSC52
        if confirmed:
            note = Notification(COPIED_NOTE.format(count=len(text)), "success", "")
        else:
            why = OSC52_IN_TMUX if self.environ.get("TMUX") else OSC52_UNCONFIRMED
            note = Notification(COPY_SENT_NOTE.format(why=why), "warn", "")
        return note.line(self.size[0], self.theme)

    def _theme(self, arg: str) -> None:
        """`/theme <name>` picks a palette, `/theme auto|light|dark` the background it is measured against; alone, both.

        Either redraws the screen, so the rows above are repainted in it.
        """
        choice = arg.strip().lower()
        if not choice:
            self.launch_picker = LaunchPicker(self.launch_look)
            self.dirty = True
            return
        if choice in LAUNCH_PRESETS:
            self._keep_launch_look(choice)
            return
        if choice in BACKGROUND_MODES:
            self.background_mode = choice
        elif theme_for_name(arg) or theme_for_skin_name(arg):
            self.theme = theme_named(arg)
        else:
            self.transcript.add_notice(LAUNCH_NO_NAME_NOTICE.format(
                name=arg, themes=", ".join(theme_names()), looks=", ".join(LAUNCH_PRESETS)), NOTICE_WARN)
            return
        self.theme = self._themed()
        if choice in BACKGROUND_MODES:
            self.transcript.add_notice(f"Theme {self.theme.name} {self._background_text()}.")
        else:
            self.transcript.add_notice(f"Theme {self.theme.name} applies to this session; `omh theme` keeps it.")
        self._full_redraw()

    def _shown_look(self) -> str:
        """The launch look drawn now: the /theme picker's highlight while it is open, else the one in use."""
        return self.launch_picker.highlighted if self.launch_picker is not None else self.launch_look

    def _badge_forms(self) -> tuple[Line, ...]:
        """`[⚚ OMH Native]` in the shown look and its shorter forms (`frame.badge_forms`), for the info line's left
        end; none on a tiny terminal, which keeps its one line for what the keys do. Built again only when the look or
        the theme changed."""
        if is_tiny(self.size[1], self.size[0]):
            return ()
        key = (self._shown_look(), self.theme, self.color_depth)
        if self.badge_cache[0] == key:
            return self.badge_cache[1]
        background = self._surface()
        palette = launch_palette(self._shown_look(), surface_for(self._skin(), background))
        if palette.sweep or palette.faces:  # the spectrum's hues across the letters, or the look's own colour
            native = launch_wordmark(NATIVE_WORD, self._skin(), background, palette)
        else:  # graphite: its turquoise, the one hue it has
            surface = surface_for(self._skin(), background)
            ink = BLACK if is_light(surface) else WHITE
            native = (Span(NATIVE_WORD, Style(fg=lifted_colour(palette.spark, surface, TEXT_CONTRAST, ink), bold=True)),)
        if self.color_depth == NO_COLOR:
            native = tuple(Span(span.text, replace(span.style, depth=NO_COLOR)) for span in native)
        forms = badge_forms(self.theme, self._launch_paint().look.brand, native)
        self.badge_cache = (key, forms)
        return forms

    def _launch_paint(self) -> LaunchPaint:
        """The shown look's card colours against the theme's background, painted at this terminal's depth."""
        background = self._surface()
        palette = launch_palette(self._shown_look(), surface_for(self._skin(), background))
        look = launch_styles(self._skin(), background, palette)
        if self.color_depth == NO_COLOR:
            look = LaunchStyles(*(replace(style, depth=NO_COLOR) for style in (look.brand, look.label, look.edge)))
        return LaunchPaint(self.theme, look)

    def _card_lines(self, cols: int, room: int) -> list[Line]:
        """The launch card in the shown look, from what the session has said so far, fitted to `room` rows."""
        row = self.last_session_row
        facts = LaunchFacts(
            model=self.model, effort=self.effort, session=self.stored_id,
            last_title=row.label if row is not None else "", last_id=row.id if row is not None else "",
            last_count=row.message_count if row is not None else 0,
        )
        return launch_card(self._shown_look(), facts, self._launch_paint(), cols, room, self.session_skills)

    def _launch_swatches(self) -> dict[str, tuple[Style, ...]]:
        """Each launch look's colours for its row in the /theme picker, each lifted to a glyph's 3:1."""
        surface = surface_for(self._skin(), self._surface())
        ink = BLACK if is_light(surface) else WHITE
        swatches = {}
        for name in LAUNCH_PRESETS:
            palette = launch_palette(name, surface)
            colours = palette.faces or palette.sweep or (*palette.greys[:1], *palette.whites[:2], palette.spark)
            step = max(len(colours) // LAUNCH_SWATCH_STEPS, 1)
            swatches[name] = tuple(
                Style(fg=lifted_colour(colour, surface, EDGE_CONTRAST, ink), depth=self.color_depth)
                for colour in colours[::step][:LAUNCH_SWATCH_STEPS]
            )
        return swatches

    def _keep_launch_look(self, name: str) -> None:
        """Use launch look `name` from now on, save it under the OMH home, and draw the logo and the card in it."""
        self.launch_look = name
        self.theme = self._themed()
        home = self._omh_home()
        if home is None:
            self.transcript.add_notice(LAUNCH_SESSION_NOTICE.format(name=name))
        else:
            try:
                path = write_launch_choice(home, name)
            except OSError as error:
                self.transcript.add_notice(
                    LAUNCH_SAVE_FAILED_NOTICE.format(name=name, path=theme_store_path(home), error=error), NOTICE_WARN)
            else:
                self.transcript.add_notice(LAUNCH_KEPT_NOTICE.format(name=name, path=path))
        self._redraw_launch()

    def _preview_launch(self) -> None:
        """Draw the shown look where it shows: on the launch screen, the logo by a full redraw and the live card in
        the region; past it, the compact preview above the picker (`_launch_preview`) needs only the next frame."""
        self.theme = self._themed()  # a sent prompt's band in the shown look
        if self.card_state == CARD_LIVE:
            self._full_redraw()
        self.dirty = True

    def _redraw_launch(self) -> None:
        """Draw a look kept: as the preview does, and once the launch is past it, the logo and the kept card in
        scrollback again by a full redraw while the whole session still fits one, as `/theme <name>` repaints."""
        if self.card_state == CARD_LIVE or (self.in_launch_session and not self.transcript.left_out):
            self._full_redraw()
        self.dirty = True

    def _launch_preview(self, cols: int) -> list[Line]:
        """The highlighted look in four rows: its wordmark and its card's frame."""
        background = self._surface()
        palette = launch_palette(self._shown_look(), surface_for(self._skin(), background))
        mark = launch_wordmark(BANNER_BRAND, self._skin(), background, palette)
        if self.color_depth == NO_COLOR:
            mark = tuple(Span(span.text, replace(span.style, depth=NO_COLOR)) for span in mark)
        facts = LaunchFacts(model=self.model, effort=self.effort, session=self.stored_id)
        return preview(self._shown_look(), facts, self._launch_paint(), mark, cols, self.session_skills)

    def _launch_picker_key(self, event: Key | Paste | Mouse) -> None:
        """A key for the open /theme picker: a move previews the highlighted look, Enter keeps it, Esc puts the one in
        use back."""
        picker = self.launch_picker
        if picker is None or isinstance(event, Mouse):
            return
        action = picker.handle_key(event)
        if action == LAUNCH_MOVE:
            self._preview_launch()
        elif action == LAUNCH_PICK:
            self.launch_picker = None
            self._keep_launch_look(picker.highlighted)
        elif action == LAUNCH_CLOSE:
            self.launch_picker = None
            if picker.highlighted != picker.current:
                self._preview_launch()
        self.dirty = True

    def _take_launch_clickable(self, budget: Budget, cols: int, rows: int) -> None:
        """The /theme picker's look rows as the cells a click moves the highlight to, counted up from the region's
        last row like the agent list's, with mouse reports on while it is open."""
        picker = self.launch_picker
        first = budget.slot_top + (picker.first_row if picker is not None else 1)
        last = budget.total - 1
        self.clickable = {
            last - (first + index): (Hit(0, cols, f"launch:{index}"),)
            for index in range(len(LAUNCH_PRESETS)) if first + index < budget.slot_top + budget.slot
        }
        self._set_mouse(bool(self.clickable) and self.region.last_row(rows) is not None)

    def _launch_picker_click(self, event: Mouse) -> None:
        """A plain left press on one of the picker's look rows highlights that look and previews it."""
        picker = self.launch_picker
        plain = event.button == BUTTON_LEFT and event.pressed and not (event.motion or event.shift or event.alt or event.ctrl)
        last = self.region.last_row(self.size[1])
        if picker is None or not plain or last is None or self.redraw_at is not None:
            return
        above, column = last - (event.y - 1), event.x - 1 - self._margin()  # a report counts from 1
        target = next((hit.subagent_id for hit in self.clickable.get(above, ()) if hit.start <= column < hit.end), "")
        if target.startswith("launch:") and picker.move_to(int(target.split(":", 1)[1])) == LAUNCH_MOVE:
            self._preview_launch()

    def _background_text(self) -> str:
        """How the theme's background was chosen, for `/theme`'s notices."""
        if self.background_mode != BACKGROUND_AUTO:
            return f"on a {self.background_mode} background for this session; /theme auto follows the terminal again"
        if self.background_named_dark:
            return "follows the terminal's background (a dark one, as COLORFGBG names it)"
        if self.background is None:
            return "follows the terminal's background (none reported, so a dark one is assumed)"
        tone = "light" if is_light(self.background) else "dark"
        return f"follows the terminal's background ({self.background}, a {tone} one)"

    def _omh_model(self, arg: str) -> None:
        """Run the model-chain picker on the alternate screen, over the TUI's own raw terminal.

        The main screen (scrollback and the live region) stays untouched underneath
        and comes back as it was, so the picker leaves no frame behind; only a resize
        while it was open needs the full redraw. The gateway is still read while it is
        open (`_picker_reader`): a streaming reply goes on into the transcript underneath,
        and a server request closes the picker, as it closes the pager, with nothing
        saved; the question opens once the picker's screen is gone. Nothing is answered
        for the person either way.
        """
        before = self.size
        self._set_mouse(False)  # the agent list is not on the picker's screen; the next frame asks again
        self.terminal.write(ALT_SCREEN_ON + CURSOR_HOME + HIDE_CURSOR)
        self.chains_open, self.chains_closing = True, False
        try:
            message = self.pick_model_chains(
                self.environ,
                self.theme,
                read_key=self._picker_reader(),
                # Raw mode writes "\n" as a bare line feed; the picker's lines need a carriage return too.
                write=lambda text: self.terminal.write(text.replace("\n", "\r\n")),
                width=self.screen[0],
            )
        finally:
            self.terminal.write(ALT_SCREEN_OFF + self._caret_visibility())
            closed_for_question, self.chains_open, self.chains_closing = self.chains_closing, False, False
        self._take_size()
        if self.size != before:
            self._full_redraw()
        self.dirty = True
        self.transcript.add_notice(f"{CHAINS_CLOSED_NOTICE} {message}" if closed_for_question else message)

    def _picker_reader(self) -> Callable[[], str]:
        """A picker's `read_key` over the TUI's terminal and key decoder; a hung-up terminal cancels.

        The decoder is told what the loop tells it, so a report sent before
        the picker's off still types nothing and its ESC does not cancel. As
        in the loop, an empty read settles held bytes only once input has been
        quiet for `FLUSH_SILENCE_SECONDS`: a resize signal ends a read early
        with nothing read, and must not turn an arrow's ESC into Esc. Between
        reads it takes what the gateway sent, as the loop would, so nothing
        waits on the picker; once a server request has come (or the gateway is
        gone) the next key it hands the picker is the one that cancels.
        """
        pending: deque[Key | Paste | Mouse] = deque()

        def read_key() -> str:
            while not pending:
                if self.chains_closing or self.exit_code is not None or self.respawn_reason:
                    return KEY_QUIT
                try:
                    data = self.terminal.read(READ_TIMEOUT_SECONDS, self.wake)
                except EOFError:
                    return KEY_QUIT
                if data:
                    self.input_at = self.clock()
                    pending.extend(self.decoder.feed(data))
                elif self.clock() - self.input_at >= FLUSH_SILENCE_SECONDS:
                    pending.extend(self.decoder.flush(self.terminal.mouse_reporting, self.mouse_off_at))
                self._drain_gateway()
            return picker_key(pending.popleft())

        return read_key

    def _caret_visibility(self) -> str:
        """The cursor as the live region's last frame left it, for the main screen coming back from the alternate one."""
        return HIDE_CURSOR if self.region.caret_hidden else SHOW_CURSOR

    # ── pager ──

    def _open_pager(self, title: str, lines: list[Line]) -> None:
        """`lines` in a pager on the alternate screen (`_show_pager`)."""
        self._show_pager(Pager(title, lines))

    def _show_pager(self, pager: Pager) -> None:
        """`pager` on the alternate screen; a pager already open is replaced without switching to that screen again.

        A second `ALT_SCREEN_ON` would save the main screen's cursor over the
        one saved on the way in. It is no agent's log: `_open_agent_log` names
        the agent once this returns.
        """
        if self.pager is None:
            self.terminal.write(ALT_SCREEN_ON)
        self._stop_board_reader()  # a board this replaces reads no more
        self.pager = pager
        self.log_agent = ""

    def _leave_pager(self) -> None:
        self.pager = None
        self.log_agent = ""
        self._stop_board_reader()
        self.terminal.write(ALT_SCREEN_OFF + self._caret_visibility())
        if self.redraw_after_pager:
            self.redraw_after_pager = False
            self._full_redraw()

    # ── drawing ──

    def _on_resize(self) -> None:
        """Note the new size; the redraw waits until the size settles (`_redraw_when_settled`).

        A terminal reflows its own rows when its width changes, so the live
        region's relative bookkeeping no longer matches the screen and any
        in-place repaint leaves the old frame behind in scrollback. The only
        clean answer is a full redraw from the transcript kept in memory.
        Mouse reports go off at once, since what is on screen until then is
        the old layout reflowed; the settled redraw's frame turns them back
        on if it still has an agent to click.
        """
        self._set_mouse(False)
        self._take_size()
        self.dirty = True
        if self.pager is not None:
            self.redraw_after_pager = True
            return
        self.redraw_at = self.clock() + RESIZE_SETTLE_SECONDS

    def _redraw_when_settled(self) -> None:
        """The settled size redraws the session, even one back where it was printed: a shrink and restore close
        together (a tab shown again, a split laid out again) reaches the loop as one signal at the old size, and the
        terminal has reflowed its rows by then."""
        if self.redraw_at is not None and self.clock() >= self.redraw_at:
            self.redraw_at = None
            self._full_redraw()

    def _full_redraw(self) -> None:
        """Erase screen and scrollback, then print the session again at the current width.

        The banner and the transcript's last `REDRAW_TAIL_ROWS` rows are
        rendered anew (`Transcript.retake_tail`), under one row counting the
        messages above them, so nothing wrapped at the old width survives, no
        earlier frame is left in scrollback, and a long session costs a redraw
        no more than that. Scrollback from before the TUI started is erased
        with it.
        """
        if self.pager is not None:
            # Erasing from the alternate screen leaves the main screen's rows (and, on some terminals, its scrollback)
            # in place, so the session printed again under them would show twice: the main screen is redrawn once
            # the pager is left instead, and the pager stays as it is.
            self.redraw_after_pager = True
            return
        # The clear homes the cursor, so the next first frame starts on the screen's top row; it goes out in that
        # frame's synchronized update, so the blank screen never shows.
        self.region = self._new_region(at_top=True, lead=CLEAR_SCREEN_AND_SCROLLBACK)
        self.transcript.retake_tail(self.size[0], self.theme, REDRAW_TAIL_ROWS)
        if self.banner_record is not None:
            self.banner_facts = dict(self.banner_record)
            # The logo comes back only on top of the whole session it opened, never above a cut.
            self.logo_due = self.in_launch_session and not self.transcript.left_out
        self.dirty = True

    def _take_hud(self) -> None:
        # The subagents whose output tokens the poller's next read takes from state.db, on its thread, not this one.
        self.poller.watch_tokens(self.roster.token_sessions(self.clock()))
        snapshot = self.poller.take()
        if snapshot is not None and snapshot.session_id == self.stored_id:
            self.hud = snapshot
            self._prune_kept_lanes()  # a run a new turn read as open may be over in this payload
            self.roster.ingest_tokens(snapshot.output_tokens)
            self.dirty = True
            self._retire_finished_plan()
            self._print_catches()
            self._take_background(snapshot)

    def _print_catches(self) -> None:
        """One row per catch OMH made in this session since the last payload (`catch_lines`), as it happens.

        The first payload of a session only sets the mark: a resumed or
        attached session does not replay the catches it made before it was
        opened here. The empty snapshot a switch delivers is no payload, and an
        error payload says nothing about which catches exist, so the mark is set
        by the first readable read of the session. A `seq` below the mark means
        the ledger started over (deleted or unreadable): the mark moves down to
        it, so new catches print again instead of waiting for the old count.
        """
        hud = self.hud
        catches = catch_lines(hud.payload) if hud is not None else None
        if hud is None or catches is None:
            return
        newest = max((seq for seq, _ in catches), default=-1)
        if self.catch_seen is None or self.catch_seen[0] != hud.session_id or newest < self.catch_seen[1]:
            self.catch_seen = (hud.session_id, newest)
            return
        seen = self.catch_seen[1]
        for seq, line in catches:
            if seq > seen and line:
                self.transcript.add_aside(NoticeBlock(line, one_line=True, mark=CATCH_MARK))
        self.catch_seen = (hud.session_id, max(seen, newest))

    def _take_background(self, snapshot: HudSnapshot) -> None:
        """The session's background processes from this read, and whether one ended unreported.

        One ended unreported when it was last seen with no turn running since,
        nothing could wake the session on its exit, its end could be asked
        (`askable`), and no turn runs now. The row then says it finished and
        the bell rings once; one that ends before that offer is taken joins
        it. A process that ended while a turn ran just goes, and so does one
        Hermes may report: `notify_on_complete` on, or watch patterns, which
        Hermes turns into a completion notice in memory once they stop
        matching (`process_registry`), with no checkpoint rewrite to show it.
        One whose end cannot be asked just goes too, since its row also drops
        when another interpreter rewrites the file. Another session's read
        starts over and reports nothing. The first read after each turn is
        always delivered (`_turn_ended` refreshes the poller), so a process
        first seen during a turn is stamped quiet once it is over. Only a read
        that started after that refresh stamps: one taken during the turn and
        handed over after it may list a process that has since ended.
        """
        if snapshot.session_id != self.bg_session:
            self.bg_session = snapshot.session_id
            self.bg_running, self.bg_quiet, self.bg_done = (), {}, None
        running = {process.proc_id for process in snapshot.processes}
        ended = tuple(
            process for process in self.bg_running
            if process.proc_id not in running and not process.notify and not process.watched and askable(process)
            and self.bg_quiet.get(process.proc_id, -math.inf) > self.busy_since
        )
        if ended and not self._busy():
            done, at = self.bg_done or ((), self.wall_clock())
            self.bg_done = (done + ended, at)
            self._alert_background(ended[0])
        self.bg_running = snapshot.processes
        self.bg_quiet = {key: at for key, at in self.bg_quiet.items() if key in running}
        if not self._busy() and snapshot.refreshes >= self.bg_after:
            self.bg_quiet.update((process.proc_id, self.clock()) for process in self.bg_running)

    def _alert_background(self, process: BackgroundProcess) -> None:
        """The bell a question rings (`_alert_question`), once, as a process ends unreported; none with OMH_TUI_BELL=0."""
        if self.environ.get(BELL_ENV) == BELL_OFF:
            return
        signal = attention_sequence(self.environ, truncate(f"{tool_call(process)} finished", QUESTION_ALERT_CHARS))
        self.terminal.write(BELL if signal == BELL else BELL + signal)

    def _report_background(self) -> None:
        """Enter on an empty composer under a finished row: the one prompt that tells the session, and the row goes."""
        done = self.bg_done
        if done is None:
            return
        self.bg_done = None
        self.dirty = True
        self._send_prompt(report_prompt(done[0]))  # every process the row counts

    def _background_line(self, cols: int) -> Line | None:
        """The background-process row: the first process that ended unreported (and how many more did), else the
        running one most at risk of going unnoticed (the newest Hermes will not wake the session for), else none."""
        if self.bg_done is not None:
            done, at = self.bg_done
            return finished_line(done[0], ago=self.wall_clock() - at, theme=self.theme, width=cols, more=len(done) - 1)
        if not self.bg_running:
            return None
        quiet = [process for process in self.bg_running if not process.notify and not process.watched]
        shown = (quiet or list(self.bg_running))[-1]
        glyph = WORKING_GLYPHS[self._spinner_frame() % len(WORKING_GLYPHS)]
        return running_line(
            shown, more=len(self.bg_running) - 1, now=self.wall_clock(), glyph=glyph, turn_runs=self._busy(),
            theme=self.theme, width=cols,
        )

    def _background_live(self) -> bool:
        """Whether the background-process row shows, so its spinner turns and its clock ticks."""
        return bool(self.bg_running) or self.bg_done is not None

    def _retire_finished_plan(self) -> None:
        """Stop drawing a plan whose every item is done, once no turn runs, as Claude Code's list goes once done.

        A plan the panel showed with an item left also leaves its final state
        in the transcript; one that was already finished when the session
        opened only goes. A plan with another text (a new one) is drawn again.
        """
        payload = self.hud.payload if self.hud is not None else None
        state = plan_state(payload)
        if state == "open":
            self.plan_seen_open = True
        elif state == "done" and not self._busy():
            text = plan_text(payload)
            if text != self.retired_plan:
                self.retired_plan = text
                if self.plan_seen_open:
                    self.transcript.add_notice(text)
                self.plan_seen_open = False

    def _panel_live(self) -> bool:
        payload = self.hud.payload if self.hud is not None else None
        return isinstance(payload, Mapping) and bool(payload.get("active"))

    def _aura_live(self) -> bool:
        """Whether the composer's `dag-ulw` aura moves now (`aura`): a token in the draft it draws, at the truecolor
        depth, with motion on, on a background its band shows on (`theme.aura_moves`), and while no list or tree
        holds the keys (the composer is drawn blank then). Only then does the loop tick for it; the gradient stands
        still at 256 or 16 colours and with reduced motion, and there is none at the `NO_COLOR` depth, so nothing
        ticks while it would not move.
        """
        composer = self.composer
        return (
            self._aura_moves()
            and not composer.pastes and not composer.masked and not self._composer_hidden()
            and self.list_selected is None and self.tree_selected is None  # browsing draws the composer blank
            and bool(aura_ranges(composer.text))
        )

    def _take_size(self) -> None:
        """The terminal's size now (`screen`), and the size the session is laid out for (`size`): the screen less
        the working glow's margin and footer where it has them (`_edged`)."""
        self.screen = self.terminal.size()
        cols, rows = self.screen
        self.size = (cols - 2 * EDGE_MARGIN, rows - 1) if self._edged() else self.screen

    def _edged(self) -> bool:
        """Whether the screen keeps its edge for the working glow's frame (`edge_glow`): where it shows
        (`_glow_shown`), on a screen big enough (`edge_fits`). The rows are then drawn `EDGE_MARGIN` columns in from
        each side, over a blank last row of the region's own, whether a turn runs or not, so nothing moves as the
        frame comes and goes."""
        return self._glow_shown() and edge_fits(*self.screen)

    def _glow_shown(self) -> bool:
        """Whether the working glow shows on a screen big enough: wanted (`/glow`), not held off by OMH_TUI_GLOW=0,
        with motion on, at the truecolor depth."""
        return (self.glow and self.environ.get(GLOW_ENV) != GLOW_OFF and self.motion
                and self.color_depth == TRUECOLOR)

    def _saved_glow(self) -> bool:
        """Whether the working glow is wanted: as saved under the OMH home, else on."""
        home = self._omh_home()
        saved = read_glow_choice(home) if home is not None else None
        return True if saved is None else saved

    def _glow(self, arg: str) -> None:
        """`/glow on|off` turns the working glow on or off and keeps that under the OMH home; alone, switches it.

        The rows move in or out by the margin it takes, so the session is drawn again.
        """
        choice = arg.strip().lower()
        if choice not in ("", "on", "off"):
            self.transcript.add_notice(GLOW_USAGE_NOTICE, NOTICE_WARN)
            return
        self.glow = not self.glow if not choice else choice == "on"
        state = "on" if self.glow else "off"
        home = self._omh_home()
        if home is None:
            self.transcript.add_notice(GLOW_SESSION_NOTICE.format(state=state))
        else:
            try:
                path = write_glow_choice(home, self.glow)
            except OSError as error:
                self.transcript.add_notice(
                    GLOW_SAVE_FAILED_NOTICE.format(state=state, path=theme_store_path(home), error=error), NOTICE_WARN)
            else:
                self.transcript.add_notice(GLOW_KEPT_NOTICE.format(state=state, path=path))
        if self.glow and self.environ.get(GLOW_ENV) == GLOW_OFF:
            self.transcript.add_notice(GLOW_ENV_NOTICE.format(state=state))
        elif self.glow and not self._glow_shown():
            self.transcript.add_notice(GLOW_UNAVAILABLE_NOTICE.format(state=state))
        if self._edged() != (self.size != self.screen):  # the margin comes or goes: lay the session out again
            self._take_size()
            self._full_redraw()
        self.dirty = True

    def _margin(self) -> int:
        """Columns the rows are drawn in from the screen's left edge."""
        return EDGE_MARGIN if self._edged() else 0

    def _new_region(self, **place: Any) -> LiveRegion:
        """A live region for the screen as it is now: with the working glow's margin and footer where it has them."""
        edged = self._edged()
        return LiveRegion(self.terminal.write, margin=EDGE_MARGIN if edged else 0, footer=edged, **place)

    def _edge_live(self) -> bool:
        """Whether the working glow's light goes round the screen now (`edge_glow`): while a turn runs, where the
        screen keeps its edge for it (`_edged`)."""
        return self._busy() and self._edged() and bool(self.theme.glow_ring)

    def _edge(self) -> Edge | None:
        """The working glow's light for this frame (owner request 2026-10-28), at the clock's time, or None."""
        return edge(*self.screen, self.theme, self.clock()) if self._edge_live() else None

    def _aura_moves(self) -> bool:
        """Whether the dag-ulw aura moves on this terminal now: the truecolor depth, motion on, and a background its
        band shows on (`theme.aura_moves`). Where it does not, nothing draws it but the composer's still look."""
        return self.motion and self.color_depth == TRUECOLOR and aura_moves(self.theme)

    def _aura_phase(self) -> int | None:
        """The phase a running dag-ulw node's aura stands at (`dag_tree`, `/dag`), or None where the aura does not
        move: those surfaces then draw the node as they always have."""
        return self._spinner_frame() if self._aura_moves() else None

    def _render_when_due(self) -> None:
        if self.terminal.resized():  # one that came during this step's work: no frame is drawn at the old size
            self._on_resize()
        self._redraw_when_settled()
        if self.redraw_at is not None:
            return  # the screen is mid-reflow; the settled redraw paints it
        now = self.clock()
        due = (self._busy() or self._panel_live() or self._aura_live() or self._background_live()
               or bool(self.held_submits)) \
            and now - self.last_render >= self._tick_seconds()
        if not (self.dirty or due):
            return
        self.dirty = False
        self.last_render = now
        self._render()

    def _render(self) -> None:
        cols, rows = self.size
        self._settle_list()
        self._write_title()
        if self.pager is not None:
            self.clickable = {}
            self._set_mouse(True, drag=True)  # the alternate screen has no scrollback to take: the pager scrolls itself
            self._refresh_agent_log()
            self.terminal.write(self.pager.frame(*self.screen, self.theme))
            return
        stable = self.transcript.take_stable_lines(cols, self.theme)
        prompt_row = self.transcript.prompt_row
        head: list[Line] = []
        if self.banner_facts is not None:
            background = self._surface()
            palette = launch_palette(self._shown_look(), surface_for(self._skin(), background))
            if self.logo_due:
                head = banner_logo(self._skin(), background, cols, rows, self.color_depth, palette)
            head += banner_lines(**self.banner_facts, theme=self.theme, width=cols, brand=self._launch_paint().look.brand)
            if self.card_state == CARD_KEPT and self.logo_due:  # a redraw of the whole session prints it again
                head += [*self._card_lines(cols, self.card_room), ()]
            self.banner_facts = None
        if self.card_state == CARD_LIVE and not self.launch_layout:
            # The first prompt went: the card, as it was last fitted, stays in scrollback above it.
            head += [*self._card_lines(cols, self.card_room), ()]
            self.card_state = CARD_KEPT
        if head:
            stable = head + stable
            prompt_row = None if prompt_row is None else prompt_row + len(head)
        # Counted from the prompt's own first row: not the blank row or the held rows above it, and after a full
        # redraw only the rows retaken from the prompt on.
        if prompt_row is not None:
            self.flushed_since_prompt = len(stable) - prompt_row
        else:
            self.flushed_since_prompt += len(stable)
        if not self._menu_rows():
            self.menu_below = None
        # On the screen's last row the region keeps its height (what the flush below covers aside), so what shrinks
        # becomes pad rows under the live block and the composer stays on the bottom rows; above it, the region
        # follows the content. Where the region's place is not certain it counts as above.
        pinned = self.region.last_row(rows) == rows - 1
        min_height = max(self.region.height - len(stable), 0) if pinned else 0
        # The frame a turn ends with, on the bottom rows: the turn's last frame. Its working rows, their spacer and
        # the done line balance out, but the sticky prompt (and the blank row over it) and the blank row over the plan
        # have nothing in this frame to take their rows. The sticky came in once the prompt had scrolled off, scrolling
        # as many transcript rows into scrollback, and nothing brings those back, so kept they would stand as blank
        # rows between the done line and the composer. The region gives them up and the composer rises by them.
        ended = self.frame_budget if pinned and self.frame_busy and not self._busy() else None
        if ended is not None:
            min_height = max(min_height - ended.sticky - ended.sticky_gap, 0)
        top = self.region.top_row(rows)
        if not pinned and self.launch_layout and top is not None:
            # Until the first prompt the launch fills the screen: the rows under the banner pad the region down to the
            # last row, so the composer stands on the bottom rows from the first frame and the pinned rule keeps it.
            min_height = max(rows - min(top + len(stable), rows - 1), 0)
        build = partial(
            build_frame,
            cols=cols,
            rows=rows,
            min_height=min_height,
            composer=None if self._composer_hidden() else self.composer,
            # the list, or the dag tree, under the info line has the keys
            composer_blank=self.list_selected is not None or self.tree_selected is not None,
            info=self._info_line(cols),
            tail=self._tail(cols),
            tail_spacer=self.tail_spacer,  # read after `_tail` made it
            slot=self._slot_lines(cols, rows),
            # The plan breathes: a blank row over it (where the tail does not end blank) and one between it and the rule.
            gaps=(self.panel_shown, self.panel_shown),
            gap_reserve=1 + int(rows >= TIP_MIN_ROWS),  # the working row and its tip, kept free as the turn ends
            below=self.menu_under,  # read after `_slot_lines` made it
            agents=self._agent_view(cols, rows),
            tail_floor=self._working_rows(),
            known_slash=self.known_slash,
            aura=self._spinner_frame() if self._aura_live() else 0,
            aura_depth=self.color_depth,
            text_question=self.slot is not None and not self.slot.picking,
            slot_caret=self._slot_caret(),  # read after `_slot_lines` drew the picker it comes from
            theme=self.theme,
            mode=self._display_mode(),
            placeholder=(TELL_PLACEHOLDER if self.tell_draft is not None else PLACEHOLDER)
            if self._composer_open()
            else "",
        )
        frame = build()
        if ended is not None and frame.budget.gaps[0] < ended.gaps[0]:  # the tail now ends blank, its own gap
            min_height = max(min_height - (ended.gaps[0] - frame.budget.gaps[0]), 0)
            build = partial(build, min_height=min_height)
            frame = build()
        if self._place_menu(rows, len(stable), frame):
            build = partial(build, slot=self._slot_lines(cols, rows), below=self.menu_under)
            frame = build()
        wanted, busy = len(build.keywords["agents"]), self._busy()
        room = frame.budget.agents
        if not busy and pinned:
            room = min(room, self._held_view_rows(wanted, frame.budget, rows))
        elif not busy:
            self.view_hold = None  # above the bottom rows the composer follows the content: nothing to keep
        if room < wanted:
            # A full slot and a tall composer left the view fewer rows than its cap, or on the bottom rows it leaves
            # the working rows the ended turn kept: drawn again to fit them, so its last row (the count of what it
            # cannot show) is never the one cut.
            build = partial(build, agents=self._agent_view(cols, rows, room))
            frame = build()
        # A dag run's tree that left the view as its run ended (`_retire_finished_run`) gives its rows up on the bottom
        # rows as blank rows under the info line, not as pad above the composer: what the run's end print and the
        # turn's last lines did not fill would be a blank band between them and the composer. The composer stays where
        # the flush leaves it, as Claude Code's prompt does when the list under it goes, and the rows go as output
        # fills them (the pad they stand for shrinks), at the next turn, and above the bottom rows.
        self.tree_freed = min(self.tree_freed, frame.budget.pad) if pinned and not busy else 0
        if self.tree_freed:
            build = partial(build, agents=[*build.keywords["agents"], *[()] * self.tree_freed])
            frame = build()
        if self.card_state == CARD_LIVE and self.launch_layout and min_height > 0:
            # The card goes at the region's top, under what is flushed above it (and the spacer the tail opens with
            # after a notice), and blank rows take the rest down to the composer, so the region still reaches the
            # last row and no pad goes above the card.
            room = min_height - (frame.budget.total - frame.budget.pad)
            card = self._card_lines(cols, room - 1)  # a blank row stays over the composer's rule
            self.card_room = max(room - 1, 0)
            if card:
                build = partial(build, tail=[*build.keywords["tail"], *card, *([()] * (room - len(card)))])
                frame = build()
        # The rows above the region once the flush below and this frame are drawn: transcript rows.
        if self._sticky_needed(self.region.rows_above(rows, len(stable), frame.height)):
            frame = build(sticky=sticky_line(self.sticky, cols, self.theme, self.known_slash))
        # Flushed before the frame, the lines cover the region's top rows, where the lines leaving
        # the tail were drawn (a settled tool group is those same rows, moved above the region), and
        # the frame is drawn under them. Flush and frame are one write, so no screen between them shows.
        self.region.render(frame.lines, frame.cursor, cols, flush=stable, screen_rows=rows, edge=self._edge())
        self.frame_budget = frame.budget
        self.frame_busy = busy
        if busy:
            self.view_hold = (wanted, frame.budget.agents, self._working_rows())
        self._take_clickable(frame.budget, self._clickable_rows())
        if self.launch_picker is not None:
            self._take_launch_clickable(frame.budget, cols, rows)

    def _place_menu(self, rows: int, flushed: int, frame: Frame) -> bool:
        """Where the open completion menu goes with `frame`; True when that changed, so the frame is built again.

        A menu that opens goes under the composer where the region's place is
        certain and, with the menu at its tallest (`slot_cap`), the region
        would still end short of the screen's last row once `flushed` lines
        and the frame are drawn: there the composer and the caret stay where
        they are, as under Claude Code's menu. On the bottom rows (where that
        end is the screen's last row already), close to them, or where the
        place is unknown, it opens above the composer as before. Filtering it
        never moves it. Output that brings a region holding it under the
        composer to the screen's last row takes it above in the same frame, so
        the composer reaches the bottom rows with that output and closing the
        menu there moves nothing (the region keeps its height).
        """
        if not self._menu_rows():
            return False
        if self.menu_below is None:
            tallest = frame.height + slot_cap(rows, self.size[0]) - frame.budget.slot - frame.budget.below
            self.menu_below = (
                self.region.top_row(rows) is not None
                and self.region.rows_above(rows, flushed, tallest) + tallest <= rows - 1
            )
            return self.menu_below
        if self.menu_below and self.region.rows_above(rows, flushed, frame.height) + frame.height > rows - 1:
            self.menu_below = False
            return True
        return False

    def _display_mode(self) -> str:
        """What the info line shows: the shell while the composer holds a `!` line for Hermes' shell, else the input mode."""
        if self._composer_open() and self.composer.text.startswith(SHELL_PREFIX):
            return MODE_SHELL
        return self.mode

    def _composer_open(self) -> bool:
        """Whether the composer takes the keys for a prompt: no question, picker, search or agent list has them."""
        return (
            self.slot is None and self.picker is None and self.search is None and self.rewind_picker is None
            and self.model_picker is None and self.list_selected is None and self.tree_selected is None
            and self.launch_picker is None
        )

    def _composer_hidden(self) -> bool:
        """Whether the frame draws no composer: the person picks from a list, so nothing is typed into it.

        A question answered by picking (`PromptSlot.picking`), the session,
        rewind and model pickers, whose filter is a row of their own, and the
        history search, whose query row is. The completion menus keep it, and
        the agent list keeps its rows, drawn blank (`build_frame`'s
        `composer_blank`).
        """
        if self.slot is not None:
            return self.slot.picking
        return (
            self.picker is not None or self.rewind_picker is not None or self.model_picker is not None
            or self.search is not None or self.launch_picker is not None
        )

    def _info_line(self, cols: int) -> Line:
        """The info line, saying what the next key does when that is not the usual (a rewind, Esc's or Ctrl+C's second press).

        A picked steer or rewind keeps room for its last form but one, the shortest that still names what it
        acts on: the agent count (`_agent_chip`, after the mode's label) drops its `↓ agents`, then goes, before
        that would be cut. The right side (`_info_right`) gives way before either. A terminal too small for the
        agent view counts the agents without `↓ agents`: the list cannot open there. While the list is open it
        shows the agents itself, and the line says its keys. The line starts `_info_inset()` cells in.
        """
        inset = self._info_inset()
        say: str | tuple[str, ...] = ""
        say_style = None
        armed = self.escape_armed
        steered = self.roster.agents.get(self.agent_steer or "")
        picker_keys = self._picker_keys()
        if self.slot is not None:
            say = self.slot.keys_while(self._busy())
        elif picker_keys:
            say = picker_keys
        elif self.list_selected is not None:
            say, say_style = self._agent_list_say()
        elif self.tree_selected is not None:
            say, say_style = self._tree_say()
        elif self._exit_said():  # over a steer, rewind or tell only after an interrupt (`_exit_said`)
            say = EXIT_HINT
        elif steered is not None:
            say, say_style = tuple(form.format(name=steered.name) for form in STEER_SAY), self.theme.muted
        elif self.rewind is not None:
            say, say_style = tuple(form.format(ordinal=self.rewind.ordinal) for form in REWIND_SAY), self.theme.warn
        elif self.tell_draft is not None:
            say, say_style = TELL_SAY, self.theme.muted
        elif armed is not None and self.clock() - armed[1] <= DOUBLE_ESCAPE_SECONDS:
            say = ESCAPE_AGAIN.format(armed[0])
        elif self._newline_keys_due():
            say = NEWLINE_KEYS
        badge = self._badge_forms()
        # The count is sized on the whole line: the badge and the branch give way before the count does (`info_line`).
        room = cols - inset - chip_column(self._display_mode(), self.theme)
        if isinstance(say, tuple):
            room -= cell_width(LABEL_SEPARATOR + say[max(len(say) - 2, 0)])
        listing = self.list_selected is not None or self.tree_selected is not None
        chip = self._agent_chip(room) if not listing or self.slot is not None else ()
        line = info_line(
            mode=self._display_mode(),
            width=cols - inset,
            theme=self.theme,
            right=self._info_right(),
            chip=chip,
            say=say,
            say_style=say_style,
            # While Hermes has approvals off on its own, Shift+Tab turns plan on and off and nothing else.
            cycle=HERMES_OWN_CYCLE.get(self._display_mode(), "") if self.approvals_off_by_hermes else "",
            badge=badge,
            branch=branch_forms(self.git.state, self.theme) if self.git is not None and badge else (),
        )
        return (Span(" " * inset), *line) if inset and line else line

    def _info_inset(self) -> int:
        """Cells before the info line's text: `INFO_INSET` under the composer's rule; none on a tiny
        terminal, which draws no rule."""
        return 0 if is_tiny(self.size[1], self.size[0]) else INFO_INSET

    def _newline_keys_due(self) -> bool:
        """Whether the info line names the keys that add a line: the draft spans lines (typed, or a pasted chip of them)
        on a terminal that has sent no key report, where Shift+Enter would send it; idle, in normal mode."""
        return (
            not self.keyboard_protocol and self._composer_open() and not self._busy()
            and self._display_mode() == MODE_NORMAL and "\n" in self.composer.expanded()
        )

    def _slot_caret(self) -> tuple[int, int] | None:
        """The open picker's caret, at the end of its filter row (its last render's), or the history search's, at
        the end of its query; None with neither open.

        A question answered by picking has none: no key types anywhere there.
        """
        if self.slot is not None:
            return None
        picker = self.picker or self.rewind_picker or self.model_picker or self.search
        return picker.caret if picker is not None else None

    def _picker_keys(self) -> tuple[str, ...]:
        """The open picker's or search's keys, said on the info line in place of the composer's; () with neither open."""
        if self.picker is not None:
            return SESSION_PICKER_KEYS
        if self.launch_picker is not None:
            return LAUNCH_PICKER_KEYS
        if self.search is not None:
            return SEARCH_HINTS
        if self.rewind_picker is not None:
            return REWIND_PICKER_KEYS
        return MODEL_PICKER_KEYS if self.model_picker is not None else ()

    def _esc_interrupts(self) -> bool:
        """Whether the working row offers Esc for the interrupt: Esc interrupts the running turn now, nothing else
        taking it (`_escape`, and what has the keys), and no interrupt is on its way yet.

        So the screen gives Esc one meaning: a question, a picker, the search, the agent list, a picked steer or
        rewind, the `@` menu and a draft each take it. While `interrupting…` shows, Esc still asks again.
        """
        return (
            self._busy() and self._composer_open() and self.list_selected is None and not self.path_items
            and self.agent_steer is None and self.rewind is None and self.tell_draft is None
            and not self.composer.text and not self.interrupting
        )

    # ── subagents ──

    def _spinner_frame(self) -> int:
        """The frame every spinner and sweep shows now; the first, always, with reduced motion."""
        return int(self.clock() / TICK_SECONDS) if self.motion else 0

    def _tick_seconds(self) -> float:
        """How often the loop paints while something moves: faster while the working glow's light goes round, so it
        glides (`edge_glow.TICK_SECONDS`); the spinners still step by `TICK_SECONDS`."""
        if self._edge_live():
            return EDGE_TICK_SECONDS
        return TICK_SECONDS if self.motion else REDUCED_TICK_SECONDS

    @property
    def keyboard_protocol(self) -> bool:
        """Whether Ctrl+Enter reaches the TUI apart from Enter: the terminal answered the kitty keyboard query with
        the flag pushed on, or a key has arrived as a CSI u or modifyOtherKeys report.

        Asking the terminal for those reports is not enough, since a terminal
        on the list can ignore the request and send Ctrl+Enter as Enter. So
        the row under the queued prompts names Ctrl+J, which every terminal
        sends apart from Enter, until one of those, and Ctrl+Enter from then
        on: from the first frame on a terminal that answers the query.
        """
        return self.decoder.protocol_reported

    def _sticky_needed(self, above: int) -> bool:
        """Whether the sent prompt needs echoing above the composer: only once it has scrolled off.

        `above` is how many screen rows lie above the live region. Everything
        there is transcript, so while the rows printed from the prompt's first
        row on still fit there, the prompt itself is on screen and an echo
        would only repeat it.
        """
        if not (self._busy() and self.sticky.strip()):
            return False
        return self.flushed_since_prompt > above

    def _tail(self, cols: int) -> list[Line]:
        now = self.clock()
        # Never more than the screen; running tools' marks pulse unless motion is reduced.
        lines = self.transcript.live_lines(cols, self.theme, max_rows=self.size[1], now=now if self.motion else None,
                                           glint=self._aura_moves())
        if not lines and self.transcript.taken_any:
            lines = [()]  # the spacer a block opens with, here between the transcript and the region under it
        # A blank row above the working row, as between two blocks; the frame drops it first when rows are short.
        self.tail_spacer = self._busy() and bool(lines) and bool(lines[-1])
        if self.tail_spacer:
            lines.append(())
        if self._busy() and self.waiting_since is not None:
            # The turn waits on the person: no spinner, and one clock, the wait's.
            waited = elapsed_text(now - self.waiting_since)
            row = (Span(WAITING_GLYPH, self.theme.user), Span(STATE_WAITING, self.theme.text),
                   Span(f" ({waited})", self.theme.muted))
            lines.append(truncate_line(row, cols))
        elif self._busy() and self.interrupting:
            elapsed = elapsed_text(now - (self.busy_since or now))
            written = f" · ↓{compact_count(self.turn_shown)} tokens" if self.turn_shown else ""
            row = (Span(WORKING_GLYPHS[0], self.theme.warn), Span(" "), Span(INTERRUPTING, self.theme.warn),
                   Span(f" ({elapsed}{written})", self.theme.muted))
            lines.append(truncate_line(row, cols))
        elif self._busy():
            # The verb slot keeps Hermes' spinner verb (the last one this turn while a status says more); a status it
            # reports (`🧠 OMH — recalled 4 memories`) goes after the facts, dim, and is the first to give way.
            spun = working_verb(self.transcript.activity) if spinner_shaped(self.transcript.activity) else ""
            self.spinner_verb = spun or self.spinner_verb
            verb = self.spinner_verb or WORKING_VERB
            said = working_verb(self.transcript.status) or ("" if spun else working_verb(self.transcript.activity))
            text = f"{verb}…"
            if self.transcript.moa:
                text = f"{text} · {self.transcript.moa}"
            frame = self._spinner_frame()
            elapsed = elapsed_text(now - (self.busy_since or now))
            written = f"↓{compact_count(self.turn_shown)} tokens" if self.turn_shown else ""
            effort = ""
            if self.effort in contract.REASONING_LEVELS and self.effort != "none":  # `none` is thinking off
                effort = THINKING_EFFORT.format(self.effort)
            interrupt = INTERRUPT_HINT if self._esc_interrupts() else ""  # else Esc means something else now
            lead = (Span(WORKING_GLYPHS[frame % len(WORKING_GLYPHS)], self.theme.accent), Span(" "),
                    *working_spans(text, frame, self.theme))
            # A narrow row drops whole facts, the effort first (the info line says it where it has room), then the
            # tokens, the time, and the interrupt last; only a verb too long for the row alone is cut at the edge.
            row: Line = lead
            status = (Span(f" · {said}", self.theme.faint),) if said else ()
            for facts, tail in (((elapsed, written, effort, interrupt), status), ((elapsed, written, effort, interrupt), ()),
                                ((elapsed, written, interrupt), ()), ((elapsed, interrupt), ()), ((interrupt,), ())):
                joined = " · ".join(fact for fact in facts if fact)
                candidate = (*lead, *((Span(f" ({joined})", self.theme.muted),) if joined else ()), *tail)
                if line_width(candidate) <= cols:
                    row = candidate
                    break
            lines.append(truncate_line(row, cols))
            tip = self._tip_line(cols)
            if tip is not None:
                lines.append(tip)
        return lines

    def _working_rows(self) -> int:
        """The tail's last rows that say a turn runs, as `_tail` draws them: the working (or waiting, or
        interrupting) row, and the tip under the working row from TIP_MIN_ROWS rows. The agent view leaves the tail
        these (`layout.allocate`'s `tail_floor`), so a short terminal never loses the row saying a turn runs."""
        if not self._busy():
            return 0
        return 1 + int(self.size[1] >= TIP_MIN_ROWS and self.waiting_since is None and not self.interrupting)

    def _tip_line(self, cols: int) -> Line | None:
        """The working row's tip, `  ⎿  Tip: …`, the same all turn and the next one in TIPS the turn after; None on a
        terminal under TIP_MIN_ROWS rows. CYCLE_TIP reads HERMES_OWN_CYCLE_TIP while Hermes has approvals off on its own.

        It is the tail's last row, and the region gives the slot (a question, a
        picker, a menu, the plan) and the agent view their rows before the tail's,
        so the tip takes a row from the transcript above it, never from them;
        and it stays while they open, so the rows under it do not move.
        """
        if self.size[1] < TIP_MIN_ROWS:
            return None
        if self.tip_turn != self.busy_since:
            self.tip_turn, self.tip_index = self.busy_since, self.tip_index + 1
        tip = TIPS[self.tip_index % len(TIPS)]
        if tip == CYCLE_TIP and self.approvals_off_by_hermes:
            tip = HERMES_OWN_CYCLE_TIP
        return truncate_line(
            (Span(OUTPUT_INDENT), Span(OUTPUT_MARK, self.theme.dim), Span(f"Tip: {tip}", self.theme.hint)), cols
        )

    def _slot_lines(self, cols: int, rows: int) -> list[Line]:
        """The slot's rows; with the composer hidden it has the composer frame's rows too (`layout.choice_cap`)."""
        cap = choice_cap(rows, cols) if self._composer_hidden() else slot_cap(rows, cols)
        self.menu_under = []
        self.panel_shown = False  # the plan panel is in the slot (`_menu_or_panel_lines`): it gets its blank rows
        if self.slot is not None:
            cap = max(cap, 1)  # on a tiny terminal a question answered with text keeps a row for its label (`allocate`)
        if cap <= 0:
            return []
        # The info line says a question's or a picker's keys at every height; their rows do not.
        if self.slot is not None:
            return self.slot.lines(cols, self.theme, cap, waiting=len(self.waiting_requests))
        if self.launch_picker is not None:
            shown = [] if self.card_state == CARD_LIVE else self._launch_preview(cols)
            return self.launch_picker.lines(cols, self.theme, cap, self._launch_swatches(), shown)
        if self.picker is not None:
            return self.picker.lines(cols, self.theme, cap, self.wall_clock())
        if self.search is not None:
            return self.search.lines(cols, self.theme, cap)
        if self.rewind_picker is not None:
            return self.rewind_picker.lines(cols, self.theme, cap, self.wall_clock())
        if self.model_picker is not None:
            return self.model_picker.lines(cols, self.theme, cap)
        # Nothing has the keys, or the agent list under the info line has them (the slot keeps its rows then, so
        # nothing moves): the background-process row takes the slot's last row, right above the composer's top
        # rule, the `waiting for the image…` row above it while a submit is held for a paste, the queued prompts the
        # rows above that, Hermes' notification the row above them, Hermes' standing goal
        # the row above that, and the menu or the plan gets the rows left. A question or the picker hides them,
        # since Up then does not edit the queue. With one row, the queue keeps it: its `↑ edit` says what Up does.
        found = self._background_line(cols)
        background = [found] if found is not None and (cap > 1 or not self.queued) else []
        hint = QUEUE_HELD_HINT if self.queue_held else QUEUE_EDIT_HINT
        send_now = self._steer_keys_live() and self._queue_head_steers()
        below = SEND_NOW_HINT.format(key=SEND_NOW_KEYS[self.keyboard_protocol]) if send_now else ""
        found = self._image_wait_line(cols)
        waiting = [found] if found is not None and cap > len(background) else []
        queue = queue_lines([line.shown or line.text for line in self.queued], cols,
                            cap - len(background) - len(waiting), self.theme, hint, below)
        taken = len(background) + len(waiting) + len(queue)
        notice = [self.notification.line(cols, self.theme)] if self.notification and cap > taken else []
        shown = goal_line(self.goal, cols, self.theme)
        goal = [shown] if shown is not None and cap > taken + len(notice) else []
        menu = self._menu_or_panel_lines(cols, cap - taken - len(notice) - len(goal))
        if self.menu_below:  # the menu goes under the composer, and the panel stays away as it does for the menu
            self.menu_under, menu = menu, []
            self.panel_shown = False
        return menu + goal + notice + queue + waiting + background

    def _menu_or_panel_lines(self, cols: int, cap: int) -> list[Line]:
        if cap <= 0:
            return []
        rows = self._menu_rows()
        if rows:
            return _menu_lines(rows, min(self.menu_index, len(rows) - 1), cols, cap, self.theme)
        payload = self.hud.payload if self.hud is not None else None
        if payload is None:
            return []
        show_plan = not self.retired_plan or plan_text(payload) != self.retired_plan
        lines = panel_lines(
            payload, cols, cap, self.theme, self.wall_clock(), received_at=self.hud.received_at,
            show_agents=False, show_graph=False,  # the agent view under the info line draws them
            show_plan=show_plan,
            motion=self.motion,
            color_depth=self.color_depth,
            plan_folded=self.plan_folded,
            fold_key=PLAN_FOLD_KEY,
        )
        self.panel_shown = bool(lines)
        self.plan_room_collapsed = show_plan and plan_room_collapsed(payload, cap)
        return lines

    def _context_style(self) -> Style:
        percent = self.context_percent if self.context_percent is not None else 0.0
        if percent >= CONTEXT_BAD_PERCENT:
            return self.theme.error
        return self.theme.warn if percent >= CONTEXT_WARN_PERCENT else self.theme.muted

    def _info_right(self) -> tuple[Line, ...]:
        """The info line's right side, composed again only when something it shows changed (a spinner tick changes nothing).

        Its forms are the same at every width; `info_line` picks the one that fits.
        """
        shown = (self.model, self.context_percent, self.effort, self._busy(), self.slot is not None, self.session_title)
        held = self.info_held
        if held is not None and held[0] == shown and held[1] is self.theme and held[2] is self.hud:
            return held[3]
        forms = self._compose_info_right()
        self.info_held = (shown, self.theme, self.hud, forms)
        return forms

    def _compose_info_right(self) -> tuple[Line, ...]:
        """The right side's forms, longest first: the session's title, the HUD's chips, the model, the context and the
        effort, then less.

        The title (Hermes' `session.title`, cut to `INFO_TITLE_CELLS`) goes
        first; the model then shortens (`model_forms`), then goes, then the
        effort, then the context; the HUD's chips (`hud_chips`: a repeating
        call, the tool calls in flight) go last. The context turns warn from
        `CONTEXT_WARN_PERCENT` full and error from `CONTEXT_BAD_PERCENT`.
        """
        payload = self.hud.payload if self.hud is not None else None
        chips = list(hud_chips(payload, self.theme, turn_runs=self._busy(), question_waits=self.slot is not None))
        percent = self.context_percent
        context: Line = (Span(f"ctx {percent:.0f}%", self._context_style()),) if percent is not None else ()
        effort: Line = (Span(effort_words(self.effort), self.theme.muted),)
        models: list[Line] = [(Span(name, self.theme.muted),) for name in model_forms(self.model)]
        fields = [[*chips, model, context, effort] for model in models]
        fields += [[*chips, context, effort], [*chips, context], chips]
        forms: list[Line] = []
        for parts in fields:
            joined: Line = ()
            for part in (part for part in parts if part):
                joined += ((Span(INFO_SEPARATOR, self.theme.dim),) if joined else ()) + part
            if joined and joined not in forms:
                forms.append(joined)
        if self.session_title:
            title: Line = (Span(truncate(self.session_title, INFO_TITLE_CELLS), self.theme.muted),)
            forms.insert(0, (*title, Span(INFO_SEPARATOR, self.theme.dim), *forms[0]) if forms else title)
        return tuple(forms)


# ── entry point ───────────────────────────────────────────────────────────


def _holds_cursor_report(data: bytes) -> bool:
    """Whether `data` holds a cursor position report: `ESC[`, a row, `;`, a column and `R`."""
    start = data.find(CURSOR_REPORT_START)
    while start >= 0:
        end = data.find(CURSOR_REPORT_FINAL, start)
        if end < 0:
            return False
        row, separator, column = data[start + len(CURSOR_REPORT_START) : end].partition(b";")
        if separator and row.isdigit() and column.isdigit():
            return True
        start = data.find(CURSOR_REPORT_START, start + 1)
    return False


def _exit_on_signal(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


def _install_exit_signals() -> dict[int, Any]:
    """Route `EXIT_SIGNALS` through SystemExit; the handlers they replace."""
    previous: dict[int, Any] = {}
    for name in EXIT_SIGNALS:
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, _exit_on_signal)
        except ValueError:
            break  # handlers can only be installed from the main thread
    return previous


def _restore_signals(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler if handler is not None else signal.SIG_DFL)


def _say(stream: TextIO, text: str) -> None:
    """One line to the shell, after the terminal is restored; gateway text in it is cleaned of escapes and controls."""
    stream.write(clean_text(text) + "\n")
    stream.flush()


class _Told:
    """`main`'s stderr, keeping what it said there: a fallback hands that to `omh` (`request_fallback`).

    Hermes' own TUI, which `omh` opens next, clears the screen those lines
    were on, so `omh` says them again once it closes.
    """

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.lines: list[str] = []

    def write(self, text: str) -> int:
        self.lines.append(text)
        return self.stream.write(text)

    def flush(self) -> None:
        self.stream.flush()

    def said(self) -> str:
        return "".join(self.lines)


def _start_gateway(client: GatewayClient, stderr: TextIO) -> Event | None:
    """The gateway's ready event, or None after saying why it did not start."""
    try:
        return client.start()
    except GatewayUnavailable as error:
        _say(stderr, f"omh: the Hermes gateway did not start: {error}")
        for line in error.stderr_tail[-STARTUP_TAIL_LINES:]:
            _say(stderr, f"  {clean_text(line)}")  # the gateway's own text: no escape reaches the shell
    except GatewayCallError as error:
        _say(stderr, f"omh: the Hermes gateway refused the OMH TUI: {error}")
    return None


def _run(
    client: GatewayClient,
    environ: Mapping[str, str],
    stderr: _Told,
    open_terminal: Callable[[], TerminalLike],
    make_poller: Callable[[str | None, str | None], PollerLike],
    make_client: Callable[..., GatewayClient] | None = None,
    make_git: Callable[[str], GitWatcher] = GitWatcher,
) -> int:
    """Start the gateway, open the session, then run the loop on the raw terminal; the exit code.

    `make_client` spawns a gateway again after a crash (`App._respawn_gateway`).
    A session the person closed exits `CLOSED_EXIT` rather than 0 when `omh`
    launched the TUI (`SESSION_FILE_ENV` set): `omh` prints the exit card,
    Hermes' launcher prints nothing, and the shell still sees 0.
    """
    ready = _start_gateway(client, stderr)
    if ready is None:
        return request_fallback(environ, stderr.said())
    terminal = open_terminal()
    app = App(
        terminal,
        client,
        environ,
        poller=make_poller(environ.get("OMH_HOME") or None, environ.get("HERMES_HOME") or None),
        theme=initial_theme(ready.payload, environ.get("OMH_HOME") or None),
        make_client=make_client,
        # The session's directory as the launcher names it; with none named, no branch (never the TUI's own cwd).
        # TERMINAL_CWD is the attach entry's own fallback for the session directory (`gateway_attach`).
        git=make_git(cwd) if (cwd := environ.get("HERMES_TUI_CWD") or environ.get("HERMES_CWD")
                              or environ.get("TERMINAL_CWD")) else None,
    )
    try:
        app.startup()
    except (GatewayCallError, GatewayTimeout, GatewayUnavailable) as error:
        _say(stderr, f"omh: the OMH TUI could not open a Hermes session: {error}")
        return request_fallback(environ, stderr.said())
    try:
        with terminal:
            background, typed, row = terminal.query_background()
            app.adopt_background(background, environ)
            # Started: the shell's rows and the launcher's warnings are pushed off the screen and erased with the scrollback.
            app.clear_launch_screen(row)
            code = app.run(typed)
    finally:
        if app.client is not client:  # a gateway spawned after a crash; the caller reaps the first one
            app.client.close(grace=CLOSE_GRACE_SECONDS, terminate_grace=TERMINATE_GRACE_SECONDS)
    if app.farewell:
        _say(stderr, app.farewell)
    return CLOSED_EXIT if code == 0 and environ.get(SESSION_FILE_ENV) else code


def main(
    environ: Mapping[str, str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    open_terminal: Callable[[], TerminalLike] | None = None,
    make_client: Callable[..., GatewayClient] = GatewayClient,
    make_poller: Callable[[str | None, str | None], PollerLike] = HudPoller,
) -> int:
    """Start the OMH TUI and return its exit code (`FALLBACK_EXIT` when it could not start)."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = _Told(sys.stderr if stderr is None else stderr)
    if not terminal_supported(stdin, stdout, environ):
        _say(stderr, "omh: this terminal cannot run the OMH TUI; opening Hermes' own terminal instead.")
        return request_fallback(environ, stderr.said())
    if attach_refused(environ):
        _say(stderr, attach_message(environ))
        return 1
    try:
        client = make_client(gateway_spawn(environ))
    except GatewayUnavailable as error:
        _say(stderr, f"omh: the Hermes gateway did not start: {error}")
        return request_fallback(environ, stderr.said())
    previous_handlers = _install_exit_signals()
    try:
        # The terminal picks its key reports from the environment the TUI was given (TERM_PROGRAM and kin).
        return _run(
            client, environ, stderr, open_terminal or (lambda: Terminal(environ=environ)), make_poller, make_client
        )
    except KeyboardInterrupt:
        # Ctrl+C is a signal, not a key, until the terminal goes raw: while the gateway starts
        # and the session opens. The child is reaped below either way.
        _say(stderr, "omh: the OMH TUI was interrupted.")
        return INTERRUPTED_EXIT
    finally:
        # The screen has settled and the terminal is the shell's again; only now wait on the child.
        try:
            client.close(grace=CLOSE_GRACE_SECONDS, terminate_grace=TERMINATE_GRACE_SECONDS)
        finally:
            _restore_signals(previous_handlers)
