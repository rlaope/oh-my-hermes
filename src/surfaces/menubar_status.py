from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ..executors import executor_label
from ..hud import build_hud_payload
from ..local_store import read_json_object
from ..paths import OmhPaths
from ..runtime.artifacts import summarize_delegated_coding_status
from ..routing.action_copy import next_action_label
from ..targets import read_target_registry_result


MENUBAR_STATUS_SCHEMA_VERSION = "menubar_status/v1"
PROCESS_OVERLAY_SCHEMA_VERSION = "menubar_process_overlay/v1"
DEFAULT_PROCESS_OVERLAY_TTL_SECONDS = 10
DEFAULT_RESTART_WINDOW_SECONDS = 20
_OBSERVED_PROCESS_STATUSES = {"running", "restarting"}

_SOURCE_ICON_LABELS = {
    "source.discord": "Discord",
    "source.slack": "Slack",
    "source.telegram": "Telegram",
    "source.whatsapp": "WhatsApp",
    "source.signal": "Signal",
    "source.hermes": "Hermes",
    "source.cli": "CLI",
    "source.local": "Local",
    "source.unknown": "Unknown source",
}

_MODEL_ICON_LABELS = {
    "model.openai": "OpenAI",
    "model.anthropic": "Anthropic",
    "model.google": "Google",
    "model.local": "Local model",
    "model.other": "Other model",
    "model.unknown": "Model not observed",
}


def build_menubar_status_payload(
    paths: OmhPaths,
    *,
    limit: int = 3,
    process_overlay: dict[str, Any] | None = None,
    observe_local_processes: bool = False,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, default=3)
    hud = build_hud_payload(paths, preset="full", limit=safe_limit)
    hermes_agents = _hermes_agent_rows(paths)
    external_executors = _external_executor_rows(paths, limit=safe_limit)
    current_executor, current_executor_source = _select_current_external_executor(paths, external_executors)
    if observe_local_processes and process_overlay is None:
        process_overlay = _local_process_overlay(hermes_agents, now=now)
    overlay_summary = _apply_process_overlay(
        hermes_agents,
        external_executors,
        process_overlay=process_overlay,
        now=now,
    )
    settings = _settings(hud, hermes_agents, current_executor)
    return {
        "schema_version": MENUBAR_STATUS_SCHEMA_VERSION,
        "package": "oh-my-hermes",
        "omh_home": str(paths.omh_home),
        "hermes_home": str(paths.hermes_home),
        "display": _display(settings, hermes_agents, current_executor),
        "sections": {
            "hermes_agents": {
                "title": "Hermes agents",
                "empty_label": "No Hermes target observed",
            },
            "external_coding_executors": {
                "title": "External coding executors",
                "empty_label": "No coding agent activity observed",
            },
            "settings": {
                "title": "Settings",
            },
        },
        "hermes_agents": hermes_agents,
        "external_coding_executors": external_executors,
        "current_external_coding_executor": _current_external_executor_payload(
            current_executor,
            selection_source=current_executor_source,
        ),
        "process_overlay": overlay_summary,
        "versions": _versions(hud),
        "settings": settings,
        "icon_contract": {
            "source_icons": _icon_catalog(_SOURCE_ICON_LABELS),
            "model_icons": _icon_catalog(_MODEL_ICON_LABELS),
            "rendering_rule": "Render source and model as icons in compact surfaces; expose tooltip text on hover or focus.",
        },
        "evidence_boundary": (
            "menubar_status/v1 is a metadata-only view projection unless a caller overlay or explicit local process "
            "observation is applied. Configured Hermes targets and prepared coding-agent actions are not execution, "
            "verification, review, CI, merge, or PID evidence."
        ),
        "privacy": "metadata_only",
    }


