"""Read-only Hermes configuration advisory lane.

Contract: ``hermes_config_advice/v1``.

Every inspector here is strictly read-only and NON-THROWING. When any parse is
ambiguous, a file is missing, or a read fails, the inspector returns status
``unobserved`` rather than guessing ``advice`` or ``ok``. Advisory entries are a
SEPARATE structure from ``maintenance.doctor``'s ``list[Check]``: they are never
folded into ``doctor_ok()`` and never change the doctor exit code.

The ``auxiliary:`` reader in this module is intentionally self-contained. The
codebase reads Hermes ``config.yaml`` with tolerant indentation-based readers
(see ``install/config_adapter.py``) instead of importing a YAML library, and
this module matches that convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..coding.model_discovery import discover_local_models
from ..coding.model_recommendations import (
    MODEL_CATEGORIES,
    MODEL_RECOMMENDATION_DOMAINS,
    SHIPPED_MODEL_RECOMMENDATIONS,
    resolve_model_recommendation,
)
from ..config_adapter import external_dirs, read_config
from ..paths import default_hermes_home, expand_path, find_project_root
from ..plugin_bundle.omh import hermes_memory
from ..routing.owner_preference import owner_preference_path, validate_owner_preference
from ..system.local_store import read_json_object_result
from ..system.metadata_safety import require_opaque_metadata_ref
from ..system.paths import OmhPaths

CONTRACT = "hermes_config_advice/v1"

# Values that mean "no explicit model / provider pin" in a tolerant reader.
_NULL_MARKERS = frozenset({"", "null", "~"})
_AUTO_PROVIDER_MARKERS = frozenset({"", "auto", "null", "~", "default"})

# Named Hermes auxiliary task slots (11), locked here for the remediation copy.
AUXILIARY_TASK_SLOTS = (
    "vision",
    "compression",
    "web_extract",
    "approval scoring",
    "skills-hub lookup",
    "MCP routing",
    "triage specifier",
    "kanban decomposer",
    "profile describer",
    "curator",
    "title",
)

# Hermes memory files and the caps Hermes falls back to when config.yaml does
# not override them. Sourced from the reader so the cap and the unit it is
# measured in cannot drift apart; the per-file cap actually in force comes from
# the reading, not from these.
DEFAULT_MEMORY_FILE_CAP_CHARS = hermes_memory.DEFAULT_MEMORY_FILE_CAP_CHARS
DEFAULT_USER_FILE_CAP_CHARS = hermes_memory.DEFAULT_USER_FILE_CAP_CHARS
MEMORY_STALE_AFTER_DAYS = 30

# Conservative SOUL starter heuristic knobs.
SOUL_STARTER_MAX_CHARS = 400
SOUL_STARTER_MARKERS = (
    "describe who this agent is",
    "this is a starter soul",
    "your agent's soul",
    "placeholder",
    "todo: define",
    "<!-- starter -->",
    "auto-seeded",
)

# Rough context-weight estimate per installed skill (SKILL.md front-loading).
APPROX_TOKENS_PER_SKILL = 350

# One sentence, two facts: the command that installs the absent engines, and
# why the command the operator already ran did not. `{command}` is filled from
# the recorded profile, because only a `full` install adds every packaged skill.
_WORKFLOW_ENGINE_REACH_REMEDIATION = (
    "Run `{command}` to install them. `omh update` adds only what the recorded profile "
    "names and otherwise refreshes what is already on disk, so a core install never "
    "acquires a full-only skill by updating; `omh skill-profile` reports the recorded "
    "and the effective profile."
)


@dataclass(frozen=True)
class AdviceEntry:
    check_id: str
    status: str  # "advice" | "ok" | "unobserved"
    remediation: str
    evidence_boundary: str
    observed: str
    read_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "read_only": self.read_only,
            "remediation": self.remediation,
            "evidence_boundary": self.evidence_boundary,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class AdvisoryReport:
    contract: str = CONTRACT
    entries: list[AdviceEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _resolve_hermes_home(hermes_home: str | Path | None) -> Path:
    if hermes_home is None:
        return default_hermes_home()
    return Path(hermes_home).expanduser()


# ---------------------------------------------------------------------------
# Model routing status and advisory
# ---------------------------------------------------------------------------


def build_model_routing_status(
    paths: OmhPaths,
    *,
    discovery_home: str | Path | None = None,
) -> dict[str, object]:
    """Join local routing metadata without claiming model execution or access."""
    home = Path(discovery_home).expanduser() if discovery_home is not None else paths.hermes_home.parent
    discovery = discover_local_models(home)
    observations = discovery.get("observations", [])
    safe_observations = [entry for entry in observations if isinstance(entry, dict)]
    confirmed = sorted(
        (dict(entry) for entry in safe_observations if entry.get("status") == "confirmed_active"),
        key=_model_observation_key,
    )
    confirmed_keys = {(str(entry.get("provider", "")), str(entry.get("model_id", ""))) for entry in confirmed}
    discovered_only = sorted(
        (
            dict(entry)
            for entry in safe_observations
            if entry.get("status") != "confirmed_active"
            and (str(entry.get("provider", "")), str(entry.get("model_id", ""))) not in confirmed_keys
        ),
        key=_model_observation_key,
    )
    active_models = [
        {
            **entry,
            "model_alias": str(entry.get("model_id", "")).rsplit("/", 1)[-1],
            "provider_family": str(entry.get("provider", "")),
        }
        for entry in confirmed
    ]
    hermes = _hermes_model_status(paths.hermes_config_path, active_models)
    maestro_categories = {
        category: _recommendation_status(
            resolve_model_recommendation(owner="maestro", active_models=active_models, category=category),
            _recommendation_head("categories", category),
        )
        for category in MODEL_CATEGORIES
    }
    maestro_domains = {
        domain: _recommendation_status(
            resolve_model_recommendation(owner="maestro", active_models=active_models, domain=domain),
            _recommendation_head("domain_affinities", domain),
        )
        for domain in MODEL_RECOMMENDATION_DOMAINS
    }
    owner_learning = _owner_learning_status(paths)
    source_statuses = {
        str(name): str(value.get("status", "unobserved"))
        for name, value in discovery.get("sources", {}).items()
        if isinstance(value, dict)
    }
    missing_heads = sorted(
        {
            str(value["missing_head"])
            for value in (*maestro_categories.values(), *maestro_domains.values())
            if value.get("missing_head")
        }
    )
    next_action = _model_routing_next_action(
        hermes=hermes,
        owner_learning=owner_learning,
        confirmed=confirmed,
        missing_heads=missing_heads,
    )
    return {
        "schema_version": "model_routing_status/v1",
        "status": _model_routing_readiness(hermes, owner_learning, confirmed),
        "models": {
            "confirmed": confirmed,
            "discovered_only": discovered_only,
            "source_statuses": source_statuses,
            "discovery_truncated": any(status == "truncated" for status in source_statuses.values()),
        },
        "hermes": hermes,
        "maestro": {
            "categories": maestro_categories,
            "domain_affinities": maestro_domains,
            "missing_heads": missing_heads,
        },
        "owner_learning": owner_learning,
        "next_action": next_action,
        "claim_boundary": (
            "This report joins local metadata only. Discovered config or session history is not confirmed "
            "model availability; confirmed-active configuration is not entitlement, credential validity, "
            "dispatch, execution, review, CI, or merge evidence. No network request was made."
        ),
    }


def check_model_routing_readiness(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
    discovery_home: str | Path | None = None,
) -> AdviceEntry:
    home = _resolve_hermes_home(hermes_home)
    paths = OmhPaths(
        omh_home=Path(omh_home).expanduser() if omh_home is not None else home.parent / ".omh",
        hermes_home=home,
    )
    try:
        status = build_model_routing_status(paths, discovery_home=discovery_home)
    except OSError as error:
        return AdviceEntry(
            "model_routing_readiness",
            "unobserved",
            "Repair the unreadable local model metadata, then run `omh coding model-routing status`.",
            "Bounded local model/config/preference metadata only; no provider or network observation.",
            f"model routing metadata unreadable: {error}",
        )
    models = status["models"]
    maestro = status["maestro"]
    hermes = status["hermes"]
    owner = status["owner_learning"]
    observed = (
        f"confirmed={len(models['confirmed'])} discovered_only={len(models['discovered_only'])} "
        f"hermes={hermes['status']} aliases={len(hermes['aliases'])} "
        f"missing_heads={len(maestro['missing_heads'])} owner_learning={owner['status']}"
    )
    return AdviceEntry(
        "model_routing_readiness",
        "ok" if status["status"] == "ready_metadata" else "advice",
        str(status["next_action"]),
        str(status["claim_boundary"]),
        observed,
    )


def _model_observation_key(entry: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(entry.get(key, "")) for key in ("model_id", "provider", "source", "variant", "timestamp"))


def _hermes_model_status(config_path: Path, active_models: list[dict[str, object]]) -> dict[str, object]:
    auth = {
        "status": "unobserved",
        "reason": "This offline status surface does not read credentials or contact providers.",
    }
    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"status": "missing", "config_path": str(config_path), "aliases": {}, "recommendation": None, "auth": auth}
    except (OSError, UnicodeDecodeError) as error:
        return {
            "status": "corrupt",
            "config_path": str(config_path),
            "aliases": {},
            "error": f"unreadable: {error}",
            "recommendation": None,
            "auth": auth,
        }
    aliases, error = parse_hermes_model_aliases(text)
    if error:
        return {
            "status": "corrupt",
            "config_path": str(config_path),
            "aliases": {},
            "error": error,
            "recommendation": None,
            "auth": auth,
        }
    resolution = resolve_model_recommendation(owner="hermes", active_models=active_models, role_slot="main")
    return {
        "status": "configured" if aliases else "aliases_unset",
        "config_path": str(config_path),
        "aliases": aliases,
        "recommendation": _recommendation_status(resolution, _recommendation_head("role_suggestions", "main")),
        "auth": auth,
    }


def parse_hermes_model_aliases(text: str) -> tuple[dict[str, str], str]:
    """The `model.aliases` mapping a Hermes config declares, or why none was read.

    Public because the setup profile pack reads the same aliases and must read
    them the same way: both halves of every entry go through
    `require_opaque_metadata_ref`, so a credential cannot arrive as an alias
    target. A second parser would be a second place for that screen to lapse.
    """
    if "\t" in text or "\x00" in text:
        return {}, "config contains unsupported tab indentation or NUL bytes"
    lines = text.splitlines()
    aliases: dict[str, str] = {}
    in_model = False
    in_aliases = False
    model_indent = aliases_indent = -1
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_model = stripped == "model:"
            in_aliases = False
            model_indent = 0 if in_model else -1
            if stripped.startswith("model_aliases:"):
                if stripped != "model_aliases:":
                    return {}, "model_aliases must be a mapping"
                in_aliases = True
                aliases_indent = 0
            continue
        if in_model and indent > model_indent and stripped.startswith("aliases:"):
            if stripped != "aliases:":
                return {}, "model.aliases must be a mapping"
            in_aliases = True
            aliases_indent = indent
            continue
        if in_aliases:
            if indent <= aliases_indent:
                in_aliases = False
                continue
            if ":" not in stripped:
                return {}, "model alias entry is malformed"
            alias, _, target = stripped.partition(":")
            alias = alias.strip().strip("'\"")
            target = target.strip().strip("'\"")
            try:
                safe_alias = require_opaque_metadata_ref(alias, field="model alias")
                safe_target = require_opaque_metadata_ref(target, field="model alias target")
            except ValueError:
                return {}, "model alias entry is malformed or unsafe"
            aliases[safe_alias] = safe_target
    return dict(sorted(aliases.items())), ""


def _recommendation_head(section: str, name: str) -> str:
    table = SHIPPED_MODEL_RECOMMENDATIONS.get(section, {})
    chain = table.get(name, []) if isinstance(table, dict) else []
    if not isinstance(chain, list) or not chain or not isinstance(chain[0], dict):
        return ""
    return str(chain[0].get("model_alias", ""))


def _recommendation_status(resolution: dict[str, object], head: str) -> dict[str, object]:
    selected = resolution.get("selected")
    selected_model = str(selected.get("model_alias", "")) if isinstance(selected, dict) else ""
    return {
        "status": str(resolution.get("status", "unconfigured")),
        "recommended_head": head,
        "selected_model": selected_model,
        "missing_head": head if head and selected_model != head else "",
        "available_chain": list(resolution.get("available_chain", [])),
        "inactive_candidates": list(resolution.get("inactive_candidates", [])),
    }


def _owner_learning_status(paths: OmhPaths) -> dict[str, object]:
    path = owner_preference_path(paths)
    if not path.exists():
        return {"status": "missing", "path": str(path), "routes": {}}
    state, error = read_json_object_result(path)
    if error or state is None:
        return {"status": "corrupt", "path": str(path), "error": error or "expected JSON object", "routes": {}}
    errors = validate_owner_preference(state)
    if errors:
        return {"status": "corrupt", "path": str(path), "error": "; ".join(errors), "routes": {}}
    routes: dict[str, object] = {}
    for family, route in state.get("routes", {}).items():
        if not isinstance(route, dict):
            continue
        count = int(route.get("consecutive_accepted_explicit_choices", 0) or 0)
        route_status = "learned" if count >= 3 else "learning"
        if count == 0 and route.get("reset_at"):
            route_status = "reset"
        routes[str(family)] = {
            "status": route_status,
            "selected_owner": str(route.get("selected_owner", "")),
            "evidence_count": count,
            "reset_at": str(route.get("reset_at", "")),
            "reset_reason": str(route.get("reset_reason", "")),
        }
    overall = "learned" if any(value.get("status") == "learned" for value in routes.values() if isinstance(value, dict)) else "unlearned"
    return {"status": overall, "path": str(path), "routes": routes}


def _model_routing_readiness(
    hermes: dict[str, object], owner: dict[str, object], confirmed: list[dict[str, str]]
) -> str:
    if hermes.get("status") == "corrupt" or owner.get("status") == "corrupt":
        return "needs_repair"
    if not confirmed:
        return "needs_confirmation"
    if hermes.get("status") in {"missing", "aliases_unset"}:
        return "needs_configuration"
    return "ready_metadata"


def _model_routing_next_action(
    *,
    hermes: dict[str, object],
    owner_learning: dict[str, object],
    confirmed: list[dict[str, str]],
    missing_heads: list[str],
) -> str:
    if hermes.get("status") == "corrupt":
        return f"Repair the Hermes config at {hermes['config_path']}, then run `omh coding model-routing status`."
    if owner_learning.get("status") == "corrupt":
        return f"Repair or archive the corrupt owner preference at {owner_learning['path']}, then run `omh coding model-routing status`."
    if not confirmed:
        return "Confirm locally active models in OMO configuration, then run `omh coding model-routing status`."
    if hermes.get("status") in {"missing", "aliases_unset"}:
        return "Preview and apply Hermes model aliases for confirmed models, then run `omh coding model-routing status`."
    if missing_heads:
        return "Review the missing recommendation heads and keep the shown confirmed fallback or configure a confirmed replacement."
    return "No metadata repair is required; choose an owner explicitly or use the visible learned default."


# ---------------------------------------------------------------------------
# 1. auxiliary_routing_unset
# ---------------------------------------------------------------------------

def _parse_auxiliary_slots(config_text: str) -> list[dict[str, str]] | None:
    """Self-contained tolerant reader for the nested ``auxiliary:`` block.

    Returns a list of slot mappings, or ``None`` when the shape is missing,
    empty, or ambiguous. Never raises for shape reasons; callers still wrap in
    try/except as a belt-and-suspenders invariant.
    """
    if "\t" in config_text:
        return None  # tabs make indentation ambiguous
    lines = config_text.splitlines()

    aux_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.startswith(" "):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "auxiliary:":
            aux_idx = idx
            break
        if stripped.startswith("auxiliary:"):
            # Inline scalar / list on the key -> unexpected shape.
            return None
    if aux_idx is None:
        return None

    block: list[str] = []
    for line in lines[aux_idx + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" "):
            break  # dedent to another top-level key ends the block
        block.append(line)
    if not block:
        return None  # declared but empty -> nothing observable

    child_indent = len(block[0]) - len(block[0].lstrip(" "))
    if child_indent == 0:
        return None

    slots: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in block:
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if indent == child_indent:
            if ":" not in content:
                return None
            key, _, value = content.partition(":")
            key = key.strip()
            value = value.strip()
            if not key or value != "":
                return None  # slots must be nested maps, not inline scalars
            current = {"__name__": key}
            slots.append(current)
        elif indent > child_indent:
            if current is None:
                return None
            if ":" not in content:
                return None
            key, _, value = content.partition(":")
            current[key.strip()] = value.strip().strip("'\"")
        else:
            return None  # misaligned indentation

    for slot in slots:
        recognized = (set(slot.keys()) - {"__name__"}) & {"provider", "model"}
        if not recognized:
            return None  # bare/truncated slot -> ambiguous
    return slots


def _auxiliary_all_unset(slots: list[dict[str, str]]) -> bool:
    for slot in slots:
        provider = slot.get("provider", "").strip().lower()
        model = slot.get("model", "").strip()
        model_set = model.lower() not in _NULL_MARKERS
        provider_set = provider not in _AUTO_PROVIDER_MARKERS
        if model_set or provider_set:
            return False
    return True


def check_auxiliary_routing_unset(hermes_home: str | Path | None = None) -> AdviceEntry:
    home = _resolve_hermes_home(hermes_home)
    config_path = home / "config.yaml"
    evidence_boundary = (
        "Local read of the Hermes config.yaml `auxiliary:` block only; the live "
        "Hermes routing decisions are not observed."
    )
    remediation = (
        "Hermes routes 11 auxiliary task slots (vision, compression, web_extract, "
        "approval scoring, skills-hub lookup, MCP routing, triage specifier, "
        "kanban decomposer, profile describer, curator, title). With every slot on "
        "provider `auto` and no model pin, the main model can burn premium tokens "
        "on these auxiliary tasks. Consider pinning a cheaper model per slot in "
        "`~/.hermes/config.yaml` under `auxiliary:`."
    )
    try:
        if not config_path.exists():
            return AdviceEntry(
                "auxiliary_routing_unset",
                "unobserved",
                remediation,
                evidence_boundary,
                f"{config_path} not found",
            )
        config_text = read_config(config_path)
        slots = _parse_auxiliary_slots(config_text)
        if slots is None or not slots:
            return AdviceEntry(
                "auxiliary_routing_unset",
                "unobserved",
                remediation,
                evidence_boundary,
                "auxiliary block missing, empty, or ambiguous shape",
            )
        if _auxiliary_all_unset(slots):
            return AdviceEntry(
                "auxiliary_routing_unset",
                "advice",
                remediation,
                evidence_boundary,
                f"all {len(slots)} observed auxiliary slot(s) use provider auto with no model pin",
            )
        return AdviceEntry(
            "auxiliary_routing_unset",
            "ok",
            remediation,
            evidence_boundary,
            f"{len(slots)} observed auxiliary slot(s); at least one pins a provider or model",
        )
    except OSError as error:
        return AdviceEntry(
            "auxiliary_routing_unset",
            "unobserved",
            remediation,
            evidence_boundary,
            f"config unreadable: {error}",
        )


# ---------------------------------------------------------------------------
# 2. soul_missing_or_starter
# ---------------------------------------------------------------------------

def _looks_like_starter_soul(content: str) -> bool:
    stripped = content.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if len(stripped) <= SOUL_STARTER_MAX_CHARS and any(
        marker in lowered for marker in SOUL_STARTER_MARKERS
    ):
        return True
    return False


def check_soul_missing_or_starter(hermes_home: str | Path | None = None) -> AdviceEntry:
    home = _resolve_hermes_home(hermes_home)
    soul_path = home / "SOUL.md"
    evidence_boundary = (
        "Local read of ~/.hermes/SOUL.md contents only; whether Hermes actually "
        "loads it as system-prompt slot #1 at runtime is not observed."
    )
    remediation = (
        "SOUL.md is Hermes system-prompt slot #1 and shapes every turn. Author a "
        "real agent persona in `~/.hermes/SOUL.md` instead of leaving it missing or "
        "on the auto-seeded starter."
    )
    try:
        if not soul_path.exists():
            return AdviceEntry(
                "soul_missing_or_starter",
                "advice",
                remediation,
                evidence_boundary,
                f"{soul_path} not found",
            )
        content = soul_path.read_text(encoding="utf-8", errors="replace")
        if _looks_like_starter_soul(content):
            return AdviceEntry(
                "soul_missing_or_starter",
                "advice",
                remediation,
                evidence_boundary,
                "SOUL.md appears empty or matches the auto-seeded starter heuristic",
            )
        return AdviceEntry(
            "soul_missing_or_starter",
            "ok",
            remediation,
            evidence_boundary,
            f"SOUL.md present with {len(content.strip())} chars of custom content",
        )
    except OSError as error:
        return AdviceEntry(
            "soul_missing_or_starter",
            "unobserved",
            remediation,
            evidence_boundary,
            f"SOUL.md unreadable: {error}",
        )


# ---------------------------------------------------------------------------
# 3. hermes_memory_staleness
# ---------------------------------------------------------------------------

def _now_seconds() -> float:
    import time

    return time.time()


def check_hermes_memory_staleness(hermes_home: str | Path | None = None) -> AdviceEntry:
    home = _resolve_hermes_home(hermes_home)
    evidence_boundary = (
        "Local character/entry/mtime read of ~/.hermes/memories/MEMORY.md and USER.md only; "
        "OMH reports on Hermes memory and cannot change Hermes memory."
    )
    remediation = (
        "OMH reports only and cannot change Hermes memory (memories/MEMORY.md and "
        "USER.md, each capped by memory.memory_char_limit / memory.user_char_limit in "
        "Hermes config.yaml). If these look stale, update them from inside Hermes; "
        "OMH will not write to them."
    )
    readings = hermes_memory.read_hermes_memory(home, now=_now_seconds())
    if not any(reading.exists for reading in readings):
        return AdviceEntry(
            "hermes_memory_staleness",
            "unobserved",
            remediation,
            evidence_boundary,
            "no memories/MEMORY.md or USER.md found",
        )
    unreadable = [reading for reading in readings if reading.error]
    if unreadable:
        return AdviceEntry(
            "hermes_memory_staleness",
            "unobserved",
            remediation,
            evidence_boundary,
            "; ".join(f"{reading.label} unreadable: {reading.error}" for reading in unreadable),
        )
    details: list[str] = []
    flagged = False
    for reading in readings:
        if not reading.exists:
            details.append(f"{reading.label} missing")
            continue
        details.append(
            f"{reading.label} {reading.chars} chars of {reading.cap} in "
            f"{len(reading.entries)} entries, {reading.age_days:.0f}d since mtime"
        )
        # A file at or over the cap is the condition Hermes rejects the next
        # write on, so it is advice even when the file was touched today.
        if reading.over_cap or reading.age_days >= MEMORY_STALE_AFTER_DAYS:
            flagged = True
    return AdviceEntry(
        "hermes_memory_staleness",
        "advice" if flagged else "ok",
        remediation,
        evidence_boundary,
        "; ".join(details),
    )


# ---------------------------------------------------------------------------
# 4. legacy_plan_artifacts
# ---------------------------------------------------------------------------

def check_legacy_plan_artifacts(hermes_home: str | Path | None = None) -> AdviceEntry:
    """Report plans left in Hermes' home by the pre-relocation writer."""
    home = _resolve_hermes_home(hermes_home)
    legacy_dirs = ((home / "plans", "plans"), (home / "context", "context"))
    evidence_boundary = (
        "Local file count of ~/.hermes/plans and ~/.hermes/context only; OMH does not read, "
        "move, or delete them."
    )
    remediation = (
        "OMH used to write plan artifacts into Hermes' own home. It now writes them to "
        "`<repo>/.omh/plans`, so these older files are no longer read by anything. They are "
        "plain markdown: `omh hermes plan-accept <path>` still works on one, and they are "
        "safe to delete or archive by hand. OMH will not touch them."
    )
    counts: list[str] = []
    try:
        for directory, label in legacy_dirs:
            if not directory.is_dir():
                continue
            found = len([entry for entry in directory.glob("*.md") if entry.is_file()])
            if found:
                counts.append(f"{found} file(s) in {label}")
    except OSError as error:
        return AdviceEntry(
            "legacy_plan_artifacts",
            "unobserved",
            remediation,
            evidence_boundary,
            f"legacy plan directories unreadable: {error}",
        )
    if not counts:
        return AdviceEntry(
            "legacy_plan_artifacts",
            "ok",
            remediation,
            evidence_boundary,
            "no plan artifacts left under ~/.hermes",
        )
    return AdviceEntry(
        "legacy_plan_artifacts",
        "advice",
        remediation,
        evidence_boundary,
        "; ".join(counts),
    )


