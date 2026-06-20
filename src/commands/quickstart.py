from __future__ import annotations

import argparse
import os
import sys

from ..quickstart import build_quickstart_card
from .common import _paths, _print_json, _wants_json


def cmd_quickstart(args: argparse.Namespace) -> int:
    card = build_quickstart_card(_paths(args), source=str(getattr(args, "source", "hermes") or "hermes"))
    if _wants_json(args):
        _print_json(card)
    else:
        _print_quickstart_card(card)
    return 0


def _print_quickstart_card(card: dict[str, object]) -> None:
    use_color = _use_color()
    status = str(card.get("status", "unknown"))
    local_status = card.get("local_status", {})
    if not isinstance(local_status, dict):
        local_status = {}
    doctor = local_status.get("doctor", {})
    plugin_bridge = local_status.get("plugin_bridge", {})
    wrapper_usage = local_status.get("wrapper_usage", {})
    target_topology = local_status.get("target_topology", {})
    if not isinstance(doctor, dict):
        doctor = {}
    if not isinstance(plugin_bridge, dict):
        plugin_bridge = {}
    if not isinstance(wrapper_usage, dict):
        wrapper_usage = {}
    if not isinstance(target_topology, dict):
        target_topology = {}

    print(_color("OMH quickstart", "1;36", use_color))
    print(_color("Summary", "1;32", use_color))
    print(f"  Status: {_status_label(status, use_color)}")
    print(f"  OMH version: {card.get('omh_version', '')}")
    print(f"  Local install: {doctor.get('status', 'unknown')} ({doctor.get('passing', 0)}/{doctor.get('total', 0)} checks)")
    print(f"  Plugin bridge: {_plugin_bridge_label(str(plugin_bridge.get('status', 'unknown')))}")
    print(f"  Live Hermes plugin use: {_observed_label(bool(local_status.get('plugin_runtime_active')), positive='observed', negative='not observed yet')}")
    print(f"  Wrapper usage: {_wrapper_usage_label(str(wrapper_usage.get('status', 'missing')))}")
    print(
        "  Target topology: "
        f"{target_topology.get('mode', 'unknown')} "
        f"({target_topology.get('known_target_count', 0)} known target(s))"
    )

    print(_color("Do this in Hermes", "1;32", use_color))
    for line in _string_list(card.get("first_five_minutes", [])):
        print(f"  - {line}")

    print(_color("Try one prompt", "1;32", use_color))
    for prompt in _dict_list(card.get("chat_prompts", []))[:3]:
        print(f"  - {prompt.get('label', 'prompt')}: {prompt.get('prompt', '')}")

    print(_color("Still not evidence", "1;32", use_color))
    for line in _string_list(card.get("not_evidence_yet", [])):
        print(f"  - {line}")

    actions = _dict_list(card.get("operator_next_actions", []))
    if actions:
        print(_color("Operator next actions", "1;32", use_color))
        for action in actions[:4]:
            print(f"  - {action.get('label', 'Next')}: {action.get('next', '')}")
    print("  For machine-readable output, rerun with `--json`.")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _status_label(status: str, use_color: bool) -> str:
    if status == "ready":
        return _color("ready", "1;32", use_color)
    if status == "needs_attention":
        return _color("needs attention", "1;33", use_color)
    return status


def _plugin_bridge_label(status: str) -> str:
    if status == "ready_locally":
        return "ready locally"
    return status.replace("_", " ")


def _wrapper_usage_label(status: str) -> str:
    if status == "available":
        return "recorded"
    if status == "missing":
        return "not recorded yet"
    return status


def _observed_label(observed: bool, *, positive: str, negative: str) -> str:
    return positive if observed else negative


def _use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _add_quickstart_commands(sub) -> None:
    quickstart = sub.add_parser(
        "quickstart",
        help="Show the first-use OMH/Hermes path and current evidence boundaries.",
    )
    quickstart.add_argument("--json", action="store_true", help="Print the full machine-readable quickstart card.")
    quickstart.add_argument(
        "--source",
        default="hermes",
        choices=("hermes", "discord", "slack", "telegram", "terminal", "wrapper"),
        help="Surface that will render the card.",
    )
    quickstart.set_defaults(func=cmd_quickstart)
