#!/usr/bin/env python3
"""Review false-alarm trap benchmark: does a reviewer invent bugs?

    bench.py --dry-run --fixture fixtures/recorded-verdicts.json
        grade recorded replies; no model, no Hermes process
    bench.py validate
        check every case in the corpus against the schema
    bench.py run --live --profile-on P --profile-off Q --runs 3 --output out.json
        real reviews through `hermes -z`, one per case, arm and run

A live run needs `--live`; without it `run` prints the plan and exits.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "lib"))

import rfa_grading as grading  # noqa: E402
import rfa_harness as harness  # noqa: E402
import rfa_report as report  # noqa: E402

DEFAULT_FIXTURE = BASE / "fixtures" / "recorded-verdicts.json"


def dry_run(fixture: Path, corpus: Path, per_case: bool) -> int:
    cases = grading.load_corpus(corpus)
    graded = grading.grade_records(cases, grading.load_records(fixture))
    print(f"Dry run: {fixture.name}, {len(graded)} recorded replies, no model called.")
    print()
    print(report.markdown_table(report.summarize(graded)))
    if per_case:
        print()
        print(report.per_case_table(graded))
    return 0


def validate(corpus: Path) -> int:
    cases = grading.load_corpus(corpus)
    traps = sum(1 for case in cases.values() if case.kind == "trap")
    controls = len(cases) - traps
    print(f"{len(cases)} cases valid: {traps} traps, {controls} controls")
    return 0


def run(args: argparse.Namespace) -> int:
    cases = grading.load_corpus(args.corpus)
    selected = [cases[name] for name in args.case] if args.case else list(cases.values())
    arms = args.arm or list(grading.ARMS)
    profiles = {"omh-on": args.profile_on, "omh-off": args.profile_off}
    planned = len(selected) * len(arms) * args.runs
    if args.provider and args.provider.casefold() in harness.REFUSED_PROVIDERS:
        print(f"refused: provider {args.provider!r} is not used by this benchmark", file=sys.stderr)
        return 2
    if not args.live:
        print(
            f"Plan: {len(selected)} cases x {len(arms)} arms x {args.runs} runs = {planned} Hermes calls. "
            "Nothing was run; pass --live to run them."
        )
        return 0
    missing = [arm for arm in arms if not profiles[arm]]
    if missing:
        print(f"refused: --live needs a Hermes profile for {', '.join(missing)}", file=sys.stderr)
        return 2
    if len(arms) == 2 and profiles["omh-on"] == profiles["omh-off"]:
        print("refused: the two arms must use different profiles", file=sys.stderr)
        return 2
    if args.output is None or args.output.exists():
        print("refused: --live needs an --output path that does not exist yet", file=sys.stderr)
        return 2
    records = []
    for run_index in range(1, args.runs + 1):
        for case in selected:
            for arm in arms:
                result = harness.review_once(
                    case,
                    hermes_executable=args.hermes_executable,
                    profile=profiles[arm],
                    provider=args.provider,
                    model=args.model,
                    toolsets=args.toolsets,
                    ignore_rules=args.ignore_rules,
                    timeout=args.timeout,
                )
                records.append({"arm": arm, "case": case.id, "run": run_index, **result})
                args.output.write_text(
                    json.dumps({"schema": grading.RECORDS_SCHEMA, "records": records}, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"{len(records)}/{planned} {arm} {case.id} run {run_index}", file=sys.stderr)
    graded = grading.grade_records(cases, records)
    print(report.markdown_table(report.summarize(graded)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Grade a recorded-verdicts fixture; no model.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--corpus", type=Path, default=grading.CORPUS_ROOT)
    parser.add_argument("--per-case", action="store_true", help="Also print each case's outcomes.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("validate", help="Check the corpus schema.")
    run_parser = sub.add_parser("run", help="Live reviews through hermes -z.")
    run_parser.add_argument("--live", action="store_true", help="Actually call Hermes (spends model calls).")
    run_parser.add_argument(
        "--harness",
        choices=("hermes",),
        default="hermes",
        help="Who runs the review. Only `hermes -z` one-shot today.",
    )
    run_parser.add_argument("--arm", action="append", choices=grading.ARMS)
    run_parser.add_argument("--case", action="append", help="Run only these case ids.")
    run_parser.add_argument("--runs", type=int, default=3)
    run_parser.add_argument("--profile-on", help="Hermes profile with the OMH plugin enabled.")
    run_parser.add_argument("--profile-off", help="Hermes profile identical except OMH is disabled.")
    run_parser.add_argument("--provider", help="Provider override; unset uses the profile's default.")
    run_parser.add_argument("--model", help="Model override; unset uses the profile's default.")
    run_parser.add_argument("--toolsets", default=harness.DEFAULT_TOOLSETS)
    run_parser.add_argument(
        "--ignore-rules",
        action="store_true",
        help="Pass --ignore-rules to both arms (drops AGENTS.md, memory and preloaded skills).",
    )
    run_parser.add_argument("--timeout", type=int, default=harness.DEFAULT_TIMEOUT)
    run_parser.add_argument("--hermes-executable", default="hermes")
    run_parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return validate(args.corpus)
    if args.command == "run":
        if args.runs < 1:
            parser.error("--runs must be at least 1")
        return run(args)
    if args.dry_run:
        return dry_run(args.fixture, args.corpus, args.per_case)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
