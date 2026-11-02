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

The provider exposes one small save/recall tool, ``omh_remember``. Hermes
tool_search never defers provider tools, so the save path stays visible without
loading the full ``omh_memory`` plugin tool. The full tool still handles block
reads and memory lifecycle operations through the plugin path.

OMH still makes no model call and still cannot write Hermes memory. This
provider reads OMH's own store, renders it, and records what it saw.
"""

from __future__ import annotations

from . import runtime_paths

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

# A missing optional module or exported symbol is a capability gap; an
# internal import failure in an existing host module must still propagate.
_memory_api = runtime_paths._optional_module("agent.memory_provider")
_MemoryProviderBase = getattr(_memory_api, "MemoryProvider", object)
RecallStatus = getattr(_memory_api, "RecallStatus", None)
if RecallStatus is None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class RecallStatus:  # type: ignore[no-redef]
        """Field-for-field the Hermes contract, so the repo's tests see what Hermes sees."""

        provider_label: str
        count: int
        glyph: str = "🧠"


from .hermes_memory import (
    entry_digest,
    HermesMemoryFile,
    count_record_expiry,
    demotion_origin_ref,
    read_approved_records,
    read_hermes_memory,
)
from .memory_admission import demotion_refusal_reason
from .memory_store_io import guard_store_write, read_project_memory_candidates
from .memory_block_replay import MemoryBlockSelection
from .memory_blocks import (
    DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
    MemoryBlock,
    REFERENCE_TIER,
    SYSTEM_TIER,
    read_memory_blocks,
    render_block_index,
    render_memory_blocks,
    render_memory_blocks_within,
    select_memory_blocks,
)
from .memory_dreaming import (
    adopt_legacy_dreaming_files,
    build_consolidation_handoff,
    clear_after_consolidation,
    configured_dreaming_mode,
    consolidation_path,
    consolidation_reasons,
    headroom_floor_for_cap,
    HEADROOM_USER_GUARD_INSTRUCTION,
    dreaming_state_path,
    HEADROOM_DEMOTE_INSTRUCTION,
    HEADROOM_TRIM_INSTRUCTION,
    normalize_demotion_rows,
    read_dreaming_state,
    read_latest_consolidation,
    record_compaction,
    record_consolidation_observed,
    record_memory_write,
    record_turn,
    update_dreaming_state,
)
from .memory_eviction import build_eviction_plan
from .memory_messenger import CHANNEL, DIRECT, HermesAuthorization, MessengerConversation, classify_conversation, principal_identity, same_person
from .memory_principals import PrincipalContractError, build_principal_context, derive_channel_ref, parse_principal_context
from .project_identity import ProjectIdentityResolution, project_identity_root, resolve_project_identity
from .memory_prefetch_receipt import (
    build_prefetch_receipt,
    mark_prefetch_receipt_returned,
    prefetch_receipt_path,
)
from .memory_principals import principal_recall_decision
from .memory_query_sanitizer import sanitize_memory_query
from .memory_recall_selector import resolve_scope_allowlist
from .memory_recall_support import _record_perspective_matches
from .memory_session_digest import (
    clamp_to_reported,
    digest_window_start,
    render_session_digest,
    session_close_path,
    session_digest_counts,
    write_reported_through,
    write_session_close,
)
from .memory_session_lens import (
    BOUND_SURFACE_CLASSES,
    OPERATOR_CONSOLE_PLATFORMS,
    OWNER_SURFACE_CLASSES,
    PRIMARY_AGENT_CONTEXTS,
    SESSION_LENS_STALE_HOURS,
    SURFACE_BACKGROUND,
    SURFACE_CHANNEL,
    SURFACE_DIRECT,
    SURFACE_OPERATOR_CONSOLE,
    SURFACE_OWNER_DIRECT,
    SURFACE_SHARED,
    lens_surface_class,
    memory_surface_class,
    note_session_records,
    publish_session_lens,
    read_session_lens,
    session_lens_path,
    surface_flags,
    tighter_surface_class,
    withdraw_session_lens,
)
from .memory_records import (
    PREFETCH_EXECUTOR_TARGET,
    prefetch_required_scope_kinds,
    prefetch_scope_allowlist,
    prepare_prefetch_records,
    read_record_store_snapshot,
    record_served,
)
from .memory_open_reminders import (
    mark_open_reminder_asked,
    open_reminders_path,
    read_open_reminders,
    render_open_reminder,
    select_open_reminder,
)
from .memory_state_files import state_file_lock, write_text_atomic, write_text_locked
from .memory_thread_parent import auto_thread_parent_channel
from .tools.memory_tool import REMEMBER_TOOL_SCHEMA, REMEMBER_TOOL_NAME, omh_remember_handler

PROVIDER_NAME = "omh"
# What Hermes prints in front of "recalled N memories" on every surface it
# speaks through -- CLI, TUI, and each gateway platform -- when a prefetch
# actually put OMH memory into the turn.
PROVIDER_LABEL = "OMH"
# The brief rides in the prefetch pack, bounded so a long reason list or eviction
# plan cannot crowd out the memory it is asking the model to keep.
CONSOLIDATION_RENDER_BUDGET_CHARS = 1600
CONSOLIDATION_MAX_ITEMS = 6
# Three moves of the largest entries free most of a
# nearly-full file, and the rows have to share the render budget above.
DEMOTION_BRIEF_MAX_ROWS = 3
DEMOTION_PREVIEW_CHARS = 40
WRITE_JOURNAL_SCHEMA_VERSION = "omh_memory_write_journal_entry/v1"
JOURNAL_LIMIT = 32
# Swallowed write failures kept on the provider for the receipt; the count
# keeps going past it, only the detail is bounded.
WRITE_FAILURE_LIMIT = 16

# Hermes states that only a primary agent should write; a cron or subagent
# context replaying its own system prompt would otherwise move the counters that
# decide when consolidation is due. That is the background surface class
# (`memory_surface_class`), whose writes are off.

# Hermes spills an external provider's prefetch result longer than this many
# characters to a file and keeps only its first and last 500 in the prompt
# (`DEFAULT_MAX_CHARS`, hermes-agent `tools/hook_output_spill.py`, applied by
# `MemoryManager` in `agent/memory_manager.py`). Copied, not imported: OMH
# does not import Hermes; tests/test_memory_pack_budget.py compares the copy.
HERMES_PREFETCH_SPILL_MAX_CHARS = 10_000
# The whole pack's budget. Past the spill cap the records in the middle of the
# pack vanish while the receipt, `served.json` and the reminder ledger still
# count them as served. Each section's own cap summed to about 11,300
# characters before the reference index, which had none. The 1,000 characters
# of margin absorb a smaller default in a later Hermes before the pin test
# catches it, and keep the pack clear of the cap rather than at it.
PACK_BUDGET_CHARS = 9_000
# The reference index lists labels whose values stay behind `omh_memory read`;
# past this it keeps a prefix and one `<omitted count=...>` line.
REFERENCE_INDEX_PACK_MAX_CHARS = 600
# System blocks take what the other sections leave, at most their own
# section cap. Below the floor, index lines and then the brief's demote rows
# give way first. The floor is what system blocks are left when every other
# section sits at its cap with ordinary record ids (records 2,400, digest 512,
# brief 1,600, index 600, a reminder near 750, separators): about 3,100. So
# trimming past the blocks happens only when a section runs long, such as a
# reminder about a record with a long imported id, and the top block at the
# default 2,000-character block limit (about 2,200 with its element) still
# fits whole beside a few omission lines.
SYSTEM_BLOCKS_PACK_MAX_CHARS = DEFAULT_SYSTEM_RENDER_BUDGET_CHARS
SYSTEM_BLOCKS_PACK_FLOOR_CHARS = 3_000

