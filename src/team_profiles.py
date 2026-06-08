from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, atomic_write_text, utc_now
from .paths import OmhPaths


TEAM_PROFILE_SCHEMA_VERSION = "omhm_team_profile_pack/v1"


class TeamProfileError(ValueError):
    pass


@dataclass(frozen=True)
class TeamRole:
    id: str
    title: str
    role: str
    purpose: str
    owns: tuple[str, ...]
    not_owned: tuple[str, ...]
    escalation: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "role": self.role,
            "purpose": self.purpose,
            "owns": list(self.owns),
            "not_owned": list(self.not_owned),
            "escalation": list(self.escalation),
        }


@dataclass(frozen=True)
class TeamProfilePack:
    id: str
    title: str
    summary: str
    use_when: str
    roles: tuple[TeamRole, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "use_when": self.use_when,
            "roles": [role.to_dict() for role in self.roles],
            "install_command": f"omh setup --profile-pack {self.id}",
            "claim_boundary": _CLAIM_BOUNDARY,
        }


_CLAIM_BOUNDARY = (
    "Installing a team profile pack creates Hermes agent role files only. It does not prove "
    "Hermes activated those profiles, spawned agents, executed code, reviewed a PR, passed CI, "
    "or merged anything."
)


_COMMON_NOT_OWNED = (
    "claim observed work without matching runtime or wrapper evidence",
    "hide coding execution inside Hermes",
    "patch Hermes core or require platform credentials",
)