# ---------------------------------------------------------------------------
# 5. orphaned_project_scope_store
# ---------------------------------------------------------------------------

def check_orphaned_project_scope_store(
    hermes_home: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
) -> AdviceEntry:
    """Report a `--scope project` store stranded below the repository root.

    `--scope project` used to anchor on the literal working directory, so
    running it from a subdirectory installed into `<subdir>/.omh`. It now
    anchors at the repository root, which leaves any such install unreachable.
    This is the exact inverse of that change, not a guess: it looks only between
    the current directory and the root, so it can fire only for a store the
    change actually orphaned.
    """
    del hermes_home  # this check reads the working directory, not Hermes' home
    evidence_boundary = (
        "Local existence check of `.omh/manifest.json` in directories between the working "
        "directory and the repository root; OMH does not read, move, or delete them."
    )
    remediation = (
        "`--scope project` now anchors at the repository root, so a store installed from a "
        "subdirectory is no longer found. Re-run `omh --scope project setup` from the "
        "repository root, then delete the old directory by hand. OMH will not move it."
    )
    try:
        root = find_project_root(cwd)
        start = expand_path(cwd or Path.cwd())
        if root is None or start == root:
            return AdviceEntry(
                "orphaned_project_scope_store",
                "ok",
                remediation,
                evidence_boundary,
                "no subdirectory between the working directory and a repository root",
            )
        stranded = [
            str(candidate)
            for candidate in _ancestors_below(start, root)
            if (candidate / ".omh" / "manifest.json").is_file()
        ]
    except OSError as error:
        return AdviceEntry(
            "orphaned_project_scope_store",
            "unobserved",
            remediation,
            evidence_boundary,
            f"working directory unreadable: {error}",
        )
    if not stranded:
        return AdviceEntry(
            "orphaned_project_scope_store",
            "ok",
            remediation,
            evidence_boundary,
            "no project-scope store below the repository root",
        )
    return AdviceEntry(
        "orphaned_project_scope_store",
        "advice",
        remediation,
        evidence_boundary,
        "; ".join(f"stranded store in {path}" for path in stranded),
    )


