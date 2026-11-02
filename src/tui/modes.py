"""The OMH TUI's input modes (normal, accept, plan) and reasoning effort, mixed into `App`.

Input modes: Shift+Tab cycles normal, accept and plan. Accept is Hermes'
per-session yolo, so entering and leaving it are `config.set` calls that
always name this session and an explicit value and never a `scope`; the mode
shown changes only once Hermes confirms it for this session, an answer that
confirms anything else is treated as a failure and followed by an explicit
off (accept is shown again if that off is not confirmed either: approvals
may be off), and `session.info` corrects what is shown (one saying approvals
are on within `YOLO_SETTLE_SECONDS` of a confirmed on waits for the next: it
may be a snapshot Hermes took before the switch). With approvals off Hermes
sends no approval request, so the TUI still answers none. Plan is the
TUI's own flag, apart from what accept shows: a prompt typed while it is on
goes as `/plan <text>`. When Hermes has approvals off on its own (an off it
confirmed did not end them, or they were off without the TUI turning them
on), accept stays shown and Shift+Tab turns only plan on and off, sending
nothing.
Ctrl+T and `/effort <level>` set the session's reasoning effort the same way
(`config.set` with the session id); the level shown is the one Hermes
confirmed or reports in `session.info`.

The info line under the composer is drawn here too (`info_line`), since its
left side starts with the mode's label and the agent count starts after it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import json
from typing import Any

from . import gateway_contract as contract
from .frame import MODE_ACCEPT, MODE_ACCEPT_PLAN, MODE_NORMAL, MODE_PLAN, MODE_SHELL
from .keys import CHAR, TAB, Key, Paste
from .style import Line, Span, Style
from .theme import KIND_FAMILIES, Theme
from .transcript import NOTICE_ERROR, NOTICE_WARN, as_text
from .width import cell_width, line_width, truncate_line

# Said by every call that needs a session when none is open yet; it lives here because `ModesMixin`
# says it too, and `app` imports this module.
NO_SESSION_NOTICE = "No session is open yet; try again in a moment."

# The info line under the composer. Its left side is the badge, the branch, the background-process row, the mode's
# label, the agent count and the keys that matter now (none in the normal mode between turns: the launch card names
# `?`); its right side is what `App._info_right` gives (title, model, context, effort), cut down first when the line is
# narrow (`info_line`).
# After accept's or plan's label: what Shift+Tab does next. `{cycle}` is CYCLE_WORDS while the key walks normal, accept
# all and plan; while Hermes has approvals off on its own it turns plan on and off and nothing else (`HERMES_OWN_CYCLE`).
MODE_HINTS = (" (⇧⇥ {cycle})", "")
CYCLE_WORDS = "to cycle"
HERMES_OWN_CYCLE = {MODE_ACCEPT: "plan", MODE_ACCEPT_PLAN: "plan off"}
EFFORT_KEY = "ctrl+t effort"  # the right side's effort while Hermes has reported none
ACCEPT_LABEL = "⏵⏵ accept all on"
PLAN_LABEL = "⏸ plan mode on"
SHELL_LABEL = "! shell (not sent to the model)"
# Each label's shorter forms, for a line where what the next key does would not fit beside the full words.
ACCEPT_LABELS = (ACCEPT_LABEL, "⏵⏵ accept", "⏵⏵")
PLAN_LABELS = (PLAN_LABEL, "⏸ plan", "⏸")
SHELL_LABELS = (SHELL_LABEL, "! shell", "!")
SHELL_HINT = " · enter runs it in Hermes' shell, 30 s at most"
INFO_GAP = 3  # the fewest blank cells between the left side and the right side
BADGE_GAP = 2  # the blank cells between the badge, at the left end, and what follows it
LABEL_SEPARATOR = " · "  # between the mode's label, the agent count and the hint on the info line
INFO_SEPARATOR = " · "  # between the right side's fields

# Accept mode is Hermes' per-session yolo. The TUI sends these words; Hermes answers "1" or "0".
YOLO_ON = "on"
YOLO_OFF = "off"
YOLO_ANSWERS = {True: "1", False: "0"}
# Hermes builds `session.info` on other threads too, reading yolo before its slow probes, so one snapshot
# taken before a confirmed on can arrive after it. For this long after a confirmed on, a `session.info`
# saying approvals are on does not take accept off the info line by itself.
YOLO_SETTLE_SECONDS = 2.0
ACCEPT_REFUSED_NOTICE = (
    "Hermes did not turn approvals off for this session alone ({}). "
    "Accept all stays off, and the OMH TUI asked Hermes to switch it back off."
)
ACCEPT_STUCK_NOTICE = "Hermes did not confirm that this session asks for approvals again ({}). Accept all may still be on."
# Said once per session, the first time Shift+Tab meets approvals Hermes turned off on its own.
HERMES_APPROVALS_NOTICE = (
    "Hermes itself has approvals off for this session: its approvals.mode is off, it was started with --yolo, "
    "or /yolo turned them off. Accept all stays shown, and Shift+Tab now turns plan mode on and off "
    "without changing Hermes' setting."
)
SWITCH_BACK_FAILED_NOTICE = (
    "Hermes did not confirm the switch back either ({}), so approvals may be off: accept all is shown again, "
    "and Shift+Tab asks Hermes to turn them back on."
)
LEFT_YOLO_NOTICE = (
    "Hermes did not confirm that the session you left asks for approvals again ({}). "
    "Its approvals may stay off while this Hermes gateway runs."
)

# Ctrl+T steps through these; `/effort` takes any level in `contract.REASONING_LEVELS`.
EFFORT_CYCLE = ("low", "medium", "high", "xhigh", "max")
# What the info line says while Hermes reports no level for the session: none is configured, so each route sends its
# own default or none at all (Hermes 6c61c3e27d `_session_info`: "" = provider default). No level Ctrl+T steps from.
EFFORT_DEFAULT = "default"
EFFORT_REFUSED_NOTICE = "Hermes did not set the reasoning effort to {} ({}); it stays as shown."


def mode_label(mode: str, theme: Theme, form: int = 0) -> Line:
    """The mode's own words on the info line: accept and plan have them, both when both are on, normal has none.

    `form` picks a shorter form (`ACCEPT_LABELS`, `PLAN_LABELS`, `SHELL_LABELS`): 1 the short words, 2 the glyph.
    """
    accept: Line = (Span(ACCEPT_LABELS[form], replace(theme.mode_accept, bold=True)),)
    plan: Line = (Span(PLAN_LABELS[form], replace(theme.mode_plan, bold=True)),)
    if mode == MODE_ACCEPT_PLAN:
        return (*accept, Span(LABEL_SEPARATOR, theme.hint), *plan)
    if mode == MODE_SHELL:
        return (Span(SHELL_LABELS[form], theme.kinds[KIND_FAMILIES.index("shell")]),)  # the shell family's hue
    return {MODE_ACCEPT: accept, MODE_PLAN: plan}.get(mode, ())


def editing_label(editing: str, mode: str, theme: Theme, form: int = 0) -> Line:
    """The mode's label (`mode_label`), after vim mode's editing mode (`INSERT` or `NORMAL`, "" with vim mode off).

    The editing mode has one form: it stays whole while the mode's label shortens.
    """
    own = mode_label(mode, theme, form)
    if not editing:
        return own
    word: Line = (Span(editing, replace(theme.text, bold=True)),)
    return (*word, Span(LABEL_SEPARATOR, theme.hint), *own) if own else word


def chip_column(mode: str, theme: Theme, editing: str = "") -> int:
    """The info line cell the agent count starts on: after the mode's label and a separator, or the line's first."""
    label = editing_label(editing, mode, theme)
    return line_width(label) + cell_width(LABEL_SEPARATOR) if label else 0


def configured_effort(config_result: Mapping[str, Any]) -> str:
    """The effort `agent.reasoning_effort` sets, from a `config.get {key: "full"}` answer, read as Hermes 6c61c3e27d
    reads it (`hermes_constants.parse_reasoning_effort`): a level, `none` when thinking is off (`false`, `none`, an
    `{enabled: false}` form), `EFFORT_DEFAULT` when unset or not a level Hermes knows. "" where the answer cannot say:
    no config, or per-model overrides (`agent.reasoning_overrides`), which Hermes matches against the model itself.
    """
    config = config_result.get("config")
    agent = config.get(contract.CONFIG_AGENT, {}) if isinstance(config, Mapping) else None
    if not isinstance(agent, Mapping) or agent.get(contract.CONFIG_REASONING_OVERRIDES):
        return ""
    raw = agent.get(contract.CONFIG_REASONING_EFFORT)
    if isinstance(raw, Mapping):
        raw = False if raw.get("enabled") is False else raw.get("effort")
    if raw is False:
        return "none"
    word = str(raw).strip().lower() if isinstance(raw, str) else ""
    if word in ("none", "false", "disabled"):
        return "none"
    return word if word in contract.REASONING_LEVELS else EFFORT_DEFAULT


def effort_words(effort: str) -> str:
    """`effort medium`, or `ctrl+t effort` while Hermes has reported none: the effort on the info line's right."""
    return f"effort {effort}" if effort else EFFORT_KEY


