"""Bounded local proofreading of the draft in the composer.

With OMH_PROOFREAD=1 the App checks after 600 ms quiet, showing inline marks.
Alt+P opens only the issue at the cursor. Nothing is applied without an explicit
Enter on a replacement, and no submit ever follows. App owns scheduling and
foreground state; this client has no automatic server installation or startup.

What keeps the read narrow (`docs/OMH-TUI-BOUNDARY.md`, "Proofreading"):

* One endpoint, `OMH_PROOFREAD_URL`, default `http://127.0.0.1:8081/v2/check`.
  Plain `http` to a loopback IP literal (or `localhost`, connected as
  127.0.0.1) only, no credentials, no query. `http.client` is used directly, so
  no proxy variable is read and a 3xx is an error, never followed.
* Stdlib only; one daemon worker thread, at most one request pending, a
  `TIMEOUT_SECONDS` socket timeout and a `MAX_RESPONSE_BYTES` cap. The screen's
  thread never waits: the loop takes the outcome (`Worker.take`).
* What is sent is the draft with its protected spans blanked: slash and `!`
  command lines, fenced and inline code, image tokens and paste chips. Blanking
  keeps every other character where it was, so LanguageTool's UTF-16 offsets map
  back to the draft through `Protected.units` and `Protected.origin`. A paste's
  text is never expanded. A masked composer sends nothing, and a draft with
  nothing left to read sends nothing.
* An outcome applies only to the draft it was asked of: `Snapshot` binds the
  composer object, its edit generation, its text, its chip and image metadata
  and who owns it (session, question). Text equality alone is not enough, since
  an edit away and back is the same text and a different draft.
* The dictionary (`DICTIONARY_FILE` under the OMH home) is read and saved only
  on `DictionaryTask`'s short-lived thread, never on the screen's: a file that
  is not regular (a FIFO, a symlink) is refused without waiting on it, and a
  save rereads under the lock before its atomic replacement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import threading
import time
import unicodedata
from urllib.parse import urlencode, urlsplit

from ..system.local_store import atomic_write_text, file_lock
from .composer import Composer, _is_token
from .keys import CHAR, DOWN, ENTER, ESCAPE, UP, Key, Paste, list_nav_step
from .session_picker import picker_row
from .style import Line, Span
from .theme import Theme
from .width import truncate_line

URL_ENV = "OMH_PROOFREAD_URL"
LANGUAGE_ENV = "OMH_PROOFREAD_LANGUAGE"
DEFAULT_URL = "http://127.0.0.1:8081/v2/check"
DEFAULT_LANGUAGE = "auto"
TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 512 * 1024
MAX_TEXT_CHARS = 20000  # client-side draft limit
MAX_REPLACEMENT_CHARS = 200
MAX_ISSUES = 50
ARM_SECONDS = 0.3  # keys this soon after a review opens are swallowed: a late Enter must not accept one

MASKED_NOTICE = "Proofread skips masked input."
NOTHING_NOTICE = "Nothing to proofread in this draft."
TOO_LONG_NOTICE = "This draft is too long to proofread."
BUSY_NOTICE = "Proofread is already checking a draft."
START_NOTICE = "Proofreading this draft locally…"
STALE_NOTICE = "Proofread dropped: the draft changed."
CLEAN_NOTICE = "Proofread: nothing to fix."
DONE_NOTICE = "Proofread: done."
CANCEL_NOTICE = "Proofread cancelled."

DICTIONARY_FILE = Path("proofread") / "dictionary.txt"
DICTIONARY_LIMIT = 64 * 1024
DICTIONARY_KEY_LIMIT = 100  # code points of the saved (folded) word, so every key that is written reads back
DICTIONARY_ERROR = "Could not update the local dictionary"
UNKNOWN: tuple = ()  # the fingerprint of a dictionary not read yet; matches no file
HINT_CORRECT = "Alt+P corrects at cursor"
HINT_ADD = "Alt+P adds word to dictionary"
HINT_REMOVE = "Alt+P removes word from dictionary"
ADD_WORD = "Add to dictionary"
REMOVE_WORD = "Remove from dictionary"
CANCEL = "Cancel"
KEYS = ("↑↓ move · enter picks · esc cancels", "↑↓ enter picks · esc cancels", "esc cancels")

_LANGUAGE = re.compile(r"^(auto|[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*)$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CONTAINER = re.compile(r"^ {0,3}(?:>[ \t]?|[-+*][ \t]|\d+[.)][ \t])")
_BACKTICKS = re.compile(r"`+")


class ProofreadError(Exception):
    """A reason the check cannot run or its answer cannot be used; its text is shown to the person."""


# ── endpoint ──


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    path: str
    language: str


def endpoint(environ: Mapping[str, str]) -> Endpoint:
    """The server to ask, from the environment: loopback only, plain http, no credentials."""
    url = (environ.get(URL_ENV) or DEFAULT_URL).strip()
    language = (environ.get(LANGUAGE_ENV) or DEFAULT_LANGUAGE).strip()
    if not _LANGUAGE.match(language):
        raise ProofreadError(f"{LANGUAGE_ENV} is not a language code.")
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise ProofreadError(f"{URL_ENV} is not a URL.") from None
    if parts.scheme != "http" or host is None or port is None:
        raise ProofreadError(f"{URL_ENV} must be http://<loopback>:<port>/path.")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ProofreadError(f"{URL_ENV} may carry no credentials, query or fragment.")
    if host == "localhost":
        host = "127.0.0.1"
    else:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ProofreadError(f"{URL_ENV} must name a loopback address.")
    return Endpoint(host, port, parts.path or "/", language)


# ── protected spans ──


@dataclass(frozen=True)
class Protected:
    """The draft as it is sent, and how to get back to the draft from what the server says."""

    sent: str  # the draft with every protected character blanked by as many UTF-16 units of spaces
    origin: tuple[int, ...]  # per character of `sent`: the draft index it stands for
    units: Mapping[int, int]  # UTF-16 offset in `sent` -> index in `sent` (a boundary between characters)
    blocked: tuple[bool, ...]  # per character of the draft: protected
    readable: bool  # something unprotected is left that a person would read


def _blocked(text: str, chips: list[tuple[int, int]]) -> list[bool]:
    mask = [False] * len(text)
    for start, end in chips:
        mask[start:end] = [True] * (end - start)
    for index, char in enumerate(text):
        if _is_token(char):
            mask[index] = True
    position, fence = 0, ""
    fence_quotes = 0
    for line in text.split("\n"):
        start, end = position, position + len(line)
        position = end + 1
        # Expand at original columns before slicing prefixes; detection only.
        content = line.expandtabs(4)
        raw_content = line
        quotes, list_marker = 0, False
        while True:
            # Inspect every remainder before another marker can consume its indent.
            indented = content.startswith("    ") or raw_content.expandtabs(4).startswith("    ")
            container = None if indented else _CONTAINER.match(content)
            if container is None:
                break
            prefix = container.group().lstrip()
            quotes += prefix.startswith(">")
            list_marker |= not prefix.startswith(">")
            content = content[container.end():]
            # Retain the existing conservative tab-indent exclusions too.
            raw_container = _CONTAINER.match(raw_content)
            raw_content = raw_content[raw_container.end():] if raw_container else ""
        marker = None if indented else _FENCE.match(content)
        protect = False
        if fence:
            protect = True
            if (marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence)
                    and not content[marker.end():].strip() and quotes == fence_quotes and not list_marker):
                fence = ""
        elif marker:
            fence, protect = marker.group(1), True
            fence_quotes = quotes
        elif indented or any(part.lstrip()[:1] in ("/", "!")
                 for part in (line, content)):
            protect = True
        if protect:
            mask[start:end] = [True] * (end - start)
    cursor = 0
    while found := _BACKTICKS.search(text, cursor):
        if mask[found.start()]:
            cursor = found.end()
            continue
        end = len(text)  # an unclosed span protects the rest conservatively
        for closing in _BACKTICKS.finditer(text, found.end()):
            if closing.group() == found.group():
                end = closing.end()
                break
        mask[found.start():end] = [True] * (end - found.start())
        cursor = end
    return mask


def protect(text: str, chips: list[tuple[int, int]]) -> Protected:
    mask = _blocked(text, chips)
    sent: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        if mask[index] and char != "\n":
            width = 2 if ord(char) > 0xFFFF else 1  # the server counts UTF-16 units
            sent.append(" " * width)
            origin.extend([index] * width)
        else:
            sent.append(char)
            origin.append(index)
    joined = "".join(sent)
    units: dict[int, int] = {}
    offset = 0
    for index, char in enumerate(joined):
        units[offset] = index
        offset += 2 if ord(char) > 0xFFFF else 1
    units[offset] = len(joined)
    readable = any(not mask[i] and text[i].isalnum() for i in range(len(text)))
    return Protected(joined, tuple(origin), units, tuple(mask), readable)


# ── what a draft was when it was asked about ──


@dataclass(frozen=True, eq=False)
class Snapshot:
    composer: Composer
    generation: int
    text: str
    masked: bool
    metadata: tuple
    owner: tuple

    @staticmethod
    def _metadata(composer: Composer) -> tuple:
        return (tuple(sorted(composer.pastes.items())), tuple(sorted((k, v[0]) for k, v in composer.images.items())))

    @classmethod
    def capture(cls, composer: Composer, owner: tuple) -> Snapshot:
        return cls(composer, composer._generation, composer.text, composer.masked, cls._metadata(composer), owner)

    def matches(self, composer: Composer, owner: tuple) -> bool:
        return (
            composer is self.composer and composer._generation == self.generation and composer.text == self.text
            and composer.masked == self.masked and self._metadata(composer) == self.metadata and owner == self.owner
        )


# ── the question and its answer ──


@dataclass(frozen=True, eq=False)
class Job:
    endpoint: Endpoint
    protected: Protected
    original: str
    snapshot: Snapshot


def prepare(composer: Composer, owner: tuple, environ: Mapping[str, str]) -> Job | str:
    """The job for this draft, or the notice saying why there is none. No request is made here."""
    if composer.masked:
        return MASKED_NOTICE
    try:
        where = endpoint(environ)
    except ProofreadError as error:
        return str(error)
    if len(composer.text) > MAX_TEXT_CHARS:
        return TOO_LONG_NOTICE
    protected = protect(composer.text, composer._chip_spans())
    if not protected.readable:
        return NOTHING_NOTICE
    return Job(where, protected, composer.text, Snapshot.capture(composer, owner))


def post_check(where: Endpoint, sent: str) -> Mapping[str, object]:
    """One POST to the server; the decoded reply. `http.client` follows no redirect and reads no proxy variable."""
    body = urlencode({"text": sent, "language": where.language}).encode()
    connection = http.client.HTTPConnection(where.host, where.port, timeout=TIMEOUT_SECONDS)
    started = time.monotonic()
    deadline = None
    expired = threading.Event()
    try:
        connection.connect()
        wire = connection.sock

        def interrupt() -> None:
            expired.set()
            try:
                wire.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # the request may already have closed its socket

        deadline = threading.Timer(max(0.0, TIMEOUT_SECONDS - (time.monotonic() - started)), interrupt)
        deadline.daemon = True
        deadline.start()
        connection.request("POST", where.path, body, {
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
        })
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ProofreadError("The proofread server redirected; redirects are refused.")
        if response.status != 200:
            raise ProofreadError(f"The proofread server answered {response.status}.")
        length = response.getheader("Content-Length")
        if length is not None and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
            raise ProofreadError("The proofread server's reply is too large.")
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if expired.is_set():
            raise ProofreadError("The proofread server exceeded the request deadline.")
    except ProofreadError:
        raise
    except (OSError, http.client.HTTPException) as error:
        raise ProofreadError(f"The proofread server is unavailable ({type(error).__name__}).") from None
    finally:
        if deadline is not None:
            deadline.cancel()
        connection.close()
    if len(data) > MAX_RESPONSE_BYTES:
        raise ProofreadError("The proofread server's reply is too large.")
    try:
        payload = json.loads(data)
    except ValueError:
        raise ProofreadError("The proofread server's reply is not JSON.") from None
    if not isinstance(payload, dict):
        raise ProofreadError("The proofread server's reply is not an object.")
    return payload


def word_key(text: str) -> str | None:
    """The dictionary key of one word of letters (and their combining marks): NFC, casefolded. None for anything
    else, and for a word whose folded key is longer than `DICTIONARY_KEY_LIMIT` (`ß` folds to `ss`), so a key that
    is offered and saved always reads back."""
    word = unicodedata.normalize("NFC", text)
    if not (0 < len(word) <= DICTIONARY_KEY_LIMIT and word[0].isalpha() and all(
        char.isalpha() or unicodedata.category(char).startswith("M") for char in word
    )):
        return None
    key = unicodedata.normalize("NFC", word.casefold())
    return key if len(key) <= DICTIONARY_KEY_LIMIT else None


def read_dictionary(path: Path, known: tuple | None = UNKNOWN) -> tuple[frozenset[str], tuple | None] | None:
    """The saved words and the file's fingerprint (None: no file), or None when the fingerprint is still `known`.

    Only a regular file is read: a symlink is not followed and a FIFO is opened without waiting for a writer and
    then refused, as `history.load_history` does. Too large, not UTF-8 or a bad entry raise ValueError."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None if known is None else (frozenset(), None)
    with os.fdopen(descriptor, "rb") as handle:  # closes the descriptor whatever happens below
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("dictionary is not a regular file")
        fingerprint = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if fingerprint == known:
            return None
        data = handle.read(DICTIONARY_LIMIT + 1)
    if len(data) > DICTIONARY_LIMIT:
        raise ValueError("dictionary is too large")
    entries = [word_key(line) for line in data.decode("utf-8").splitlines()]
    if any(word is None for word in entries):
        raise ValueError("invalid dictionary entry")
    return frozenset(word for word in entries if word is not None), fingerprint


