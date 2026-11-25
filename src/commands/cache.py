from __future__ import annotations

import argparse
import sys

from ..maintenance.cache_report import CacheReportError, build_cache_report, render_cache_report
from .common import _paths, _print_json, _wants_json


def cmd_cache(args: argparse.Namespace) -> int:
    if args.days <= 0:
        print("omh cache: --days must be positive", file=sys.stderr)
        return 2
    try:
        report = build_cache_report(_paths(args).hermes_home, days=args.days)
    except CacheReportError as exc:
        print(f"omh cache: {exc}", file=sys.stderr)
        return 1
    if _wants_json(args):
        _print_json(report)
    else:
        print(render_cache_report(report))
    return 0


def _add_cache_commands(sub) -> None:
    cache = sub.add_parser(
        "cache",
        help="Report prompt-cache read share, idle gaps and cron cache writes from the profile's state.db (read-only).",
    )
    cache.add_argument("--days", type=float, default=7, help="Window in days, counted back from now (default 7).")
    cache.add_argument("--json", action="store_true", help="Print the machine-readable report.")
    cache.set_defaults(func=cmd_cache)