def model_forms(model: str) -> tuple[str, ...]:
    """The model's names on the info line, longest first: as Hermes names it, its last path segment, then that
    segment without its first `-` word (`deepseek/deepseek-v4.1-flash` → `deepseek-v4.1-flash` → `v4.1-flash`).

    A form equal to the one before it is left out, and so is an empty one;
    the third is left out too when what is left starts with a digit, a bare
    version (`glm-5.3`, `gemini-4-argon`).
    """
    segment = model.rsplit("/", 1)[-1]
    head, dash, rest = segment.partition("-")
    forms: list[str] = []
    for form in (model, segment, rest if dash and head and rest and not rest[0].isdigit() else segment):
        if form and form not in forms:
            forms.append(form)
    return tuple(forms)


def default_hints(mode: str, cycle: str) -> tuple[str, ...]:
    """The info line's own words when nothing else is said: where Shift+Tab goes from accept or plan; none in the
    normal mode (the launch card names `?`, which still opens the list).

    Longest first; the last of accept's and plan's is empty, so a narrow line drops it whole.
    """
    if mode in (MODE_ACCEPT, MODE_PLAN, MODE_ACCEPT_PLAN):
        return tuple(form.format(cycle=cycle or CYCLE_WORDS) for form in MODE_HINTS)
    return ()


