"""What the waiting row waits on (the owner, 2026-11-19): a verb and a short detail for each wait, read from structure
only, never from what the model said.

The waiting row above the composer (`App._pending_wait`, `App._tail`) said
`✻ Waiting… (33m 47s · 1 agent · terminal)` for every wait. It now names the
longest one: `✻ Waiting for CI… (38m · #2975 · +1 test run · 1 agent)`. Three
structures name it:

* a background process Hermes will wake the session for: its command
  (`BackgroundProcess.command`, from Hermes' `processes.json`), of which only
  the words in command position of each `&&`, `||`, `;`, `|` segment count, after
  `cd …`, `export …`, `unset …`, leading `VAR=value` assignments and wrappers
  (`uv run`, `uvx`, `npx`, `pnpm exec`, `bunx`, `poetry run`, `bash`/`sh` running a
  script, `time`, `nice`, `env`) are skipped (`classify`); a word that only
  appears as an argument (`echo pytest`, `grep build`) names nothing;
* a process Hermes wakes on a matching line: the first pattern its `terminal`
  result armed (`watching`);
* the delegation graph's lanes the HUD reads: a dag-ulw run by its name and its
  nodes' states (`dag_wait`), a single child by its category or role (`lane_wait`).

Nothing here reads a file or sends anything; the app passes what it already holds.
Provider-side waits (a retry, a fallback switch, a reconnect) are not named.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import posixpath
import re
import shlex
from typing import Any

from ..plugin_bundle.omh.hud_text import elapsed_text
from .markdown import clean_text
from .width import truncate

# Kinds, in the priority a command's segments are matched in: the first kind any segment matches wins.
CI = "ci"
DEPLOY = "deploy"
TEST = "test"
BUILD = "build"
INSTALL = "install"
RENDER = "render"
PUSH = "push"
DOWNLOAD = "download"
SLEEP = "sleep"
WATCH = "watch"
RUN = "run"  # a dag-ulw run
REVIEW = "review"
RESEARCH = "research"
WRITING = "writing"
AGENT = "agent"

VERBS = {CI: "Waiting for CI", DEPLOY: "Deploying", TEST: "Testing", BUILD: "Building", INSTALL: "Installing",
         RENDER: "Rendering", PUSH: "Pushing", DOWNLOAD: "Downloading", SLEEP: "Sleeping", REVIEW: "Reviewing",
         RESEARCH: "Researching", WRITING: "Writing", AGENT: "Running agent"}
# What the end line calls a wait (`✓ Review finished (3m 2s)`); a run is called by its name, a watch by `Watch`.
LABELS = {CI: "CI", DEPLOY: "Deploy", TEST: "Tests", BUILD: "Build", INSTALL: "Install", RENDER: "Render",
          PUSH: "Push", DOWNLOAD: "Download", SLEEP: "Sleep", WATCH: "Watch", REVIEW: "Review", RESEARCH: "Research",
          WRITING: "Writing", AGENT: "Agent"}
# How the row counts the waits after the first: `+1 test run`, `+2 builds`. Agents keep `N agents`.
NOUNS = {CI: ("CI wait", "CI waits"), DEPLOY: ("deploy", "deploys"), TEST: ("test run", "test runs"),
         BUILD: ("build", "builds"), INSTALL: ("install", "installs"), RENDER: ("render", "renders"),
         PUSH: ("push", "pushes"), DOWNLOAD: ("download", "downloads"), SLEEP: ("sleep", "sleeps"),
         WATCH: ("watch", "watches")}
COUNT_ORDER = (CI, DEPLOY, TEST, BUILD, INSTALL, RENDER, PUSH, DOWNLOAD, SLEEP, WATCH)

PATTERN_CELLS = 24  # a watched pattern in `Watching for "<pattern>"`, cut with `…`
NAME_CELLS = 32  # a dag run's name in `Running <name>`
MODEL_CELLS = 32  # a child's model as the detail
# Research is the routes whose work is looking things up (`orchestration_say.ROUTE_PURPOSE_PHRASES`).
RESEARCH_CATEGORIES = frozenset({"research", "google-search", "x-search"})
RUNNING_STATES = ("running", "stuck")

CHAIN = frozenset({"&&", "||", ";", "|", "&", "|&", ";;"})
SKIPPED = frozenset({"cd", "export", "unset", "pushd", "popd"})  # a segment that only sets up: names nothing
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
NUMBER = re.compile(r"#?(\d{1,7})")
DURATION = re.compile(r"(\d+(?:\.\d+)?)([smh]?)")
PYTHON = re.compile(r"python(\d+(\.\d+)?)?")
# Wrapper options that take a value in the next word (`uv run --with x pytest`).
VALUE_OPTIONS = frozenset({"--with", "--with-requirements", "--project", "--directory", "--python", "-p", "--package",
                           "--extra", "--group", "--env-file", "--from", "--index", "--index-url", "-n", "-u", "-C",
                           "--filter", "-F", "--workspace", "-w", "--prefix", "--adjustment"})
NODES = ("npm", "pnpm", "yarn", "bun")


@dataclass(frozen=True)
class WaitKind:
    """What one wait is: its kind, the row's verb, what the end line calls it, and a short detail (`#2975`,
    `3/7 nodes`, `12s left`); the detail is empty where nothing is known."""

    kind: str
    verb: str
    label: str
    detail: str = ""


@dataclass(frozen=True)
class Wait:
    """One thing the session waits on between turns: a background process (`key` its process id) or the running
    lanes of one delegated wait (`lanes` the graph's node ids: one child, or a dag run's running nodes)."""

    key: str
    seconds: float
    kind: WaitKind | None
    lanes: tuple[str, ...] = ()

    @property
    def agent(self) -> bool:
        return bool(self.lanes)


def _words(command: str) -> list[str]:
    """The command's shell words with `&&`, `||`, `;`, `|` as words of their own; a line shlex cannot read (an open
    quote) is split on blanks."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def _segments(command: str) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for word in _words(command):
        if word in CHAIN:
            segments.append([])
        elif word in ("(", ")", "{", "}"):
            continue
        else:
            segments[-1].append(word)
    return [segment for segment in segments if segment]


