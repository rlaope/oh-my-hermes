from __future__ import annotations

import errno
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .metadata import (
    OPTIONAL_HOOKS,
    PROVIDED_HOOKS,
    PROVIDED_TOOLS,
    REQUIRED_HOOKS,
    TOOL_FILE_STEMS,
    TOOLS_REQUIRING_ROLE_CATALOG,
)

STATUS_SCHEMA_VERSION = "omh_status/v1"
HUD_SCHEMA_VERSION = "omh_hud/v1"
HUD_PRESETS = {"minimal", "focused", "full"}
HUD_REQUIRED_TOOLS = PROVIDED_TOOLS
HUD_REQUIRED_HOOKS = REQUIRED_HOOKS
HUD_OPTIONAL_HOOKS = OPTIONAL_HOOKS
OBSERVATION_EVENT_SCHEMA_VERSION = "omh_observation_event/v1"
JOURNAL_EVENT_ALIASES = {
    "coding_handoff_prepared": "prepared_handoff_created",
    "handoff_prepared": "prepared_handoff_created",
    "runtime_start": "runtime_start_observed",
    "worktree_creation": "worktree_creation_observed",
    "worker_dispatch": "executor_dispatch_observed",
    "executor_dispatch": "executor_dispatch_observed",
    "worker_result": "executor_result_observed",
    "executor_result": "executor_result_observed",
    "verification": "verification_result_observed",
    "review": "review_result_observed",
    "ci": "ci_result_observed",
    "merge_readiness": "merge_gate_observed",
    "merge": "merge_observed",
}
# Hand-copied from `omh.coding.owner_progress_normalization`
# (`NORMALIZED_PROGRESS_EVENT_TYPES`) and `omh.coding.executor_progress`
# (`ALLOWED_EXECUTOR_PROFILES`); the bundle cannot import from src. Parity is
# gated by `tests/test_executor_progress_quality_floor.py` -- an event type
# added in one place and not the other is silently dropped at this read
# boundary, which is how `omo_runtime` bindings were rejected here long after
# the lane accepted them.
EXECUTOR_PROGRESS_EVENT_TYPES = {
    "executor_dispatched",
    "repo_exploration",
    "running_no_diff_observed",
    "diff_started",
    "tests_started",
    "tests_failed",
    "tests_passed",
    "executor_completed",
    "executor_blocked",
    "executor_failed",
    "reported_change_not_observed",
    "progress_observed",
    "unmapped_source_event",
}
EXECUTOR_PROGRESS_PROFILES = {"codex", "claude_code", "hermes_local", "omo_runtime"}
EXECUTOR_PROGRESS_BINDING_STATES = {"active", "stale", "expired", "closed"}
# Hand-copied from `omh.workflows.external_effect_receipts` and
# `omh.runtime.artifacts` (`external_effect_id`, which composes an effect id as
# `<kind>:<run_id>`); the bundle cannot import from src. Parity is gated by
# `tests/test_runtime_reader_external_effect_receipts.py` -- a store renamed or
# a schema version bumped in one place and not the other would silently return
# this reader to claiming CI and merge success from a local record alone.
EXTERNAL_EFFECT_RECEIPT_STORE_NAME = "external_effect_receipts.jsonl"
EXTERNAL_EFFECT_RECEIPT_SCHEMA_VERSION = "external_effect_receipt/v1"
EXTERNAL_EFFECT_CLAIM_BOUNDARY = (
    "An external effect receipt is one acting surface's observation of one external effect. "
    "It is not execution, verification, review, CI, merge-readiness, or merge evidence for any other effect."
)
# The run-summary claims that assert an external effect, and the effect kind
# whose receipt has to back each one.
RECEIPT_BACKED_RUN_CLAIMS = {"review_observed": "review", "ci_observed": "ci", "merge_observed": "merge"}
OBSERVATION_STATUS_ORDER = (
    "unknown",
    "prepared_not_observed",
    "runtime_start_observed",
    "worktree_creation_observed",
    "dispatch_observed",
    "execution_observed",
    "verification_observed",
    "review_observed",
    "ci_observed",
    "merge_gate_observed",
    "merge_observed",
)
RAW_OR_HIDDEN_KEYS = {
    "analysis",
    "chain_of_thought",
    "cot",
    "hidden",
    "hidden_reasoning",
    "raw",
    "raw_log",
    "raw_logs",
    "raw_output",
    "reasoning",
    "think",
    "thinking",
    "transcript",
}
MAX_HUD_METADATA_BYTES = 262_144
MAX_HUD_TEXT_CHARS = 120


def _expand_path(value: str | Path) -> Path:
    try:
        return Path(os.path.expandvars(str(value))).expanduser().resolve()
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise RuntimeError("cannot resolve path through a symlink loop") from exc
        raise


def _hud_text(value: Any, *, limit: int = MAX_HUD_TEXT_CHARS) -> str:
    return str(value or "").strip()[:limit]


def _default_omh_home() -> Path:
    return _expand_path(os.environ.get("OMH_HOME", "~/.omh"))


