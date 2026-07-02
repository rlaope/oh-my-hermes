from __future__ import annotations

from pathlib import Path

from ..paths import OmhPaths
from .hermes_retained_context_catalog import RetainedContextChannel
from .hermes_retained_context_provider import (
    ProviderSelection,
    clean_config_scalar,
    marker_exists_under,
    provider_selection,
)


def retained_context_channels(paths: OmhPaths, config_text: str) -> list[RetainedContextChannel]:
    memory_provider = provider_selection(_section_value(config_text, "memory", "provider"))
    return [
        _file_channel(
            "hermes_config",
            "Hermes config",
            paths.hermes_config_path,
            True,
            ("setup", "memory provider selection"),
        ),
        _sessions_channel(paths.hermes_home / "sessions" / "sessions.json"),
        _state_db_channel(paths.hermes_home / "state.db"),
        _memory_provider_channel(paths, memory_provider),
        _omh_memory_channel(paths),
        _omh_learning_channel(paths),
        _omh_runtime_journal_channel(paths),
        _dir_channel(
            "omh_loop_artifacts",
            "OMH loop artifacts",
            paths.omh_home / "loops",
            False,
            ("loop continuity", "recurring workflow review"),
        ),
        _external_knowledge_channel(paths),
    ]


def _file_channel(
    channel_id: str,
    label: str,
    path: Path,
    required: bool,
    improves: tuple[str, ...],
) -> RetainedContextChannel:
    available = path.is_file()
    return {
        "id": channel_id,
        "label": label,
        "status": "available" if available else "missing",
        "required_for_retained_context": required,
        "evidence": [str(path)],
        "metrics": {"exists": available, "size_bytes": path.stat().st_size if available else 0},
        "improves": list(improves),
        "message": f"{label} exists." if available else f"{label} is missing.",
    }


def _dir_channel(
    channel_id: str,
    label: str,
    path: Path,
    required: bool,
    improves: tuple[str, ...],
) -> RetainedContextChannel:
    available = path.is_dir()
    return {
        "id": channel_id,
        "label": label,
        "status": "available" if available else "unknown",
        "required_for_retained_context": required,
        "evidence": [str(path)],
        "metrics": {"exists": available, "file_count": _file_count(path)},
        "improves": list(improves),
        "message": f"{label} is available." if available else f"{label} has no local marker yet.",
    }


def _sessions_channel(path: Path) -> RetainedContextChannel:
    channel = _file_channel(
        "hermes_sessions_index",
        "Hermes sessions index",
        path,
        False,
        ("conversation recall", "gateway session continuity", "MCP session bridge"),
    )
    channel["metrics"]["content_inspected"] = False
    return channel


def _state_db_channel(path: Path) -> RetainedContextChannel:
    return _file_channel(
        "hermes_state_db",
        "Hermes state database",
        path,
        False,
        ("session search", "memory substrate", "cron/subagent lineage"),
    )


def _memory_provider_channel(paths: OmhPaths, provider: ProviderSelection) -> RetainedContextChannel:
    memory_plugin_root = paths.hermes_plugins_dir / "memory"
    source_plugin_root = paths.hermes_home / "hermes-agent" / "plugins" / "memory"
    metrics = {
        "provider_configured": provider.configured,
        "provider_id_safe": provider.safe,
        "plugin_marker_exists": False,
    }
    if not provider.configured:
        return {
            "id": "hermes_memory_provider",
            "label": "Hermes memory provider",
            "status": "unknown",
            "required_for_retained_context": True,
            "evidence": [str(paths.hermes_config_path)],
            "metrics": metrics,
            "improves": ["durable user/project memory", "provider-specific recall"],
            "message": "No memory.provider value was found in Hermes config.",
        }
    if not provider.safe:
        return {
            "id": "hermes_memory_provider",
            "label": "Hermes memory provider",
            "status": "unknown",
            "required_for_retained_context": True,
            "evidence": [str(paths.hermes_config_path), str(memory_plugin_root), str(source_plugin_root)],
            "metrics": metrics,
            "improves": ["durable user/project memory", "provider-specific recall"],
            "message": "Hermes config has a memory.provider value, but it is not a safe provider id.",
        }
    plugin_marker = memory_plugin_root / provider.provider_id / "plugin.yaml"
    source_marker = source_plugin_root / provider.provider_id / "plugin.yaml"
    available = marker_exists_under(plugin_marker, memory_plugin_root) or marker_exists_under(
        source_marker,
        source_plugin_root,
    )
    metrics["plugin_marker_exists"] = available
    return {
        "id": "hermes_memory_provider",
        "label": "Hermes memory provider",
        "status": "available" if available else "missing",
        "required_for_retained_context": True,
        "evidence": [str(paths.hermes_config_path), str(memory_plugin_root), str(source_plugin_root)],
        "metrics": metrics,
        "improves": ["durable user/project memory", "provider-specific recall"],
        "message": (
            "A configured Hermes memory provider has a plugin marker."
            if available
            else "Hermes config selects a safe memory provider id, but no plugin marker was found."
        ),
    }