TEAM_PROFILE_PACKS: tuple[TeamProfilePack, ...] = (
    TeamProfilePack(
        id="startup-delivery",
        title="Startup Delivery Team",
        summary="A lightweight product delivery loop for small teams that want clear product, tech, QA, and release ownership.",
        use_when="Use when a founder or small SaaS team wants Hermes to turn chat signals into scoped product work and release-ready handoffs.",
        roles=(
            TeamRole(
                id="product-lead",
                title="Product Lead",
                role="Product Lead",
                purpose="Clarify customer value, rank feedback, and shape acceptance criteria before implementation.",
                owns=("customer signal triage", "problem framing", "acceptance criteria", "product tradeoffs"),
                not_owned=("implementation", "merge approval", *_COMMON_NOT_OWNED),
                escalation=("scope is unclear", "business priority conflicts", "customer evidence is missing"),
            ),
            TeamRole(
                id="tech-lead",
                title="Tech Lead",
                role="Technical Lead",
                purpose="Choose the technical path, decide whether Hermes retains work or prepares an executor handoff, and preserve risk boundaries.",
                owns=("technical plan", "executor selection", "risk notes", "verification strategy"),
                not_owned=("unobserved execution claims", "business priority decisions", *_COMMON_NOT_OWNED),
                escalation=("architecture risk is high", "executor choice is ambiguous", "verification cannot be named"),
            ),
            TeamRole(
                id="qa-gate",
                title="QA Gate",
                role="Quality Gate",
                purpose="Keep expected behavior, test evidence, and release confidence separate.",
                owns=("test checklist", "observed verification", "regression risk", "quality summary"),
                not_owned=("fix implementation", "CI claims without records", *_COMMON_NOT_OWNED),
                escalation=("tests are missing", "verification is contradictory", "release risk remains high"),
            ),
            TeamRole(
                id="release-lead",
                title="Release Lead",
                role="Release Lead",
                purpose="Summarize readiness, blockers, and user-facing release status in plain language.",
                owns=("release summary", "blocker status", "merge-ready evidence", "post-release follow-up"),
                not_owned=("approval without human or policy gate", "deployment claims without evidence", *_COMMON_NOT_OWNED),
                escalation=("approval is required", "CI or review is missing", "deployment health is unobserved"),
            ),
        ),
    ),
    TeamProfilePack(
        id="engineering-delivery",
        title="Engineering Delivery Team",
        summary="An engineering-centered workflow for planning, coding handoff, review, and release gates.",
        use_when="Use when the main work is repository change management and the operator wants clear handoff/review ownership.",
        roles=(
            TeamRole(
                id="planning-lead",
                title="Planning Lead",
                role="Planning Lead",
                purpose="Turn ambiguous engineering requests into scoped plans with non-goals and verification criteria.",
                owns=("clarification", "scope", "non-goals", "acceptance criteria"),
                not_owned=("implementation", "review approval", *_COMMON_NOT_OWNED),
                escalation=("scope changes materially", "the plan cannot be verified", "the user must choose a tradeoff"),
            ),
            TeamRole(
                id="coding-handoff",
                title="Coding Handoff",
                role="Coding Handoff",
                purpose="Prepare executor-neutral coding handoffs and explain what is still unobserved.",
                owns=("executor choice", "handoff payload", "prompt-only fallback", "prepared-vs-observed status"),
                not_owned=("executor result", "test execution", "merge", *_COMMON_NOT_OWNED),
                escalation=("executor is not selected", "handoff lacks acceptance criteria", "runtime evidence is unavailable"),
            ),
            TeamRole(
                id="review-gate",
                title="Review Gate",
                role="Review Gate",
                purpose="Separate findings, fixes, review evidence, CI, and merge readiness.",
                owns=("review findings", "fix evidence requirements", "CI/review status", "merge-readiness check"),
                not_owned=("fixing code", "overriding failed CI", *_COMMON_NOT_OWNED),
                escalation=("review finds a blocker", "CI is missing or failed", "merge readiness is contradicted"),
            ),
            TeamRole(
                id="release-gate",
                title="Release Gate",
                role="Release Gate",
                purpose="Confirm final release claims match observed evidence.",
                owns=("release checklist", "claim audit", "final status report", "follow-up list"),
                not_owned=("shipping without approval", "deployment without observed health", *_COMMON_NOT_OWNED),
                escalation=("claim evidence is missing", "approval is unclear", "release notes overstate reality"),
            ),
        ),
    ),
    TeamProfilePack(
        id="research-strategy",
        title="Research Strategy Team",
        summary="A non-coding team profile for source-backed research, strategy synthesis, and meeting preparation.",
        use_when="Use when Hermes should help with business research, leadership prep, strategy memos, and decisions without defaulting to coding.",
        roles=(
            TeamRole(
                id="research-lead",
                title="Research Lead",
                role="Research Lead",
                purpose="Own source boundaries, confidence, and unknowns for business or technical research.",
                owns=("research question", "source boundary", "confidence", "unknowns"),
                not_owned=("implementation plan by default", "unsupported claims", *_COMMON_NOT_OWNED),
                escalation=("sources are unavailable", "facts are time-sensitive", "confidence is low"),
            ),
            TeamRole(
                id="strategy-lead",
                title="Strategy Lead",
                role="Strategy Lead",
                purpose="Convert research and feedback into options, tradeoffs, and decision-ready recommendations.",
                owns=("options", "tradeoffs", "decision memo", "next-step recommendation"),
                not_owned=("accepted decision", "implementation", *_COMMON_NOT_OWNED),
                escalation=("decision owner is unclear", "options require more evidence", "risk tolerance is unknown"),
            ),
            TeamRole(
                id="meeting-lead",
                title="Meeting Lead",
                role="Meeting Lead",
                purpose="Prepare agendas, discussion prompts, decisions, and follow-up capture.",
                owns=("agenda", "discussion prompts", "decision log", "follow-up framing"),
                not_owned=("claiming a meeting happened", "assigning implementation silently", *_COMMON_NOT_OWNED),
                escalation=("attendees or decision owner are unclear", "follow-up requires code work", "inputs are incomplete"),
            ),
        ),
    ),
    TeamProfilePack(
        id="cto-loop",
        title="CTO Loop",
        summary="An optional CTO/PM/Dev/QA/Security/Ops operating model for teams that explicitly want an organization-style Hermes loop.",
        use_when="Use when an operator wants Hermes to manage a repository workflow with founder-facing status, issue triage, handoff, review, and release gates.",
        roles=(
            TeamRole(
                id="cto",
                title="CTO",
                role="Chief Technology Officer",
                purpose="Orchestrate the loop, choose owners, monitor status, and escalate decisions in plain language.",
                owns=("overall prioritization", "owner assignment", "status narration", "escalation policy"),
                not_owned=("coding directly by default", "silent merge approval", *_COMMON_NOT_OWNED),
                escalation=("business decision required", "two attempts fail", "security or production risk appears"),
            ),
            TeamRole(
                id="pm",
                title="PM",
                role="Product Manager",
                purpose="Turn issues and chat feedback into prioritized, testable tickets.",
                owns=("backlog triage", "ticket clarity", "priority scoring", "acceptance criteria"),
                not_owned=("implementation", "architecture decisions", "guessing unclear requirements", *_COMMON_NOT_OWNED),
                escalation=("requirement is vague", "priority conflicts", "design or product direction is missing"),
            ),
            TeamRole(
                id="dev",
                title="Dev",
                role="Software Developer",
                purpose="Own implementation only when an accepted handoff and selected executor path exist.",
                owns=("implementation scope", "local verification", "change summary", "handoff report"),
                not_owned=("unapproved scope changes", "product decisions", "merge approval", *_COMMON_NOT_OWNED),
                escalation=("scope changes", "tests cannot run", "implementation needs a product decision"),
            ),
            TeamRole(
                id="qa",
                title="QA",
                role="Quality Assurance",
                purpose="Validate behavior, record evidence, and keep failures visible.",
                owns=("test plan", "observed test result", "regression notes", "plain-language QA summary"),
                not_owned=("fix implementation", "review approval", *_COMMON_NOT_OWNED),
                escalation=("verification fails", "coverage is too thin", "status contradicts evidence"),
            ),
            TeamRole(
                id="security",
                title="Security",
                role="Security Reviewer",
                purpose="Check trust boundaries, secret exposure, dependency risk, and release blockers.",
                owns=("security findings", "secret-scan status", "dependency risk", "blocker recommendation"),
                not_owned=("business approval", "fix implementation", *_COMMON_NOT_OWNED),
                escalation=("secret or credential risk appears", "critical vulnerability is found", "threat model is unclear"),
            ),
            TeamRole(
                id="ops",
                title="Ops",
                role="Operations",
                purpose="Track deployment readiness, health checks, incidents, and rollback notes.",
                owns=("deployment checklist", "health status", "incident notes", "rollback recommendation"),
                not_owned=("claiming production health without checks", "shipping without approval", *_COMMON_NOT_OWNED),
                escalation=("health is unobserved or failing", "rollback may be needed", "operator credentials are required"),
            ),
        ),
    ),
)

