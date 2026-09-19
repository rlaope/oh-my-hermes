"""Parallel tool-call burst observation, in-flight liveness, repeat guard.

Hermes executes a model turn's batched tool calls concurrently (its
``_execute_tool_calls_concurrent`` dispatch), but the transcript renders
only a collapsed "Tool calls (N)" group -- nothing tells the user whether
that batch actually ran as a parallel shot, or whether the batch is still
running at all. The ``pre_tool_call`` hook fires once per call, so calls
whose start ticks land inside one short window are the concurrent batch;
this module records those ticks (tool name, timestamp, and a short one-way
digest of the call's arguments -- never the arguments themselves) and
projects the latest burst for the ``[OMH]`` status line.

That digest is what the repeat guard compares, and it is the reason the
"never arguments" line above is worded the way it is. It is a truncated
BLAKE2b over the canonicalized arguments, capped before hashing, and only
the hex digest is stored: equal digests mean an identical call, unequal
digests mean a different one, and that is the whole of what the field
says. The guard stores a second digest of the same shape for what the
call RETURNED, because arguments alone cannot tell a loop from a poll
(#1706): `gh pr checks` run twice has byte-identical arguments and a
different answer. The privacy contract is the same one, with no
exception -- length plus a truncated BLAKE2b of a bounded prefix, never
the text. Nothing written here can be read as a path, a pattern, a file
body, or a tool's output, so the record stays inside the plugin's
declared ``privacy: metadata_only`` contract (``config.yaml``) -- a
fingerprint of content is not content. Stated exactly, because this is a
privacy claim: a digest is confirmable by guessing, not readable. Someone
holding this file and a candidate string can test that guess, which is
the ordinary property of every fingerprint and is precisely why the field
is a digest instead of a truncated copy.

``post_tool_call`` (a second supported Hermes observer hook, paired with
``pre_tool_call`` by ``tool_call_id``) closes what ``pre_tool_call`` opens.
Pairing the two gives an exact in-flight count -- the gap the
ring-buffer-only design could not see: a stopped turn with an incomplete
todo item read identically to 40 tool calls genuinely running, because
nothing distinguished "the ring saturated" from "work is happening". A
host that omits ``tool_call_id`` degrades silently to the pre-pairing
behavior: the tick still lands for burst grouping, but no in-flight entry
opens, and the HUD's liveness signal simply stays quiet for that call.

Scope: the ledger lives at one path per OMH home
(``<omh_home>/runtime/tool-bursts.json``), machine-wide and shared by every
Hermes session pointed at that home. The burst and in-flight projections
are not scoped to one session or turn: a sibling session sharing the same
OMH home shows up in this session's liveness signal exactly the same as
this session's own calls, and the ``turn_id`` stored on each open entry
rides along as inert metadata that nothing here reads back.

The repeat history is the one part that IS keyed by session, and it has
to be for the same reason the rest is not: in a ledger every session
writes to, an unkeyed counter would read two sessions running the same
search as one session looping. Each session holds one row: a bounded
list of its recent calls, each carrying a tool, an argument digest, a
result digest and a tick, plus a count of the calls this guard refused.
The row is capped in entries and in the length of every field, and a
session not currently repeating anything is trimmed to the shortest
history a cycle could still be found in.

What the history is for, stated without overclaiming. It feeds two
stages at ``pre_tool_call``: a ``block``, whose message goes back to the
model, and then an ``approve``, which the host routes to the
human-approval gate instead -- withheld in a lane with nobody there to
answer it. The evidence says the first stage may do nothing at all: in the
session this was built from, a model read 185 of the host's own refusals
on one tool and 100+ on another and reissued the identical call every
time. So the claim here is detection and refusal, not that the loop ends:
one stage the model can ignore, one it cannot answer by itself, and a
count a later surface can show the person.
"""
from __future__ import annotations

from . import runtime_paths

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the awareness ledger's portable lock and atomic-write primitives so
# there is exactly one file-locking implementation in the plugin.
from .awareness_delivery import _awareness_delivery_lock, _write_delivery_record

