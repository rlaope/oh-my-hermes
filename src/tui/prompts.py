"""The prompt slot: how the OMH TUI asks the person what Hermes asked.

A server-to-client request (an approval, a clarify question, a sudo password)
takes over the panel slot above the composer until it is answered, declined,
or withdrawn by the gateway. Three rules shape this module:

- Nothing is answered on the person's behalf. Every answer comes from a key
  they pressed or text they submitted; Esc or Ctrl+C sends the contract's
  decline frame (an explicit deny for approvals). Every deny the person gives
  an approval (Esc, Ctrl+C, `d`, `n`, Enter on deny) also asks the app to stop
  the running turn (`Answer.stops`). Allowing a command takes
  the arrows and then Enter: deny is the first row and selected, the
  narrowest allow sits under it, the selection does not wrap, no digit picks
  a choice, and a letter can only deny. An approval's last row denies too,
  but stops nothing: it asks the app to give the composer to what the person
  tells Hermes instead (`Answer.tell`). The app ignores every key for a
  moment after any slot opens, or its next question appears. A request the gateway
  withdraws itself (its own timeout, an interrupt) arrives as
  `request.cancel`, and the app closes the slot without answering.
- Nothing is left unanswered. A request the TUI cannot show is answered at
  once with its decline frame and a visible notice, because over stdio the
  gateway would otherwise wait out its whole deadline.
- Nothing typed into a masked prompt is kept: the slot holds no copy of the
  value after it builds the answer frame.

A question answered by picking (`PromptSlot.picking`: an approval, or a
clarify question with choices) lists its choices, each from a row of its own
and wrapped when long, the highlighted one marked `❯`, and the app hides the
composer while it is open. A clarify
question's last row opens a text field for an answer of the person's own
(Hermes' wording, "Other (type your answer)"); while that field is open the
composer is the field. Every slot row hangs off a `▌` bar, in the warn colour
for an approval and grey for anything else, so a question Hermes asked
never reads as panel or transcript text.

An approval shows its command one command per row (`command_risk`), the
ones that destroy something in full after a `▲`. Every command is listed when
they all fit. Only when they do not, and only when Hermes' description names a
risk `command_risk` found (so what Hermes flagged is one of the `▲` rows), do
the commands that change nothing (`Segment.foldable`, a closed allowlist) fold
into one `+ N other commands` row; every other one stays while rows allow, the
directory changes and assignments that aim a risky one first among them, and
no `▲` row is cut while another command's row shows. `command_risk` knows
far fewer patterns than Hermes, so when Hermes flagged something it does not
know, every command is listed and `_fit` cuts from the end with its marker.
Risks Hermes did not name get a `✦ OMH also sees:` row under its header.
Ctrl+O shows the command whole, as Hermes sent it (`whole_lines`). Each choice
has its icon and its tone (deny red, an allow green, always amber), and the
highlighted one sits on a band of its tone (`Theme.pick_*`). When rows run
short the spacing goes first, then the listing folds, then `_fit` cuts the
body from its end.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
import json
import os
import sys
from typing import Any

from . import command_risk
from . import gateway_contract as contract
from .keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, UP, Key, Paste
from .markdown import wrap_prefixed
from .style import Line, Span, Style, fill, is_fill
from .theme import CATCH_MARK, Theme
from .width import cell_width, line_width, truncate, truncate_line, wrap_line

# The order is the distance from safe: deny first (and selected), then the
# narrowest allow, then the broadest. `always` is Hermes' permanent allow:
# Hermes saves the command's pattern in its config (`command_allowlist`), so
# later commands like it run without asking. It is offered only when Hermes
# lists it (Hermes leaves it out where a permanent allow is refused, such as a
# command its smart approval flagged), and it takes the arrows and Enter like
# every allow. A request that lists no choices gets the ones that end with
# this session.
APPROVAL_ORDER = ("deny", "once", "session", "always")
APPROVAL_CHOICES = ("deny", "once", "session")
# Last on every approval, as Claude Code puts its "No, and tell Claude" row last: it sends the explicit deny, and the
# app then gives the composer to what the person tells Hermes instead (`App._open_tell`).
APPROVAL_TELL = "tell"
_APPROVAL_LABELS = {
    "once": "allow once",
    "session": "allow this session",
    "always": "always allow {what} (Hermes saves it)",
    "deny": "deny",
    APPROVAL_TELL: "no, and tell Hermes what to do instead",
}
ALWAYS_WHAT = "commands like this"  # `always`'s label for a request with no description
# Each choice's icon and tone: the theme role its row is drawn in, and `pick_<tone>` when highlighted.
APPROVAL_TONES = dict(zip((*APPROVAL_ORDER, APPROVAL_TELL),
                          (("✗", "error"), ("✓", "ok"), ("✓", "ok"), ("★", "warn"), ("✎", "muted"))))
RISK_MARK = "▲ "
ALSO_SEES = " also sees: "
OTHER_COMMANDS = "    + {count} other command{s} "
OTHER_HINT = " · ctrl+o shows all"
# How many steps an approval's `+ N other commands` row folds by, each more when rows run short (`_command_bodies`).
FOLD_STEPS = 4
RULE_CELLS = 60  # the faint rule between the command and the choices, at most
# A letter can only deny. Allowing takes the arrows and Enter, so a key typed
# for the composer as the slot opens can never run a command.
_DENY_KEYS = frozenset("dn")
# The keys that pick a clarify choice. `str.isdigit` also admits "²" or "٣", which `int` rejects.
CHOICE_DIGITS = "123456789"
# The last row of a clarify question's choices: it opens a text field (Hermes' Ink TUI, `prompt.clarify.other`).
CLARIFY_OTHER = "Other (type your answer)"
# A question the TUI asks itself (the app's model confirmation) sets this to True: its choices are the only answers,
# so it has no text field's row. Hermes' own questions never carry it.
CLOSED_CHOICES = "omh_closed_choices"
# A multi-select question (`multi_select`): a box before each choice, and a note after the question.
TICKED, UNTICKED = "[x] ", "[ ] "
MULTI_NOTE = " (choose one or more)"
SLOT_BAR = "▌ "
CHOICE_MARK = "❯ "
# Each question's keys, longest first, for the info line while it is open: Esc then has one meaning on the screen.
APPROVAL_KEYS = (
    "↑↓ pick · enter confirms · d or esc denies and stops",
    "↑↓ pick · enter confirms · esc denies and stops",
    "↑↓ · esc denies and stops",  # short enough to leave the agent count its room on a narrow line
    "esc denies and stops",
)
# The same with no turn running (a subagent that outlived the turn asks): a deny then interrupts nothing.
APPROVAL_IDLE_KEYS = tuple(form.removesuffix(" and stops") for form in APPROVAL_KEYS)
CLARIFY_CHOICE_KEYS = (
    "↑↓ or 1-9 · enter picks · type to answer · esc cancels", "↑↓ enter picks · esc cancels", "esc cancels"
)
CLARIFY_CLOSED_KEYS = ("↑↓ or 1-9 · enter picks · esc cancels", "↑↓ enter picks · esc cancels", "esc cancels")
CLARIFY_FIELD_KEYS = (
    "type your answer · enter sends · ↑↓ back to the choices · esc cancels",
    "enter sends · ↑↓ choices · esc cancels",
    "esc cancels",
)
CLARIFY_MULTI_KEYS = (
    "↑↓ · space or 1-9 ticks · enter sends · type to answer · esc cancels",
    "space ticks · enter sends · esc cancels",
    "esc cancels",
)
CLARIFY_TEXT_KEYS = ("type an answer · enter sends · esc cancels",)
VALUE_KEYS = ("type it · enter sends · esc declines",)
# A question the slot cannot show whole says that Ctrl+O shows it (`App._question_view`), longest form that fits
# first: on a row of its own (counting the command's rows left out, when any are), or at the end of the last row
# the cut leaves, in a form that leaves that row whole if one does.
MORE_ROWS = ("  … +{count} more line{s} · ctrl+o shows all", "  … +{count} · ctrl+o", "  … ctrl+o")
MORE_ANY_ROWS = ("  … ctrl+o shows all", "  … ctrl+o")
MORE_FORMS = (" … ctrl+o shows all", " … ctrl+o")
# Choices the slot cannot list (a short terminal): a row of their own beside the ones listed, on the side they are
# cut from, counting them and the ticked ones among them (`{ticked}` is ", 2 ticked" or ""). An approval's rows carry
# no number anywhere (no digit picks one), so its marker counts nothing.
MORE_CHOICES = ("  … +{count} more choice{s}{ticked} · ctrl+o shows all", "  … +{count}{ticked} · ctrl+o", "  … ctrl+o")
MORE_APPROVAL_CHOICES = ("  … more choices · ctrl+o shows all", "  … more choices · ctrl+o", "  … more · ctrl+o", "  … ctrl+o")
# After the open question's first words, while others wait behind it (`App.waiting_requests`).
WAITING = " · {count} more question{s} waiting"
# What a question that closed reads as in the transcript (`outcomes`, `withdrawn_outcome`), after `✓` or `✗` and
# before ` · <what it asked>`. Hermes' `request.cancel` reasons with a word of their own; any other is named.
OUTCOME_SKIPPED = "skipped"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_ANSWERED = "answered"
OUTCOME_DECLINED = "declined"
WITHDRAWN_WORDS = {"timeout": "timed out", "interrupted": "interrupted"}
WITHDRAWN = "withdrawn ({reason})"

_DECLINE_NOTICES = {
    "vault.unlock_prompt": "Hermes asked to unlock a password vault. Vault prompts run in `hermes --tui`; declined.",
    "vault.save_login": "Hermes asked to save a login to a password vault. That runs in `hermes --tui`; declined.",
}


@dataclass(frozen=True)
class Answer:
    """The frame to send back for one request.

    `stops`: an approval's deny the person gave, after which the app stops the
    running turn. `tell`: an approval's deny from its tell row, after which the
    app gives the composer to what the person tells Hermes instead.
    """

    request_id: str
    frame: dict[str, Any]
    tell: bool = False
    stops: bool = False


@dataclass(frozen=True)
class ImmediateAnswer:
    """A request the TUI cannot show: answered at once, with a notice for the transcript."""

    answer: Answer
    notice: str


@dataclass(frozen=True)
class TypeIt:
    """A key that opened a clarify question's text field: the app types it into the field (the composer)."""

    key: Key | Paste


