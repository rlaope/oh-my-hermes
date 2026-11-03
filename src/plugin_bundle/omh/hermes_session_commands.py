"""Hermes' own session commands, where OMH would otherwise route over them.

Three questions, each answered once, here, for the plugin's per-turn hook and
for `omh.routing` alike. Standalone, because the bundle may not import `omh`.

`host_command_turn` -- did Hermes write this turn? Hermes' session commands
reach the model as an ordinary user-role turn whose text the host built from
a fixed template. The CLI and the TUI write none of these rows with a
`display_kind`. The messaging gateway stamps its `/loop` wakeups
`internal_notification` (in the floor release and on main) and, since 0.21.4,
its heartbeats too, which `turn_authorship.host_synthesized_turn` already
reads; its `/plan`, `/learn` and `/blueprint` turns (the command's own event
text rewritten) and `/goal` continuations (a synthetic event that is not
internal) stay unstamped. Where no stamp exists, the template's own opening is
the only record of who wrote the turn. Each frame is verbatim from upstream,
all present in the floor release (`v2026.9.7`) except `/initiate-setup`, which
only newer hosts send (a frame match needs no version check: an older host
never writes it):

- `/plan` -- `build_plan_prompt`, `agent/plan_prompt.py`;
- a `/loop` wakeup -- `WAKEUP_PROMPT_TEMPLATE`, `hermes_cli/loops.py`;
- a `/goal` continuation, with or without a completion contract or `/subgoal`
  criteria, or after a failed quality gate -- the `CONTINUATION_PROMPT_*`
  templates, `hermes_cli/goals.py`;
- the `/goal` kick that stands in for a goal the person just sent --
  `GOAL_ALREADY_SEEN_KICK`, same file;
- a goal-mode kanban card's continuation and finalize nudges --
  `KANBAN_GOAL_*_TEMPLATE`, same file;
- a `/heartbeat` firing -- `HEARTBEAT_PROMPT_TEMPLATE`, `hermes_cli/heartbeat.py`;
- `/learn` -- `build_learn_prompt`, `agent/learn_prompt.py`;
- `/initiate-setup` -- `HEADER`, `agent/initiate_setup_prompt.py`;
- the `/blueprint` seed that asks for a matched blueprint's settings --
  `build_blueprint_seed`, `hermes_cli/blueprint_cmd.py`.

Such a turn already carries the host's instruction for itself, so it is not a
request for OMH to route. A frame counts only as the template writes it: the
turn's first line is the frame line (or, where the template continues it with
a tick or an interval, starts with it and closes with `]`; or, where it fills
in values mid-line, starts with it and holds the fixed text between them),
and the next non-blank line opens with the template's next fixed text. A
person who types only a blueprint seed's first line wrote no such next line,
and routes as before. A heartbeat's next
line is the person's own recurring instruction, so a person who types under a
pasted heartbeat frame cannot be told from the host there. On a messaging
gateway Hermes may put its own material before the frame
(`gateway/run_inbound.py`, modelled in `jev_consent`): a Discord trigger note
or a reply pointer, each closed by `]` and a blank line (`v2026.9.7` writes
the reply pointer outermost, hermes-agent 6c61c3e27d the trigger note), an
attachment note closed the same way, channel-history backfill ending in
`[New message]`, and a `[<name>] ` sender prefix in a shared session. Those
are removed first; a reply pointer ends at the `"]` and blank line after its
quoted text, and an image description at the `~]` closing its closer-look
note, not at a `]` inside either. A host block that never closes --
including a quote or a description that itself holds its block's close,
which is cut there -- and QQ's `[Quoted message]:` block, which has no close
at all, leave the turn a person's, which routes as it did before this module
existed.

`person_request_text` -- what did the person write? The same removal, read
for routing decisions: the hook's route hint and candidate line, the chat
router and the wrapper's own decisions read a turn's request through it, so
the gateway material above never picks a workflow. A reply's quoted text is
context, not the request, here as for the frame; what OMH forwards or hands
off still carries the whole turn. The sender prefix is removed only on a
turn from a messaging gateway, the one place Hermes writes it. The cuts
above are the ways it fails: what follows the cut is read as the person's,
as all of it was before.

A slash skill is the one host template both questions read. Hermes sends
`/<skill> <text>` as the skill's whole body inside a frame
(`_build_skill_message`, `agent/skill_commands.py`), so the body is never the
person's words. For a skill of OMH's own, `person_request_text` reads the
turn as it was typed, `/<skill> <text>`, as Hermes' `describe_skill_invocation`
does. Any other skill is a `host_command_turn`: the person chose it, and an
OMH route hint would compete with it.

`loop_timer_verdict` -- is this request a loop on a timer? "loop every 5
minutes and check CI", `/loop 5m ...`, "every 10 minutes loop over the inbox"
or "5분마다 ... 루프 돌려줘" asks for a check repeated on a cadence, which is
Hermes' native `/loop` inside the session (or a cron job when it must run
unattended), not OMH's long-horizon goal loop. Only the opening of the
person's current message is read -- after the gateway material above and the
courtesy openers every reader of a request's opening strips
(`request_lead.COURTESY_OPENERS`), never the backfill before `[New message]`
-- and only these shapes are a loop on a timer:

- `loop` or `/loop` is the first word and its cadence follows (`loop 5m ...`,
  `/loop 5m ...`, `loop every 5 minutes ...`, `loop each hour ...`);
- the cadence opens the message and `loop` is the very next word, followed
  by its object, a preposition or conjunction (`_LOOP_VERB_CONTINUATIONS`),
  or nothing (`every 10 minutes loop over the inbox`, `every 2 hours loop
  and ...`), never by a noun (`every hour loop counters reset`); a count of
  two or more before a spelled singular unit is no cadence here (`every 5
  minute loop ...`), and a first sentence that ends in `?` or says why or
  how is a question about a fault (`every 5 min loop back to login, why?`);
- a Korean cadence opens the message and its first clause closes on
  running the loop (`5분마다 루프 돌려줘`, `5분마다 CI 확인하는 루프 돌려주세요`),
  with no connective such as `-는데` or `-지만` in that clause.

A loop word anywhere else, or used as an adverbial (`... in a loop`,
`반복해서`, `루프 돌면서`, `루프 돌려서`), leaves the verdict `none`, because
the same words describe a fault as often as they ask for a loop ("every 5
minutes my pod restarts in a loop", "5분마다 반복해서 에러 나는데 원인
찾아줘"); the turn routes as it did before this module existed. A request
that opens by asking to write or explain a `for` loop or a music loop that
runs on a timer is `construct_loop`. Either shape is OMH's goal loop instead
(`goal_loop`) when the person uses one of OMH's own forms, names the goal
loop, or sets it a goal (`_carries_goal` is the whole rule) -- with one
exception: a typed `/loop` with its cadence is Hermes' command whatever its
prompt mentions (`typed_loop_sets_goal` says when its prompt would otherwise
have been the goal loop). Every surface that has to decide -- the chat
router's early answer, the loop guard in the scorer, the route hint and the
candidate line -- takes the verdict from this one function, read on the
turn's executable routing text (`reference_regions`), so none of them keeps
word lists of its own for it. `native_loop_prompt` is that loop's prompt,
which `spend_signals` reads: a loop whose prompt spends the person's money is
`spend-gate`'s turn, not one answered with `/loop`.

Text is folded with NFKC and a case fold, as the router's `normalized_phrase`
does, with the Unicode hyphens folded to `-`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata

from .jev_consent import BACKFILL_SEPARATOR, HOST_BLOCK_END, HOST_BLOCK_OPENERS, SENDER_PREFIX
from .memory_query_sanitizer import GATEWAY_ORIGIN_CLOSING, GATEWAY_ORIGIN_OPENING
from .reference_regions import executable_routing_text
from .request_lead import after_courtesy
from .show_reel_cues import backfill_is_inert


@dataclass(frozen=True)
class HostFrame:
    """A host template's first line and the fixed text its next line opens with.

    `opening` is the whole first line, or its fixed start when `open_ended`
    (the template continues the line with a tick or an interval and closes it
    with `]`) or when `holds` is set (the template fills values into the line
    and writes `holds` between them; no `]` closes it). `next_line` is ""
    where the template's next line is the person's own words.
    """

    opening: str
    next_line: str = ""
    open_ended: bool = False
    holds: str = ""


# Verbatim from upstream; see the module docstring for each template's source.
HOST_COMMAND_TURN_FRAMES = (
    HostFrame("[/plan — plan mode]", "For this turn, you are in PLAN MODE"),
    HostFrame("[/loop wakeup #", "Recurring task: ", open_ended=True),
    HostFrame("[Continuing toward your standing goal]", "Goal: "),
    HostFrame("[Continuing toward your standing goal — a quality gate failed]", "Goal: "),
    HostFrame("[Goal set] Continue with the goal you were just given; there is no need to re-read it."),
    HostFrame("[Continuing toward this kanban task — judge says it is not done yet]", "Reason: "),
    HostFrame("[The work looks complete, but the task is still open]", "Reason: "),
    HostFrame("[Heartbeat — recurring instruction, fires every ", open_ended=True),
    HostFrame(
        "[/learn] The user wants you to learn a reusable skill from the request below, and save it.",
        "THE REQUEST:",
    ),
    # The template's body is a SKILL.md file, whose first line is the
    # frontmatter fence and nothing else.
    HostFrame("[/initiate-setup]", "---\n"),
    # The blueprint's title, then its key, then its description fill the line.
    HostFrame(
        "Set up the '",
        "Ask me for each of these, one at a time, offering the default in brackets if I don't have a preference:",
        holds="' automation for me (automation blueprint '",
    ),
)

# The four verdicts on a loop beside a timer.
LOOP_TIMER_GOAL = "goal_loop"  # OMH's goal loop, whatever timer sits beside it
LOOP_TIMER_NATIVE = "native_loop"  # a check repeated on a timer: Hermes' `/loop`
LOOP_TIMER_CONSTRUCT = "construct_loop"  # a code or media loop that runs on a timer
LOOP_TIMER_NONE = "none"  # no loop on a timer; nothing here decides the turn
# The two a surface answers in chat instead of offering the goal loop.
LOOP_TIMERS_ANSWERED_DIRECTLY = frozenset({LOOP_TIMER_NATIVE, LOOP_TIMER_CONSTRUCT})

# Set on the route hint payload when the verdict is one of those two, so the
# candidate line, which ranks the catalog on its own, leaves the goal loop off.
NATIVE_LOOP_CADENCE_HINT_KEY = "native_loop_cadence"

# -- the gateway's material --------------------------------------------------
# Where a host block's own close is known it is read first, so a `]` and a
# blank line inside the block do not end it: a reply pointer closes after the
# text it quotes (`[Replying to: "<text>"]`), and the image description Hermes
# writes closes after its closer-look note (`... image_url: <path> ~]`). On the
# routing lexer's projection, which the loop verdict reads, a quote and its
# marks are masked; there the first `]` and blank line is the close. A quote or
# a description that itself holds its block's close is cut there.
_BLOCK_CLOSES = (
    ("[Replying to", '"]\n\n'),
    ("[The user sent an image~", "~]\n\n"),
)
# QQ's `[Quoted message]:` block runs into the person's text with no close of
# its own (`jev_consent` counts it unsplittable too), so no cut finds where the
# person's words start: the turn is left whole, as it read before this module.
_UNSPLITTABLE_BLOCK = "[Quoted message]"
# A message that reaches a messaging gateway while the agent is busy steers or
# redirects the running turn with its origin written before it
# (`_steer_text_with_origin`, `gateway/run_busy.py`): this opening line, the
# origin as one JSON line, and this closing line, then a blank line and the
# person's text. A redirect opens a turn on that text. Read as the request,
# the JSON keys (platform, chat, thread, profile, message, reply) ranked the
# same three skills on every such Discord or Slack turn and, being ASCII,
# kept a Korean request off the Hangul line. Hermes joins steers that arrive
# together with a newline (`agent/interrupt_control.py`) and a leftover steer
# opens the next turn (`run_busy.py`), so a turn can hold several blocks, each
# at the start of a line: every one is cut and the person's lines stay in
# order. Only the exact shape is cut: the opening line, one JSON object of ids
# on one line (`json.dumps(ensure_ascii=True)` with `[` and `]` escaped, so no
# bracket), the closing line, a blank line. The two lines are
# `memory_query_sanitizer`'s, the one source for both readers.
_GATEWAY_ORIGIN_BLOCK = re.compile(
    r"^" + re.escape(GATEWAY_ORIGIN_OPENING) + r"\n"
    r"\{[^\n\[\]]*\}\n"
    + re.escape(GATEWAY_ORIGIN_CLOSING) + r"\n\n",
    re.MULTILINE,
)
# Hermes writes `[<display name>] ` before the person's text in a shared session
# on a messaging gateway and nowhere else (`_prefix_inbound_sender_context`:
# `is_shared_multi_user_session` and a user name). The name is one line with its
# whitespace collapsed (`neutralize_untrusted_inline_text`) and may itself hold
# `] `, so the prefix runs to the last `] ` before any `[` on the first line.
_DISPLAY_NAME_PREFIX = re.compile(r"\[([^\[\n]*)\] ")
# A leading bracket that opens with a command sigil or an OMH skill label
# (`[/plan] ...`, `[$loop] ...`, `[ulw-loop] ...`, `[omh-role:reviewer] ...`)
# is the person invoking something, not a display name.
_INVOCATION_BRACKET = re.compile(r"\[\s*(?:/|\$|\./|(?:omh|ulw)[- ])", re.IGNORECASE)
_OMH_BRACKET_WORDS = frozenset({"omh", "ulw"})

# -- a slash skill's scaffold ------------------------------------------------
# Hermes never hands `/<skill> <text>` to a hook as typed: the CLI, the TUI,
# the gateway and cron all send the skill's whole body inside a frame
# (`_build_skill_message` and `_scaffold_header`, `agent/skill_commands.py`).
# The frame's first line, whole, for one skill and for a bundle or a stacked
# `/a /b` invocation, and the markers Hermes' own `describe_skill_invocation`
# reads the instruction back by. Verbatim from upstream, the same in the floor
# release (`v2026.9.7`) and in 0.22.2.
_SINGLE_SKILL_FRAME = re.compile(
    r'\[IMPORTANT: The user has invoked the "([^"\n]*)" skill, indicating they want you to follow its '
    r"instructions\. The full skill content is loaded below\.\]\n"
)
_BUNDLE_FRAME = re.compile(
    r'\[IMPORTANT: The user has invoked the "([^"\n]*)" (stacked )?skill bundle, loading \d+ skills together\. '
    r"Treat every skill below as active guidance for this turn\.\]\n"
)
_SINGLE_SKILL_INSTRUCTION = "The user has provided the following instruction alongside the skill invocation: "
_RUNTIME_NOTE = "\n\n[Runtime note:"
_BUNDLE_USER_INSTRUCTION = "\nUser instruction: "
_BUNDLE_FIRST_SKILL_BLOCK = "\n\n[Loaded as part of the "

# -- the cadence -------------------------------------------------------------
_TIMER_UNITS = frozenset(
    {"second", "seconds", "sec", "secs", "minute", "minutes", "min", "mins", "hour", "hours", "hr", "hrs"}
)
# `_INTERVAL_TOKEN_RE` in `hermes_cli/loops.py`: hours, then minutes, then
# seconds, at least one, digits first (`30s`, `5m`, `1h30m`).
_INTERVAL_TERM = re.compile(r"^(?=\d)(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
# A count glued to a spelled unit: `5mins`, `2hrs`.
_GLUED_UNIT_TERM = re.compile(r"^[1-9]\d*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)$")
# `5분마다`, `2시간마다`, `매분`, `매시간`, where the request starts.
_KOREAN_CADENCE = r"(?:[1-9]\d*\s?(?:초|분|시간)\s?마다|매(?:초|분|시간))"
_KOREAN_CADENCE_LEAD = re.compile(rf"{_KOREAN_CADENCE}(?=\s)")

# -- the request's opening ---------------------------------------------------
# What may follow `loop` when it is the verb after a cadence ("every 5 minutes
# loop over the inbox"). A noun does not ("every 10 minutes loop detection
# kills my agent").
# A count of two or more before a spelled singular unit is an adjective, not a
# cadence: "every 5 minute loop that runs the backup fails" is a noun phrase.
_SINGULAR_UNITS = frozenset({"second", "minute", "hour"})
# A question about a cadence-first loop asks about a fault, not for a loop:
# "every 5 min loop back to login, why?".
_QUESTION_WORDS = frozenset({"why", "how"})
_LOOP_VERB_CONTINUATIONS = frozenset(
    {"and", "then", "over", "through", "to", "until", "back", "it", "them"}
    | {"the", "this", "that", "these", "those", "my", "our", "a", "an"}
)
# `5분마다 루프 돌려줘`, `5분마다 ... 확인하는 루프 돌려주세요`: running the loop is
# the request, and it closes the clause.
_KOREAN_LOOP_REQUEST = re.compile(r"(?:루프|loop)(?:를|을)?\s?돌려\s?(?:줘|줘요|주세요|주십시오)$")
# A clause joined by one of these reports something before it asks
# ("5분마다 에러 나는데 루프 돌려줘").
_KOREAN_CONNECTIVES = ("는데", "은데", "던데", "인데", "지만", "니까", "길래")
_CLAUSE_END = re.compile(r"[,.!?;\n，。]")
_SENTENCE_END = re.compile(r"(?<=[.?!;])\s|\n")

# -- OMH's own forms ---------------------------------------------------------
# The skill's name and its older `omh-` label, hyphenated or spaced, wherever
# they appear in the current message ("/ulw-loop every 5m ...", "omh loop
# every hour ...", "every 2 hours ulw-loop the flaky list"). The boundary is
# Latin only, so a Korean particle after the name keeps it.
_OMH_LOOP_NAME = re.compile(r"(?<![0-9a-z_-])(?:ulw|omh)[- ]loop(?![0-9a-z_-])")
# Leading forms, read where the person's own words start.
_OMH_LOOP_LEADS = ("./loop", "$loop", "omh 루프")
_OMH_LOOP_LEAD_SIGIL = re.compile(r"^(?:\./|\$)(?=loop(?:\s|$))")

# -- a name for the goal loop ------------------------------------------------
_GOAL_LOOP_NAME = re.compile(
    r"(?<![0-9a-z_-])(?:goal loop|loop engineering|loopable|loopability|loop skill)(?![0-9a-z_-])"
)
_GOAL_LOOP_PHRASES = (
    "목표 루프",
    "loop 스킬",
    "루프 스킬",
    "loop로 돌릴만",
    "loop로 해야",
    "루프로 돌릴만",
    "루프로 해야",
)

# -- a goal beside the loop --------------------------------------------------
# The loop guard (`omh.routing.policy._loop_goal_guard_applies`) reads these
# same three vocabularies for requests that say no loop word at all.
LOOP_REPEATED_IMPROVEMENT_TOKENS = frozenset({"repeatedly", "iteratively", "iterate", "until"})
LOOP_REPEATED_IMPROVEMENT_PHRASES = (
    "keep improving",
    "reduce friction",
    "reducing friction",
    "until first success",
    "until first value",
    "improve until first value",
    "반복 개선",
    "계속 개선",
    "계속해서 개선",
    "줄여가며 개선",
    "줄이면서 개선",
    "막히는 부분을 계속 개선",
)
LOOP_PRODUCT_GOAL_TOKENS = frozenset({"oss", "repo", "repository", "install", "first-run", "friction", "product"})
LOOP_PRODUCT_GOAL_PHRASES = (
    "first run",
    "first-run",
    "first run experience",
    "first successful value",
    "install to first value",
    "why users do not feel value",
    "스타급 oss",
    "star-worthy oss",
    "설치 후",
    "설치부터 첫 성공",
    "10분 안에 가치",
    "가치 못 느끼는",
    "첫 성공",
    "첫 성공까지",
)
LOOP_NORTH_STAR_TOKENS = frozenset({"star", "stars", "star-worthy", "starworthy", "10k-star", "100k-star", "adoption"})
LOOP_NORTH_STAR_PHRASES = (
    "star worthy",
    "star-worthy",
    "first-run friction",
    "10k star",
    "10k-star",
    "100k star",
    "100k-star",
)
# Asking the loop to make something better is a goal on its own; a check is not.
_IMPROVEMENT_TOKENS = frozenset({"improve", "improving", "enhance", "enhancing"})
_IMPROVEMENT_PHRASES = ("개선", "향상", "더 좋게")
# Moving a product or star measure is a goal too: "to lower install friction",
# "to get us to 10k stars", "설치 후 ... 시간을 줄여줘".
_OUTCOME_TOKENS = frozenset(
    {"lower", "lowering", "reduce", "reduces", "reducing", "cut", "cutting", "shrink", "shrinking"}
    | {"raise", "raising", "increase", "increasing", "grow", "growing", "boost", "boosting"}
)
_OUTCOME_REACH = re.compile(r"(?<![0-9a-z_-])get (?:us )?to(?![0-9a-z_-])")
_OUTCOME_PHRASES = ("줄여", "줄이", "낮춰", "낮추", "높여", "높이", "늘려", "늘리", "올려", "올리")

# -- a loop that is a thing, not a request -----------------------------------
LOOP_CONSTRUCT_PHRASES = (
    "for loop",
    "while loop",
    "event loop",
    "bash loop",
    "shell loop",
    "loop in python",
    "loop in bash",
    "music loop",
    "audio loop",
    "video loop",
    "game loop",
)
# How a request to write or explain one opens.
_CONSTRUCT_ASKS = (
    "write ",
    "explain ",
    "show me ",
    "implement ",
    "how do i ",
    "how do you ",
    "how to ",
    "how would i ",
    "how can i ",
    "how should i ",
)
# The construct is named within this many words of that opening.
_CONSTRUCT_ASK_REACH = 8

_TOKEN = re.compile(r"[0-9a-z][0-9a-z_-]*")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace("‐", "-")


_FOLDED_FRAMES = tuple(
    HostFrame(_fold(frame.opening), _fold(frame.next_line), frame.open_ended, _fold(frame.holds))
    for frame in HOST_COMMAND_TURN_FRAMES
)


def _opens_with_frame(text: str) -> bool:
    first, _, rest = text.replace("\r\n", "\n").partition("\n")
    first = first.rstrip()
    rest = rest.lstrip("\n")
    for frame in _FOLDED_FRAMES:
        if frame.holds:
            opens = first.startswith(frame.opening) and frame.holds in first[len(frame.opening):]
        elif frame.open_ended:
            opens = first.startswith(frame.opening) and first.endswith("]")
        else:
            opens = first == frame.opening
        if opens and rest.startswith(frame.next_line):
            return True
    return False


def _after_gateway_material(text: str) -> str:
    """`text` after the backfill and host blocks a gateway prepends; a block that
    never closes, or that cannot be split, is left in place."""
    if BACKFILL_SEPARATOR in text:
        text = text.rsplit(BACKFILL_SEPARATOR, 1)[1]
    text = _GATEWAY_ORIGIN_BLOCK.sub("", text.lstrip()).lstrip()
    while text.startswith(HOST_BLOCK_OPENERS) and not text.startswith(_UNSPLITTABLE_BLOCK):
        end, block_end = -1, HOST_BLOCK_END
        for opener, close in _BLOCK_CLOSES:
            if text.startswith(opener):
                end, block_end = text.find(close), close
        if end == -1:
            end, block_end = text.find(HOST_BLOCK_END), HOST_BLOCK_END
        if end == -1:
            break
        text = text[end + len(block_end):].lstrip()
    return text


@lru_cache(maxsize=1)
def _catalog_skill_words() -> frozenset[str]:
    return frozenset(name.casefold() for name in _skill_shortlist.catalog_skill_names() or ()) | _OMH_BRACKET_WORDS


def _display_name_prefix_end(text: str) -> int:
    """Where the person's words start after a shared session's sender prefix, or 0.

    A bracket the router reads as the person's own stays: a relay header the
    routing lexer masks (`[REPORT] ...`), an invocation (`_INVOCATION_BRACKET`),
    and a bracket that holds only a catalog skill's name or label, `omh` or `ulw`
    (`[deep-interview] ...`, `[omh] status`). So does a prefix whose next word
    opens a bracket too: the two cannot be told apart, so the turn is read as
    it was before, by readers that take one leading bracket for a sender.
    """
    prefix = _DISPLAY_NAME_PREFIX.match(text)
    if (
        not prefix
        or text[prefix.end():].lstrip().startswith("[")
        or _INVOCATION_BRACKET.match(text)
        or _fold(prefix.group(1)).strip() in _catalog_skill_words()
        or not executable_routing_text(prefix.group()).strip()
    ):
        return 0
    return prefix.end()


def _skill_invocation(text: str, *, after_sender: bool) -> tuple[str, bool | None] | None:
    """(the invocation as typed, whether every skill it loads is OMH's own) when
    `text` opens with Hermes' slash-skill frame, or None.

    `describe_skill_invocation(content, separator=" ")` in stdlib: `/<name>
    <instruction>`, or `/<name>` for a bare invocation; a stacked one keeps its
    typed `/a /b`. One skill's instruction follows its body, which may quote
    the marker, so the LAST marker is the person's, up to the runtime note. A
    bundle's sits in its header, read up to the first loaded skill's block, so
    a body below cannot supply one. With `after_sender`, a shared session's
    `[<name>] ` sender prefix may come first, as Hermes writes it there.

    Ownership is None when the catalog sidecar cannot be read. A named bundle
    is the person's own set, never one of OMH's skills.
    """
    if after_sender:
        sender = SENDER_PREFIX.match(text)
        if sender and not (_SINGLE_SKILL_FRAME.match(text) or _BUNDLE_FRAME.match(text)):
            text = text[sender.end():]
    single = _SINGLE_SKILL_FRAME.match(text)
    bundle = None if single else _BUNDLE_FRAME.match(text)
    if single:
        name = single.group(1).strip()
        skills: tuple[str, ...] = (name,)
        at = text.rfind(_SINGLE_SKILL_INSTRUCTION)
        instruction = text[at + len(_SINGLE_SKILL_INSTRUCTION):].split(_RUNTIME_NOTE, 1)[0] if at != -1 else ""
    elif bundle:
        name = bundle.group(1).strip()
        skills = tuple(key.lstrip("/") for key in name.split()) if bundle.group(2) else ()
        header = text.split(_BUNDLE_FIRST_SKILL_BLOCK, 1)[0]
        at = header.find(_BUNDLE_USER_INSTRUCTION)
        instruction = header[at + len(_BUNDLE_USER_INSTRUCTION):] if at != -1 else ""
    else:
        return None
    if not name:
        return None
    label = name if name.startswith("/") else f"/{name}"
    instruction = instruction.strip()
    labels = _skill_shortlist.catalog_skill_labels()
    owned = None if labels is None else bool(skills) and all(skill in labels for skill in skills)
    return (f"{label} {instruction}" if instruction else label), owned


def person_request_text(message: str, *, messaging: bool = False) -> str:
    """The words the person wrote in this turn, which is all OMH routes on.

    The gateway material in the module docstring is removed: the backfill
    before `[New message]`, and each host block closed by `]` and a blank line
    (the Discord trigger note, a reply pointer and the text it quotes, an
    attachment note). A reply's quoted text is context for the request, not
    part of it. `messaging` says the turn came through a messaging gateway,
    the only place Hermes writes a shared session's `[<display name>] `
    sender prefix; there that prefix goes too, unless the bracket is the
    person's own (`_display_name_prefix_end`). Anywhere else a leading
    bracket is the person's. A block that never closes or cannot be split
    stays with everything after it, and so does a host command turn's frame,
    which is what `host_command_turn` reads.

    A slash skill of OMH's own is read as the person typed it, `/dag-ulw
    <text>`. Hermes sends it as the skill's whole body inside a frame
    (`_skill_invocation`), and that body, read as the person's words, picked
    the workflows its own prose names instead. Only a turn that opens with the
    frame's exact first line is read this way, so a typed message reads as it
    did before. Any other skill's scaffold is left whole, for
    `host_command_turn`.

    Only what decides a route reads this. What OMH hands on -- a forwarded
    routing prompt, a coding handoff, a plan -- carries the whole turn, so the
    quote, an attachment's path and the backfill still reach it as context.
    """
    text = _after_gateway_material(message)
    if messaging and not text.startswith(HOST_BLOCK_OPENERS) and not _opens_with_frame(_fold(text)):
        text = text[_display_name_prefix_end(text):]
    invocation = _skill_invocation(text, after_sender=messaging)
    if invocation is not None and invocation[1] is not False:
        return invocation[0]
    return text


# A reply pointer, an attachment or image note, and the channel backfill a
# gateway puts before `[New message]`: material a person's words may point at
# ("make a demo video of this") that routing does not read. `[New message]`
# stays last: `host_context_removed` reads the backfill by its content.
_CONTEXT_BLOCK_OPENERS = ("[Replying to", "[The user sent", "[If you need a closer look", "[Image attached", "[New message]")


def host_context_removed(message: str) -> bool:
    """Whether `person_request_text` removes a reply pointer, an attachment note or the channel backfill from this turn.

    Routing reads only the person's words; a reader that must prove the request
    whole (a closed show-reel form) treats removed context like masked text.
    An inert backfill (`backfill_is_inert`: the Discord adapter's shape, with
    acknowledgement-only messages), after the trigger note Hermes writes
    before it, is not counted: it holds nothing such a request could be
    pointing at.
    """
    text = _after_gateway_material(message)
    removed = message[: len(message) - len(text)] if message.endswith(text) else message
    if BACKFILL_SEPARATOR in removed and not any(opener in removed for opener in _CONTEXT_BLOCK_OPENERS[:-1]):
        backfill, after = removed.rsplit(BACKFILL_SEPARATOR, 1)
        if backfill.startswith("[Triggering message id:"):
            backfill = backfill.partition(HOST_BLOCK_END)[2]
        return bool(after.strip()) or not backfill_is_inert(backfill)
    return any(opener in removed for opener in _CONTEXT_BLOCK_OPENERS)


def handed_on_text(message: str) -> str:
    """The turn as OMH hands it on (a coding handoff, a plan's statement): whole, except that the scaffold of a
    slash skill of OMH's own is the invocation typed, after any gateway material and sender prefix before it.

    The body Hermes loaded is its instruction to its own agent, not context the person gave: a handoff that carried
    it judged every path the skill names, Hermes' own absolute skill directory among them, as one the person named.
    """
    text = _after_gateway_material(message)
    invocation = _skill_invocation(text, after_sender=True)
    if invocation is None or invocation[1] is False:
        return message
    sender = None if (_SINGLE_SKILL_FRAME.match(text) or _BUNDLE_FRAME.match(text)) else SENDER_PREFIX.match(text)
    return message[: len(message) - len(text)] + (sender.group() if sender else "") + invocation[0]


def _host_command_turn(text: str) -> bool:
    text = _after_gateway_material(text)
    # A host block still open here never closed; what follows it is inside it.
    if text.startswith(HOST_BLOCK_OPENERS):
        return False
    invocation = _skill_invocation(text, after_sender=True)
    if invocation is not None:
        return invocation[1] is False
    if _opens_with_frame(_fold(text)):
        return True
    sender = SENDER_PREFIX.match(text)
    return bool(sender) and _opens_with_frame(_fold(text[sender.end():]))


def host_command_turn(message: object) -> bool:
    """Whether Hermes opened this turn from one of its own session-command templates.

    A slash skill that is not one of OMH's is one too: the person picked that
    skill, and the body Hermes loaded for it is the turn's instruction, so an
    OMH route hint read from its instruction would compete with the skill the
    person chose (`_skill_invocation`). A slash skill of OMH's own is not; it
    routes on its invocation as typed (`person_request_text`).
    """
    return isinstance(message, str) and _host_command_turn(message)


def _interval_term(term: str) -> bool:
    match = _INTERVAL_TERM.match(term)
    if match:
        return any(int(part or 0) for part in match.groups())
    return bool(_GLUED_UNIT_TERM.match(term))


def _bare(word: str) -> str:
    return word.rstrip(",.:;!?")


def _tokens(folded: str) -> set[str]:
    """Whole tokens, hyphenated ones kept whole: `cto-loop` is not the word `loop`."""
    return set(_TOKEN.findall(folded))


def _past_cadence(words: list[str], at: int) -> int:
    """The index after an `every <N> <unit>` cadence that starts at `words[at]`, or 0.

    The unit sits within two words of `every`: "every 5 minutes", "every
    hour", "every 5m", never "every engineer spends 30 minutes".
    """
    if len(words) <= at or words[at] not in ("every", "each"):
        return 0
    for reach in (1, 2):
        if len(words) > at + reach:
            word = _bare(words[at + reach])
            if word in _TIMER_UNITS or _interval_term(word):
                return at + reach + 1
    return 0


def _first_sentence(text: str) -> str:
    return _SENTENCE_END.split(text, maxsplit=1)[0].strip()


def _korean_loop_request(text: str) -> bool:
    """Whether the first clause of `text` closes on running the loop, with no connective before it."""
    clause = _CLAUSE_END.split(text, maxsplit=1)[0].strip().rstrip("~ ")
    return bool(_KOREAN_LOOP_REQUEST.search(clause)) and not any(word in clause for word in _KOREAN_CONNECTIVES)


def _prompt(words: list[str]) -> str:
    """The loop's prompt: the words after its cadence, less a joining "and" or "then"."""
    if words and _bare(words[0]) in ("and", "then"):
        words = words[1:]
    return " ".join(words)


def _loop_request_prompt(lead: str) -> str | None:
    """The prompt after `lead`'s loop command and cadence, or None when `lead` opens with neither.

    See the module docstring for the shapes. A Korean request's prompt is not
    read, and is "".
    """
    words = lead.split()
    if not words:
        return None
    # The native command's own syntax, `/loop [interval] <prompt>`, or the
    # cadence spelled out after it.
    if _bare(words[0]) in ("loop", "/loop"):
        if len(words) > 1 and _interval_term(_bare(words[1])):
            return _prompt(words[2:])
        if cadence_end := _past_cadence(words, 1):
            return _prompt(words[cadence_end:])
    korean = _KOREAN_CADENCE_LEAD.match(lead)
    past = _past_cadence(words, 0)
    if past > 2 and _bare(words[past - 1]) in _SINGULAR_UNITS and words[past - 2].isdigit() and int(words[past - 2]) > 1:
        past = 0
    if korean:
        rest = lead[korean.end():].lstrip()
    elif past:
        rest = " ".join(words[past:])
    else:
        return None
    # The cadence came first; `loop` has to be the very next word and its verb,
    # in a sentence that does not ask why or how.
    after = rest.split(maxsplit=2)
    sentence = _first_sentence(lead)
    if (
        after
        and _bare(after[0]) == "loop"
        and not sentence.endswith("?")
        and not _tokens(sentence) & _QUESTION_WORDS
    ):
        # "loop." or "loop:" closes the clause; otherwise the next word tells
        # a verb from a noun.
        if len(after) == 1 or after[0] != "loop" or _bare(after[1]) in _LOOP_VERB_CONTINUATIONS:
            return _prompt(rest.split()[1:])
    # A Korean cadence, and running the loop closes its first clause.
    return "" if korean and _korean_loop_request(rest) else None


def _asks_for_a_construct_on_a_timer(lead: str) -> bool:
    """Whether `lead` opens by asking to write or explain a code or media loop that runs on a timer."""
    sentence = _first_sentence(lead)
    if not sentence.startswith(_CONSTRUCT_ASKS):
        return False
    words = sentence.split()
    opening = f" {' '.join(_bare(word) for word in words[:_CONSTRUCT_ASK_REACH])} "
    if not any(f" {phrase} " in opening for phrase in LOOP_CONSTRUCT_PHRASES):
        return False
    return any(_past_cadence(words, at) for at in range(len(words)))


def _names_goal_loop(folded: str) -> bool:
    return bool(_GOAL_LOOP_NAME.search(folded)) or any(phrase in folded for phrase in _GOAL_LOOP_PHRASES)


def _carries_goal(folded: str) -> bool:
    """Whether the request sets the loop a goal rather than a check.

    It does when it asks to improve or enhance something; or pairs a product
    or star word with a repeat cue or an outcome verb; or pairs a star word
    with a product word.
    """
    tokens = _tokens(folded)
    if tokens & _IMPROVEMENT_TOKENS or any(phrase in folded for phrase in _IMPROVEMENT_PHRASES):
        return True
    repeated = bool(tokens & LOOP_REPEATED_IMPROVEMENT_TOKENS) or any(
        phrase in folded for phrase in LOOP_REPEATED_IMPROVEMENT_PHRASES
    )
    outcome = (
        bool(tokens & _OUTCOME_TOKENS)
        or bool(_OUTCOME_REACH.search(folded))
        or any(phrase in folded for phrase in _OUTCOME_PHRASES)
    )
    product = bool(tokens & LOOP_PRODUCT_GOAL_TOKENS) or any(phrase in folded for phrase in LOOP_PRODUCT_GOAL_PHRASES)
    north_star = bool(tokens & LOOP_NORTH_STAR_TOKENS) or any(phrase in folded for phrase in LOOP_NORTH_STAR_PHRASES)
    return ((repeated or outcome) and (product or north_star)) or (north_star and product)


@lru_cache(maxsize=1024)
def _loop_timer_reading(text: str) -> tuple[str, bool, str]:
    """The verdict on `text`, whether a typed `/loop` overrode a goal-loop verdict to reach it, and the loop's prompt."""
    text = text.strip()
    # A turn Hermes wrote is no request at all, whatever its template says.
    if _host_command_turn(text):
        return LOOP_TIMER_NONE, False, ""
    # Only the person's current message is read: not the backfill, and not a
    # host block that never closed, which still holds whatever follows it.
    message = _after_gateway_material(text)
    if message.startswith(HOST_BLOCK_OPENERS):
        return LOOP_TIMER_NONE, False, ""
    message = _fold(message)
    sender = SENDER_PREFIX.match(message)
    lead = after_courtesy(message[sender.end():] if sender else message)
    # OMH's names stand where the loop word would: "/ulw-loop every 5m ..." has
    # the same shape as "/loop every 5m ...", and is OMH's.
    plain = _OMH_LOOP_NAME.sub("loop", _OMH_LOOP_LEAD_SIGIL.sub("", lead, count=1))
    prompt = _loop_request_prompt(plain)
    if prompt is not None:
        shape = LOOP_TIMER_NATIVE
    elif _asks_for_a_construct_on_a_timer(plain):
        shape, prompt = LOOP_TIMER_CONSTRUCT, ""
    else:
        return LOOP_TIMER_NONE, False, ""
    # The name is read on the whole message, so a bracketed `[ulw-loop]` that
    # the sender-prefix strip took for a display name still counts.
    goal = bool(
        _OMH_LOOP_NAME.search(message)
        or lead.startswith(_OMH_LOOP_LEADS)
        or _names_goal_loop(lead)
        or _carries_goal(lead)
    )
    # Typed out with its cadence, the native command is the native command,
    # whatever its prompt mentions.
    if lead.startswith("/loop ") and shape == LOOP_TIMER_NATIVE:
        return LOOP_TIMER_NATIVE, goal, prompt
    return (LOOP_TIMER_GOAL if goal else shape), False, prompt


def loop_timer_verdict(text: str) -> str:
    """Whether `text` opens with a loop on a timer: one of the four `LOOP_TIMER_*` verdicts.

    `text` is the turn's executable routing text, before any display-name fold.
    `goal_loop` and `none` both leave the turn to its ordinary route.
    """
    return _loop_timer_reading(text)[0]


def typed_loop_sets_goal(text: str) -> bool:
    """Whether `text` is a typed `/loop` whose prompt would otherwise make it OMH's goal loop.

    Its verdict is `native_loop` all the same; a surface that answers it can
    say how OMH's goal loop is started instead.
    """
    return _loop_timer_reading(text)[1]


def native_loop_prompt(text: str) -> str:
    """The person's prompt to a loop whose verdict is `native_loop`, or "" for any other verdict.

    The words after the loop and its cadence ("buy the tickets with my card if
    they drop under $50" in "/loop 1h buy the tickets ..."), less a joining
    "and" or "then". A Korean request's prompt is not read.
    """
    verdict, _typed_goal, prompt = _loop_timer_reading(text)
    return prompt if verdict == LOOP_TIMER_NATIVE else ""


# Bound at the end, after this module's own definitions: `skill_shortlist`
# imports this module, and a sibling is read through a module-scope name
# because Hermes may evict the bundle's modules from `sys.modules` while its
# hooks stay callable (#1979).
from . import skill_shortlist as _skill_shortlist  # noqa: E402
