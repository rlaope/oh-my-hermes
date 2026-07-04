from __future__ import annotations

from typing import Any

from ..system.local_store import read_json_object_result, utc_now
from ..system.paths import OmhPaths

ACHIEVEMENTS_OBSERVATION_SCHEMA_VERSION = "hermes_achievements_observation/v1"
ACHIEVEMENTS_AGENT_PROFILE_SCHEMA_VERSION = "hermes_achievements_agent_profile/v1"
ACHIEVEMENTS_EVIDENCE_BOUNDARY = (
    "Achievements are observed from local hermes-achievements plugin artifacts only. "
    "OMH does not rescan Hermes session history and does not claim unlocks it did not read."
)
BADGE_STATES = ("unlocked", "discovered", "secret")
TIER_ORDER = ("copper", "silver", "gold", "diamond", "olympian")

# The plugin artifact layout is upstream-internal; only badge ids are stable.
# Every extractor below tolerates missing keys and unknown shapes by degrading
# to fewer observed fields instead of raising.
_SNAPSHOT_BADGE_KEYS = ("achievements", "badges", "catalog", "items")
_STATE_UNLOCK_KEYS = ("unlocked", "unlocks", "unlocked_badges", "history")
_SCAN_TIMESTAMP_KEYS = ("completed_at", "scanned_at", "generated_at", "last_scan_at", "updated_at")


def observe_achievements(paths: OmhPaths, *, recent_limit: int = 5) -> dict[str, Any]:
    snapshot_path = paths.hermes_achievements_snapshot_path
    state_path = paths.hermes_achievements_state_path
    errors: list[str] = []
    snapshot, snapshot_error = read_json_object_result(snapshot_path)
    if snapshot_error:
        errors.append(f"scan_snapshot.json: {snapshot_error}")
    state, state_error = read_json_object_result(state_path)
    if state_error:
        errors.append(f"state.json: {state_error}")

    badges = _badges_from_snapshot(snapshot or {})
    _apply_state_unlocks(badges, state or {})
    badge_list = sorted(badges.values(), key=lambda badge: (badge["category"], badge["name"], badge["badge_id"]))

    observed = snapshot is not None or state is not None
    summary = _summary(badge_list, snapshot or {})
    return {
        "schema_version": ACHIEVEMENTS_OBSERVATION_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "status": "observed" if observed else "not_observed",
        "observed": observed,
        "source": {
            "plugin_dir": str(paths.hermes_achievements_plugin_dir),
            "snapshot_path": str(snapshot_path),
            "snapshot_observed": snapshot is not None,
            "state_path": str(state_path),
            "state_observed": state is not None,
        },
        "errors": errors,
        "summary": summary,
        "badges": badge_list,
        "recent_unlocks": _recent_unlocks(badge_list, limit=recent_limit),
        "agent_profile": _agent_profile(paths, summary, observed=observed),
        "evidence_boundary": ACHIEVEMENTS_EVIDENCE_BOUNDARY,
        "privacy": "metadata_only",
    }


def filter_badges(
    badges: list[dict[str, Any]],
    *,
    category: str = "",
    state: str = "",
    limit: int = 0,
) -> list[dict[str, Any]]:
    selected = list(badges)
    if category:
        wanted_category = category.strip().lower()
        selected = [badge for badge in selected if badge["category"].lower() == wanted_category]
    if state:
        wanted_state = state.strip().lower()
        selected = [badge for badge in selected if badge["state"] == wanted_state]
    if limit > 0:
        selected = selected[:limit]
    return selected


def find_badge(badges: list[dict[str, Any]], badge_id: str) -> dict[str, Any] | None:
    wanted = badge_id.strip()
    for badge in badges:
        if badge["badge_id"] == wanted:
            return badge
    lowered = wanted.lower()
    for badge in badges:
        if badge["badge_id"].lower() == lowered or badge["name"].lower() == lowered:
            return badge
    return None


def render_achievements_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# Hermes Achievements (OMH observation)",
        "",
        f"- Status: {payload.get('status', 'not_observed')}",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Unlocked: {summary.get('unlocked_count', 0)} / {summary.get('total_count', 0)}",
    ]
    if summary.get("top_tier"):
        lines.append(f"- Top tier: {summary['top_tier']}")
    if summary.get("last_scan_at"):
        lines.append(f"- Last plugin scan: {summary['last_scan_at']}")
    badges = payload.get("badges", [])
    if badges:
        current_category = None
        for badge in badges:
            if badge["category"] != current_category:
                current_category = badge["category"]
                lines.extend(
                    [
                        "",
                        f"## {current_category}",
                        "",
                        "| Badge | Tier | State | Progress | Unlocked at |",
                        "| --- | --- | --- | --- | --- |",
                    ]
                )
            lines.append(
                f"| {badge['name']} (`{badge['badge_id']}`) | {badge.get('tier') or ''} "
                f"| {badge['state']} | {_progress_text(badge.get('progress_percent'))} "
                f"| {badge.get('unlocked_at') or ''} |"
            )
    else:
        lines.extend(["", "No local hermes-achievements badge artifacts were observed."])
    lines.extend(["", f"Boundary: {payload.get('evidence_boundary', ACHIEVEMENTS_EVIDENCE_BOUNDARY)}", ""])
    return "\n".join(lines)


