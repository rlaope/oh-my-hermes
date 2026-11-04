"""Shared store for the HUD todo artifact.

One todo list per declaring session. A record that knows the host session
that declared it (``session_ref``) lives at
``$OMH_HOME/runtime/todos/<session key>.json``; a record written without one
-- `omh runtime todo set` with no ``--session``, or anything predating the
field -- keeps the home-wide ``$OMH_HOME/runtime/todo.json``. The CLI and the
`omh_todo` plugin tool both write through this module so the schema has a
single source of truth; `runtime_reader` projects the records into the HUD
payload read-only, choosing the file that belongs to the reading session.

The per-session layout is what keeps unrelated sessions apart: a plan
declared from a Slack or Discord gateway session, or from a second live TUI,
is its own file, so it neither overwrites nor renders inside another
session's checklist. Writers sharing one home no longer race for one file.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

# The bundle's one sanctioned lock, the same object `tool_bursts`,
# `approval_bypass` and `memory_open_reminders` take. It carries both backends
# because this directory is vendored into the user's Hermes install and may not
# import omh core; a copy here would be the third, and the policy gate in
# `tests/test_journal_lock_portability.py` exists to stop exactly that.
from .awareness_delivery import _awareness_delivery_lock
from .native_tools import NATIVE_CANCELLED_REASON, NATIVE_TODO_TOOL
from .todo_evidence import EVIDENCE_KINDS, evidence_key, valid_evidence
from .todo_templates import (
    TODO_TEMPLATES,
    template_coverage_error,
    template_items,
    template_phase_labels,
)
from .iso_datetime import strict_fromisoformat

TODO_SCHEMA_VERSION = "omh_todo/v1"
TODO_FILENAME = "todo.json"
# Per-session records live one directory below the home-wide file, keyed by
# the declaring session. The directory is bounded on every write: records
# past the reader's own stale bound are removed, and so are temporary files a
# crashed write left behind. Only files this module wrote are candidates --
# a record's name has the key shape below -- so nothing else placed in the
# directory is ever touched, and a fresh record is never evicted to make
# room: one session declares one record, and the stale window is the bound.
TODO_SESSION_DIRNAME = "todos"
TODO_STALE_SECONDS = 86400
_SESSION_RECORD_NAME = re.compile(r"(?:[A-Za-z0-9_-]{1,48}-)?[0-9a-f]{16}\.json")
_TEMPORARY_NAME = re.compile(r"\..*\.tmp")
# The lock file beside a record, named the same way so the prune below can
# recognise its own. It is only ever a rendezvous point: nothing is read out
# of it and nothing is written into it.
_LOCK_NAME = re.compile(r"\..*\.json\.lock")
# How long a writer waits for this record before refusing. The shared lock's
# own default is 0.1s, sized for telemetry that would rather drop a counter
# than delay a turn; a plan write is the opposite trade, so this passes its
# own. A write here is a few hundred microseconds of work, so a wait measured
# in whole seconds means a holder is stuck rather than busy -- long enough
# that a contended turn waits instead of failing, short enough that a stuck
# holder becomes a refusal the caller can act on.
_LOCK_TIMEOUT_SECONDS = 2.0
# The largest record this module reads back itself (clear's stamp check);
# the HUD reader applies the same cap to every metadata file.
MAX_TODO_RECORD_BYTES = 262_144
TODO_ITEM_STATES = ("pending", "active", "done")
MAX_TODO_ITEMS = 20
MAX_TODO_TEXT_CHARS = 200
MAX_TODO_TITLE_CHARS = 80
MAX_TODO_SOURCE_CHARS = 80
# Optional owning-session id, stamped when the writer knows which host session
# declared the plan. Bounded to the host-observation session limit because it
# is the same identifier. A record without it is a legacy or CLI write, and
# readers scope it by write time instead of by identity.
MAX_TODO_SESSION_REF_CHARS = 160
# Optional phase label per item ("Internal Context", "Delivery", ...). A
# phase-structured plan declared BEFORE engine work bounds the run: progress
# is a checklist walked phase by phase, not an open-ended reasoning loop.
MAX_TODO_PHASE_CHARS = 60
# Optional reason an item cannot proceed. It is a FIELD rather than a fourth
# item state so the counts, the HUD projection and the widget keep reading
# three states; an item is still pending or active while it carries one.
#
# It exists because the plan's own stop criterion ("an item is recorded
# blocked with its reason") was previously inferred from the item text, and
# inference was wrong in both directions on ordinary input: "verify the retry
# is not blocked on the session limit" read as blocked, while "차단됨: 소유자
# 승인 대기" and "waiting on the owner's review" did not. A reader that
# decides whether work stops must read a record, not a substring.
MAX_TODO_BLOCKED_REASON_CHARS = 200
# Optional PLAN-LEVEL reason the person steered the session elsewhere. It is
# not a second `blocked_reason`, and what makes it a different field is the
# digest stored beside it rather than the wording: blocked is "this item
# cannot proceed" and is cleared by hand, this is "the person asked for
# something else first" and LAPSES ON ITS OWN.
#
# The reason is written together with a digest of the item list as it stood at
# the moment of deferral, and a reader honours the deferral only while that
# digest still matches the items it is reading. Marking an item done, moving
# which one is active, or re-scoping the list all change the digest, so a
# deferral cannot outlive the plan it was written against. That is the whole
# reason this is a field and not a hand-cleared flag: a flag someone must
# remember to clear is the same forgetting this surface exists to prevent,
# moved one step later. The state is derived from the items rather than
# asserted beside them, so it cannot drift from what the plan is.
#
# One consequence, stated rather than left to be discovered. A writer that
# sends the reason AGAIN alongside a changed item list gets a digest over the
# new list, so that is a new deferral for that list and not the old one
# surviving. Deliberate: the record is the declaration and the writer owns it,
# exactly as with `blocked_reason`. Every writer that does not re-send the
# field -- the CLI, which has none; a hand edit; a generation predating the
# field; and the tool, whose description says to omit it -- lapses the
# deferral by default, which is what makes resuming cost nobody a clearing
# step.
MAX_TODO_DEFERRED_REASON_CHARS = 200
# Optional name of the phase template this plan was stamped with
# (`todo_templates`). A closed vocabulary, not free text: the bound is what a
# reader allocates for it, and the validator below rejects anything that is
# not a known template name outright. Additive-optional like every field
# above it -- a record written without one is byte-identical to what this
# module wrote before the field existed.
MAX_TODO_TEMPLATE_CHARS = 40
# Optional stage of a PLANNING run: whether the person has accepted the plan
# this checklist belongs to. A closed vocabulary, additive-optional on exactly
# the terms above, and the whole of what `plan_stage_gate` reads -- the reason
# an unaccepted plan can be told from an accepted one without reading a word
# of anybody's prose.
#
# Absence is the third value and it means UNKNOWN, never "not accepted": a
# delivery plan, a CLI write, a record predating the field, and a planning run
# whose writer never stamped one are all the same absence here, and the gate
# stays silent for every one of them. Only `PLAN_STAGE_AWAITING_ACCEPTANCE`
# makes it speak.
#
# It is sticky across `advance` and declared per write on `set`, which is the
# same split `template` and `deferred_reason` already draw and for the same
# reason: marking a planning stage done is the plan ADVANCING, not the person
# accepting it, so an advance must not drop the stamp; re-declaring the
# checklist is a new declaration, so a `set` that omits the field has none.
# That is what makes the common close free -- a run handing an accepted plan
# to a delivery engine writes a new list and the gate lapses with it.
PLAN_STAGE_AWAITING_ACCEPTANCE = "awaiting_acceptance"
PLAN_STAGE_ACCEPTED = "accepted"
TODO_PLAN_STAGES = (PLAN_STAGE_AWAITING_ACCEPTANCE, PLAN_STAGE_ACCEPTED)
# Read only by the projection, and never as a truncation point on its own: a
# value cut to this length is the longest member whenever it merely STARTS
# like one, so the reader slices one past it and the writer tests membership
# before bounding anything. The writer needs no bound at all, because the
# only value it ever returns is a member.
MAX_TODO_PLAN_STAGE_CHARS = max(len(stage) for stage in TODO_PLAN_STAGES)
# The digest is only ever compared for equality, never inverted, so the bound
# is about how much record a deferral costs, not about collision resistance;
# 128 bits is far past what "is this the same item list" needs.
TODO_DEFERRED_DIGEST_CHARS = 32
# The item fields the digest covers: every field an item declares. Any edit to
# any of them is the plan moving, `blocked_reason` included -- writing down
# that an item is stuck is a plan advancing, not a plan standing still.
_DIGESTED_ITEM_KEYS = (
    "text", "state", "phase", "depth", "blocked_reason", "evidence", "done_at", "window_start",
)
# The fields OMH binds and a writer never supplies on the tool path
# (`bind_done_items`): what closed the item, when it was marked done, and where
# its window starts. `window_start` is stamped on an OPEN item too -- when it
# is declared, when it goes from pending to active, and when it leaves done --
# because a window opens at the item's own last transition, never at whatever
# plan write happened last. `evidence` survives a reopen: a failed binding is
# sticky until a later call in the item's window replaces it. `done_at` is only
# on a done item, and is the line between an item done before evidence existed
# -- none of the three, counted done as it always was -- and one the stop
# criterion judges.
TODO_DONE_BINDING_KEYS = ("evidence", "done_at", "window_start")
MAX_TODO_STAMP_CHARS = 40
# Plan-level: the bindings a whole-list `set` dropped because no item of the
# new list carries the text they were bound under -- a rename, a split, a
# removal -- each with when it was dropped. A binding that failed is the
# plan's memory of a check that did not pass under a name it no longer uses,
# so an item opened at or after the drop cannot close until a passing command
# of its own resolves it (`todo_evidence`). Bounded to the newest entries, one
# plan's worth. It lives in the record, so `clear` removes it with the plan.
MAX_TODO_DROPPED_BINDINGS = 20
# Optional nesting depth per item: 0 is a top-level task, 1..3 are subtask
# levels rendered indented beneath it (e.g. "검증작업하기" with usability /
# UI / load-verification children). Three levels is the owner's declared
# ceiling; deeper nesting stops reading as a checklist.
MAX_TODO_DEPTH = 3
TODO_CLAIM_BOUNDARY = (
    "Todo items are plan declarations. They are not execution, verification, "
    "review, CI, merge-readiness, or merge evidence."
)


class TodoValidationError(ValueError):
    """The supplied todo payload does not satisfy the omh_todo/v1 contract."""


class TodoStoreError(RuntimeError):
    """The todo destination under the OMH home is unsafe to write."""


class TodoContendedError(TodoStoreError):
    """Another writer held this record's lock for longer than the wait allows.

    A subclass, so every `except TodoStoreError` written before the lock
    existed keeps catching it and nothing has to learn a new failure to stay
    correct. It exists as its own type for the one caller that must tell the
    two apart: a refusal saying the payload was invalid tells a writer to
    change its arguments, and changing the arguments is exactly the wrong
    response to a lock that will be free in milliseconds. The right response
    is the same call again.
    """


# Terminal escape sequences are removed whole before the control characters
# below, so dropping an ESC does not leave its `[31m` behind as text for every
# renderer. The grammar is `omh.tui.escapes.strip_escapes`', which this
# directory cannot import (a test holds the two equal): a CSI, 7-bit or 8-bit,
# with its parameters, intermediates and final byte; a control string (OSC,
# DCS, SOS, PM, APC) up to BEL or ST, or to the end when unterminated; any
# other ESC with its intermediates and final byte. A sequence cut off goes as
# far as it got. Brackets without an introducer are text: `[31m` typed as
# such, or left at rest by a write from before this, stays as it is.
_ESCAPE_SEQUENCE = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]?"
    r"|(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f])(?:[^\x07\x1b\x9c]|\x1b(?!\\))*(?:\x07|\x1b\\|\x9c)?"
    r"|\x1b(?:[ -/]*[0-~])?"
)
# C0/C1 control characters (ESC, BEL, CR, LF included) are stripped on write
# and again on read so neither the artifact at rest nor the HUD projection can
# carry terminal escapes or forge extra checklist lines.
_CONTROL_CHARACTERS = {code: None for code in (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0))}


def strip_control_characters(value: object) -> str:
    return _ESCAPE_SEQUENCE.sub("", str(value or "")).translate(_CONTROL_CHARACTERS).strip()


def validate_todo_items(items: object) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise TodoValidationError("todo items must be a non-empty list")
    if len(items) > MAX_TODO_ITEMS:
        raise TodoValidationError(f"todo items are capped at {MAX_TODO_ITEMS}")
    validated: list[dict[str, str]] = []
    # One recorded fact closes at most one item: a call that closed item 1
    # copied onto items 2 and 3 would close three items with one command.
    bound: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise TodoValidationError("each todo item must be an object")
        text = strip_control_characters(item.get("text", ""))
        if not text:
            raise TodoValidationError("each todo item needs non-empty text")
        if len(text) > MAX_TODO_TEXT_CHARS:
            raise TodoValidationError(f"todo item text is capped at {MAX_TODO_TEXT_CHARS} characters")
        state = str(item.get("state", "pending"))
        if state not in TODO_ITEM_STATES:
            raise TodoValidationError(f"todo item state must be one of {', '.join(TODO_ITEM_STATES)}")
        phase = strip_control_characters(item.get("phase", ""))
        if len(phase) > MAX_TODO_PHASE_CHARS:
            raise TodoValidationError(f"todo item phase is capped at {MAX_TODO_PHASE_CHARS} characters")
        blocked_reason = strip_control_characters(item.get("blocked_reason", ""))
        if len(blocked_reason) > MAX_TODO_BLOCKED_REASON_CHARS:
            raise TodoValidationError(
                f"todo item blocked_reason is capped at {MAX_TODO_BLOCKED_REASON_CHARS} characters"
            )
        depth = item.get("depth", 0)
        if isinstance(depth, bool) or not isinstance(depth, int) or not 0 <= depth <= MAX_TODO_DEPTH:
            raise TodoValidationError(f"todo item depth must be an integer from 0 to {MAX_TODO_DEPTH}")
        evidence = _validated_evidence(item.get("evidence"), state)
        done_at = _validated_stamp(item.get("done_at"), state, "done_at")
        window_start = _validated_stamp(item.get("window_start"), "done", "window_start")
        entry: dict[str, Any] = {"text": text, "state": state}
        if phase:
            entry["phase"] = phase
        if depth:
            entry["depth"] = depth
        if blocked_reason:
            entry["blocked_reason"] = blocked_reason
        if evidence:
            key = evidence_key(evidence)
            if key in bound:
                raise TodoValidationError("todo item evidence is already bound to another item")
            bound.add(key)
            entry["evidence"] = evidence
        if done_at:
            entry["done_at"] = done_at
        if window_start:
            entry["window_start"] = window_start
        validated.append(entry)
    return validated


def _validated_evidence(evidence: object, state: str) -> dict[str, str] | None:
    """The item's evidence reference as it will be stored, or ``None``.

    A typed ``{"kind", "ref"}`` naming the recorded fact that closes a done
    item (`todo_evidence` says which kinds resolve and how). It is kept on an
    item that left done, because a failed binding is sticky until a later
    call replaces it, and refused when it is not one of the known kinds in
    its kind's shape, since a reader that cannot look it up would have to
    treat it as text.

    Absence is the common case and costs nothing: a record whose items carry
    no reference is byte-identical to one written before the field existed.
    """
    if evidence is None or evidence == "" or evidence == {}:
        return None
    checked = valid_evidence(evidence)
    if checked is None:
        kinds = ", ".join(EVIDENCE_KINDS)
        raise TodoValidationError(
            f"todo item evidence must be {{kind, ref}} with kind one of: {kinds}"
        )
    return checked


def _validated_stamp(value: object, state: str, name: str) -> str:
    """A bound ISO stamp as it will be stored, or ``""``; only on a done item."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise TodoValidationError(f"todo item {name} must be a timestamp string")
    safe = strip_control_characters(value)
    try:
        strict_fromisoformat(safe.replace("Z", "+00:00"))
    except ValueError as error:
        raise TodoValidationError(f"todo item {name} must be an ISO timestamp") from error
    if len(safe) > MAX_TODO_STAMP_CHARS:
        raise TodoValidationError(f"todo item {name} is capped at {MAX_TODO_STAMP_CHARS} characters")
    if state != "done":
        raise TodoValidationError(f"todo item {name} is recorded only on a done item")
    return safe


