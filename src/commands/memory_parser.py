from __future__ import annotations

import argparse

from ..plugin_bundle.omh.memory_blocks import DEFAULT_BLOCK_LIMIT_CHARS
from ..plugin_bundle.omh.memory_governance import SCOPE_KINDS, SOURCE_CLASSES
from ..plugin_bundle.omh.memory_recall_settings import RECALL_LINES, RECALL_MODES
from ..workflows.memory import CAPTURE_ON_DUPLICATE_CHOICES, MEMORY_ATTENTION_TIERS
from . import memory
from .domain_intelligence_parser import add_domain_intelligence_commands


def _add_candidate_revision_argument(parser: argparse.ArgumentParser, verb: str) -> None:
    """Bind one review verb to the card revision its reviewer rendered.

    Spelled and defaulted identically on both verbs so a wrapper submits the
    same field either way. The default stays empty rather than absent: an
    empty value means "no card was proven", which the command refuses, and a
    caller that never rendered a card gets that refusal instead of a silent
    decision on a payload it never read.
    """
    parser.add_argument(
        "--candidate-revision",
        default="",
        help=(
            f"Candidate revision from the `memory review` card being acted on; "
            f"{verb} refuses when the stored candidate no longer matches it."
        ),
    )


def add_memory_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = sub.add_parser("memory", help="Agent/operator-only OMH memory review, migration, lifecycle, and prepared-context controls.")
    memory_sub = command.add_subparsers(dest="memory_command", required=True)

    identity = memory_sub.add_parser("project-identity", help="Operator-only stable repository identity and reviewed scope migration.")
    identity_sub = identity.add_subparsers(dest="identity_command", required=True)
    for verb in ("show", "init", "report", "migrate"):
        action = identity_sub.add_parser(verb)
        action.set_defaults(func=memory.cmd_memory_project_identity)
        if verb == "migrate":
            approval = action.add_mutually_exclusive_group(required=True)
            approval.add_argument("--approve", metavar="REPORT_DIGEST")
            approval.add_argument("--rollback", metavar="RECEIPT_ID")

    status = memory_sub.add_parser("status", help="Show OMH project-memory policy, store paths, and review counts.")
    status.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    status.set_defaults(func=memory.cmd_memory_status)

    capture = memory_sub.add_parser("capture", help="Capture an OMH project-memory candidate for review.")
    capture.add_argument("summary", nargs="*", help="Short reviewed-memory summary to capture.")
    capture.add_argument("--type", choices=("fact", "decision", "lesson", "procedure", "episode"), default="fact", help="Typed memory record category.")
    capture.add_argument("--content", default="", help="Optional raw source text. It is hashed/length-counted, not persisted raw.")
    capture.add_argument("--stdin", action="store_true", help="Read optional raw source text from stdin without persisting it raw.")
    capture.add_argument("--scope-kind", choices=tuple(sorted(SCOPE_KINDS)), default="project")
    capture.add_argument("--scope-ref", default=None)
    capture.add_argument("--source", default="cli")
    capture.add_argument(
        "--source-ref",
        default="",
        help="What this memory is about. An absolute path to a readable local file is also digested, so a later change to that file marks the record stale.",
    )
    capture.add_argument("--tag", action="append", default=[])
    capture.add_argument("--ttl-days", type=int, default=None)
    capture.add_argument("--stale-after-days", type=int, default=None)
    capture.add_argument(
        "--stale-after",
        default="",
        metavar="DATE",
        help="Absolute review deadline (YYYY-MM-DD = start of that UTC day, or a full ISO timestamp); mutually exclusive with --stale-after-days.",
    )
    capture.add_argument(
        "--expires-at",
        default="",
        metavar="DATE",
        help="Absolute retention expiry (YYYY-MM-DD = start of that UTC day, or a full ISO timestamp); mutually exclusive with --ttl-days.",
    )
    capture.add_argument("--retention-class", choices=("volatile", "standard", "durable"), default="standard", help="Retention class for the review candidate.")
    capture.add_argument(
        "--derived-from",
        action="append",
        default=[],
        metavar="RECORD_ID",
        help="Existing approved record this candidate was derived from; repeatable, at most 8.",
    )
    capture.add_argument("--observer", default=None, help="Optional perspective observer label; defaults to hermes when --observed is set.")
    capture.add_argument("--observed", default=None, help="Actor this record is about (e.g. codex, claude); scoped records only surface through a matching lens.")
    capture.add_argument("--source-class", choices=tuple(sorted(SOURCE_CLASSES)), default="omh_local", help="Source class; direct capture accepts OMH-local candidates only.")
    capture.add_argument("--principal-context", default=None, metavar="PATH", help="Operator-supplied local memory_principal_context/v1 JSON; not host authentication evidence.")
    capture.add_argument("--audience-principal", action="append", default=[], help="Opaque principal allowed to recall a reviewed shared project/thread record; repeatable.")
    capture.add_argument(
        "--unresolved",
        action="store_true",
        help=(
            "Mark the record as an open question: past its review deadline it stays delivered as "
            "'open · N days unresolved' instead of going stale, until confirm, correct, or retire answers it."
        ),
    )
    capture.add_argument(
        "--on-duplicate",
        choices=CAPTURE_ON_DUPLICATE_CHOICES,
        default="candidate",
        help=(
            "What an exact-summary duplicate of a live record does: 'candidate' (default) keeps a pending "
            "candidate stamped duplicate_of; 'skip' persists nothing and reports the existing record."
        ),
    )
    capture.set_defaults(func=memory.cmd_memory_capture)

    review = memory_sub.add_parser("review", help="Return review cards for pending OMH project-memory candidates.")
    review.add_argument("--candidate", default=None, help="Limit review output to one candidate id.")
    review.add_argument("--limit", type=int, default=20)
    review.set_defaults(func=memory.cmd_memory_review)

    approve = memory_sub.add_parser("approve", help="Approve a reviewed project-memory candidate.")
    approve.add_argument("candidate_id")
    approve.add_argument("--approved-by", default="operator")
    approve.add_argument("--principal-context", default=None, metavar="PATH")
    _add_candidate_revision_argument(approve, "approve")
    approve.add_argument(
        "--retention-class",
        choices=("volatile", "standard", "durable"),
        default=None,
        help=(
            "Re-class the record at approval (most usefully durable, which drops the default "
            "90-day review clock); retention and the review deadline are re-derived for the new class."
        ),
    )
    approve.add_argument(
        "--unresolved",
        action="store_true",
        help="Approve the record as an open question (staleness.resolution: open, clock starting now); see `capture --unresolved`.",
    )
    approve.set_defaults(func=memory.cmd_memory_approve)

    reject = memory_sub.add_parser("reject", help="Reject a project-memory candidate.")
    reject.add_argument("candidate_id")
    reject.add_argument("--rejected-by", default="operator")
    reject.add_argument("--reason", default="")
    _add_candidate_revision_argument(reject, "reject")
    reject.set_defaults(func=memory.cmd_memory_reject)

    incident = memory_sub.add_parser(
        "recall-incident",
        help="Diagnose one expected memory from local evidence without changing memory.",
    )
    anchor = incident.add_mutually_exclusive_group(required=True)
    anchor.add_argument("--record-id", default="", help="Expected OMH record or candidate ID.")
    anchor.add_argument("--claim-digest", default="", help="SHA256 of the exact expected claim.")
    incident.add_argument("--query", default="", help="Recall query; only its digest is retained.")
    incident.add_argument("--session-id", default="")
    incident.add_argument("--scope-kind", choices=tuple(sorted(SCOPE_KINDS)), default="project")
    incident.add_argument("--scope-ref", default="")
    incident.add_argument("--observer", default=None)
    incident.add_argument("--observed", default=None)
    incident.add_argument("--limit", type=int, default=6)
    incident.add_argument("--max-chars", type=int, default=None)
    incident.add_argument(
        "--provider-served-count", type=int, default=None,
        help="Optional aggregate count; never authoritative record-delivery evidence.",
    )
    incident.add_argument("--write", action="store_true", help="Save only the metadata incident artifact.")
    incident.set_defaults(func=memory.cmd_memory_recall_incident)

    recall = memory_sub.add_parser("recall", help="Recall reviewed OMH project memory for a task as prepared context.")
    recall.add_argument("query", nargs="*", help="Task/query text used for deterministic keyword recall.")
    recall.add_argument("--executor", default="generic", help="Executor target label to record in the recall pack.")
    recall.add_argument("--session-id", default="", help="Optional wrapper session id to bind to the recall pack.")
    recall.add_argument("--scope-kind", choices=tuple(sorted(SCOPE_KINDS)), default=None)
    recall.add_argument("--scope-ref", default=None)
    recall.add_argument("--limit", type=int, default=6)
    recall.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Optional summary-character budget; records cut by it are marked over_budget and the pack says truncated.",
    )
    recall.add_argument("--include-stale", action="store_true")
    recall.add_argument(
        "--include-archived",
        action="store_true",
        help="Also recall archive-tier records. They are excluded by default as archived_tier, never deleted.",
    )
    recall.add_argument(
        "--intent",
        choices=("auto", "default", "temporal"),
        default="auto",
        help=(
            "State whether the query asks for the most recent, instead of leaving it to the English cue table. "
            "temporal doubles the recency weight inside rank fusion; it never changes which records match. "
            "auto keeps the existing English-cue derivation."
        ),
    )
    recall.add_argument("--observer", default=None, help="Perspective lens: only unscoped records and records with this observer pass.")
    recall.add_argument("--observed", default=None, help="Perspective lens: only unscoped records and records about this actor pass.")
    recall.add_argument("--principal-context", default=None, metavar="PATH", help="Operator-supplied local memory_principal_context/v1 JSON; user-scoped recall fails closed without it.")
    recall.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    recall.set_defaults(func=memory.cmd_memory_recall)

    rejected_recall = memory_sub.add_parser(
        "rejected-recall",
        help="Recall reviewed rejected-decision metadata as OMH-local context.",
    )
    rejected_recall.add_argument("query", nargs="*", help="Decision/query text used for deterministic keyword recall.")
    rejected_recall.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), required=True)
    rejected_recall.add_argument("--scope-ref", required=True)
    rejected_recall.add_argument("--tag", action="append", default=[])
    rejected_recall.add_argument("--include-stale", action="store_true")
    rejected_recall.add_argument("--limit", type=int, default=6)
    rejected_recall.set_defaults(func=memory.cmd_memory_rejected_recall)

    perspectives = memory_sub.add_parser("perspectives", help="List observer/observed perspective pairs with reviewed-record counts.")
    perspectives.set_defaults(func=memory.cmd_memory_perspectives)

    add_domain_intelligence_commands(memory_sub)

    rollup = memory_sub.add_parser("rollup", help="Report an additive episode rollup over matching records; --apply stages the reviewable episode candidate.")
    rollup.add_argument("--tag", default=None, help="Roll up records carrying this tag.")
    rollup.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default=None)
    rollup.add_argument("--scope-ref", default=None)
    rollup.add_argument("--apply", action="store_true", help="Stage the episode candidate through the normal capture/review pipeline (default is report-only).")
    rollup.set_defaults(func=memory.cmd_memory_rollup)

    pin = memory_sub.add_parser("pin", help="Mark one reviewed record as a recall anchor: first in packs, exempt from no-overlap cuts, never from eligibility.")
    pin.add_argument("record_id")
    pin.set_defaults(func=memory.cmd_memory_pin)

    unpin = memory_sub.add_parser("unpin", help="Remove one record's recall-anchor marker.")
    unpin.add_argument("record_id")
    unpin.set_defaults(func=memory.cmd_memory_unpin)

    demote = memory_sub.add_parser(
        "demote",
        help=(
            "Plan moving capped Hermes memory entries (L1) down into the OMH store (L2), leaving a short "
            "reference line; --stage captures the planned entries as review-first candidates."
        ),
    )
    demote.add_argument("--file", default=None, help="Only plan one Hermes memory file (MEMORY.md or USER.md).")
    demote.add_argument("--max", type=int, default=5, help="Most entries to plan, biggest savings first (default 5).")
    demote.add_argument(
        "--stage",
        action="store_true",
        help="Capture the planned entries as OMH candidates (default is report-only). Hermes itself applies the L1 edits.",
    )
    demote.set_defaults(func=memory.cmd_memory_demote)

    confirm = memory_sub.add_parser(
        "confirm",
        help=(
            "Confirm one approved record is still true and reset its review deadline; "
            "--all-due confirms every record whose deadline has passed."
        ),
    )
    confirm.add_argument("record_id", nargs="?", default="", help="Record to confirm; omit when using --all-due.")
    confirm.add_argument(
        "--all-due",
        action="store_true",
        help="Confirm every approved record whose review deadline has passed; refusals are reported as skipped.",
    )
    confirm.add_argument(
        "--stale-after-days",
        type=int,
        default=None,
        help="Days until the next review deadline (default 90).",
    )
    confirm.add_argument(
        "--stale-after",
        default="",
        metavar="DATE",
        help="Absolute next review deadline (YYYY-MM-DD = start of that UTC day, or ISO timestamp); mutually exclusive with --stale-after-days.",
    )
    confirm.add_argument("--confirmed-by", default="operator", help="Who confirmed the record; stored as bounded metadata.")
    confirm.set_defaults(func=memory.cmd_memory_confirm)

    keep_open = memory_sub.add_parser(
        "keep-open",
        help=(
            "Answer 'still open' for one unresolved record: resets the reminder clock only; "
            "the record, its deadline, and its state are untouched."
        ),
    )
    keep_open.add_argument("record_id", help="Open record to keep open; refused (not_open) when the record is not marked unresolved.")
    keep_open.set_defaults(func=memory.cmd_memory_keep_open)

    attention = memory_sub.add_parser(
        "attention",
        help="Report how one record's attention tier would change the working context; --apply writes the local tier change.",
    )
    attention.add_argument("record_id")
    attention.add_argument(
        "--tier",
        choices=MEMORY_ATTENTION_TIERS,
        required=True,
        help="active leads the working context; reference stays recallable behind active peers; archive leaves default recall without deleting anything.",
    )
    attention.add_argument("--reason", default="", help="Why the tier changed; stored as bounded metadata on the record and in the local journal.")
    attention.add_argument("--query", nargs="*", default=[], help="Optional task text so the previewed working context matches the recall this tier change affects.")
    attention.add_argument("--limit", type=int, default=6, help="Recall budget used to preview the working context.")
    attention.add_argument("--apply", action="store_true", help="Write the tier change (default is report-only).")
    attention.set_defaults(func=memory.cmd_memory_attention)

    sources = memory_sub.add_parser(
        "sources",
        help=(
            "Index reviewed records by the source they were admitted from; with --source, enumerate that "
            "source's blast radius. Read-only: it quarantines and deletes nothing."
        ),
    )
    sources.add_argument(
        "--source",
        default="",
        help="Enumerate every record admitted from this source value, matched on each source axis it appears on.",
    )
    sources.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum selected record cards to return; the reported count stays the full match.",
    )
    sources.set_defaults(func=memory.cmd_memory_sources)

    lineage = memory_sub.add_parser("lineage", help="Trace derived-from provenance links for one reviewed memory record.")
    lineage.add_argument("record_id")
    lineage.add_argument("--depth", type=int, default=3, help="Maximum ancestor/descendant hops to traverse (clamped to 1-10).")
    lineage.set_defaults(func=memory.cmd_memory_lineage)

    retire = memory_sub.add_parser(
        "retire",
        help=(
            "Report expired OMH project-memory records; --apply moves them into the local archive. "
            "With a record id, retire that one record -- including an open (unresolved) record the operator chose to drop."
        ),
    )
    retire.add_argument(
        "record_id",
        nargs="?",
        default="",
        help="Only this record: expired records and open records qualify; a live settled record is refused as not_expired.",
    )
    retire.add_argument("--apply", action="store_true", help="Move expired records into .omh/memory/archive/ (default is report-only).")
    retire.add_argument("--window-days", type=int, default=7, help="How many days ahead counts as expiring soon.")
    retire.set_defaults(func=memory.cmd_memory_retire)

    inspect = memory_sub.add_parser("inspect")
    inspect.add_argument("--fixture", default=None, help="Optional memory_snapshot/v1 JSON fixture supplied by a wrapper for deterministic inspection.")
    inspect.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default=None, help="Only inspect snapshots from this scope kind.")
    inspect.add_argument("--scope-ref", default=None, help="Only inspect snapshots with this scope reference.")
    inspect.add_argument("--session-limit", type=int, default=None, help="Maximum recent wrapper session snapshots to inspect.")
    inspect.add_argument("--review-item-limit", type=int, default=None, help="Maximum review items to return.")
    inspect.add_argument("--summary", action="store_true", help="Return snapshot summaries instead of full snapshot items.")
    inspect.set_defaults(func=memory.cmd_memory_inspect)

    pack = memory_sub.add_parser("pack")
    pack.add_argument("--fixture", default=None, help="Optional memory_snapshot/v1 JSON fixture supplied by a wrapper before packing handoff context.")
    pack.add_argument("--executor", default="generic", help="Executor target label to record in the context pack.")
    pack.add_argument("--session-id", default="", help="Optional wrapper session id to bind to the context pack.")
    pack.add_argument("--scope-kind", choices=("project", "target", "thread", "run"), default=None, help="Only pack context from this scope kind.")
    pack.add_argument("--scope-ref", default=None, help="Only pack context with this scope reference.")
    pack.add_argument("--session-limit", type=int, default=None, help="Maximum recent wrapper session snapshots to inspect.")
    pack.add_argument("--review-item-limit", type=int, default=None, help="Maximum review items to build when a fixture is supplied.")
    pack.add_argument("--context-limit", type=int, default=12, help="Maximum context items to include in the handoff pack.")
    pack.set_defaults(func=memory.cmd_memory_pack)

    apply = memory_sub.add_parser("apply", help="Compatibility report for direct batches; it never writes scope memory.")
    apply.add_argument("--batch", required=True, help="Path to memory_update_batch/v1 JSON, or '-' to read from stdin.")
    apply.add_argument("--dry-run", action="store_true", help="Retained compatibility marker; direct batches are always review-required and write-free.")
    apply.set_defaults(func=memory.cmd_memory_apply)

    inventory = memory_sub.add_parser("inventory", help="Emit a dry-run v1/v2 memory ledger; write it only with --write-ledger.")
    inventory.add_argument("--write-ledger", action="store_true", help="Persist the bounded metadata-only inventory ledger through the operation store.")
    inventory.set_defaults(func=memory.cmd_memory_inventory)

    reactivate = memory_sub.add_parser("reactivate", help="Reactivate exactly one legacy artifact only after matching immutable review.")
    reactivate.add_argument("artifact_id")
    reactivate.add_argument("--revision", required=True, type=int, help="Exact legacy artifact revision.")
    reactivate.add_argument("--review-id", required=True, help="Matching immutable legacy-review record id.")
    reactivate.add_argument("--apply", action="store_true", help="Perform the exact reviewed reactivation (default is report-only).")
    reactivate.set_defaults(func=memory.cmd_memory_reactivate)

    batch_stage = memory_sub.add_parser("batch-stage", help="Stage a scope-update batch for immutable review; never makes it prompt eligible.")
    batch_stage.add_argument("--batch", required=True, help="Path to memory_update_batch/v1 JSON, or '-' to read from stdin.")
    batch_stage.set_defaults(func=memory.cmd_memory_batch_stage)

    batch_review = memory_sub.add_parser("batch-review", help="Record one immutable remember/refuse/defer decision per staged item.")
    batch_review.add_argument("batch_id")
    batch_review.add_argument("--decisions", required=True, help="Path to an object mapping exact staged item ids to remember, refuse, or defer.")
    batch_review.add_argument("--reviewer-label", default="operator", help="Reviewer claim label; it is not an authenticated identity.")
    batch_review.set_defaults(func=memory.cmd_memory_batch_review)

    batch_apply = memory_sub.add_parser("batch-apply", help="Apply a fully remembered staged batch only with --apply.")
    batch_apply.add_argument("batch_id")
    batch_apply.add_argument("--apply", action="store_true", help="Perform the staged batch apply (default is report-only).")
    batch_apply.set_defaults(func=memory.cmd_memory_batch_apply)

    restore = memory_sub.add_parser("restore", help="Report one archived revision; --apply requires the lifecycle transaction executor.")
    restore.add_argument("record_id")
    restore.add_argument("--revision", required=True, type=int)
    restore.add_argument("--apply", action="store_true", help="Request restore of the exact archive revision (default is report-only).")
    restore.add_argument("--principal-context", default=None, metavar="PATH")
    restore.set_defaults(func=memory.cmd_memory_restore)

    prune = memory_sub.add_parser("prune", help="Report hard-delete-local targets for one expired approved volatile revision.")
    prune.add_argument("record_id")
    prune.add_argument("--revision", required=True, type=int)
    prune.add_argument("--apply", action="store_true", help="Request hard-delete-local apply (default is report-only).")
    prune.add_argument("--confirm-hard-delete-local", action="store_true", help="Required alongside --apply; does not claim external deletion or erasure.")
    prune.add_argument("--principal-context", default=None, metavar="PATH")
    prune.set_defaults(func=memory.cmd_memory_prune)

    correct = memory_sub.add_parser("correct", help="Prepare a superseding pending correction; --apply requires the lifecycle transaction executor.")
    correct.add_argument("record_id")
    correct.add_argument("summary", nargs="+", help="Bounded replacement summary for review.")
    correct.add_argument("--revision", required=True, type=int)
    correct.add_argument("--apply", action="store_true", help="Request correction apply (default is report-only).")
    correct.add_argument("--principal-context", default=None, metavar="PATH")
    correct.set_defaults(func=memory.cmd_memory_correct)

    evaluate = memory_sub.add_parser("evaluate", help="Run deterministic, host-normalized OMH memory evaluation evidence.")
    evaluate.add_argument("--profile", choices=("small", "medium", "stress"), default="small", help="OMH-owned deterministic corpus profile.")
    evaluate.add_argument("--repetitions", type=int, default=3, help="Target and same-host baseline samples to preserve.")
    evaluate.add_argument("--seed", type=int, default=None, help="Override the profile's declared deterministic seed.")
    evaluate.add_argument("--output", default=None, help="Write the exact JSON evidence object to this path.")
    evaluate.set_defaults(func=memory.cmd_memory_evaluate)

    recall_suite = memory_sub.add_parser(
        "recall-suite",
        help="Run the retained retrieval-quality corpus through the production recall-pack builder; exits non-zero on a regression.",
    )
    recall_suite.add_argument("--revision", default="", help="Target revision this report is bound to; two reports compare only when it matches.")
    recall_suite.add_argument("--output", default=None, help="Write the exact JSON regression report to this path.")
    recall_suite.set_defaults(func=memory.cmd_memory_recall_suite)

    blocks = memory_sub.add_parser("blocks", help="List OMH memory blocks by label, without their values.")
    blocks.add_argument("--tier", choices=("system", "reference"), default=None, help="Limit the listing to one tier.")
    blocks.set_defaults(func=memory.cmd_memory_blocks)

    block_set = memory_sub.add_parser("block-set", help="Create or replace one OMH memory block.")
    block_set.add_argument("label", help="Block label: lowercase letters, digits, '-' or '_'.")
    block_set.add_argument("--value", default="", help="Block content. Rejected when longer than --limit.")
    block_set.add_argument("--stdin", action="store_true", help="Read block content from stdin instead of --value.")
    block_set.add_argument("--description", default="", help="What the block is for; shown to the model beside the value.")
    block_set.add_argument("--limit", type=int, default=DEFAULT_BLOCK_LIMIT_CHARS, help="Per-block character budget.")
    block_set.add_argument("--tier", choices=("system", "reference"), default="system", help="'system' renders every turn; 'reference' is listed by label and read on request.")
    block_set.set_defaults(func=memory.cmd_memory_block_set)

    block_remove = memory_sub.add_parser("block-remove", help="Remove one OMH memory block.")
    block_remove.add_argument("label")
    block_remove.add_argument("--tier", choices=("system", "reference"), default="system")
    block_remove.set_defaults(func=memory.cmd_memory_block_remove)

    dream = memory_sub.add_parser("dream", help="Report whether memory consolidation is due, and why. Never consolidates.")
    dream.add_argument("--evaluate", action="store_true", help="Weigh the triggers now and write the consolidation handoff when they fire.")
    dream.set_defaults(func=memory.cmd_memory_dream)

    migration = memory_sub.add_parser("principal-migration", help="Report, apply, or roll back reviewed acting-principal assignments.")
    migration_mode = migration.add_mutually_exclusive_group(required=True)
    migration_mode.add_argument("--report", action="store_true", help="List bounded identity-unbound revisions without content or writes.")
    migration_mode.add_argument("--plan", default=None, metavar="PATH", help="Reviewed memory_principal_migration_plan/v1 JSON.")
    migration_mode.add_argument("--rollback", default=None, metavar="OPERATION_ID", help="Reverse an unchanged migrated revision.")
    migration.add_argument("--apply", action="store_true", help="Required for plan application or rollback.")
    migration.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    migration.set_defaults(func=memory.cmd_memory_principal_migration)

    principal_export = memory_sub.add_parser("principal-export", help="Export records allowed for one acting principal.")
    principal_export.add_argument("--principal-context", required=True, metavar="PATH")
    principal_export.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    principal_export.set_defaults(func=memory.cmd_memory_principal_export)

    provider = memory_sub.add_parser("provider", help="Show or change Hermes' single external memory-provider selection.")
    provider_slot = provider.add_mutually_exclusive_group()
    provider_slot.add_argument("--enable", action="store_true", help="Point Hermes' memory.provider at OMH. Refused when another provider holds the slot.")
    provider_slot.add_argument("--disable", action="store_true", help="Hand the slot back, only when OMH currently holds it.")
    provider.add_argument("--dry-run", action="store_true", help="Report the change without writing Hermes config.")
    provider.set_defaults(func=memory.cmd_memory_provider)

    recall_line = memory_sub.add_parser(
        "recall-line", help="Show or set where Hermes shows the OMH recall line for this profile (default: console)."
    )
    recall_line.add_argument("value", nargs="?", choices=RECALL_LINES, help="all: every surface; console: CLI, TUI and Desktop only; off: nowhere.")
    recall_line.add_argument("--dry-run", action="store_true", help="Report the change without writing Hermes config.")
    recall_line.set_defaults(func=memory.cmd_memory_recall_line)

    recall_mode = memory_sub.add_parser(
        "recall-mode", help="Show or set whether this profile recalls OMH memory every turn (default: auto)."
    )
    recall_mode.add_argument(
        "value", nargs="?", choices=RECALL_MODES,
        help="auto: every turn; on_demand: only when the model asks; off: never, tool recall refused too.",
    )
    recall_mode.add_argument("--dry-run", action="store_true", help="Report the change without writing Hermes config.")
    recall_mode.set_defaults(func=memory.cmd_memory_recall_mode)