# Hermes sets these in a Kanban worker's environment
# (`hermes_cli/kanban_db_dispatch.py`, the worker spawn). A worker is a CLI
# process, so it is an operator console, but nobody is at it.
KANBAN_WORKER_ENV_TASK = "HERMES_KANBAN_TASK"
KANBAN_WORKER_ENV_SOURCE = ("HERMES_SESSION_SOURCE", "kanban")

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
        # The profile whose dreaming counters, brief and mode this provider
        # keeps (`memory_dreaming.profile_dreaming_dir`): the Hermes home
        # `resolve_homes` chose, kept even where that store is not yet bound
        # for reading below, and rebound by `initialize` to the home it is given.
        self._profile_home: Path = self._hermes_home
        if hermes_home is None and runtime_paths._host() is None:
            # Standalone callers may supply the native comparison root at first
            # initialize; no Hermes store is read before that explicit binding.
            self._hermes_home = None
        self._session_id = ""
        self._writes_enabled = True
        self._principal_context: dict[str, object] | None = None
        self._profile_ref = ""
        self._turn_ref = ""
        # Decided at `initialize` (`memory_surface_class`). Before it, as for
        # `omh memory dream --evaluate`, the caller is the operator's own CLI.
        # `_declared_class` is that decision; `_session_class` is this
        # provider's own class for the current turn (a messenger conversation
        # re-derives it at each turn start); `_surface_class` is what this
        # session id is held to: `_session_class` narrowed by the tightest
        # lens another provider published under the id (`_foreign_floor`,
        # `_tighten_to`) until the id changes.
        self._declared_class = SURFACE_OPERATOR_CONSOLE
        self._session_class = SURFACE_OPERATOR_CONSOLE
        self._foreign_floor: str | None = None
        self._surface_class = SURFACE_OPERATOR_CONSOLE
        self._tightened_by_foreign_lens = False
        # A gateway conversation `memory_messenger` verified from Hermes'
        # kwargs (a 1:1 DM or a group), its channel scope, and the authorized
        # set the owner's DM is judged by. None everywhere else.
        self._conversation: MessengerConversation | None = None
        self._channel_scope: dict[str, str] | None = None
        self._authorization: HermesAuthorization | None = None
        self._messenger_profile = "default"
        # This turn's author as Hermes passed it to `on_turn_start` (id, is a
        # bot). Kept so a session id rotated mid-turn is bound by the same
        # author, never by a default that reads as the DM partner.
        self._turn_author: tuple[str, bool] = ("", False)
        self._shared_surface = False
        # A console nobody is at: a Kanban worker (`_attended`).
        self._unattended = False
        # Names the lens files this provider writes, so it never withdraws or
        # widens another provider's lens under the same session id.
        self._instance = secrets.token_hex(8)
        # True once this provider found a tighter lens another instance wrote
        # under its session id and adopted it (`_publish_lens`).
        self._guest = False
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
        self._query_sanitized = sanitize_memory_query("")
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
        # The one `omh reminder:` line the rendered pack asks about an open
        # record, and the one the LAST prefetch actually served. The ask
        # ledger is written only when the pack is served, and once per
        # prepared reminder: a queued re-render that is never served must not
        # count as having asked, and the same pack served to several API
        # calls inside one turn is one ask, not several.
        self._prepared_reminder: dict[str, object] | None = None
        self._served_reminder: dict[str, object] | None = None
        self._reminder_recorded = False
        # The records the rendered pack carries, and whether their serve was
        # counted. Same rule as the reminder: `prefetch` counts, a queued
        # re-render does not, and one render served to several API calls in a
        # turn is one serve. `served.json` is never a ranking input.
        self._prepared_record_ids: tuple[str, ...] = ()
        self._served_recorded = False
        # The "since your last session" digest (`memory_session_digest`): its
        # window is fixed at a session start, every render carries it until a
        # prefetch serves one, then never again in that session.
        # `_pack_digest_evaluated` says the current render was made while it
        # was pending, so a pack rendered before a `/new` cannot use up the
        # new session's digest.
        self._digest_window: tuple[datetime, datetime] | None = None
        self._digest_pending = False
        self._pack_digest_evaluated = False
        self._pack_digest = ""
        # The confinement last published for `omh_memory` (`_publish_lens`).
        self._published_lens: dict[str, object] | None = None
        # Hermes hands a status callback to providers on the CLI surface only;
        # gateway platforms travel a different path and get the brief through
        # the pack instead. None means "say nothing here", never "fail".
        self._status_callback = None
        # Every write `_safely` swallowed: op, file basename and error class
        # only. Kept for the life of the provider, not reset per session, so a
        # failure during one session's shutdown still reaches the next receipt.
        self._write_failures: list[dict[str, str]] = []
        self._write_failure_count = 0
        # One render at a time, and a serve reads one render whole: Hermes
        # queues the finished turn's render on a worker thread while the
        # next turn's hooks run on the main thread. Re-entrant because a
        # serve may itself render.
        self._render_lock = threading.RLock()

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

    def backup_paths(self) -> list[str]:
        """Existing real OMH memory directory for Hermes backup, without initialization.

        A restored ``principal.key`` initially has the restore's umask mode;
        ``memory_principals._principal_key`` re-tightens it to 0600 on its next
        read. This hook only lists paths and never creates or changes them.
        """
        try:
            memory = self._omh_home / "memory"
            return [str(memory.absolute())] if not memory.is_symlink() and memory.is_dir() else []
        except (OSError, ValueError):
            return []

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home is not None:
            supplied_home = runtime_paths.expand_path(hermes_home)
            if self._hermes_home is not None and supplied_home != self._hermes_home:
                raise runtime_paths.RuntimeBindingError("OMH provider cannot be initialized for another profile")
            self._hermes_home = supplied_home
            self._profile_home = supplied_home
        self._query = ""
        self._query_sanitized = sanitize_memory_query("")
        self._pack, self._pack_count, self._pack_has_memory = "", 0, False
        self._served_pack, self._served_count, self._served_has_memory = "", 0, False
        self._prepared_receipt, self._served_receipt = None, None
        self._prepared_reminder, self._served_reminder, self._reminder_recorded = None, None, False
        self._prepared_record_ids, self._served_recorded = (), False
        self._session_id = str(session_id or "")
        # Hermes passes `platform` (`cli`, `tui`, `desktop`, a gateway name,
        # `cron`, `subagent`) and `agent_context` (`agent/agent_init.py`,
        # `_memory_provider_init_kwargs`); it never passes `principal_context`.
        # A gateway also passes the chat's identity (`chat_type`, `chat_id`,
        # `chat_name`, `user_id`, `thread_id`, each only when set), from which
        # a 1:1 DM or a group conversation is verified (`memory_messenger`); a
        # primary gateway session nothing verifies stays shared.
        platform, agent_context = kwargs.get("platform", ""), kwargs.get("agent_context", "")
        shared_request = kwargs.get("shared_surface", False)
        self._conversation, self._channel_scope, self._authorization = None, None, None
        self._turn_author = ("", False)
        self._messenger_profile = str(kwargs.get("agent_identity", "") or "default")
        if str(agent_context or "") in PRIMARY_AGENT_CONTEXTS and not shared_request and str(platform or "") not in OPERATOR_CONSOLE_PLATFORMS:
            self._conversation = classify_conversation(
                platform,
                chat_type=kwargs.get("chat_type"),
                chat_id=kwargs.get("chat_id"),
                user_id=kwargs.get("user_id"),
                thread_id=kwargs.get("thread_id"),
                chat_name=kwargs.get("chat_name"),
                hermes_home=self._hermes_home,
            )
        if self._conversation is not None:
            self._authorization = HermesAuthorization(self._hermes_home)
            if self._conversation.kind == CHANNEL:
                channel_identity = (
                    auto_thread_parent_channel(self._hermes_home, self._session_id)
                    if self._conversation.platform == "discord" and self._hermes_home is not None else None
                )
                self._channel_scope = self._derive_channel_scope(self._conversation, channel_identity=channel_identity)
        self._declared_class = memory_surface_class(
            platform=platform,
            agent_context=agent_context,
            shared_surface=shared_request,
            messenger_class=self._messenger_class() if self._conversation is not None else "",
        )
        self._session_class, self._foreign_floor = self._declared_class, None
        self._settle_class()
        # Read where the provider runs: Hermes starts a Kanban worker as its own
        # `hermes -p <profile> --cli ... chat -q` process with these set.
        self._unattended = bool(os.environ.get(KANBAN_WORKER_ENV_TASK)) or (
            os.environ.get(KANBAN_WORKER_ENV_SOURCE[0]) == KANBAN_WORKER_ENV_SOURCE[1]
        )
        self._principal_context = parse_principal_context(
            kwargs.get("principal_context"),
            expected_session=self._session_id,
        )
        self._profile_ref = str(self._principal_context.get("profile_ref", "")) if self._principal_context is not None else str(kwargs.get("active_profile", "") or "")
        if self._shared_surface:
            self._principal_context = None
        # A DM's principal is OMH's own, derived from the verified partner.
        self._bind_conversation()
        cwd = runtime_paths.expand_path(kwargs["cwd"]) if kwargs.get("cwd") else runtime_paths.runtime_cwd()
        self._project_cwd = str(cwd) if cwd is not None else None
        self._project_home = _project_omh_home(cwd) if cwd is not None else None
        callback = kwargs.get("status_callback")
        self._status_callback = callback if callable(callback) else None
        self._guest = False
        self._publish_lens(reset=True, initializing=True)
        self._claim_legacy_dreaming_state()
        self._start_session_digest(initializing=True)
        self._pack = self.render_pack()
        # A session that died rather than ended -- a killed process, a closed
        # laptop, a lost gateway -- never reaches on_session_end, so nothing
        # would ever act on the turns it accumulated. The counters survived on
        # disk; this is where they are honoured.
        self._evaluate_if_due("session_start_recovery")

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Keep save/recall visible: Hermes tool_search never defers provider tools."""
        return [REMEMBER_TOOL_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs: Any) -> str:
        """Dispatch with this provider's session, never a model-supplied identity."""
        if tool_name == REMEMBER_TOOL_NAME:
            return omh_remember_handler(args, session_id=self._session_id)
        return json.dumps({"status": "error", "reason": "unknown_tool"}, sort_keys=True)

    def system_prompt_block(self) -> str:
        """A static save reminder for foreground conversations, not background agents."""
        if self._surface_class == SURFACE_BACKGROUND:
            return ""
        return "Use omh_remember to save lasting preferences, decisions and facts the user states, and to recall them in later conversations."

    def prefetch(
        self,
        query: str = "",
        *,
        session_id: str = "",
        principal_context: dict[str, object] | None = None,
    ) -> str:
        with self._render_lock:
            if session_id and str(session_id) != self._session_id and self._session_id:
                # Hermes passes the live id every turn; a turn-lease reload
                # rotates it without `on_session_switch`, and the tool finds
                # its lens by that id. `reset`: from here a `/new` racing this
                # prefetch is indistinguishable from a reload, and carrying the
                # old conversation's seen/confirmed lists into a new one is
                # the worse mistake. No digest, though: a reload is the same
                # conversation, and a real `/new` still reaches
                # `on_session_switch(reset=True)` from Hermes' worker.
                self._rebind_session(str(session_id), reset=True)
            if principal_context is not None and self._conversation is None:
                # A verified messenger conversation binds its own principal.
                supplied = parse_principal_context(
                    principal_context,
                    expected_profile=self._profile_ref,
                    expected_session=self._session_id,
                    expected_turn=self._turn_ref,
                )
                if supplied != self._principal_context:
                    # The pack and its reminder were chosen under the lens they
                    # were rendered for. A different principal gets its own
                    # render, never the previous lens's pack -- and never an empty
                    # one either, which would make memory vanish for whoever
                    # arrived second.
                    self._principal_context = supplied
                    self._publish_lens(reset=False)
                    self._pack = self.render_pack()
            sanitized = sanitize_memory_query(str(query)) if query else None
            if sanitized is not None and sanitized.clean != self._query:
                # A host that hands prefetch a query it never gave on_turn_start
                # still gets a pack ranked for what the user just said.
                self._query_sanitized = sanitized
                self._query = sanitized.clean
                self._pack = self.render_pack()
            self._served_pack, self._served_count = self._pack, self._pack_count
            self._served_has_memory = self._pack_has_memory
            if self._pack_digest_evaluated:
                # This serve carried the digest, or found nothing to say: the
                # session's later packs never repeat it.
                if self._pack_digest and not self._shared_surface and self._digest_window is not None:
                    # What it reported stays reported, whoever starts next. A
                    # shared surface's digest counted only its own lens, so it
                    # marks nothing.
                    until = self._digest_window[1]
                    self._safely("session_marks", session_close_path(self._omh_home), lambda: write_reported_through(self._omh_home, until=until))
                self._digest_pending, self._pack_digest_evaluated, self._pack_digest = False, False, ""
            # The failures carried are the ones swallowed BEFORE this serve; a
            # failure writing this very receipt shows on the next one.
            self._served_receipt = (
                mark_prefetch_receipt_returned(
                    self._prepared_receipt,
                    write_failures_count=self._write_failure_count,
                    last_write_failure=self._write_failures[-1] if self._write_failures else None,
                )
                if self._prepared_receipt is not None
                else None
            )
            if self._served_receipt is not None:
                payload = json.dumps(self._served_receipt, ensure_ascii=False, sort_keys=True)
                receipt_path = prefetch_receipt_path(self._omh_home)
                self._safely("prefetch_receipt", receipt_path, lambda: _write_text(receipt_path, payload))
            # Serving the pack is what makes the reminder an ask -- and only a pack
            # that actually carries the line counts, never a prepared reminder
            # whose pack was blanked. The ledger line goes through `_safely` like
            # the receipt: a home that cannot be written costs the cadence, never
            # the turn. It writes the ledger and nothing else -- no record is
            # touched by a reminder.
            self._served_reminder = (
                self._prepared_reminder
                if self._prepared_reminder is not None and render_open_reminder(self._prepared_reminder) in self._served_pack
                else None
            )
            if self._served_reminder is not None and not self._reminder_recorded:
                self._reminder_recorded = True
                record_id = str(self._served_reminder.get("record_id", ""))
                self._safely(
                    "open_reminder",
                    open_reminders_path(self._omh_home),
                    lambda: mark_open_reminder_asked(self._omh_home, record_id, asked_at=_utc_now()),
                )
            if self._prepared_record_ids and not self._served_recorded:
                self._served_recorded = True
                self._record_served(self._prepared_record_ids)
            return self._pack

    def _record_served(self, record_ids: tuple[str, ...]) -> None:
        """One serve per record, in the home that holds it; and the ids this session has now seen."""
        stamp = _utc_now()
        homes = self._record_homes()
        by_home: dict[Path, list[str]] = {}
        for record_id in record_ids:
            home = next((home for home in homes if (home / "memory" / "records" / f"{record_id}.json").is_file()), homes[-1])
            by_home.setdefault(home, []).append(record_id)
        for home, ids in by_home.items():
            self._safely("served_usage", home / "memory" / "served.json", lambda home=home, ids=ids: record_served(home, ids, now=stamp))
        if self._session_id:
            session_id = self._session_id
            self._safely(
                "session_lens",
                session_lens_path(self._omh_home, session_id),
                lambda: note_session_records(self._omh_home, session_id, "seen", record_ids),
            )

    def _publish_lens(self, *, reset: bool, initializing: bool = False, refresh: bool = False) -> None:
        """Publish this session's confinement for `omh_memory`, which cannot see the provider.

        The tool reads it back by session id (`memory_session_lens`); without
        it the tool treats the session as a shared surface with no writes.
        Rewritten at a session start, when an input changed, at each turn
        start (``refresh``, which keeps ``published_at`` current so a successor
        never takes this lens for an abandoned one), and whenever the lens on
        disk is missing or another provider instance wrote it. Over another
        instance's live lens this one may only tighten: when that lens withholds
        more, this provider adopts its class and stays a guest under the id.
        """
        if not self._session_id:
            return
        session_id = self._session_id
        path = session_lens_path(self._omh_home, session_id)
        lens = {
            "surface_class": self._surface_class,
            "shared_surface": self._shared_surface,
            "writes_enabled": self._writes_enabled,
            "principal_context": self._principal_context,
            "channel_scope": self._channel_scope if self._surface_class == SURFACE_CHANNEL else None,
            "homes": [str(home) for home in self._record_homes()],
            "project_identity": resolve_project_identity(self._project_cwd).identity if self._project_cwd is not None else "",
            "executor_target": PREFETCH_EXECUTOR_TARGET,
        }
        looser_foreign: dict[str, Any] | None = None
        if not reset:
            on_disk = read_session_lens(self._omh_home, session_id)
            mine = on_disk is not None and on_disk.get("instance") == self._instance
            if mine and lens == self._published_lens and not refresh:
                return
            if on_disk is not None and not mine and (self._guest or self._withholds_less_than(on_disk)):
                # A guest stays one under this id: having adopted the owner's
                # class it now matches it, and writing would take the lens over
                # and withdraw it at this provider's shutdown.
                self._adopt(on_disk)
                return
            if on_disk is not None and not mine and lens_surface_class(on_disk) != self._surface_class:
                looser_foreign = on_disk
        stale_before = datetime.now(timezone.utc) - timedelta(hours=SESSION_LENS_STALE_HOURS) if initializing else None
        published: dict[str, Any] = {}
        self._safely(
            "session_lens",
            path,
            lambda: published.update(
                publish_session_lens(
                    self._omh_home,
                    session_id,
                    {**lens, "published_at": _utc_now()},
                    reset=reset,
                    instance=self._instance,
                    stale_before=stale_before,
                )
            ),
        )
        if published and published.get("instance") != self._instance:
            # A guest under another provider's session: a hygiene or
            # `/compress` agent Hermes loads as `cli` for a gateway session.
            self._adopt(published)
            self._published_lens = None
            return
        # A swallowed write leaves the class where it was: it never loosens.
        self._published_lens = lens if published else None
        if not published and looser_foreign is not None:
            # The reclaim failed and a looser lens would keep answering the
            # tool: remove it (only if it is still that one), so the session
            # reads as unbound -- no writes, nothing recalled -- until a write
            # succeeds.
            foreign_instance = str(looser_foreign.get("instance", "") or "")
            self._safely(
                "session_lens",
                path,
                lambda: withdraw_session_lens(self._omh_home, session_id, instance=foreign_instance),
            )

    def _observe_lens(self) -> None:
        """Re-read the lens before handing anything out; a tighter foreign one narrows this session.

        A tighter provider can take the lens between this provider's turns --
        the loose-first ordering -- so a render or a pre-compress hand-off
        reads what the tool would read before it decides what to include.
        """
        if not self._session_id:
            return
        on_disk = read_session_lens(self._omh_home, self._session_id)
        if on_disk is not None and on_disk.get("instance") != self._instance and self._withholds_less_than(on_disk):
            self._adopt(on_disk)

    def _withholds_less_than(self, lens: dict[str, Any]) -> bool:
        """True when ``lens`` withholds something this session's current class does not.

        That is a tighter class, or one that withholds different things (a DM
        and a channel), whose meet is tighter than both.
        """
        return tighter_surface_class(lens_surface_class(lens), self._surface_class) != self._surface_class

    def _adopt(self, lens: dict[str, Any]) -> None:
        """Become a guest under another instance's lens, taking its class if it is tighter."""
        self._guest = True
        self._tighten_to(lens_surface_class(lens))

    def _tighten_to(self, surface_class: str) -> None:
        """Take on a class that withholds more; never one that withholds less. Sticky for this id.

        A DM's principal and a channel's scope belong to the provider that
        verified them, so under another instance's direct or channel lens this
        provider is a shared surface: it holds no binding of its own there.
        """
        if surface_class in BOUND_SURFACE_CLASSES and surface_class != self._session_class:
            surface_class = SURFACE_SHARED
        self._foreign_floor = surface_class if self._foreign_floor is None else tighter_surface_class(self._foreign_floor, surface_class)
        self._settle_class()

    def _settle_class(self) -> None:
        """The class this session id is held to: its own, narrowed by the tightest foreign lens it met."""
        surface_class = self._session_class if self._foreign_floor is None else tighter_surface_class(self._session_class, self._foreign_floor)
        self._surface_class, self._tightened_by_foreign_lens = surface_class, surface_class != self._session_class
        self._shared_surface, self._writes_enabled = surface_flags(surface_class)
        if self._shared_surface and surface_class != SURFACE_DIRECT:
            self._principal_context = None

    def _restore_declared_class(self) -> None:
        """A new session id starts from the class `initialize` decided; a tightening belonged to the old id."""
        self._guest = False
        self._session_class, self._foreign_floor = self._declared_class, None
        self._settle_class()
        # A DM's principal names its session; bind one for the new id.
        self._bind_conversation()

    def _messenger_class(self) -> str:
        """The class of the verified conversation as Hermes authorizes it right now; shared when unverifiable."""
        conversation = self._conversation
        if conversation is None:
            return SURFACE_SHARED
        if conversation.kind == CHANNEL:
            return SURFACE_CHANNEL if self._channel_scope is not None else SURFACE_SHARED
        if self._authorization is not None and self._authorization.owner(conversation):
            return SURFACE_OWNER_DIRECT
        return SURFACE_DIRECT

    def _bind_conversation(self) -> None:
        """This turn's class for a verified messenger conversation, and the principal a DM binds.

        Re-derived at every turn start, so a second person paired since the
        last turn ends the owner's DM at the next one, and again whenever the
        session id moves, by the same turn's author. A turn a bot wrote, or
        one whose author is not the DM partner, is shared for that turn. An
        absent author is the partner: a verified 1:1 DM has only two parties,
        and the bot's own messages do not start turns.
        """
        conversation = self._conversation
        if conversation is None:
            return
        author_id, author_is_bot = self._turn_author
        surface_class = self._messenger_class()
        if author_is_bot or (
            conversation.kind == DIRECT and author_id and not same_person(conversation.platform, author_id, conversation.partner, self._hermes_home)
        ):
            surface_class = SURFACE_SHARED
        self._session_class = surface_class
        self._settle_class()
        self._principal_context = self._messenger_principal() if self._surface_class == SURFACE_DIRECT else None
        if self._surface_class == SURFACE_DIRECT and self._principal_context is None:
            # No principal could be derived: a DM bound to nobody is shared.
            self._session_class = SURFACE_SHARED
            self._settle_class()

    def _messenger_principal(self) -> dict[str, object] | None:
        """The DM partner's principal context for this session and turn; None when it cannot be derived."""
        conversation = self._conversation
        if conversation is None or conversation.kind != DIRECT:
            return None
        try:
            return build_principal_context(
                self._omh_home,
                profile_ref=self._messenger_profile,
                surface_ref=conversation.platform,
                session_ref=self._session_id,
                turn_ref=self._turn_ref or "turn_0",
                actor_kind="human",
                host_identity=principal_identity(conversation, self._hermes_home),
                identity_evidence_refs=["hermes_gateway_direct_message"],
            )
        except (OSError, PrincipalContractError):
            return None

    def _derive_channel_scope(self, conversation: MessengerConversation, *, channel_identity: str | None = None) -> dict[str, str] | None:
        """One scope per channel; Discord auto-created threads use their parent channel."""
        try:
            ref = derive_channel_ref(self._omh_home, profile_ref=self._messenger_profile, surface_ref=conversation.platform, channel_identity=channel_identity or conversation.chat_id)
        except (OSError, PrincipalContractError):
            return None
        return {"kind": "channel", "ref": ref}

    def _digest_withheld(self) -> bool:
        """A messenger session serves the digest only while it is the owner's DM."""
        return self._conversation is not None and self._surface_class not in OWNER_SURFACE_CLASSES

    @property
    def _console_provider(self) -> bool:
        """The session's own console provider, the one allowed to withdraw a lens an earlier release wrote."""
        return self._declared_class == SURFACE_OPERATOR_CONSOLE

    @property
    def _attended(self) -> bool:
        """An operator console somebody is at, or the owner's own DM.

        Only there are the open-record reminder and the consolidation brief
        served, the brief raised, and the dreaming counters moved. A shared
        surface or a background run has no operator to answer them. A Kanban
        worker reads as a console (#2088 relies on records in its turns), but
        runs unattended: an ask recorded there would defer the operator's real
        one, and the brief would ask it to remove Hermes entries. The owner's
        DM is the operator at another keyboard: the brief's demote rows quote
        the owner's own Hermes memory, to the owner. A guest under another
        provider's lens is a hygiene or `/compress` agent nobody is at.
        """
        return self._surface_class in OWNER_SURFACE_CLASSES and not self._unattended and not self._guest

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
        # Hermes runs this on its memory-sync worker thread while the next
        # turn's `on_turn_start`/`prefetch` run on the main thread; the lock
        # keeps one render's text from being served with another's count and
        # receipt.
        with self._render_lock:
            if principal_context is not None and self._conversation is None:
                self._principal_context = parse_principal_context(
                    principal_context,
                    expected_profile=self._profile_ref,
                    expected_session=self._session_id,
                    expected_turn=self._turn_ref,
                )
            self._query_sanitized = sanitize_memory_query(str(query or ""))
            self._query = self._query_sanitized.clean
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

    def latest_open_reminder(self) -> dict[str, object] | None:
        """The `omh reminder:` the LAST prefetch asked about an open record; None otherwise.

        Hermes' ``RecallStatus`` carries a label, a count and a glyph and
        nothing else, so the recall line cannot say a question was asked.
        This accessor and the receipt's ``reminder`` field are where the ask
        is disclosed: record id, age, and the bounded summary the line used.
        Like the receipt, it reports only what was served, never a queued
        re-render.
        """
        return dict(self._served_reminder) if self._served_reminder is not None else None

    def shutdown(self) -> None:
        """Hermes is closing. Last chance to leave a brief behind."""
        self._evaluate_if_due("shutdown")
        self._record_session_close()
        if self._session_id:
            session_id = self._session_id
            self._safely(
                "session_lens",
                session_lens_path(self._omh_home, session_id),
                lambda: withdraw_session_lens(self._omh_home, session_id, instance=self._instance, unowned=self._console_provider),
            )
        self._published_lens = None
        self._pack, self._pack_count, self._pack_has_memory = "", 0, False
        self._served_pack, self._served_count, self._served_has_memory = "", 0, False
        self._prepared_receipt, self._served_receipt = None, None
        self._prepared_reminder, self._served_reminder, self._reminder_recorded = None, None, False
        self._prepared_record_ids, self._served_recorded = (), False
        self._digest_window, self._digest_pending, self._pack_digest_evaluated, self._pack_digest = None, False, False, ""
        self._principal_context = None
        self._profile_ref = ""
        self._turn_ref = ""
        self._turn_author = ("", False)

    # -- Optional hooks -----------------------------------------------------

    def on_turn_start(self, turn_number: int, message: str = "", **kwargs: Any) -> None:
        self._turn_ref = f"turn_{turn_number}"
        if self._conversation is not None:
            # Hermes passes the turn's author (`agent/turn_context.py`,
            # `_memory_turn_start_and_prefetch`): this turn is judged by it.
            self._turn_author = (str(kwargs.get("author_id") or "").strip(), bool(kwargs.get("author_is_bot", False)))
            self._bind_conversation()
        else:
            self._principal_context = parse_principal_context(
                kwargs.get("principal_context"),
                expected_profile=self._profile_ref,
                expected_session=self._session_id,
                expected_turn=self._turn_ref,
            )
        self._publish_lens(reset=False, refresh=True)
        # Hermes calls this hook and then `prefetch` inside the SAME turn;
        # `queue_prefetch` only runs after the turn ends. The pack is therefore
        # re-rendered here, under this turn's principal and for this turn's
        # message, rather than blanked: blanking it isolated the previous
        # principal's pack correctly and then served nothing at all, every
        # turn, from 2026-09-12 until the hook order was checked. Re-rendering
        # keeps the isolation (a new lens never sees the old pack) and makes
        # the current message, not the previous turn's, the recall query.
        with self._render_lock:
            # Blank first, render last: if the render raises (the host
            # suppresses it), prefetch finds nothing to serve rather than the
            # previous turn's pack under this turn's query and receipt.
            self._served_pack, self._served_count, self._served_has_memory = "", 0, False
            self._served_receipt = None
            self._served_reminder = None
            self._pack, self._pack_count, self._pack_has_memory = "", 0, False
            self._prepared_receipt = None
            self._prepared_reminder, self._reminder_recorded = None, False
            self._prepared_record_ids, self._served_recorded = (), False
            self._pack_digest_evaluated, self._pack_digest = False, ""
            self._query_sanitized = sanitize_memory_query(str(message or ""))
            self._query = self._query_sanitized.clean
            if self._attended:
                # The counters move before the render so a turn is counted
                # whatever the render does, and a brief that falls due on this
                # turn rides in this turn's pack rather than the next one's.
                self._mutate_state(record_turn)
                self._evaluate_if_due("turn")
            self._pack = self.render_pack()

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        rewound: bool = False,
        **kwargs: Any,
    ) -> None:
        """Hermes rotated the session id without teardown; move the published lens with it.

        Compression, `/new`, `/reset`, `/resume` and `/branch` reassign
        ``session_id`` mid-process, and every later tool call carries the new
        one, so a lens left under the old id makes the tool fail closed for the
        rest of the conversation. The old lens is withdrawn and a new one
        published. A compression (``reset`` false) is the same conversation, so
        the records it saw and confirmed carry over; a genuinely new
        conversation starts empty. ``rewound`` keeps the id: nothing to move.

        Hermes' ``reset`` (``/new``, ``/reset``) also starts this session's
        digest and records the old one's close. It arrives from Hermes' worker
        after ``on_session_end``, often after the next turn's ``prefetch``
        already adopted the new id; then the lens was moved there and only the
        digest and the close are left to do here.
        """
        new_id = str(new_session_id or "")
        if rewound or not new_id:
            return
        with self._render_lock:
            if new_id != self._session_id:
                self._rebind_session(new_id, reset=reset)
            elif not reset:
                return
            if reset:
                # Counted from the close on disk first, then this close is
                # recorded: with history Hermes already closed it in
                # `on_session_end`, so the old conversation's writes stay out.
                self._start_session_digest(initializing=False)
                self._record_session_close()

    def _rebind_session(self, new_id: str, *, reset: bool) -> None:
        """Withdraw the old lens and publish one under ``new_id``; carry its lists unless ``reset``."""
        old_id = self._session_id
        carried = None if reset or not old_id else read_session_lens(self._omh_home, old_id)
        if old_id:
            self._safely(
                "session_lens",
                session_lens_path(self._omh_home, old_id),
                lambda: withdraw_session_lens(self._omh_home, old_id, instance=self._instance, unowned=self._console_provider),
            )
        self._session_id = new_id
        # The principal context was bound to the old session; the next
        # turn supplies one for the new id.
        self._principal_context = None
        self._published_lens = None
        self._restore_declared_class()
        self._publish_lens(reset=True)
        if carried:
            for key in ("seen", "confirmed"):
                ids = [str(item) for item in carried.get(key, [])]
                self._safely(
                    "session_lens",
                    session_lens_path(self._omh_home, new_id),
                    lambda key=key, ids=ids: note_session_records(self._omh_home, new_id, key, ids),
                )

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

        The return value is the system blocks and nothing else. Hermes'
        compressor JSON-encodes it and tells the summarizer to decode it "only
        as source material to preserve in the summary, not as instructions"
        (``agent/context_compressor.py``, ``_memory_provider_section``), so a
        request appended here would argue with the host's own rule. The facts
        are reached the other way: Hermes' summary template already keeps the
        user's preferences, constraints and decisions under a fixed heading,
        and the compaction brief served next turn points the model at it. OMH
        stays a v1 best-effort provider (no ``pre_compress_checkpoint_api_version``),
        so this text never takes part in a checkpoint decision.
        """
        self._observe_lens()
        if self._attended:
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
        # The journal is provenance and records every writing context. The
        # counters and the brief belong to the attended console that is served
        # it: a gateway write must not retire the operator's brief.
        if not self._attended:
            return
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
        # Hermes also calls this at a compression and a gateway soft-evict, mid
        # conversation; a console's later close stamp only narrows the next
        # digest, and a gateway records none.
        self._record_session_close()

    # -- Deterministic work, exposed for the CLI and for tests --------------

    def _evaluate_if_due(self, trigger: str, *, messages_at_risk: int = 0) -> dict[str, object] | None:
        """Weigh the triggers at one of the moments memory can be lost.

        Every trigger point calls this: each turn, compaction, session end,
        shutdown, and the start of the next session. Deferring the decision to
        session end alone -- which is what this did first -- means a laptop that
        closes mid-session writes nothing at all, and a turn interval that comes
        due at turn 5 waits until whenever the session happens to stop.
        """
        if not self._attended:
            return None
        return self.consolidation_due(trigger=trigger, messages_at_risk=messages_at_risk)

    def render_pack(self, *, now: datetime | None = None) -> str:
        """System blocks in full, reference blocks by label only, then the
        reviewed records the canonical selector chose for the queued query.

        The operator's blocks go to an operator console only, and the
        open-record reminder and the consolidation brief to an attended one
        (`_attended`). A shared surface is a chat other people read, and a
        background run or a Kanban worker has nobody to ask; the brief's
        demote rows even quote USER.md and MEMORY.md. Records and the digest
        keep their own lens rules there. The whole pack fits
        `PACK_BUDGET_CHARS` (`fit_prefetch_pack`), and the receipt names only
        what the returned text carries.
        """
        self._observe_lens()
        # None is a bound absence, not permission to inspect the process cwd.
        self._project_resolution = (
            resolve_project_identity(self._project_cwd) if self._project_cwd is not None
            else ProjectIdentityResolution(diagnostics=("outside_repository",))
        )
        moment = now or datetime.now(timezone.utc)
        console = self._surface_class in OWNER_SURFACE_CLASSES
        blocks = read_memory_blocks(self._omh_home) if console else ()
        selection = self._block_selection(blocks=blocks, now=moment)
        system_blocks = tuple(block for block in blocks if block.tier == SYSTEM_TIER)
        reference_blocks = tuple(block for block in blocks if block.tier == REFERENCE_TIER)
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
            required_scope_kinds=prefetch_required_scope_kinds(self._project_resolution.identity),
        )
        # The reminder asks about the oldest open record whose review deadline
        # passed and whose last ask is older than `open_ask_days`, one line per
        # pack, inside the same explicit scope allowlist the selector used. It
        # is a question, not a memory: it never moves the recall count, and it
        # is asked only on a console, never in a group chat that would be asked
        # to settle a question that belongs to the operator. Selecting here
        # only prepares it; `prefetch` is what turns it into an ask.
        self._prepared_reminder = None
        self._reminder_recorded = False
        self._prepared_record_ids, self._served_recorded = (), False
        reminder = (
            select_open_reminder(
                snapshot.records,
                read_open_reminders(self._record_homes()),
                now=moment,
                allowed_scopes=prepared.selection.scope_allowlist,
                eligible_record_ids=_askable_record_ids(prepared.selection.pack),
            )
            if self._attended
            else None
        )
        # The brief is a request, not a memory: it is served so the model can
        # consolidate in this turn, and it never moves the recall count. Only
        # this profile's brief, and none at all when its mode is `off`.
        brief = (
            read_latest_consolidation(self._omh_home, self._profile_home, mode=configured_dreaming_mode(self._profile_home))
            if self._attended
            else None
        )
        # A status, not a memory either: counts only, and never the recall count.
        # Withheld for a turn that is not the owner's DM: it stays pending,
        # never spent where it cannot be shown.
        digest_withheld = self._digest_withheld()
        digest = "" if digest_withheld else self._session_digest_section()
        fitted = fit_prefetch_pack(
            render_system=lambda budget: render_memory_blocks_within(system_blocks, total_chars=budget, evaluations=selection.evaluations),
            render_index=lambda budget: render_block_index(reference_blocks, evaluations=selection.evaluations, budget_chars=budget),
            render_brief=lambda rows: render_consolidation_brief(brief, hermes_home=self._hermes_home, max_demote_rows=rows),
            records=prepared.section.text,
            reminder=render_open_reminder(reminder) if reminder is not None else "",
            digest=digest,
        )
        pack = fitted.text
        # The count is what the renderer emitted, never what selection chose.
        self._pack_count = fitted.block_count + len(prepared.section.rendered)
        self._pack_has_memory = bool(fitted.system or fitted.index or fitted.records)
        self._prepared_reminder = reminder if fitted.reminder else None
        self._prepared_receipt = build_prefetch_receipt(
            prepared,
            session_id=self._session_id,
            home_digests=snapshot.home_digests,
            rendered_block_count=fitted.block_count,
            project_resolution=self._project_resolution,
            reminder=self._prepared_reminder,
            unreadable=snapshot.unreadable,
            store_read_error=snapshot.store_read_error,
            pack_chars=len(pack),
            surface_class=self._surface_class,
            tightened_by_foreign_lens=self._tightened_by_foreign_lens,
            query_sanitized=self._query_sanitized,
        )
        # Last, so a render that raised leaves no ids beside the previous pack.
        self._prepared_record_ids = tuple(str(item["record_id"]) for item in prepared.section.rendered)
        # A digest the budget left out stays pending for a later render.
        self._pack_digest_evaluated, self._pack_digest = (
            not digest_withheld and self._digest_pending and fitted.digest == digest,
            fitted.digest,
        )
        return pack

    def _start_session_digest(self, *, initializing: bool) -> None:
        """Fix this session's digest window, before it serves or writes anything.

        The window ends at this moment, floored to its second -- record and
        journal stamps are whole seconds, so a write this session makes in its
        first second can never fall inside -- and starts at the later of the
        last recorded close and the end of the last digest served in this OMH
        home (`digest_window_start`). A cron or subagent context has no user
        to tell and gets none.
        """
        self._digest_window, self._digest_pending, self._pack_digest_evaluated, self._pack_digest = None, False, False, ""
        if not self._writes_enabled or self._unattended or self._digest_withheld():
            # A Kanban worker has nobody to tell either, and serving the digest
            # would mark it reported for the operator's next session. A
            # messenger DM of anyone but the owner, or a group, gets none.
            return

        def window() -> tuple[datetime, datetime] | None:
            until = datetime.now(timezone.utc).replace(microsecond=0)
            since = digest_window_start(self._omh_home, until=until, initializing_session=self._session_id if initializing else "")
            return None if since is None else (since, until)

        self._digest_window = self._guard_digest(window, None)
        self._digest_pending = self._digest_window is not None

    def _session_digest_section(self) -> str:
        """The digest for this render while it is pending; "" otherwise or when nothing changed.

        Counted per render, so a shared surface is judged by the lens this
        render was made under. The window was fixed at the session start.
        """
        if not self._digest_pending or self._digest_window is None:
            return ""
        since, until = self._digest_window

        def section() -> str:
            # Another session may have served its digest since this window was
            # fixed; what it reported is not reported again.
            start = clamp_to_reported(self._omh_home, since, now=datetime.now(timezone.utc))
            if start is None or start >= until:
                return ""
            counts, journal_at_cap = session_digest_counts(
                self._record_homes(),
                self._omh_home,
                since=start,
                until=until,
                journal_limit=JOURNAL_LIMIT,
                in_lens=self._recall_lens() if self._shared_surface else None,
            )
            return render_session_digest(counts, since=start, shared=self._shared_surface, journal_at_cap=journal_at_cap)

        return self._guard_digest(section, "")

    def _recall_lens(self):
        """The gate prefetch and `omh_memory` recall apply, in their order: principal, scope, perspective.

        Mirrors `memory_tool._in_session_scope` over this render's allowlist
        and principal context; lifecycle state is not a lens gate.
        """
        scopes, status = resolve_scope_allowlist(
            self._prefetch_scopes(), required_scope_kinds=prefetch_required_scope_kinds(self._project_resolution.identity)
        )
        principal, shared = self._principal_context, self._shared_surface
        channels = tuple(scope for scope in scopes if scope["kind"] == "channel")

        def admits(record: dict[str, Any]) -> bool:
            return (
                status == "resolved"
                and bool(principal_recall_decision(record, principal, shared_surface=shared, channel_scopes=channels)["allowed"])
                and record.get("scope") in scopes
                and _record_perspective_matches(record, observer=None, observed=PREFETCH_EXECUTOR_TARGET)
            )

        return admits

    def _guard_digest(self, compute, fallback):
        """A digest fault costs the digest, never the hook that asked for it.

        `initialize`, a session switch and every render reach the digest;
        whatever its stores hold, none of them may fail because of it. The fault
        is recorded like a swallowed write -- op `session_digest` and the error
        class -- so the next receipt reports it, and the session gets no digest.
        """
        try:
            return compute()
        except Exception as error:  # noqa: BLE001 - classified in tests/test_broad_exception_policy.py
            self._digest_window, self._digest_pending = None, False
            self._write_failure_count += 1
            self._write_failures.append({"op": "session_digest", "path": "memory_digest", "error": type(error).__name__})
            del self._write_failures[:-WRITE_FAILURE_LIMIT]
            return fallback

    def _record_session_close(self) -> None:
        """Record that a session closed here, for the next session's digest window. Attended consoles only.

        The window is the operator's: a gateway session or a Kanban worker that
        closed would move it past changes nobody at the console was told about.
        """
        if not self._attended:
            return
        path = session_close_path(self._omh_home)
        self._safely("session_close", path, lambda: write_session_close(self._omh_home, at=datetime.now(timezone.utc)))

    def _record_homes(self) -> tuple[Path, ...]:
        """The project store first when there is one, then the user store."""
        if self._project_home is not None and self._project_home != self._omh_home:
            return (self._project_home, self._omh_home)
        return (self._omh_home,)

    def _prefetch_scopes(self) -> list[dict[str, str]]:
        """One stable project label, or an unresolved, fail-closed allowlist; a channel names its own scope."""
        identity = self._project_resolution.identity
        principal = str(self._principal_context.get("principal", "")) if self._principal_context is not None else ""
        channel = self._channel_scope["ref"] if self._surface_class == SURFACE_CHANNEL and self._channel_scope is not None else ""
        return prefetch_scope_allowlist(
            project_identity=identity,
            session_id=self._session_id,
            principal_ref=principal,
            include_legacy_personal=not self._shared_surface,
            channel_ref=channel,
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
        weighed, not only the ones that fired. The counters weighed and the
        brief written are this profile's; under its `off` mode nothing is due.
        """
        state = read_dreaming_state(self._omh_home, self._profile_home)
        mode = configured_dreaming_mode(self._profile_home)
        moment = now or datetime.now(timezone.utc)
        plan, reason_kwargs, record_expiry, readings = self._evaluation_inputs(trigger, now=moment)
        blocks = () if self._shared_surface else read_memory_blocks(self._omh_home)
        selection = self._block_selection(blocks=blocks, now=moment)
        reasons = self._with_replay_reminders(consolidation_reasons(state, mode=mode, **reason_kwargs), selection, mode=mode)
        handoff = build_consolidation_handoff(
            reasons,
            block_summaries=[self._block_summary(block, selection.evaluations[block.block_id]) for block in blocks],
            eviction_plan=plan,
            record_expiry=record_expiry,
            mode=mode,
            trigger=trigger,
            messages_at_risk=messages_at_risk,
            session_id=self._session_id,
            # Only a brief that actually fires was raised; stamping the not-due
            # inspection object gave it a raise time for a raise that never was.
            raised_at=_utc_now() if reasons else "",
            demotion_rows=(
                self._demotion_rows(readings)
                if any(reason.startswith("headroom_below_floor") for reason in reasons)
                else []
            ),
            hermes_files=[
                {"label": item.label, "headroom_chars": item.headroom_chars, "floor": headroom_floor_for_cap(item.cap)}
                for item in readings
                if item.exists
            ],
        )
        if reasons:
            self._write_handoff(handoff)
            # Cleared on the counters as they stand under the lock, not on the
            # copy read above: the clear zeroes the counters either way, and
            # writing the stale copy back would discard what a concurrent
            # session wrote in between without saying so.
            cleared_at = _utc_now()
            self._mutate_state(lambda current: clear_after_consolidation(current, at=cleared_at, reasons=reasons))
            self._say(consolidation_status_line(trigger, reasons))
        else:
            # Suppression keeps an unchanged `expiring_records:N` from re-firing,
            # which is right -- but the breakdown behind that N can still move
            # (a record crossing from expiring into expired keeps N identical).
            # The persisted brief is refreshed in place: no new notification,
            # no suppression reset, no counter mutation.
            self._refresh_brief_record_expiry(record_expiry, mode=mode)
        return handoff

    def _evaluation_inputs(
        self,
        trigger: str,
        *,
        count_expiry: bool = True,
        now: datetime | None = None,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, int], tuple[HermesMemoryFile, ...]]:
        """The eviction plan, reason kwargs, and expiry counts for one evaluation.

        The expiry scan is one glob plus a JSON parse per approved record and
        runs at most once per evaluation. The retirement standing-check passes
        ``count_expiry=False``: expiry is a standing condition only retirement
        itself can clear, so counting it there would both waste the scan and
        block `_retire_stale_brief` forever.
        """
        moment = now or datetime.now(timezone.utc)
        readings = self._hermes_snapshot()
        reading = next((item for item in readings if item.label == "MEMORY.md" and item.exists), None)
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
                "headroom_floor_chars": headroom_floor_for_cap(reading.cap) if reading is not None else 0,
                "file_headrooms": {
                    item.label: (item.headroom_chars, headroom_floor_for_cap(item.cap))
                    for item in readings
                    if item.label != "MEMORY.md" and item.exists
                },
                "duplicate_count": len(plan.get("duplicate_clusters", []) or []),
                "expiring_count": record_expiry["expired"] + record_expiry["expiring_soon"],
                "session_ending": trigger in _SESSION_ENDING_TRIGGERS,
            },
            record_expiry,
            readings,
        )

    def _refresh_brief_record_expiry(self, record_expiry: dict[str, int], *, mode: str) -> None:
        """Keep the persisted due brief's expiry breakdown current, silently."""
        brief = read_latest_consolidation(self._omh_home, self._profile_home, mode=mode)
        if not brief or not brief.get("due") or brief.get("record_expiry") == record_expiry:
            return
        updated = dict(brief)
        updated["record_expiry"] = dict(record_expiry)
        payload = json.dumps(updated, ensure_ascii=False, sort_keys=True)
        path = consolidation_path(self._omh_home, self._profile_home)
        self._safely("consolidation_brief", path, lambda: _write_text(path, payload))

    def _standing_reasons(self) -> list[str]:
        """Is anything still true at all? Read-only, suppression bypassed.

        A suppressed standing condition returns [] from the default evaluation
        while remaining true; retirement must see through that, or it would
        clear a notice whose fact had not cleared.
        """
        state = read_dreaming_state(self._omh_home, self._profile_home)
        _, reason_kwargs, _record_expiry, _readings = self._evaluation_inputs("memory_write", count_expiry=False)
        blocks = () if self._shared_surface else read_memory_blocks(self._omh_home)
        selection = self._block_selection(blocks=blocks)
        # The mode is not asked here: whether a condition still holds is a fact
        # about the profile, and under `off` there is no brief to retire.
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
        brief = read_latest_consolidation(self._omh_home, self._profile_home)
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
        *,
        mode: str,
    ) -> list[str]:
        # Replay exclusions are standing reminder evidence, not another
        # consolidation trigger subject to the normal last-reasons suppression.
        # A manual inspection must still report them when no ordinary trigger
        # fired; the selection is read-only and evaluated at the same instant
        # as the rest of this consolidation decision. Under `off` none are
        # added: `consolidation_reasons` returned nothing for that mode, and a
        # replay reminder would still raise a brief the profile turned off.
        replay = self._replay_reminder_reasons(selection) if mode != "off" else []
        return [*reasons, *replay]

    def _demotion_rows(self, snapshot: tuple[HermesMemoryFile, ...]) -> list[dict[str, object]]:
        """The Hermes entries a nearly-full brief asks the model to demote, metadata only.

        Every Hermes memory file below the headroom floor contributes, because
        a USER.md row is what clears a USER.md reason and a MEMORY.md row would
        not. Largest first across the files, because the first move should free
        the most. Rows the model's `demote` would refuse -- redacted, over the
        summary bound, a pending, rejected or unknown candidate for exactly
        that entry, or an entry held by both files (one digest, two files) --
        are left out, or the same refused row would ride every brief. Whether
        an entry is already held is not decided here: `demote` decides it live.

        A failure costs the rows, never the brief: it is recorded like a
        swallowed write and the brief goes out without them.
        """
        label = "memories"
        try:
            readings = {item.label: item for item in snapshot}
            parked = {
                str(candidate.get("source_ref", ""))
                for candidate in read_project_memory_candidates(self._omh_home)
                if str(candidate.get("status", "")) != "approved"
            }
            offered: list[tuple[str, str]] = []
            for label, reading in readings.items():
                if not reading.exists or reading.headroom_chars > headroom_floor_for_cap(reading.cap):
                    continue
                elsewhere = {item for other, held in readings.items() if other != label for item in held.entries}
                offered.extend(
                    (label, item)
                    for item in dict.fromkeys(reading.entries)
                    if item not in elsewhere and not demotion_refusal_reason(item) and demotion_origin_ref(label, item) not in parked
                )
            offered.sort(key=lambda pair: -len(pair[1]))
            return [
                {"kind": "demote", "file": label, "sha12": entry_digest(item)[:12], "chars": len(item)}
                for label, item in offered[:DEMOTION_BRIEF_MAX_ROWS]
            ]
        except Exception as error:
            self._write_failure_count += 1
            self._write_failures.append({"op": "demotion_rows", "path": label, "error": type(error).__name__})
            del self._write_failures[:-WRITE_FAILURE_LIMIT]
            return []

    def _hermes_snapshot(self) -> tuple[HermesMemoryFile, ...]:
        """Every Hermes memory file, read once per evaluation; empty when unreadable."""
        if self._hermes_home is None:
            return ()
        try:
            return read_hermes_memory(self._hermes_home)
        except OSError:
            return ()

    def _mutate_state(self, mutate) -> None:
        """Read-modify-write the counters under the state lock; a failure is counted."""
        self._safely(
            "dreaming_state",
            dreaming_state_path(self._omh_home, self._profile_home),
            lambda: update_dreaming_state(self._omh_home, self._profile_home, mutate),
        )

    def _claim_legacy_dreaming_state(self) -> None:
        """At a session start, claim the home-wide counters and brief an earlier release left.

        Only an attended console of a profile that is not routed claims them
        (`memory_dreaming.adopt_legacy_dreaming_files`): a single-profile host
        keeps a pending brief and its counters across the upgrade. A routed
        profile -- every profile of a multiplexed process, or one other than
        the launch profile -- cannot tell whose they were, so it leaves them
        unread rather than serve another profile's brief (#2087).
        """
        if not self._attended:
            return
        try:
            routed = runtime_paths.profile_is_routed()
        except runtime_paths.RuntimeBindingError:
            return
        if routed:
            return
        self._safely(
            "dreaming_state",
            dreaming_state_path(self._omh_home, self._profile_home),
            lambda: adopt_legacy_dreaming_files(self._omh_home, self._profile_home),
        )

    def _write_handoff(self, handoff: dict[str, object]) -> None:
        """Write this profile's latest handoff and retain the home's bounded metadata-only journal.

        The journal stays home-wide: it is a history read by evidence reports,
        never served, and each line carries the session that raised it.
        """
        payload = json.dumps(handoff, ensure_ascii=False, sort_keys=True)
        brief, journal = consolidation_path(self._omh_home, self._profile_home), self._omh_home / "memory" / "consolidation.jsonl"
        self._safely("consolidation_brief", brief, lambda: _write_text(brief, payload))
        entry = _consolidation_journal_entry(handoff)
        self._safely("consolidation_journal", journal, lambda: _append_bounded_json_line(journal, entry))

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
        removed = (metadata or {}).get("previous_content")
        if action == "remove" and isinstance(removed, str) and removed:
            # Hermes hands over the full entry its remove selected. Whether it
            # is one OMH holds intact says if a demotion's remove hit its mark;
            # absent when Hermes did not say what it removed.
            entry["removed_entry_demoted"] = self._holds_demoted_copy(target, removed)
        path = self._omh_home / "memory" / "write_journal.jsonl"
        self._safely("write_journal", path, lambda: _append_bounded_json_line(path, entry))

    def _holds_demoted_copy(self, target: str, removed: str) -> bool:
        """True when an approved OMH record is the intact demoted copy of ``removed``."""
        label = "USER.md" if str(target) == "user" else "MEMORY.md"
        origin_ref = demotion_origin_ref(label, removed.strip())
        try:
            records = read_approved_records(self._omh_home)
        except OSError:
            return False
        return any(
            str(record.get("source_ref", "")) == origin_ref and str(record.get("summary", "")) == removed.strip()
            for record in records
        )

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

    def _safely(self, op: str, path: Path, write) -> None:
        """A memory-provider write must never take down the turn that triggered it.

        Hermes calls these hooks inside a live conversation. A read-only home, a
        full disk, or a lock another session held past its deadline is a lost
        journal line -- not a failed turn -- so the failure is swallowed here
        and nowhere else in this module. Swallowed is not silent: each one is
        recorded as op, file basename and error class -- never the message,
        which can carry a path or content -- and the next served receipt
        reports the count and the latest one.
        """
        try:
            write()
        except OSError as error:
            self._write_failure_count += 1
            self._write_failures.append({"op": op, "path": path.name, "error": type(error).__name__})
            del self._write_failures[:-WRITE_FAILURE_LIMIT]