def _ancestors_below(start: Path, root: Path) -> list[Path]:
    """`start` and its parents, stopping before `root`."""
    below: list[Path] = []
    for candidate in (start, *start.parents):
        if candidate == root:
            break
        below.append(candidate)
    return below


# ---------------------------------------------------------------------------
# 6. installed_skill_context_weight
# ---------------------------------------------------------------------------

def _count_skill_dirs(skills_dir: Path) -> int:
    """Skills a host would register from this directory, in either install layout.

    Skills install under `<skills_dir>/<category>/<label>/`, so counting only the
    top level reported a full install as holding no skill at all. A flat directory
    left by an older release still registers, so both depths count.
    """
    from ..install.installer import installed_skill_directories

    return len(installed_skill_directories(skills_dir))


def _derive_skill_dirs(hermes_home: Path) -> list[Path]:
    config_path = hermes_home / "config.yaml"
    if not config_path.exists():
        return []
    config_text = read_config(config_path)
    dirs: list[Path] = []
    for raw in external_dirs(config_text):
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs


def check_installed_skill_context_weight(
    hermes_home: str | Path | None = None,
    skills_dirs: list[Path] | None = None,
) -> AdviceEntry:
    home = _resolve_hermes_home(hermes_home)
    evidence_boundary = (
        "Local count of OMH-managed SKILL.md directories only; the runtime context "
        "budget Hermes actually spends is not observed."
    )
    remediation = (
        "Installed skills add up-front context. `tools.tool_search.enabled` already "
        "defaults to auto (threshold_pct 10), so confirm it stays on rather than "
        "enabling it anew. To trim always-loaded skills use `hermes skills config` "
        "and `hermes skills opt-out`."
    )
    try:
        resolved_dirs = skills_dirs if skills_dirs is not None else _derive_skill_dirs(home)
        if not resolved_dirs:
            return AdviceEntry(
                "installed_skill_context_weight",
                "unobserved",
                remediation,
                evidence_boundary,
                "no registered OMH skill directory found",
            )
        skill_count = 0
        for skills_dir in resolved_dirs:
            skills_dir = Path(skills_dir)
            if skills_dir.is_dir():
                skill_count += _count_skill_dirs(skills_dir)
        if skill_count == 0:
            return AdviceEntry(
                "installed_skill_context_weight",
                "unobserved",
                remediation,
                evidence_boundary,
                "registered skill directory present but no SKILL.md found",
            )
        approx_tokens = skill_count * APPROX_TOKENS_PER_SKILL
        return AdviceEntry(
            "installed_skill_context_weight",
            "advice",
            remediation,
            evidence_boundary,
            f"{skill_count} installed OMH skill(s) ~{approx_tokens} tokens of up-front context",
        )
    except OSError as error:
        return AdviceEntry(
            "installed_skill_context_weight",
            "unobserved",
            remediation,
            evidence_boundary,
            f"skill directory unreadable: {error}",
        )