def _default_hermes_home() -> Path:
    return _expand_path(os.environ.get("HERMES_HOME", "~/.hermes"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _open_hud_descriptor(path: Path, *, root: Path | None) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if root is None or os.open not in os.supports_dir_fd or not hasattr(os, "O_DIRECTORY"):
        if root is not None and _contains_symlink(path, root=root):
            raise OSError("unsafe HUD metadata path")
        return os.open(path, flags)

    absolute_root = Path(os.path.abspath(root))
    absolute_path = Path(os.path.abspath(path))
    relative = absolute_path.relative_to(absolute_root)
    if not relative.parts:
        raise OSError("HUD metadata path must name a file below its root")
    directory_flags = flags | os.O_DIRECTORY
    directory_descriptor = os.open(absolute_root, directory_flags)
    try:
        for part in relative.parts[:-1]:
            child_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = child_descriptor
        return os.open(relative.parts[-1], flags, dir_fd=directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _read_hud_text(path: Path, *, root: Path | None = None) -> str | None:
    try:
        descriptor = _open_hud_descriptor(path, root=root)
    except (OSError, ValueError):
        return None
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_size > MAX_HUD_METADATA_BYTES
        ):
            return None
        chunks: list[bytes] = []
        remaining = MAX_HUD_METADATA_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_HUD_METADATA_BYTES:
            return None
        return raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(descriptor)


def _read_hud_json(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    try:
        text = _read_hud_text(path, root=root)
        data = json.loads(text) if text is not None else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) and not _has_raw_or_hidden_content(data) else {}


def _read_hud_coding_projection(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    try:
        text = _read_hud_text(path, root=root)
        data = json.loads(text) if text is not None else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    projected: dict[str, Any] = {
        key: data[key]
        for key in (
            "recommended_workflow",
            "recommended_harness",
            "selected_executor_profile",
            "executor_profile",
            "status",
        )
        if isinstance(data.get(key), (str, int, float, bool))
    }
    for key in ("executor_handoff", "prompt_handoff"):
        value = data.get(key)
        if isinstance(value, dict):
            projected[key] = {
                nested: value[nested]
                for nested in ("executor_target", "selected_executor_profile")
                if isinstance(value.get(nested), str)
            }
    return projected


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _read_hud_jsonl(path: Path, *, root: Path | None = None) -> list[dict[str, Any]]:
    text = _read_hud_text(path, root=root)
    if text is None:
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _contains_symlink(path: Path, *, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink():
            return True
        if current == current.parent:
            return True
        current = current.parent
    return root.is_symlink()


def _child_files(directory: Path, *relative: str) -> list[Path]:
    """Return every existing `directory/<child>/*relative` file.

    `Path.glob` is tolerant by design: it swallows the `OSError` `os.scandir`
    raises on an unreadable directory and yields nothing, so a directory the
    process cannot read produces the same empty result as one that is
    genuinely empty. That is the failure-relabeled-as-a-normal-result shape
    `tests/test_broad_exception_policy.py` exists to keep out, so this reads
    the directory with an API that propagates instead.

    A directory that was never created is the routine case and really is
    empty, so `FileNotFoundError` and `NotADirectoryError` return `[]`. Any
    other `OSError` is a real fault and is left to reach the caller that
    classifies it, which records a `runtime_status_read` degradation rather
    than reporting a host with nothing to report.
    """
    try:
        with os.scandir(directory) as entries:
            names = [entry.name for entry in entries if not entry.is_symlink()]
    except (FileNotFoundError, NotADirectoryError):
        return []
    candidates = [directory.joinpath(name, *relative) for name in names]
    return [
        candidate
        for candidate in candidates
        if not _contains_symlink(candidate, root=directory)
        and candidate.is_file()
    ]


def _hud_child_files(directory: Path, *relative: str) -> list[Path]:
    files = _child_files(directory, *relative)
    safe: list[Path] = []
    for path in files:
        try:
            if path.stat().st_size <= MAX_HUD_METADATA_BYTES:
                safe.append(path)
        except OSError:
            continue
    return safe


def _bool_from_record(record: dict[str, Any], key: str = "observed") -> bool:
    return bool(record.get(key, False)) if record else False


def _summarize_run(
    run_dir: Path,
    *,
    run: dict[str, Any],
    journal_events: list[dict[str, Any]],
    external_effect_receipts: list[dict[str, Any]],
    json_reader: Callable[[Path], dict[str, Any]] = _read_json,
    coding_reader: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    coding = (coding_reader or json_reader)(run_dir / "coding_delegation.json")
    delegation = json_reader(run_dir / "delegation.json")
    wrapper = json_reader(run_dir / "wrapper.json")
    review = json_reader(run_dir / "review.json")
    ci = json_reader(run_dir / "ci.json")
    merge = json_reader(run_dir / "merge.json")
    legacy = {
        "run_id": str(run.get("run_id", run_dir.name)),
        "workflow": str(coding.get("recommended_workflow") or run.get("skill", "unknown")),
        "harness": str(coding.get("recommended_harness") or run.get("harness", "unknown")),
        "executor_target": _executor_target_from_coding(coding),
        "phase": str(run.get("phase", run.get("status", "unknown"))),
        "artifact_kind": str(run.get("artifact_kind", "")),
        "observation_status": str(run.get("observation_status", coding.get("status", "unknown"))),
        "prepared_handoff": bool(coding) and str(coding.get("status", "")) == "prepared_not_observed",
        "prompt_dispatched": _bool_from_record(wrapper, "prompt_dispatched"),
        "execution_observed": _bool_from_record(delegation),
        "verification_observed": _bool_from_record(wrapper, "verification_observed"),
        "review_observed": _bool_from_record(review),
        "review_status": str(review.get("status", "not_observed" if review else "unknown")),
        "ci_observed": _bool_from_record(ci),
        "ci_status": str(ci.get("status", "not_observed" if ci else "unknown")),
        "merge_observed": _bool_from_record(merge),
        "merge_status": str(merge.get("status", "not_observed" if merge else "unknown")),
    }
    lifecycle = _journal_projection_for_run(run_dir, legacy, journal_events)
    _apply_lifecycle_to_run_summary(legacy, lifecycle)
    _apply_external_effect_receipts_to_run_summary(
        run_dir,
        legacy,
        lifecycle,
        external_effect_receipts,
    )
    legacy["lifecycle"] = lifecycle
    legacy["journal_event_count"] = lifecycle["journal_event_count"]
    legacy["latest_event"] = lifecycle["latest_event"]
    return legacy


def _apply_external_effect_receipts_to_run_summary(
    run_dir: Path,
    summary: dict[str, Any],
    lifecycle: dict[str, Any],
    receipts: list[dict[str, Any]],
) -> None:
    """Withdraw a review, CI, or merge success claim that no receipt backs.

    These are the three rungs that assert something happened outside this
    machine. A local `review.json`, `ci.json`, or `merge.json` is the claim, not
    the evidence for it, and the journal event beside it is written by the same
    call, so none can promote itself. Before the receipt store existed this
    reader reported `ci_observed: True` from a local record alone -- which is
    the state of every pre-#836 store on disk today, and why the default here is
    to withdraw the claim rather than to trust the record. Review joined the
    other two in #844.

    The rule is the same one `omh.runtime.claims._receipt_cited` applies on the
    CLI side, so the Hermes-facing surface cannot contradict it.
    """
    backed = _receipt_backed_effect_kinds(receipts, str(summary.get("run_id", run_dir.name)))
    for key, kind in RECEIPT_BACKED_RUN_CLAIMS.items():
        if kind in backed:
            continue
        summary[key] = False
        lifecycle[key] = False
    demoted = _demote_observation_status(str(summary.get("observation_status", "unknown")), backed)
    summary["observation_status"] = demoted
    lifecycle["observation_status"] = _demote_observation_status(
        str(lifecycle.get("observation_status", "unknown")), backed
    )
    summary["external_effect_claims"] = {
        "receipt_backed": sorted(kind for kind in RECEIPT_BACKED_RUN_CLAIMS.values() if kind in backed),
        "unreceipted": sorted(kind for kind in RECEIPT_BACKED_RUN_CLAIMS.values() if kind not in backed),
        "claim_boundary": EXTERNAL_EFFECT_CLAIM_BOUNDARY,
    }


def _receipt_backed_effect_kinds(receipts: list[dict[str, Any]], run_id: str) -> set[str]:
    """Effect kinds whose latest receipt for this run succeeded and named an actor.

    Latest-wins, not any-wins: a run whose CI succeeded and was then re-run to a
    failure has a `succeeded` receipt on disk that no longer describes the
    current state, because the store is append-only and supersedes by link.
    """
    latest: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        if receipt.get("schema_version") != EXTERNAL_EFFECT_RECEIPT_SCHEMA_VERSION:
            continue
        if str(receipt.get("run_id", "")) != run_id:
            continue
        effect_id = str(receipt.get("effect_id", ""))
        kind, separator, effect_run = effect_id.partition(":")
        if not separator or effect_run != run_id or kind not in RECEIPT_BACKED_RUN_CLAIMS.values():
            continue
        latest[kind] = receipt
    return {
        kind
        for kind, receipt in latest.items()
        if str(receipt.get("observed_result", "")) == "succeeded"
        and str(receipt.get("acting_surface", ""))
        and str(receipt.get("receipt_id", ""))
    }


def _demote_observation_status(status: str, backed: set[str]) -> str:
    """Walk an observation status down to the highest rung it can still claim."""
    if status in {"blocked", "failed", "cancelled"}:
        return status
    try:
        index = OBSERVATION_STATUS_ORDER.index(status)
    except ValueError:
        return status
    while index > 0:
        kind = RECEIPT_BACKED_RUN_CLAIMS.get(OBSERVATION_STATUS_ORDER[index])
        if kind is None or kind in backed:
            break
        index -= 1
    return OBSERVATION_STATUS_ORDER[index]


def _executor_target_from_coding(coding: dict[str, Any]) -> str:
    if not isinstance(coding, dict):
        return ""
    handoff = coding.get("executor_handoff")
    if isinstance(handoff, dict):
        value = str(handoff.get("executor_target") or handoff.get("selected_executor_profile") or "").strip()
        if value:
            return value
    prompt_handoff = coding.get("prompt_handoff")
    if isinstance(prompt_handoff, dict):
        value = str(prompt_handoff.get("selected_executor_profile") or "").strip()
        if value:
            return value
    value = str(coding.get("selected_executor_profile") or coding.get("executor_profile") or "").strip()
    return value


def _journal_projection_for_run(
    run_dir: Path,
    legacy: dict[str, Any],
    journal_events: list[dict[str, Any]],
) -> dict[str, Any]:
    run_id = str(legacy.get("run_id", run_dir.name))
    events = [
        event
        for event in journal_events
        if event.get("schema_version") == OBSERVATION_EVENT_SCHEMA_VERSION
        and str(event.get("run_id", "")) == run_id
    ]
    projection: dict[str, Any] = {
        "schema_version": "omh_lifecycle_projection/v1",
        "run_id": run_id,
        "workflow": str(legacy.get("workflow", "")),
        "harness": str(legacy.get("harness", "")),
        "phase": str(legacy.get("phase", "")),
        "prepared_handoff": bool(legacy.get("prepared_handoff", False)),
        "plan_artifact": "",
        "plan_status": "",
        "prompt_dispatched": bool(legacy.get("prompt_dispatched", False)),
        "runtime_start_observed": False,
        "worktree_observed": False,
        "execution_observed": bool(legacy.get("execution_observed", False)),
        "verification_observed": bool(legacy.get("verification_observed", False)),
        "review_observed": bool(legacy.get("review_observed", False)),
        "ci_observed": bool(legacy.get("ci_observed", False)),
        "merge_gate_observed": False,
        "merge_observed": bool(legacy.get("merge_observed", False)),
        "observation_status": str(legacy.get("observation_status", "unknown")),
        "journal_event_count": len(events),
        "latest_event_id": "",
        "latest_event": {},
    }
    for event in events:
        name = JOURNAL_EVENT_ALIASES.get(str(event.get("event", "")), str(event.get("event", "")))
        status = str(event.get("status", "observed"))
        projection["latest_event_id"] = str(event.get("event_id", ""))
        projection["latest_event"] = {
            "event": name,
            "status": status,
            "summary": str(event.get("summary", "")),
            "observed_at": str(event.get("observed_at", "")),
        }
        if event.get("plan_artifact"):
            projection["plan_artifact"] = str(event.get("plan_artifact", ""))
        if event.get("plan_status"):
            projection["plan_status"] = str(event.get("plan_status", ""))
        if status != "observed":
            if status in {"blocked", "failed"}:
                projection["observation_status"] = status
            continue
        if name == "prepared_handoff_created":
            projection["prepared_handoff"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "prepared_not_observed")
        elif name == "runtime_start_observed":
            projection["runtime_start_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "runtime_start_observed")
        elif name == "worktree_creation_observed":
            projection["worktree_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "worktree_creation_observed")
        elif name == "executor_dispatch_observed":
            projection["prompt_dispatched"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "dispatch_observed")
        elif name == "executor_result_observed":
            projection["execution_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "execution_observed")
        elif name == "verification_result_observed":
            projection["verification_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "verification_observed")
        elif name == "review_result_observed":
            projection["review_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "review_observed")
        elif name == "ci_result_observed":
            projection["ci_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "ci_observed")
        elif name == "merge_gate_observed":
            projection["merge_gate_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "merge_gate_observed")
        elif name == "merge_observed":
            projection["merge_observed"] = True
            projection["observation_status"] = _later_status(projection["observation_status"], "merge_observed")
    return projection


def _apply_lifecycle_to_run_summary(summary: dict[str, Any], lifecycle: dict[str, Any]) -> None:
    for key in (
        "prepared_handoff",
        "prompt_dispatched",
        "execution_observed",
        "verification_observed",
        "review_observed",
        "ci_observed",
        "merge_observed",
    ):
        summary[key] = bool(summary.get(key, False)) or bool(lifecycle.get(key, False))
    if lifecycle.get("observation_status") and lifecycle.get("observation_status") != "unknown":
        summary["observation_status"] = str(lifecycle["observation_status"])
    if lifecycle.get("plan_artifact"):
        summary["plan_artifact"] = lifecycle["plan_artifact"]
    if lifecycle.get("plan_status"):
        summary["plan_status"] = lifecycle["plan_status"]


def _later_status(current: str, candidate: str) -> str:
    order = list(OBSERVATION_STATUS_ORDER)
    if current in {"blocked", "failed", "cancelled"}:
        return current
    try:
        return candidate if order.index(candidate) >= order.index(current) else current
    except ValueError:
        return candidate


def read_omh_hud(
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    *,
    status: dict[str, Any] | None = None,
    preset: str = "focused",
    limit: int = 3,
    token_metadata: dict[str, Any] | None = None,
    package_version: str = "",
) -> dict[str, Any]:
    safe_preset = preset if preset in HUD_PRESETS else "focused"
    home = _expand_path(omh_home) if omh_home else _default_omh_home()
    hermes = _expand_path(hermes_home) if hermes_home else _default_hermes_home()
    safe_limit = _safe_limit(limit, default=3)
    status_payload = status if status is not None else _read_omh_hud_status(home, limit=safe_limit)
    state = _read_hud_json(home / "runtime" / "state.json", root=home)
    profile = _read_hud_json(home / "setup-profile.json", root=home)
    target_registry = _read_hud_json(home / "targets.json", root=home)
    runs = status_payload.get("runs", [])
    latest_run = runs[0] if runs else {}
    payload: dict[str, Any] = {
        "schema_version": HUD_SCHEMA_VERSION,
        "preset": safe_preset,
        "package": "oh-my-hermes",
        "version": _package_version(state, package_version),
        "omh_home": str(home),
        "hermes_home": str(hermes),
        "plugin": _plugin_summary(hermes, state),
        "target_topology": _target_topology_summary(target_registry),
        "executor": _executor_summary(profile),
        "runtime": _hud_runtime_summary(status_payload, latest_run),
        "achievements": _achievements_summary(hermes),
        "tokens": _token_summary(token_metadata or {}),
        "evidence_boundary": (
            "HUD is metadata-only. Prepared handoffs are not execution, review, CI, merge, or token-usage evidence."
        ),
        "privacy": "metadata_only",
    }
    payload["subagents"] = _hud_subagent_summary(status_payload)
    payload["maestro"] = {
        "status": "observed" if payload["subagents"]["maestro_rows"] else "idle",
        "rows": payload["subagents"].pop("maestro_rows"),
    }
    payload["active"] = bool(
        payload["runtime"]["workflow"] != "idle"
        or payload["subagents"]["active"]
        or payload["maestro"]["rows"]
    )
    payload["display"] = {
        "line": format_omh_hud_line(payload, preset=safe_preset),
        "segments": _hud_segments(payload, preset=safe_preset),
        "widget_lines": _hud_widget_lines(payload),
    }
    return payload


def format_omh_hud_line(payload: dict[str, Any], *, preset: str = "focused") -> str:
    return " | ".join(_hud_segments(payload, preset=preset))


def _package_version(state: dict[str, Any], fallback: str) -> str:
    value = str(state.get("version", "") or fallback or "").strip()
    if value:
        return value
    last_install = state.get("last_install", {})
    if isinstance(last_install, dict):
        release_update = last_install.get("release_update", {})
        current = release_update.get("current", {}) if isinstance(release_update, dict) else {}
        value = str(current.get("package_version", "") if isinstance(current, dict) else "").strip()
    return value or "unknown"


def _plugin_summary(hermes_home: Path, state: dict[str, Any]) -> dict[str, Any]:
    plugin_dir = hermes_home / "plugins" / "omh"
    installed = plugin_dir.is_dir() and not _contains_symlink(plugin_dir, root=hermes_home)
    readable_plugin_dir = plugin_dir if installed else hermes_home / ".missing-omh-plugin"
    last_distribution = state.get("last_plugin_distribution", {})
    observed = bool(last_distribution.get("observed", False)) if isinstance(last_distribution, dict) else False
    capabilities = _plugin_capabilities(
        readable_plugin_dir,
        last_distribution if isinstance(last_distribution, dict) else {},
        root=hermes_home,
    )
    complete_files = bool(capabilities["files"]["plugin_yaml"] and capabilities["files"]["init_py"])
    required_tools_ready = all(capabilities["tools"].values())
    required_hooks_ready = all(capabilities["hooks"].get(hook, False) for hook in HUD_REQUIRED_HOOKS)
    if installed and complete_files and required_tools_ready and required_hooks_ready:
        status = "ready"
    elif installed and complete_files:
        status = "stale"
    elif installed:
        status = "installed"
    else:
        status = "missing"
    return {
        "status": status,
        "version": _plugin_version(readable_plugin_dir, root=hermes_home),
        "plugin_dir": str(plugin_dir),
        "distribution_observed": observed,
        "runtime_observed": False,
        "required_tools": list(HUD_REQUIRED_TOOLS),
        "required_hooks": list(HUD_REQUIRED_HOOKS),
        "optional_hooks": list(HUD_OPTIONAL_HOOKS),
        "capabilities": capabilities,
        "stale": status == "stale",
    }


def _plugin_version(plugin_dir: Path, *, root: Path) -> str:
    plugin_yaml = plugin_dir / "plugin.yaml"
    text = _read_hud_text(plugin_yaml, root=root)
    if text is None:
        return ""
    match = re.search(r'(?m)^version:\s*["\']?([A-Za-z0-9._+-]+)', text)
    return match.group(1) if match else ""


def _plugin_capabilities(
    plugin_dir: Path,
    last_distribution: dict[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    files = {
        "plugin_yaml": _hud_regular_file(plugin_dir / "plugin.yaml", root=root),
        "init_py": _hud_regular_file(plugin_dir / "__init__.py", root=root),
        "role_catalog": _hud_has_role_catalog(plugin_dir / "references", root=root),
        "managed_manifest": _hud_regular_file(plugin_dir / ".omh-plugin-manifest.json", root=root),
    }
    files.update(
        {
            stem: _hud_regular_file(plugin_dir / "tools" / f"{stem}.py", root=root)
            for stem in sorted(set(TOOL_FILE_STEMS.values()))
        }
    )
    yaml_text = _read_hud_text(plugin_dir / "plugin.yaml", root=root) or ""
    advertised_tools = set(_yaml_list_values(yaml_text, "provides_tools"))
    advertised_hooks = set(_yaml_list_values(yaml_text, "provides_hooks"))
    registered_tools = set(_string_list(last_distribution.get("registered_tools", [])))
    registered_hooks = set(_string_list(last_distribution.get("registered_hooks", [])))
    tool_sources = advertised_tools | registered_tools
    hook_sources = advertised_hooks | registered_hooks
    return {
        "files": files,
        "tools": _plugin_tool_capabilities(files, tool_sources),
        "hooks": {hook: hook in hook_sources for hook in PROVIDED_HOOKS},
        "advertised_tools": sorted(advertised_tools),
        "advertised_hooks": sorted(advertised_hooks),
    }


def _hud_regular_file(path: Path, *, root: Path) -> bool:
    try:
        descriptor = _open_hud_descriptor(path, root=root)
    except (OSError, ValueError):
        return False
    try:
        return stat.S_ISREG(os.fstat(descriptor).st_mode)
    except OSError:
        return False
    finally:
        os.close(descriptor)


def _hud_has_role_catalog(path: Path, *, root: Path) -> bool:
    if (
        os.open not in os.supports_dir_fd
        or os.scandir not in os.supports_fd
        or not hasattr(os, "O_DIRECTORY")
    ):
        try:
            if _contains_symlink(path, root=root) or not path.is_dir():
                return False
            names = [
                entry.name
                for entry in path.iterdir()
                if entry.name.startswith("role-")
                and entry.name.endswith(".md")
                and not entry.is_symlink()
            ]
        except OSError:
            return False
        return any(_hud_regular_file(path / name, root=root) for name in names)
    try:
        descriptor = _open_hud_descriptor(path, root=root)
    except (OSError, ValueError):
        return False
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            return False
        with os.scandir(descriptor) as entries:
            names = [
                entry.name
                for entry in entries
                if entry.name.startswith("role-")
                and entry.name.endswith(".md")
                and not entry.is_symlink()
            ]
        return any(_hud_regular_file(path / name, root=root) for name in names)
    except OSError:
        return False
    finally:
        os.close(descriptor)


def _plugin_tool_capabilities(files: dict[str, bool], tool_sources: set[str]) -> dict[str, bool]:
    capabilities = {}
    for tool in HUD_REQUIRED_TOOLS:
        file_ready = files[TOOL_FILE_STEMS[tool]]
        if tool in TOOLS_REQUIRING_ROLE_CATALOG:
            file_ready = file_ready and files["role_catalog"]
        capabilities[tool] = file_ready and tool in tool_sources
    return capabilities


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _yaml_list_values(text: str, key: str) -> list[str]:
    values: list[str] = []
    in_list = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_list:
            if stripped.startswith("- "):
                values.append(_unquote_yaml_scalar(stripped[2:].strip()))
                continue
            if not raw_line.startswith((" ", "\t")):
                in_list = False
        if stripped.startswith(f"{key}:"):
            remainder = stripped.split(":", 1)[1].strip()
            if not remainder:
                in_list = True
            elif remainder.startswith("[") and remainder.endswith("]"):
                values.extend(_unquote_yaml_scalar(item.strip()) for item in remainder[1:-1].split(",") if item.strip())
            else:
                values.append(_unquote_yaml_scalar(remainder))
    return values


def _unquote_yaml_scalar(value: str) -> str:
    cleaned = value.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _target_topology_summary(registry: dict[str, Any]) -> dict[str, Any]:
    topology = registry.get("topology", {}) if isinstance(registry, dict) else {}
    if not isinstance(topology, dict):
        topology = {}
    targets = registry.get("targets", {}) if isinstance(registry, dict) else {}
    known_count = _safe_int(topology.get("known_target_count"), len(targets) if isinstance(targets, dict) else 0)
    active_count = _safe_int(topology.get("active_agent_count"), known_count)
    mode = str(topology.get("mode", "") or "").strip()
    if not mode:
        mode = "multi_agent_targets" if active_count > 1 else "single_agent_target" if active_count == 1 else "unknown"
    return {
        "mode": mode,
        "known_target_count": known_count,
        "active_agent_count": active_count,
        "transition": str(topology.get("transition", "unknown") or "unknown"),
    }


def _executor_summary(profile: dict[str, Any]) -> dict[str, Any]:
    executor = str(profile.get("default_executor", "") or "").strip() if isinstance(profile, dict) else ""
    if not executor:
        executor = "choose"
    return {
        "default": executor,
        "configured": bool(profile),
        "dispatch_policy": str(profile.get("dispatch_policy", "ask_before_dispatch") if isinstance(profile, dict) else "ask_before_dispatch"),
    }


def _achievements_summary(hermes_home: Path) -> dict[str, Any]:
    # The plugin bundle stays standalone, so this mirrors the tolerant reading
    # in workflows/hermes_achievements.py at HUD granularity: counts only.
    plugin_dir = hermes_home / "plugins" / "hermes-achievements"
    snapshot = _read_hud_json(plugin_dir / "scan_snapshot.json", root=hermes_home)
    state = _read_hud_json(plugin_dir / "state.json", root=hermes_home)
    total = 0
    unlocked_flags = 0
    for key in ("achievements", "badges", "catalog", "items"):
        entries = snapshot.get(key)
        if isinstance(entries, dict):
            entries = list(entries.values())
        if isinstance(entries, list):
            total = len(entries)
            unlocked_flags = sum(
                1
                for entry in entries
                if isinstance(entry, dict)
                and (entry.get("unlocked") is True or str(entry.get("state", "")).lower() == "unlocked")
            )
            break
    unlocked = 0
    for key in ("unlocked", "unlocks", "unlocked_badges"):
        container = state.get(key)
        if isinstance(container, (dict, list)):
            unlocked = len(container)
            break
    return {
        "observed": bool(snapshot or state),
        "unlocked_count": max(unlocked, unlocked_flags),
        "total_count": total,
    }


def _hud_runtime_summary(status: dict[str, Any], latest_run: dict[str, Any]) -> dict[str, Any]:
    runs = status.get("runs", [])
    run_count = len(runs) if isinstance(runs, list) else 0
    if not latest_run:
        return {
            "state_present": bool(status.get("runtime_state_present", False)),
            "recent_run_count": run_count,
            "latest_run_id": "",
            "executor_target": "",
            "workflow": "idle",
            "phase": "idle",
            "observation_status": "idle",
            "evidence_state": "idle",
        }
    return {
        "state_present": bool(status.get("runtime_state_present", False)),
        "recent_run_count": run_count,
        "latest_run_id": _hud_text(latest_run.get("run_id", ""), limit=80),
        "executor_target": _hud_text(latest_run.get("executor_target", ""), limit=80),
        "workflow": _hud_text(latest_run.get("workflow", "unknown")),
        "phase": _hud_text(latest_run.get("phase", "unknown"), limit=40),
        "observation_status": _hud_text(latest_run.get("observation_status", "unknown"), limit=40),
        "evidence_state": _evidence_state(latest_run),
    }


def _hud_subagent_summary(status: dict[str, Any]) -> dict[str, Any]:
    active_rows = status.get("active_executors", [])
    active = active_rows if isinstance(active_rows, list) else []
    stale_rows = status.get("stale_executors", [])
    stale = stale_rows if isinstance(stale_rows, list) else []
    progress_rows = status.get("latest_progress_events", [])
    progress = progress_rows if isinstance(progress_rows, list) else []
    blocked = 0
    for row in active:
        event = row.get("latest_event", {}) if isinstance(row, dict) else {}
        event_type = str(event.get("event_type", "")) if isinstance(event, dict) else ""
        event_status = str(event.get("status", "")) if isinstance(event, dict) else ""
        if event_type in {"executor_blocked", "executor_failed"} or event_status in {"blocked", "failed"}:
            blocked += 1
    completed = sum(
        1
        for event in progress
        if isinstance(event, dict) and str(event.get("event_type", "")) == "executor_completed"
    )
    latest_action = ""
    if progress:
        latest = progress[0]
        if isinstance(latest, dict):
            latest_action = _hud_text(latest.get("summary", ""))
    subagent_rows: list[dict[str, Any]] = []
    maestro_rows: list[dict[str, Any]] = []
    maestro_run_ids = {
        str(run.get("run_id", ""))
        for run in (status.get("runs", []) if isinstance(status.get("runs"), list) else [])
        if isinstance(run, dict) and str(run.get("executor_target", "")).casefold() == "maestro"
    }
    for row in active[:5]:
        if not isinstance(row, dict):
            continue
        event = row.get("latest_event", {})
        event = event if isinstance(event, dict) else {}
        event_type = str(event.get("event_type", ""))
        event_status = str(event.get("status", ""))
        state = (
            "blocked"
            if event_type in {"executor_blocked", "executor_failed"}
            or event_status in {"blocked", "failed"}
            else "running"
        )
        projected = {
            "state": state,
            "task_id": _hud_text(row.get("target_id", ""), limit=80)[:8],
            "role": _hud_executor_role(row),
            "action": _hud_text(event.get("summary", "")),
            "model": _hud_text(row.get("routed_model", "")),
            "effort": _hud_text(row.get("routed_reasoning_effort", ""), limit=40),
            "tokens": row.get("tokens_total") if isinstance(row.get("tokens_total"), int) else None,
            "elapsed_seconds": _hud_number(row.get("elapsed_seconds")),
            "observed_at": _hud_text(event.get("observed_at", ""), limit=40),
            "category": _hud_text(row.get("category", ""), limit=80),
            "fallback_count": _hud_number(row.get("fallback_count")),
            "turn_count": _hud_number(row.get("turn_count")),
            "tool_count": _hud_number(row.get("tool_count")),
            "cost_usd": _hud_number(row.get("cost_usd")),
            "tokens_per_second": _hud_number(row.get("tokens_per_second")),
        }
        for key in ("cache_hit_percentage", "context_percentage"):
            value = _hud_percentage(row.get(key))
            if value is not None:
                projected[key] = value
        if (
            str(row.get("executor_profile", "")).casefold() == "maestro"
            or str(row.get("target_id", "")) in maestro_run_ids
        ):
            maestro_rows.append(projected)
        else:
            subagent_rows.append(projected)
    return {
        "status": "observed" if active or stale or progress else "idle",
        "active": len(active),
        "running": max(0, len(active) - blocked),
        "blocked": blocked,
        "completed": completed,
        "stale": len(stale),
        "latest_action": latest_action,
        "rows": subagent_rows,
        "maestro_rows": maestro_rows,
    }


def _hud_executor_role(row: dict[str, Any]) -> str:
    target_id = str(row.get("target_id", ""))
    profile = str(row.get("executor_profile", ""))
    if target_id.startswith(("run-", "session-")):
        return profile[:40]
    return (target_id or profile)[:40]


def _hud_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return int(number) if number.is_integer() else number


def _hud_percentage(value: Any) -> int | float | None:
    number = _hud_number(value)
    if number is None or number > 100:
        return None
    return number


def _hud_widget_lines(payload: dict[str, Any]) -> list[str]:
    runtime = payload.get("runtime", {})
    subagents = payload.get("subagents", {})
    workflow = {
        "fanout-unit": "Parallel work",
        "fanout": "Parallel work",
        "goal": "Goal",
        "wrapper-session": "Session",
    }.get(str(runtime.get("workflow", "")).casefold(), str(runtime.get("workflow", "Work")))
    phase = {
        "runtime": "active",
        "executing": "active",
        "prepared": "ready",
        "completed": "complete",
    }.get(str(runtime.get("phase", "")).casefold(), str(runtime.get("phase", "")))
    if not int(subagents.get("active", 0) or 0):
        phase = "ready"
    header = (
        f"[OMH] {workflow} {phase}  •  "
        f"agents {subagents.get('active', 0)}  •  "
        f"run {subagents.get('running', 0)}  •  "
        f"block {subagents.get('blocked', 0)}  •  "
        f"done {subagents.get('completed', 0)}"
    )
    latest_action = str(subagents.get("latest_action", "")).strip()
    return [header, f"latest {latest_action}"] if latest_action else [header]


def _evidence_state(run: dict[str, Any]) -> str:
    if run.get("merge_observed"):
        return "merge_observed"
    if run.get("ci_observed"):
        return "ci_observed"
    if run.get("review_observed"):
        return "review_observed"
    if run.get("verification_observed"):
        return "verification_observed"
    if run.get("execution_observed"):
        return "execution_observed"
    if run.get("prompt_dispatched"):
        return "dispatch_observed"
    if run.get("prepared_handoff"):
        return "prepared_not_observed"
    return str(run.get("observation_status", "unknown") or "unknown")


def _token_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    values = {
        key: value
        for key, value in (
            ("tokens_remaining", _optional_number(metadata.get("tokens_remaining"))),
            ("token_budget", _optional_number(metadata.get("token_budget"))),
            ("input_tokens", _optional_number(metadata.get("input_tokens"))),
            ("output_tokens", _optional_number(metadata.get("output_tokens"))),
            ("context_remaining_percent", _optional_number(metadata.get("context_remaining_percent"))),
        )
        if value is not None
    }
    if not values:
        return {
            "status": "unobserved",
            "summary": "unobserved",
            "values": {},
        }
    summary = _token_display(values)
    return {
        "status": "observed_from_host_metadata",
        "summary": summary,
        "values": values,
    }


def _token_display(values: dict[str, int | float]) -> str:
    remaining = values.get("tokens_remaining")
    budget = values.get("token_budget")
    percent = _token_percent(values)
    if percent is not None:
        return f"{_format_percent(percent)}%"
    if remaining is not None and budget is not None:
        return f"{remaining}/{budget}"
    if remaining is not None:
        return f"remaining={remaining}"
    parts = []
    if values.get("input_tokens") is not None:
        parts.append(f"in={values['input_tokens']}")
    if values.get("output_tokens") is not None:
        parts.append(f"out={values['output_tokens']}")
    return ",".join(parts) if parts else "observed"


def _token_percent(values: dict[str, int | float]) -> float | None:
    supplied = values.get("context_remaining_percent")
    if supplied is not None:
        return float(supplied)
    remaining = values.get("tokens_remaining")
    budget = values.get("token_budget")
    if remaining is None or budget is None or float(budget) <= 0:
        return None
    return float(remaining) / float(budget) * 100


def _format_percent(value: float) -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}"


def _hud_segments(payload: dict[str, Any], *, preset: str) -> list[str]:
    version = str(payload.get("version", "unknown"))
    plugin = payload.get("plugin", {})
    topology = payload.get("target_topology", {})
    executor = payload.get("executor", {})
    runtime = payload.get("runtime", {})
    base = [f"[omh] v{version}"]
    if preset == "minimal":
        return [*base, _activity_label(runtime)]
    focused = [*base, f"plugin:{_plugin_display_status(plugin)}"]
    topology_label = _topology_label(topology)
    if topology_label != "unknown":
        focused.append(f"target:{topology_label}")
    focused.append(_coding_agent_segment(runtime, executor))
    evidence_state = str(runtime.get("evidence_state", "unknown") or "unknown")
    if preset == "full" and evidence_state not in {"idle", "unknown"}:
        focused.append(f"evidence:{_evidence_display_status(evidence_state)}")
    achievements = payload.get("achievements", {})
    if preset == "full" and isinstance(achievements, dict) and achievements.get("observed"):
        focused.append(f"ach:{achievements.get('unlocked_count', 0)}/{achievements.get('total_count', 0)}")
    return focused


def _plugin_display_status(plugin: dict[str, Any]) -> str:
    status = str(plugin.get("status", "unknown") or "unknown")
    labels = {
        "missing": "not-installed",
        "stale": "update-needed",
    }
    return labels.get(status, status)


def _evidence_display_status(state: str) -> str:
    labels = {
        "prepared_not_observed": "prepared",
        "dispatch_observed": "dispatched",
        "execution_observed": "executed",
        "verification_observed": "verified",
        "review_observed": "reviewed",
        "ci_observed": "ci-pass",
        "merge_observed": "merged",
    }
    return labels.get(state, state.replace("_", "-"))


def _coding_agent_segment(runtime: dict[str, Any], executor: dict[str, Any]) -> str:
    # Three-state model (see docs/INSTALLATION.md "Status model: no-run,
    # prepared-handoff, observed-run"):
    #   1. no-run, no preference -> executor-neutral "not-selected" (no
    #      executor name; nothing to imply is idle).
    #   2. no-run, real preference recorded at setup -> the preference is
    #      shown, labeled by its idle state, because it is a genuine user
    #      choice rather than a placeholder.
    #   3. a run exists with an executor_target -> a prepared handoff or
    #      observed runtime fact, shown with its actual phase.
    executor_target = str(runtime.get("executor_target", "") or "").strip()
    if executor_target:
        return f"coding-agent:{_coding_agent_state(runtime)}({_coding_agent_label(executor_target)})"
    preference = str(executor.get("default", "") or "").strip()
    if preference and preference != "choose":
        return f"coding-agent:idle({_coding_agent_label(preference)})"
    return "coding-agent:not-selected"


def _coding_agent_label(value: Any) -> str:
    normalized = str(value or "").strip()
    labels = {
        "generic": "prompt",
        "hermes": "hermes",
        "codex": "codex",
        "claude-code": "claude-code",
        "omx-runtime": "omx-runtime",
        "omo-runtime": "omo-runtime",
        "omc-runtime": "omc-runtime",
    }
    return labels.get(normalized, normalized)


def _activity_label(runtime: dict[str, Any]) -> str:
    workflow = str(runtime.get("workflow", "idle"))
    phase = str(runtime.get("phase", "idle"))
    return "idle" if workflow == "idle" else f"{workflow}:{phase}"


def _coding_agent_state(runtime: dict[str, Any]) -> str:
    if not str(runtime.get("latest_run_id", "")):
        return "idle"
    if not str(runtime.get("executor_target", "")).strip():
        return "idle"
    return str(runtime.get("phase", "unknown") or "unknown")


def _topology_label(topology: dict[str, Any]) -> str:
    mode = str(topology.get("mode", "unknown"))
    active = _safe_int(topology.get("active_agent_count"), 0)
    if mode == "single_agent_target":
        return "single"
    if mode == "multi_agent_targets":
        return f"multi:{active}"
    return "unknown"


def _optional_number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed.is_integer():
        return int(parsed)
    return parsed


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_limit(value: Any, *, default: int, maximum: int = 20) -> int:
    return max(0, min(_safe_int(value, default), maximum))


def _group_rows_by_run_id(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = row.get("run_id")
        if value is None:
            continue
        run_id = str(value)
        if run_id:
            grouped.setdefault(run_id, []).append(row)
    return grouped


def read_omh_status(omh_home: str | Path | None = None, limit: int = 5) -> dict[str, Any]:
    safe_limit = _safe_limit(limit, default=5)
    home = _expand_path(omh_home) if omh_home else _default_omh_home()
    runtime_dir = home / "runtime"
    runs_dir = runtime_dir / "runs"
    state = _read_json(runtime_dir / "state.json")
    journal_dir = runtime_dir / "journal"
    journal_events_by_run = _group_rows_by_run_id(_read_jsonl(journal_dir / "events.jsonl"))
    receipts_by_run = _group_rows_by_run_id(
        _read_jsonl(journal_dir / EXTERNAL_EFFECT_RECEIPT_STORE_NAME)
    )
    runs: list[dict[str, Any]] = []
    for run_json in sorted(_child_files(runs_dir, "run.json"), reverse=True)[:safe_limit]:
        run = _read_json(run_json)
        run_id = str(run.get("run_id", run_json.parent.name))
        runs.append(
            _summarize_run(
                run_json.parent,
                run=run,
                journal_events=journal_events_by_run.get(run_id, []),
                external_effect_receipts=receipts_by_run.get(run_id, []),
            )
        )
    progress = _executor_progress_projection(runtime_dir, limit=max(safe_limit * 10, safe_limit))
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "omh_home": str(home),
        "runtime_dir": str(runtime_dir),
        "journal_path": str(runtime_dir / "journal" / "events.jsonl"),
        "runtime_state_present": bool(state),
        "latest_run_id": str(state.get("last_run_id", "")) if state else "",
        "plugin_session_end": _read_json(runtime_dir / "plugin-session-end.json"),
        "runs": runs,
        "active_executors": progress["active_executors"],
        "stale_executors": progress["stale_executors"],
        "latest_progress_events": progress["latest_progress_events"],
        "evidence_boundary": {
            "prepared_handoff": "not execution evidence",
            "execution": "requires observed delegation result",
            "verification": "requires observed wrapper verification",
            "review": "requires separate review record",
            "ci": "requires separate CI record and an external effect receipt naming the surface that ran it",
            "merge": "requires separate merge record and an external effect receipt naming the surface that merged it",
        },
        "privacy": "metadata_only",
    }


def _read_omh_hud_status(home: Path, *, limit: int) -> dict[str, Any]:
    runtime_dir = home / "runtime"
    if _contains_symlink(runtime_dir, root=home):
        return {
            "runtime_state_present": False,
            "runs": [],
            "active_executors": [],
            "stale_executors": [],
            "latest_progress_events": [],
        }
    json_reader = partial(_read_hud_json, root=runtime_dir)
    coding_reader = partial(_read_hud_coding_projection, root=runtime_dir)
    runs: list[dict[str, Any]] = []
    for run_json in sorted(
        _hud_child_files(runtime_dir / "runs", "run.json"),
        reverse=True,
    )[:limit]:
        run = json_reader(run_json)
        if run:
            runs.append(
                _summarize_run(
                    run_json.parent,
                    run=run,
                    journal_events=[],
                    external_effect_receipts=[],
                    json_reader=json_reader,
                    coding_reader=coding_reader,
                )
            )
    progress = _executor_progress_projection(
        runtime_dir,
        limit=max(limit * 10, limit),
        hud_safe=True,
    )
    return {
        "runtime_state_present": bool(json_reader(runtime_dir / "state.json")),
        "runs": runs,
        **progress,
    }


def read_omh_activity(omh_home: str | Path | None = None, limit: int = 5) -> dict[str, Any]:
    """Project only live executor state for latency-sensitive hook routing."""
    safe_limit = _safe_limit(limit, default=5)
    home = _expand_path(omh_home) if omh_home else _default_omh_home()
    runtime_dir = home / "runtime"
    progress = _executor_progress_projection(runtime_dir, limit=max(safe_limit * 10, safe_limit))
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "omh_home": str(home),
        "runtime_dir": str(runtime_dir),
        "runs": [],
        "active_executors": progress["active_executors"],
        "stale_executors": progress["stale_executors"],
        "latest_progress_events": progress["latest_progress_events"],
    }


def _executor_progress_projection(
    runtime_dir: Path,
    *,
    limit: int,
    hud_safe: bool = False,
) -> dict[str, Any]:
    bindings = _progress_bindings(runtime_dir, limit=limit, hud_safe=hud_safe)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in bindings:
        binding = item["binding"]
        binding = dict(binding)
        binding["state"] = _projected_binding_state(runtime_dir, binding)
        if binding["state"] == "expired":
            continue
        item["binding"] = binding
        groups.setdefault(str(binding.get("correlation_root", "")), []).append(item)
    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    latest_events: list[dict[str, Any]] = []
    for group in groups.values():
        primary = _choose_progress_primary(group)
        event = _latest_progress_payload(group, "event")
        report = _latest_progress_payload(group, "report")
        if not event and not report:
            continue
        if event:
            latest_events.append(_compact_progress_event(event, primary["binding"]))
        row = _progress_row(primary, group, event, report)
        if primary["binding"].get("state") == "active":
            active.append(row)
        elif primary["binding"].get("state") == "stale":
            stale.append(row)
    active.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    stale.sort(key=lambda item: str(item.get("latest_observed_at", "")), reverse=True)
    latest_events.sort(key=lambda item: str(item.get("observed_at", "")), reverse=True)
    return {
        "active_executors": active[:limit],
        "stale_executors": stale[:limit],
        "latest_progress_events": latest_events[:limit],
    }


def _progress_bindings(
    runtime_dir: Path,
    *,
    limit: int,
    hud_safe: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    roots = (
        (runtime_dir / "runs", "run"),
        (runtime_dir / "wrapper_sessions", "wrapper_session"),
    )
    for root, target_type in roots:
        child_files = _hud_child_files if hud_safe else _child_files
        json_reader = (
            partial(_read_hud_json, root=runtime_dir)
            if hud_safe
            else _read_json
        )
        jsonl_reader = (
            partial(_read_hud_jsonl, root=runtime_dir)
            if hud_safe
            else _read_jsonl
        )
        for binding_path in sorted(child_files(root, "executor_progress", "binding.json"), reverse=True):
            binding = json_reader(binding_path)
            if not _valid_progress_binding(binding, target_type):
                continue
            progress_dir = binding_path.parent
            events = jsonl_reader(progress_dir / "events.jsonl")
            reports = jsonl_reader(progress_dir / "reports.jsonl")
            binding_id = str(binding.get("binding_id", ""))
            instance_id = str(binding.get("instance_id", ""))
            matching_events = [event for event in events if _valid_progress_event(event, binding_id, instance_id)]
            matching_reports = [report for report in reports if _valid_progress_report(report, binding_id, instance_id)]
            items.append(
                {
                    "binding": binding,
                    "latest_event": matching_events[-1] if matching_events else {},
                    "latest_report": matching_reports[-1] if matching_reports else {},
                }
            )
    items.sort(key=lambda item: str(item["binding"].get("updated_at", "")), reverse=True)
    return items[:limit]


def _projected_binding_state(runtime_dir: Path, binding: dict[str, Any]) -> str:
    target_type = str(binding.get("target_type", ""))
    target_id = str(binding.get("target_id", ""))
    if _target_has_terminal_result(runtime_dir, target_type, target_id):
        return "closed"
    if str(binding.get("state", "")) == "closed":
        return "closed"
    age = _seconds_since(str(binding.get("last_observed_at") or binding.get("updated_at") or ""))
    if age is None:
        return "stale"
    expiry = _safe_int(binding.get("expiry_seconds"), 86400)
    freshness = _safe_int(binding.get("freshness_seconds"), 900)
    if age > expiry:
        return "expired"
    if age > freshness:
        return "stale"
    return "active"


def _target_has_terminal_result(runtime_dir: Path, target_type: str, target_id: str) -> bool:
    if (
        not target_id
        or target_id in {".", ".."}
        or "/" in target_id
        or "\\" in target_id
        or "\x00" in target_id
    ):
        return False
    if target_type == "run":
        delegation = _read_json(runtime_dir / "runs" / target_id / "delegation.json")
        return bool(delegation.get("observed")) and str(delegation.get("result", "")) in {"completed", "blocked", "failed"}
    if target_type == "wrapper_session":
        record = _read_json(runtime_dir / "wrapper_sessions" / target_id / "executor_session.json")
        return bool(record.get("result_observed")) and str(record.get("result", "")) in {"completed", "blocked", "failed"}
    return False


def _choose_progress_primary(group: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        binding = item["binding"]
        target_type = str(binding.get("target_type", ""))
        state = str(binding.get("state", ""))
        precedence = {
            ("wrapper_session", "active"): 5,
            ("run", "active"): 4,
            ("wrapper_session", "stale"): 3,
            ("run", "stale"): 2,
        }.get((target_type, state), 1)
        return precedence, str(binding.get("updated_at", ""))

    return sorted(group, key=sort_key, reverse=True)[0]


def _latest_progress_payload(group: list[dict[str, Any]], key: str) -> dict[str, Any]:
    payload_key = f"latest_{key}"
    timestamp_key = "observed_at" if key == "event" else "reported_at"
    payloads = [item[payload_key] for item in group if isinstance(item.get(payload_key), dict) and item[payload_key]]
    payloads.sort(key=lambda item: str(item.get(timestamp_key, "")), reverse=True)
    return payloads[0] if payloads else {}


def _progress_row(primary: dict[str, Any], group: list[dict[str, Any]], event: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    binding = primary["binding"]
    linked = [
        {
            "binding_id": item["binding"].get("binding_id", ""),
            "instance_id": item["binding"].get("instance_id", ""),
            "target_type": item["binding"].get("target_type", ""),
            "target_id": item["binding"].get("target_id", ""),
            "correlation_root": item["binding"].get("correlation_root", ""),
            "state": item["binding"].get("state", ""),
        }
        for item in group
        if item["binding"].get("binding_id") != binding.get("binding_id")
    ]
    row = {
        "primary_binding_id": binding.get("binding_id", ""),
        "primary_instance_id": binding.get("instance_id", ""),
        "binding_id": binding.get("binding_id", ""),
        "instance_id": binding.get("instance_id", ""),
        "target_type": binding.get("target_type", ""),
        "target_id": binding.get("target_id", ""),
        "executor": binding.get("executor_profile", ""),
        "executor_profile": binding.get("executor_profile", ""),
        "correlation_root": binding.get("correlation_root", ""),
        "state": binding.get("state", ""),
        "latest_event": _compact_progress_event(event, binding) if event else {},
        "latest_report": _compact_progress_report(report) if report else {},
        "latest_observed_at": str(event.get("observed_at") or binding.get("last_observed_at") or binding.get("updated_at") or ""),
        "linked_bindings": linked,
        "claim_boundary": binding.get("claim_boundary", ""),
    }
    signal = event.get("signal", {}) if event else {}
    if isinstance(signal, dict):
        for key in (
            "routed_model",
            "routed_reasoning_effort",
            "tokens_total",
            "elapsed_seconds",
            "category",
            "fallback_count",
            "turn_count",
            "tool_count",
            "cost_usd",
            "tokens_per_second",
            "cache_hit_percentage",
            "context_percentage",
        ):
            value = signal.get(key)
            if value not in (None, ""):
                row[key] = value
    return row


def _compact_progress_event(event: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": event.get("binding_id") or binding.get("binding_id", ""),
        "instance_id": event.get("instance_id") or binding.get("instance_id", ""),
        "executor_profile": event.get("executor_profile") or binding.get("executor_profile", ""),
        "event_type": event.get("event_type", ""),
        "status": event.get("status", ""),
        "summary": event.get("summary", ""),
        "observed_at": event.get("observed_at", ""),
        "claim_boundary": event.get("claim_boundary", binding.get("claim_boundary", "")),
    }


def _compact_progress_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": report.get("binding_id", ""),
        "instance_id": report.get("instance_id", ""),
        "event_type": report.get("event_type", ""),
        "status": report.get("status", ""),
        "summary": report.get("summary", ""),
        "reported_at": report.get("reported_at", ""),
        "claim_boundary": report.get("claim_boundary", ""),
    }


def _valid_progress_binding(binding: dict[str, Any], expected_target_type: str) -> bool:
    if not isinstance(binding, dict) or _has_raw_or_hidden_content(binding):
        return False
    if binding.get("schema_version") != "omh_executor_progress_binding/v1":
        return False
    target_value = binding.get("target")
    target = target_value if isinstance(target_value, dict) else {}
    target_type = str(binding.get("target_type") or target.get("type") or "")
    target_id = str(binding.get("target_id") or target.get("id") or "")
    profile = str(binding.get("executor_profile") or binding.get("executor") or "")
    if target_type != expected_target_type or target_type not in {"run", "wrapper_session"}:
        return False
    if (
        not target_id
        or target_id in {".", ".."}
        or "/" in target_id
        or "\\" in target_id
        or "\x00" in target_id
    ):
        return False
    if profile not in EXECUTOR_PROGRESS_PROFILES:
        return False
    if str(binding.get("binding_id", "")) != f"{target_type}:{target_id}:{profile}":
        return False
    if not str(binding.get("instance_id", "")).strip():
        return False
    if not str(binding.get("correlation_root", "")).strip():
        return False
    if str(binding.get("state", "")) not in EXECUTOR_PROGRESS_BINDING_STATES:
        return False
    return "not result" in str(binding.get("claim_boundary", ""))


def _valid_progress_event(event: dict[str, Any], binding_id: str, instance_id: str) -> bool:
    if not isinstance(event, dict) or _has_raw_or_hidden_content(event):
        return False
    if event.get("schema_version") != "omh_progress_event/v1":
        return False
    if str(event.get("binding_id", "")) != binding_id:
        return False
    if str(event.get("instance_id", "")) != instance_id:
        return False
    if str(event.get("event_type", "")) not in EXECUTOR_PROGRESS_EVENT_TYPES:
        return False
    if str(event.get("executor_profile", "")) not in EXECUTOR_PROGRESS_PROFILES:
        return False
    summary = str(event.get("summary", "")).strip()
    if not summary or len(summary) > 360:
        return False
    if not str(event.get("transition_fingerprint", "")).strip():
        return False
    return "not result" in str(event.get("claim_boundary", ""))


def _valid_progress_report(report: dict[str, Any], binding_id: str, instance_id: str) -> bool:
    if not isinstance(report, dict) or _has_raw_or_hidden_content(report):
        return False
    if report.get("schema_version") != "omh_progress_report/v1":
        return False
    if str(report.get("binding_id", "")) != binding_id:
        return False
    if str(report.get("instance_id", "")) != instance_id:
        return False
    if str(report.get("executor_profile", "")) not in EXECUTOR_PROGRESS_PROFILES:
        return False
    summary = str(report.get("summary", "")).strip()
    if not summary or len(summary) > 360:
        return False
    return "not result" in str(report.get("claim_boundary", ""))


def _has_raw_or_hidden_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in RAW_OR_HIDDEN_KEYS:
                return True
            if _has_raw_or_hidden_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(_has_raw_or_hidden_content(item) for item in value)
    if isinstance(value, str):
        return len(value) > 2000
    return False


def _seconds_since(value: str) -> float | None:
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - parsed.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None