def info_line(
    *,
    mode: str,
    width: int,
    theme: Theme,
    right: Sequence[Line] = (),
    chip: Line = (),
    say: str | tuple[str, ...] = "",
    say_style: Style | None = None,
    cycle: str = "",
    badge: Sequence[Line] = (),
    branch: Sequence[Line] = (),
    background: Sequence[Line] = (),
    right_spare: int = 0,
    editing: str = "",
    notice: Sequence[Line] = (),
) -> Line:
    """The one line under the composer. Its left side is `badge` (`[⚚ OMH Native]`), `branch` (the git branch),
    `background` (the background-process row: `background.running_forms`), the mode's label (accept, plan, a shell
    line), the agent count and the keys that matter now, `BADGE_GAP` cells between the first four; its right side is
    the first of `right` (the title, the model, the context, the effort) that leaves room for the left side whole.
    `badge`, `branch`, `background` and `right` are forms, longest first. `notice` is the update notice's forms,
    longest first (`v4.0.5 available · omh update`, then `↑ v4.0.5`), said `BADGE_GAP` cells after the badge's first
    form, the one with the version: the longest only while the rest of the line is whole, the shortest for as long as
    the version is shown.

    What gives way, in order: the update notice's long form, first, since
    it is the least live of it all (owner, 2026-11-02), leaving its short
    form; then the first `right_spare` of the right side's forms (the
    session's title), then the background-process row (through its forms,
    then whole), then the rest of the right side (through its forms, then
    whole), then the badge's version and the notice's short form together
    (`badge`'s second form), then the branch's name (`branch`'s shorter
    forms), then
    the badge (to `[⚚ OMH]`, then `⚚`, then none),
    then the branch; the label, the agent count and what the next key
    does (a question's or a picker's way out) keep their words until all
    of those are gone, and only then shorten. So the row goes before the
    model, the context and the effort shorten, and a terminal too narrow
    for those shows none of it.

    `chip` is the count of the agents in the view under the line while there
    are any, after the label. `say`, when given, is what the next key
    will do (a rewind waiting to be sent, Esc's second press, a question's
    keys) and stands in for the hint, in `say_style`; given as forms, longest
    first. The first `say` form that fits whole is said, so a narrow line
    keeps the point rather than the start of the long one, and when none fits
    beside the label's words the label takes its short words, then its glyph
    alone, before the last form is cut; any other hint takes its longest form
    that fits, else its last, cut at the edge, after a label that takes its
    short words, then its glyph alone, when its own words do not fit. During
    a turn the line names no key for the turn: the working row offers the
    interrupt, and the queue's own row the send-now key. The label always
    survives, in some form, and the count after it. Accept and plan say where
    Shift+Tab goes next (`cycle`; CYCLE_WORDS when not given). In the normal
    mode between turns the left side is the badge and the branch alone.

    `editing` is vim mode's editing mode (`INSERT`, `NORMAL`; "" with vim mode
    off), said first in the label (`editing_label`), so it lasts as long as
    the label does and never shortens; in the normal mode it is the label.
    """
    forms = (say,) if isinstance(say, str) else say
    if any(forms):
        hints = tuple(forms)
    elif mode == MODE_SHELL:
        hints = (SHELL_HINT,)
    else:
        hints = default_hints(mode, cycle)

    def label_of(form: int) -> Line:
        own = editing_label(editing, mode, theme, form)
        return (*own, Span(LABEL_SEPARATOR, theme.hint), *chip) if chip and own else chip or own

    def placed(texts: Sequence[str], label: Line) -> list[str]:
        """The hint's forms as drawn after `label`: what the next key does after a separator, the rest glued on."""
        if any(forms):
            return [text if not label else LABEL_SEPARATOR + text for text in texts]
        if chip:
            return [LABEL_SEPARATOR + text.removeprefix(LABEL_SEPARATOR).strip() if text else "" for text in texts]
        return list(texts)

    whole = line_width(label_of(0)) + (cell_width(placed(hints, label_of(0))[0]) if hints else 0)

    def lead(*parts: Line) -> Line:
        """The badge, branch and background forms shown, `BADGE_GAP` cells after each but a last one nothing follows."""
        shown = [part for part in parts if part]
        gap = Span(" " * BADGE_GAP)
        joined: Line = ()
        for index, part in enumerate(shown):
            joined += (*part, *((gap,) if index < len(shown) - 1 or whole else ()))
        return joined

    def fits(left: int, side: Line) -> bool:
        return left + (INFO_GAP + line_width(side) if side else 0) <= width

    badges, branches, rows = list(badge) or [()], list(branch) or [()], list(background) or [()]
    sides = [*(form for form in right if form), ()]
    spare = min(right_spare, len(sides) - 1)
    # The notice's long form only while everything else is whole: it is the first thing to go. Its short form stays
    # beside the version, and goes with it.
    said = [form for form in notice if form] if badges[0] else []
    noticed = (*badges[0], Span(" " * BADGE_GAP), *said[0]) if said else ()
    versioned = (*badges[0], Span(" " * BADGE_GAP), *said[-1]) if len(said) > 1 else badges[0]
    tries = [(noticed, branches[0], rows[0], sides[0])] if noticed else []
    tries += [(versioned, branches[0], rows[0], side) for side in sides[: spare + 1]]
    tries += [(versioned, branches[0], form, sides[spare]) for form in [*rows[1:], ()]]
    tries += [(versioned, branches[0], (), side) for side in sides[spare + 1 :]]
    unversioned = badges[1] if len(badges) > 1 else badges[0]  # the version goes before the branch name is cut
    tries += [(unversioned, form, (), ()) for form in branches]
    tries += [(form, branches[-1], (), ()) for form in [*badges[2:], ()]]
    tries += [((), (), (), ())]
    shown_badge, shown_branch, shown_row, shown_right = next(
        (tried for tried in tries if fits(line_width(lead(*tried[:3])) + whole, tried[3])), tries[-1]
    )
    front = lead(shown_badge, shown_branch, shown_row)
    room = width - (line_width(shown_right) + INFO_GAP if shown_right else 0) - line_width(front)
    label = label_of(0)
    hint = ""
    if any(forms):
        for form in range(len(ACCEPT_LABELS)):
            label = label_of(form)
            said = placed(hints, label)
            fitting = [text for text in said if cell_width(text) <= room - line_width(label)]
            if fitting or not mode_label(mode, theme, form):
                break  # what the next key does outranks the label's words, which shorten while nothing fits
        hint = fitting[0] if fitting else said[-1]
    elif hints:
        label = next((label_of(form) for form in range(len(ACCEPT_LABELS)) if line_width(label_of(form)) <= room),
                     label_of(len(ACCEPT_LABELS) - 1))
        said = placed(hints, label)
        hint = next((text for text in said if cell_width(text) <= max(room - line_width(label), 0)), said[-1])
    rest = truncate_line(label, room) + truncate_line((Span(hint, say_style or theme.hint),), max(room - line_width(label), 0))
    left = truncate_line((*front, *rest), width)
    if not shown_right:
        shown_right = next((side for side in right if side and fits(line_width(left), side)), ())
    if not shown_right:
        return left
    return (*left, Span(" " * (width - line_width(left) - line_width(shown_right))), *shown_right)