def bind_done_items(
    items: object,
    *,
    prior_items: object,
    calls: list[dict[str, Any]],
    fallback_start: str,
    now: str,
) -> object:
    """``items`` as the `omh_todo` tool writes them: bindings are OMH's, never the writer's.

    Every binding field the writer sent is dropped first -- a reference it
    can send is a reference it can copy from a result it was shown. Each item
    is then matched to the stored item with the same text (items sharing a
    text pair in order, `paired_with_prior`), and:

    * an item done before and done now keeps exactly what it had, including
      nothing: an item done before evidence existed stays unbound and counts
      as done, and re-sending a done item is the list standing still;
    * an open item keeps its window and any failed binding. Its window opens
      NOW when it is new, goes from pending to active, or leaves done;
    * an item newly done is judged over its own window -- from its stored
      ``window_start``, else the previous plan write (``fallback_start``), and
      from ``now`` when the item is new, so a renamed or re-declared item has
      an empty window. It takes the LATEST of ``calls`` inside that window
      that no other item holds, replacing a sticky binding, and each call is
      given to one item. Nothing inside keeps any sticky binding it had.

    ``calls`` are ``{"evidence", "at"}`` entries (`todo_evidence.observed_calls`).
    Pure and tolerant: anything that is not a dict item passes through for
    ``validate_todo_items`` to refuse with its own message.
    """
    if not isinstance(items, list):
        return items
    pairs, _ = paired_with_prior(items, prior_items)
    entries: list[tuple[Any, dict[str, Any] | None]] = [
        (
            {key: value for key, value in item.items() if key not in TODO_DONE_BINDING_KEYS}
            if isinstance(item, dict)
            else item,
            prior,
        )
        for item, prior in pairs
    ]
    held = {
        index: evidence_key(checked)
        for index, (entry, prior) in enumerate(entries)
        if isinstance(entry, dict)
        and prior is not None
        and (checked := valid_evidence(prior.get("evidence")))
    }
    bound: list[Any] = []
    for index, (entry, prior) in enumerate(entries):
        if not isinstance(entry, dict):
            bound.append(entry)
            continue
        carried = {key: prior[key] for key in TODO_DONE_BINDING_KEYS if prior and prior.get(key)}
        prior_state = prior.get("state") if prior else None
        state = entry.get("state", "pending")
        if state == "done" and prior_state == "done":
            entry.update(carried)
        elif state == "done":
            opened = carried.get("window_start") or (fallback_start if prior else now)
            entry.update(evidence=carried.get("evidence"), window_start=opened, done_at=now)
            others = {key for other, key in held.items() if other != index}
            call = _latest_call_after(calls, opened, others)
            if call is not None:
                entry["evidence"] = call
                held[index] = evidence_key(call)
            if not entry.get("evidence"):
                entry.pop("evidence", None)
        else:
            carried.pop("done_at", None)
            entry.update(carried)
            if prior is None or prior_state == "done" or (prior_state == "pending" and state == "active"):
                entry["window_start"] = now
        bound.append(entry)
    return bound