def _omh_memory_channel(paths: OmhPaths) -> RetainedContextChannel:
    path = paths.memory_index_path
    channel = _file_channel(
        "omh_memory_store",
        "OMH reviewed memory store",
        path,
        False,
        ("reviewed memory", "handoff recall packs"),
    )
    channel["metrics"]["content_inspected"] = False
    return channel


def _omh_learning_channel(paths: OmhPaths) -> RetainedContextChannel:
    traces = _file_count(paths.learning_traces_dir)
    candidates = _file_count(paths.learning_candidates_dir)
    store_routes = _file_count(paths.learning_store_routes_dir)
    available = bool(traces or candidates or store_routes)
    return {
        "id": "omh_learning_store",
        "label": "OMH workflow-learning store",
        "status": "available" if available else "unknown",
        "required_for_retained_context": False,
        "evidence": [str(paths.learning_dir)],
        "metrics": {"trace_count": traces, "candidate_count": candidates, "store_route_count": store_routes},
        "improves": ["failure retrospectives", "self-improvement review", "regression replay"],
        "message": (
            "Workflow-learning artifacts are available."
            if available
            else "No workflow-learning artifacts were found."
        ),
    }


def _omh_runtime_journal_channel(paths: OmhPaths) -> RetainedContextChannel:
    path = paths.runtime_journal_events_path
    channel = _file_channel(
        "omh_runtime_journal",
        "OMH runtime observation journal",
        path,
        False,
        ("observed lifecycle", "merge/review/CI evidence"),
    )
    channel["metrics"]["content_inspected"] = False
    return channel


def _external_knowledge_channel(paths: OmhPaths) -> RetainedContextChannel:
    candidates = (paths.omh_home / "knowledge", paths.omh_home / "external-knowledge", paths.omh_home / "wiki")
    available = any(path.exists() for path in candidates)
    return {
        "id": "external_knowledge_store",
        "label": "External knowledge-store marker",
        "status": "available" if available else "unknown",
        "required_for_retained_context": False,
        "evidence": [str(path) for path in candidates],
        "metrics": {"marker_count": sum(1 for path in candidates if path.exists())},
        "improves": ["wiki capture", "destination-aware retained knowledge", "Obsidian/Notion/folder handoff"],
        "message": (
            "A local external knowledge-store marker is available."
            if available
            else "No external knowledge-store marker was found; wiki guidance remains destination-prepared only."
        ),
    }


def _section_value(config_text: str, section: str, key: str) -> str:
    dotted = f"{section}.{key}:"
    section_header = f"{section}:"
    in_section = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(dotted):
            return _clean_scalar(stripped[len(dotted) :])
        if not line.startswith(" "):
            in_section = stripped == section_header
            continue
        if in_section and line.startswith("  ") and not line.startswith("    "):
            prefix = f"{key}:"
            if stripped.startswith(prefix):
                return _clean_scalar(stripped[len(prefix) :])
    return ""


def _clean_scalar(value: str) -> str:
    return clean_config_scalar(value)


def _file_count(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_file())


__all__ = ["retained_context_channels"]
