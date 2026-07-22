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

from ..config_adapter import external_dirs, read_config
from ..paths import default_hermes_home

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

# Hermes memory files and their observed soft caps (chars).
MEMORY_FILE_CAP_CHARS = 2200
USER_FILE_CAP_CHARS = 1375
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
    memory_path = home / "memories" / "MEMORY.md"
    user_path = home / "memories" / "USER.md"
    evidence_boundary = (
        "Local size/mtime read of ~/.hermes/memories/MEMORY.md and USER.md only; "
        "OMH reports on Hermes memory and cannot change Hermes memory."
    )
    remediation = (
        "OMH reports only and cannot change Hermes memory (memories/MEMORY.md ~2,200 "
        "chars, USER.md ~1,375 chars). If these look stale, update them from inside "
        "Hermes; OMH will not write to them."
    )
    try:
        if not memory_path.exists() and not user_path.exists():
            return AdviceEntry(
                "hermes_memory_staleness",
                "unobserved",
                remediation,
                evidence_boundary,
                "no memories/MEMORY.md or USER.md found",
            )
        now = _now_seconds()
        details: list[str] = []
        stale = False
        for label, path, cap in (
            ("MEMORY.md", memory_path, MEMORY_FILE_CAP_CHARS),
            ("USER.md", user_path, USER_FILE_CAP_CHARS),
        ):
            if not path.exists():
                details.append(f"{label} missing")
                continue
            stat = path.stat()
            age_days = max(0.0, (now - stat.st_mtime) / 86400.0)
            details.append(
                f"{label} {stat.st_size} bytes (cap ~{cap}), {age_days:.0f}d since mtime"
            )
            if age_days >= MEMORY_STALE_AFTER_DAYS:
                stale = True
        status = "advice" if stale else "ok"
        return AdviceEntry(
            "hermes_memory_staleness",
            status,
            remediation,
            evidence_boundary,
            "; ".join(details),
        )
    except OSError as error:
        return AdviceEntry(
            "hermes_memory_staleness",
            "unobserved",
            remediation,
            evidence_boundary,
            f"memory files unreadable: {error}",
        )


# ---------------------------------------------------------------------------
# 4. installed_skill_context_weight
# ---------------------------------------------------------------------------

def _count_skill_dirs(skills_dir: Path) -> int:
    count = 0
    for child in skills_dir.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        if (child / "SKILL.md").is_file():
            count += 1
    return count


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


def run_config_advisories(hermes_home: str | Path | None = None) -> AdvisoryReport:
    """Run all four read-only inspectors and return the separate advisory report."""
    return AdvisoryReport(
        contract=CONTRACT,
        entries=[
            check_auxiliary_routing_unset(hermes_home),
            check_soul_missing_or_starter(hermes_home),
            check_hermes_memory_staleness(hermes_home),
            check_installed_skill_context_weight(hermes_home),
        ],
    )