def _progress_text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f"{float(value):g}%"


def _clean_text(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _badge_entries(container: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(container, dict):
        return [(_clean_text(key), value) for key, value in container.items() if isinstance(value, dict)]
    if isinstance(container, list):
        return [("", value) for value in container if isinstance(value, dict)]
    return []


def _badges_from_snapshot(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    badges: dict[str, dict[str, Any]] = {}
    for key in _SNAPSHOT_BADGE_KEYS:
        entries = _badge_entries(snapshot.get(key))
        if not entries:
            continue
        for fallback_id, entry in entries:
            badge = _normalize_badge(entry, fallback_id=fallback_id)
            if badge:
                badges[badge["badge_id"]] = badge
        break
    return badges


def _normalize_badge(entry: dict[str, Any], *, fallback_id: str = "") -> dict[str, Any] | None:
    badge_id = _clean_text(entry.get("id") or entry.get("badge_id") or entry.get("key")) or fallback_id
    if not badge_id:
        return None
    return {
        "badge_id": badge_id,
        "name": _clean_text(entry.get("name") or entry.get("title")) or badge_id,
        "tier": _normalize_tier(entry.get("tier")),
        "category": _clean_text(entry.get("category") or entry.get("group")) or "uncategorized",
        "state": _normalize_state(entry),
        "progress_percent": _progress_percent(entry.get("progress")),
        "unlocked_at": _clean_text(entry.get("unlocked_at") or entry.get("unlockedAt")),
    }


def _normalize_tier(value: Any) -> str:
    tier = _clean_text(value).lower()
    return tier if tier in TIER_ORDER else ""


def _normalize_state(entry: dict[str, Any]) -> str:
    state = _clean_text(entry.get("state") or entry.get("status")).lower()
    if state in BADGE_STATES:
        return state
    if entry.get("unlocked") is True:
        return "unlocked"
    if entry.get("secret") is True or entry.get("hidden") is True:
        return "secret"
    return "discovered"


def _progress_percent(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        percent = number * 100.0 if 0.0 <= number <= 1.0 else number
        return round(min(max(percent, 0.0), 100.0), 1)
    if isinstance(value, dict):
        current = value.get("current")
        target = value.get("target") or value.get("total")
        if isinstance(current, (int, float)) and isinstance(target, (int, float)) and float(target) > 0:
            return round(min(max(float(current) / float(target) * 100.0, 0.0), 100.0), 1)
        percent = value.get("percent")
        if isinstance(percent, (int, float)) and not isinstance(percent, bool):
            return round(min(max(float(percent), 0.0), 100.0), 1)
    return None


def _unlock_entries(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    for key in _STATE_UNLOCK_KEYS:
        container = state.get(key)
        if isinstance(container, dict):
            return [
                (_clean_text(badge_id), meta if isinstance(meta, dict) else {})
                for badge_id, meta in container.items()
            ]
        if isinstance(container, list):
            entries: list[tuple[str, dict[str, Any]]] = []
            for item in container:
                if isinstance(item, dict):
                    badge_id = _clean_text(item.get("id") or item.get("badge_id") or item.get("key"))
                    if badge_id:
                        entries.append((badge_id, item))
                else:
                    badge_id = _clean_text(item)
                    if badge_id:
                        entries.append((badge_id, {}))
            return entries
    return []


def _apply_state_unlocks(badges: dict[str, dict[str, Any]], state: dict[str, Any]) -> None:
    for badge_id, meta in _unlock_entries(state):
        if not badge_id:
            continue
        badge = badges.get(badge_id)
        if badge is None:
            badges[badge_id] = {
                "badge_id": badge_id,
                "name": _clean_text(meta.get("name") or meta.get("title")) or badge_id,
                "tier": _normalize_tier(meta.get("tier")),
                "category": _clean_text(meta.get("category") or meta.get("group")) or "uncategorized",
                "state": "unlocked",
                "progress_percent": 100.0,
                "unlocked_at": _clean_text(meta.get("unlocked_at") or meta.get("unlockedAt")),
            }
            continue
        badge["state"] = "unlocked"
        badge["progress_percent"] = 100.0
        tier = _normalize_tier(meta.get("tier"))
        if tier:
            badge["tier"] = tier
        unlocked_at = _clean_text(meta.get("unlocked_at") or meta.get("unlockedAt"))
        if unlocked_at:
            badge["unlocked_at"] = unlocked_at


def _summary(badges: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    unlocked = [badge for badge in badges if badge["state"] == "unlocked"]
    categories: dict[str, dict[str, int]] = {}
    for badge in badges:
        bucket = categories.setdefault(badge["category"], {"total": 0, "unlocked": 0})
        bucket["total"] += 1
        if badge["state"] == "unlocked":
            bucket["unlocked"] += 1
    return {
        "total_count": len(badges),
        "unlocked_count": len(unlocked),
        "discovered_count": sum(1 for badge in badges if badge["state"] == "discovered"),
        "secret_count": sum(1 for badge in badges if badge["state"] == "secret"),
        "top_tier": _top_tier(unlocked),
        "categories": [
            {"category": name, "total": bucket["total"], "unlocked": bucket["unlocked"]}
            for name, bucket in sorted(categories.items())
        ],
        "last_scan_at": _last_scan_at(snapshot),
    }


def _top_tier(unlocked: list[dict[str, Any]]) -> str:
    best = -1
    for badge in unlocked:
        tier = badge.get("tier", "")
        if tier in TIER_ORDER:
            best = max(best, TIER_ORDER.index(tier))
    return TIER_ORDER[best] if best >= 0 else ""


def _last_scan_at(snapshot: dict[str, Any]) -> str:
    for key in _SCAN_TIMESTAMP_KEYS:
        value = _clean_text(snapshot.get(key))
        if value:
            return value
    return ""


def _agent_profile(paths: OmhPaths, summary: dict[str, Any], *, observed: bool) -> dict[str, Any]:
    upstream, upstream_error = read_json_object_result(paths.hermes_achievements_agent_summary_path)
    profile: dict[str, Any] = {
        "schema_version": ACHIEVEMENTS_AGENT_PROFILE_SCHEMA_VERSION,
        "observed": observed or upstream is not None,
        "derivation": "none",
        "strengths": [],
        "gaps": [],
        "top_tier": summary.get("top_tier", ""),
        "unlocked_count": summary.get("unlocked_count", 0),
        "total_count": summary.get("total_count", 0),
        "source": {
            "agent_summary_path": str(paths.hermes_achievements_agent_summary_path),
            "agent_summary_observed": upstream is not None,
            "agent_summary_error": upstream_error or "",
        },
        "routing_rule": (
            "Use strengths and gaps only as advisory workflow-suggestion context; "
            "never present them as productivity scores or execution evidence."
        ),
    }
    if upstream is not None:
        profile["derivation"] = "upstream_agent_summary"
        profile["strengths"] = _bounded_labels(upstream.get("strengths"))
        profile["gaps"] = _bounded_labels(upstream.get("gaps"))
        top_tier = _normalize_tier(upstream.get("top_tier"))
        if top_tier:
            profile["top_tier"] = top_tier
        for key in ("unlocked_count", "total_count"):
            value = upstream.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                profile[key] = value
        return profile
    if observed:
        categories = summary.get("categories", [])
        if isinstance(categories, list):
            unlocked = [entry for entry in categories if isinstance(entry, dict) and entry.get("unlocked", 0) > 0]
            locked = [entry for entry in categories if isinstance(entry, dict) and entry.get("unlocked", 0) == 0]
            unlocked.sort(key=lambda entry: (-int(entry.get("unlocked", 0)), str(entry.get("category", ""))))
            profile["derivation"] = "derived_from_observed_badges"
            profile["strengths"] = [str(entry.get("category", "")) for entry in unlocked[:5]]
            profile["gaps"] = [str(entry.get("category", "")) for entry in locked[:5]]
    return profile


def _bounded_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels = [str(item).strip() for item in value if isinstance(item, (str, int, float))]
    return [label for label in labels if label][:5]


def _recent_unlocks(badges: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    unlocked = [badge for badge in badges if badge["state"] == "unlocked"]
    dated = sorted(
        (badge for badge in unlocked if badge["unlocked_at"]),
        key=lambda badge: badge["unlocked_at"],
        reverse=True,
    )
    undated = [badge for badge in unlocked if not badge["unlocked_at"]]
    safe_limit = max(0, int(limit))
    return [dict(badge) for badge in (dated + undated)[:safe_limit]]