def _skip_options(words: list[str], at: int) -> int:
    """The index of the first word at or after `at` that is not a wrapper option (or an option's value)."""
    while at < len(words) and words[at].startswith("-") and words[at] != "-":
        at += 2 if words[at] in VALUE_OPTIONS else 1
    return at


def command_words(segment: list[str]) -> list[str]:
    """A segment's words from its command on: leading assignments and wrappers dropped; [] for a segment that only
    sets up (`cd`, `export`, `unset`)."""
    words = list(segment)
    while True:
        at = 0
        while at < len(words) and ASSIGNMENT.match(words[at]):
            at += 1
        words = words[at:]
        if not words or words[0] in SKIPPED:
            return []
        head = words[0]
        if head in ("time", "nice", "env", "uvx", "npx", "bunx", "command", "exec", "nohup"):
            words = words[_skip_options(words, 1):]
        elif head in ("uv", "poetry") and words[1:2] == ["run"]:
            words = words[_skip_options(words, 2):]
        elif head == "pnpm" and words[1:2] == ["exec"]:
            words = words[_skip_options(words, 2):]
        elif head in ("bash", "sh", "zsh") and len(words) > 1 and not words[1].startswith("-"):
            words = words[1:]  # the script it runs is the command
        else:
            return words


def _base(word: str) -> str:
    return posixpath.basename(word)


def _number(args: Sequence[str]) -> str:
    """`#<n>` for the first argument that is a PR number, else ""."""
    for arg in args:
        found = NUMBER.fullmatch(arg)
        if found:
            return f"#{found.group(1)}"
    return ""


