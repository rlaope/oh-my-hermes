"""Progress evidence for one dispatched unit (`omh_unit_progress/v1`).

Pure derivation, no I/O and no clock of its own: `assess_progress` takes the
stdout captured so far plus the previous evidence and returns what OMH has
observed about the WORK. It exists because every surface this repo already
has -- the in-flight marker, the progress binding, the status board, the run
summary -- could only say that a process existed. On 2026-09-11 a unit was
alive for 36 minutes retrying the same git workaround while its supervisor
read "PID alive" as progress; the stdout snapshots that would have shown the
repetition were already being taken and were never turned into a verdict.

Boundaries, in order of importance:

- Non-terminal only. `assess_progress` never returns `failed` or `verified`.
  Those are the intake path's answer after exit, where the result record and
  the verification ladder are what decide; a mid-run reading of stdout must
  not pre-empt them. Every state this module can return is in
  `UNIT_PROGRESS_MID_RUN_STATES`.
- Growing output is not progress. The incident's 36 minutes produced new
  bytes the whole time -- the same workaround, again. The repeated-line rule
  therefore outranks the byte-growth rule, and the byte-growth rule is the
  only thing that can produce `running`.
- Shape, never truth. A matched pattern says the tail LOOKS like a limit
  refusal, a permission denial, or a missing object. It is not provider
  state, not a filesystem verdict, and not repository truth. Only the state
  and a bounded reason string are produced; the matched text itself is
  carried no further than the reason, which is truncated.
- Deterministic. `now` is a parameter (a monotonic-clock reading, so a
  system clock step cannot fabricate a stall), the pattern tables are module
  constants, and the same inputs always give the same evidence.
- Reporting only. Evidence here is observed activity. It is never result,
  verification, review, CI, merge-readiness, or merge evidence.

`ProgressEvidence` is a plain dict so it can ride in an in-flight marker and
a dispatch record without a serializer. Its keys:

- `schema_version`     -- `UNIT_PROGRESS_SCHEMA_VERSION`.
- `observed_at`        -- the `now` of this assessment (monotonic seconds).
- `output_bytes`       -- length of the stdout seen so far.
- `output_lines`       -- line count of the stdout seen so far.
- `last_new_output_at` -- the `now` of the most recent assessment that saw
                          the byte count grow. Equal to `observed_at` on the
                          first assessment, so a fresh unit is never stalled.
- `repeated_line`      -- the canonical form of the tail's most repeated
                          non-empty line, or "" when nothing repeats.
- `repeat_count`       -- how many times that canonical line occurs in the
                          tail (0 when `repeated_line` is "").
- `phase_markers`      -- recognised markers seen in the whole output so far,
                          in `PHASE_MARKERS` order; cumulative, never shrinks.
- `result_record_present` -- the caller's own answer to "has the unit's
                          result record appeared yet?". Passed in, not
                          derived: this module does not touch the filesystem.
- `state`              -- one of `UNIT_PROGRESS_MID_RUN_STATES`.
- `reason`             -- short machine-readable why, or "" for `running`.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Final, Mapping

from .unit_execution_state import (
    UNIT_STATE_ACCOUNT_LIMIT,
    UNIT_STATE_AWAITING_INPUT,
    UNIT_STATE_DATA_MISSING,
    UNIT_STATE_PERMISSION_BLOCKED,
    UNIT_STATE_PROGRESS_STALLED,
    UNIT_STATE_RUNNING,
)

UNIT_PROGRESS_SCHEMA_VERSION: Final[str] = "omh_unit_progress/v1"

UNIT_PROGRESS_CLAIM_BOUNDARY: Final[str] = (
    "Progress evidence records what one unit's stdout showed at one moment: whether it grew, "
    "whether the same line is repeating, and whether its tail matches a limit, permission, or "
    "missing-object shape. A matched shape is not provider, filesystem, or repository truth, and "
    "no state here is terminal -- `failed` and `verified` come from the intake path after exit."
)

# Silence this long is a stall. Same number as
# `plugin_bundle.omh.tool_bursts.TOOL_CALL_OPEN_TTL_SECONDS` (15 minutes),
# which is that module's answer to the same question for a single tool call:
# past this, an open thing is not still running, it is a lost tick. Defined
# here rather than imported because that sibling lives in the plugin bundle
# and pulls the plugin's file-locking chain in with it; core stays pure.
UNIT_STALL_AFTER_SECONDS: Final[float] = 15 * 60.0

# How many times one canonical line must occur in the tail before repetition
# is a verdict rather than a coincidence. Three is the smallest count that
# cannot be a pair of adjacent identical log lines.
UNIT_REPEAT_THRESHOLD: Final[int] = 3

# How long output must have been still before a trailing question counts as a
# unit waiting on an answer. Without it the rule fires on one poll step (five
# seconds): a headless CLI that prints a sentence ending in "?" and then spends
# ten seconds inside a tool call would read as blocked on a human. Sixty
# seconds is well past any single tool call and well short of the stall
# threshold, so a real prompt is still caught fourteen minutes before silence
# alone would report it.
UNIT_PROMPT_QUIET_SECONDS: Final[float] = 60.0

# Lines of tail the repetition rule looks at. Long enough to hold several
# turns of a retry loop, short enough that an hour of unrelated output ahead
# of it cannot dilute the count.
_TAIL_LINES: Final[int] = 80

# Characters of tail the shape patterns below are matched against. A refusal,
# a denial, or a missing object is reported at the END of what the process
# managed to say; scanning the whole transcript would keep re-reporting a
# denial the unit already recovered from.
_TAIL_CHARS: Final[int] = 4000

# Bound on the repeated line carried into `reason`.
_REASON_LINE_LIMIT: Final[int] = 120

# Reasons this module produces, so a reader can branch on them without
# parsing prose. `REASON_REPEATED_ERROR` is a PREFIX: the offending line
# follows the colon.
REASON_NO_NEW_OUTPUT: Final[str] = "no_new_output"
REASON_REPEATED_ERROR_PREFIX: Final[str] = "repeated_error:"
REASON_PROMPT_AT_END: Final[str] = "prompt_at_end"
REASON_ACCOUNT_LIMIT_PREFIX: Final[str] = "account_limit:"
REASON_PERMISSION_PREFIX: Final[str] = "permission_blocked:"
REASON_DATA_MISSING_PREFIX: Final[str] = "data_missing:"

# Every state `assess_progress` can return. `failed` and `verified` are
# absent on purpose -- see the module docstring's first boundary.
UNIT_PROGRESS_MID_RUN_STATES: Final[tuple[str, ...]] = (
    UNIT_STATE_RUNNING,
    UNIT_STATE_AWAITING_INPUT,
    UNIT_STATE_PERMISSION_BLOCKED,
    UNIT_STATE_ACCOUNT_LIMIT,
    UNIT_STATE_DATA_MISSING,
    UNIT_STATE_PROGRESS_STALLED,
)

# Recognised phase markers, in report order. One row per thing that actually
# emits the pattern; matched case-insensitively over the whole output so far,
# so the list is cumulative for the unit's lifetime.
PHASE_MARKER_TEST_STARTED: Final[str] = "test_started"
PHASE_MARKER_TEST_FINISHED: Final[str] = "test_finished"
PHASE_MARKER_RESULT_WRITTEN: Final[str] = "result_written"
PHASE_MARKER_COMMIT_CREATED: Final[str] = "commit_created"

PHASE_MARKERS: Final[tuple[str, ...]] = (
    PHASE_MARKER_TEST_STARTED,
    PHASE_MARKER_TEST_FINISHED,
    PHASE_MARKER_RESULT_WRITTEN,
    PHASE_MARKER_COMMIT_CREATED,
)

# Every row is `(marker, pattern)`, matched case-insensitively and in
# multiline mode over the whole output so far.
_PHASE_MARKER_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    # pytest's own run banner, printed once as its first line.
    (PHASE_MARKER_TEST_STARTED, r"=+ test session starts"),
    # unittest's verbose start line for a test method, which is what
    # `python -m unittest -v` (this repo's own command) emits per test.
    (PHASE_MARKER_TEST_STARTED, r"^test\w* \(.+\) \.\.\. "),
    # unittest's footer: `Ran 12 tests in 0.412s`.
    (PHASE_MARKER_TEST_FINISHED, r"\bran \d+ tests? in "),
    # pytest's footer: `== 12 passed, 1 failed in 3.20s ==`.
    (PHASE_MARKER_TEST_FINISHED, r"\b\d+ (?:passed|failed|errors?) "),
    # The unit-return contract's own schema version
    # (`fanout_unit_results.FANOUT_UNIT_RESULT_SCHEMA_VERSION`). A worker
    # that wrote its sidecar has this string in the JSON it wrote, and the
    # executor profiles this lane spawns echo the file they wrote.
    (PHASE_MARKER_RESULT_WRITTEN, r"fanout_unit_result/v\d"),
    # `git commit` prints its own diffstat footer on success.
    (PHASE_MARKER_COMMIT_CREATED, r"\b\d+ files? changed"),
    # `git commit` also prints `[branch 1a2b3c4] subject` as its first line.
    (PHASE_MARKER_COMMIT_CREATED, r"^\[\S+ [0-9a-f]{7,64}\] "),
)

# Permission and sandbox denials. Retrying under the same permissions cannot
# clear any of these, which is why they are their own state rather than a
# stall to be waited out.
_PERMISSION_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    # The POSIX shell/tool message, and git's own wording for it.
    ("permission_denied", "permission denied"),
    # `errno.EACCES` surfaced by name, as Python and Node both do.
    ("eacces", "eacces"),
    # macOS/BSD wording for EPERM on a protected path.
    ("operation_not_permitted", "operation not permitted"),
    # A read-only bind mount or a sandbox's read-only isolation dir.
    ("read_only_filesystem", "read-only file system"),
)

# Objects the work needs are absent in its isolation. The 2026-09-11 recovery
# run hit these against a `blob:none` partial clone with fetch forbidden --
# the case retrying can never clear, because the bytes are not there.
_DATA_MISSING_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    # git's message when a partial clone's promisor fetch is refused.
    ("missing_blob", "missing blob"),
    # git's read failure for an object that is not in the object store.
    ("unreadable_object", "could not read object"),
    # The promisor remote itself failing, named explicitly by git.
    ("promisor_remote", "promisor"),
    # Fetching a ref the remote does not advertise (a partial/filtered clone
    # that was described as complete).
    ("ref_not_advertised", "not our ref"),
    # git's verdict when an object id resolves to nothing at all.
    ("bad_object", "fatal: bad object"),
)

# Words that make a line a report of something going WRONG. The repeat rule
# counts only lines matching one of these, because the incident's signal was
# the same FAILURE repeating -- not repetition as such. Healthy runs repeat
# lines constantly: verbose unittest prints `... ok` once per test, pytest
# prints `PASSED`, a compiler prints one warning per file, and the digit
# collapse above folds `test (3.11, 0)` and `test (3.12, 1)` into one line. Any
# of those would otherwise pin a green run at `progress_stalled` for the rest
# of its life, since this rule outranks `running`.
#
# Matched case-insensitively as substrings of the canonical line. One row per
# thing that emits it; the table is deliberately small, because a word added
# here silently converts a class of healthy output into a stall verdict.
_FAILURE_SHAPED_WORDS: Final[tuple[tuple[str, str], ...]] = (
    # git, compilers, and most CLIs prefix a diagnostic line with these.
    ("error", "error"),
    ("fatal", "fatal"),
    # Test runners and build tools reporting a failed step.
    ("failed", "failed"),
    ("failure", "failure"),
    # Permission and capability refusals, in the spellings tools use.
    ("cannot", "cannot"),
    ("could_not", "could not"),
    ("unable", "unable"),
    ("denied", "denied"),
    ("refused", "refused"),
    ("rejected", "rejected"),
    # The loop itself: a worker announcing it is going round again is the
    # single clearest sign that the same workaround is being retried.
    ("retry", "retry"),
    ("retrying", "retrying"),
    # A step that ran out of time, and a merge/checkout that could not apply.
    ("timed_out", "timed out"),
    ("timeout", "timeout"),
    ("conflict", "conflict"),
)

# A prompt the unit is sitting at. Matched against the LAST non-empty line
# only, and only once output has stopped growing -- a model that merely
# prints a sentence ending in `?` keeps producing bytes and stays `running`.
_PROMPT_TAIL_PATTERNS: Final[tuple[str, ...]] = (
    # Explicit yes/no prompts, in the three spellings tools actually use.
    r"\((?:y/n|yes/no|y/n/a)\)\s*[:?]?\s*$",
    r"\[(?:y/n|yes/no|y/n/a)\]\s*[:?]?\s*$",
    # `Press ENTER to continue` and its variants.
    r"press (?:enter|return|any key)\b",
    # Any line that ends in a question mark: the "no new output since" gate
    # above is what makes this safe.
    r"\?\s*$",
)

_DIGIT_RUN = re.compile(r"\d+")
# Seven is git's short-sha floor, which is the smallest hex run worth
# collapsing; forty is a full sha1. Matched before the digit rule so a sha
# becomes one token instead of a digit/letter mosaic.
_HEX_RUN = re.compile(r"\b[0-9a-f]{7,64}\b", re.IGNORECASE)
_PROMPT_TAIL_RES = tuple(re.compile(pattern, re.I) for pattern in _PROMPT_TAIL_PATTERNS)
_PHASE_MARKER_RES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (marker, re.compile(pattern, re.I | re.M)) for marker, pattern in _PHASE_MARKER_PATTERNS
)


def empty_progress_evidence(*, now: float) -> dict[str, Any]:
    """Evidence for a unit that has been dispatched and has said nothing yet.

    `running`, not stalled: `last_new_output_at` is `now`, so the stall clock
    starts when the unit starts rather than at the epoch.
    """
    return {
        "schema_version": UNIT_PROGRESS_SCHEMA_VERSION,
        "observed_at": float(now),
        "output_bytes": 0,
        "output_lines": 0,
        "last_new_output_at": float(now),
        "repeated_line": "",
        "repeat_count": 0,
        "phase_markers": [],
        "result_record_present": False,
        "state": UNIT_STATE_RUNNING,
        "reason": "",
    }


def assess_progress(
    previous: Mapping[str, Any] | None,
    stdout_so_far: str,
    *,
    now: float,
    result_record_present: bool = False,
    stall_after_seconds: float = UNIT_STALL_AFTER_SECONDS,
    repeat_threshold: int = UNIT_REPEAT_THRESHOLD,
    prompt_quiet_seconds: float = UNIT_PROMPT_QUIET_SECONDS,
) -> dict[str, Any]:
    """Derive one unit's progress evidence from its stdout so far.

    Rule order, highest first -- the order is the whole point, so it is
    stated here rather than left to be read off the branches:

    1. A limit, permission, or missing-object shape in the tail. Each is a
       condition retrying under the same conditions cannot clear, so it must
       be reported the moment it is seen rather than waited out.
    2. The same FAILURE-SHAPED canonical line repeating `repeat_threshold`
       times in the tail -- EVEN WHILE bytes grow. This is the 2026-09-11
       incident: 36 minutes of new output that was the same workaround again.
       Only lines matching `_FAILURE_SHAPED_WORDS` are counted; a healthy run
       repeats `... ok` or one warning per file endlessly and must stay
       `running`.
    3. A prompt at the end of output with no new bytes for
       `prompt_quiet_seconds`: `awaiting_input`. The quiet window is the whole
       guard -- one poll step of silence after a question mark is just a tool
       call in progress.
    4. No new bytes for `stall_after_seconds`: `progress_stalled`.
    5. Otherwise `running`.

    `previous` may be None (first assessment) or any mapping shaped like the
    evidence this function returns; missing keys degrade to the empty-unit
    defaults rather than raising, because this runs on an observability path
    that must never fail a dispatch.
    """
    text = stdout_so_far or ""
    prior = dict(previous) if isinstance(previous, Mapping) else None
    previous_bytes = _int_at(prior, "output_bytes", 0)
    last_new_output_at = _float_at(prior, "last_new_output_at", float(now))
    grew = len(text) > previous_bytes
    if grew or prior is None:
        last_new_output_at = float(now)

    tail = text[-_TAIL_CHARS:]
    repeated_line, repeat_count = _most_repeated_line(text)
    evidence: dict[str, Any] = {
        "schema_version": UNIT_PROGRESS_SCHEMA_VERSION,
        "observed_at": float(now),
        "output_bytes": len(text),
        "output_lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "last_new_output_at": last_new_output_at,
        "repeated_line": repeated_line,
        "repeat_count": repeat_count,
        "phase_markers": _phase_markers(text),
        "result_record_present": bool(result_record_present),
        "state": UNIT_STATE_RUNNING,
        "reason": "",
    }

    shaped = _shaped_state(tail)
    if shaped is not None:
        evidence["state"], evidence["reason"] = shaped
        return evidence
    # Floor of 2: `_most_repeated_line` already refuses to name a line that
    # occurs once, so a caller passing 1 or 0 would otherwise make every line
    # of output its own verdict.
    if repeat_count >= max(2, int(repeat_threshold)):
        evidence["state"] = UNIT_STATE_PROGRESS_STALLED
        evidence["reason"] = f"{REASON_REPEATED_ERROR_PREFIX}{repeated_line[:_REASON_LINE_LIMIT]}"
        return evidence
    quiet_for = float(now) - last_new_output_at
    if prior is not None and quiet_for >= float(prompt_quiet_seconds) and _ends_at_prompt(text):
        evidence["state"] = UNIT_STATE_AWAITING_INPUT
        evidence["reason"] = REASON_PROMPT_AT_END
        return evidence
    if quiet_for >= float(stall_after_seconds):
        evidence["state"] = UNIT_STATE_PROGRESS_STALLED
        evidence["reason"] = REASON_NO_NEW_OUTPUT
    return evidence


def stalled_for_seconds(evidence: Mapping[str, Any] | None) -> int:
    """Whole seconds since this unit's output last grew. 0 when unknown.

    The evidence's own clock readings are monotonic and meaningless in
    another process, so every cross-process surface carries this derived
    elapsed instead of the raw readings.
    """
    if not isinstance(evidence, Mapping):
        return 0
    observed = _float_at(evidence, "observed_at", 0.0)
    last_new = _float_at(evidence, "last_new_output_at", observed)
    return max(0, int(observed - last_new))


def progress_state_summary(evidence: Mapping[str, Any] | None) -> str:
    """One line a person can read: the state word, plus why and for how long.

    A `running` unit renders the bare word. Every stuck state renders its own
    word with its reason, and a stall also renders how long output has been
    still -- the whole point being that a stuck unit must never render the
    same as a live one.
    """
    if not isinstance(evidence, Mapping):
        return ""
    state = str(evidence.get("state", "") or "")
    if not state:
        return ""
    reason = str(evidence.get("reason", "") or "")
    if not reason:
        return state
    elapsed = stalled_for_seconds(evidence)
    if elapsed > 0:
        return f"{state} ({reason}; no new output for {elapsed}s)"
    return f"{state} ({reason})"


def _shaped_state(tail: str) -> tuple[str, str] | None:
    """First matching retry-proof shape in the tail, or None."""
    lowered = tail.casefold()
    for label, needle in _limit_shaped_patterns():
        if needle in lowered:
            return UNIT_STATE_ACCOUNT_LIMIT, f"{REASON_ACCOUNT_LIMIT_PREFIX}{label}"
    for label, needle in _PERMISSION_PATTERNS:
        if needle in lowered:
            return UNIT_STATE_PERMISSION_BLOCKED, f"{REASON_PERMISSION_PREFIX}{label}"
    for label, needle in _DATA_MISSING_PATTERNS:
        if needle in lowered:
            return UNIT_STATE_DATA_MISSING, f"{REASON_DATA_MISSING_PREFIX}{label}"
    return None


_LIMIT_PATTERN_CACHE: list[tuple[str, str]] = []


def _limit_shaped_patterns() -> tuple[tuple[str, str], ...]:
    """`fanout_dispatch`'s limit shapes, case-folded once and cached.

    The single source of those shapes, including the `session_limit` rows PR
    #1486 added for the 2026-09-11 refusal ("You've hit your session limit").
    Imported lazily: `fanout_dispatch` imports THIS module for the on-output
    assessment, so a module-level import here would be a cycle. An import
    failure degrades to no limit patterns rather than raising -- this runs on
    an observability path that must never fail a dispatch, and a missed limit
    shape reads as `running` rather than taking the process down.
    """
    if _LIMIT_PATTERN_CACHE:
        return tuple(_LIMIT_PATTERN_CACHE)
    try:
        from .fanout_dispatch import _LIMIT_SHAPED_PATTERNS
    except ImportError:
        _LIMIT_SHAPED_PATTERNS = ()
    _LIMIT_PATTERN_CACHE.extend(
        (str(label), str(needle).casefold()) for label, needle in _LIMIT_SHAPED_PATTERNS
    )
    return tuple(_LIMIT_PATTERN_CACHE)


def _ends_at_prompt(text: str) -> bool:
    """True when the LAST non-empty line looks like a question or a prompt."""
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        return any(pattern.search(stripped) for pattern in _PROMPT_TAIL_RES)
    return False


def _most_repeated_line(text: str) -> tuple[str, int]:
    """The tail's most frequent canonical FAILURE-SHAPED line, and its count.

    Non-failure lines are not counted at all, rather than counted and then
    filtered: a green run's `... ok` would otherwise be the most common line
    and would mask a failure repeating underneath it.
    """
    counts = Counter(
        canonical
        for canonical in (_canonical_line(line) for line in text.splitlines()[-_TAIL_LINES:])
        if canonical and _is_failure_shaped(canonical)
    )
    if not counts:
        return "", 0
    # `most_common` breaks ties by insertion order, which is the tail's own
    # order, so the same text always names the same line.
    line, count = counts.most_common(1)[0]
    return (line, count) if count > 1 else ("", 0)


def _is_failure_shaped(canonical_line: str) -> bool:
    """True when the line reports something going wrong. See the table."""
    lowered = canonical_line.casefold()
    return any(needle in lowered for _label, needle in _FAILURE_SHAPED_WORDS)


def _canonical_line(line: str) -> str:
    """One line with its varying parts collapsed, so a retry counter cannot
    disguise the same failure as fresh output.

    Hex runs first, then digit runs: collapsing digits first would shred a
    short sha into a `<n>`/letter mosaic that no longer matches its siblings.
    """
    stripped = line.strip()
    if not stripped:
        return ""
    return _DIGIT_RUN.sub("<n>", _HEX_RUN.sub("<hash>", stripped))


def _phase_markers(text: str) -> list[str]:
    return [
        marker
        for marker in PHASE_MARKERS
        if any(
            compiled.search(text)
            for row_marker, compiled in _PHASE_MARKER_RES
            if row_marker == marker
        )
    ]


def _int_at(mapping: Mapping[str, Any] | None, key: str, default: int) -> int:
    if not isinstance(mapping, Mapping):
        return default
    value = mapping.get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _float_at(mapping: Mapping[str, Any] | None, key: str, default: float) -> float:
    if not isinstance(mapping, Mapping):
        return default
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)