def _askable_record_ids(pack: dict[str, Any]) -> set[str]:
    """The records this pack was willing to deliver: the only ones a reminder may ask about.

    A reminder offers three answers, and two of them (`confirm`, `retire`)
    refuse a record the pack itself refuses -- superseded, expired, archived,
    principal-denied, out of lens. Asking about such a record is a question
    with no working answer, and it would still mark the ledger. So the ask
    set is what the selector delivered, plus records it held back only for
    reasons that are not about eligibility: no query overlap, overlap only on
    store-common words, and the budget cut. The reminder is not query-bound --
    an open question is open whether or not this turn's message mentions it --
    but it is eligibility-bound.
    Hidden exclusions (scope, perspective, principal) never appear in the
    pack at all, so they never appear here.
    """
    askable = {
        str(item.get("record_id", ""))
        for item in pack.get("included_records", [])
        if isinstance(item, dict)
    }
    askable.update(
        str(item.get("record_id", ""))
        for item in pack.get("excluded_records", [])
        if isinstance(item, dict)
        and str(item.get("reason", "")) in {"no_query_overlap", "common_terms_only", "over_budget"}
        and str(item.get("eligibility_reason", "")) == "eligible"
    )
    askable.discard("")
    return askable


def _write_text(path: Path, text: str) -> None:
    # Every caller writes under `<omh_home>/memory`; a link on the way is refused.
    guard_store_write(path)
    write_text_locked(path, text)