def _python_module(words: list[str]) -> list[str]:
    """`python -m <module> …` as [<module>, …]; [] when the command is not a python running a module."""
    if not PYTHON.fullmatch(_base(words[0])):
        return []
    at = 1
    while at < len(words) and words[at].startswith("-"):
        if words[at] == "-m":
            return words[at + 1:]
        at += 2 if words[at] in ("-X", "-W") else 1
    return []


def _git(words: list[str]) -> str:
    """The git subcommand, past `-C <dir>` and `-c <key=value>`."""
    at = 1
    while at < len(words) and words[at].startswith("-"):
        at += 2 if words[at] in ("-C", "-c") else 1
    return words[at] if at < len(words) else ""


def _match(kind: str, words: list[str]) -> str | None:
    """The detail when `words` (a segment from its command on) is a `kind` wait, else None."""
    head, rest = _base(words[0]), words[1:]
    sub = rest[0] if rest else ""
    pair = rest[:2]
    module = _python_module(words)
    if kind == CI:
        if head == "gh" and pair in (["pr", "checks"], ["pr", "merge"]):
            return _number(rest[2:])
        if head == "gh" and pair == ["run", "watch"]:
            return ""  # a run id, not a PR number
        if head in ("merge_when_green.sh", "merge_train.sh"):
            return _number(rest)
    elif kind == DEPLOY:
        if head == "vercel" or head in ("fly", "flyctl", "wrangler", "netlify") and sub == "deploy" or (
                head == "kubectl" and sub == "rollout"):
            return ""
    elif kind == TEST:
        if head in ("pytest", "vitest", "jest", "run_test_modules.sh") or module[:1] in (["pytest"], ["unittest"]):
            return ""
        if head in NODES and (sub == "test" or sub == "run" and rest[1:2] and rest[1].startswith("test")):
            return ""
        if head in ("cargo", "go") and sub == "test":
            return ""
    elif kind == BUILD:
        if head in NODES and sub == "run" and rest[1:2] and rest[1].startswith("build"):
            return ""
        if head in ("cargo", "go", "vite", "docker", "tauri") and sub == "build" or head in ("tsc", "make", "gmake"):
            return ""
    elif kind == INSTALL:
        if head == "uv" and (sub == "sync" or pair == ["pip", "install"]):
            return ""
        if head in ("pip", "pip3", "brew", "cargo") and sub == "install" or module[:2] == ["pip", "install"]:
            return ""
        if head in NODES and sub in ("install", "i", "add", "ci"):
            return ""
    elif kind == RENDER:
        if head in ("ffmpeg", "manim") or head == "hyperframes" and sub == "render" or (
                head == "blender" and ("-b" in rest or "--background" in rest)):
            return ""
    elif kind == PUSH:
        if head == "git" and _git(words) == "push":
            return ""
    elif kind == DOWNLOAD:
        if head == "git" and _git(words) in ("clone", "fetch", "pull") or head == "wget":
            return ""
        if head in ("hf", "huggingface-cli") and sub == "download":
            return ""
        if head == "curl" and any(arg in ("--output", "--remote-name", "--remote-name-all")
                                  or arg.startswith("-") and not arg.startswith("--") and ("o" in arg or "O" in arg)
                                  for arg in rest):
            return ""
    return None