def paired_with_prior(
    items: list[Any], prior_items: object
) -> tuple[list[tuple[Any, dict[str, Any] | None]], list[dict[str, Any]]]:
    """Each item with the stored item it continues, and the stored items none continues.

    An item continues the stored item with the same text; items sharing a
    text pair in order, the first with the first. Anything that is not a
    dict item continues nothing.
    """
    by_text: dict[str, list[dict[str, Any]]] = {}
    for prior in prior_items if isinstance(prior_items, list) else []:
        if isinstance(prior, dict):
            by_text.setdefault(strip_control_characters(prior.get("text", "")), []).append(prior)
    pairs: list[tuple[Any, dict[str, Any] | None]] = []
    for item in items:
        queue = by_text.get(strip_control_characters(item.get("text", ""))) if isinstance(item, dict) else None
        pairs.append((item, queue.pop(0) if queue else None))
    return pairs, [prior for queue in by_text.values() for prior in queue]


def dropped_bindings(
    items: object, *, prior_items: object, prior_dropped: object, now: str
) -> list[dict[str, str]]:
    """The record's dropped bindings after a whole-list `set` of ``items``.

    The ones already recorded, then the binding of every stored item the new
    list does not continue, stamped ``now`` -- the stamp the same write opens
    a new item's window at, so a renamed item opens at its own drop.
    """
    kept = [entry for entry in prior_dropped if isinstance(entry, dict)] if isinstance(prior_dropped, list) else []
    if isinstance(items, list):
        for prior in paired_with_prior(items, prior_items)[1]:
            checked = valid_evidence(prior.get("evidence"))
            if checked is not None:
                kept.append({**checked, "dropped_at": now})
    return kept[-MAX_TODO_DROPPED_BINDINGS:]


