from __future__ import annotations

import argparse
import time
from typing import Any

from ..hud import build_hud_payload
from .common import _paths, _print_json, _wants_json


def cmd_hud(args: argparse.Namespace) -> int:
    payload = _hud_payload(args)
    if _wants_json(args):
        _print_json(payload)
    else:
        print(payload["display"]["line"])
    if not getattr(args, "watch", False):
        return 0
    while True:
        time.sleep(max(0.2, float(args.interval)))
        payload = _hud_payload(args)
        if _wants_json(args):
            _print_json(payload)
        else:
            print(payload["display"]["line"], flush=True)


def _hud_payload(args: argparse.Namespace) -> dict[str, Any]:
    return build_hud_payload(
        _paths(args),
        preset=args.preset,
        limit=args.limit,
        token_metadata=_token_metadata(args),
    )


def _token_metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "tokens_remaining": args.tokens_remaining,
            "token_budget": args.token_budget,
            "input_tokens": args.input_tokens,
            "output_tokens": args.output_tokens,
            "context_remaining_percent": args.context_remaining_percent,
        }.items()
        if value is not None
    }


def _add_hud_commands(sub) -> None:
    hud = sub.add_parser("hud", help="Print the compact OMH status line that Hermes TUI/plugin surfaces can render.")
    hud.add_argument("--preset", choices=("minimal", "focused", "full"), default="focused")
    hud.add_argument("--limit", type=int, default=3, help="Maximum recent runtime runs to inspect.")
    hud.add_argument("--tokens-remaining", type=float, default=None, help="Optional host-provided token metadata.")
    hud.add_argument("--token-budget", type=float, default=None, help="Optional host-provided token budget metadata.")
    hud.add_argument("--input-tokens", type=float, default=None, help="Optional host-provided input token metadata.")
    hud.add_argument("--output-tokens", type=float, default=None, help="Optional host-provided output token metadata.")
    hud.add_argument("--context-remaining-percent", type=float, default=None, help="Optional host-provided context remaining percentage.")
    hud.add_argument("--watch", action="store_true", help="Keep printing the HUD line until interrupted.")
    hud.add_argument("--interval", type=float, default=2.0, help="Seconds between --watch refreshes.")
    hud.add_argument("--json", action="store_true", help="Print the full machine-readable HUD payload.")
    hud.set_defaults(func=cmd_hud)
