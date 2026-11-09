from __future__ import annotations

import json
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from ..plugin_bundle.omh.run_records import CODING_DELEGATION_FILE
from ..executors import executor_label
from ..hud import build_hud_payload
from ..local_store import read_json_object, read_runtime_record
from ..paths import OmhPaths
from ..runtime.artifacts import summarize_delegated_coding_status
from ..routing.action_copy import next_action_label
from ..targets import read_target_registry_result
from .hermes_model_settings import HERMES_AUX_ALIASES, read_hermes_model_settings
from .hermes_processes import HERMES_PROCESS_SCHEMA_VERSION, observe_hermes_processes
from .hermes_sessions import hermes_state_watch_paths, observe_hermes_sessions
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat


MENUBAR_STATUS_SCHEMA_VERSION = "menubar_status/v2"
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
    hermes_sessions = observe_hermes_sessions(paths, now=now)
    model_settings = read_hermes_model_settings(paths)
    hermes_processes = (
        observe_hermes_processes(now=now) if observe_local_processes else _unrequested_process_observation(now=now)
    )
    if observe_local_processes and process_overlay is None:
        process_overlay = _local_process_overlay(hermes_agents, hermes_processes, now=now)
    overlay_summary = _apply_process_overlay(
        hermes_agents,
        external_executors,
        process_overlay=process_overlay,
        now=now,
    )
    settings = _settings(hud, hermes_agents, current_executor)
    settings["tui_runtime"] = tui_runtime_setting(paths)
    return {
        "schema_version": MENUBAR_STATUS_SCHEMA_VERSION,
        "package": "oh-my-hermes",
        "omh_home": str(paths.omh_home),
        "hermes_home": str(paths.hermes_home),
        "watch_paths": menubar_watch_paths(paths),
        "display": _display(settings, hermes_processes, hermes_sessions, model_settings, current_executor),
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
        "hermes_processes": hermes_processes,
        "hermes_sessions": hermes_sessions,
        "model_settings": model_settings,
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
            "menubar_status/v2 combines read-only Hermes state.db session observation and config.yaml model settings "
            "with metadata unless a caller overlay or explicit local process observation is applied. These sources "
            "are not execution, verification, review, CI, merge, token-usage, or PID evidence."
        ),
        "privacy": "metadata_only",
    }


def menubar_watch_paths(paths: OmhPaths) -> list[str]:
    """Files a poller can stat to notice a change without paying for a read.

    This is a latency hint, not the payload's input set. Building this
    payload costs about 0.7s, almost all of it interpreter start, importing
    the CLI, and the `ps` scan behind `--observe-local-processes`; every file
    it reads together costs about 4ms. So the menu bar helper backs its timer
    off while nothing changes, and stats these paths on a short tick to catch
    the one kind of change that happens while nobody is typing: Hermes
    session activity.

    The other inputs (`config.yaml`, `targets.json`, the routing files) move
    only because the operator just ran a command in a terminal they are
    already looking at, so the helper's backoff ceiling is soon enough for
    them and they stay off this list. Correctness does not rest here: the
    helper re-reads on its own ladder regardless of what these stamps say.
    """
    return [str(path) for path in hermes_state_watch_paths(paths)]


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


def _local_process_overlay(
    hermes_agents: list[dict[str, Any]],
    hermes_processes: dict[str, Any],
    *,
    now: datetime | str | None,
) -> dict[str, Any]:
    observed_at = (
        _parse_datetime(str(hermes_processes.get("observed_at", "") or ""))
        or _coerce_datetime(now)
        or datetime.now(timezone.utc)
    )
    processes = [row for row in _list(hermes_processes.get("rows")) if row.get("role") == "agent"]
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


def _unrequested_process_observation(*, now: datetime | str | None) -> dict[str, Any]:
    observed_at = _coerce_datetime(now) or datetime.now(timezone.utc)
    return {
        "schema_version": HERMES_PROCESS_SCHEMA_VERSION,
        "observed": False,
        "reason": "not_requested",
        "agent_count": 0,
        "process_count": 0,
        "rows": [],
        "source": "local_process_scan",
        "observed_at": _format_datetime(observed_at),
        "claim_boundary": (
            "Local process observation is bounded, best-effort, and is not execution, review, CI, or merge evidence."
        ),
    }


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
            run = read_runtime_record(run_json)
        except (OSError, JSONDecodeError, ValueError):
            continue
        if isinstance(run, dict):
            run_ids.append(str(run.get("run_id", "") or run_json.parent.name))
    return run_ids