def _validated_dropped_bindings(value: object) -> list[dict[str, str]]:
    """The plan's dropped bindings as they will be stored; an entry out of shape is refused."""
    if value is None or value == [] or value == ():
        return []
    if not isinstance(value, (list, tuple)) or len(value) > MAX_TODO_DROPPED_BINDINGS:
        raise TodoValidationError(
            f"todo dropped_bindings must be a list of at most {MAX_TODO_DROPPED_BINDINGS} entries"
        )
    validated: list[dict[str, str]] = []
    for entry in value:
        checked = valid_evidence(entry) if isinstance(entry, dict) else None
        stamp = _validated_stamp(entry.get("dropped_at"), "done", "dropped_at") if checked else ""
        if checked is None or not stamp:
            raise TodoValidationError("todo dropped_bindings entries must be {kind, ref, dropped_at}")
        validated.append({**checked, "dropped_at": stamp})
    return validated


def _latest_call_after(
    calls: list[dict[str, Any]], opened: str, held: set[str]
) -> dict[str, str] | None:
    """The latest call recorded after ``opened`` that nothing in ``held`` holds."""
    start = _stamp_epoch(opened)
    for call in reversed(calls):
        evidence = valid_evidence(call.get("evidence"))
        at = call.get("at")
        if evidence is None or evidence_key(evidence) in held or not isinstance(at, (int, float)):
            continue
        if start is not None and at <= start:
            continue
        return evidence
    return None


