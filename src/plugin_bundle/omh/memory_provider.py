"""OMH as a Hermes memory provider: the lane that runs without being called.

Everything OMH knew about memory used to require someone to ask. `omh memory
status` had the comparison, the `omh_memory` tool had it after PR #672, and both
waited for a question. Meanwhile Hermes' own memory kept being written by
``agent/background_review.py``, which forks after each turn and decides for
itself what to save -- with nothing telling it what OMH already holds, what is
duplicated, or how little room is left.

Hermes exposes the seam for this and OMH was not standing in it.
``plugins/memory/__init__.py`` scans ``$HERMES_HOME/plugins/<name>/`` as well as
its own bundled directory, which is where the OMH bundle already installs, and
``agent/memory_provider.py`` defines the lifecycle. Four of its hooks are the
ones that matter here:

- ``prefetch``       -- runs before every API call, so recall arrives unasked
- ``on_pre_compress``-- runs before compression discards messages
- ``on_memory_write``-- runs when Hermes writes its own memory, giving provenance
- ``on_session_end`` -- runs at a session boundary, where consolidation belongs

No tool schemas are exposed. ``memory_provider.py`` gives tool-schema bloat as
the reason only one external provider may run at a time, and OMH already
registers ten tools through the plugin path; the on-demand block read belongs on
``omh_memory``, which exists, rather than on a second registration path that
Hermes gates behind toolset config.

OMH still makes no model call and still cannot write Hermes memory. This
provider reads OMH's own store, renders it, and records what it saw.
"""

from __future__ import annotations

from . import runtime_paths

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Present only inside the Hermes process.
    from agent.memory_provider import MemoryProvider as _MemoryProviderBase
    from agent.memory_provider import RecallStatus as RecallStatus
except ModuleNotFoundError as exc:  # Standalone has no Hermes dependency.
    if exc.name not in {"agent", "agent.memory_provider"}:
        raise
    from dataclasses import dataclass

    _MemoryProviderBase = object

    @dataclass(frozen=True)
    class RecallStatus:  # type: ignore[no-redef]
        """Field-for-field the Hermes contract, so the repo's tests see what Hermes sees."""

        provider_label: str
        count: int
        glyph: str = "🧠"


from .hermes_memory import count_record_expiry, read_hermes_memory
from .memory_block_replay import MemoryBlockSelection
from .memory_blocks import (
    DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
    MemoryBlock,
    REFERENCE_TIER,
    SYSTEM_TIER,
    read_memory_blocks,
    render_block_index,
    render_memory_blocks,
    render_memory_blocks_counted,
    select_memory_blocks,
)
from .memory_dreaming import (
    build_consolidation_handoff,
    clear_after_consolidation,
    consolidation_reasons,
    read_dreaming_state,
    read_latest_consolidation,
    record_compaction,
    record_consolidation_observed,
    record_memory_write,
    record_turn,
    write_dreaming_state,
)
from .memory_eviction import build_eviction_plan
from .memory_principals import parse_principal_context
from .project_identity import ProjectIdentityResolution, project_identity_root, resolve_project_identity
from .memory_prefetch_receipt import (
    build_prefetch_receipt,
    mark_prefetch_receipt_returned,
    prefetch_receipt_path,
)
from .memory_records import (
    prefetch_scope_allowlist,
    prepare_prefetch_records,
    read_record_store_snapshot,
)

PROVIDER_NAME = "omh"
# What Hermes prints in front of "recalled N memories" on every surface it
# speaks through -- CLI, TUI, and each gateway platform -- when a prefetch
# actually put OMH memory into the turn.
PROVIDER_LABEL = "OMH"
# The brief rides in the prefetch pack, bounded so a long reason list or eviction
# plan cannot crowd out the memory it is asking the model to keep.
CONSOLIDATION_RENDER_BUDGET_CHARS = 1600
CONSOLIDATION_MAX_ITEMS = 6
WRITE_JOURNAL_SCHEMA_VERSION = "omh_memory_write_journal_entry/v1"
JOURNAL_LIMIT = 32

# Hermes states that only a primary agent should write; a cron or subagent
# context replaying its own system prompt would otherwise move the counters that
# decide when consolidation is due.
_WRITING_CONTEXTS = frozenset({"", "primary"})

# Moments after which this session gets no further turn. The turn interval
# assumes a later turn will come; at these it will not, so a single
# unconsolidated turn is enough. `session_start_recovery` belongs here because
# it is settling the account of a session that already ended without one.
_SESSION_ENDING_TRIGGERS = frozenset({"session_end", "shutdown", "session_start_recovery"})


