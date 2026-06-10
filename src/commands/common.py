from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..ingress import extract_message_text, extract_source_metadata
from ..installer import OmhError
from ..paths import resolve_paths
from ..setup_profiles import read_setup_profile
from ..targets import TARGET_METADATA_KEYS


def _paths(args: argparse.Namespace):
    return resolve_paths(args.omh_home, args.hermes_home, scope=getattr(args, "scope", None))


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _wants_json(args: argparse.Namespace) -> bool:
    output = os.environ.get("OMH_OUTPUT", "").strip().lower()
    return bool(getattr(args, "json", False)) or output == "json"


def _explicit_source_metadata(args: argparse.Namespace) -> dict[str, str]:
    values = {
        "source_event_id": getattr(args, "source_event_id", ""),
        "channel_ref": getattr(args, "channel_ref", ""),
        "user_ref": getattr(args, "user_ref", ""),
    }
    values.update({key: getattr(args, key, "") for key in TARGET_METADATA_KEYS if key != "hermes_home"})
    return {key: str(value) for key, value in values.items() if value}


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
