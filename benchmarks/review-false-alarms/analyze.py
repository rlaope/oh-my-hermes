#!/usr/bin/env python3
"""Summarize a records file: per arm, false-alarm rate and hit rate side by side.

    analyze.py <records.json> [--per-case] [--json]

The records file is what `bench.py run --live --output` writes, or a recorded
fixture of the same schema. Both numbers are always printed together; the
two-sided win rule is in README.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "lib"))

import rfa_grading as grading  # noqa: E402
import rfa_report as report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("records", type=Path)
    parser.add_argument("--corpus", type=Path, default=grading.CORPUS_ROOT)
    parser.add_argument("--per-case", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print the summary as JSON instead of a table.")
    args = parser.parse_args(argv)
    cases = grading.load_corpus(args.corpus)
    graded = grading.grade_records(cases, grading.load_records(args.records))
    summary = report.summarize(graded)
    if args.json:
        print(json.dumps({"summary": summary, "win_rule": report.verdict_on_win_rule(summary)}, indent=2, sort_keys=True))
        return 0
    print(report.markdown_table(summary))
    if args.per_case:
        print()
        print(report.per_case_table(graded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