def _sleep_seconds(words: list[str]) -> float | None:
    if len(words) != 2 or words[0] != "sleep":
        return None
    found = DURATION.fullmatch(words[1])
    if found is None:
        return None
    return float(found.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[found.group(2)]


def classify(command: str, *, started_at: float | None = None, now: float | None = None) -> WaitKind | None:
    """What a background process's command waits on, or None (the row then says plain `Waiting`). The first kind in
    priority order that any segment matches wins (`gh pr checks 1 && pytest` waits for CI). `sleep N` counts only as
    the whole command; its detail is the time left from `started_at` to `now`, never below zero."""
    segments = [words for words in (command_words(segment) for segment in _segments(command)) if words]
    if not segments:
        return None
    for kind in (CI, DEPLOY, TEST, BUILD, INSTALL, RENDER, PUSH, DOWNLOAD):
        for words in segments:
            detail = _match(kind, words)
            if detail is not None:
                return WaitKind(kind, VERBS[kind], LABELS[kind], detail)
    seconds = _sleep_seconds(segments[0]) if len(segments) == 1 else None
    if seconds is None:
        return None
    detail = ""
    if started_at is not None and now is not None:
        detail = f"{_clock(max(0.0, started_at + seconds - now))} left"
    return WaitKind(SLEEP, VERBS[SLEEP], LABELS[SLEEP], detail)


def _clock(seconds: float) -> str:
    """As `hud_text.elapsed_text`, rounded up so a sleep never reads `0s left` while it still runs."""
    return elapsed_text(-(-seconds // 1))


def watching(pattern: str) -> WaitKind:
    """`Watching for "<pattern>"`: a process Hermes wakes the session for on a matching line."""
    shown = truncate(clean_text(pattern), PATTERN_CELLS)
    return WaitKind(WATCH, f'Watching for "{shown}"', LABELS[WATCH])


def lane_wait(lane: Mapping[str, Any]) -> WaitKind:
    """A single delegated child by its category or its dag role: reviewing, researching, writing, else running an
    agent; the detail is the model Hermes recorded for it, when one is."""
    category, role = str(lane.get("category") or ""), str(lane.get("role") or "")
    kind = (REVIEW if REVIEW in (category, role) else RESEARCH if category in RESEARCH_CATEGORIES
            else WRITING if category == WRITING else AGENT)
    model = str(lane.get("model") or "")
    detail = truncate(clean_text(model), MODEL_CELLS) if model and model != "?" else ""
    return WaitKind(kind, VERBS[kind], LABELS[kind], detail)


def dag_wait(name: str, lanes: Sequence[Mapping[str, Any]]) -> WaitKind:
    """`Running <run name>` with `<done>/<total> nodes`, and `· <k> failed` when any failed, from the run's lanes'
    graph states."""
    shown = truncate(clean_text(name), NAME_CELLS) or "dag run"
    states = [lane.get("state") for lane in lanes]
    detail = f"{states.count('done')}/{len(states)} nodes"
    failed = states.count("failed")
    if failed:
        detail = f"{detail} · {failed} failed"
    return WaitKind(RUN, f"Running {shown}", shown, detail)


def count_words(waits: Sequence[Wait]) -> list[str]:
    """The waits after the first, counted: `+N <noun>` for each named process kind in priority order, then
    `N agent(s)` for the lanes, then the unnamed processes as `terminal`/`N terminals`."""
    words: list[str] = []
    named = [wait.kind.kind for wait in waits if not wait.agent and wait.kind is not None]
    for kind in COUNT_ORDER:
        count = named.count(kind)
        if count:
            words.append(f"+{count} {NOUNS[kind][count != 1]}")
    agents = sum(len(wait.lanes) for wait in waits)
    words += [agents_text(agents)] if agents else []
    plain = sum(1 for wait in waits if not wait.agent and wait.kind is None)
    words += [terminals_text(plain)] if plain else []
    return words


def agents_text(count: int) -> str:
    return f"{count} agent{'' if count == 1 else 's'}"


def terminals_text(count: int) -> str:
    return "terminal" if count == 1 else f"{count} terminals"


def plain_counts(waits: Sequence[Wait]) -> list[str]:
    """The waits counted in the row's words of before (`1 agent · terminal`): lanes, then processes."""
    agents = sum(len(wait.lanes) for wait in waits)
    terminals = sum(1 for wait in waits if not wait.agent)
    return ([agents_text(agents)] if agents else []) + ([terminals_text(terminals)] if terminals else [])