_PACKS_BY_ID = {pack.id: pack for pack in TEAM_PROFILE_PACKS}


def list_team_profile_packs() -> dict[str, object]:
    return {
        "schema_version": "team_profile_catalog/v1",
        "default_install": "none",
        "claim_boundary": _CLAIM_BOUNDARY,
        "packs": [pack.to_dict() for pack in TEAM_PROFILE_PACKS],
    }


def inspect_team_profile_pack(pack_id: str) -> dict[str, object]:
    pack = _pack(pack_id)
    return {"schema_version": TEAM_PROFILE_SCHEMA_VERSION, "pack": pack.to_dict()}


def install_team_profile_pack(paths: OmhPaths, pack_id: str, *, force: bool = False, dry_run: bool = False) -> dict[str, object]:
    pack = _pack(pack_id)
    files = _pack_files(paths, pack)
    if dry_run:
        return _install_result(paths, pack, files, observed=False, dry_run=True, written=[])

    dirty = [str(path) for path, content in files if path.exists() and path.read_text(encoding="utf-8") != content]
    if dirty and not force:
        raise TeamProfileError("team profile files differ, refusing to overwrite without --force: " + ", ".join(dirty))

    for path, content in files:
        atomic_write_text(path, content)

    result = _install_result(paths, pack, files, observed=True, dry_run=False, written=[str(path) for path, _ in files])
    atomic_write_json(paths.team_profile_manifest_dir / f"{pack.id}.json", result, private=True)
    return result


def render_team_role_markdown(pack: TeamProfilePack, role: TeamRole) -> str:
    owns = "\n".join(f"- {item}" for item in role.owns)
    not_owned = "\n".join(f"- {item}" for item in role.not_owned)
    escalation = "\n".join(f"- {item}" for item in role.escalation)
    return (
        "---\n"
        f"name: OMHM {role.title}\n"
        f"role: {role.role}\n"
        f"pack: {pack.id}\n"
        f"schema_version: {TEAM_PROFILE_SCHEMA_VERSION}\n"
        "---\n\n"
        f"# OMHM {role.title}\n\n"
        "This is an optional Hermes agent/profile role file. It is installed only when an operator selects the "
        f"`{pack.id}` team profile pack.\n\n"
        "It describes responsibility and communication style. It is not proof that Hermes activated this profile, "
        "spawned an agent, executed code, reviewed a PR, passed CI, or merged anything.\n\n"
        "## Purpose\n\n"
        f"{role.purpose}\n\n"
        "## Owns\n\n"
        f"{owns}\n\n"
        "## Does Not Own\n\n"
        f"{not_owned}\n\n"
        "## Escalate When\n\n"
        f"{escalation}\n\n"
        "## Evidence Boundary\n\n"
        f"{_CLAIM_BOUNDARY}\n"
    )


def _pack(pack_id: str) -> TeamProfilePack:
    try:
        return _PACKS_BY_ID[pack_id]
    except KeyError as exc:
        valid = ", ".join(sorted(_PACKS_BY_ID))
        raise TeamProfileError(f"unknown team profile pack: {pack_id}; expected one of {valid}") from exc


def _pack_files(paths: OmhPaths, pack: TeamProfilePack) -> list[tuple[Path, str]]:
    return [
        (paths.hermes_agents_dir / f"omhm-{pack.id}-{role.id}.md", render_team_role_markdown(pack, role))
        for role in pack.roles
    ]


def _install_result(
    paths: OmhPaths,
    pack: TeamProfilePack,
    files: list[tuple[Path, str]],
    *,
    observed: bool,
    dry_run: bool,
    written: list[str],
) -> dict[str, object]:
    return {
        "schema_version": TEAM_PROFILE_SCHEMA_VERSION,
        "pack_id": pack.id,
        "title": pack.title,
        "dry_run": dry_run,
        "observed": observed,
        "installed_to": str(paths.hermes_agents_dir),
        "files": [str(path) for path, _ in files],
        "written": written,
        "roles": [role.id for role in pack.roles],
        "requires_hermes_profile_activation": True,
        "normal_user_surface": "Hermes Agent chat; team profiles are optional operating models",
        "claim_boundary": _CLAIM_BOUNDARY,
        "updated_at": utc_now(),
    }