def update_dictionary(path: Path, word: str, *, add: bool) -> tuple[frozenset[str], tuple | None]:
    """Add or remove one key; the words saved after it and the fingerprint to compare a later read with."""
    if word_key(word) != word:
        raise ValueError("not a dictionary key")
    sidecar = path.with_name(f".{path.name}.lock")
    try:
        mode = os.lstat(sidecar).st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(mode):  # opening a FIFO to lock it would wait for a reader
            raise ValueError("dictionary lock is not a regular file")
    # Reread under the lock so an already-open TUI cannot erase another TUI's changes.
    with file_lock(path, private=True, timeout_seconds=0.15) as lock:
        if not lock["enforced"]:
            raise OSError("dictionary lock unavailable")
        before, fingerprint = read_dictionary(path) or (frozenset(), None)
        words = before | {word} if add else before - {word}
        if words != before:
            text = "".join(entry + "\n" for entry in sorted(words))
            if len(text.encode("utf-8")) > DICTIONARY_LIMIT:
                raise ValueError("dictionary is too large")
            atomic_write_text(path, text, private=True)
            fingerprint = UNKNOWN  # the next refresh reads what was written
    return words, fingerprint


class DictionaryTask:
    """Dictionary reads and saves on one short-lived daemon thread at a time; the loop takes the result and never
    waits on the file or its lock. The result is (True, value) or (False, None) for an OSError or ValueError."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._outcome: tuple[bool, object] | None = None
        self._started = False

    @property
    def pending(self) -> bool:
        return self._started

    def start(self, run: Callable[[], object], wake: Callable[[], None] | None = None) -> bool:
        with self._lock:
            if self._started:
                return False
            self._started = True
        self._thread = threading.Thread(target=self._run, args=(run, wake), name="omh-proofread-dictionary",
                                        daemon=True)
        self._thread.start()
        return True

    def _run(self, run: Callable[[], object], wake: Callable[[], None] | None) -> None:
        outcome: tuple[bool, object] = (False, None)  # what anything else leaves, after the thread's fault hook
        try:
            outcome = (True, run())
        except (OSError, ValueError):
            outcome = (False, None)  # said as DICTIONARY_ERROR for a save; a read keeps what was known
        finally:
            with self._lock:
                self._outcome = outcome
            if wake is not None:
                wake()

    def take(self) -> tuple[bool, object] | None:
        with self._lock:
            outcome, self._outcome = self._outcome, None
            if outcome is not None:
                self._started = False
        return outcome

    def wait(self, timeout: float = 5.0) -> None:
        """For tests: until the thread is done."""
        if self._thread is not None:
            self._thread.join(timeout)


@dataclass(frozen=True)
class Issue:
    start: int  # in the draft, Python indices
    end: int
    original: str
    message: str
    replacements: tuple[str, ...]
    word: str | None = None  # normalized dictionary key for a single-word spelling diagnostic


def issues_from(payload: Mapping[str, object], job: Job) -> list[Issue]:
    """The candidates the draft can take, in draft order: each mapped from UTF-16 back to the draft, none touching a
    protected character, none without a replacement or dictionary key. Overlaps stay: `corrections` and `spellings`
    reduce them, so a spelling with no replacement never pushes a correction out."""
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise ProofreadError("The proofread server's reply has no matches.")
    protected, found = job.protected, []
    for match in matches[:MAX_ISSUES * 4]:
        if not isinstance(match, dict):
            continue
        offset, length, message = match.get("offset"), match.get("length"), match.get("message")
        if (not isinstance(offset, int) or isinstance(offset, bool) or not isinstance(length, int)
                or isinstance(length, bool) or length <= 0):
            continue
        first, last = protected.units.get(offset), protected.units.get(offset + length)
        if first is None or last is None or last <= first:
            continue
        start, end = protected.origin[first], protected.origin[last - 1] + 1
        if any(protected.blocked[start:end]):
            continue
        original = job.original[start:end]
        raw = match.get("replacements")
        values: list[str] = []
        for item in raw if isinstance(raw, list) else []:
            value = item.get("value") if isinstance(item, dict) else None
            if (isinstance(value, str) and value != original and value not in values
                    and len(value) <= MAX_REPLACEMENT_CHARS and not any(_is_token(c) for c in value)):
                values.append(value)
        rule = match.get("rule")
        word = word_key(original) if isinstance(rule, dict) and rule.get("issueType") == "misspelling" else None
        if values or word is not None:
            found.append(Issue(start, end, original, message if isinstance(message, str) else "", tuple(values), word))
    found.sort(key=lambda issue: issue.start)
    return found


def corrections(issues: Sequence[Issue], saved: frozenset[str] = frozenset()) -> list[Issue]:
    """The replacements shown, as before the dictionary: first span wins, at most `MAX_ISSUES`. A saved spelling
    drops out before the overlap test, so it never hides a correction it overlaps."""
    kept: list[Issue] = []
    for issue in issues:
        if issue.replacements and issue.word not in saved and (not kept or issue.start >= kept[-1].end):
            kept.append(issue)
    return kept[:MAX_ISSUES]


def spellings(issues: Sequence[Issue]) -> list[Issue]:
    """The single-word spellings a dictionary action can take, reduced and capped on their own."""
    kept: list[Issue] = []
    for issue in issues:
        if issue.word is not None and (not kept or issue.start >= kept[-1].end):
            kept.append(issue)
    return kept[:MAX_ISSUES]


@dataclass(frozen=True, eq=False)
class Outcome:
    job: Job
    issues: list[Issue] = field(default_factory=list)
    error: str = ""


class Worker:
    """One daemon thread, one request at a time; the loop takes the answer and never waits for it."""

    def __init__(self, post: Callable[[Endpoint, str], Mapping[str, object]] = post_check) -> None:
        self._post = post
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._outcome: Outcome | None = None
        self._started = False

    @property
    def pending(self) -> bool:
        return self._started

    def start(self, job: Job, wake: Callable[[], None] | None = None) -> bool:
        with self._lock:
            if self._started:
                return False
            self._started = True
        self._thread = threading.Thread(target=self._run, args=(job, wake), name="omh-proofread", daemon=True)
        self._thread.start()
        return True

    def _run(self, job: Job, wake: Callable[[], None] | None) -> None:
        try:
            outcome = Outcome(job, issues_from(self._post(job.endpoint, job.protected.sent), job))
        except ProofreadError as error:
            outcome = Outcome(job, error=str(error))
        except Exception as error:  # a raise on this thread would be lost; say what happened instead
            outcome = Outcome(job, error=f"Proofread failed ({type(error).__name__}).")
        with self._lock:
            self._outcome = outcome
        if wake is not None:
            wake()

    def take(self) -> Outcome | None:
        with self._lock:
            outcome, self._outcome = self._outcome, None
            if outcome is not None:
                self._started = False
        return outcome

    def wait(self, timeout: float = 5.0) -> None:
        """For tests: until the thread is done."""
        if self._thread is not None:
            self._thread.join(timeout)


# ── the review ──


@dataclass
class Review:
    """Cursor-targeted corrections, an optional dictionary action, and Cancel."""

    snapshot: Snapshot
    issues: list[Issue]
    armed_until: float = 0.0
    position: int = 0
    row: int = 0
    dictionary_action: str = ""
    word: str | None = None  # the dictionary key the action saves or removes

    @property
    def issue(self) -> Issue:
        return self.issues[self.position]

    @property
    def replacements(self) -> tuple[str, ...]:
        # The saved word's own replacements are not offered; a correction it overlaps keeps its own.
        hidden = self.dictionary_action == "remove_word" and self.issue.word == self.word
        return () if hidden else self.issue.replacements

    def choices(self) -> list[str]:
        rows = list(self.replacements)
        if self.dictionary_action:
            rows.append(ADD_WORD if self.dictionary_action == "add_word" else REMOVE_WORD)
        return [*rows, CANCEL]

    def handle_key(self, event: Key | Paste, now: float | None = None) -> tuple[str, str] | None:
        """Return a row action or None. Every key is swallowed: nothing is typed."""
        if isinstance(event, Paste):
            return None
        if event.name == ESCAPE or (event.name == CHAR and event.ctrl and event.char == "c"):
            return ("cancel", "")
        if (time.monotonic() if now is None else now) < self.armed_until:
            return None
        rows = self.choices()
        if event.name == ENTER and not (event.alt or event.shift or event.ctrl):
            if self.row < len(self.replacements):
                return ("accept", rows[self.row])
            return ("cancel" if self.row == len(rows) - 1 else self.dictionary_action, "")
        step = list_nav_step(event) or {UP: -1, DOWN: 1}.get(event.name, 0)
        if step:
            self.row = min(max(self.row + step, 0), len(rows) - 1)
        return None

    def advance(self) -> bool:
        """To the next correction; False when there is none."""
        self.position += 1
        self.row = 0
        return self.position < len(self.issues)

    def accepted(self, delta: int, snapshot: Snapshot) -> bool:
        """The correction at `position` went in, changing the draft's length by `delta`; the ones after it move with
        the text. False when none is left."""
        done = self.issues[self.position]
        later = [i for i in self.issues[self.position + 1:] if i.start >= done.end]
        self.issues[self.position + 1:] = [
            Issue(i.start + delta, i.end + delta, i.original, i.message, i.replacements, i.word) for i in later
        ]
        self.snapshot = snapshot
        return self.advance()

    def _context(self, composer: Composer, width: int, theme: Theme, radius: int = 28) -> Line:
        text, issue = composer.text, self.issue
        first, last = max(0, issue.start - radius), min(len(text), issue.end + radius)

        def shown(piece: str) -> str:
            return composer._labelled(piece).replace("\n", " ")

        return truncate_line((
            Span("  " + ("…" if first else ""), theme.muted), Span(shown(text[first:issue.start]), theme.text),
            Span(shown(text[issue.start:issue.end]), theme.warn), Span(shown(text[issue.end:last]), theme.text),
            Span("…" if last < len(text) else "", theme.muted),
        ), width)

    def lines(self, width: int, theme: Theme, max_rows: int, composer: Composer) -> list[Line]:
        if max_rows <= 0:
            return []
        rows = self.choices()
        head = truncate_line((Span(
            f" Proofread {self.position + 1}/{len(self.issues)} · {self.issue.message or 'Suggestion'}", theme.heading,
        ),), width)
        room = max(max_rows - 2, 1)
        start = min(max(self.row - room + 1, 0), max(len(rows) - room, 0))
        listed = [
            picker_row(n == self.row, "", row or "(delete)", "", width, theme)
            for n, row in enumerate(rows) if start <= n < start + room
        ]
        return ([head, self._context(composer, width, theme)] if max_rows >= 3 else [])[:max_rows] + listed[:max_rows]
