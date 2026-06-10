from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.wrapper.contract import INTERACTION_MODES, build_chat_interaction_payload, build_chat_status_interaction  # noqa: E402


SCHEMA_VERSION = "wrapper_adapter_shim/v1"


def run_shim(source: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"Render a {source} Hermes chat fixture.")
    parser.add_argument(
        "event_json",
        nargs="?",
        default=str(_default_fixture(source)),
        help="Fixture event JSON path for the Hermes chat contract example.",
    )
    parser.add_argument("--mode", choices=INTERACTION_MODES, default="auto")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument(
        "--status-json",
        default=None,
        help="Optional delegated_coding_status/v1 JSON to render as a status card instead of routing the event.",
    )
    args = parser.parse_args(argv)

    if args.status_json:
        status_payload = _read_json(Path(args.status_json))
        interaction = build_chat_status_interaction(status_payload, source=source)
    else:
        event = _read_json(Path(args.event_json))
        interaction = build_chat_interaction_payload(event, source=source, mode=args.mode, limit=args.limit)
    print(json.dumps(_render(source, interaction), indent=2, sort_keys=True))
    return 0


def _default_fixture(source: str) -> Path:
    filename = "discord-safe-feature.json" if source == "discord" else "slack-risky-refactor.json"
    return Path(__file__).resolve().parent / "wrapper-events" / filename


def _read_json(path: Path) -> dict[str, Any]:
    with path.expanduser().resolve().open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"fixture must be a JSON object: {path}")
    return payload


def _render(source: str, interaction: dict[str, object]) -> dict[str, object]:
    response = _nested(interaction, "chat_response")
    state = _nested(response, "state")
    status_card = response.get("status_card") or interaction.get("status_card")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "thread_key": interaction.get("thread_key", ""),
        "mode": interaction.get("mode", ""),
        "next_action": interaction.get("next_action", ""),
        "redaction_policy": interaction.get("redaction_policy", "metadata_only"),
        "source_metadata": interaction.get("source_metadata", {}),
        "response": {
            "kind": response.get("kind", ""),
            "headline": response.get("headline", ""),
            "body": response.get("body", ""),
            "phase": state.get("phase", ""),
            "claim_boundary": response.get("claim_boundary", ""),
        },
        "actions": [
            {
                "id": action.get("id", ""),
                "label": action.get("label", ""),
                "enabled": action.get("enabled", False),
                "style": action.get("style", ""),
            }
            for action in _list_of_dicts(response.get("actions", []))
        ],
        "status_card": status_card if isinstance(status_card, dict) else None,
        "not_evidence_until_observed": [
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "ci",
            "merge",
        ],
    }


def _nested(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
