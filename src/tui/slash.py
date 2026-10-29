"""Slash commands in the OMH TUI: which ones the TUI runs, and which belong elsewhere.

Hermes' Ink app runs about sixty slash commands itself and sends the rest to
the gateway. The gateway's `slash.exec` already answers most of them on its
own, and the TUI's gateway child answers the ones a shared gateway's
`slash.exec` refuses but serves through a verb of its own (`/compress`,
`/undo`, `/stop`, ...: `attach/gateway_attach.py` SLASH_VERBS), so the OMH
TUI only has to own five kinds:

- `local`: commands about this terminal (help, quit, history, theme, the OMH
  model picker), the ones whose screen is the TUI's own (attaching an image,
  the session and model pickers, the plan as `/todos`), `/export`, which
  says what Hermes exports before it runs, and `/reload-skills`, which has
  to reach the gateway itself: `slash.exec` runs commands in a separate
  per-session worker, so a rescan there would leave the gateway's skill
  commands as they were. The TUI handles them, calling the gateway method
  underneath where there is one.
- `hermes`: commands whose surface is Ink-only (voice, the pet, the billing
  flows, overlays) or that would make the TUI persist raw prompts (`/save`,
  `/prompt`). The TUI names the Hermes door instead of half-supporting them.
- `dropped`: Ink display preferences and debug widgets that mean nothing here.
- `renamed`: Claude Code's name for a command Hermes has under another
  (`/cost` is `/usage`, `/compact` is `/compress`); it runs Hermes' command
  under the name typed.
- `classic`: Hermes commands that only its classic CLI runs (`hermes --cli`):
  Hermes' shared gateway refuses them in a TUI session, with a pointer of
  its own. They still go to Hermes as typed, so that pointer is what the
  person reads, but completion and /help leave them out.

Everything else goes to `slash.exec`, and a 4018 refusal from it falls back to
`command.dispatch`, the order Ink uses. That includes `/yolo`, which turns off
Hermes' approval prompts: the person typed it, and the TUI relays what the
person types (`/help` says so). It also includes `/plan`, which plan mode
relies on: a prompt typed in plan mode goes out as `/plan <text>`
(`plan_invocation`), so `/plan` must never be routed to `hermes` or `dropped`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import re

from .style import Span, Style

LOCAL = "local"
HERMES = "hermes"
DROPPED = "dropped"
RENAMED = "renamed"
CLASSIC = "classic"

HERMES_DOOR = "hermes --tui"
PLAN_COMMAND = "plan"  # Hermes' one-turn plan prompt; the TUI's plan mode sends every prompt through it
# Hermes' /retry and /undo take the last turn(s) back themselves before they answer: /retry with that prompt to send
# again, /undo with it to edit (a `prefill`).
TURN_BACK_COMMANDS = frozenset({"retry", "undo"})


@dataclass(frozen=True)
class SlashCommand:
    name: str
    route: str
    summary: str
    aliases: tuple[str, ...] = ()
    target: str = ""  # RENAMED: the Hermes command it runs
    # Whether the transcript echoes it as `> /name arg`. A command whose own row says what it did (the steer, or
    # the prompt it sends) is not echoed: the echo would say it twice.
    echo: bool = True
    # Whether it is echoed when typed bare. A bare command that only opens a picker or a pager, or only repaints,
    # prints nothing to attribute, so its echo would stand alone in scrollback as if it were a prompt; bare /model's
    # pick is echoed as the command it runs.
    echo_bare: bool = True
    # The aliases the `/` menu offers under their own name, when what is typed starts one and is not in `name`:
    # `/resume`, the name the launch card and the last-session line give /sessions. The rest still run, and are
    # drawn as known, but get no row, so no alias ever displaces a command's own name.
    menu_aliases: tuple[str, ...] = ()


COMMANDS: tuple[SlashCommand, ...] = (
    # The terminal's own commands.
    SlashCommand("help", LOCAL, "Show commands"),
    SlashCommand("keys", LOCAL, "List every key (also ? on an empty composer)", echo_bare=False),
    SlashCommand("quit", LOCAL, "Leave the OMH TUI", ("exit",)),
    SlashCommand("new", LOCAL, "Start a new session", ("clear", "reset")),
    SlashCommand("sessions", LOCAL, "Switch to a stored session (a picker; an id or exact title after it switches)",
                 ("switch", "session", "resume"), echo_bare=False, menu_aliases=("resume",)),
    SlashCommand("redraw", LOCAL, "Repaint the screen", echo_bare=False),
    SlashCommand("history", LOCAL, "Page through this session's transcript", echo_bare=False),
    SlashCommand("rewind", LOCAL, "Go back to an earlier prompt, edit it, and send it again (also Esc Esc)",
                 echo_bare=False),
    SlashCommand("todos", LOCAL, "Show this session's whole plan"),
    SlashCommand("model", LOCAL, "Switch this session's model (a picker, or /model <name> [--provider <slug>])",
                 echo_bare=False),
    SlashCommand("export", LOCAL,
                 "Hermes' profile archive, not this transcript (`hermes profile export` on a shared gateway)"),
    SlashCommand("details", LOCAL, "Show or hide thinking and tool details", ("detail",)),
    SlashCommand("queue", LOCAL, "Show messages waiting for the current turn", ("q",)),
    SlashCommand("steer", LOCAL, "Add a message to the running turn (/steer <text>; Ctrl+Enter where it is a key)",
                 ("s",), echo=False),
    SlashCommand("effort", LOCAL, "Set this session's reasoning effort (/effort <level>; Ctrl+T steps through it)"),
    SlashCommand("logs", LOCAL, "Show the gateway's recent stderr (kept in memory only)", echo_bare=False),
    SlashCommand("dag", LOCAL, "Show the delegation graph whole, with full boxes, in a pager", echo_bare=False),
    SlashCommand("bots", LOCAL, "Watch this machine's Hermes profiles, gateways and sessions, read-only (also Ctrl+S)",
                 echo_bare=False),
    SlashCommand("copy", LOCAL, "Copy the last reply to the clipboard"),
    SlashCommand("image", LOCAL, "Attach an image file to the next message (/image <path>)"),
    SlashCommand("paste", LOCAL, "Attach the clipboard image to the next message (also Ctrl+V)"),
    SlashCommand("theme", LOCAL, "Pick the launch look (a picker), or /theme <look|palette|auto|light|dark>",
                 echo_bare=False),
    SlashCommand("glow", LOCAL, "Turn the light that goes round the screen during a turn on or off (/glow on|off)"),
    SlashCommand("omh-model", LOCAL, "Pick OMH model chains"),
    SlashCommand("topup", LOCAL, "Nous credit balance and the top-up link (Hermes' /topup)"),
    SlashCommand("reload-skills", LOCAL, "Re-scan Hermes' skills, so one installed since the start runs as /<name>",
                 ("reload_skills",)),
    # Claude Code's names for Hermes' commands.
    SlashCommand("cost", RENAMED, "Token usage and rate limits (Hermes' /usage)", target="usage"),
    SlashCommand("permissions", RENAMED, "Show or set the persistent approval mode (Hermes' /approvals)", target="approvals"),
    SlashCommand("compact", RENAMED,
                 "Compress this session's context: [here [N] | <focus> | --preview] (Hermes' /compress)",
                 target="compress"),
    # Surfaces that only Hermes' own terminal has.
    SlashCommand("update", HERMES, "Update Hermes"),
    SlashCommand("voice", HERMES, "Voice mode"),
    SlashCommand("wake", HERMES, "Wake word listener"),
    SlashCommand("pet", HERMES, "Animated pet"),
    SlashCommand("browser", HERMES, "Agent browser"),
    SlashCommand("journey", HERMES, "Learning timeline", ("learning", "memory-graph")),
    SlashCommand("replay", HERMES, "Replay a spawn tree"),
    SlashCommand("replay-diff", HERMES, "Diff two spawn trees"),
    SlashCommand("agents", HERMES, "Spawn-tree dashboard", ("tasks",)),
    SlashCommand("subscription", HERMES, "Change plan", ("upgrade",)),
    SlashCommand("setup", HERMES, "Run Hermes setup"),
    SlashCommand("skin", HERMES, "Hermes skin (the OMH TUI uses /theme)"),
    SlashCommand("save", HERMES, "Export the transcript to a file"),
    SlashCommand("prompt", HERMES, "Compose in $EDITOR", ("compose",)),
    SlashCommand("terminal-setup", HERMES, "Write IDE keybindings"),
    # Ink display preferences and debug widgets.
    SlashCommand("mouse", DROPPED, "Mouse tracking", ("scroll",)),
    SlashCommand("density", DROPPED, "Compact display"),
    SlashCommand("focus", DROPPED, "Focus view"),
    SlashCommand("statusbar", DROPPED, "Status bar position", ("sb",)),
    SlashCommand("indicator", DROPPED, "Busy indicator style"),
    SlashCommand("battery", DROPPED, "Battery indicator"),
    SlashCommand("fortune", DROPPED, "Fortune text"),
    SlashCommand("weather", DROPPED, "Weather widget"),
    SlashCommand("widgets-reload", DROPPED, "Rescan Hermes widgets"),
    SlashCommand("heapdump", DROPPED, "V8 heap snapshot"),
    SlashCommand("theme-info", DROPPED, "Ink theme diagnostics"),
    SlashCommand("mem", DROPPED, "Ink heap numbers"),
    SlashCommand("dialog-test", DROPPED, "Demo widget"),
    SlashCommand("grid-test", DROPPED, "Demo widget"),
    SlashCommand("ticker", DROPPED, "Demo widget"),
    SlashCommand("timestamps", DROPPED, "Transcript timestamps", ("ts",)),
    # What only Hermes' classic CLI runs (`gateway/session_commands.py` REFUSAL_HINTS names the way to each).
    SlashCommand("handoff", CLASSIC, "Hand the session to a messaging platform"),
    SlashCommand("worktree", CLASSIC, "Start in a fresh git worktree"),
    SlashCommand("snapshot", CLASSIC, "Back up or restore Hermes' state", ("snap",)),
    SlashCommand("import", CLASSIC, "Import a profile archive"),
    SlashCommand("hatch", CLASSIC, "Generate a pet", ("generate-pet",)),
    SlashCommand("palette", CLASSIC, "Command palette"),
)

_BY_NAME: dict[str, SlashCommand] = {}
for _command in COMMANDS:
    for _name in (_command.name, *_command.aliases):
        _BY_NAME[_name] = _command


@dataclass(frozen=True)
class SlashInvocation:
    """One slash command: `name` as typed (no slash), the rest as `arg`.

    `for_plan_mode` says the TUI wrote the command around a prompt the person
    typed in plan mode, instead of the person typing the command. `held` says
    a prompt the command sends waits for a running turn to end whatever the
    busy mode: it is a steer Hermes did not take. `rewind` is the rewind the
    person had picked when they sent it (the app's `Rewind`), or None: a
    prompt it sends goes in place of the picked one while that very rewind is
    still picked. It is matched by identity, so it takes no part in `==` or
    `hash()`. `images` are the images typed with the command, which the
    prompt it sends goes with; nor do they take part.
    """

    name: str
    arg: str
    command: SlashCommand | None
    for_plan_mode: bool = False
    held: bool = False
    rewind: object | None = field(default=None, compare=False)
    images: tuple[object, ...] = field(default=(), compare=False)  # the app's images a prompt it sends goes with

    @property
    def text(self) -> str:
        """The command as `slash.exec` takes it: no leading slash."""
        return f"{self.name} {self.arg}".rstrip()

    @property
    def typed(self) -> str:
        """What the person typed: the command line, or only the prompt when plan mode wrote the command."""
        return self.arg if self.for_plan_mode else f"/{self.text}"

    @property
    def shown(self) -> str:
        """What the transcript shows for a prompt the command sends when Hermes names no display text.

        The command itself when plan mode wrote it; "" for a typed command,
        which keeps showing the prompt Hermes built.
        """
        return f"/{self.text}" if self.for_plan_mode else ""


def parse_slash(text: str) -> SlashInvocation | None:
    """The invocation in `text`, or None when it is not a slash command.

    Only a leading `/` followed by a command name counts; `/` alone, `//x`,
    and a path like `/usr/bin` with a slash inside the name are ordinary text.
    The TUI's own commands and their aliases resolve whatever their case, as
    Hermes resolves its own (`/Rewind` is `/rewind`); `name` keeps the
    spelling typed, for the echo and for what goes to Hermes.
    """
    stripped = text.strip()
    if not stripped.startswith("/") or stripped.startswith("//"):
        return None
    head, _, arg = stripped[1:].partition(" ")
    if not head or "/" in head:
        return None
    return SlashInvocation(head, arg.strip(), _BY_NAME.get(head.lower()))


def plan_invocation(text: str) -> SlashInvocation:
    """`/plan <text>` for a prompt typed in plan mode, routed as a typed `/plan` is; the transcript shows the command."""
    return SlashInvocation(PLAN_COMMAND, text.strip(), _BY_NAME.get(PLAN_COMMAND), for_plan_mode=True)


def hermes_notice(command: SlashCommand) -> str:
    """The notice for a command that only Hermes' own terminal runs."""
    return f"/{command.name} runs in Hermes' own terminal: `{HERMES_DOOR}`."


def dropped_notice(command: SlashCommand) -> str:
    return f"/{command.name} is an Ink display setting; the OMH TUI has no equivalent."


@dataclass(frozen=True)
class Completion:
    name: str
    summary: str


def _offered_name(command: SlashCommand, key: str) -> str:
    """The name the menu offers `command` under for the lowercased `key`: its own, unless `key` is not in it and
    starts one of its `menu_aliases`, so `/res` and `/resu` offer `/resume` (which runs /sessions) among the names
    that start with what is typed."""
    if key in command.name:
        return command.name
    return next((alias for alias in command.menu_aliases if alias.startswith(key)), command.name)


def completions(prefix: str, catalog_pairs: Iterable[tuple[str, str]] = ()) -> list[Completion]:
    """Commands starting with `prefix` (no slash), then the ones that only contain it.

    In each group the TUI's own come first, then the gateway catalog, so
    `/uml` still finds `omh-codebase-uml` after every name that starts with
    it. A TUI command whose name does not match is offered under a menu
    alias that what is typed starts (`_offered_name`), after the TUI's own
    names that start with it and before the catalog's: `/res` offers
    `/resume` first. The alias completes to itself and runs as typed.
    Catalog entries the TUI routes to Hermes or drops are left out, so the
    menu only offers what will run here. Case is ignored, as a typed name's
    is.
    """
    key = prefix.lower()
    own = [command for command in COMMANDS if command.route in (LOCAL, RENAMED)]
    named = [Completion(_offered_name(command, key), command.summary) for command in own]
    aliased = [completion for completion, command in zip(named, own) if completion.name != command.name]
    local = [completion for completion in named if completion not in aliased] + aliased
    seen = {completion.name for completion in local}
    gateway: list[Completion] = []
    for raw_name, summary in catalog_pairs:
        name = raw_name.lstrip("/")
        if name.lower() in seen or name.lower() in _BY_NAME:
            continue
        seen.add(name.lower())
        gateway.append(Completion(name, summary))
    offered = local + gateway
    leading = [completion for completion in offered if completion.name.lower().startswith(key)]
    inner = [
        completion for completion in offered if key in completion.name.lower() and not completion.name.lower().startswith(key)
    ]
    return leading + inner


# A `/name` token: whitespace or the line's edge on both sides, so a path (`/Users/x`) or `a/b` is none.
_SLASH_TOKEN = re.compile(r"(?<!\S)/([A-Za-z0-9][\w.:-]*)(?!\S)")


def known_names(catalog_pairs: Iterable[tuple[str, str]] = ()) -> frozenset[str]:
    """Every name a typed `/name` resolves to here: what completion offers, the TUI's commands (their aliases too)
    and the catalog's.

    Lowercased: a typed name is matched whatever its case, as Hermes matches
    its commands and skills (`slash.exec` lowercases the name before it routes).
    """
    aliases = {alias for command in COMMANDS if command.route in (LOCAL, RENAMED) for alias in command.aliases}
    return frozenset(completion.name.lower() for completion in completions("", catalog_pairs)) | aliases


def slash_token_ranges(text: str, known: frozenset[str]) -> list[tuple[int, int]]:
    """(start, end) of each `/name` token in `text` whose name, lowercased, is in `known`; an unknown `/foo` and a path
    are none."""
    return [(found.start(), found.end()) for found in _SLASH_TOKEN.finditer(text) if found.group(1).lower() in known]


def slash_spans(
    text: str, known: frozenset[str], style: Style, token_style: Style, ranges: list[tuple[int, int]] | None = None
) -> tuple[Span, ...]:
    """`text` in `style`, each `/name` token whose name is in `known` (`slash_token_ranges`, or the `ranges` given) in
    `token_style`."""
    spans: list[Span] = []
    at = 0
    for start, end in slash_token_ranges(text, known) if ranges is None else ranges:
        spans += [Span(text[at:start], style), Span(text[start:end], token_style)]
        at = end
    spans.append(Span(text[at:], style))
    return tuple(span for span in spans if span.text)


def catalog_pairs(catalog: Mapping[str, object]) -> list[tuple[str, str]]:
    """The `(name, summary)` pairs out of a `commands.catalog` result; malformed rows are skipped."""
    pairs = catalog.get("pairs")
    if not isinstance(pairs, list):
        return []
    return [
        (pair[0], pair[1])
        for pair in pairs
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(part, str) for part in pair)
    ]


def catalog_categories(catalog: Mapping[str, object]) -> list[tuple[str, list[str]]]:
    """`(category, command names)` out of a `commands.catalog` result, for `/help`.

    Hermes leaves skills out of its categories (`skill_count` counts them).
    A command the TUI runs itself, routes to Hermes' terminal or drops is left
    out as completion leaves it out, and a category left with none is dropped.
    """
    categories = catalog.get("categories")
    rows: list[tuple[str, list[str]]] = []
    for category in categories if isinstance(categories, list) else []:
        name = category.get("name") if isinstance(category, dict) else None
        if not isinstance(name, str):
            continue
        names = [
            pair_name
            for pair_name, _summary in catalog_pairs(category)
            if pair_name.lstrip("/").lower() not in _BY_NAME
        ]
        if names:
            rows.append((name, names))
    return rows


def catalog_skill_count(catalog: Mapping[str, object]) -> int:
    """How many skill commands a `commands.catalog` result says Hermes has; 0 when it does not say."""
    count = catalog.get("skill_count")
    return count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 0