def _run_coding_record(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    try:
        coding = read_runtime_record(paths.runtime_runs_dir / run_id / CODING_DELEGATION_FILE)
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
    coding_handoff = _setting(
        value=current_executor,
        label=f"Coding agent: {_executor_setting_label(current_executor)}",
        raw=f"coding_agent:{current_executor}",
    )
    coding_handoff["source"] = _coding_handoff_source(current_executor_row, current_executor)
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
        "coding_handoff": coding_handoff,
        "send_mode": _setting(
            value=dispatch_policy,
            label=_dispatch_policy_label(dispatch_policy, current_executor),
            raw=f"dispatch_policy:{dispatch_policy}",
        ),
    }


def tui_runtime_setting(paths: OmhPaths) -> dict[str, str]:
    """Where bare `omh` opens its sessions (`omh theme runtime`), and whether the TUI's own gateway runs now.

    `shared`: the Hermes gateway the bots use. `own` (the default): a TUI-only
    Hermes profile under the root (`tui/own_runtime.py`), its gateway's pid
    when it is live. Read-only, from the saved choice, the profile's marker and
    its record.
    """
    from ..skin_pack import RUNTIME_OWN, read_runtime_choice
    from ..tui.own_runtime import tui_home_status

    status = tui_home_status(Path(paths.hermes_home), read_runtime_choice(paths.omh_home))
    if status.runtime != RUNTIME_OWN:
        return _setting(value="shared", label="TUI runtime: shared gateway", raw="tui_runtime:shared")
    if status.gateway_live:
        label = f"TUI runtime: own (gateway pid {status.gateway_pid})"
    elif status.built:
        label = "TUI runtime: own (gateway idle)"
    else:
        label = "TUI runtime: own (home not built yet)"
    return _setting(value="own", label=label, raw=f"tui_runtime:own:{status.gateway_pid or 0}")


def _coding_handoff_source(current_executor_row: dict[str, Any], current_executor: str) -> str:
    # Distinguishes WHY an executor name is (or is not) shown, per the
    # three-state model in docs/INSTALLATION.md: a route result/observed
    # runtime fact from a run, a prepared handoff recorded but not yet
    # executed, a standing user preference recorded at setup, or none of
    # the above (the safety-first no-run state).
    if current_executor_row:
        evidence = _dict(current_executor_row.get("evidence"))
        return "observed_runtime" if bool(evidence.get("execution_observed")) else "prepared_handoff"
    if current_executor != "choose":
        return "user_preference"
    return "none"


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
    hermes_processes: dict[str, Any],
    hermes_sessions: dict[str, Any],
    model_settings: dict[str, Any],
    current_executor_row: dict[str, Any],
) -> dict[str, Any]:
    connection_ready = settings["omh_connection"]["value"] == "ready"
    processes_observed = bool(hermes_processes.get("observed"))
    sessions_observed = bool(hermes_sessions.get("observed"))
    agent_count = _safe_int(hermes_processes.get("agent_count"), 0)
    process_count = _safe_int(hermes_processes.get("process_count"), 0)
    live = _safe_int(hermes_sessions.get("live"), 0)
    if processes_observed and agent_count > 0:
        headline = "Hermes running"
    else:
        headline = "OMH ready" if connection_ready else "OMH needs attention"
    pieces: list[str] = []
    if processes_observed:
        pieces.append(f"{_plural(agent_count, 'agent')} · {_plural(process_count, 'process', 'processes')}")
    if sessions_observed:
        pieces.append(f"sessions live {live} / total {_safe_int(hermes_sessions.get('total'), 0)}")
    else:
        pieces.append("sessions not observed")
    if not connection_ready:
        menu_bar_title = "!"
    elif processes_observed and sessions_observed:
        menu_bar_title = f"{agent_count}·{live}"
    else:
        menu_bar_title = ""
    return {
        "menu_title": "omh",
        "menu_bar_title": menu_bar_title,
        "headline": headline,
        "summary_line": " · ".join(pieces),
        "menu_cards": _menu_cards(settings, hermes_sessions, model_settings, current_executor_row),
    }