def _decline(request_id: str, method: str) -> Answer:
    return Answer(request_id, dict(contract.server_request_treatment(method).decline))


@dataclass
class PromptSlot:
    """One open request. The app routes keys and submitted composer text here while it is open."""

    request_id: str
    method: str
    params: dict[str, Any]
    selected: int = 0
    question_index: int = 0
    answers: dict[str, str | None] = field(default_factory=dict)
    typing: bool = False  # a clarify question's text field is open: the composer is the field
    ticked: list[str] = field(default_factory=list)  # a multi-select question's ticked choices, in the order ticked
    # An approval's command and its `command_risk.segments`, read once instead of on every frame.
    _segments: tuple[str, list[command_risk.Segment]] | None = field(
        default=None, init=False, repr=False, compare=False,
    )

    @property
    def masked(self) -> bool:
        return contract.server_request_treatment(self.method).masked

    @property
    def wants_text(self) -> bool:
        """Whether submitted composer text answers this slot (clarify free text, value prompts)."""
        return self.method != "approval"

    @property
    def picking(self) -> bool:
        """Whether the person answers by picking from the list now, so no composer is drawn.

        An approval, and a clarify question with choices while its text field
        is closed. A question answered with text (a sudo password, a secret, a
        clarify question without choices, or one whose text field is open)
        has the composer.
        """
        if self.method == "approval":
            return True
        return self.method == "clarify" and bool(self._current_choices()) and not self.typing

    @property
    def keys(self) -> tuple[str, ...]:
        """The keys this question takes now, longest form first, said on the info line."""
        if self.method == "approval":
            return APPROVAL_KEYS
        if self.method == "clarify":
            if not self._current_choices():
                return CLARIFY_TEXT_KEYS
            if self.typing:
                return CLARIFY_FIELD_KEYS
            if not self._other_row():
                return CLARIFY_CLOSED_KEYS
            return CLARIFY_MULTI_KEYS if self._multi() else CLARIFY_CHOICE_KEYS
        return VALUE_KEYS

    def keys_while(self, turn_runs: bool) -> tuple[str, ...]:
        """`keys`, for whether a turn runs: an approval's deny stops only a turn that runs (`APPROVAL_IDLE_KEYS`)."""
        return APPROVAL_IDLE_KEYS if self.method == "approval" and not turn_runs else self.keys

    def decline(self) -> Answer:
        return _decline(self.request_id, self.method)

    # -- approval ---------------------------------------------------------------------------

    def approval_choices(self) -> tuple[str, ...]:
        offered = self.params.get("choices")
        if not isinstance(offered, list) or not offered:
            return (*APPROVAL_CHOICES, APPROVAL_TELL)
        return (*(choice for choice in APPROVAL_ORDER if choice in offered or choice == "deny"), APPROVAL_TELL)

    def approval_label(self, choice: str) -> str:
        """A choice's row: what it does, `always` naming what Hermes flagged (the description), which it saves."""
        return _APPROVAL_LABELS[choice].format(what=_one_line(self.params.get("description")) or ALWAYS_WHAT)

    # -- clarify ----------------------------------------------------------------------------

    def _questions(self) -> list[dict[str, Any]]:
        questions = self.params.get("questions")
        if not isinstance(questions, list):
            return []
        return [q for q in questions if isinstance(q, dict) and isinstance(q.get("qid"), str)]

    def _current_question(self) -> dict[str, Any] | None:
        questions = self._questions()
        return questions[self.question_index] if self.question_index < len(questions) else None

    def _current_choices(self) -> list[str]:
        question = self._current_question()
        return _string_choices(question) if question else []

    def _other_row(self) -> bool:
        """Whether the current question ends with the text field's row (`CLARIFY_OTHER`); not one `CLOSED_CHOICES` closes."""
        question = self._current_question()
        return not (question and question.get(CLOSED_CHOICES) is True)

    def _multi(self) -> bool:
        """Whether the current question takes several choices (Hermes' `multi_select`, on a question with choices)."""
        question = self._current_question()
        return bool(question and question.get("multi_select") is True and self._current_choices())

    def _record_answer(self, value: str | None) -> Answer | None:
        question = self._current_question()
        if question is None:
            return Answer(self.request_id, {"result": {"answers": dict(self.answers)}})
        self.answers[question["qid"]] = value
        self.question_index += 1
        self.selected = 0
        self.typing = False
        self.ticked = []
        if self.question_index >= len(self._questions()):
            return Answer(self.request_id, {"result": {"answers": dict(self.answers)}})
        return None

    def _pick(self, index: int) -> Answer | None:
        """Choice `index` answers the question; the row after the choices opens the text field instead.

        On a multi-select question the answer is the ticked choices, or choice
        `index` alone when none is ticked (`_ticked_answer`).
        """
        choices = self._current_choices()
        if index < len(choices):
            if self._multi():
                return self._record_answer(_ticked_answer(self.ticked or [choices[index]]))
            return self._record_answer(choices[index])
        if self._other_row():
            self.selected, self.typing = len(choices), True
        return None

    def _tick(self, index: int) -> None:
        """Tick choice `index` of a multi-select question, or untick it."""
        choice = self._current_choices()[index]
        if choice in self.ticked:
            self.ticked.remove(choice)
        else:
            self.ticked.append(choice)

    # -- input ------------------------------------------------------------------------------

    def handle_key(self, key: Key | Paste) -> Answer | TypeIt | None:
        """A key pressed while the slot is open: the answer frame once the person decided, or a key to type.

        `TypeIt` hands back a key that opened a clarify question's text field,
        for the app to type into it.
        """
        if isinstance(key, Key) and (key.name == ESCAPE or (key.name == CHAR and key.ctrl and key.char == "c")):
            return self._denied() if self.method == "approval" else self.decline()
        if self.method == "approval":
            return self._approval_key(key) if isinstance(key, Key) else None
        if self.method == "clarify":
            return self._clarify_key(key)
        return None

    def _approval_key(self, key: Key) -> Answer | None:
        """Up and Down (Left and Right too) move and stop at either end; Enter answers the highlighted choice.

        Deny is the first row and selected as the slot opens, so Up then Enter,
        the composer's recall-and-resend typed as the slot opened, still
        denies: Up moves nothing off the first row. No digit picks a choice,
        and the only letters that answer deny. Every deny stops the turn
        (`_denied`) but the tell row's.
        """
        choices = self.approval_choices()
        if key.name in (UP, LEFT):
            self.selected = max(self.selected - 1, 0)
        elif key.name in (DOWN, RIGHT):
            self.selected = min(self.selected + 1, len(choices) - 1)
        elif key.name == ENTER and choices[self.selected] == APPROVAL_TELL:
            return replace(self.decline(), tell=True)
        elif key.name == ENTER and choices[self.selected] == "deny":
            return self._denied()
        elif key.name == ENTER:
            return Answer(self.request_id, {"result": {"choice": choices[self.selected]}})
        elif key.name == CHAR and not key.ctrl and not key.alt and key.char.lower() in _DENY_KEYS:
            return self._denied()
        return None

    def _denied(self) -> Answer:
        """The explicit deny the person gave an approval, which also stops the running turn."""
        return replace(self.decline(), stops=True)

    def _clarify_key(self, key: Key | Paste) -> Answer | TypeIt | None:
        """The choices' keys, and the keys that open the text field.

        In the list: Up and Down move over the choices and the text field's row
        and stop at either end; Enter picks the highlighted row; a digit picks
        that choice, or opens the field when it numbers the field's row. Any
        other character, or a paste, opens the field and is its first text.
        On a multi-select question Space ticks the highlighted choice (and
        does nothing on the field's row), and a digit ticks its choice. With
        the field open, Up and Down go back to the list, and what was typed
        stays in the field.
        """
        choices = self._current_choices()
        if not choices:
            return None
        last = len(choices) if self._other_row() else len(choices) - 1
        if isinstance(key, Paste):
            return None if self.typing or not self._other_row() else self._open_field(key)
        if key.name in (UP, DOWN):
            self.typing = False
            step = -1 if key.name == UP else 1
            self.selected = min(max(self.selected + step, 0), last)
            return None
        if self.typing:
            return None
        if key.name == ENTER:
            return self._pick(self.selected)
        if key.name != CHAR or key.ctrl or key.alt:
            return None
        multi = self._multi()
        if multi and key.char == " ":
            if self.selected < len(choices):
                self._tick(self.selected)
            return None
        if len(key.char) == 1 and key.char in CHOICE_DIGITS and int(key.char) - 1 <= last:
            if multi and int(key.char) - 1 < len(choices):
                self._tick(int(key.char) - 1)
                return None
            return self._pick(int(key.char) - 1)
        return self._open_field(key) if self._other_row() else None

    def _open_field(self, key: Key | Paste) -> TypeIt:
        self.selected, self.typing = len(self._current_choices()), True
        return TypeIt(key)

    def submit_text(self, text: str) -> Answer | None:
        """Composer text submitted while the slot is open.

        A clarify question with choices takes an empty submit as Enter on the
        highlighted row while the list is shown, and as a way back to the list
        while the text field is open. On a multi-select question the typed
        answer joins the ticked choices.
        """
        if self.method == "approval":
            return None
        if self.method == "clarify":
            if self._current_choices() and not text.strip():
                if self.typing:
                    self.typing = False
                    return None
                return self._pick(self.selected)
            if self._multi():
                return self._record_answer(_ticked_answer([*self.ticked, text.strip()]))
            return self._record_answer(text.strip() or None)
        return Answer(self.request_id, {"result": {"value": text}})

    # -- outcome ----------------------------------------------------------------------------

    def subject(self) -> str:
        """What the question asks about, in one line: an approval command's first line (else its description), the
        clarify question open now (else the last), the value asked for."""
        if self.method == "approval":
            command = str(self.params.get("command") or "").strip().split("\n", 1)[0]
            return _one_line(command) or _one_line(self.params.get("description"))
        if self.method == "clarify":
            question = self._current_question() or (self._questions() or [{}])[-1]
            return _one_line(question.get("question"))
        return {"sudo": "sudo password", "secret": str(self.params.get("env_var") or "a secret"),
                "vault.code": "verification code"}.get(self.method, self.method)

    def outcomes(self, frame: dict[str, Any]) -> list[tuple[bool, str]]:
        """How the answer `frame` reads in the transcript: one `(answered, words)` per row, the words ending in what
        was asked.

        A clarify question answered says the label (the ticked labels, joined)
        or the text the person typed, as Hermes reads it, without the
        `(Recommended)` tag it adds to a choice (`_without_recommended`);
        `skipped` for an empty answer, and one cancelled says `cancelled`; the
        TUI's own question (`CLOSED_CHOICES`) says only the choice, whose label
        names what it does. A
        value prompt says only `answered` or
        `declined`, never the value. An approval's answer is the app's to say.
        """
        result = frame.get("result")
        if self.method == "approval" or not isinstance(result, dict):
            return []
        if self.method != "clarify":
            word = OUTCOME_ANSWERED if result.get("value") else OUTCOME_DECLINED
            return [(word == OUTCOME_ANSWERED, f"{word} · {self.subject()}")]
        answers = result.get("answers")
        if not isinstance(answers, dict):
            return [(False, f"{OUTCOME_CANCELLED} · {self.subject()}")]
        rows: list[tuple[bool, str]] = []
        for question in self._questions():
            if question["qid"] not in answers:
                continue
            value, asked = answers[question["qid"]], _one_line(question.get("question"))
            if question.get(CLOSED_CHOICES) is True and isinstance(value, str) and value:
                rows.append((True, value))
                continue
            if not isinstance(value, str) or not value:
                rows.append((False, f"{OUTCOME_SKIPPED} · {asked}"))
                continue
            multi = question.get("multi_select") is True and bool(_string_choices(question))  # as `_multi` reads it
            # A multi-select answer keeps the items with text, as Hermes keeps them (`clarify_tool._clean_answer`).
            items = [item for item in json.loads(value) if str(item).strip()] if multi else [value]
            if not items:
                rows.append((False, f"{OUTCOME_SKIPPED} · {asked}"))
                continue
            rows.append((True, f"{', '.join(_one_line(_without_recommended(item)) for item in items)} · {asked}"))
        return rows

    def attention(self) -> str:
        """What the notification for this question says as it opens: what Hermes asks, in a line, never a value."""
        if self.method == "approval":
            return f"Hermes asks to run {_one_line(self.params.get('description')) or 'a command'}"
        if self.method == "clarify":
            return f"Hermes asks: {self.subject()}"
        return f"Hermes needs your {self.subject()}" if self.method == "sudo" else f"Hermes needs {self.subject()}"

    def withdrawn_outcome(self, reason: str) -> str:
        """How the question reads in the transcript once Hermes withdrew it, for `reason` (`request.cancel`'s)."""
        word = WITHDRAWN_WORDS.get(reason) or WITHDRAWN.format(reason=reason or "no reason given")
        return f"{word} · {self.subject()}"

    # -- rendering --------------------------------------------------------------------------

    def lines(self, width: int, theme: Theme, max_rows: int, waiting: int = 0, whole: bool = False) -> list[Line]:
        """The slot's rows, at most `max_rows`; the question's keys are the info line's (`keys_while`).

        A list keeps the highlighted row whatever the budget (`_fit`). A
        question with no list keeps its first row and its last ones. Whatever
        is cut, a marker says Ctrl+O shows the question whole. `waiting`
        questions queued behind this one are counted after its first words.
        `whole` draws an approval's command as Hermes sent it instead of by
        command (`whole_lines`).
        """
        if max_rows <= 0:
            return []
        inner = max(width - len(SLOT_BAR), 1)
        queued: Line = (Span(WAITING.format(count=waiting, s="s" if waiting != 1 else ""), theme.muted),) if waiting else ()
        if self.method == "approval":
            rows = self._approval_lines(inner, theme, max_rows, queued, whole)
        elif self.method == "clarify":
            rows = self._clarify_lines(inner, theme, max_rows, queued)
        else:
            # The header and the hint matter most; the body is what gets cut.
            rows = _keep_ends(self._value_lines(inner, theme, queued), max_rows, inner, theme)
        bar = Span(SLOT_BAR, theme.warn if self.method == "approval" else theme.muted)
        # A highlighted choice's band (a fill span) runs on to the right edge past the cut.
        return [(*truncate_line((bar, *truncate_line(row, inner)), width), *(row[-1:] if row and is_fill(row[-1]) else ()))
                for row in rows]

    def whole_lines(self, width: int, theme: Theme, waiting: int = 0) -> list[Line]:
        """Every row of the question, nothing cut, an approval's command whole as Hermes sent it: what Ctrl+O pages
        while it is open (the pager has its own keys)."""
        return self.lines(width, theme, sys.maxsize, waiting=waiting, whole=True)

    def _choice_rows(self, labels: list[tuple[str, str]], width: int, theme: Theme, mark_style: Style) -> list[list[Line]]:
        """Each `(lead, label)` as its rows: the label wrapped under its lead (a number), whole, so a tag at its end
        (Hermes' `(Recommended)`) shows; the highlighted one marked `❯` and highlighted."""
        rows: list[list[Line]] = []
        for index, (lead, label) in enumerate(labels):
            current = index == self.selected
            style = theme.menu_current if current else theme.text
            first: Line = (Span(CHOICE_MARK if current else " " * len(CHOICE_MARK), mark_style), Span(lead, style))
            rest: Line = (Span(" " * (len(CHOICE_MARK) + cell_width(lead))),)
            rows.append(wrap_prefixed((Span(label, style),), first, rest, width))
        return rows

    def _span(self, choices: list[list[Line]], room: int) -> tuple[int, int]:
        """The first and last choice that fit in `room`: the highlighted one, then whole choices before it, then after."""
        first = last = self.selected
        used = len(choices[self.selected])
        while first > 0 and used + len(choices[first - 1]) <= room:
            first -= 1
            used += len(choices[first])
        while last + 1 < len(choices) and used + len(choices[last + 1]) <= room:
            last += 1
            used += len(choices[last])
        return first, last

    def _window(self, choices: list[list[Line]], room: int, width: int, theme: Theme) -> tuple[list[Line], bool]:
        """The rows of the choices that fit in `room` (`_span`), and where some do not, a marker saying so; and
        whether choices were cut with no marker row, for `_fit` to mark at the end of the last row listed.

        The marker (`MORE_CHOICES`, an approval's `MORE_APPROVAL_CHOICES`)
        counts the choices left out and the ticked ones among them, on a row of
        its own under the list when any are cut below the highlighted one, else
        above it, wherever that still leaves a row for another choice. A
        highlighted choice taller than `room` alone shows its first rows.
        """
        current = choices[self.selected]
        first, last = self._span(choices, room)
        if first == 0 and last == len(choices) - 1 and len(current) <= room:
            return [row for choice in choices for row in choice], False
        own_row = room - len(current) >= 2
        if own_row:
            first, last = self._span(choices, room - 1)
        rows = current[:room] if len(current) >= room else [row for choice in choices[first : last + 1] for row in choice]
        if not own_row:
            return rows, True
        hidden = [index for index in range(len(choices)) if not first <= index <= last]
        ticked = sum(1 for index in hidden if self._is_ticked(index))
        said = {"count": len(hidden), "s": "s" if len(hidden) != 1 else "", "ticked": f", {ticked} ticked" if ticked else ""}
        forms = list(MORE_APPROVAL_CHOICES) if self.method == "approval" else [form.format(**said) for form in MORE_CHOICES]
        if ticked:
            forms[-1] = f"  … {ticked} ticked · ctrl+o"
        marker: Line = (Span(next((form for form in forms if cell_width(form) <= width), forms[-1]), theme.muted),)
        return ([*rows, marker] if last < len(choices) - 1 else [marker, *rows]), False

    def _is_ticked(self, index: int) -> bool:
        """Whether the choice at `index` of a multi-select question is ticked (the last row, Other, never is)."""
        choices = self._current_choices() if self.method == "clarify" and self._multi() else []
        return index < len(choices) and choices[index] in self.ticked

    def _fit(
        self, head: list[Line], body: list[Line], choices: list[list[Line]], max_rows: int, width: int, theme: Theme,
    ) -> list[Line]:
        """`head`, `body` and the `choices` within `max_rows` (`_fitted`)."""
        return self._fitted(head, body, choices, max_rows, width, theme)[0]

    def _fitted(
        self, head: list[Line], body: list[Line], choices: list[list[Line]], max_rows: int, width: int, theme: Theme,
    ) -> tuple[list[Line], int]:
        """`head`, `body` and the `choices` (each one's rows), in that order, within `max_rows`, and how many of the
        body's rows show, from its first.

        Rows are counted, not choices. Everything is drawn when it fits.
        Otherwise the highlighted choice always shows, whole when it can, and
        with two rows or more the head's first row comes before it. The rows
        left go to the body's first row, the rest of the head, the other
        choices (`_window`), and as much of the body as fits, in that order.
        Each cut is marked where it is: choices left out
        beside the choices (`_window`); the head or the body cut on a row of
        its own when one is left over (counting the body's rows left out),
        else at the end of the last row above the choices. Choices cut with no
        row for their marker are marked at the end of the last one listed,
        unless the head or the body is marked already: one `ctrl+o shows all`
        then stands for the whole question. The highlighted choice's first row
        carries the marker when it is the only row.
        """
        listed = sum(len(choice) for choice in choices)
        if len(head) + len(body) + listed <= max_rows:
            return [*head, *body, *(row for choice in choices for row in choice)], len(body)
        if max_rows == 1:
            return [_ends_with_more(choices[self.selected][0], width, theme)], 0
        left = max_rows - 1 - min(len(choices[self.selected]), max_rows - 1)  # beside the head's first row and it
        reserved = min(1, left) if body else 0  # the command's first row says what it does
        rest = head[1 : 1 + left - reserved]
        shown, unmarked = self._window(choices, max_rows - 1 - len(rest) - reserved, width, theme)
        spare = max_rows - 1 - len(rest) - len(shown)
        kept = body[: spare - 1] if len(body) > spare >= 2 else body[:spare]
        above = [head[0], *rest, *kept]
        if len(rest) == len(head) - 1 and len(kept) == len(body):
            if unmarked:  # only choices were cut, with no row for their marker: it ends the last one listed
                shown[-1] = _ends_with_more(shown[-1], width, theme)
        elif spare > len(kept):
            hidden = len(body) - len(kept)
            forms = MORE_ANY_ROWS
            if hidden:
                forms = tuple(form.format(count=hidden, s="s" if hidden != 1 else "") for form in MORE_ROWS)
            above.append((Span(next((form for form in forms if cell_width(form) <= width), forms[-1]), theme.muted),))
        else:
            above[-1] = _ends_with_more(above[-1], width, theme)
        return [*above, *shown], len(kept)

    def _approval_lines(self, width: int, theme: Theme, max_rows: int, queued: Line, whole: bool) -> list[Line]:
        """The header, the risks Hermes did not name, the command by command, then the choices (`_fit`).

        Every command is listed, its risky ones marked, when that fits; else,
        when Hermes' description names a risk found, its risky ones in full and
        one row for the rest (`_command_bodies`). `whole` draws the command as
        Hermes sent it instead (`whole_lines`). Each fold step's body is drawn
        spaced, then with its rule alone, then bare, and cut from its end by
        `_fit`; a cut that leaves out a `▲` row while another command's row
        shows is not drawn, nor a step that saves no row over the one before
        unless cut. Of the rest, the one that shows the most `▲` rows, then the
        most commands that may change something, is drawn. On a tie a layout
        that fits beats a cut, the less folded and then the better spaced
        first; of two cuts, the one that shows fewer commands that change
        nothing wins, so a row more never trades a listed command for a fold.

        When Hermes' description names no risk found, nothing folds: the slot
        lists every command and, short of rows, cuts from the end, risky rows
        too, as it did before the fold steps.
        """
        description = str(self.params.get("description") or "dangerous command")
        command = str(self.params.get("command") or "")
        if self._segments is None or self._segments[0] != command:
            self._segments = (command, command_risk.segments(command))
        found = self._segments[1]
        count: Line = (Span(f" · {len(found)} commands", theme.muted),) if len(found) > 1 else ()
        head = wrap_prefixed(
            (Span(f"Hermes asks to run {description}", theme.warn), *count, *queued), (Span("⚠ ", theme.warn),),
            (Span("  "),), width,
        )
        unnamed = command_risk.unnamed_risks(found, description)
        if unnamed:
            steps = theme.catch_mark or (theme.brand,)
            mark = tuple(Span(cell, steps[min(index, len(steps) - 1)]) for index, cell in enumerate(CATCH_MARK))
            words = (*mark, Span(ALSO_SEES, theme.catch_words if theme.catch_mark else theme.muted),
                     Span(" · ".join(unnamed), replace(theme.warn, bold=True)))
            head.extend(wrap_prefixed(words, (Span("  "),), (Span("  "),), width))
        indent: Line = (Span("  ", theme.code),)
        if whole:
            rows = wrap_prefixed((Span(command, theme.code),), indent, indent, width) if command else []
            bodies = [(rows, [("!", 0)] * len(rows))]
        else:
            # Folding hides commands, so only when what Hermes flagged is one of the risky rows that stay.
            folds = FOLD_STEPS if command_risk.names_a_found_risk(found, description) else 0
            bodies = self._command_bodies(found, width, theme, folds)
        rule: Line = (Span("  " + "─" * max(min(width - 4, RULE_CELLS), 1), theme.faint),)
        blank: Line = ()
        choices = self._approval_choice_rows(width, theme)
        listed = [row for choice in choices for row in choice]
        def scored(kinds: list[tuple[str, int]], kept: int, fits: bool) -> tuple[int, int, bool, int] | None:
            shown: dict[str, set[int]] = {kind: set() for kind in (RISK_MARK, "…", "!", "", "+")}
            for kind, index in kinds[:kept]:
                shown[kind].add(index)
            if (shown["!"] or shown[""] or shown["+"]) and any(kind in (RISK_MARK, "…") for kind, _ in kinds[kept:]):
                return None  # a `▲` row would go while another command's row shows
            return len(shown[RISK_MARK]), len(shown["!"]), fits, 0 if fits else -len(shown[""])

        best: tuple[tuple[int, int, bool, int], list[Line]] | None = None
        built: list[tuple[list[Line], list[tuple[str, int]]]] = []  # the steps' bodies, built only as far as needed
        for body, kinds in bodies:
            built.append((body, kinds))
            if len(built) == 1:
                everything = (sum(1 for kind, _ in kinds if kind == RISK_MARK),
                              len({index for kind, index in kinds if kind == "!"}), True, 0)
            elif len(body) >= min(len(earlier) for earlier, _ in built[:-1]):
                continue  # a fold that saves no row hides a command for nothing
            for framed in ([*head, blank, *body, blank, rule, blank], [*head, *body, rule], [*head, *body]):
                score = scored(kinds, len(body), True) if len(framed) + len(listed) <= max_rows else None
                if score is not None and (best is None or score > best[0]):
                    best = (score, [*framed, *listed])
            if best is not None and best[0] == everything:
                return best[1]  # nothing a cut could show more of
        tried: set[tuple[tuple[str, int], ...]] = set()
        for body, kinds in built:
            if tuple(kinds) in tried:
                continue  # a step that folds nothing more draws the same cut
            tried.add(tuple(kinds))
            drawn, kept = self._fitted(head, body, choices, max_rows, width, theme)
            score = scored(kinds, kept, False)
            if score is not None and (best is None or score > best[0]):
                best = (score, drawn)
        return best[1] if best else self._fit(head, built[-1][0], choices, max_rows, width, theme)

    def _command_bodies(self, found: list[command_risk.Segment], width: int, theme: Theme,
                        folds: int) -> Iterator[tuple[list[Line], list[tuple[str, int]]]]:
        """The command's rows at each fold step from 0 to `folds`, built as asked for, each with what every row is
        and the index of its command: `RISK_MARK` for a risky command's first row and `…` for the rest of it, `!` for
        a command that may change something, `""` for one that changes nothing (`Segment.foldable`), and `+` for the
        folded row (-1).
        Each command in order: a risky one after a `▲` (on one line, wrapped, never cut), any other as written
        (its own line breaks kept), wrapped; each command is wrapped once. From step 1, other commands give way to one
        `+ N other commands` row naming their programs: at 1 those that change nothing (`Segment.foldable`); at 2 also
        a directory change or an assignment (`Segment.sets_state`) other than the last one before each risky command;
        at 3 every one of those; at 4 every command not risky. With none risky, every command is listed as written."""
        if not any(segment.risks for segment in found):
            indent: Line = (Span("  ", theme.code),)
            rows, kinds = [], []
            for index, segment in enumerate(found):
                wrapped_rows = wrap_prefixed((Span(segment.text, theme.code),), indent, indent, width)
                rows.extend(wrapped_rows)
                kinds.extend([("!", index)] * len(wrapped_rows))
            yield rows, kinds
            return
        home = os.path.expanduser("~")
        # A risky command is never cut at the width: on a narrow slot it wraps under its mark.
        mark: Line = (Span("  "), Span(RISK_MARK, replace(theme.error, bold=True)))
        under: Line = (Span(" " * (2 + cell_width(RISK_MARK))),)
        plain: Line = (Span(" " * (2 + cell_width(RISK_MARK)), theme.code),)
        wrapped = [
            wrap_prefixed((Span(_home_short(_joined(segment.text), home), replace(theme.warn, bold=True)),), mark,
                          under, width)
            if segment.risks else wrap_prefixed((Span(segment.text, theme.code),), plain, plain, width)
            for segment in found
        ]
        aiming: set[int] = set()  # the last directory change or assignment before each risky command
        last = -1
        for index, segment in enumerate(found):
            last = index if segment.sets_state else last
            if segment.risks and last >= 0:
                aiming.add(last)
                last = -1
        for fold in range(folds + 1):
            rows = []
            kinds = []
            others: list[command_risk.Segment] = []
            for index, segment in enumerate(found):
                if not segment.risks and (
                        (fold >= 1 and segment.foldable) or (fold == 2 and segment.sets_state and index not in aiming)
                        or (fold >= 3 and segment.sets_state) or fold >= 4):
                    others.append(segment)
                else:
                    rows.extend(wrapped[index])
                    kind = "" if segment.foldable else "!"
                    kinds.extend([(RISK_MARK, index), *[("…", index)] * (len(wrapped[index]) - 1)] if segment.risks
                                 else [(kind, index)] * len(wrapped[index]))
            if others:
                lead = Span(OTHER_COMMANDS.format(count=len(others), s="s" if len(others) != 1 else ""), theme.muted)
                names = truncate("(" + ", ".join(dict.fromkeys(segment.head for segment in others)) + ")",
                                 max(width - cell_width(lead.text) - cell_width(OTHER_HINT), 0))
                rows.append(truncate_line((lead, Span(names, theme.faint), Span(OTHER_HINT, theme.hint)), width))
                kinds.append(("+", -1))
            yield rows, kinds

    def _approval_choice_rows(self, width: int, theme: Theme) -> list[list[Line]]:
        """Each choice as its rows: its icon and label in its tone (`APPROVAL_TONES`), wrapped under the icon; the
        highlighted one marked `❯`, bold, on its tone's band to the right edge."""
        rows: list[list[Line]] = []
        for index, choice in enumerate(self.approval_choices()):
            icon, tone = APPROVAL_TONES[choice]
            current = index == self.selected
            style = getattr(theme, f"pick_{tone}") if current else getattr(theme, tone)
            first: Line = (Span(CHOICE_MARK if current else " " * len(CHOICE_MARK), style), Span(f"{icon} ", style))
            rest: Line = (Span(" " * (len(CHOICE_MARK) + 2), style),)
            wrapped = wrap_prefixed((Span(self.approval_label(choice), style),), first, rest, width)
            rows.append([(*row, fill(style)) for row in wrapped] if current and style.bg is not None else wrapped)
        return rows

    def _clarify_lines(self, width: int, theme: Theme, max_rows: int, queued: Line) -> list[Line]:
        """The question (its counter when there are several), then its choices and the text field's row.

        A question with no choices says how to answer under it instead.
        """
        question = self._current_question()
        if question is None:
            return []
        total = len(self._questions())
        counter = f" ({self.question_index + 1}/{total})" if total > 1 else ""
        note: Line = (Span(MULTI_NOTE, theme.muted),) if self._multi() else ()
        head: list[Line] = list(
            wrap_line(
                (Span("? ", theme.user), Span(str(question.get("question", "")) + counter, theme.text), *note, *queued),
                width,
            )
        )
        choices = self._current_choices()
        if not choices:
            return _keep_ends([*head, (Span("  type an answer and press enter · esc cancels", theme.hint),)], max_rows,
                              width, theme)
        rows = [*choices, CLARIFY_OTHER] if self._other_row() else choices
        labels = [(f"{number}. ", choice) for number, choice in enumerate(rows, start=1)]
        if self._multi():
            boxes = [TICKED if choice in self.ticked else UNTICKED for choice in choices] + [" " * len(UNTICKED)]
            labels = [(box + lead, label) for box, (lead, label) in zip(boxes, labels)]
        return self._fit(head, [], self._choice_rows(labels, width, theme, theme.user), max_rows, width, theme)

    def _value_lines(self, width: int, theme: Theme, queued: Line) -> list[Line]:
        label = {
            "sudo": "Hermes needs your sudo password",
            "secret": f"Hermes needs {self.params.get('env_var') or 'a secret'}",
            "vault.code": "Hermes needs a verification code",
        }.get(self.method, f"Hermes asks: {self.method}")
        prompt = self.params.get("prompt") or self.params.get("command") or self.params.get("hint") or ""
        rows = wrap_prefixed(
            (Span(label, theme.text), *queued), (Span("🔑 " if self.masked else "? ", theme.user),), (Span("   "),),
            width,
        )
        if prompt:
            rows.extend(wrap_line((Span("  " + str(prompt), theme.muted),), width))
        rows.append((Span("  type it in the composer and press enter · esc declines", theme.hint),))
        return rows


