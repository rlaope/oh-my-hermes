from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ingress import extract_message_text, extract_source_metadata
from ..installer import OmhError
from ..paths import resolve_paths
from ..setup_profiles import read_setup_profile


def _paths(args: argparse.Namespace):
    return resolve_paths(args.omh_home, args.hermes_home)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _explicit_source_metadata(args: argparse.Namespace) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "source_event_id": args.source_event_id,
            "channel_ref": args.channel_ref,
            "user_ref": args.user_ref,
        }.items()
        if value
    }


def _resolved_executor(args: argparse.Namespace, *, default: str) -> str:
    explicit = getattr(args, "executor", None)
    if explicit:
        return str(explicit)
    try:
        profile = read_setup_profile(_paths(args))
    except (OSError, json.JSONDecodeError, ValueError):
        profile = None
    if isinstance(profile, dict):
        executor = str(profile.get("default_executor", ""))
        if executor:
            return executor
    return default


def _chat_input_and_metadata(args: argparse.Namespace) -> tuple[dict[str, object] | str, dict[str, str]]:
    try:
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError("chat event must be an object")
            metadata = extract_source_metadata(event)
            metadata.update(_explicit_source_metadata(args))
            return event, metadata
        if args.stdin:
            return sys.stdin.read().strip(), _explicit_source_metadata(args)
        return " ".join(args.message).strip(), _explicit_source_metadata(args)
    except (OSError, json.JSONDecodeError, ValueError):
        raise


def _chat_message(args: argparse.Namespace) -> str:
    try:
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            return extract_message_text(json.loads(raw))
        if args.stdin:
            return sys.stdin.read().strip()
        return " ".join(args.message).strip()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