def yolo_answer_problem(result: Mapping[str, Any], on: bool) -> str:
    """Why a `config.set yolo` answer does not confirm the switch that was asked for; "" when it does.

    The answer must carry the value asked for ("1" on, "0" off) and
    `scope: "session"`. Any other scope means Hermes wrote something wider
    (`scope: "global"` is the permanent `approvals.mode`), so it is a failure.
    The scope proves less than it reads, though: Hermes 6c61c3e27d answers
    `scope: "session"` from its sessionless branch too, the one that sets
    `HERMES_YOLO_MODE` for the whole gateway process (`_set_yolo` in
    `tui_gateway/methods_config_set.py`), so the answer cannot say which
    branch ran. What keeps the switch on one session is settled before the
    answer: every yolo call names this session, `gateway_contract.call_problem`
    refuses to send a `config.set` without a session id, and Hermes answers a
    session id it does not hold with 4001 instead of falling back to the
    process switch (`_SESSION_SCOPED_KEYS` in the same file).
    """
    scope, value = result.get("scope"), result.get("value")
    if scope != contract.CONFIG_SET_SESSION_SCOPE:
        return f"it answered scope {json.dumps(scope)}"
    if value != YOLO_ANSWERS[on]:
        return f"it answered value {json.dumps(value)}"
    return ""