def _string_choices(question: dict[str, Any]) -> list[str]:
    """A clarify question's choices that are strings: the only ones the slot lists and answers with."""
    choices = question.get("choices")
    return [choice for choice in choices if isinstance(choice, str)] if isinstance(choices, list) else []


# The tag Hermes adds to a clarify question's first choice for display; it strips it from the answer it reads.
RECOMMENDED_TAG = "(Recommended)"


def _without_recommended(text: object) -> str:
    """`text` as Hermes reads an answer (6c61c3e27d `clarify_tool.strip_recommended`): stripped, and without
    `RECOMMENDED_TAG` at its end, matched ignoring case."""
    stripped = str(text).strip()
    if stripped.casefold().endswith(RECOMMENDED_TAG.casefold()):
        return stripped[: -len(RECOMMENDED_TAG)].strip()
    return stripped


def _home_short(text: str, home: str) -> str:
    """`text` with the home directory `home` written `~` where the shell would read `~` as it: unquoted, starting a
    word, and a whole path part (`/Users/a` in `/Users/a/x`, not in `/Users/ab` or `"/Users/a"`)."""
    if len(home) <= 1 or home not in text:
        return text
    shown: list[str] = []
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote != "'" and char == "\\":
            shown.append(text[index : index + 2])
            index += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif text.startswith(home, index) and (index == 0 or text[index - 1].isspace() or text[index - 1] in ";&|(<>"):
            after = text[index + len(home) : index + len(home) + 1]
            if not after or after.isspace() or after in "/\\;&|)<>":
                shown.append("~")
                index += len(home)
                continue
        shown.append(char)
        index += 1
    return "".join(shown)