def read_process_overlay_file(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise ValueError(f"could not read process overlay: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("process overlay must be a JSON object")
    schema = str(data.get("schema_version", "") or "")
    if schema != PROCESS_OVERLAY_SCHEMA_VERSION:
        raise ValueError(f"unsupported process overlay schema: {schema!r}")
    return data


def _local_process_overlay(hermes_agents: list[dict[str, Any]], *, now: datetime | str | None) -> dict[str, Any] | None:
    observed_at = _coerce_datetime(now) or datetime.now(timezone.utc)
    processes = _local_hermes_process_rows()
    overlay_agents: list[dict[str, Any]] = []
    if len(hermes_agents) == 1 and processes:
        process = processes[0]
        overlay_agents.append(
            {
                "id": str(hermes_agents[0].get("id", "") or ""),
                "pid": process["pid"],
                "status": "running",
                "summary": f"Hermes process observed locally: PID {process['pid']}.",
            }
        )
    elif len(hermes_agents) > 1 and len(hermes_agents) == len(processes):
        for agent, process in zip(hermes_agents, processes, strict=False):
            overlay_agents.append(
                {
                    "id": str(agent.get("id", "") or ""),
                    "pid": process["pid"],
                    "status": "running",
                    "summary": f"Hermes process observed locally: PID {process['pid']}.",
                }
            )
    return {
        "schema_version": PROCESS_OVERLAY_SCHEMA_VERSION,
        "source": "local_process_scan",
        "observed_at": _format_datetime(observed_at),
        "ttl_seconds": DEFAULT_PROCESS_OVERLAY_TTL_SECONDS,
        "restart_window_seconds": DEFAULT_RESTART_WINDOW_SECONDS,
        "agents": overlay_agents,
    }


def _local_hermes_process_rows() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,stat=,command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, stat, command = parts
        if not _looks_like_hermes_runtime_process(command):
            continue
        parsed_pid = _positive_int(pid, 0)
        if not parsed_pid:
            continue
        rows.append({"pid": parsed_pid, "stat": stat, "command": command})
    return rows


def _looks_like_hermes_runtime_process(command: str) -> bool:
    padded = f" {command} "
    return " -m hermes_cli.main " in padded or "hermes_cli.main gateway run" in command


def _hermes_agent_rows(paths: OmhPaths) -> list[dict[str, Any]]:
    registry, error = read_target_registry_result(paths)
    if error or not registry:
        return []
    targets = registry.get("targets", {})
    if not isinstance(targets, dict):
        return []
    rows = [_hermes_agent_row(record) for _, record in sorted(targets.items()) if isinstance(record, dict)]
    return rows


def _hermes_agent_row(record: dict[str, Any]) -> dict[str, Any]:
    source = str(record.get("source", "") or "")
    return {
        "kind": "hermes_agent",
        "id": str(record.get("target_id", "")),
        "name": str(record.get("display_name", "") or "Hermes Agent"),
        "pid": None,
        "pid_label": "PID not observed",
        "pid_observed": False,
        "status": "configured",
        "status_label": "Configured",
        "status_observed": False,
        "summary": _hermes_agent_summary(record),
        "source": source_icon_descriptor(source, channel_ref=str(record.get("target_ref", "") or "")),
        "model": model_icon_descriptor(_model_value(record)),
        "is_hermes_agent": True,
        "evidence": {
            "state": "configured_not_process_observed",
            "source": "target_registry",
            "observed_at": str(record.get("observed_at", "") or ""),
        },
    }


def _external_executor_rows(paths: OmhPaths, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_id in _recent_run_ids(paths, limit=limit):
        try:
            status = summarize_delegated_coding_status(paths, run_id)
        except (FileNotFoundError, OSError, JSONDecodeError, ValueError):
            continue
        prepared = _dict(status.get("prepared"))
        executor_profile = str(prepared.get("executor_target", "") or "")
        if not executor_profile or executor_profile == "hermes":
            continue
        rows.append(_external_executor_row(status, executor_profile, _run_coding_record(paths, run_id)))
    return rows


def _external_executor_row(status: dict[str, Any], executor_profile: str, coding: dict[str, Any]) -> dict[str, Any]:
    prepared = _dict(status.get("prepared"))
    execution = _dict(status.get("execution"))
    source_metadata = _dict(status.get("source_metadata"))
    handoff = _dict(coding.get("executor_handoff"))
    source = str(status.get("source", "") or "")
    evidence_state = str(prepared.get("status") or "unknown")
    execution_observed = bool(execution.get("observed", False))
    row_status = "observed" if execution_observed else "prepared" if prepared.get("available") else "not_observed"
    evidence_next_action = str(status.get("next_action", "") or "")
    return {
        "kind": "external_coding_executor",
        "id": f"{executor_profile}:{status.get('run_id', '')}",
        "name": executor_label(executor_profile),
        "executor_profile": executor_profile,
        "is_hermes_agent": False,
        "pid": None,
        "pid_label": "PID not observed",
        "pid_observed": False,
        "status": row_status,
        "status_label": _external_executor_status_label(row_status),
        "status_observed": execution_observed,
        "summary": str(status.get("safe_summary", "") or _external_executor_summary(prepared, executor_profile, source_metadata)),
        "source": source_icon_descriptor(source, channel_ref=str(source_metadata.get("channel_ref", "") or "")),
        "model": model_icon_descriptor(_model_value(source_metadata)),
        "handoff": {
            "selected": True,
            "dispatch_policy": _dispatch_policy(status, coding),
            "dispatchable": bool(handoff.get("dispatchable", coding.get("dispatchable", False))),
            "workflow": str(prepared.get("workflow", "") or ""),
            "harness": str(prepared.get("harness", "") or ""),
        },
        "evidence": {
            "state": evidence_state,
            "run_id": str(status.get("run_id", "") or ""),
            "prepared_available": bool(prepared.get("available", False)),
            "execution_observed": execution_observed,
            "next_action": evidence_next_action,
            "next_action_label": next_action_label(evidence_next_action),
        },
    }


def source_icon_descriptor(source: str, *, channel_ref: str = "") -> dict[str, Any]:
    icon_id = _source_icon_id(source)
    label = _SOURCE_ICON_LABELS[icon_id]
    tooltip = f"{label}: {channel_ref}" if channel_ref else label
    return {
        "value": source or "unknown",
        "icon_id": icon_id,
        "tooltip": tooltip,
        "channel_ref": channel_ref,
    }


def model_icon_descriptor(model: str) -> dict[str, Any]:
    normalized = str(model or "").strip()
    icon_id = _model_icon_id(normalized)
    tooltip = normalized if normalized else _MODEL_ICON_LABELS[icon_id]
    return {
        "value": normalized or "unknown",
        "icon_id": icon_id,
        "tooltip": tooltip,
        "observed": bool(normalized),
    }


def _recent_run_ids(paths: OmhPaths, *, limit: int) -> list[str]:
    runs_dir = paths.runtime_runs_dir
    if not runs_dir.exists():
        return []
    run_ids: list[str] = []
    for run_json in sorted(runs_dir.glob("*/run.json"), reverse=True)[:limit]:
        try:
            run = read_json_object(run_json)
        except (OSError, JSONDecodeError, ValueError):
            continue
        if isinstance(run, dict):
            run_ids.append(str(run.get("run_id", "") or run_json.parent.name))
    return run_ids


def _run_coding_record(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    try:
        coding = read_json_object(paths.runtime_runs_dir / run_id / "coding_delegation.json")
    except (OSError, JSONDecodeError, ValueError):
        return {}
    return coding if isinstance(coding, dict) else {}


def _select_current_external_executor(
    paths: OmhPaths,
    external_executors: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    if not external_executors:
        return {}, "none"
    try:
        state = read_json_object(paths.runtime_state_path)
    except (OSError, JSONDecodeError, ValueError):
        state = None
    last_run_id = str(state.get("last_run_id", "") if isinstance(state, dict) else "")
    if last_run_id:
        for row in external_executors:
            if str(_dict(row.get("evidence")).get("run_id", "") or "") == last_run_id:
                return row, "runtime_state.last_run_id"
    return external_executors[0], "recent_runtime_runs[0]"


def _current_external_executor_payload(row: dict[str, Any], *, selection_source: str) -> dict[str, Any]:
    if not row:
        return {
            "selected": False,
            "selection_source": selection_source,
            "row_id": "",
            "run_id": "",
            "executor_profile": "",
        }
    return {
        "selected": True,
        "selection_source": selection_source,
        "row_id": str(row.get("id", "") or ""),
        "run_id": str(_dict(row.get("evidence")).get("run_id", "") or ""),
        "executor_profile": str(row.get("executor_profile", "") or ""),
        "name": str(row.get("name", "") or ""),
        "status": str(row.get("status", "") or ""),
        "status_label": str(row.get("status_label", "") or ""),
    }


def _settings(
    hud: dict[str, Any],
    hermes_agents: list[dict[str, Any]],
    current_executor_row: dict[str, Any],
) -> dict[str, Any]:
    plugin = _dict(hud.get("plugin"))
    topology = _dict(hud.get("target_topology"))
    executor = _dict(hud.get("executor"))
    current_executor = (
        str(current_executor_row.get("executor_profile", "") or "")
        if current_executor_row
        else str(executor.get("default", "") or "choose")
    )
    dispatch_policy = (
        str(_dict(current_executor_row.get("handoff")).get("dispatch_policy", "") or "ask_before_dispatch")
        if current_executor_row
        else str(executor.get("dispatch_policy", "") or "ask_before_dispatch")
    )
    return {
        "omh_connection": _setting(
            value=str(plugin.get("status", "") or "unknown"),
            label=_plugin_status_label(str(plugin.get("status", "") or "unknown")),
            raw=f"plugin:{plugin.get('status', 'unknown')}",
        ),
        "hermes_targets": _setting(
            value=_target_value(topology, hermes_agents),
            label=_target_label(topology, hermes_agents),
            raw=f"target:{_target_value(topology, hermes_agents)}",
        ),
        "coding_handoff": _setting(
            value=current_executor,
            label=f"Coding agent: {_executor_setting_label(current_executor)}",
            raw=f"coding_agent:{current_executor}",
        ),
        "send_mode": _setting(
            value=dispatch_policy,
            label=_dispatch_policy_label(dispatch_policy, current_executor),
            raw=f"dispatch_policy:{dispatch_policy}",
        ),
    }


def _versions(hud: dict[str, Any]) -> dict[str, Any]:
    omh_version = str(hud.get("version", "") or "unknown")
    return {
        "omh": {
            "value": omh_version,
            "label": f"OMH version: {omh_version}",
            "observed": omh_version != "unknown",
        },
        "hermes": {
            "value": "unknown",
            "label": "Hermes version: Not observed",
            "observed": False,
        },
    }


def _display(
    settings: dict[str, Any],
    hermes_agents: list[dict[str, Any]],
    current_executor_row: dict[str, Any],
) -> dict[str, Any]:
    headline = "OMH ready" if settings["omh_connection"]["value"] == "ready" else "OMH needs attention"
    pieces = [f"{len(hermes_agents)} Hermes target(s)"]
    if current_executor_row:
        pieces.append(f"{current_executor_row['name']} {current_executor_row['status_label'].lower()}")
    else:
        pieces.append("coding agent idle")
    return {
        "menu_title": "omh",
        "headline": headline,
        "summary_line": " · ".join(pieces),
        "menu_cards": _menu_cards(settings, hermes_agents, current_executor_row),
    }


def _menu_cards(
    settings: dict[str, Any],
    hermes_agents: list[dict[str, Any]],
    current_executor_row: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "title": "Agent Status",
            "columns": ["Agent", "PID", "Status"],
            "rows": _agent_status_menu_rows(hermes_agents),
            "footer": "PID appears after overlay or explicit local observation.",
        },
        {
            "title": "Coding Agent",
            "rows": _coding_menu_rows(settings, current_executor_row),
        },
        {
            "title": "Evidence",
            "rows": [
                _menu_row("Boundary", _evidence_menu_value(hermes_agents, current_executor_row)),
                _menu_row("Next", _evidence_next_action(current_executor_row)),
            ],
        },
    ]


def _menu_row(label: str, value: str, *, detail: str = "", tone: str = "neutral") -> dict[str, str]:
    row = {"label": label, "value": value, "tone": tone}
    if detail:
        row["detail"] = detail
    return row


def _agent_status_row(agent: str, pid: str, status: str, *, tone: str = "neutral") -> dict[str, str]:
    return {
        "kind": "agent_status",
        "agent": agent,
        "pid": pid,
        "status": status,
        "tone": tone,
    }


def _setting_value(settings: dict[str, Any], key: str, *, default: str = "") -> str:
    row = _dict(settings.get(key))
    return str(row.get("value", "") or default)


def _coding_agent_menu_value(settings: dict[str, Any], current_executor_row: dict[str, Any]) -> str:
    if current_executor_row:
        return str(current_executor_row.get("name", "") or "selected")
    return _executor_setting_label(_setting_value(settings, "coding_handoff", default="choose"))


def _agent_status_menu_rows(hermes_agents: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not hermes_agents:
        return [_agent_status_row("none", "not observed", "run setup")]
    rows: list[dict[str, str]] = []
    for agent in hermes_agents[:3]:
        name = _short_text(str(agent.get("name", "") or "Hermes Agent"), limit=28)
        status = str(agent.get("status_label", "") or agent.get("status", "") or "configured")
        pid = _pid_menu_value(agent)
        rows.append(
            _agent_status_row(
                name,
                pid,
                status,
                tone="ok" if agent.get("status_observed") or agent.get("pid_observed") else "neutral",
            )
        )
    if len(hermes_agents) > 3:
        rows.append(_agent_status_row(f"+{len(hermes_agents) - 3} more", "not shown", "hidden"))
    return rows


def _coding_menu_rows(settings: dict[str, Any], current_executor_row: dict[str, Any]) -> list[dict[str, str]]:
    if current_executor_row:
        name = str(current_executor_row.get("name", "") or "Coding agent")
        status = str(current_executor_row.get("status_label", "") or current_executor_row.get("status", "") or "prepared")
        rows = [
            _menu_row("Agent", name),
            _menu_row("Status", status),
            _menu_row("PID", _pid_menu_value(current_executor_row)),
        ]
        next_action = str(_dict(current_executor_row.get("evidence")).get("next_action", "") or "")
        if next_action:
            rows.append(_menu_row("Next", _human_next_action(next_action)))
        return rows
    dispatch = _setting_value(settings, "send_mode", default="ask_before_dispatch")
    return [
        _menu_row("Agent", _coding_agent_menu_value(settings, current_executor_row)),
        _menu_row("Status", "idle", detail="no coding agent selected"),
        _menu_row("Open mode", _dispatch_policy_menu_value(dispatch, _setting_value(settings, "coding_handoff"))),
    ]


def _dispatch_policy_menu_value(dispatch_policy: str, executor: str) -> str:
    label = _dispatch_policy_label(dispatch_policy, executor)
    prefix = "Open mode: "
    return label[len(prefix) :] if label.startswith(prefix) else label


def _pid_menu_value(row: dict[str, Any]) -> str:
    if row.get("pid_observed") and row.get("pid"):
        return str(row.get("pid"))
    return "not observed"


def _evidence_menu_value(hermes_agents: list[dict[str, Any]], current_executor_row: dict[str, Any]) -> str:
    observed_agents = sum(1 for row in hermes_agents if row.get("status_observed") or row.get("pid_observed"))
    if current_executor_row:
        evidence = _dict(current_executor_row.get("evidence"))
        state = str(evidence.get("state", "") or "prepared_not_observed")
        return _short_text(state.replace("_", " "), limit=32)
    if observed_agents:
        return f"{observed_agents} process observed"
    return "metadata only"


def _evidence_next_action(current_executor_row: dict[str, Any]) -> str:
    if current_executor_row:
        evidence = _dict(current_executor_row.get("evidence"))
        next_action = str(evidence.get("next_action", "") or "")
        if next_action:
            return _human_next_action(next_action)
    return "open Hermes or run omh doctor"


def _human_next_action(next_action: str) -> str:
    label = next_action_label(next_action)
    return _short_text(label or next_action, limit=48)


def _short_text(value: str, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _source_icon_id(source: str) -> str:
    normalized = source.strip().lower()
    if "discord" in normalized:
        return "source.discord"
    if "slack" in normalized:
        return "source.slack"
    if "telegram" in normalized:
        return "source.telegram"
    if "whatsapp" in normalized:
        return "source.whatsapp"
    if "signal" in normalized:
        return "source.signal"
    if "hermes" in normalized:
        return "source.hermes"
    if "cli" in normalized:
        return "source.cli"
    if normalized in {"setup", "local", "generic"}:
        return "source.local"
    return "source.unknown"


def _model_icon_id(model: str) -> str:
    normalized = model.strip().lower()
    if not normalized:
        return "model.unknown"
    if normalized.startswith(("gpt-", "o1", "o3", "o4", "o5")) or "openai" in normalized:
        return "model.openai"
    if "claude" in normalized or "anthropic" in normalized:
        return "model.anthropic"
    if "gemini" in normalized or "google" in normalized:
        return "model.google"
    if any(token in normalized for token in ("local", "ollama", "lm studio", "lmstudio")):
        return "model.local"
    return "model.other"


def _icon_catalog(labels: dict[str, str]) -> list[dict[str, str]]:
    return [{"icon_id": icon_id, "label": label} for icon_id, label in sorted(labels.items())]


def _hermes_agent_summary(record: dict[str, Any]) -> str:
    source = source_icon_descriptor(str(record.get("source", "") or ""), channel_ref=str(record.get("target_ref", "") or ""))
    return f"Hermes target configured from {source['tooltip']}; process status is not observed."


def _external_executor_summary(prepared: dict[str, Any], executor_profile: str, source_metadata: dict[str, Any]) -> str:
    workflow = str(prepared.get("workflow", "") or "workflow")
    channel_ref = str(source_metadata.get("channel_ref", "") or "")
    channel = f" in channel {channel_ref}" if channel_ref else ""
    return f"{executor_label(executor_profile)} handoff prepared for {workflow}{channel}; execution is not observed."


def _apply_process_overlay(
    hermes_agents: list[dict[str, Any]],
    external_executors: list[dict[str, Any]],
    *,
    process_overlay: dict[str, Any] | None,
    now: datetime | str | None,
) -> dict[str, Any]:
    if not process_overlay:
        return _overlay_summary("not_supplied")
    schema = str(process_overlay.get("schema_version", "") or "")
    if schema != PROCESS_OVERLAY_SCHEMA_VERSION:
        return _overlay_summary("invalid", errors=[f"unsupported process overlay schema: {schema!r}"])
    observed_at = _parse_datetime(str(process_overlay.get("observed_at", "") or ""))
    if observed_at is None:
        return _overlay_summary("invalid", errors=["process overlay observed_at must be an ISO timestamp"])
    current = _coerce_datetime(now)
    if now is not None and current is None:
        return _overlay_summary("invalid", errors=["process overlay now must be an ISO timestamp"])
    if current is None:
        current = datetime.now(timezone.utc)
    age_seconds = max(0.0, (current - observed_at).total_seconds())
    ttl_seconds = _positive_int(process_overlay.get("ttl_seconds"), DEFAULT_PROCESS_OVERLAY_TTL_SECONDS)
    restart_window_seconds = _positive_int(process_overlay.get("restart_window_seconds"), DEFAULT_RESTART_WINDOW_SECONDS)
    if age_seconds > ttl_seconds:
        return _overlay_summary(
            "expired",
            observed_at=observed_at,
            age_seconds=age_seconds,
            ttl_seconds=ttl_seconds,
            restart_window_seconds=restart_window_seconds,
        )
    overlay_rows = _overlay_rows(process_overlay)
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = _external_overlay_identity_skips(overlay_rows, external_executors)
    for row in hermes_agents:
        _apply_overlay_to_row(
            row,
            overlay_rows,
            kind="hermes_agent",
            observed_at=observed_at,
            age_seconds=age_seconds,
            ttl_seconds=ttl_seconds,
            restart_window_seconds=restart_window_seconds,
            applied=applied,
            skipped=skipped,
        )
    for row in external_executors:
        _apply_overlay_to_row(
            row,
            overlay_rows,
            kind="external_coding_executor",
            observed_at=observed_at,
            age_seconds=age_seconds,
            ttl_seconds=ttl_seconds,
            restart_window_seconds=restart_window_seconds,
            applied=applied,
            skipped=skipped,
        )
    return _overlay_summary(
        "applied",
        observed_at=observed_at,
        age_seconds=age_seconds,
        ttl_seconds=ttl_seconds,
        restart_window_seconds=restart_window_seconds,
        applied=applied,
        skipped=skipped,
    )


def _apply_overlay_to_row(
    row: dict[str, Any],
    overlay_rows: list[dict[str, Any]],
    *,
    kind: str,
    observed_at: datetime,
    age_seconds: float,
    ttl_seconds: int,
    restart_window_seconds: int,
    applied: list[dict[str, str]],
    skipped: list[dict[str, str]],
) -> None:
    overlay = _matching_overlay(row, overlay_rows, kind=kind)
    if not overlay:
        return
    status = str(overlay.get("status", "") or "").strip().lower()
    if status not in _OBSERVED_PROCESS_STATUSES:
        skipped.append({"row_id": str(row.get("id", "")), "reason": "unsupported_status"})
        return
    if status == "restarting" and age_seconds > restart_window_seconds:
        skipped.append({"row_id": str(row.get("id", "")), "reason": "restart_window_expired"})
        return
    pid = _positive_int(overlay.get("pid"), 0)
    if pid:
        row["pid"] = pid
        row["pid_label"] = f"PID {pid}"
        row["pid_observed"] = True
    row["status"] = status
    row["status_label"] = status.title()
    row["status_observed"] = True
    summary = str(overlay.get("summary", "") or "").strip()
    if summary:
        row["summary"] = summary
    model = _model_value(overlay)
    if model:
        row["model"] = model_icon_descriptor(model)
    evidence = _dict(row.get("evidence"))
    evidence["process_overlay"] = {
        "schema_version": PROCESS_OVERLAY_SCHEMA_VERSION,
        "state": "observed",
        "observed_at": _format_datetime(observed_at),
        "age_seconds": round(age_seconds, 3),
        "ttl_seconds": ttl_seconds,
        "restart_window_seconds": restart_window_seconds,
    }
    row["evidence"] = evidence
    applied.append({"row_id": str(row.get("id", "")), "status": status})


def _overlay_rows(process_overlay: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _list(process_overlay.get("items")):
        rows.append(item)
    for item in _list(process_overlay.get("agents")):
        rows.append({"kind": "hermes_agent", **item})
    for item in _list(process_overlay.get("hermes_agents")):
        rows.append({"kind": "hermes_agent", **item})
    for item in _list(process_overlay.get("external_coding_executors")):
        rows.append({"kind": "external_coding_executor", **item})
    return rows


def _matching_overlay(row: dict[str, Any], overlay_rows: list[dict[str, Any]], *, kind: str) -> dict[str, Any]:
    row_id = str(row.get("id", "") or "")
    name = str(row.get("name", "") or "")
    executor_profile = str(row.get("executor_profile", "") or "")
    run_id = str(_dict(row.get("evidence")).get("run_id", "") or "")
    for overlay in overlay_rows:
        if str(overlay.get("kind", "") or "") != kind:
            continue
        overlay_id = str(overlay.get("id", "") or "")
        if overlay_id and overlay_id == row_id:
            return overlay
        if kind == "external_coding_executor":
            overlay_profile = str(overlay.get("executor_profile", "") or "")
            overlay_run_id = str(overlay.get("run_id", "") or "")
            if overlay_profile == executor_profile and overlay_run_id and overlay_run_id == run_id:
                return overlay
            continue
        overlay_name = str(overlay.get("name", "") or "")
        if overlay_name and overlay_name == name:
            return overlay
    return {}


def _external_overlay_identity_skips(
    overlay_rows: list[dict[str, Any]],
    external_executors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    executor_profiles = {str(row.get("executor_profile", "") or "") for row in external_executors}
    skipped: list[dict[str, str]] = []
    for overlay in overlay_rows:
        if str(overlay.get("kind", "") or "") != "external_coding_executor":
            continue
        if str(overlay.get("id", "") or "") or str(overlay.get("run_id", "") or ""):
            continue
        profile = str(overlay.get("executor_profile", "") or "")
        if profile and profile in executor_profiles:
            skipped.append(
                {
                    "row_id": "",
                    "reason": "external_executor_run_id_required",
                    "executor_profile": profile,
                }
            )
    return skipped


def _overlay_summary(
    status: str,
    *,
    observed_at: datetime | None = None,
    age_seconds: float | None = None,
    ttl_seconds: int = DEFAULT_PROCESS_OVERLAY_TTL_SECONDS,
    restart_window_seconds: int = DEFAULT_RESTART_WINDOW_SECONDS,
    applied: list[dict[str, str]] | None = None,
    skipped: list[dict[str, str]] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PROCESS_OVERLAY_SCHEMA_VERSION,
        "status": status,
        "observed_at": _format_datetime(observed_at) if observed_at else "",
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "ttl_seconds": ttl_seconds,
        "restart_window_seconds": restart_window_seconds,
        "applied_count": len(applied or []),
        "skipped_count": len(skipped or []),
        "applied": applied or [],
        "skipped": skipped or [],
        "errors": errors or [],
        "claim_boundary": (
            "Process status is applied only from a caller-provided overlay or explicit local process observation. "
            "Plain `omh menubar status` does not scan processes or infer PID state."
        ),
    }


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return _parse_datetime(str(value))


def _format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _external_executor_status_label(status: str) -> str:
    labels = {
        "observed": "Observed",
        "prepared": "Prepared",
        "not_observed": "Not observed",
    }
    return labels.get(status, status.replace("_", " ").title())


def _dispatch_policy(status: dict[str, Any], coding: dict[str, Any]) -> str:
    prepared = _dict(status.get("prepared"))
    handoff = _dict(status.get("handoff_contract"))
    raw_handoff = _dict(coding.get("executor_handoff"))
    for source in (raw_handoff, coding, handoff, prepared):
        value = str(source.get("dispatch_policy", "") or "")
        if value:
            return value
    return "ask_before_dispatch"


def _plugin_status_label(status: str) -> str:
    labels = {
        "ready": "OMH connection: Ready",
        "stale": "OMH connection: Update needed",
        "installed": "OMH connection: Installed",
        "missing": "OMH connection: Not installed",
        "unknown": "OMH connection: Unknown",
    }
    return labels.get(status, f"OMH connection: {status.replace('_', ' ').title()}")


def _target_value(topology: dict[str, Any], hermes_agents: list[dict[str, Any]]) -> str:
    count = _safe_int(topology.get("active_agent_count"), len(hermes_agents))
    if count > 1:
        return f"multi:{count}"
    if count == 1:
        return "single:1"
    return "none"


def _target_label(topology: dict[str, Any], hermes_agents: list[dict[str, Any]]) -> str:
    count = _safe_int(topology.get("active_agent_count"), len(hermes_agents))
    if count == 0:
        return "Hermes targets: None observed"
    return f"Hermes targets: {count}"


def _executor_setting_label(executor_profile: str) -> str:
    if executor_profile == "choose":
        return "Ask each time"
    return executor_label(executor_profile)


def _dispatch_policy_label(dispatch_policy: str, executor_profile: str) -> str:
    if dispatch_policy == "ask_before_dispatch":
        target = executor_label(executor_profile)
        return f"Open mode: Ask before opening {target}" if executor_profile != "choose" else "Open mode: Ask before choosing"
    if dispatch_policy == "prepare_only":
        return "Open mode: Prepare only"
    if dispatch_policy == "configured_auto_dispatch_reserved":
        return "Open mode: Auto dispatch reserved"
    return f"Open mode: {dispatch_policy.replace('_', ' ')}"


def _setting(*, value: str, label: str, raw: str) -> dict[str, str]:
    return {
        "value": value,
        "label": label,
        "raw": raw,
    }


def _model_value(record: dict[str, Any]) -> str:
    for key in ("model", "model_ref", "model_name", "model_id"):
        value = str(record.get(key, "") or "").strip()
        if value:
            return value
    provider = str(record.get("model_provider", "") or "").strip()
    return provider


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_limit(value: Any, *, default: int, maximum: int = 20) -> int:
    return max(0, min(_safe_int(value, default), maximum))