def _append_bounded_json_line(path: Path, entry: dict[str, object]) -> None:
    """Atomically retain the newest metadata-only journal entries.

    The read and the replace share one lock, so two sessions appending at
    once both keep their line instead of the later replace dropping the other.
    """
    guard_store_write(path)
    with state_file_lock(path):
        lines = _metadata_journal_lines(path)
        lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        write_text_atomic(path, "\n".join(lines[-JOURNAL_LIMIT:]) + "\n")


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
        if _metadata_journal_line(data):
            entries.append(json.dumps(data, ensure_ascii=False, sort_keys=True))
    return entries[-(JOURNAL_LIMIT - 1) :]


def _metadata_journal_line(data: object) -> bool:
    """A journal line the retention keeps: metadata only, plus the write journal's own digest.

    `_append_write_journal` writes ``content_digest``, a sha256 hex the provider
    computes and never the text. The "content" term matched it, so every append
    dropped every earlier line and the journal held only its newest entry -- a
    `removed_entry_demoted` line vanished at the next native write. The key is
    exempt only at the top level, spelled exactly, and holding 64 lowercase hex
    characters; anything else is judged like any other key.
    """
    if isinstance(data, dict):
        digest = data.get("content_digest")
        if isinstance(digest, str) and len(digest) == 64 and not set(digest) - set("0123456789abcdef"):
            data = {key: value for key, value in data.items() if key != "content_digest"}
    return _metadata_only(data)


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


