from __future__ import annotations

import argparse

from ..installer import OmhError
from ..paper_learning import (
    PAPER_LEARNING_LEVELS,
    PAPER_LEARNING_SOURCE_STATES,
    PaperLearningStoreError,
    build_paper_learning_record,
    paper_learning_card_path,
    paper_learning_level_or_none,
    paper_learning_ledger_path,
    read_paper_progress_ledger,
    record_paper_progress,
    render_paper_learning_list_text,
    render_paper_learning_record_text,
    scan_paper_learning_store,
    show_paper_learning_record,
    summarize_paper_learning_record,
    validate_paper_learning_store,
    write_paper_learning_record,
)
from .common import _paths, _print_json, _wants_json


DEFAULT_PAPER_LIST_LIMIT = 20

# The store proves where reading stopped and which bytes the source file had.
# It never proves the paper was extracted, paged, or explained correctly; the
# skill's own not_observed list stays on the card and this block says the same
# thing at the command boundary so a wrapper reading only stdout cannot miss it.
PAPER_LEARNING_BOUNDARY = {
    "prepared_is_not_observed": True,
    "source_hash_is_not_extraction_evidence": True,
    "page_count_observed": False,
    "recorded_chunk_is_not_correctness_evidence": True,
    "normal_user_surface": "Hermes chat or installed skills; CLI is backend/verifier infrastructure.",
}