def _joined(text: str) -> str:
    """`text` on one line: each line break outside quotes, with a `\\` continuation before it and the indentation
    around it, as one space; a line break inside quotes, and every other space, as written."""
    shown: list[str] = []
    quote = ""
    index = 0
    while index < len(text):
        char = text[index]
        if not quote and (char == "\n" or text.startswith("\\\n", index)):
            while shown and shown[-1] in (" ", "\t"):
                shown.pop()
            index += 1 if char == "\n" else 2
            while index < len(text) and text[index] in " \t":
                index += 1
            shown.append(" ")
            continue
        if quote != "'" and char == "\\":
            shown.append(text[index : index + 2])
            index += 2
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        shown.append(char)
        index += 1
    return "".join(shown).strip()


def _one_line(value: object) -> str:
    """`value` as one line of text: its whitespace, line breaks included, collapsed to single spaces."""
    return " ".join(str(value or "").split())


def _ticked_answer(choices: list[str]) -> str:
    """A multi-select answer as Hermes' Ink TUI sends it: a JSON list of the labels (`JSON.stringify`), "" for none."""
    values = [choice for choice in choices if choice.strip()]
    return json.dumps(values, ensure_ascii=False, separators=(",", ":")) if values else ""


def _ends_with_more(row: Line, width: int, theme: Theme) -> Line:
    """`row` with the cut marker at its end (`MORE_FORMS`), the row cut to make room when no form leaves it whole."""
    fits = [form for form in MORE_FORMS if line_width(row) + cell_width(form) <= width]
    form = fits[0] if fits else MORE_FORMS[-1]
    kept = row if fits else truncate_line(row, max(width - cell_width(form), 0), ellipsis="")
    return (*kept, Span(form, theme.muted))