class OmhMemoryProvider(_MemoryProviderBase):
    """Deterministic, file-backed recall for Hermes. No model call, no network."""

    def __init__(self, omh_home: str | Path | None = None, *, hermes_home: str | Path | None = None) -> None:
        # `hermes_home` is also settable here, not only through `initialize`,
        # so a caller that wants one reading -- `omh memory dream --evaluate`
        # asking whether consolidation is due -- can get a configured provider
        # without entering the session lifecycle. `initialize` is a session
        # start: it renders the pack and settles the previous session's
        # unconsolidated turns. A question is not a session start.
        self._omh_home, self._hermes_home = runtime_paths.resolve_homes(omh_home, hermes_home)
        if hermes_home is None and runtime_paths._host() is None:
            # Standalone callers may supply the native comparison root at first
            # initialize; no Hermes store is read before that explicit binding.
            self._hermes_home = None
        self._session_id = ""
        self._writes_enabled = True
        self._principal_context: dict[str, object] | None = None
        self._profile_ref = ""
        self._turn_ref = ""
        self._shared_surface = False
        # Reviewed records live in the project's own `.omh` when a session runs
        # inside a repository; `initialize` resolves it from the working
        # directory. The user home is always read as well.
        self._project_home: Path | None = None
        self._project_cwd: str | None = None
        self._project_resolution = ProjectIdentityResolution()
        # prefetch() is called before every API call and the base class asks for
        # it to be fast, so the pack is rendered off the hot path and served
        # from here. `_query` is what the pack was ranked for; `_pack_count`
        # is how many memories it carries in full.
        self._pack = ""
        self._query = ""
        self._pack_count = 0
        # True when blocks, a reference index, or records are in the pack. A
        # consolidation brief alone is a request, not recalled memory.
        self._pack_has_memory = False
        # What the LAST prefetch handed Hermes, for the recall indicator: the
        # base class asks that a stale prior count never be reported.
        self._served_pack = ""
        self._served_count = 0
        self._served_has_memory = False
        # The record-bound receipt for the rendered pack, and the one for the
        # pack the LAST prefetch actually handed back. A receipt is prepared
        # with the pack and becomes `returned_to_host` only when prefetch runs;
        # it never claims the host delivered it or a model used it.
        self._prepared_receipt: dict[str, Any] | None = None
        self._served_receipt: dict[str, Any] | None = None
        # Hermes hands a status callback to providers on the CLI surface only;
        # gateway platforms travel a different path and get the brief through
        # the pack instead. None means "say nothing here", never "fail".
        self._status_callback = None

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    # -- Core lifecycle -----------------------------------------------------

    def is_available(self) -> bool:
        """True when there is an OMH home to read. Never touches the network."""
        try:
            return self._omh_home.is_dir()
        except OSError:
            return False

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home is not None:
            supplied_home = runtime_paths.expand_path(hermes_home)
            if self._hermes_home is not None and supplied_home != self._hermes_home:
                raise runtime_paths.RuntimeBindingError("OMH provider cannot be initialized for another profile")
            self._hermes_home = supplied_home
        self._query = ""
        self._pack, self._pack_count, self._pack_has_memory = "", 0, False
        self._served_pack, self._served_count, self._served_has_memory = "", 0, False
        self._prepared_receipt, self._served_receipt = None, None
        self._session_id = str(session_id or "")
        self._writes_enabled = str(kwargs.get("agent_context", "") or "") in _WRITING_CONTEXTS
        platform = str(kwargs.get("platform", "") or "")
        self._shared_surface = bool(kwargs.get("shared_surface", bool(platform and platform != "cli")))
        self._principal_context = parse_principal_context(
            kwargs.get("principal_context"),
            expected_session=self._session_id,
        )
        self._profile_ref = str(self._principal_context.get("profile_ref", "")) if self._principal_context is not None else str(kwargs.get("active_profile", "") or "")
        if self._shared_surface:
            self._principal_context = None
        self._project_cwd = str(kwargs.get("cwd") or Path.cwd())
        self._project_home = _project_omh_home(self._project_cwd)
        self._project_resolution = resolve_project_identity(self._project_cwd)
        callback = kwargs.get("status_callback")
        self._status_callback = callback if callable(callback) else None
        self._pack = self.render_pack()
        # A session that died rather than ended -- a killed process, a closed
        # laptop, a lost gateway -- never reaches on_session_end, so nothing
        # would ever act on the turns it accumulated. The counters survived on
        # disk; this is where they are honoured.
        self._evaluate_if_due("session_start_recovery")

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """None. The on-demand block read lives on the existing `omh_memory` tool."""
        return []

    def prefetch(
        self,
        query: str = "",
        *,
        session_id: str = "",
        principal_context: dict[str, object] | None = None,
    ) -> str:
        if principal_context is not None:
            supplied = parse_principal_context(
                principal_context,
                expected_profile=self._profile_ref,
                expected_session=self._session_id,
                expected_turn=self._turn_ref,
            )
            if supplied != self._principal_context:
                self._pack, self._pack_count, self._pack_has_memory = "", 0, False
                self._prepared_receipt = None
                self._principal_context = supplied
        self._served_pack, self._served_count = self._pack, self._pack_count
        self._served_has_memory = self._pack_has_memory
        self._served_receipt = (
            mark_prefetch_receipt_returned(self._prepared_receipt) if self._prepared_receipt is not None else None
        )
        if self._served_receipt is not None:
            payload = json.dumps(self._served_receipt, ensure_ascii=False, sort_keys=True)
            self._safely(lambda: _write_text(prefetch_receipt_path(self._omh_home), payload))
        return self._pack

    def queue_prefetch(
        self,
        query: str = "",
        *,
        session_id: str = "",
        now: datetime | None = None,
        principal_context: dict[str, object] | None = None,
    ) -> None:
        """Re-render for the next turn, which is where the base class puts this work.

        Hermes queues with the turn that just finished, so the records are
        ranked for the conversation as it stands, not for the next message.
        """
        if principal_context is not None:
            self._principal_context = parse_principal_context(
                principal_context,
                expected_profile=self._profile_ref,
                expected_session=self._session_id,
                expected_turn=self._turn_ref,
            )
        self._query = str(query or "")
        self._pack = self.render_pack(now=now)

    def recall_status(self) -> RecallStatus | None:
        """What the last prefetch put into the turn, for Hermes' recall line.

        Hermes prints ``🧠 OMH — recalled N memories`` through its status
        channel -- CLI, TUI, and every gateway platform alike -- right after the
        prefetch that carried it, so the user sees memory was used even when
        the model says nothing about it. Nothing served, nothing said. A pack
        that is only a reference-block index counts as content without a
        discrete count, which Hermes renders generically; a pack that is only
        a consolidation brief is a request, not memory, and says nothing.
        """
        if not self._served_pack or not self._served_has_memory:
            return None
        return RecallStatus(provider_label=PROVIDER_LABEL, count=self._served_count)

    def latest_prefetch_receipt(self) -> dict[str, Any] | None:
        """The record-bound receipt of what the LAST prefetch returned; None otherwise.

        Rendering a pack prepares a receipt; only a prefetch turns it into the
        served one reported here, so a queued re-render never reads as served
        and a shutdown leaves nothing stale behind.
        """
        return json.loads(json.dumps(self._served_receipt)) if self._served_receipt is not None else None

    def shutdown(self) -> None:
        """Hermes is closing. Last chance to leave a brief behind."""
        self._evaluate_if_due("shutdown")
        self._pack, self._pack_count, self._pack_has_memory = "", 0, False
        self._served_pack, self._served_count, self._served_has_memory = "", 0, False
        self._prepared_receipt, self._served_receipt = None, None
        self._principal_context = None
        self._profile_ref = ""
        self._turn_ref = ""

    # -- Optional hooks -----------------------------------------------------

    def on_turn_start(self, turn_number: int, message: str = "", **kwargs: Any) -> None:
        self._turn_ref = f"turn_{turn_number}"
        self._principal_context = parse_principal_context(
            kwargs.get("principal_context"),
            expected_profile=self._profile_ref,
            expected_session=self._session_id,
            expected_turn=self._turn_ref,
        )
        self._pack, self._pack_count, self._pack_has_memory = "", 0, False
        self._served_pack, self._served_count, self._served_has_memory = "", 0, False
        self._prepared_receipt, self._served_receipt = None, None
        if not self._writes_enabled:
            return
        self._mutate_state(record_turn)
        self._evaluate_if_due("turn")

    def on_pre_compress(
        self,
        messages: list[dict[str, Any]] | None = None,
        *,
        now: datetime | None = None,
    ) -> str:
        """Hand the compressor what must survive it, and note that it happened.

        Compaction is one of the two triggers Letta uses for dreaming, and it is
        the more informative one: the session just proved it outgrew its context.
        It is also the one place where waiting costs something real -- the brief
        has to exist *before* the messages go, not at whatever later moment the
        session happens to end -- so the evaluation runs here rather than being
        deferred with a flag.
        """
        if self._writes_enabled:
            self._mutate_state(record_compaction)
            self._evaluate_if_due("compaction", messages_at_risk=len(messages or []))
        blocks = () if self._shared_surface else read_memory_blocks(self._omh_home, tier=SYSTEM_TIER)
        if not blocks:
            return ""
        selection = self._block_selection(blocks=blocks, now=now)
        return render_memory_blocks(
            blocks,
            budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
            evaluations=selection.evaluations,
        )

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record that Hermes wrote, and what shape the entry was -- never its text.

        This is the hook that closes the provenance gap. Entries written by the
        background review used to appear in MEMORY.md with nothing recording that
        they had been written, by what, or when; OMH could only observe, later,
        that some entry matched no record it held.
        """
        if not self._writes_enabled:
            return
        self._append_write_journal(action, target, content, metadata)
        self._mutate_state(record_memory_write)
        # Retirement only, and only for consolidation-shaped writes. The first
        # version routed this through the full evaluation, which had two
        # measured consequences: every write below the headroom floor re-raised
        # a brief (the embedded value changes, so suppression never held) and
        # reset the turn counter, starving the interval trigger and growing the
        # journal one record per write. And gating on the trigger alone was not
        # enough either -- an interval-raised brief has its counters cleared at
        # birth, so ANY 'add' write one moment later looked like consolidation.
        # Hermes documents the action vocabulary as add/replace/remove:
        # an 'add' appends new material and consolidates nothing; 'replace' and
        # 'remove' are what a merge or prune actually emits.
        if action in ("replace", "remove"):
            # The consolidation the turn counter is named after just happened,
            # so the clock restarts BEFORE the standing check. Observed live
            # without this: the counter survived the consolidation, so the very
            # session that tidied memory raised a fresh
            # `session_ending_with_unconsolidated_turns` brief at its own exit,
            # and every tidy-up ended by requesting the next one.
            self._mutate_state(record_consolidation_observed)
            if not self._standing_reasons():
                self._retire_stale_brief("memory_write")
                self._say(f"🧹 {PROVIDER_LABEL} — memory consolidated ({action} on {target})")

    def on_session_end(self, messages: list[dict[str, Any]] | None = None) -> None:
        self._evaluate_if_due("session_end")

    # -- Deterministic work, exposed for the CLI and for tests --------------

    def _evaluate_if_due(self, trigger: str, *, messages_at_risk: int = 0) -> dict[str, object] | None:
        """Weigh the triggers at one of the moments memory can be lost.

        Every trigger point calls this: each turn, compaction, session end,
        shutdown, and the start of the next session. Deferring the decision to
        session end alone -- which is what this did first -- means a laptop that
        closes mid-session writes nothing at all, and a turn interval that comes
        due at turn 5 waits until whenever the session happens to stop.
        """
        if not self._writes_enabled:
            return None
        return self.consolidation_due(trigger=trigger, messages_at_risk=messages_at_risk)

    def render_pack(self, *, now: datetime | None = None) -> str:
        """System blocks in full, reference blocks by label only, then the
        reviewed records the canonical selector chose for the queued query."""
        self._project_resolution = resolve_project_identity(self._project_cwd)
        moment = now or datetime.now(timezone.utc)
        blocks = () if self._shared_surface else read_memory_blocks(self._omh_home)
        selection = self._block_selection(blocks=blocks, now=moment)
        system_blocks = tuple(block for block in blocks if block.tier == SYSTEM_TIER)
        reference_blocks = tuple(block for block in blocks if block.tier == REFERENCE_TIER)
        system, block_count = render_memory_blocks_counted(
            system_blocks,
            budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
            evaluations=selection.evaluations,
        )
        index = render_block_index(reference_blocks, evaluations=selection.evaluations)
        # One selection contract for the live turn and the coding handoff:
        # explicit user-global/project/thread allowlist, the Hermes perspective
        # lens, and the selector's own lifecycle, ranking and budget ladder.
        snapshot = read_record_store_snapshot(self._record_homes())
        prepared = prepare_prefetch_records(
            snapshot,
            self._query,
            allowed_scopes=self._prefetch_scopes(),
            session_id=self._session_id,
            now=moment,
            principal_context=self._principal_context,
            shared_surface=self._shared_surface,
        )
        records = prepared.section.text
        # The count is what the renderer emitted, never what selection chose.
        self._pack_count = block_count + len(prepared.section.rendered)
        self._pack_has_memory = bool(system or index or records)
        self._prepared_receipt = build_prefetch_receipt(
            prepared,
            session_id=self._session_id,
            home_digests=snapshot.home_digests,
            rendered_block_count=block_count,
            project_resolution=self._project_resolution,
        )
        # The brief is a request, not a memory: it is served so the model can
        # consolidate in this turn, and it never moves the recall count.
        consolidation = render_consolidation_brief(read_latest_consolidation(self._omh_home))
        return "\n".join(part for part in (system, index, records, consolidation) if part)

    def _record_homes(self) -> tuple[Path, ...]:
        """The project store first when there is one, then the user store."""
        if self._project_home is not None and self._project_home != self._omh_home:
            return (self._project_home, self._omh_home)
        return (self._omh_home,)

    def _prefetch_scopes(self) -> list[dict[str, str]]:
        """One stable project label, or an unresolved, fail-closed allowlist."""
        identity = self._project_resolution.identity
        principal = str(self._principal_context.get("principal", "")) if self._principal_context is not None else ""
        return prefetch_scope_allowlist(
            project_identity=identity,
            session_id=self._session_id,
            principal_ref=principal,
            include_legacy_personal=not self._shared_surface,
        )

    def consolidation_due(
        self,
        *,
        trigger: str = "manual",
        messages_at_risk: int = 0,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Decide whether dreaming is due; write the brief when it is.

        Returns the handoff either way so a caller can see the reasons that were
        weighed, not only the ones that fired.
        """
        state = read_dreaming_state(self._omh_home)
        moment = now or datetime.now(timezone.utc)
        plan, reason_kwargs, record_expiry = self._evaluation_inputs(trigger, now=moment)
        blocks = () if self._shared_surface else read_memory_blocks(self._omh_home)
        selection = self._block_selection(blocks=blocks, now=moment)
        reasons = self._with_replay_reminders(consolidation_reasons(state, **reason_kwargs), selection)
        handoff = build_consolidation_handoff(
            reasons,
            block_summaries=[self._block_summary(block, selection.evaluations[block.block_id]) for block in blocks],
            eviction_plan=plan,
            record_expiry=record_expiry,
            trigger=trigger,
            messages_at_risk=messages_at_risk,
            session_id=self._session_id,
            # Only a brief that actually fires was raised; stamping the not-due
            # inspection object gave it a raise time for a raise that never was.
            raised_at=_utc_now() if reasons else "",
        )
        if reasons:
            self._write_handoff(handoff)
            write_dreaming_state(
                self._omh_home,
                clear_after_consolidation(state, at=_utc_now(), reasons=reasons),
            )
            self._say(consolidation_status_line(trigger, reasons))
        else:
            # Suppression keeps an unchanged `expiring_records:N` from re-firing,
            # which is right -- but the breakdown behind that N can still move
            # (a record crossing from expiring into expired keeps N identical).
            # The persisted brief is refreshed in place: no new notification,
            # no suppression reset, no counter mutation.
            self._refresh_brief_record_expiry(record_expiry)
        return handoff

    def _evaluation_inputs(
        self,
        trigger: str,
        *,
        count_expiry: bool = True,
        now: datetime | None = None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, int]]:
        """The eviction plan, reason kwargs, and expiry counts for one evaluation.

        The expiry scan is one glob plus a JSON parse per approved record and
        runs at most once per evaluation. The retirement standing-check passes
        ``count_expiry=False``: expiry is a standing condition only retirement
        itself can clear, so counting it there would both waste the scan and
        block `_retire_stale_brief` forever.
        """
        moment = now or datetime.now(timezone.utc)
        reading = self._memory_reading()
        plan = (
            build_eviction_plan(reading.entries, cap=reading.cap, cap_source=reading.cap_source)
            if reading is not None
            else {}
        )
        record_expiry = (
            count_record_expiry(self._omh_home, now=moment)
            if count_expiry and not self._shared_surface
            else {"expired": 0, "expiring_soon": 0}
        )
        return (
            plan,
            {
                "headroom_chars": reading.headroom_chars if reading is not None else None,
                "duplicate_count": len(plan.get("duplicate_clusters", []) or []),
                "expiring_count": record_expiry["expired"] + record_expiry["expiring_soon"],
                "session_ending": trigger in _SESSION_ENDING_TRIGGERS,
            },
            record_expiry,
        )

    def _refresh_brief_record_expiry(self, record_expiry: dict[str, int]) -> None:
        """Keep the persisted due brief's expiry breakdown current, silently."""
        brief = read_latest_consolidation(self._omh_home)
        if not brief or not brief.get("due") or brief.get("record_expiry") == record_expiry:
            return
        updated = dict(brief)
        updated["record_expiry"] = dict(record_expiry)
        payload = json.dumps(updated, ensure_ascii=False, sort_keys=True)
        self._safely(lambda: _write_text(self._omh_home / "memory" / "consolidation.json", payload))

    def _standing_reasons(self) -> list[str]:
        """Is anything still true at all? Read-only, suppression bypassed.

        A suppressed standing condition returns [] from the default evaluation
        while remaining true; retirement must see through that, or it would
        clear a notice whose fact had not cleared.
        """
        state = read_dreaming_state(self._omh_home)
        _, reason_kwargs, _record_expiry = self._evaluation_inputs("memory_write", count_expiry=False)
        blocks = () if self._shared_surface else read_memory_blocks(self._omh_home)
        selection = self._block_selection(blocks=blocks)
        return [
            *consolidation_reasons(state, suppress=False, **reason_kwargs),
            *self._replay_reminder_reasons(selection),
        ]

    def _retire_stale_brief(self, trigger: str) -> None:
        """Mark the on-disk brief not-due once consolidation was observed.

        Nothing used to clear `consolidation.json`: it was written when
        consolidation came due and never touched again, so the doctor warning
        and every messenger's chat notice repeated forever -- including after
        the user actually consolidated.

        The only caller is the consolidation-shaped branch of
        `on_memory_write`: a 'replace' or 'remove' from Hermes' memory tool is
        what a merge or prune actually emits, and it is the one observable
        signal that consolidation happened. Timers, reads, and other triggers
        never retire -- event reasons clear their own counters by firing, so
        anything looser erases a brief before anyone could act on it.
        """
        brief = read_latest_consolidation(self._omh_home)
        if not brief or not brief.get("due"):
            return
        retired = dict(brief)
        retired["due"] = False
        retired["superseded_at"] = _utc_now()
        retired["superseded_by_trigger"] = trigger
        self._write_handoff(retired)

    # -- Internals ----------------------------------------------------------

    def _block_selection(
        self,
        *,
        blocks: tuple[MemoryBlock, ...] | None = None,
        now: datetime | None = None,
    ) -> MemoryBlockSelection:
        return select_memory_blocks(
            blocks if blocks is not None else (() if self._shared_surface else read_memory_blocks(self._omh_home)),
            now=now,
            omh_home=self._omh_home,
        )

    @staticmethod
    def _block_summary(block: MemoryBlock, evaluation: dict[str, object]) -> dict[str, object]:
        return {
            **block.to_summary(),
            "replay": {
                "eligible": bool(evaluation.get("eligible")),
                "reason_code": str(evaluation.get("reason_code", "ineligible")),
            },
        }

    @staticmethod
    def _replay_reminder_reasons(selection: MemoryBlockSelection) -> list[str]:
        stale = sum(
            evaluation.get("reason_code") == "stale_review_required"
            for evaluation in selection.evaluations.values()
        )
        expired_volatile = sum(
            evaluation.get("reason_code") == "expired_volatile"
            for evaluation in selection.evaluations.values()
        )
        reasons = []
        if stale:
            reasons.append(f"stale_review_required:{stale}")
        if expired_volatile:
            reasons.append(f"expired_volatile_records:{expired_volatile}")
        return reasons

    def _with_replay_reminders(
        self,
        reasons: list[str],
        selection: MemoryBlockSelection,
    ) -> list[str]:
        # Replay exclusions are standing reminder evidence, not another
        # consolidation trigger subject to the normal last-reasons suppression.
        # A manual inspection must still report them when no ordinary trigger
        # fired; the selection is read-only and evaluated at the same instant
        # as the rest of this consolidation decision.
        return [*reasons, *self._replay_reminder_reasons(selection)]

    def _memory_reading(self):
        if self._hermes_home is None:
            return None
        try:
            readings = read_hermes_memory(self._hermes_home)
        except OSError:
            return None
        return next((item for item in readings if item.label == "MEMORY.md" and item.exists), None)

    def _mutate_state(self, mutate) -> None:
        state = read_dreaming_state(self._omh_home)
        self._safely(lambda: write_dreaming_state(self._omh_home, mutate(state)))

    def _write_handoff(self, handoff: dict[str, object]) -> None:
        """Write the latest handoff and retain a bounded metadata-only journal."""
        directory = self._omh_home / "memory"
        payload = json.dumps(handoff, ensure_ascii=False, sort_keys=True)
        self._safely(lambda: _write_text(directory / "consolidation.json", payload))
        entry = _consolidation_journal_entry(handoff)
        self._safely(lambda: _append_bounded_json_line(directory / "consolidation.jsonl", entry))

    def _append_write_journal(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        entry: dict[str, object] = {
            "schema_version": WRITE_JOURNAL_SCHEMA_VERSION,
            "observed_at": _utc_now(),
            "action": str(action or ""),
            "target": str(target or ""),
            "chars": len(str(content or "")),
            "content_digest": hashlib.sha256(str(content or "").encode("utf-8")).hexdigest(),
            "session_id": self._session_id,
            "write_origin": str((metadata or {}).get("write_origin", "") or ""),
            "execution_context": str((metadata or {}).get("execution_context", "") or ""),
            "scope_decision": self._native_write_scope_decision(target, metadata),
            "redaction_policy": "metadata_only",
        }
        identity = _journal_record_identity((metadata or {}).get("record_identity"))
        if identity is not None:
            entry["record_identity"] = identity
        path = self._omh_home / "memory" / "write_journal.jsonl"
        self._safely(lambda: _append_bounded_json_line(path, entry))

    def _native_write_scope_decision(
        self,
        target: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, object]:
        supplied = metadata.get("principal_context") if isinstance(metadata, dict) and "principal_context" in metadata else metadata
        context = parse_principal_context(
            supplied,
            expected_profile=self._profile_ref,
            expected_session=self._session_id,
            expected_turn=self._turn_ref,
        )
        actor_kind = str(context.get("actor_kind", "unknown")) if context is not None else "unknown"
        principal = str(context.get("principal", "")) if context is not None else ""
        allowed = str(target) == "user" and actor_kind == "human" and bool(principal)
        return {
            "decision": "allow_observation" if allowed else "deny_observation",
            "reason_code": "human_principal_bound" if allowed else "principal_unbound_or_nonhuman",
            "principal_ref": principal or None,
            "actor_kind": actor_kind,
            "admission_performed": False,
        }

    def _say(self, line: str) -> None:
        """One status line through the host, where the host offered a channel.

        Hermes passes `status_callback` to `initialize` on the CLI surface; it
        prints there and forwards to the gateway status path. A failing
        callback must not take down the hook that called it.
        """
        if self._status_callback is None or not line:
            return
        try:
            self._status_callback(line)
        except Exception:  # noqa: BLE001 - host callback; the memory hook must survive it
            return

    @staticmethod
    def _safely(write) -> None:
        """A memory-provider write must never take down the turn that triggered it.

        Hermes calls these hooks inside a live conversation. A read-only home, a
        full disk, or a racing writer is a lost journal line -- not a failed turn
        -- so the failure is swallowed here and nowhere else in this module.
        """
        try:
            write()
        except OSError:
            return


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_bounded_json_line(path: Path, entry: dict[str, object]) -> None:
    """Atomically retain the newest metadata-only journal entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _metadata_journal_lines(path)
    lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[-JOURNAL_LIMIT:]) + "\n")
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _metadata_journal_lines(path: Path) -> list[str]:
    try:
        if path.is_symlink() or not path.is_file():
            return []
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    entries = []
    for line in source.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if _metadata_only(data):
            entries.append(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return entries[-(JOURNAL_LIMIT - 1) :]


def _metadata_only(value: object) -> bool:
    forbidden = ("content", "value", "summary", "description", "sha256", "hash", "prompt", "body", "raw")
    if isinstance(value, dict):
        return all(
            isinstance(key, str)
            and not any(term in key.lower() for term in forbidden)
            and _metadata_only(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_metadata_only(item) for item in value)
    return value is None or isinstance(value, (bool, int, float, str))


def _consolidation_journal_entry(handoff: dict[str, object]) -> dict[str, object]:
    entry: dict[str, object] = {
        "schema_version": str(handoff.get("schema_version", "") or ""),
        "due": bool(handoff.get("due")),
        "trigger": str(handoff.get("trigger", "") or ""),
        "raised_at": str(handoff.get("raised_at", "") or ""),
        "session_id": str(handoff.get("session_id", "") or ""),
        "messages_at_risk": _non_negative_int(handoff.get("messages_at_risk")),
        "reasons": [str(reason) for reason in handoff.get("reasons", []) if isinstance(reason, str)],
        "record_expiry": _record_expiry_summary(handoff.get("record_expiry")),
        "blocks": _block_summaries(handoff.get("blocks")),
        "requested_of_executor": [
            str(instruction)
            for instruction in handoff.get("requested_of_executor", [])
            if isinstance(instruction, str)
        ],
        "redaction_policy": "metadata_only",
    }
    sequence = handoff.get("sequence")
    if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0:
        entry["sequence"] = sequence
    return entry


def _record_expiry_summary(value: object) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        "expired": _non_negative_int(source.get("expired")),
        "expiring_soon": _non_negative_int(source.get("expiring_soon")),
    }


def _block_summaries(value: object) -> list[dict[str, object]]:
    allowed = {
        "block_id",
        "revision",
        "label",
        "tier",
        "chars",
        "limit",
        "headroom_chars",
        "over_limit",
        "source_class",
        "admission_status",
    }
    rows = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        row = {key: item[key] for key in allowed & set(item) if _metadata_only(item[key])}
        replay = item.get("replay")
        if isinstance(replay, dict):
            row["replay"] = {
                "eligible": bool(replay.get("eligible")),
                "reason_code": str(replay.get("reason_code", "ineligible")),
            }
        rows.append(row)
    return rows


def _journal_record_identity(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) != {"schema_version", "id", "id_key", "revision", "scope"}:
        return None
    schema_version = value.get("schema_version")
    id_key = value.get("id_key")
    if not isinstance(schema_version, str) or not isinstance(value.get("id"), str) or not value["id"]:
        return None
    expected_id_keys = {
        "project_memory_record/v2": "record_id",
        "omh_memory_scope/v2": "item_id",
        "omh_memory_block/v2": "block_id",
    }
    if expected_id_keys.get(schema_version) != id_key:
        return None
    revision = value.get("revision")
    scope = value.get("scope")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
        return None
    if not isinstance(scope, dict) or set(scope) != {"kind", "ref"}:
        return None
    if not isinstance(scope.get("kind"), str) or not isinstance(scope.get("ref"), str) or not scope["ref"]:
        return None
    return {
        "schema_version": schema_version,
        "id": value["id"],
        "id_key": id_key,
        "revision": revision,
        "scope": {"kind": scope["kind"], "ref": scope["ref"]},
    }


def _non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def render_consolidation_brief(brief: dict[str, Any] | None) -> str:
    """The due brief as one bounded prompt section; "" when nothing is due.

    Measured before this existed: 32 briefs in seven days on one machine,
    every one written to disk, none ever read by a model -- the chat card
    notice lives on the wrapper surface, and a Hermes turn saw nothing. So
    `memory_writes_observed` stayed 0 at every consolidation. The section asks
    for the consolidation and for one line to the user, which is the only
    channel that reaches every platform Hermes speaks through.
    """
    if not brief or not brief.get("due"):
        return ""
    lines = [f'<memory_consolidation trigger="{_attr(brief.get("trigger", ""))}" raised_at="{_attr(brief.get("raised_at", ""))}">']
    reasons = [str(item) for item in brief.get("reasons", []) if isinstance(item, str)]
    for reason in reasons[:CONSOLIDATION_MAX_ITEMS]:
        lines.append(f"  <reason>{_text(reason)}</reason>")
    if len(reasons) > CONSOLIDATION_MAX_ITEMS:
        lines.append(f'  <omitted reasons="{len(reasons) - CONSOLIDATION_MAX_ITEMS}" />')
    plan = brief.get("eviction_plan") if isinstance(brief.get("eviction_plan"), dict) else {}
    clusters = plan.get("duplicate_clusters") if isinstance(plan.get("duplicate_clusters"), list) else []
    if clusters or plan.get("headroom_chars") is not None:
        lines.append(
            f'  <hermes_memory entries="{_attr(plan.get("entry_count", ""))}" headroom_chars="{_attr(plan.get("headroom_chars", ""))}"'
            f' duplicate_clusters="{len(clusters)}" />'
        )
    requested = [str(item) for item in brief.get("requested_of_executor", []) if isinstance(item, str)]
    for item in requested[:CONSOLIDATION_MAX_ITEMS]:
        lines.append(f"  <do>{_text(item)}</do>")
    lines.append("  <do>Then tell the user in one short line that OMH asked for memory consolidation and what you changed, or that nothing needed changing.</do>")
    lines.append("</memory_consolidation>")
    text = "\n".join(lines)
    if len(text) > CONSOLIDATION_RENDER_BUDGET_CHARS:
        text = text[: CONSOLIDATION_RENDER_BUDGET_CHARS - len("\n</memory_consolidation>")].rsplit("\n", 1)[0] + "\n</memory_consolidation>"
    return text


def consolidation_status_line(trigger: str, reasons: list[str]) -> str:
    """The line a host prints when a brief fires: trigger and the first reason."""
    first = reasons[0] if reasons else ""
    more = f" +{len(reasons) - 1}" if len(reasons) > 1 else ""
    return f"💤 {PROVIDER_LABEL} — memory consolidation due ({trigger}: {first}{more})"


def _text(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(value: object) -> str:
    return _text(str(value if value is not None else "")).replace('"', "&quot;")


def _default_omh_home() -> Path:
    return runtime_paths.default_omh_home()


def _project_omh_home(cwd: object = None) -> Path | None:
    """`<repository>/.omh` for the nearest `.git` above the working directory.

    The same rule `omh --scope project` uses: a `.git` directory in a checkout
    or a `.git` file in a linked worktree marks the root. Hermes passes no
    working directory to `initialize`, so use its logical context cwd.
    """
    try:
        start = runtime_paths.expand_path(cwd) if cwd else runtime_paths.runtime_cwd()
        if start is None:
            return None
        root = project_identity_root(start)
        if root is not None:
            return root / ".omh"
    except OSError:
        return None
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