def check_workflow_engine_reach(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
) -> AdviceEntry:
    """Say when the recorded profile cannot reach the ULW workflow engines.

    `install_skill_pack` refreshes whatever is on disk and ADDS only what the
    recorded profile names, so a `core` install can never acquire a full-only
    skill: no number of `omh update` runs will add one, and only `--full` or an
    explicit reconcile changes that. The split is deliberate and stays -- an
    update that silently shed installed skills, or one that left them on an
    older render, would each be worse.

    What was missing is the consequence. None of the canonical ULW workflow
    engines is in `CORE_PROFILE_SKILLS`, so a core install holds none of them;
    a user who invokes one finds nothing, and until this entry existed no
    surface said why or named the command that fixes it. `--core`'s own help
    text states the trade at the moment of choosing and nothing restates it
    afterwards, which is exactly when it is needed.

    This sits in the advisory lane rather than among the doctor checks because
    core is a legitimate, deliberately recommended profile: a fact with a
    consequence, not a health failure, and it must not move the doctor status
    or exit code. It is the honest counterpart of
    `installed_skill_context_weight`, which states the cost of the other choice.

    The finding is derived from which engines are absent, never from the
    profile label, so an install that has them stays silent whatever it
    recorded.
    """
    from ..install.installer import installed_skill_names
    from ..manifest import read_manifest
    from ..skills.catalog import ulw_inventory_payload

    home = _resolve_hermes_home(hermes_home)
    paths = OmhPaths(
        omh_home=Path(omh_home).expanduser() if omh_home is not None else home.parent / ".omh",
        hermes_home=home,
    )
    evidence_boundary = (
        "Local install manifest and on-disk skill directories only; whether Hermes would "
        "have selected an absent engine is not observed."
    )
    try:
        manifest = read_manifest(paths.manifest_path)
        installed = set(installed_skill_names(paths.skills_dir))
    except OSError as error:
        return AdviceEntry(
            "workflow_engine_reach",
            "unobserved",
            _WORKFLOW_ENGINE_REACH_REMEDIATION.format(command="omh update --full"),
            evidence_boundary,
            f"install manifest or skill directory unreadable: {error}",
        )
    profile = str((manifest or {}).get("skill_profile") or "")
    # Only a `full` install adds every packaged skill; every other recorded
    # value needs the flag that changes the profile.
    command = "omh update" if profile == "full" else "omh update --full"
    remediation = _WORKFLOW_ENGINE_REACH_REMEDIATION.format(command=command)
    if manifest is None or not installed:
        return AdviceEntry(
            "workflow_engine_reach",
            "unobserved",
            remediation,
            evidence_boundary,
            "no OMH skill install found to measure reach against",
        )
    engines = ulw_inventory_payload()["canonical_engines"]
    absent = sorted(
        str(engine["display_name"]) for engine in engines if str(engine["canonical"]) not in installed
    )
    if not absent:
        return AdviceEntry(
            "workflow_engine_reach",
            "ok",
            remediation,
            evidence_boundary,
            f"all {len(engines)} ULW workflow engine(s) installed; profile={profile or 'unrecorded'}",
        )
    return AdviceEntry(
        "workflow_engine_reach",
        "advice",
        remediation,
        evidence_boundary,
        (
            f"recorded skill profile {profile or 'unrecorded'}; {len(absent)} of {len(engines)} "
            f"ULW workflow engine(s) not installed: {', '.join(absent)}"
        ),
    )


def run_config_advisories(
    hermes_home: str | Path | None = None,
    *,
    omh_home: str | Path | None = None,
    discovery_home: str | Path | None = None,
) -> AdvisoryReport:
    """Run every read-only inspector and return the separate advisory report."""
    return AdvisoryReport(
        contract=CONTRACT,
        entries=[
            check_model_routing_readiness(
                hermes_home,
                omh_home=omh_home,
                discovery_home=discovery_home,
            ),
            check_auxiliary_routing_unset(hermes_home),
            check_soul_missing_or_starter(hermes_home),
            check_hermes_memory_staleness(hermes_home),
            check_legacy_plan_artifacts(hermes_home),
            check_orphaned_project_scope_store(hermes_home),
            check_installed_skill_context_weight(hermes_home),
            check_workflow_engine_reach(hermes_home, omh_home=omh_home),
        ],
    )