def _keep_ends(rows: list[Line], max_rows: int, width: int, theme: Theme) -> list[Line]:
    """`rows` within `max_rows`: when they do not fit, the first row, marked as cut, and the last ones."""
    if len(rows) <= max_rows:
        return rows
    return [_ends_with_more(rows[0], width, theme), *rows[len(rows) - (max_rows - 1) :]]


def open_request(request_id: str, method: str, params: dict[str, Any]) -> PromptSlot | ImmediateAnswer:
    """A slot for a request the TUI shows, or the immediate answer for one it cannot."""
    if not contract.server_request_treatment(method).shown:
        notice = _DECLINE_NOTICES.get(
            method, f"Hermes asked for `{method}`, which only Hermes' Desktop app answers; declined."
        )
        return ImmediateAnswer(_decline(request_id, method), notice)
    slot = PromptSlot(request_id=request_id, method=method, params=dict(params))
    if method == "clarify" and not slot._questions():
        # An empty slot would wait on a question nobody can see; answer it now, visibly.
        return ImmediateAnswer(slot.decline(), "Hermes sent a clarify request with no question in it; declined.")
    if method == "approval":
        # Enter on an untouched approval denies: allowing takes the arrows, then Enter.
        slot.selected = slot.approval_choices().index("deny")
    return slot