@dataclass(frozen=True)
class FittedPack:
    """The sections one prefetch returns, each already closed, in pack order."""

    system: str
    block_count: int
    index: str
    records: str
    reminder: str
    digest: str
    brief: str

    @property
    def text(self) -> str:
        return "\n".join(part for part in (self.system, self.index, self.records, self.reminder, self.digest, self.brief) if part)


def fit_prefetch_pack(
    *,
    render_system: Callable[[int], tuple[str, int]],
    render_index: Callable[[int], str],
    render_brief: Callable[[int | None], str],
    records: str,
    reminder: str,
    digest: str,
    budget: int | None = None,
) -> FittedPack:
    """Every section inside one budget, so Hermes never spills the pack.

    The records, the reminder, the digest and the brief are rendered at their
    own caps, the reference index at `REFERENCE_INDEX_PACK_MAX_CHARS`, and the
    system blocks take what is left, at most `SYSTEM_BLOCKS_PACK_MAX_CHARS`.
    What gives, in order: system blocks down to the floor (or to their own
    size when smaller), then index lines, then the brief's demote rows, then
    system blocks below the floor. Each renderer returns a closed section or
    nothing, so no closing tag, no record and no `<do>` line of the brief is
    ever cut. The reminder and the digest are whole or absent; with the
    sections at their caps they always fit, so dropping them (reminder first)
    is the last resort that keeps the bound unconditional.
    """
    budget = PACK_BUDGET_CHARS if budget is None else budget
    index = render_index(REFERENCE_INDEX_PACK_MAX_CHARS)
    brief = render_brief(None)

    def rest() -> int:
        return len("\n".join(part for part in (index, records, reminder, digest, brief) if part))

    def room() -> int:
        # One separator between the system section and the rest.
        length = rest()
        return budget - length - (1 if length else 0)

    wanted = min(SYSTEM_BLOCKS_PACK_FLOOR_CHARS, len(render_system(SYSTEM_BLOCKS_PACK_MAX_CHARS)[0]))
    if room() < wanted and index:
        index = render_index(max(len(index) - (wanted - room()), 0))
    for rows in range(DEMOTION_BRIEF_MAX_ROWS - 1, -1, -1):
        if room() >= wanted or not brief:
            break
        brief = render_brief(rows)
    if rest() > budget:
        reminder = ""
    if rest() > budget:
        digest = ""
    system, block_count = render_system(max(min(SYSTEM_BLOCKS_PACK_MAX_CHARS, room()), 0))
    return FittedPack(system, block_count, index, records, reminder, digest, brief)