def _stamp_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = strict_fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def todo_timestamp() -> str:
    """The stamp format every record field here uses."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def todo_items_digest(items: object) -> str:
    """A digest of an item list, over every field an item declares.

    The same function answers for a writer's validated items and for the
    reader's projection of them, and the two are byte-equal for any record
    this module wrote: both build each entry from the same fields, in the same
    order, under the same bounds (the writer rejects an over-length field, the
    reader truncates at the identical cap). So a deferral written here is
    recognised by the reader until an item actually changes.

    Never raises, because every caller sits under a host that swallows
    exceptions. A malformed item list yields a digest that simply will not
    match the recorded one, and a deferral that fails to match lapses -- which
    is the safe direction: corruption makes the plan keep going, never stop.
    """
    if not isinstance(items, list):
        return ""
    canonical = [
        {key: entry[key] for key in _DIGESTED_ITEM_KEYS if key in entry}
        for entry in items
        if isinstance(entry, dict)
    ]
    # `default=str` is the last guard rather than a convenience: a hand-written
    # record can carry a value json cannot serialize, and raising here would
    # end the turn silently.
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:TODO_DEFERRED_DIGEST_CHARS]


def build_todo_record(
    title: object,
    items: object,
    *,
    source: str,
    session_ref: object = "",
    deferred_reason: object = "",
    template: object = "",
    plan_stage: object = "",
    dropped: object = (),
) -> dict[str, Any]:
    """Build the on-disk todo record.

    ``session_ref`` names the host session that declared this plan, when the
    writer knows it. It is additive-optional inside ``omh_todo/v1``: the key is
    written only when non-empty, so a CLI write is byte-identical to what it
    was before the field existed, and a reader that predates it still reads
    every field it knew.

    ``deferred_reason`` is additive-optional on the same terms, and carries a
    second key with it: ``deferred_items_digest``, the digest of the items this
    record is being written with. The two are always written together and
    never separately -- a reason without a digest would be a deferral nothing
    can lapse, which is the hand-cleared flag this field exists instead of.

    ``template`` names a phase template from `todo_templates` and is
    additive-optional on the same terms again. It does two things and they are
    the same thing seen from either end of the write: with no ``items`` it
    FILLS them, one pending item per phase in delivery order, so the shape of
    the plan comes from the template rather than from whatever the writer
    invents; with ``items`` it HOLDS them to that shape, refusing a list that
    drops a phase, renames one, reorders them, or leaves an item outside every
    phase. A writer that omits the field gets exactly the record this function
    built before the field existed, items and all.

    The coverage check runs after ``validate_todo_items`` and not before,
    because it reads the phase each item ended up with, which is the form the
    record and the HUD will carry. Checking the raw input would judge a phase
    the record never stores: ``'  I. Story  '`` would be refused as an unknown
    label for a phase the validator writes as ``'I. Story'``.

    ``plan_stage`` names where a PLANNING run stands with the person, and is
    additive-optional on the same terms once more. It is the only field here
    another surface REFUSES work on: `plan_stage_gate` escalates a file edit
    to the host's human-approval gate while a record says
    ``awaiting_acceptance``. So it is a closed vocabulary rather than free
    text, and an unrecognised value raises instead of being stored -- a stamp
    a reader cannot classify would make that gate silent on a plan that
    believes it is guarded, which is the worst of the three states.

    ``dropped`` is the plan's ``dropped_bindings`` (`dropped_bindings`),
    written only when non-empty, so a plan that never dropped a binding is
    byte-identical to one written before the field existed.
    """
    safe_title = strip_control_characters(title)
    if len(safe_title) > MAX_TODO_TITLE_CHARS:
        raise TodoValidationError(f"todo title is capped at {MAX_TODO_TITLE_CHARS} characters")
    safe_source = strip_control_characters(source)[:MAX_TODO_SOURCE_CHARS]
    safe_session_ref = strip_control_characters(session_ref)[:MAX_TODO_SESSION_REF_CHARS]
    safe_deferred_reason = _validated_deferred_reason(deferred_reason)
    safe_template = _validated_template(template)
    safe_plan_stage = _validated_plan_stage(plan_stage)
    safe_dropped = _validated_dropped_bindings(dropped)
    if safe_template and items in (None, []):
        items = template_items(safe_template)
    # The cap refusal, answered here rather than in `validate_todo_items`,
    # because only this frame knows a template is involved. The generic
    # sentence is the whole of what an unstamped plan sees and is left
    # untouched; a stamped one gets the arithmetic it cannot do for itself.
    if safe_template and isinstance(items, list) and len(items) > MAX_TODO_ITEMS:
        raise TodoValidationError(_template_cap_error(safe_template, len(items)))
    validated_items = validate_todo_items(items)
    if safe_template and (error := template_coverage_error(safe_template, validated_items)):
        raise TodoValidationError(error)
    record: dict[str, Any] = {
        "schema_version": TODO_SCHEMA_VERSION,
        "title": safe_title,
        "source": safe_source,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "items": validated_items,
        "claim_boundary": TODO_CLAIM_BOUNDARY,
    }
    if safe_session_ref:
        record["session_ref"] = safe_session_ref
    if safe_deferred_reason:
        record["deferred_reason"] = safe_deferred_reason
        record["deferred_items_digest"] = todo_items_digest(validated_items)
    if safe_template:
        record["template"] = safe_template
    if safe_plan_stage:
        record["plan_stage"] = safe_plan_stage
    if safe_dropped:
        record["dropped_bindings"] = safe_dropped
    return record


def _template_cap_error(template: str, declared_items: int) -> str:
    """What a stamped plan is told when it overruns ``MAX_TODO_ITEMS``.

    The generic message is true and unactionable in the same breath: a writer
    that sent ten template phases plus eleven items of its own is told the
    cap and given no way to learn that the template it asked for is holding
    half of it. Its two available moves from there are to retry the identical
    payload or to drop the template, and neither is the one that works. So
    the sentence keeps its opening -- an unstamped plan reads exactly the
    string it always read -- and appends the arithmetic only this frame can
    do: how much the template spends, what is left, and what arrived.

    It also says nothing was written, because a cap that truncates and a cap
    that refuses call for opposite next moves and a person assumes the first.
    Nothing partial lands: this raises before `write_todo`, so the record on
    disk is whatever it was.
    """
    holds = len(template_phase_labels(template))
    return (
        f"todo items are capped at {MAX_TODO_ITEMS}; template {template!r} declares "
        f"{holds} of them, leaving {max(0, MAX_TODO_ITEMS - holds)} for items of your "
        f"own, and this plan has {declared_items}. Nothing was written."
    )


def _validated_plan_stage(plan_stage: object) -> str:
    """The planning stage as it will be stored, or ``""``.

    The same shape as ``_validated_template`` below, for the same reason and
    with one difference worth naming. Same reason: a closed vocabulary, so a
    value no reader can classify raises here rather than being stored, and
    absence is spelled by omitting the argument.

    The difference is which way the silence falls. An unknown template name
    hides a coverage rule that WOULD have refused; an unknown plan stage hides
    a gate that would have asked a person. Both are silent failures, but this
    one is silent on the surface that stops work, so a writer that sends
    ``"unaccepted"`` or ``"pending"`` -- near misses a model reaches for --
    must be told rather than quietly left unguarded.

    Membership is tested BEFORE any length bound, and that ordering is the
    whole of the difference between a refusal and a silent arming. Bounding
    first -- the shape every other field here uses, because every other field
    STORES what the caller sent -- truncates ``"awaiting_acceptance_later"``
    to exactly the longest vocabulary member and then finds it in the set, so
    the refusal above would be a promise this function did not keep for any
    string that merely starts the right way. Nothing needs the bound: only a
    vocabulary member is ever returned, so what is stored is bounded by the
    vocabulary itself.
    """
    if plan_stage is None or plan_stage == "":
        return ""
    if not isinstance(plan_stage, str):
        raise TodoValidationError("todo plan_stage must be a string")
    safe = strip_control_characters(plan_stage)
    if safe not in TODO_PLAN_STAGES:
        known = ", ".join(repr(stage) for stage in TODO_PLAN_STAGES)
        raise TodoValidationError(f"todo plan_stage must be one of: {known}")
    return safe


def _validated_template(template: object) -> str:
    """The template name as it will be stored, or ``""``.

    A closed vocabulary, so an unrecognised name raises instead of being
    stored: a stamp nothing can project is worse than no stamp, because the
    coverage rule the stamp exists to impose would then be silently absent
    from a record that claims to have one. The message names the templates
    that do exist, since the writer is a model reading a refusal rather than
    a person reading this file.

    A non-string is rejected rather than coerced, the call
    ``_validated_deferred_reason`` below makes for the same reason: a number
    is not a template name in any language. The parallel stops there: that
    function treats whitespace as absence, and this one strips it and then
    fails the membership test, so a blank string raises. Deliberate --
    absence means "no template" and is spelled by omitting the argument,
    while a writer that sent something got it wrong and should be told.
    """
    if template is None or template == "":
        return ""
    if not isinstance(template, str):
        raise TodoValidationError("todo template must be a string")
    safe = strip_control_characters(template)[:MAX_TODO_TEMPLATE_CHARS]
    if safe not in TODO_TEMPLATES:
        known = ", ".join(repr(name) for name in sorted(TODO_TEMPLATES))
        raise TodoValidationError(f"todo template must be one of: {known}")
    return safe


def _validated_deferred_reason(deferred_reason: object) -> str:
    """The plan-level deferral reason as it will be stored, or ``""``.

    A non-string is rejected rather than coerced. ``strip_control_characters``
    would turn ``7`` into the truthy string ``"7"``, and a number is not a
    declaration in any language -- the same call the item-level reason makes on
    the way back out. Whitespace is not a declaration either: it strips to
    empty and the record is written without the field, so a blank reason is
    absence rather than a deferral nobody can read.

    Over-length raises instead of truncating, matching ``blocked_reason``: the
    reasons are the same shape of free text, and a reason silently cut at its
    cap can read as something the writer did not say. The tool surfaces the
    error so the writer can shorten it.
    """
    if deferred_reason is None or deferred_reason == "":
        return ""
    if not isinstance(deferred_reason, str):
        raise TodoValidationError("todo deferred_reason must be a string")
    safe = strip_control_characters(deferred_reason)
    if len(safe) > MAX_TODO_DEFERRED_REASON_CHARS:
        raise TodoValidationError(
            f"todo deferred_reason is capped at {MAX_TODO_DEFERRED_REASON_CHARS} characters"
        )
    return safe


def todo_session_key(session_ref: object) -> str:
    """The filename stem a session's todo record lives under.

    Host session ids are filesystem-safe today (``20260831_153632_11fc69``),
    but a gateway thread id may carry any character, so the key is a bounded
    sanitized slug for legibility plus a short digest of the exact reference
    for uniqueness. The reference is bounded to the host-observation session
    limit before either is taken, the same bound the record's stamp has, so
    the key and the stamp always describe the same string. Empty when the
    reference is empty.
    """
    reference = strip_control_characters(session_ref)[:MAX_TODO_SESSION_REF_CHARS]
    if not reference:
        return ""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", reference).strip("_-")[:48]
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]
    return f"{slug}-{digest}" if slug else digest


def todo_path(omh_home: Path, session_ref: object = "") -> Path:
    """Where the todo record for ``session_ref`` lives; the home-wide file when empty."""
    key = todo_session_key(session_ref)
    if not key:
        return omh_home / "runtime" / TODO_FILENAME
    return omh_home / "runtime" / TODO_SESSION_DIRNAME / f"{key}.json"


def todo_session_dir(omh_home: Path) -> Path:
    return omh_home / "runtime" / TODO_SESSION_DIRNAME


def write_todo(omh_home: Path, record: dict[str, Any]) -> Path:
    """Write ``record`` to the file its ``session_ref`` selects.

    Taken under the record's lock, and that is not about this write on its
    own: ``os.replace`` already makes a whole-record write atomic against a
    reader. It is about ``advance_todo_item``, whose read-modify-write is not
    atomic against anything, and which can only be serialised against a
    whole-list write if both go through the same lock.
    """
    session_ref = str(record.get("session_ref", "") or "")
    destination = todo_path(omh_home, session_ref)
    _reject_symlink_ancestry(destination, root=omh_home)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise TodoStoreError(f"todo destination is not writable: {error}") from error
    # Post-mkdir TOCTOU recheck of the whole ancestry: the walk above ran
    # before the session directory existed, so a link planted in between
    # would otherwise be followed by the write.
    _reject_symlink_ancestry(destination, root=omh_home)
    with _todo_record_lock(destination, root=omh_home):
        _replace_todo_record(destination)(record)
    if session_ref:
        _prune_session_records(omh_home, keep=destination)
    return destination


def _replace_todo_record(destination: Path):
    """A writer bound to one destination, for use inside the record's lock.

    Returned as a closure rather than taking the path twice because both
    callers have already resolved and checked the destination, and a second
    path argument at the call site is a second chance for the lock and the
    write to describe different files.
    """

    def write(record: dict[str, Any]) -> None:
        temporary = destination.with_name(
            f".{destination.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            os.replace(temporary, destination)
        except OSError as error:
            raise TodoStoreError(f"todo destination is not writable: {error}") from error
        finally:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()

    return write


@contextlib.contextmanager
def _todo_record_lock(destination: Path, *, root: Path) -> Iterator[None]:
    """Serialize every write to one todo record, across processes.

    A lock rather than a compare-and-set on ``updated_at`` because the window
    a compare-and-set leaves open is the whole of the failure: the advance
    path reads the record, validates a list, rebuilds it and writes, and a
    stamp checked before that last step is checked in a different instant
    than the ``os.replace`` that acts on it. Under the lock the read and the
    write are one step, so a whole-list `set` landing in the middle is not
    possible rather than unlikely.

    The lock itself is `awareness_delivery`'s, not one of this module's own.
    That module is where the bundle keeps its two-backend implementation, for
    the reason recorded there -- vendored into the user's Hermes install, so
    it cannot share `local_store.file_lock` -- and three other modules here
    already take it. What this adds is the deadline and the vocabulary: a
    timeout is `TodoContendedError`, so the caller can tell a busy record
    from an invalid payload, and never a silent unlocked pass.

    A host with neither backend yields `none` from the shared helper and
    takes no lock. This does not refuse in that case, which is the behaviour
    every writer here had before the lock existed; refusing would make a
    platform without `fcntl` or `msvcrt` unable to keep a plan at all.
    """
    # Derived the same way the shared helper derives it, and checked before
    # the helper creates it. `_lock_file_for` is the single spelling of that
    # derivation, and `test_the_shared_lock_file_is_the_one_the_prune_knows`
    # pins it against the file the helper actually writes.
    _reject_symlink_ancestry(_lock_file_for(destination), root=root)
    # `held` is what keeps the two handlers below honest. They sit outside the
    # `with`, so they see the caller's body as well as the acquisition, and an
    # `OSError` from the body relabelled as "the destination is not writable"
    # would be this module deciding what someone else's failure was --
    # `TimeoutError` is an `OSError` too, so the pair is easy to get wrong.
    # Once the lock is held, anything raised is the caller's and leaves
    # unchanged.
    held = False
    try:
        with _awareness_delivery_lock(destination, timeout_seconds=_LOCK_TIMEOUT_SECONDS):
            held = True
            yield
    except TimeoutError as error:
        if held:
            raise
        raise TodoContendedError(
            f"todo record is held by another writer after "
            f"{_LOCK_TIMEOUT_SECONDS:g}s and was not written: {destination}. "
            "Nothing changed; send the same call again."
        ) from error
    except OSError as error:
        if held:
            raise
        raise TodoStoreError(f"todo destination is not writable: {error}") from error


def _lock_file_for(destination: Path) -> Path:
    """The lock file `_awareness_delivery_lock` will create beside ``destination``."""
    return destination.with_name(f".{destination.name}.lock")


def advance_todo_item(
    omh_home: Path,
    *,
    item: object,
    item_text: object,
    state: object,
    source: str,
    session_ref: object = "",
    blocked_reason: object = "",
    deferred_reason: object = "",
    observed_calls: Callable[[str, set[str]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Change ONE item's state on an existing record, and return the new record.

    The same write as a whole-list `set`, reached with one item's worth of
    arguments instead of the whole list. That equivalence is the contract and
    it is enforced structurally rather than by agreement: the new list is the
    stored list with one entry's ``state`` and ``blocked_reason`` replaced,
    and it then goes through ``build_todo_record`` -- the same title, source,
    session, deferral and template handling, the same ``validate_todo_items``,
    the same stamp. There is no second validator here and no second schema; a
    record this produces is byte-equal to the one `set` produces for the same
    plan. ``source`` is the one field that is not the caller's: the stored
    record's declaring tool is kept, and ``source`` names the writer only for
    a record that names none. On a record `todo_list` holds, the item's
    ``state`` is not the caller's either: the advance records its reasons and
    keeps the state the last `todo_list` write set (`native_todo`), a
    cancelled item's own reason included when the call sends none.

    The template name is read off the stored record and sent back through, so
    a single-item write neither drops it nor escapes it: the phase coverage
    the template imposes is re-checked on the advanced list, exactly as it
    would be on a whole-list `set`. Advancing an item cannot move a
    phase, so this passes for any record this module wrote; a hand-edited
    record that no longer covers its template refuses here, naming the phase,
    and `set` is how it is re-declared.

    A record naming a template this build does not have is the one refusal
    on this path a caller could not act on, so it is relabelled rather than
    passed through. The builder's message tells a writer to send a different
    `template`, and `action=advance` has no such argument -- the name came
    off the record, not off the call -- so a model reading that wording
    would look for an argument it never sent. It is also permanent for that
    record: only `set` clears a stored name, and the replacement says so.
    Reachable today from a hand edit, or from a bundle rolled back under a
    record a newer generation stamped.

    ``item`` is 1-based, the way the checklist reads, and it is guarded rather
    than trusted. ``item_text`` must be a prefix of the text already stored at
    that position, so a reference computed against a list that has since been
    re-set refuses instead of ticking whatever now sits at that index. The
    guard is required for that reason: an unguarded index is exactly the
    silent mis-write this action would otherwise introduce, and the whole
    point of a single-item write is that the caller no longer re-reads the
    list on every advance.

    ``blocked_reason`` replaces the item's recorded reason and omitting it
    clears one, which is what `set` does with a field left out of an item.
    Making it sticky instead would create a record state reachable by `set`
    and not by this, and the equivalence above is what the action is for.
    The one exception is the reason OMH writes for a cancelled item on a plan
    `todo_list` holds (above).

    The whole read-modify-write runs inside the record's lock, so a `set` from
    another turn or another process cannot land between the read and the
    write and be overwritten by a list this call read before it.

    ``observed_calls`` is how the tool path binds. Called inside the lock with
    the start of the item's window -- its own ``window_start``, else the
    stored ``updated_at`` -- and the evidence keys the OTHER items hold, it
    returns the calls recorded since, oldest first. The store reads no
    session records itself; the CLI shares this module, passes none, and its
    writes bind nothing. With a reader:

    * done: the latest call in the window binds, replacing a sticky binding;
      with none, an item newly done is stamped ``done_at`` over its window
      and keeps any failed binding it carried, and an item already done
      changes nothing -- a no-op re-advance is not a write, so it neither
      restamps the plan nor reads as progress to `nudge_budget`;
    * pending to active, or out of done: the item's window opens now, and a
      binding it had is kept, since a failure is sticky.

    Leaving done always drops ``done_at``. A call whose record is identical
    to the stored one apart from its stamp is not written at all.
    """
    destination = todo_path(omh_home, session_ref)
    _reject_symlink_ancestry(destination, root=omh_home)
    # Asked before the lock, because taking one means creating a file in a
    # directory that may not exist, and the OSError that produces would
    # report a home that is not writable about a home that is merely empty.
    # Nothing is lost to the gap: a record appearing here is one this call
    # never read, which is the same answer it would give a moment earlier.
    if not destination.parent.is_dir():
        raise TodoValidationError(
            "no todo record for this session; declare one with action=set"
        )
    with _todo_record_lock(destination, root=omh_home):
        record = _read_todo_record(destination)
        if record is None:
            raise TodoValidationError(
                "no todo record for this session; declare one with action=set"
            )
        stored = record.get("items")
        if not isinstance(stored, list) or not stored:
            raise TodoValidationError(
                "the stored todo record has no items; declare one with action=set"
            )
        # A finished plan still takes a done write: a done mark with no
        # command behind it leaves the item open for the stop criterion
        # (`todo_evidence`), and marking it done again after the command ran
        # is how it closes. Every other move on a finished plan is refused.
        if state != "done" and all(
            isinstance(entry, dict) and entry.get("state") == "done" for entry in stored
        ):
            raise TodoValidationError(
                "this plan is finished; declare a new one with action=set"
            )
        position = _validated_item_reference(item, len(stored))
        current = stored[position]
        if not isinstance(current, dict):
            raise TodoValidationError(f"todo item {position + 1} is not an object")
        _check_item_guard(item_text, current, position)
        if state not in TODO_ITEM_STATES:
            raise TodoValidationError(
                f"todo item state must be one of {', '.join(TODO_ITEM_STATES)}"
            )
        # On a plan Hermes' `todo_list` holds (`native_todo`), item states are
        # todo_list's: an advance records its reasons and keeps the state the
        # last todo_list write set. Otherwise the next todo_list write -- which
        # still shows the native status -- would read the advance's state as a
        # move and drop the reason it carried.
        native_held = record.get("source") == NATIVE_TODO_TOOL
        if native_held and current.get("state") in TODO_ITEM_STATES:
            state = current["state"]
        updated = dict(current)
        updated["state"] = state
        safe_reason = strip_control_characters(blocked_reason)
        if safe_reason:
            updated["blocked_reason"] = blocked_reason
        elif not (native_held and current.get("blocked_reason") == NATIVE_CANCELLED_REASON):
            # `cancelled` is a todo_list status the record spells as this
            # reason, so an advance that sends none does not turn a cancelled
            # item into a completed one.
            updated.pop("blocked_reason", None)
        prior_state = current.get("state")
        if state != "done":
            updated.pop("done_at", None)
            if observed_calls is not None and (
                prior_state == "done" or (prior_state == "pending" and state == "active")
            ):
                updated["window_start"] = todo_timestamp()
        elif observed_calls is not None:
            stamp = record.get("updated_at", "")
            opened = current.get("window_start") or (stamp if isinstance(stamp, str) else "")
            # The OTHER items' references only. This item's own is left
            # rebindable on purpose: were it held, a re-advance after its bound
            # failure would skip that failure and bind an older passing call.
            held = {
                evidence_key(checked)
                for index, entry in enumerate(stored)
                if index != position
                and isinstance(entry, dict)
                and (checked := valid_evidence(entry.get("evidence")))
            }
            calls = observed_calls(opened, held)
            # The latest call being the one already bound is nothing new: a
            # re-advance over it must stay a no-op, or it would restamp
            # `done_at` and buy a turn-end nudge with no work behind it.
            if calls and calls[-1]["evidence"] != current.get("evidence"):
                updated.update(
                    evidence=calls[-1]["evidence"], done_at=todo_timestamp(), window_start=opened
                )
            elif prior_state != "done":
                updated.update(done_at=todo_timestamp(), window_start=opened)
        items = list(stored)
        items[position] = updated
        stored_template = record.get("template", "")
        # Read off the record and sent back through, exactly like the template
        # name above it and for a reason of its own: ticking a planning stage
        # off is the plan advancing, and a stamp that a completed stage
        # cleared would retire the gate on the very call that proves the run
        # is still planning. Only `set` -- a re-declaration of the whole
        # checklist -- changes or drops it.
        #
        # Carried forward only when the stored value is one this build knows,
        # where the template handling instead relabels a refusal. The two
        # differ because an unknown value costs different things: an unknown
        # template hides a coverage rule that would have refused, so the write
        # must stop and say so, while an unknown plan stage is ALREADY
        # unguarded -- `plan_stage_gate` reads two literals and nothing else --
        # so raising here would refuse an advance over a field the caller
        # never sent, to protect a gate that was silent either way. Dropping
        # it makes the record say what was already true.
        stored_plan_stage = record.get("plan_stage", "")
        if stored_plan_stage not in TODO_PLAN_STAGES:
            stored_plan_stage = ""
        # The declaring tool stays, for the reason the stage does: an advance
        # annotates the plan, it does not re-declare it. That is what keeps a
        # plan Hermes' `todo_list` holds (`native_todo`) read as todo_list's
        # after `omh_todo` records a reason on one of its items, so the
        # surfaces that leave its items to Hermes' own panel keep doing so.
        # ``source`` names the writer only for a record that names none.
        stored_source = record.get("source", "")
        try:
            advanced = build_todo_record(
                record.get("title", ""),
                items,
                source=stored_source if isinstance(stored_source, str) and stored_source else source,
                session_ref=session_ref,
                deferred_reason=deferred_reason,
                template=stored_template,
                plan_stage=stored_plan_stage,
                # An advance moves one item and drops none, so it carries the
                # plan's dropped bindings exactly as they were.
                dropped=record.get("dropped_bindings", ()),
            )
        except TodoValidationError as error:
            raise _advance_template_error(stored_template, error) from error
        if _same_apart_from_stamp(advanced, record):
            return record
        _replace_todo_record(destination)(advanced)
    return advanced