class ModesMixin:
    """`App`'s input modes and reasoning effort.

    The state it reads and writes is set in `App.__init__`; `_request` and
    `_menu_rows` are `App`'s.
    """

    @property
    def mode(self) -> str:
        """What the info line shows: accept while approvals are off, plan while its flag is on."""
        if self.approvals_off:
            return MODE_ACCEPT_PLAN if self.plan_mode else MODE_ACCEPT
        return MODE_PLAN if self.plan_mode else MODE_NORMAL

    @property
    def approvals_off_by_hermes(self) -> bool:
        """Whether approvals are off on Hermes' own, not by the TUI's Shift+Tab: the key then turns plan on and off."""
        return self.approvals_off and not self.yolo_by_tui

    def _take_session_state(self, info: Mapping[str, Any]) -> None:
        """Hermes' own word on the session: its reasoning effort, and whether its approvals are off.

        Approvals off means accept is shown, on means it is not; the plan
        flag is the TUI's and stays as it is. Hermes reports yolo on for its
        own reasons too (`approvals.mode` off, `--yolo`, a `/yolo` typed to
        it), and then the info line says so as well.

        One `session.info` saying approvals are on, within
        `YOLO_SETTLE_SECONDS` of the TUI's confirmed on, is held instead: it
        may be a snapshot Hermes took before the switch and wrote after its
        answer. Hermes 6c61c3e27d has no per-session read to settle it with
        (`config.get` reads `approvals.mode`, the global setting, and nothing
        reads the session switch), so accept stays shown and the next
        `session.info` decides. The other way round needs no hold: approvals
        off is shown at once, since in doubt the info line shows accept.
        """
        effort = info.get(contract.SESSION_INFO_REASONING_EFFORT)
        if isinstance(effort, str):
            self.effort = effort or EFFORT_DEFAULT
            self.effort_said = True
        yolo = info.get(contract.SESSION_INFO_YOLO)
        if not isinstance(yolo, bool):
            return
        confirmed_at = self.yolo_confirmed_at
        settling = confirmed_at is not None and self.clock() - confirmed_at < YOLO_SETTLE_SECONDS
        if not yolo and self.yolo_by_tui and settling:
            self.yolo_confirmed_at = None  # held once: the next session.info decides
            return
        self.yolo_reported = self.approvals_off = yolo
        if not yolo:
            self.yolo_by_tui = False  # nothing has approvals off now, the TUI's own switch included

    def _mode_key(self, event: Key | Paste) -> bool:
        """Shift+Tab cycles the input mode; with a completion menu open it stays the no-op it was.

        Shift+Tab alone: a key report that adds Ctrl or Alt to it is another
        chord, and a chord that may turn approvals off is never a guess.
        """
        if event != Key(TAB, shift=True) or self._menu_rows():
            return False
        self._cycle_mode()
        return True

    def _cycle_mode(self) -> None:
        """normal → accept → plan → normal. Entering and leaving accept wait for Hermes; plan is the TUI's own flag.

        Approvals Hermes turned off on its own are not the TUI's to turn back
        on: then accept stays shown and the key turns plan on and off, with
        nothing sent.
        """
        if self.mode_request_open:
            return  # one change at a time: the mode shown is the last one Hermes confirmed
        if self.approvals_off_by_hermes:
            self.plan_mode = not self.plan_mode
            self._say_hermes_approvals()
        elif self.approvals_off:
            self._set_yolo(False)
        elif self.plan_mode:
            self.plan_mode = False
        else:
            self._set_yolo(True)

    def _say_hermes_approvals(self) -> None:
        if not self.hermes_approvals_said:
            self.hermes_approvals_said = True
            self.transcript.add_notice(HERMES_APPROVALS_NOTICE, NOTICE_WARN)

    def _set_yolo(self, on: bool) -> None:
        """Ask Hermes to turn this session's approvals off (`on`) or back on; accept, or plan, once it confirms.

        The only caller is Shift+Tab. The call always names the session and
        an explicit value: without a session Hermes would set the switch for
        the whole gateway process, and a blank value toggles whatever it finds.
        """
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        sid = self.sid
        self.mode_request_open = True
        self.yolo_reported = self.yolo_confirmed_at = None
        self._request(
            "config.set",
            {"key": "yolo", "session_id": sid, "value": YOLO_ON if on else YOLO_OFF},
            lambda result: self._on_yolo_answer(sid, on, yolo_answer_problem(result, on)),
            lambda error: self._on_yolo_answer(
                sid, on, f"{error.get('code')}: {as_text(error.get('message')) or 'refused'}"
            ),
        )

    def _on_yolo_answer(self, sid: str, on: bool, problem: str) -> bool:
        """Hermes answered a yolo call; `problem` says why the answer confirms nothing ("" when it does).

        A confirmed off moves on to plan. When Hermes still reports approvals
        off after it, they are Hermes' own: accept stays shown beside plan.
        """
        if sid != self.sid:
            return True  # that session was left meanwhile, and its switch with it
        self.mode_request_open = False
        if problem and on:
            # Whatever Hermes did, it was not "this session only": show accept off and ask for it explicitly.
            self.approvals_off = False
            self.mode_request_open = True  # the switch-back is a yolo call out too: possibly on until it is answered
            self.transcript.add_notice(ACCEPT_REFUSED_NOTICE.format(problem), NOTICE_ERROR)
            self._request(
                "config.set",
                {"key": "yolo", "session_id": sid, "value": YOLO_OFF},
                lambda result: self._on_switched_back(sid, yolo_answer_problem(result, False)),
                lambda error: self._on_switched_back(
                    sid, f"{error.get('code')}: {as_text(error.get('message')) or 'refused'}"
                ),
            )
        elif problem:
            self.transcript.add_notice(ACCEPT_STUCK_NOTICE.format(problem), NOTICE_ERROR)  # accept stays shown
        elif on:
            self.approvals_off = self.yolo_by_tui = True
            self.yolo_confirmed_at = self.clock()
        else:
            self.yolo_by_tui, self.plan_mode, self.approvals_off = False, True, bool(self.yolo_reported)
            if self.approvals_off:
                self._say_hermes_approvals()
        return True

    def _on_switched_back(self, sid: str, problem: str) -> bool:
        """The explicit off after an on Hermes did not confirm; `problem` says why this answer confirms nothing either.

        Unconfirmed, approvals may be off, so accept is shown again, as the
        TUI's own: Shift+Tab then asks for the off once more, and leaving the
        session sends one. Accept shown with approvals on costs nothing;
        normal shown with them off would hide that Hermes asks nothing.
        An answer for a session already left changes nothing and says
        nothing: leaving it counted the switch-back as possibly on and sent
        an off of its own, whose answer reports for it.
        """
        if sid != self.sid:
            return True
        self.mode_request_open = False
        if problem:
            self.transcript.add_notice(SWITCH_BACK_FAILED_NOTICE.format(problem), NOTICE_ERROR)
            self.approvals_off = self.yolo_by_tui = True
        return True

    # ── reasoning effort ──

    def _effort_key(self, event: Key | Paste) -> bool:
        """Ctrl+T steps the reasoning effort through `EFFORT_CYCLE` from the level shown, from low when it is at none
        of them (the provider's default, `EFFORT_DEFAULT`, is no step of it)."""
        if not isinstance(event, Key) or event.name != CHAR or not event.ctrl or event.alt or event.char != "t":
            return False
        current = self.effort_asked or self.effort
        step = EFFORT_CYCLE.index(current) + 1 if current in EFFORT_CYCLE else 0
        self._set_effort(EFFORT_CYCLE[step % len(EFFORT_CYCLE)])
        return True

    def _effort_command(self, arg: str) -> None:
        """`/effort <level>`: any level Hermes takes; alone, it names the level shown and the choices."""
        level = arg.strip().lower()
        levels = ", ".join(contract.REASONING_LEVELS)
        if level in contract.REASONING_LEVELS:
            self._set_effort(level)
        elif level:
            self.transcript.add_notice(f"No reasoning effort named {arg}. Levels: {levels}.", NOTICE_WARN)
        else:
            if self.effort == EFFORT_DEFAULT:
                now = "Hermes sets no reasoning effort for this session, so the provider's default applies."
            else:
                now = f"Reasoning effort {self.effort}." if self.effort else "Hermes reports no reasoning effort."
            self.transcript.add_notice(f"{now} /effort <level> sets it for this session. Levels: {levels}.")

    def _set_effort(self, level: str) -> None:
        """Ask Hermes for `level` in this session; the info line changes once Hermes confirms it."""
        if not self.sid:
            self.transcript.add_notice(NO_SESSION_NOTICE, NOTICE_WARN)
            return
        sid = self.sid
        self.effort_asked = level
        self._request(
            "config.set",
            {"key": "reasoning", "session_id": sid, "value": level},
            lambda result: self._on_effort_answer(sid, level, result.get("value")),
            lambda error: self._on_effort_answer(
                sid, level, None, f"{error.get('code')}: {as_text(error.get('message')) or 'refused'}"
            ),
        )

    def _on_effort_answer(self, sid: str, level: str, value: object, refusal: str = "") -> bool:
        """Hermes answered an effort call: its `value` is the level it set, or `refusal` says why it set none."""
        if sid != self.sid:
            return True  # that session was left meanwhile
        if self.effort_asked == level:
            self.effort_asked = ""
        if not refusal and value != level:
            refusal = f"it answered {json.dumps(value)}"
        if refusal:
            self.transcript.add_notice(EFFORT_REFUSED_NOTICE.format(level, refusal), NOTICE_WARN)
        else:
            self.effort, self.effort_said = level, True
        return True

    def _turn_off_yolo_set_here(self, sid: str) -> None:
        """Before leaving `sid`: an explicit yolo off for it, when the TUI turned yolo on there or a yolo call is out.

        Hermes clears a session's yolo as it closes it only when it owns the
        session's lifecycle, and never for a session a messaging gateway
        started (`tui_gateway/session_lifecycle.py`), so the switch the TUI
        set would outlive the TUI's attachment. Sent before `session.close`:
        Hermes runs both inline, in the order they arrive, and answers the id
        of a session it closed with 4001. An off for a call still out is
        harmless and lands after it. A refused off is a notice in whatever
        transcript is live when the answer comes; nothing waits for it, so a
        switch or an exit is never held up.
        """
        if not (self.yolo_by_tui or self.mode_request_open):
            return
        self.yolo_by_tui = self.mode_request_open = False  # sent once; the session is being left
        self._request(
            "config.set",
            {"key": "yolo", "session_id": sid, "value": YOLO_OFF},
            lambda result: self._on_left_yolo_off(yolo_answer_problem(result, False)),
            lambda error: self._on_left_yolo_off(f"{error.get('code')}: {as_text(error.get('message')) or 'refused'}"),
        )

    def _on_left_yolo_off(self, problem: str) -> bool:
        if problem:
            self.transcript.add_notice(LEFT_YOLO_NOTICE.format(problem), NOTICE_ERROR)
        return True