def render_consolidation_brief(
    brief: dict[str, Any] | None,
    *,
    hermes_home: str | Path | None = None,
    max_demote_rows: int | None = None,
) -> str:
    """The due brief as one bounded prompt section; "" when nothing is due.

    Measured before this existed: 32 briefs in seven days on one machine,
    every one written to disk, none ever read by a model -- the chat card
    notice lives on the wrapper surface, and a Hermes turn saw nothing. So
    `memory_writes_observed` stayed 0 at every consolidation. The section asks
    for the consolidation and for one line to the user, which is the only
    channel that reaches every platform Hermes speaks through.

    Demotion rows carry no entry text on disk. Each is resolved against the
    live Hermes file here, at render time, for a short preview; a row whose
    entry is gone (already removed) is dropped, and rows are the first thing
    given up when the section would exceed its budget, then the reason and
    headroom lines; the `<do>` lines and the closing tag never are.
    ``max_demote_rows`` is the pack budget asking for fewer rows.
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
    rows = _demotion_row_lines(brief.get("demotion_rows"), hermes_home)
    if max_demote_rows is not None:
        # The pack's budget asked for fewer: the rows are the brief's only part that gives.
        rows = rows[: max(max_demote_rows, 0)]
    # A per-file headroom line only for a file that has a reason or an offered
    # row: the others are not why this brief exists, and each line costs budget
    # the rows need.
    named = {
        reason.split(":")[1] if not reason.split(":")[1][:1].isdecimal() else "MEMORY.md"
        for reason in reasons
        if reason.startswith("headroom_below_floor:")
    } | {label for label in ("MEMORY.md", "USER.md") if any(row.startswith(f'  <demote file="{label}" ') for row in rows)}
    for item in brief.get("hermes_files") if isinstance(brief.get("hermes_files"), list) else []:
        if item.get("label") in named and (item.get("label") != "MEMORY.md" or not (clusters or plan.get("headroom_chars") is not None)):
            lines.append(
                f'  <hermes_memory file="{_attr(item.get("label"))}" headroom_chars="{_attr(item.get("headroom_chars"))}"'
                f' floor="{_attr(item.get("floor"))}" />'
            )
    requested = [str(item) for item in brief.get("requested_of_executor", []) if isinstance(item, str)]

    def tail_lines(rendered: list[str]) -> list[str]:
        # The demote instruction was chosen when the brief was raised; it is
        # re-chosen here from the rows actually rendered, so a section whose
        # rows were all dropped never says "for each demote row".
        chosen = [HEADROOM_TRIM_INSTRUCTION if item == HEADROOM_DEMOTE_INSTRUCTION and not rendered else item for item in requested]
        if not any(row.startswith('  <demote file="USER.md" ') for row in rendered):
            chosen = [item for item in chosen if item != HEADROOM_USER_GUARD_INSTRUCTION]
        tail = [f"  <do>{_text(item)}</do>" for item in chosen[:CONSOLIDATION_MAX_ITEMS]]
        tail.append("  <do>Then tell the user in one short line what you remembered or trimmed, or that nothing needed changing.</do>")
        tail.append("</memory_consolidation>")
        return tail

    while rows and len("\n".join([*lines, *rows, *tail_lines(rows)])) > CONSOLIDATION_RENDER_BUDGET_CHARS:
        rows.pop()
    tail = tail_lines(rows)
    # Still over: the detail lines under the opening tag give next, last first,
    # so a `<do>` line and the closing tag are never cut. The opening tag and
    # the longest tail the shipped instructions can make fit the budget
    # (tests/test_memory_pack_budget.py pins it).
    while len(lines) > 1 and len("\n".join([*lines, *rows, *tail])) > CONSOLIDATION_RENDER_BUDGET_CHARS:
        lines.pop()
    return "\n".join([*lines, *rows, *tail])


def _demotion_row_lines(value: object, hermes_home: str | Path | None) -> list[str]:
    """One `<demote>` line per row whose entry still exists."""
    rows = normalize_demotion_rows(value)
    if not rows or hermes_home is None:
        return []
    try:
        entries = {reading.label: reading.entries for reading in read_hermes_memory(hermes_home)}
    except OSError:
        return []
    lines = []
    for row in rows:
        entry = next((item for item in entries.get(str(row["file"]), ()) if entry_digest(item).startswith(str(row["sha12"]))), None)
        if entry is None:
            continue
        flat = " ".join(entry.split())
        preview = flat if len(flat) <= DEMOTION_PREVIEW_CHARS else flat[:DEMOTION_PREVIEW_CHARS] + "…"
        lines.append(
            f'  <{row["kind"]} file="{_attr(row["file"])}" entry="{row["sha12"]}" chars="{len(entry)}">{_text(preview)}</{row["kind"]}>'
        )
    return lines


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