TOOL_BURSTS_SCHEMA_VERSION = "omh_tool_bursts/v1"
TOOL_ACTIVITY_SCHEMA_VERSION = "omh_tool_activity/v1"
TOOL_BURSTS_FILE = "tool-bursts.json"
# Raised from 40 (2026-08, HUD liveness fix): the ring ceiling used to be
# what the "parallel shot x40" badge actually measured -- a fanout wave of
# 40+ short calls saturated the ring long before it went idle, so the badge
# read the buffer filling up, not the truth about what was running. 200 is
# burst HISTORY depth, not a concurrency claim: Hermes caps concurrent tool
# workers well below this (`_MAX_TOOL_WORKERS` in Hermes'
# `agent/tool_executor.py`), so no real dispatch ever has 200 calls open at
# once -- this ceiling exists to keep a long chain of small, fast, strictly
# SEQUENTIAL calls (which the 1.5s grouping window still chains into one
# burst) from growing the file without bound, while keeping each entry
# small (two-three short fields).
MAX_TOOL_BURST_ENTRIES = 200
# Same headroom rationale as MAX_TOOL_BURST_ENTRIES, applied to the
# in-flight ledger: a host that never sends a matching post_tool_call (a
# crash, an unsupported host) must not let open_calls grow without bound.
# Losing the oldest open entry under pathological load is acceptable --
# the ledger is best-effort observation, not a correctness-critical store.
MAX_OPEN_TOOL_CALLS = 200
# Ticks closer together than this belong to one dispatch burst: Hermes
# starts a concurrent batch's workers within milliseconds of each other,
# while consecutive sequential turns are separated by at least one model
# round-trip.
BURST_WINDOW_SECONDS = 1.5
# The HUD shows the latest burst only while it is recent enough to still
# describe "what just happened". Seconds, not minutes, by owner direction
# ('한 몇초만 지나면 바로없어지게'): the badge flags the batch as it lands
# and vanishes right after, refreshed continuously through a busy wave by
# the next batch's ticks.
BURST_FRESH_SECONDS = 8.0
# An open call with no matching post_tool_call this long is not still
# running -- it is a process restart, a crashed host, or a lost tick. It is
# reported as expired rather than kept open forever, and never reported as
# completed (nothing observed it finishing). Known limitation, not fixed
# here: at 100+-way concurrency the file lock `record_tool_call_close`
# takes can itself time out under contention, which strands that close as a
# best-effort no-op -- the entry then rides out this same TTL instead of
# closing promptly, which is an accepted cost of best-effort observation.
TOOL_CALL_OPEN_TTL_SECONDS = 15 * 60
TOOL_BURST_CLAIM_BOUNDARY = (
    "Burst grouping observes pre_tool_call start ticks only; it is evidence "
    "the host dispatched the calls as one batch, not proof every call "
    "overlapped for its full duration."
)
TOOL_ACTIVITY_CLAIM_BOUNDARY = (
    "In-flight state is the local pairing of this host's pre_tool_call and "
    "post_tool_call ticks by tool_call_id. It is evidence of calls this OMH "
    "install observed opening and closing, not a complete accounting of "
    "every tool call Hermes ran."
)
# Consecutive identical calls before `pre_tool_call` refuses the next one.
# Nothing here claims this refusal is stronger than the host's. It is not:
# a `block` becomes the tool result, exactly as Hermes' own guard's error
# did, and a model that ignores one can ignore the other the same way.
# Two reasons put it at 8 rather than at the host's own 4.
#
# First, Hermes already refuses a repeated `search_files` at the 4th
# identical call (`tools/file_tools.py`, `if count >= 4`, warning at the
# 3rd) and guards a repeated `read_file` region too. A second refusal at
# the same point is the same message in another voice, not a second
# mechanism. Engaging four calls later means engaging on evidence the
# host's refusal did not produce: that it was ignored.
#
# Second, an identical repeated call is not always a loop. Polling is the
# legitimate case -- `terminal` running `gh pr checks <n>` back to back
# while waiting on CI has byte-identical arguments every time, and so does
# any status check. The result digest below is what now separates the two,
# and it is the reason 8 is no longer sized to leave room for a poll: a
# poll whose output changes never reaches a stage at all. 8 stays because
# the two reasons above still hold, and because it is far outside an
# immediate retry (two or three times) and far short of the measured
# failure (the same `search_files` call 203 times, one `read_file` region
# 100+ times).
REPEAT_CALL_BLOCK_THRESHOLD = 8
# Longest repeating cycle the guard recognizes, and the fewest laps of one
# that count as a cycle at all. Both are the host's own numbers
# (`agent/tool_guardrails.py`, `_STALL_GUARD_MAX_CYCLE_PERIOD` and
# `STALL_GUARD_IDENTICAL_CALL_THRESHOLD`), matched deliberately: two
# detectors that disagreed about what a cycle is would refuse different
# sequences, and a person comparing OMH's refusal with the host's note
# could not tell which one was wrong. Period 1 is the consecutive streak
# this guard shipped with, so there is one mechanism here, not two.
REPEAT_CYCLE_MAX_PERIOD = 4
REPEAT_CYCLE_MIN_LAPS = 3
# Tools the host exempts from its own identical-call notice, because they
# are "legitimately re-invoked with identical args"
# (`agent/tool_guardrails.py`, `STALL_GUARD_REPEATABLE_TOOLS` and
# `_STALL_GUARD_REPEATABLE_SUFFIXES`). Mirrored for the same reason the
# periods are: a person comparing OMH's refusal with the host's silence
# should not have to work out which of the two is wrong about the same
# call.
POLLER_TOOL_NAMES = frozenset({"process_manage"})
POLLER_TOOL_SUFFIXES = ("_get_result", "_poll")
# What the threshold above means for a cycle, and the reason it is a
# formula rather than a second constant: counting LAPS alone would let a
# period-4 cycle run 32 calls before the guard said anything, four times
# the budget a period-1 streak gets, purely because the model padded the
# loop. So a cycle is engaged when it has both run enough laps to BE a
# cycle and spent roughly the same number of calls:
#
#     period 1 -> 8 laps  =  8 calls   (unchanged from the streak)
#     period 2 -> 4 laps  =  8 calls
#     period 3 -> 3 laps  =  9 calls
#     period 4 -> 3 laps  = 12 calls
#
# The 9 and the 12 are the price of the minimum-laps floor, which is what
# keeps a coincidental A,B,A,B from reading as a loop.
def _required_laps(period: int) -> int:
    """Laps of a `period`-long cycle before stage one engages."""
    return max(REPEAT_CYCLE_MIN_LAPS, -(-REPEAT_CALL_BLOCK_THRESHOLD // max(period, 1)))


# Blocks a session may ignore before the call stops going to the model at
# all and goes to a person. The distance is the meaning: the history
# freezes once stage one starts refusing (a blocked call never runs, so it
# is never recorded), so four more attempts are exactly four stage-one
# blocks that were ignored. One ignored block can be a model recovering --
# a retry already in flight, a message that crossed the refusal -- and two
# can be the same. Four is not: measured, session 20260919_140745_db409e
# ignored 185 of the host's refusals on `search_files` and 100+ on
# `read_file`. At that point the only response in the `pre_tool_call`
# contract a model cannot answer by itself is the human-approval gate.
REPEAT_CALL_ESCALATION_ATTEMPTS = 4
# Ceiling on the interception counter, matching the shape the activity
# observer uses for its own counters. Every rung above this reads the same,
# so the cap costs no decision and keeps the field's length bounded.
MAX_INTERCEPTED_COUNT = 10**9
# The period-1 reading of the ladder, kept because it is how the two
# stages were first described and how the shipped tests name them: the
# 9th identical call blocks, the 13th escalates.
REPEAT_CALL_APPROVAL_THRESHOLD = REPEAT_CALL_BLOCK_THRESHOLD + REPEAT_CALL_ESCALATION_ATTEMPTS
# Arguments are canonicalized and capped before hashing so a single huge
# call (a whole-file write body) cannot make the digest step expensive.
# Two calls whose arguments differ only past the cap share a digest and so
# read as a repeat; acceptable here, because they still agree on their
# first 8 KiB and any call outside the cycle clears the guard.
MAX_DIGEST_INPUT_BYTES = 8192
# The same bound for a tool RESULT, with one addition: the result's full
# length is hashed alongside its first 8 KiB. The asymmetry is deliberate
# and the directions differ. Two different huge arguments colliding on
# their prefix reads as a repeat, which the next call outside the cycle
# clears.
# Two different huge RESULTS colliding on their prefix reads as "nothing
# changed", which is how a legitimate poll gets blocked -- so the length
# goes into the hash, because the growing log and the lengthening job
# summary that make up most long-running polls change length on every
# read even when their first 8 KiB does not.
#
# The limit that remains, stated because it cannot be closed from here: a
# result that differs ONLY past 8 KiB and at exactly the same length reads
# as identical. And the opposite, more common case -- a result carrying a
# timestamp, an elapsed duration, or a progress percentage -- never
# repeats byte-for-byte at all, so it reads as progress forever. That is
# the safe direction for a poll and the unsafe one for a loop whose output
# is timestamped. OMH does not normalize result text to close it: deciding
# which bytes of a result "do not count" is wording inference, and a guard
# that guesses wrong there refuses work on a claim it cannot support.
MAX_RESULT_DIGEST_INPUT_BYTES = 8192
# One streak row per session id, capped like the other maps in this file:
# the ledger is machine-wide and a long-lived host must not grow it without
# bound. Dropping the least recently active session's row costs that
# session its count, which is the same as its guard never having armed.
MAX_REPEAT_STREAKS = 64
# Calls of per-session history the cycle detector reads. The host keeps 64;
# this keeps 16 because the ladder cannot use more -- the longest engagement
# above is 12 calls (period 4, 3 laps) and the longest lookback any stage
# needs is that same 12. The remainder is slack, not capability.
#
# The bound is in bytes as well as entries, and the arithmetic is the
# bound: every field of a serialized entry is capped (tool 48 chars, two
# digests 64 each, a whole-second timestamp), so one entry cannot exceed
# ~200 bytes and a session's history cannot exceed ~3 KiB.
MAX_REPEAT_HISTORY = 16
# What a session that is NOT in a loop keeps, which is almost every row in
# a busy ledger and therefore almost all of its bytes. Two laps of the
# longest cycle is what it takes to detect one at all, so a history with
# no cycle in it can be cut to that without losing anything: a cycle is
# always a suffix, the count of laps starts at 2, and an entry older than
# the last eight can only ever join a cycle whose first two laps are
# already inside those eight. Once a cycle IS live the row grows back to
# MAX_REPEAT_HISTORY so the laps can accumulate toward a stage.
#
# This is the difference between a ledger that costs a gateway ~110 KiB
# and one that costs it ~190 KiB, and `pre_tool_call` reads and rewrites
# that file on every allowed call.
IDLE_REPEAT_HISTORY = REPEAT_CYCLE_MAX_PERIOD * 2
# A streak whose last call is older than this no longer describes a loop.
# A real one fires its repeats back to back inside a single turn (the
# observed burn ran 180 calls at ~0.0s each); after a gap this long the
# session has been idle, or the host restarted, or a session id was reused,
# and the guard must not greet a returning session with a refusal it earned
# much earlier. It is also what keeps a dead session's row from sitting in
# the file until the cap evicts it.
REPEAT_STREAK_WINDOW_SECONDS = 300.0
# The one sentence in this module the MODEL acts on, so it has to describe
# the rule the gate actually applies. It used to end "any different tool
# call clears the guard immediately", true while the guard only ever
# watched one repeated call and false the moment `_call_is_in_cycle`
# replaced position with membership: under a period-2 cycle the other
# element IS a different tool call and is refused, so the message was
# telling the model to do the one thing this change made it stop doing.
REPEAT_CALL_BLOCK_SUFFIX = (
    "This tool call was blocked by OMH before execution because it repeats "
    "a cycle of calls this session keeps running. A blocked call did not "
    "run, and any call outside that cycle clears the guard immediately."
)
# The `[a]lways` allowlist grain for an escalated call. Explicit, because
# the host derives one from the tool name plus a hash of the reason when
# this is empty (`tools/approval.py`, `request_tool_approval`), and this
# reason carries a count that changes every call -- which would mint a new
# key each time and re-prompt a person who already answered "always". Keyed
# by digest instead, an informed "always" covers exactly this one call with
# these arguments and nothing wider. The digest, never the arguments.
REPEAT_CALL_RULE_KEY_PREFIX = "omh_repeat"
REPEAT_CALL_CLAIM_BOUNDARY = (
    "A repeat streak counts calls this OMH install saw at pre_tool_call, "
    "keyed by session, compared by argument digest, and compared by result "
    "digest for the calls whose post_tool_call this install also saw. It is "
    "evidence that the same call -- or the same short cycle of calls -- was "
    "attempted again, and for the compared calls that two returns were "
    "byte-identical inside the digest bound. It is never evidence of WHAT "
    "any call returned, and an intercepted call is not evidence of what the "
    "host or the person then did with it."
)
_MAX_TOOL_NAME_CHARS = 48
_MAX_ID_CHARS = 128
# 16 hex characters is what `tool_args_digest` produces. The cap only
# bounds what a foreign or hand-edited file can put in the field.
_MAX_DIGEST_CHARS = 64
# History entries are serialized under one-letter keys, and only there:
# every reader turns them back into the named fields the rest of this
# module uses, so the compaction never reaches the code that compares
# them. It is here because `pre_tool_call` reads and rewrites this file
# on every allowed call and a session now stores up to sixteen entries
# instead of one -- the field names alone were a third of each entry.
_HISTORY_TOOL_KEY = "t"
_HISTORY_ARGS_KEY = "a"
_HISTORY_RESULT_KEY = "r"
_HISTORY_TICK_KEY = "s"
# The attendance answer the GATE computed for this session, recorded on the
# row so a reader in another process can render the stage the gate acts on
# rather than one it would not.
#
# The predicate itself (`session_attendance.escalation_can_reach_a_person`)
# reads two process-global maps: the platform `pre_llm_call` recorded and the
# delegated-child set `subagent_start` recorded. The HUD reader is a separate
# interpreter -- the TUI widget spawns one every two seconds -- so both maps
# are empty there and the predicate would answer "attended" for every
# session, which is precisely the disagreement `_repeat_stage`'s signature
# exists to prevent. Recording the gate's own answer is what carries that
# guarantee across the process boundary: there is no second predicate, and no
# default standing in for one. A row with no recorded answer withholds the
# escalation stage instead of assuming it (`_recorded_escalation`).
_ROW_ESCALATION_KEY = "esc"


def _runtime_dir(omh_home: str = "") -> Path:
    root = Path(omh_home).expanduser() if omh_home else runtime_paths.default_omh_home()
    return root / "runtime"


def tool_bursts_path(omh_home: str = "") -> Path:
    return _runtime_dir(omh_home) / TOOL_BURSTS_FILE


def _normalized_name(tool_name: object) -> str:
    return " ".join(str(tool_name or "").split())[:_MAX_TOOL_NAME_CHARS]


def _normalized_id(value: object) -> str:
    return str(value or "").strip()[:_MAX_ID_CHARS]


def tool_args_digest(tool_input: object) -> str:
    """A short one-way digest of this call's arguments, or "" for none.

    "" is the degrade-to-allow signal, and the only one: arguments that
    cannot be canonicalized (a self-referential structure) produce no
    digest, no streak row, and therefore no refusal. The guard would rather
    miss a loop than block a call it could not identify.
    """
    try:
        canonical = json.dumps(tool_input, sort_keys=True, default=str)
    except (TypeError, ValueError, RecursionError):
        return ""
    return hashlib.blake2b(
        canonical.encode("utf-8", "replace")[:MAX_DIGEST_INPUT_BYTES],
        digest_size=8,
    ).hexdigest()


def tool_result_digest(result: object) -> str:
    """A short one-way digest of this call's result, or "" for unknown.

    "" is the degrade signal, and it degrades to exactly the behaviour this
    guard shipped with: an element whose result is unknown compares on its
    arguments alone (`_elements_equal`), so a host that never fires
    `post_tool_call` still gets the argument-digest guard and no message
    here claims anything about results.

    Only text is digested, and the reason is cost rather than a claim
    about what results look like. `model_tools.handle_function_call` is
    typed to return a string, but the hook is also emitted from paths
    that pass the raw result, and the host's own guard branches on
    non-string multimodal results throughout
    (`agent/tool_guardrails.py`: "non-string (multimodal) results never
    form one"). Canonicalizing an arbitrary object means `json.dumps`
    copying a payload that may hold a base64 image, on the hot path, to
    fingerprint a result no loop in this repository has been measured
    repeating. So anything that is not text is unknown -- the cheap
    answer, and the one that degrades to the argument comparison rather
    than to a guess.

    Privacy is the same contract as `tool_args_digest`: the length and a
    truncated BLAKE2b of the first `MAX_RESULT_DIGEST_INPUT_BYTES`, never
    the text. Equal digests mean the two returns matched inside that
    bound, unequal digests mean they did not, and that is the whole of
    what the field says.
    """
    if isinstance(result, bytes):
        head, size = result[:MAX_RESULT_DIGEST_INPUT_BYTES], len(result)
    elif isinstance(result, str):
        # Sliced before encoding so a 10 MB result costs a 8 KiB copy and
        # not a 10 MB one; `len` on a str is O(1), so the length that
        # separates a growing log from a stalled one is free.
        head, size = result[:MAX_RESULT_DIGEST_INPUT_BYTES].encode("utf-8", "replace"), len(result)
    else:
        return ""
    return hashlib.blake2b(b"%d:" % size + head, digest_size=8).hexdigest()


def is_poller_tool(tool_name: str) -> bool:
    """Whether the host exempts this tool from its own identical-call notice.

    A copy of `agent/tool_guardrails.py` `is_stall_guard_repeatable` and
    the two constants it reads, `STALL_GUARD_REPEATABLE_TOOLS` and
    `_STALL_GUARD_REPEATABLE_SUFFIXES`. Copied rather than imported for
    the reason every host vocabulary in this bundle is: OMH never imports
    Hermes, and the interpreter that loads this bundle has no `omh`
    package either.

    Taken rather than reinvented because #1719's comment asked for
    exactly that -- "taken from the host's list rather than a second list
    kept here". Result-awareness supersedes the allowlist for a poll
    whose output moves, and does not for the one the host actually names:
    a `process_manage` status poll returning the same "running" line has
    identical arguments and an identical result, so without this the
    guard refuses at the ninth check the tool a model is told to use.
    """
    return tool_name in POLLER_TOOL_NAMES or tool_name.endswith(POLLER_TOOL_SUFFIXES)


def _elements_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Whether two recorded calls are the same call, returning the same thing.

    Arguments must match. Results must match too, unless either side has no
    result digest -- an unknown result is not evidence of a change, and
    treating it as one would disarm the guard on every host that does not
    fire `post_tool_call`, and on every call still in flight when the next
    one starts. The cost of the other choice is the one this takes: an
    unknown result reads as "no evidence either way", so the pair falls
    back to the argument comparison that shipped in #1708, and the message
    the gate writes says so rather than claiming a result was compared.
    """
    if left["tool"] != right["tool"] or left["args_digest"] != right["args_digest"]:
        return False
    if not left["result_digest"] or not right["result_digest"]:
        return True
    return left["result_digest"] == right["result_digest"]


def _detect_cycle(history: list[dict[str, Any]]) -> tuple[int, int] | None:
    """The shortest repeating cycle at the END of this history, or None.

    Returns `(period, laps)`: `period` calls repeated `laps` times back to
    back, ending at the most recent call. Period 1 is the consecutive
    identical-call streak, which is why this replaced that counter instead
    of standing beside it -- an A,B,A,B alternation resets a consecutive
    streak on every call, so the guard was armed and silent through exactly
    the failure #1719 measured.

    Shortest period wins: A,A,A,A is four laps of one call, not two of two.
    Laps are counted by comparing each block with the block before it, so
    the answer is "how many times in a row did this repeat", never a
    pattern found somewhere in the middle of the history.
    """
    size = len(history)
    for period in range(1, REPEAT_CYCLE_MAX_PERIOD + 1):
        if size < period * 2:
            break
        laps, start = 1, size - period
        while start - period >= 0 and all(
            _elements_equal(history[start - period + offset], history[start + offset])
            for offset in range(period)
        ):
            laps, start = laps + 1, start - period
        if laps >= 2:
            # A cycle made only of pollers is not a loop, and the skip is
            # the host's: `_detect_identical_cycle` runs the same check on
            # the same tail and `continue`s to a longer period rather than
            # returning. What continuing actually buys, measured rather
            # than asserted: on a `terminal`, poll, poll loop it finds the
            # mixed period-3 cycle at call 10 where `return None` finds it
            # at 11. One call, not a lost detection -- the shorter
            # all-poller tail would have been skipped either way, and the
            # next call's own detection picks the mixed cycle up.
            if all(is_poller_tool(entry["tool"]) for entry in history[-period:]):
                continue
            return period, laps
    return None


def _call_is_in_cycle(elements: list[dict[str, Any]], tool: str, args_digest: str) -> bool:
    """Whether this call is one of the cycle's own, at any position.

    Membership, not "the element the cycle predicts next", and the
    difference is measured rather than argued. Driven through the real
    hooks, a period-2 cycle blocked at its first element and then ran
    eight more calls: the model issued the OTHER element, the phase had
    not advanced (a blocked call never runs, so it is never recorded),
    and a positional check read the second element as something new. It
    is not new -- it is the same loop, one step along, and it had already
    returned the same thing on every lap.

    What still clears the guard is what always cleared it: a call that is
    not in the cycle at all. That one dispatches, joins the history, and
    leaves no cycle behind it.
    """
    return any(
        entry["tool"] == tool and entry["args_digest"] == args_digest for entry in elements
    )


def _results_were_compared(history: list[dict[str, Any]], period: int, laps: int) -> bool:
    """Whether every call in the detected cycle carried a result digest.

    The one gate on what a message may claim. True means the results were
    compared and found equal; False means at least one call's result was
    never observed, so the cycle rests on arguments alone and no sentence
    may say otherwise.
    """
    return all(entry["result_digest"] for entry in history[len(history) - period * laps :])


def _repeat_stage(
    laps: int, period: int, intercepted: int, *, escalation_allowed: bool
) -> str:
    """Which stage this cycle is in. One rule, one place.

    Every caller must pass the same three counts AND the same attendance
    answer, and neither this function nor `repeat_call_streak` gives that
    last one a default, so "a surface cannot render a stage the gate
    would not act on" is enforced by the signatures rather than left to
    whoever writes the next caller. Two earlier versions of this
    sentence were not true: the first because the gate took the
    attendance answer and the reader did not, the second because the
    reader took it with a default that a caller could simply omit.

    The two counts are read on different rungs, which is the whole design.
    Laps of the cycle decide whether to intervene at all: that many
    repetitions reached the host. Blocks the session ignored decide whether
    the intervention still goes to the model, because once stage one starts
    no further call runs and therefore no further lap is recorded -- a rung
    reading laps alone would freeze there and nothing could ever escalate.
    """
    if laps < _required_laps(period):
        return "watching"
    if intercepted >= REPEAT_CALL_ESCALATION_ATTEMPTS and escalation_allowed:
        return "approval"
    return "blocking"


def _cycle_subject(elements: list[dict[str, Any]], laps: int) -> str:
    """How a detected cycle is named to a reader. Period 1 keeps its voice.

    A cycle of one tool called with different arguments each lap is the
    measured shape -- two `terminal` commands alternating -- and listing
    the tool once per element rendered it as "2 tool calls (`terminal`,
    `terminal`)", which reads like a bug in the message. So a cycle whose
    calls all use one tool names it once, with the count.

    Every other cycle lists one name per call, in cycle order, duplicates
    included, so the names always number what the sentence says they do.
    Naming only the DISTINCT tools was tried and is worse: "3 tool calls
    (`read_file`, `terminal`)" invites the reader to count two.

    The arguments are what actually differ between two calls of one tool,
    and they are exactly what this module may not print.
    """
    if len(elements) == 1:
        return f"`{elements[0]['tool']}` {laps} times in a row"
    tools = [entry["tool"] for entry in elements]
    subject = (
        f"{len(tools)} `{tools[0]}` calls"
        if len(set(tools)) == 1
        else f"{len(tools)} tool calls ({', '.join(f'`{tool}`' for tool in tools)})"
    )
    return f"the same cycle of {subject} {laps} times in a row"


def _repeat_block_message(
    elements: list[dict[str, Any]], laps: int, results_compared: bool
) -> str:
    """Stage one, addressed to the model. Says only what was measured.

    Two shapes, and which one is used is decided by evidence rather than
    by wording. When every call in the cycle carried a result digest the
    message may say the results were identical, because they were
    compared and found equal -- that is #1706's whole point, and it is the
    sentence the arguments-only version had to hedge. When any call's
    result was never observed the message falls back to the hedge, which
    is the honest thing to say about a comparison that did not happen.

    Neither shape says "you already have this information", the host's
    wording in the measured session, which was false there for the
    opposite reason: the pattern named functions that do not exist, so the
    search returned nothing and there was nothing the model already had.

    A refusal that misdescribes the situation is one the model can be
    right to disagree with, and the measured session is what disagreeing
    looks like.
    """
    if len(elements) == 1:
        lead = (
            f"[OMH Repeat Guard] `{elements[0]['tool']}` has been issued {laps} "
            "times in a row with exactly these arguments"
        )
    else:
        lead = f"[OMH Repeat Guard] {_cycle_subject(elements, laps)} with exactly these arguments"
    if results_compared:
        return (
            f"{lead}, and every one returned the same result. Running it "
            "again will not produce anything new. If what comes back is "
            "nothing, what you are looking for is not there under that "
            "name, so read the file directly or list what it does define. "
            "Otherwise change the call, or change the approach.\n"
            f"{REPEAT_CALL_BLOCK_SUFFIX}"
        )
    return (
        f"{lead}. OMH compares arguments, not results, so it cannot tell "
        "which of these you are doing. If the call keeps returning the same "
        "thing, including nothing, repeating it will not help: when nothing "
        "comes back, what you are looking for is not there under that name, "
        "so read the file directly or list what it does define. If you are "
        "waiting on something that changes, do other work between checks "
        f"instead of re-issuing the same call back to back.\n{REPEAT_CALL_BLOCK_SUFFIX}"
    )


def _repeat_approval_message(
    elements: list[dict[str, Any]], laps: int, intercepted: int, results_compared: bool
) -> str:
    """Stage two, addressed to a person, not the model.

    The host turns this into "Tool '<name>' requires approval (<this>)" at
    the same gate as a dangerous shell command, so it has to read as a
    question someone can answer without the session in front of them: what
    is being repeated, how far it has gone, and what each answer does.

    "Refused or escalated", not "refused": the first interventions were
    refusals, but once this prompt has been shown, later ones are
    escalations whose outcome a person decided and OMH never observes.
    Calling them all refusals would claim an answer this module does not
    have.

    The result sentence branches on the same evidence the block message
    uses. A person deciding whether to allow a poll is exactly who needs
    to know whether the output was changing, and exactly who must not be
    told it was unchanged when nothing checked.
    """
    ran = len(elements) * laps
    if len(elements) == 1:
        subject = f"`{elements[0]['tool']}` {ran + intercepted} times in a row with identical arguments"
    else:
        subject = (
            f"{_cycle_subject(elements, laps)} with identical arguments, "
            f"{ran + intercepted} calls counting the ones OMH stopped"
        )
    evidence = (
        "Every lap returned the same result, which is what separates a stuck "
        "loop from a status poll here."
        if results_compared
        else "OMH compares arguments only, so it cannot say whether the result "
        "is changing -- a stuck loop and a status poll look the same from here."
    )
    return (
        f"repeat guard: this session has issued {subject}. OMH saw the "
        f"first {ran} reach the tool and has refused or escalated the "
        f"{intercepted} since, and the session issues the same call again "
        "after each one. It does not observe how an escalation was "
        f"answered, so more than {ran} may have run. {evidence} Denying "
        "ends the repetition; allowing runs that same call once more."
    )


def repeat_call_rule_key(tool_name: str, args_digest: str) -> str:
    """The allowlist grain for an escalated call: one tool, one digest."""
    return f"{REPEAT_CALL_RULE_KEY_PREFIX}:{tool_name}:{args_digest}"


def repeat_cycle_rule_key(elements: list[dict[str, Any]]) -> str:
    """The allowlist grain for an escalated CYCLE, stable under rotation.

    A person who answered `[a]lways` must not be asked again because the
    guard happened to notice the same loop one call later: A,B,A,B and
    B,A,B,A are the same loop, and a key derived from where detection
    landed would differ between them and re-prompt. So the elements are
    rotated to their lexicographically smallest arrangement first, which
    is one key per loop regardless of entry point.

    Arguments only, never results, for the same reason period 1 has always
    been keyed that way: the grain a person is answering about is "this
    call with these arguments", and folding in a result digest would mint
    a new key the moment the output changed -- re-prompting on exactly the
    change that means the answer no longer matters.
    """
    if len(elements) == 1:
        return repeat_call_rule_key(elements[0]["tool"], elements[0]["args_digest"])
    pairs = [(entry["tool"], entry["args_digest"]) for entry in elements]
    canonical = min(tuple(pairs[index:] + pairs[:index]) for index in range(len(pairs)))
    joined = "|".join(f"{tool}:{digest}" for tool, digest in canonical)
    fingerprint = hashlib.blake2b(joined.encode("utf-8"), digest_size=8).hexdigest()
    # The space is the separator, and it is chosen because
    # `_normalized_name` joins a tool name on whitespace and so can never
    # produce one. Without it the two namespaces are the same shape and a
    # tool literally named `cycle2` would need only a digest collision to
    # share a person's `[a]lways` answer with an unrelated loop.
    return f"{REPEAT_CALL_RULE_KEY_PREFIX}:cycle {len(elements)}:{fingerprint}"


def repeat_call_directive(
    *,
    tool_name: object,
    args_digest: object,
    session_id: object = "",
    omh_home: str = "",
    now: float | None = None,
    escalation_allowed: bool = True,
) -> dict[str, str] | None:
    """Intervene on a call this session keeps repeating, or None to allow.

    Two stages, because a refusal is only as strong as the model's
    willingness to read it, and the measured session read 185 of the
    host's and repeated the call anyway. Stage one returns ``block``: the
    message becomes the tool result, which a better-behaved model can act
    on and this one may ignore. Stage two returns ``approve``, which the
    host routes to the same human gate as a dangerous shell command
    (``tools/approval.py``, ``request_tool_approval``) -- it does not go
    back to the model as text at all, and in a context with no human to
    ask it fails closed.

    ``escalation_allowed=False`` keeps stage two at ``block``. It is not a
    softer setting; it is what a lane with nobody to ask needs, and the
    reason is measured rather than assumed. `tools/approval.py`
    `_run_approval_gate` resolves an unattended context instantly, two
    ways and neither of them a person: `approvals.unattended_mode` at its
    `deny` default returns the HOST's block text, which drops OMH's advice
    and closes by telling the reader to set `unattended_mode: approve`;
    and at `approve` it returns `_approved()`, so the escalation RUNS the
    call the block stage was refusing. The second is the binding one --
    stage two would be the first rung of this ladder that makes a loop
    worse -- and both say the same thing: where no person can answer,
    ``block`` is the whole of what OMH can usefully do.

    Read-only. ``record_tool_call`` records the calls that dispatched and
    ``record_repeat_refusal`` counts the ones this guard intercepted, so
    the message can say how many times the call actually RAN while the
    stage ladder still advances on attempts that never ran.

    Every path out of the narrow positive case is ``None`` -- allow. The
    conjunction is: this session is identified, the arguments produced a
    digest, the session's recent history ends in a repeating cycle of at
    most `REPEAT_CYCLE_MAX_PERIOD` calls, this call is one of that
    cycle's own, the history is recent enough to still be the same loop,
    and the cycle has reached a stage. A missing session id, an
    unreadable or absent ledger, a malformed row, and a path that will
    not resolve all land here as allow -- #1674 is what a veto costs when
    it fires on a session it was never meant to touch.
    """
    name = _normalized_name(tool_name)
    session = _normalized_id(session_id)
    digest = str(args_digest or "")[:_MAX_DIGEST_CHARS]
    # `not session` is a stated precondition, not a load-bearing branch, and
    # deleting it turns no test red: no row can be keyed to a blank session
    # (`_advance_repeat_streak` writes none and `_raw_repeat_streaks`
    # drops one a hand-edited file supplies), so the lookup below would miss
    # anyway. It stays because a veto should refuse on its own terms rather
    # than inherit its safety from two other functions.
    if not name or not session or not digest:
        return None
    tick = float(now if now is not None else time.time())
    try:
        row = _read_one_repeat_streak(tool_bursts_path(omh_home), session)
    except (OSError, ValueError, TypeError, RuntimeError):
        return None
    if row is None or tick - row["ts"] > REPEAT_STREAK_WINDOW_SECONDS:
        return None
    history = _decided_history(_fresh_history(row["history"], now=tick))
    cycle = _detect_cycle(history)
    if cycle is None:
        return None
    period, laps = cycle
    elements = history[-period:]
    if not _call_is_in_cycle(elements, name, digest):
        return None
    intercepted = int(row["intercepted"])
    stage = _repeat_stage(laps, period, intercepted, escalation_allowed=escalation_allowed)
    if stage == "watching":
        return None
    results_compared = _results_were_compared(history, period, laps)
    if stage == "approval":
        return {
            "action": "approve",
            "message": _repeat_approval_message(elements, laps, intercepted, results_compared),
            "rule_key": repeat_cycle_rule_key(elements),
        }
    return {"action": "block", "message": _repeat_block_message(elements, laps, results_compared)}


def repeat_call_streak(
    omh_home: str = "",
    *,
    session_id: object = "",
    escalation_allowed: bool,
    now: float | None = None,
) -> dict[str, Any]:
    """This session's current repeat streak, or an idle marker.

    The read side of the same row the gate reads, so a later surface can
    render `repeat xN` without reaching into the stored shape or
    re-deriving the stage rule. Adding that surface must not need a change
    here or in what is written.

    ``escalation_allowed`` has no default, and that is the whole of what
    makes `_repeat_stage`'s claim true rather than intended. The first
    version defaulted it to the attended answer, so a caller that simply
    omitted it rendered `approval` on a lane the gate was blocking -- and
    the test written to pin the fix asserted exactly that, pinning the
    counterexample beside the sentence. A required parameter cannot be
    omitted, so the disagreement is unreachable rather than merely
    discouraged. A caller rendering the stage a person will see (#1687's
    HUD row) passes `escalation_can_reach_a_person(session_id)`, the same
    call `pre_tool_call` makes.
    """
    current = float(now if now is not None else time.time())
    session = _normalized_id(session_id)
    idle: dict[str, Any] = {"status": "idle"}
    if not session:
        return idle
    try:
        row = _read_one_repeat_streak(tool_bursts_path(omh_home), session)
    except (OSError, ValueError, TypeError, RuntimeError):
        return idle
    live = _live_cycle(row, now=current)
    if live is None or row is None:
        return idle
    history, period, laps, intercepted = live
    ran = period * laps
    return {
        "status": "observed",
        # The most recent call, which for a period-1 cycle is the whole of
        # what repeats and for a longer one is where the cycle stands now.
        "tool": history[-1]["tool"],
        "args_digest": history[-1]["args_digest"],
        "period": period,
        "laps": laps,
        # Whether the results of every call in the cycle were compared, so
        # a surface rendering this cannot claim more than the gate would.
        "results_compared": _results_were_compared(history, period, laps),
        # Calls the host dispatched, and calls this guard did not let
        # through. Kept apart because only the first is evidence that a
        # call ran, and their sum is what a person is shown at stage two.
        "ran": ran,
        "intercepted": intercepted,
        "consecutive": ran + intercepted,
        "stage": _repeat_stage(laps, period, intercepted, escalation_allowed=escalation_allowed),
        "observed_at": _iso(row["ts"]),
        "claim_boundary": REPEAT_CALL_CLAIM_BOUNDARY,
    }


def _live_cycle(
    row: dict[str, Any] | None, *, now: float
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    """One sanitized row read as a cycle, or None when it describes none.

    `(decided history, period, laps, intercepted)`. Shared by every reader
    of a row so the gate's view and a surface's view cannot be assembled
    two different ways from the same bytes -- the same reason
    `_sanitized_repeat_streak_row` is shared by the two file readers.

    No cycle is the one-lap reading: the last call, once. That keeps a
    reader's numbers continuous with the gate's -- a session one call into
    a repeat reports `ran: 1`, the way the counter this replaced did --
    rather than reporting a cycle that has not formed. A surface that must
    not render a single call as a repeat asks for `laps`, which is 1
    there and 2 or more once something actually repeated.
    """
    if row is None or now - row["ts"] > REPEAT_STREAK_WINDOW_SECONDS:
        return None
    history = _decided_history(_fresh_history(row["history"], now=now))
    if not history:
        return None
    period, laps = _detect_cycle(history) or (1, 1)
    return history, period, laps, int(row["intercepted"])


def _repeat_row_projection(
    streaks: dict[str, dict[str, Any]], session: object, *, now: float
) -> dict[str, Any]:
    """The repeat block of the HUD payload: idle, or a repeat and its stage.

    Built from rows a caller has ALREADY read, never from a read of its
    own. `read_omh_hud` takes one snapshot of this ledger per poll and
    three projections come out of it; a second read here would be a
    second chance to straddle a concurrent writer, and the HUD reader is
    spawned every two seconds per TUI.

    Three things this deliberately does not carry, and one it does:

    * **Not the tool name and not the argument digest.** #1687 asks the
      row to say that a call repeated and never what it was, and a
      surface cannot render a field it was not given. The digest is
      one-way and the tool name is already in the clear inside the
      ledger, so neither is a disclosure on its own -- they are simply
      not this row's business, and leaving them out is what makes the
      privacy claim checkable against the serialized payload rather than
      argued.
    * **Not a single call.** `laps` is 1 for a session that made one
      call, and rendering `repeat x1` on every tool call is noise, not a
      loop. The block answers `idle` until something has actually
      repeated, which is also #1687's acceptance criterion: N different
      calls show nothing.
    * **The stage the gate would act on, or none.** The attendance answer
      comes off the row (`_ROW_ESCALATION_KEY`), where the gate recorded
      its own. A row written before this field existed, or by a caller
      that had no answer to give, withholds the escalation stage rather
      than assuming it -- rendering `approval` where the gate blocks is
      the one disagreement this projection must not produce, and
      `escalation_recorded` says which of the two happened.
    """
    key = _normalized_id(session)
    idle: dict[str, Any] = {"status": "idle"}
    if not key:
        return idle
    raw = streaks.get(key)
    row = _sanitized_repeat_streak_row(raw) if isinstance(raw, dict) else None
    live = _live_cycle(row, now=now)
    if live is None or row is None:
        return idle
    history, period, laps, intercepted = live
    if laps < 2:
        return idle
    recorded = row["escalation_allowed"]
    ran = period * laps
    # Field order is load bearing at one extreme: `_fit_widget_hud_budget`
    # truncates an oversized payload's dicts to their first N keys, so the
    # three a surface renders come first and a block cut to four keys still
    # says a repeat happened, how long, and what the guard did about it.
    return {
        "status": "observed",
        "consecutive": ran + intercepted,
        "stage": _repeat_stage(
            laps, period, intercepted, escalation_allowed=bool(recorded)
        ),
        "period": period,
        # True once the cycle is longer than one call: "the same call over
        # and over" and "this short sequence over and over" are different
        # things to look at, and the surface says which.
        "cycle": period > 1,
        "laps": laps,
        "results_compared": _results_were_compared(history, period, laps),
        "ran": ran,
        "intercepted": intercepted,
        "escalation_recorded": recorded is not None,
        "observed_at": _iso(row["ts"]),
        "claim_boundary": REPEAT_CALL_CLAIM_BOUNDARY,
    }


def record_tool_call(
    tool_name: object,
    *,
    omh_home: str = "",
    now: float | None = None,
    tool_call_id: object = None,
    turn_id: object = None,
    args_digest: object = "",
    session_id: object = "",
    escalation_allowed: bool | None = None,
) -> None:
    """Append one pre_tool_call tick and, when the host supplies a
    tool_call_id, open an in-flight entry post_tool_call will close.

    ``escalation_allowed`` is the answer the GATE just computed for this
    session, threaded through rather than recomputed so the value stored
    is literally the one the directive was decided with. ``None`` means
    this caller had no answer to give, which a reader treats as "no
    escalation stage" rather than as "attended"; see
    `_ROW_ESCALATION_KEY`. It is not required, because a writer that
    cannot answer must still be able to record the call -- a missing
    answer costs a surface one rung of detail and costs the gate
    nothing, while a required parameter would push every caller into
    inventing one.

    Best-effort: losing a tick is acceptable, breaking the hook that feeds
    the model is not. What a lost tick now costs is worth naming, because
    it went up. The lock waits 0.1 s (`_LOCK_TIMEOUT_SECONDS`) and raises
    a `TimeoutError`, which is an `OSError`, so a write lost to contention
    lands in the swallow below and the call never enters the history. For
    the single counter this replaced that was one missed increment out of
    eight. For a cycle detector the missing element breaks the pattern its
    neighbours formed and resets the laps to 1, which can cost the whole
    engagement rather than one step of it.

    The direction is unchanged -- a lost write can only delay a refusal,
    never invent one -- and the same contention that loses the write is a
    machine where several sessions share one OMH home, which is where the
    guard is least likely to be the thing that matters. #1734 covers
    counting these; nothing here adds a new silent swallow."""
    name = _normalized_name(tool_name)
    if not name:
        return
    tick = float(now if now is not None else time.time())
    call_id = _normalized_id(tool_call_id)
    path = tool_bursts_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            record = _read_record(path)
            open_calls = _prune_expired_opens(record["open_calls"], now=tick)
            # How many calls this install already has open the instant this
            # one starts, counting itself if it opens too. This is the only
            # honest concurrency evidence available: closed entries carry no
            # end time (record_tool_call_close only deletes them), so a
            # group's true peak can only be observed live, at tick time, not
            # reconstructed afterward from start ticks alone.
            open_at_tick = len(open_calls) + (1 if call_id else 0)
            entries = record["entries"]
            entries.append({"tool": name, "ts": tick, "id": call_id, "open_at_tick": open_at_tick})
            entries = entries[-MAX_TOOL_BURST_ENTRIES:]
            if call_id:
                open_calls[call_id] = {
                    "tool": name,
                    "turn_id": _normalized_id(turn_id),
                    "started_at": tick,
                }
                open_calls = _cap_open_calls(open_calls)
            # Recorded here rather than in the gate so the history only
            # ever holds calls that reached dispatch: a call the gate
            # refused never ran, and must not be reported as one that did.
            repeat_streaks = _advance_repeat_streak(
                _prune_stale_streaks(record["repeat_streaks"], now=tick),
                session=_normalized_id(session_id),
                tool=name,
                args_digest=str(args_digest or "")[:_MAX_DIGEST_CHARS],
                now=tick,
                escalation_allowed=escalation_allowed,
            )
            _write_delivery_record(
                path,
                {
                    "schema_version": TOOL_BURSTS_SCHEMA_VERSION,
                    "entries": entries,
                    "open_calls": open_calls,
                    "repeat_streaks": repeat_streaks,
                    "post_tool_call_observed_at": record["post_tool_call_observed_at"],
                },
                # The one ledger written on every tool call, and the only
                # one holding a per-session call history. See the writer.
                compact=True,
            )
    except (OSError, ValueError, TypeError):
        return


def record_repeat_refusal(
    *,
    tool_name: object,
    args_digest: object,
    session_id: object,
    omh_home: str = "",
    now: float | None = None,
) -> None:
    """Count one call the repeat guard did not let through.

    Separate from ``record_tool_call`` because the two facts are
    different, and collapsing them would cost the block message its
    honesty: that one records a call the host went on to dispatch, this
    one records a call it did not. Keeping them apart is what lets the
    message say how many times the call actually RAN while the stage
    ladder still advances on attempts nobody ran.

    Only ever updates a row whose recorded history ends in a cycle this
    call continues. It creates none, and it re-derives the cycle rather
    than trusting that the caller had a reason: a refusal can only follow
    a detected loop, so a row that no longer shows one means the caller
    and the ledger disagree and the safe reading is that there is nothing
    to count. Best-effort, like every writer here.
    """
    name = _normalized_name(tool_name)
    session = _normalized_id(session_id)
    digest = str(args_digest or "")[:_MAX_DIGEST_CHARS]
    if not name or not session or not digest:
        return
    tick = float(now if now is not None else time.time())
    path = tool_bursts_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            record = _read_record(path)
            streaks = _prune_stale_streaks(record["repeat_streaks"], now=tick)
            raw = streaks.get(session)
            current = _sanitized_repeat_streak_row(raw) if isinstance(raw, dict) else None
            if current is None:
                return
            history = _decided_history(_fresh_history(current["history"], now=tick))
            cycle = _detect_cycle(history)
            if cycle is None:
                return
            if not _call_is_in_cycle(history[-cycle[0] :], name, digest):
                return
            streaks[session] = {
                # The stored row, with two fields advanced: its history is
                # carried through untouched, because a refused call never
                # ran and so is not a call to record.
                **raw,
                # Capped like every other counter in this bundle. A session
                # that ignores the guard for long enough must not be able to
                # grow a field without bound in a file the hot path rewrites
                # on every call; past the block stage the exact number stops
                # meaning anything anyway.
                "intercepted": min(MAX_INTERCEPTED_COUNT, int(current["intercepted"]) + 1),
                # The loop is still live, so the row is too. Without this a
                # long enough sequence of refused calls would age past the
                # window and hand the model a fresh budget.
                "ts": tick,
            }
            _write_delivery_record(
                path,
                {
                    "schema_version": TOOL_BURSTS_SCHEMA_VERSION,
                    "entries": record["entries"],
                    "open_calls": _prune_expired_opens(record["open_calls"], now=tick),
                    "repeat_streaks": streaks,
                    "post_tool_call_observed_at": record["post_tool_call_observed_at"],
                },
                # The one ledger written on every tool call, and the only
                # one holding a per-session call history. See the writer.
                compact=True,
            )
    except (OSError, ValueError, TypeError):
        return


def record_tool_call_close(
    tool_call_id: object,
    *,
    omh_home: str = "",
    now: float | None = None,
    session_id: object = "",
    tool_name: object = "",
    args_digest: object = "",
    result_digest: object = "",
) -> None:
    """post_tool_call: close the in-flight entry pre_tool_call opened, fill
    in what this call returned, and record that this install has observed
    post_tool_call actually fire.

    The result digest lands here because this is the earliest seam that
    sees a result, and the only one that sees it clean. OMH's own
    `transform_tool_result` passes run after this and may annotate the
    string; the host's loop-guardrail note is appended later still, by
    `agent/tool_executor.py`, and it carries a lap count that changes on
    every call. Digesting at either of those points would make every
    result look different from the one before it and the guard would
    never see a repeat at all.

    The close itself is a no-op when there is nothing to close -- an already
    expired entry, or a host that never sent the matching pre_tool_call tick
    (or any tick at all, for a host that omits tool_call_id). But this
    function running at all is the evidence the HUD's activity block needs:
    ``_host_supports_hook`` skips registering post_tool_call on hosts whose
    ``VALID_HOOKS`` predates it, and on such a host this is simply never
    called. Recording that timestamp unconditionally -- even when there is
    no entry to close -- is what lets the reader tell "this host never
    fires post_tool_call, liveness is unanswerable" apart from "this host
    fires it and nothing happens to be open right now". Best-effort, same
    as ``record_tool_call``."""
    call_id = _normalized_id(tool_call_id)
    tick = float(now if now is not None else time.time())
    path = tool_bursts_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            record = _read_record(path)
            open_calls = _prune_expired_opens(record["open_calls"], now=tick)
            if call_id and call_id in open_calls:
                del open_calls[call_id]
            observed_at = max(tick, record["post_tool_call_observed_at"])
            # Pruned, never dropped. Closing a call says nothing about
            # whether the next one repeats it, and a writer that dropped
            # this key would silently disarm the guard.
            streaks = _prune_stale_streaks(record["repeat_streaks"], now=tick)
            _fill_result_digest(
                streaks,
                session=_normalized_id(session_id),
                tool=_normalized_name(tool_name),
                args_digest=str(args_digest or "")[:_MAX_DIGEST_CHARS],
                result_digest=str(result_digest or "")[:_MAX_DIGEST_CHARS],
            )
            _write_delivery_record(
                path,
                {
                    "schema_version": TOOL_BURSTS_SCHEMA_VERSION,
                    "entries": record["entries"],
                    "open_calls": open_calls,
                    "repeat_streaks": streaks,
                    "post_tool_call_observed_at": observed_at,
                },
                # The one ledger written on every tool call, and the only
                # one holding a per-session call history. See the writer.
                compact=True,
            )
    except (OSError, ValueError, TypeError):
        return


def _fill_result_digest(
    streaks: dict[str, dict[str, Any]],
    *,
    session: str,
    tool: str,
    args_digest: str,
    result_digest: str,
) -> None:
    """Record what one call returned, in place, or do nothing.

    Matched by the call's own identity -- session, tool, argument digest
    -- and filled into the OLDEST entry still waiting for a result, which
    is first-in-first-out for the only case where more than one is
    waiting: a parallel batch of the same call. The host's
    ``tool_call_id`` would be exact, and was tried; it cost 30-odd bytes
    on every one of a session's sixteen entries, on a file
    `pre_tool_call` rereads and rewrites on every allowed call, to
    disambiguate entries that are identical in everything the comparator
    reads. Two entries that could be confused here agree on their tool
    and their arguments, so swapping their results changes nothing unless
    the results differ -- and results that differ break the cycle either
    way round.

    Every missing piece -- no session, no digest, no waiting entry --
    leaves the entry unknown, which `_elements_equal` reads as "no
    evidence either way" and falls back to the argument comparison.
    """
    if not session or not tool or not args_digest or not result_digest:
        return
    row = streaks.get(session)
    history = row.get("history") if isinstance(row, dict) else None
    for entry in history if isinstance(history, list) else []:
        if not isinstance(entry, dict) or entry.get(_HISTORY_RESULT_KEY):
            continue
        if entry.get(_HISTORY_TOOL_KEY) == tool and entry.get(_HISTORY_ARGS_KEY) == args_digest:
            entry[_HISTORY_RESULT_KEY] = result_digest
            return


def _read_one_repeat_streak(path: Path, session: str) -> dict[str, Any] | None:
    """One session's row, sanitized, without touching any other session's.

    The gate runs on every tool call and needs exactly one row, while
    `_read_record` rebuilds every row in the file -- at the caps, a
    thousand dictionaries constructed to answer a question about sixteen
    of them. Reading one row keeps the gate's cost a function of the
    parse and of this session's own history, not of how many other
    sessions share the OMH home.

    The lookup is by the exact key, which is what every writer here
    stores (`_normalized_id` is applied before the write and before this
    call). A hand-edited file whose key needs normalizing is missed, and
    a missed row reads as no history, which allows.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    source = raw.get("repeat_streaks") if isinstance(raw, dict) else None
    item = source.get(session) if isinstance(source, dict) else None
    if not isinstance(item, dict):
        return None
    return _sanitized_repeat_streak_row(item)


def _read_record(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "entries": _sanitized_entries(raw),
        "open_calls": _sanitized_open_calls(raw),
        "repeat_streaks": _raw_repeat_streaks(raw),
        "post_tool_call_observed_at": _sanitized_observed_at(raw),
    }


def _sanitized_observed_at(raw: dict[str, Any]) -> float:
    value = raw.get("post_tool_call_observed_at")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _sanitized_entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    source = raw.get("entries")
    entries: list[dict[str, Any]] = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        tick = item.get("ts")
        tool = str(item.get("tool", "") or "")
        open_at_tick = item.get("open_at_tick")
        if isinstance(tick, (int, float)) and not isinstance(tick, bool) and tool:
            entries.append(
                {
                    "tool": tool[:_MAX_TOOL_NAME_CHARS],
                    "ts": float(tick),
                    "id": _normalized_id(item.get("id")),
                    "open_at_tick": (
                        int(open_at_tick)
                        if isinstance(open_at_tick, (int, float)) and not isinstance(open_at_tick, bool)
                        else 1
                    ),
                }
            )
    entries.sort(key=lambda entry: entry["ts"])
    return entries


def _sanitized_open_calls(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = raw.get("open_calls")
    open_calls: dict[str, dict[str, Any]] = {}
    for call_id, item in (source.items() if isinstance(source, dict) else ()):
        if not isinstance(item, dict):
            continue
        started_at = item.get("started_at")
        normalized_id = _normalized_id(call_id)
        if not normalized_id or not isinstance(started_at, (int, float)) or isinstance(started_at, bool):
            continue
        open_calls[normalized_id] = {
            "tool": str(item.get("tool", "") or "")[:_MAX_TOOL_NAME_CHARS],
            "turn_id": _normalized_id(item.get("turn_id")),
            "started_at": float(started_at),
        }
    return open_calls


def _raw_repeat_streaks(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Rows exactly as the file holds them, minus the ones nothing can use.

    Carried through rather than rebuilt, which is the opposite of what
    every other reader in this file does and is deliberate. A writer
    touches one session; rebuilding the other sixty-three on every tool
    call was the largest single cost of keeping a history at all, and it
    bought nothing, because a row is sanitized where it is COMPARED
    (`_sanitized_repeat_streak_row`, one row, at the gate) and a row
    written back unchanged is the same bytes the file already held.

    A row without a usable timestamp is dropped: pruning and capping both
    read it, and a row neither can place is dead weight. A row written by
    the single-counter form this replaced keeps its timestamp and so
    survives here, then fails to produce a history when the gate reads
    it -- one session loses a count it had already earned, which is the
    same as its guard never having armed.
    """
    source = raw.get("repeat_streaks")
    rows: dict[str, dict[str, Any]] = {}
    for session, item in (source.items() if isinstance(source, dict) else ()):
        key = _normalized_id(session)
        if key and isinstance(item, dict) and _row_tick(item) is not None:
            rows[key] = item
    return rows


def _row_tick(item: dict[str, Any]) -> float | None:
    """A row's last-activity stamp, or None when the row has no usable one.

    The only field a writer reads out of a row it is not touching:
    pruning and capping are both decided by it, and neither needs to
    know what the row's history says.
    """
    value = item.get("ts")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _sanitized_repeat_streak_row(item: dict[str, Any]) -> dict[str, Any] | None:
    """One row, or None when nothing in it can be compared.

    Shared by the whole-file read and the gate's single-row read so the
    two cannot come to different conclusions about the same bytes.
    """
    tick = item.get("ts")
    intercepted = item.get("intercepted")
    if not isinstance(tick, (int, float)) or isinstance(tick, bool):
        return None
    history = _sanitized_history(item.get("history"))
    if not history:
        return None
    return {
        "history": history,
        # The one field that defaults instead of dropping the row. A row
        # hand-edited without it has observed no interceptions, and 0
        # delays the next stage rather than inventing evidence for it.
        "intercepted": (
            int(intercepted)
            if isinstance(intercepted, int) and not isinstance(intercepted, bool) and intercepted >= 0
            else 0
        ),
        # Tri-state on purpose: True, False, or "the gate never said".
        # Collapsing the third into either of the first two is what makes
        # a reader render a stage the gate would not act on.
        "escalation_allowed": _row_escalation(item),
        "ts": float(tick),
    }


def _sanitized_history(source: object) -> list[dict[str, Any]]:
    """The recorded calls of one session, in the order they were made.

    Deliberately not sorted, unlike `entries`: the cycle detector reads
    adjacency, so re-ordering by timestamp would let a file with two
    equal stamps decide what repeats. An entry missing the tool, the
    argument digest, or a timestamp is dropped -- those are the three
    fields a comparison needs, and a defaulted one would be a call
    nobody made.
    """
    entries: list[dict[str, Any]] = []
    for item in source if isinstance(source, list) else []:
        if not isinstance(item, dict):
            continue
        tool = str(item.get(_HISTORY_TOOL_KEY, "") or "")[:_MAX_TOOL_NAME_CHARS]
        args_digest = str(item.get(_HISTORY_ARGS_KEY, "") or "")[:_MAX_DIGEST_CHARS]
        tick = item.get(_HISTORY_TICK_KEY)
        if not tool or not args_digest:
            continue
        if not isinstance(tick, (int, float)) or isinstance(tick, bool):
            continue
        entries.append(
            {
                "tool": tool,
                "args_digest": args_digest,
                # Absent is the normal state for a call still running and
                # for every call on a host without post_tool_call, so it
                # defaults rather than dropping the entry.
                "result_digest": str(item.get(_HISTORY_RESULT_KEY, "") or "")[:_MAX_DIGEST_CHARS],
                "ts": float(tick),
            }
        )
    return entries[-MAX_REPEAT_HISTORY:]


def _stored_history_entry(tool: str, args_digest: str, *, now: float) -> dict[str, Any]:
    """One history entry in the form the file holds.

    The timestamp is whole seconds. It is only ever compared against
    `REPEAT_STREAK_WINDOW_SECONDS`, so a resolution of one second cannot
    change an answer, and the eight characters it saves are paid on every
    entry of every row on every tool call.
    """
    return {
        _HISTORY_TOOL_KEY: tool,
        _HISTORY_ARGS_KEY: args_digest,
        # Unknown until post_tool_call fires for this call, which is the
        # correct state for a call that has not returned yet.
        _HISTORY_RESULT_KEY: "",
        _HISTORY_TICK_KEY: int(now),
    }


def _fresh_history(history: list[dict[str, Any]], *, now: float) -> list[dict[str, Any]]:
    """The calls recent enough to still describe one loop.

    Entries are appended in time order, so this always returns a suffix
    and the cycle detector never sees a gap stitched shut. A loop fires
    its repeats back to back inside one turn; calls this far apart are a
    session that came back, not a session that never stopped -- which is
    the false positive this closes, because a row stays alive as long as
    SOMETHING happens in it, and eight identical polls four minutes apart
    would otherwise read as one loop.
    """
    return [entry for entry in history if now - entry["ts"] <= REPEAT_STREAK_WINDOW_SECONDS]


def _decided_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The calls whose result this install actually saw, or all of them.

    `_elements_equal` reads an unknown result as "no evidence either way"
    and falls back to the arguments. That is right for a host that never
    fires `post_tool_call`, and wrong for a sibling call that has simply
    not returned yet. Hermes dispatches a batch through a pool of eight
    (`agent/tool_executor.py`), so at the gate for one call of a batch the
    rest of the batch is in flight, unknown, and under the fallback
    indistinguishable from a repeat. Measured: a `terminal` poll with a
    different output on every call, dispatched eight wide, was blocked at
    call 9 -- exactly what #1706 exists to prevent.

    So the ladder is computed over the calls that have returned. The
    fallback survives for the case it was written for and no other: when
    NOTHING in the history has a result this install has no result
    evidence at all, which is the host without `post_tool_call`, and the
    whole history is used -- the argument-only guard #1708 shipped.

    The cost, stated: on a batching host a real loop is engaged later,
    because a call in flight is not yet evidence of anything.
    """
    decided = [entry for entry in history if entry["result_digest"]]
    return decided or history


# Order note, because two exemptions meet here and only one order is
# reachable: this filter runs before `_detect_cycle`, so a poller whose
# result is unknown -- in flight, or not text -- is already gone by the
# time `is_poller_tool` is consulted. The poller skip therefore only ever
# sees calls that returned. That is the safe order (an unknown result
# cannot arm the guard, whatever tool produced it), and it means the two
# exemptions cannot disagree about the same call.


def _prune_stale_streaks(streaks: dict[str, dict[str, Any]], *, now: float) -> dict[str, dict[str, Any]]:
    """Drop rows no longer describing a live session. Reads only `ts`."""
    return {
        session: row
        for session, row in streaks.items()
        if now - (_row_tick(row) or 0.0) <= REPEAT_STREAK_WINDOW_SECONDS
    }


def _advance_repeat_streak(
    streaks: dict[str, dict[str, Any]],
    *,
    session: str,
    tool: str,
    args_digest: str,
    now: float,
    escalation_allowed: bool | None = None,
) -> dict[str, dict[str, Any]]:
    """Record this call in the session's history and re-read the loop.

    The self-clearing behaviour is now a property of the detector rather
    than of an overwrite: a call that leaves the history showing no cycle
    clears the interception count, so one genuinely new call disarms both
    stages at once and a session cannot be left stuck at the approval
    stage because a counter outlived the loop it described. A call that
    CONTINUES the cycle keeps the count, which is what lets four ignored
    blocks still add up to an escalation after the person allowed one.

    Nothing recorded when the host named no session or the arguments
    produced no digest -- the gate needs both to identify a repeat, and
    an entry it cannot key or compare would only ever be dead weight.
    """
    if not session or not args_digest:
        return streaks
    # The one row a writer rebuilds is the session it is recording; every
    # other row in `streaks` is carried through as the file held it. The
    # rebuild stays in the STORED form and sanitizes only to compare, so
    # one entry is never held in two shapes at once.
    row = streaks.get(session) or {}
    stored = _fresh_stored_history(row.get("history"), now=now)
    stored.append(_stored_history_entry(tool, args_digest, now=now))
    stored = stored[-MAX_REPEAT_HISTORY:]
    intercepted = row.get("intercepted")
    intercepted = int(intercepted) if isinstance(intercepted, int) and not isinstance(intercepted, bool) and intercepted >= 0 else 0
    # Detected on the WHOLE history rather than on `_decided_history`,
    # unlike the gate. This is a storage decision, not a ladder decision:
    # the call just appended has no result yet, so the decided view would
    # always exclude it and every first call of a batch would look like
    # the end of a loop and drop the history the next one needs.
    #
    # What the difference can cost, stated: an interception count can
    # outlive the gate's view of the cycle for as long as the arguments
    # alone still form one. It cannot be invented -- `record_repeat_refusal`
    # only increments behind the gate's own filtered detection -- so the
    # residue is at most an escalation arriving sooner in a session that
    # was already looping on the same arguments.
    if _detect_cycle(_sanitized_history(stored)) is None:
        intercepted = 0
        stored = stored[-IDLE_REPEAT_HISTORY:]
    row_out: dict[str, Any] = {"history": stored, "intercepted": intercepted, "ts": now}
    # This call's answer wins; a caller that had none leaves the last one
    # the gate recorded in place. The two maps the predicate reads are
    # per session and do not move between one call and the next, so the
    # previous answer is still the gate's answer for this session -- and
    # dropping it would silently downgrade a surface from the gate's
    # stage to no stage at all on the first write that came from a caller
    # without one.
    recorded = escalation_allowed if escalation_allowed is not None else _row_escalation(row)
    if recorded is not None:
        row_out[_ROW_ESCALATION_KEY] = bool(recorded)
    streaks[session] = row_out
    return _cap_repeat_streaks(streaks)


def _row_escalation(item: dict[str, Any]) -> bool | None:
    """The attendance answer stored on a row, or None when it holds none.

    Only a real boolean answers. A hand-edited or foreign value is the
    same as an absent one, which withholds the escalation stage -- the
    direction a reader must fail in.
    """
    value = item.get(_ROW_ESCALATION_KEY)
    return value if isinstance(value, bool) else None


def _fresh_stored_history(source: object, *, now: float) -> list[dict[str, Any]]:
    """The stored entries still inside the window, as stored.

    The same rule as `_fresh_history` applied one representation
    earlier, so the writer never has to turn entries into the compared
    form and back to drop the old ones.
    """
    entries: list[dict[str, Any]] = []
    for item in source if isinstance(source, list) else []:
        tick = item.get(_HISTORY_TICK_KEY) if isinstance(item, dict) else None
        if not isinstance(tick, (int, float)) or isinstance(tick, bool):
            continue
        if now - float(tick) <= REPEAT_STREAK_WINDOW_SECONDS:
            entries.append(item)
    return entries


def _cap_repeat_streaks(streaks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(streaks) <= MAX_REPEAT_STREAKS:
        return streaks
    newest_first = sorted(streaks.items(), key=lambda item: _row_tick(item[1]) or 0.0, reverse=True)
    return dict(newest_first[:MAX_REPEAT_STREAKS])


def _prune_expired_opens(open_calls: dict[str, dict[str, Any]], *, now: float) -> dict[str, dict[str, Any]]:
    return {
        call_id: entry
        for call_id, entry in open_calls.items()
        if now - float(entry.get("started_at", now)) <= TOOL_CALL_OPEN_TTL_SECONDS
    }


def _cap_open_calls(open_calls: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(open_calls) <= MAX_OPEN_TOOL_CALLS:
        return open_calls
    newest_first = sorted(open_calls.items(), key=lambda item: item[1]["started_at"], reverse=True)
    return dict(newest_first[:MAX_OPEN_TOOL_CALLS])


def _iso(tick: float) -> str:
    return datetime.fromtimestamp(tick, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _latest_shot_from_entries(
    entries: list[dict[str, Any]],
    open_calls: dict[str, dict[str, Any]],
    *,
    now: float,
) -> dict[str, Any]:
    idle: dict[str, Any] = {"status": "idle"}
    if not entries:
        return idle
    groups: list[list[dict[str, Any]]] = [[entries[0]]]
    for entry in entries[1:]:
        if entry["ts"] - groups[-1][-1]["ts"] <= BURST_WINDOW_SECONDS:
            groups[-1].append(entry)
        else:
            groups.append([entry])
    latest = next((group for group in reversed(groups) if len(group) >= 2), None)
    if latest is None:
        return idle
    last_tick = latest[-1]["ts"]
    if now - last_tick > BURST_FRESH_SECONDS:
        return idle
    open_count = sum(1 for entry in latest if entry.get("id") and entry["id"] in open_calls)
    return {
        "status": "observed",
        "size": len(latest),
        "distinct_tools": len({entry["tool"] for entry in latest}),
        "observed_at": _iso(last_tick),
        # True in-flight split within this shot's own members, not the ring
        # ceiling: a batch of 40 that saturated the old ring could not tell
        # "still running" from "buffer full".
        "open_count": open_count,
        # NOT a completion claim -- naming it that contradicted
        # TOOL_CALL_OPEN_TTL_SECONDS's own rule that an expired open entry is
        # "never reported as completed (nothing observed it finishing)".
        # This is every member not currently open: a member with no
        # tool_call_id (host degraded to pre-pairing behavior) was never
        # opened, and an expired member's close was never observed either --
        # both land here as "not open", which is the only claim the data
        # backs, not "finished".
        "closed_or_unobserved_count": len(latest) - open_count,
        # The highest open_at_tick observed among this group's own members:
        # at least this many calls were open simultaneously at some point
        # during the shot. This is the group's actual measured concurrency,
        # not `size` -- `size` only proves the host dispatched these calls
        # inside the grouping window, which a long strictly-sequential chain
        # can satisfy just as well as a real parallel batch (Hermes caps
        # concurrent tool workers well under `size` in either case).
        "peak_open_count": max((entry.get("open_at_tick", 1) for entry in latest), default=0),
        "claim_boundary": TOOL_BURST_CLAIM_BOUNDARY,
    }


def _read_snapshot(omh_home: str, *, now: float) -> dict[str, Any]:
    """One ledger read, pruned to `now`. The single point every projection
    below builds from, so a poll that needs more than one projection (the
    HUD reader wants both the parallel-shot and the activity block) sees one
    consistent state instead of two reads that can straddle a concurrent
    writer and disagree about what is currently open."""
    record = _read_record(tool_bursts_path(omh_home))
    return {
        "entries": record["entries"],
        "open_calls": _prune_expired_opens(record["open_calls"], now=now),
        # Rows as the file held them. `_read_record` carries them through
        # rather than rebuilding them, and only the ONE row a projection
        # asks about is sanitized -- so adding the repeat block costs this
        # read nothing beyond the dictionary lookup for that row.
        "repeat_streaks": _prune_stale_streaks(record["repeat_streaks"], now=now),
        "post_tool_call_observed_at": record["post_tool_call_observed_at"],
    }


def _activity_from_snapshot(snapshot: dict[str, Any], shot: dict[str, Any], *, now: float) -> dict[str, Any]:
    open_calls = snapshot["open_calls"]
    count = len(open_calls)
    if count:
        oldest_id, oldest = min(open_calls.items(), key=lambda item: item[1]["started_at"])
        oldest_started_at = _iso(oldest["started_at"])
        oldest_elapsed_seconds: float | None = max(0.0, now - oldest["started_at"])
    else:
        oldest_started_at = ""
        oldest_elapsed_seconds = None
    return {
        "schema_version": TOOL_ACTIVITY_SCHEMA_VERSION,
        "open_call_count": count,
        "oldest_open_started_at": oldest_started_at,
        "oldest_open_elapsed_seconds": oldest_elapsed_seconds,
        "live": count > 0,
        # Whether this OMH install has ever seen post_tool_call actually
        # fire (record_tool_call_close ran at least once). False on a host
        # `_host_supports_hook` skipped registering post_tool_call for: the
        # ledger's open entries can only expire there, never legitimately
        # close, so `live`/`oldest_open_elapsed_seconds` cannot be trusted
        # either way and the HUD must render liveness as unanswerable
        # rather than inverting silence into a false stall.
        "post_tool_call_observed": snapshot["post_tool_call_observed_at"] > 0,
        "latest_shot": shot,
        "claim_boundary": TOOL_ACTIVITY_CLAIM_BOUNDARY,
    }


def latest_parallel_shot(omh_home: str = "", *, now: float | None = None) -> dict[str, Any]:
    """Project the most recent concurrent batch, or an idle marker."""
    current = float(now if now is not None else time.time())
    snapshot = _read_snapshot(omh_home, now=current)
    return _latest_shot_from_entries(snapshot["entries"], snapshot["open_calls"], now=current)


def tool_call_activity(omh_home: str = "", *, now: float | None = None) -> dict[str, Any]:
    """The HUD's liveness signal: exact open tool-call count plus the shot.

    ``live`` is true precisely while at least one tool call this OMH install
    saw open has not yet closed and has not expired -- it answers "is
    something actually running right now", the question the ring-buffer-only
    badge and a lingering active todo item could not.
    """
    current = float(now if now is not None else time.time())
    snapshot = _read_snapshot(omh_home, now=current)
    shot = _latest_shot_from_entries(snapshot["entries"], snapshot["open_calls"], now=current)
    return _activity_from_snapshot(snapshot, shot, now=current)


def tool_call_projection(
    omh_home: str = "", *, session_id: object = "", now: float | None = None
) -> dict[str, Any]:
    """`{"parallel_shot": ..., "activity": ..., "repeat": ...}` from one read.

    The HUD reader needs all three projections every poll; calling
    ``latest_parallel_shot`` and ``tool_call_activity`` separately each reads
    the ledger file on its own, so a write landing between the two reads
    could hand the two blocks different snapshots of the same poll. This is
    the single-read equivalent of calling them all.

    ``session_id`` scopes the repeat block and nothing else. The first two
    projections are install-wide by construction -- an open call is open
    whoever made it -- while a repeat streak is one session's, and two
    sessions sharing an OMH home must not add up. No session id means no
    repeat block, never a sum over the file.
    """
    current = float(now if now is not None else time.time())
    snapshot = _read_snapshot(omh_home, now=current)
    shot = _latest_shot_from_entries(snapshot["entries"], snapshot["open_calls"], now=current)
    return {
        "parallel_shot": shot,
        "activity": _activity_from_snapshot(snapshot, shot, now=current),
        "repeat": _repeat_row_projection(snapshot["repeat_streaks"], session_id, now=current),
    }