def _plural(count: int, singular: str, plural: str = "") -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _menu_cards(
    settings: dict[str, Any],
    hermes_sessions: dict[str, Any],
    model_settings: dict[str, Any],
    current_executor_row: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _sessions_card(hermes_sessions),
        _models_card(hermes_sessions, model_settings),
        {
            "title": "",
            "rows": [
                {
                    "label": "coding",
                    "value": _coding_agent_menu_value(settings, current_executor_row),
                    "detail": "metadata only",
                }
            ],
        },
    ]


def _coding_agent_menu_value(settings: dict[str, Any], current_executor_row: dict[str, Any]) -> str:
    if current_executor_row:
        return str(current_executor_row.get("name", "") or "selected")
    coding_handoff = _dict(settings.get("coding_handoff"))
    return _executor_setting_label(str(coding_handoff.get("value", "") or "choose"))


def _sessions_card(hermes_sessions: dict[str, Any]) -> dict[str, Any]:
    if not hermes_sessions.get("observed"):
        return {
            "title": "Sessions",
            "columns": ["Hermes session", "Count"],
            "rows": [{"kind": "table_row", "left": "sessions", "right": "not observed"}],
            "footer": str(hermes_sessions.get("reason", "") or "not observed"),
        }
    live = _safe_int(hermes_sessions.get("live"), 0)
    stale = _safe_int(hermes_sessions.get("stale"), 0)
    total = _safe_int(hermes_sessions.get("total"), 0)
    window_minutes = max(1, _safe_int(hermes_sessions.get("live_window_seconds"), 0) // 60)
    rows = [
        {"kind": "table_row", "left": "live", "right": str(live), "tone": "ok" if live else "neutral"},
    ]
    # Open rows Hermes never closed (crash, killed terminal, orphan not yet
    # reaped) are shown as their own line instead of inflating `live`.
    if stale:
        rows.append({"kind": "table_row", "left": "open, idle", "right": str(stale), "tone": "neutral"})
    rows.append({"kind": "table_row", "left": "total", "right": str(total), "tone": "ok" if total else "neutral"})
    return {
        "title": "Sessions",
        "columns": ["Hermes session", "Count"],
        "rows": rows,
        "footer": f"live = activity within {window_minutes} min · Hermes state.db (read-only)",
    }


def _models_card(hermes_sessions: dict[str, Any], model_settings: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    current_model = _dict(hermes_sessions.get("current_model"))
    if current_model.get("observed"):
        rows.append(
            {
                "kind": "table_row",
                "left": "current",
                "right": str(current_model.get("label", "") or "not observed"),
                "tone": "ok",
            }
        )
    aliases = {str(row.get("alias", "") or ""): row for row in _list(model_settings.get("aliases"))}
    main = aliases.get("main")
    if main is not None and len(rows) < 5:
        rows.append({"kind": "table_row", "left": "main", "right": str(main.get("label", "") or "inherit")})
    # The delegation model is what fan-out children run when no OMH route is
    # set; on a machine whose main model differs it is the more useful line.
    delegation = _dict(model_settings.get("delegation"))
    if delegation.get("configured") and len(rows) < 5:
        rows.append({"kind": "table_row", "left": "delegation", "right": str(delegation.get("label", "") or "inherit")})
    inherit_count = sum(
        1
        for alias in HERMES_AUX_ALIASES
        if (entry := aliases.get(alias)) is not None and not entry.get("configured")
    )
    configured_row_limit = 4 if inherit_count > 0 else 5
    for alias in HERMES_AUX_ALIASES:
        entry = aliases.get(alias)
        if entry is None or not entry.get("configured") or len(rows) >= configured_row_limit:
            continue
        rows.append({"kind": "table_row", "left": alias, "right": str(entry.get("label", "") or "inherit")})
    if inherit_count > 0 and len(rows) < 5:
        rows.append({"kind": "table_row", "left": f"+{inherit_count} aliases", "right": "inherit default"})
    return {
        "title": "Models",
        "columns": ["Alias", "Model"],
        "rows": rows,
        "footer": "current = live session · main/delegation/aux = config.yaml",
    }


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
        parsed = strict_fromisoformat(normalized)
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
        return "Not selected"
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