def _same_apart_from_stamp(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """Whether a write would change nothing but ``updated_at``."""
    return {key: value for key, value in new.items() if key != "updated_at"} == {
        key: value for key, value in old.items() if key != "updated_at"
    }


def _advance_template_error(
    stored_template: object, error: TodoValidationError
) -> TodoValidationError:
    """Re-label the one advance refusal whose remedy the builder cannot name.

    Every other refusal on this path ends with what to do next -- "declare
    one with action=set", "read the plan with action=show first". The
    builder's unknown-template message ends with "must be one of: ..." and
    means "send a different `template`", which is advice about an argument
    `action=advance` does not have. Only the unknown-name case is relabelled:
    a coverage refusal already names its phase and is actionable as written,
    so it is returned untouched.
    """
    # Only a record that NAMES a template this build cannot resolve. An
    # unstamped record is the common case and every refusal on it is the
    # builder's own -- an over-length reason, an item text past the cap --
    # so relabelling those would answer a question about item fields with a
    # sentence about templates.
    # `isinstance` before the lookup, not after: a hand-edited record can
    # carry an unhashable value there, and `{} in TODO_TEMPLATES` raises
    # TypeError -- inside an exception handler, which would replace a
    # refusal the caller can read with a crash it cannot.
    if not stored_template or (
        isinstance(stored_template, str) and stored_template in TODO_TEMPLATES
    ):
        return error
    known = ", ".join(repr(name) for name in sorted(TODO_TEMPLATES))
    shown = strip_control_characters(stored_template)[:MAX_TODO_TEMPLATE_CHARS]
    return TodoValidationError(
        f"this plan names a template this build does not know ({shown!r}); "
        f"re-declare it with action=set, using one of: {known}"
    )


def _validated_item_reference(item: object, count: int) -> int:
    """The 0-based position ``item`` names, or a refusal that names the field.

    ``bool`` is rejected before ``int`` because ``True`` is ``1`` and would
    otherwise tick the first item; the same call ``validate_todo_items``
    makes about ``depth``.
    """
    if isinstance(item, bool) or not isinstance(item, int):
        raise TodoValidationError(
            f"todo item must be an integer from 1 to {count}; the plan has {count} items"
        )
    if not 1 <= item <= count:
        raise TodoValidationError(
            f"todo item {item} is out of range; the plan has {count} items"
        )
    return item - 1


def _check_item_guard(item_text: object, current: dict[str, Any], position: int) -> None:
    """Refuse unless ``item_text`` still describes the item at ``position``.

    A compare-and-set, written as a text prefix because the record has no
    item id and does not need one for anything else: adding one would change
    the on-disk schema, the digest the deferral lapses on, and every surface
    that projects an item, to carry a handle whose only reader would be this
    function.
    """
    guard = strip_control_characters(item_text)
    if not guard:
        raise TodoValidationError(
            "todo item_text is required; it guards the item reference against a stale index"
        )
    stored_text = strip_control_characters(current.get("text", ""))
    if not stored_text.startswith(guard):
        raise TodoValidationError(
            f"todo item_text does not match item {position + 1} "
            f"({stored_text[:60]!r}); read the plan with action=show first"
        )


def _read_todo_record(path: Path) -> dict[str, Any] | None:
    """The record on disk, read without following links, or ``None``.

    The RAW record, not the HUD projection: the projection truncates for
    display and drops what a checklist row cannot show, so rebuilding a write
    from it would quietly rewrite the plan. The bounds are the ones
    ``_stamped_session_ref`` already applies to the same file.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_TODO_RECORD_BYTES:
            return None
        record = json.loads(os.read(descriptor, MAX_TODO_RECORD_BYTES).decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        os.close(descriptor)
    return record if isinstance(record, dict) else None


def read_todo_record(omh_home: Path, session_ref: object = "") -> dict[str, Any] | None:
    """The raw record ``session_ref`` selects, or ``None``; see `_read_todo_record`."""
    return _read_todo_record(todo_path(omh_home, session_ref))


def clear_todo(omh_home: Path, session_ref: object = "") -> bool:
    """Remove the todo record ``session_ref`` selects.

    A session clearing its plan also removes the home-wide record when that
    record is one the session renders: unstamped (an operator's
    `omh runtime todo set`, which the reader shows to the live session), or
    stamped by this very session (the layout that predates per-session
    files). It never touches another session's stamped record, so a clear
    always answers for what the caller was looking at and nothing else.
    """
    reference = strip_control_characters(session_ref)[:MAX_TODO_SESSION_REF_CHARS]
    removed = remove_todo_file(omh_home, todo_path(omh_home, reference))
    if reference:
        legacy = todo_path(omh_home)
        if _stamped_session_ref(legacy) in {"", reference}:
            removed = remove_todo_file(omh_home, legacy) or removed
    return removed


def remove_todo_file(omh_home: Path, destination: Path) -> bool:
    _reject_symlink_ancestry(destination, root=omh_home)
    if not destination.is_file() or destination.is_symlink():
        return False
    try:
        destination.unlink()
    except OSError as error:
        raise TodoStoreError(f"todo destination is not removable: {error}") from error
    return True


def _stamped_session_ref(path: Path) -> str:
    """The ``session_ref`` a record on disk carries, read without following links."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return ""
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_TODO_RECORD_BYTES:
            return ""
        record = json.loads(os.read(descriptor, MAX_TODO_RECORD_BYTES).decode("utf-8"))
    except (OSError, ValueError):
        return ""
    finally:
        os.close(descriptor)
    if not isinstance(record, dict):
        return ""
    return strip_control_characters(record.get("session_ref", ""))[:MAX_TODO_SESSION_REF_CHARS]


def _prune_session_records(omh_home: Path, *, keep: Path) -> None:
    """Drop per-session records the reader would already treat as stale.

    Best effort: a prune failure never fails the write that triggered it.
    Only regular files this module names -- session records, its own
    temporary files, and the lock files beside them -- directly inside the
    session directory are considered, only once they are older than the stale
    bound, and the record just written is always kept.

    A lock file has one extra condition, because removing one that is still
    coordinating writers would let two of them into the record at once: it
    goes only when the record it guards is already gone. Past the stale bound
    with no record beside it, nothing can be mid-write on it -- a writer
    creating a record holds a lock that is seconds old, not a day.
    """
    directory = todo_session_dir(omh_home)
    now = datetime.now(timezone.utc).timestamp()
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return
    for entry in entries:
        if entry.name == keep.name:
            continue
        if _LOCK_NAME.fullmatch(entry.name):
            if (directory / entry.name[1:-len(".lock")]).exists():
                continue
        elif not (
            _SESSION_RECORD_NAME.fullmatch(entry.name) or _TEMPORARY_NAME.fullmatch(entry.name)
        ):
            continue
        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            if now - entry.stat(follow_symlinks=False).st_mtime <= TODO_STALE_SECONDS:
                continue
            os.unlink(entry.path)
        except OSError:
            continue


def _reject_symlink_ancestry(path: Path, *, root: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise TodoStoreError(f"refusing symlinked todo path: {current}")
        if current == root or current == current.parent:
            return
        current = current.parent