def cmd_paper_plan(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        record = build_paper_learning_record(
            title=args.title,
            source_ref=args.source or "",
            authors=args.author or [],
            level=args.level,
            source_state=args.source_state,
            sections=args.section,
            observed_sections=args.observed_section or [],
            missing_sections=args.missing_section or [],
            evidence_ref=args.evidence_ref or "",
            output_language=args.output_language or "source",
        )
        written = write_paper_learning_record(paths, record)
    except PaperLearningStoreError as exc:
        raise OmhError(_store_error_message(exc)) from exc
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return _emit_record(args, paths, written, schema_version="omh_paper_learning_plan_result/v1")


def cmd_paper_list(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        limit = _limit_from_args(args, default=DEFAULT_PAPER_LIST_LIMIT)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    all_records, unreadable = scan_paper_learning_store(paths)
    records = all_records if limit is None else all_records[-limit:]
    summaries = [summarize_paper_learning_record(record) for record in records]
    if _wants_json(args):
        _print_json(
            {
                "schema_version": "omh_paper_learning_list/v1",
                "count": len(records),
                "total_count": len(all_records),
                "limit": limit if limit is not None else "all",
                "truncated": limit is not None and len(all_records) > len(records),
                "summary_only": True,
                "index_authority": "cache_only",
                "papers": summaries,
                # A record the scan could not read is counted and named here,
                # never dropped: a list that says "1 of 1" over a directory
                # holding two records is the lie `validate` exists to catch.
                "unreadable_count": len(unreadable),
                "unreadable_records": unreadable,
                "next_action": "run `omh paper validate` to see every store fault" if unreadable else "",
            }
        )
    else:
        print(render_paper_learning_list_text(summaries, unreadable, total_count=len(all_records)))
    return 0


def cmd_paper_show(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        record = show_paper_learning_record(paths, args.paper_id)
        entries, ledger_errors = read_paper_progress_ledger(paths, args.paper_id)
    except PaperLearningStoreError as exc:
        raise OmhError(_store_error_message(exc)) from exc
    if _wants_json(args):
        _print_json(
            {
                "schema_version": "omh_paper_learning_show/v1",
                "record": record,
                "ledger": entries,
                "ledger_errors": ledger_errors,
                "store": _store_block(paths, record["paper_id"]),
                "boundary": PAPER_LEARNING_BOUNDARY,
            }
        )
    else:
        print(render_paper_learning_record_text(record, entries))
        if ledger_errors:
            print("")
            print("Ledger lines that could not be read:")
            for error in ledger_errors:
                print(f"  - {error}")
    return 0


def cmd_paper_progress(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        updated, entry = record_paper_progress(
            paths,
            args.paper_id,
            covered=args.covered or [],
            next_section=args.next,
            missing=args.missing or [],
            observed=args.observed_section or [],
            note=args.note or "",
            source_state=args.source_state,
            evidence_ref=args.evidence_ref,
        )
    except PaperLearningStoreError as exc:
        raise OmhError(_store_error_message(exc)) from exc
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return _emit_record(args, paths, updated, schema_version="omh_paper_learning_progress_result/v1", entry=entry)


def cmd_paper_validate(args: argparse.Namespace) -> int:
    result = validate_paper_learning_store(_paths(args))
    if _wants_json(args):
        _print_json(result)
    else:
        if result["ok"]:
            print(f"paper-learning store ok: {result['paper_count']} record(s), 0 errors")
        else:
            print(f"paper-learning store has {len(result['errors'])} error(s) across {result['paper_count']} readable record(s):")
            for error in result["errors"]:
                print(f"  - {error}")
    return 0 if result["ok"] else 1


def _emit_record(args: argparse.Namespace, paths, record: dict, *, schema_version: str, entry: dict | None = None) -> int:
    if _wants_json(args):
        payload = {
            "schema_version": schema_version,
            "record": record,
            "store": _store_block(paths, record["paper_id"]),
            "boundary": PAPER_LEARNING_BOUNDARY,
        }
        if entry is not None:
            payload["entry"] = entry
        _print_json(payload)
        return 0
    entries = [entry] if entry is not None else []
    print(render_paper_learning_record_text(record, entries))
    print(f"Card: {paper_learning_card_path(paths, record['paper_id'])}")
    return 0


def _store_error_message(exc: PaperLearningStoreError) -> str:
    """One line per reason code, so a wrapper reading stderr can tell a typo from a broken file."""
    if exc.reason_code == "record_not_found":
        return f"paper learning record not found (record_not_found): {exc.detail}"
    if exc.reason_code == "source_unreadable":
        return f"paper source is unreadable (source_unreadable): {exc.detail}; nothing was recorded"
    return f"paper learning record is corrupt (record_corrupt): {exc.detail}; run `omh paper validate`"


def _level_argument(value: str) -> str:
    level = paper_learning_level_or_none(value)
    if level is None:
        raise argparse.ArgumentTypeError(f"unknown level {value!r}; use one of {', '.join(PAPER_LEARNING_LEVELS)} (aliases such as 'very easy' or 'advanced' are accepted)")
    return level


def _store_block(paths, paper_id: str) -> dict[str, str]:
    return {
        "omh_home": str(paths.omh_home),
        "paper_learning_dir": str(paths.paper_learning_dir),
        "card_path": str(paper_learning_card_path(paths, paper_id)),
        "ledger_path": str(paper_learning_ledger_path(paths, paper_id)),
        "index_path": str(paths.paper_learning_index_path),
        "index_authority": "cache_only",
    }


def _limit_from_args(args: argparse.Namespace, *, default: int) -> int | None:
    if args.all:
        return None
    if args.limit is None:
        return default
    if args.limit < 1:
        raise ValueError("--limit must be at least 1")
    return args.limit


def cmd_paper_audit(args: argparse.Namespace) -> int:
    from ..workflows.repro_audit.operations import run
    return run(args)


def _add_paper_commands(sub) -> None:
    paper = sub.add_parser(
        "paper",
        help="Record and resume paper-learning reading progress: one card plus a chunk ledger per paper.",
        description=(
            "Durable store for the paper-learning skill: one paper_learning_card/v1 plus an append-only chunk ledger "
            "per paper under $OMH_HOME/paper-learning/<paper_id>/, so a resumed Hermes session continues from the "
            "recorded next section. The source file is hashed for identity, never parsed."
        ),
    )
    paper_sub = paper.add_subparsers(dest="paper_command", required=True)
    audit_init = paper_sub.add_parser("audit-init", help="Agent infrastructure: create all-unknown audit inputs; no evaluation.")
    audit_init.add_argument("--out", required=True)
    audit_init.add_argument("--metric", choices=("acc", "acc_norm"), default="acc")
    audit_init.set_defaults(func=cmd_paper_audit, command="init")
    native = paper_sub.add_parser("import-harness", help="Agent infrastructure: import local Harness claims for human review; no evaluation.")
    native.add_argument("--results", required=True)
    native.add_argument("--metric", choices=("acc", "acc_norm"), required=True)
    native.add_argument("--out", required=True)
    native.set_defaults(func=cmd_paper_audit, command="import-harness")
    audit = paper_sub.add_parser("audit", help="Agent infrastructure: compare local normalized evidence; no evaluation.")
    audit.add_argument("--case", required=True)
    audit.add_argument("--out", required=True)
    audit.set_defaults(func=cmd_paper_audit, command="audit")

    plan = paper_sub.add_parser(
        "plan",
        help="Create a paper_learning_card/v1 record for a supplied paper; the source is hashed if it is a local file, never parsed.",
    )
    plan.add_argument("--title", required=True)
    plan.add_argument("--source", default="", help="Path, URL, or reference such as arxiv:1706.03762.")
    plan.add_argument("--author", action="append")
    plan.add_argument("--level", type=_level_argument, default="choose", help="One of " + ", ".join(PAPER_LEARNING_LEVELS) + " (aliases accepted; an unknown level is refused).")
    plan.add_argument("--source-state", choices=PAPER_LEARNING_SOURCE_STATES, default="metadata_only")
    plan.add_argument("--section", action="append", help="Replace the ten default sections; repeat once per section in reading order.")
    plan.add_argument("--observed-section", action="append", help="Section whose text a host already observed.")
    plan.add_argument("--missing-section", action="append", help="Section known to be absent from the observed text.")
    plan.add_argument("--evidence-ref", default="", help="Host evidence reference for the recorded source state.")
    plan.add_argument("--output-language", default="source")
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(func=cmd_paper_plan)

    list_cmd = paper_sub.add_parser("list", help="List recorded papers with where reading stopped.")
    list_cmd.add_argument("--limit", type=int, default=None)
    list_cmd.add_argument("--all", action="store_true", help="Return every record.")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_paper_list)

    show = paper_sub.add_parser("show", help="Show one paper's card, coverage ledger, and progress ledger.")
    show.add_argument("paper_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_paper_show)

    progress = paper_sub.add_parser(
        "progress",
        help="Record one explained chunk: which sections were covered, what comes next, what is missing.",
    )
    progress.add_argument("paper_id")
    progress.add_argument("--covered", action="append", help="Section explained in this chunk; repeatable. Moves explanation status only, never the source state.")
    progress.add_argument("--next", default=None, help="Section to resume from; defaults to the first pending section.")
    progress.add_argument("--missing", action="append", help="Section found absent from the observed text; repeatable.")
    progress.add_argument("--observed-section", action="append", help="Section whose text the host observed; repeatable; needs --evidence-ref.")
    progress.add_argument("--note", default="", help="Short resume note (max 500 characters); not the explanation itself.")
    progress.add_argument("--source-state", choices=PAPER_LEARNING_SOURCE_STATES, default=None, help="Record a new source state; needs --evidence-ref.")
    progress.add_argument("--evidence-ref", default=None, help="Host evidence reference for --observed-section / --source-state.")
    progress.add_argument("--json", action="store_true")
    progress.set_defaults(func=cmd_paper_progress)

    validate = paper_sub.add_parser("validate", help="Validate every paper record, its ledger, and the index cache.")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_paper_validate)
