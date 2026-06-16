from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


USE_CASE_CATALOG_SCHEMA_VERSION = "omh_use_case_catalog/v1"
USE_CASE_RECOMMENDATION_SCHEMA_VERSION = "omh_use_case_recommendation/v1"
USE_CASE_VALIDATION_SCHEMA_VERSION = "omh_use_case_validation/v1"


@dataclass(frozen=True)
class UseCase:
    goal: str
    priority: int
    id: str
    title: str
    hermes_use_case: str
    current_gap: str
    primary_skill: str
    playbook: str
    harness: str
    feature_surface: str
    direct_skill_invocation: str
    hermes_chat_prompt: str
    next_action: str
    user_value: str
    evidence_boundary: str
    proof_surfaces: tuple[str, ...]
    keywords: tuple[str, ...]


USE_CASES: tuple[UseCase, ...] = (
    UseCase(
        goal="G1",
        priority=1,
        id="natural-automation-blueprint",
        title="Natural-language scheduled automation",
        hermes_use_case="Turn a plain recurring request into a Hermes cron/automation blueprint with delivery target and confirmation card.",
        current_gap="Loop had automation metadata, but the Hermes cron-ready blueprint surface was the only partially implemented member of this pack.",
        primary_skill="automation-blueprint",
        playbook="scheduled-ops-blueprint",
        harness="scheduled-ops-blueprint",
        feature_surface="automation-blueprint skill: schedule intent, skill list, delivery target, silence policy, and confirmation/status card.",
        direct_skill_invocation="$automation-blueprint Every morning, research competitor updates and send a digest only if something changed.",
        hermes_chat_prompt="Use OMH automation-blueprint for: Every morning, research competitor updates and send a digest only if something changed.",
        next_action="prepare_scheduled_ops_blueprint",
        user_value="Hermes can shape recurring work without pretending cron, source retrieval, or delivery already happened.",
        evidence_boundary="A scheduled ops blueprint is not host cron creation, Hermes automation enablement, gateway delivery, source retrieval, or no-agent execution evidence.",
        proof_surfaces=("omh ops blueprint", "omh playbook inspect scheduled-ops-blueprint", "omh harness inspect scheduled-ops-blueprint"),
        keywords=("cron", "automation", "every morning", "daily", "digest", "slack", "discord", "telegram", "매일", "정기", "자동화"),
    ),
    UseCase(
        goal="G2",
        priority=2,
        id="github-event-ops",
        title="GitHub PR/Issue event operations",
        hermes_use_case="Route PR opened, CI failed, issue opened, and review events into review, triage, labeling, or fix-handoff cards.",
        current_gap="OMH had handoff/status strength, but GitHub event recipes were not first-class.",
        primary_skill="github-event-ops",
        playbook="github-event-ops",
        harness="github-event-ops",
        feature_surface="github-event-ops skill: PR/issue/CI event classification with label/review/fix-handoff actions.",
        direct_skill_invocation="$github-event-ops PR opened with failing CI; decide whether to review, label, or prepare a fix handoff.",
        hermes_chat_prompt="Use OMH github-event-ops for: PR opened with failing CI; decide whether to review, label, or prepare a fix handoff.",
        next_action="prepare_github_event_ops_card",
        user_value="Maintainers can paste or receive GitHub events and get a safe next action without claiming a bot mutated GitHub.",
        evidence_boundary="A GitHub event ops card is not webhook delivery, GitHub API mutation, label application, review completion, CI rerun, or fix execution evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect github-event-ops", "omh harness inspect github-event-ops"),
        keywords=("github", "webhook", "pr opened", "ci failed", "issue opened", "label", "review", "깃허브", "이슈", "ci"),
    ),
    UseCase(
        goal="G3",
        priority=3,
        id="agent-board",
        title="Multi-agent Kanban board",
        hermes_use_case="Let multiple Hermes profiles or agents collaborate through task, handoff, heartbeat, blocker, and completion states.",
        current_gap="OMH had target topology and team profiles, but not a Hermes board contract.",
        primary_skill="agent-board",
        playbook="agent-board",
        harness="agent-board",
        feature_surface="agent-board contract: task/handoff/heartbeat/block/complete cards connected to OMH status.",
        direct_skill_invocation="$agent-board Coordinate CTO, PM, QA, and release agents on this launch checklist.",
        hermes_chat_prompt="Use OMH agent-board for: Coordinate CTO, PM, QA, and release agents on this launch checklist.",
        next_action="prepare_agent_board_card",
        user_value="Teams see who owns each lane and which states are only prepared versus observed.",
        evidence_boundary="An agent board card is not proof that another Hermes target accepted, worked, heartbeat-ed, or completed unless target-specific evidence exists.",
        proof_surfaces=("omh recommend", "omh playbook inspect agent-board", "omh harness inspect agent-board"),
        keywords=("agent board", "kanban", "multi agent", "heartbeat", "blocker", "handoff", "profile", "칸반", "여러 에이전트"),
    ),
    UseCase(
        goal="G4",
        priority=4,
        id="memory-curation-review",
        title="Memory and skill curation review",
        hermes_use_case="Review stale memories, conflicting facts, and duplicate skills with approve/reject/update actions.",
        current_gap="OMH had memory inspect, but not a deep Hermes MEMORY.md/USER.md/curator flow.",
        primary_skill="memory-curation-review",
        playbook="memory-curation-review",
        harness="memory-curation-review",
        feature_surface="memory-curation-review skill: candidate cleanup list, conflict detection, and human approval gates.",
        direct_skill_invocation="$memory-curation-review Inspect stale project memories and ask me what to keep.",
        hermes_chat_prompt="Use OMH memory-curation-review for: Inspect stale project memories and ask me what to keep.",
        next_action="prepare_memory_curation_review",
        user_value="Users can clean memory and skill drift without a silent destructive edit.",
        evidence_boundary="A memory curation review is not Hermes internal memory, MEMORY.md, USER.md, or skill-file modification evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect memory-curation-review", "omh harness inspect memory-curation-review"),
        keywords=("memory", "curation", "stale", "conflict", "duplicate", "MEMORY.md", "USER.md", "기억", "메모리", "중복"),
    ),
    UseCase(
        goal="G5",
        priority=5,
        id="gateway-intent-card",
        title="Gateway-native intent card",
        hermes_use_case="Normalize Discord, Slack, Telegram, and other gateway sessions into origin/thread/delivery/silent/attachment/status-update policy.",
        current_gap="OMH had wrapper contracts, but gateway-native target and delivery models were shallow.",
        primary_skill="gateway-intent-card",
        playbook="gateway-intent-card",
        harness="gateway-intent-card",
        feature_surface="gateway-intent-card skill: origin, thread, delivery, silence, attachment, and status-update policy.",
        direct_skill_invocation="$gateway-intent-card Route this Discord thread update silently unless action is needed.",
        hermes_chat_prompt="Use OMH gateway-intent-card for: Route this Discord thread update silently unless action is needed.",
        next_action="prepare_gateway_intent_card",
        user_value="Gateway builders get a platform-neutral card Hermes can use without hardcoding a bot SDK into OMH.",
        evidence_boundary="A gateway intent card is not platform login, message send, thread mutation, attachment upload, or delivery evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect gateway-intent-card", "omh harness inspect gateway-intent-card"),
        keywords=("gateway", "discord", "slack", "telegram", "thread", "delivery", "attachment", "silent", "게이트웨이", "디스코드", "슬랙"),
    ),
    UseCase(
        goal="G6",
        priority=6,
        id="executor-runtime-readiness",
        title="Executor runtime readiness",
        hermes_use_case="Show whether Codex, Claude Code, Hermes coding, or an oh-my runtime has the tools, credentials, and handoff mode needed.",
        current_gap="OMH had executor-neutral handoff, but runtime migration readiness was weak.",
        primary_skill="executor-runtime-readiness",
        playbook="executor-runtime-readiness",
        harness="executor-runtime-readiness",
        feature_surface="executor-runtime-readiness skill: runtime matrix, missing tools, and handoff mode.",
        direct_skill_invocation="$executor-runtime-readiness Can this task run in Codex, Claude Code, or Hermes coding?",
        hermes_chat_prompt="Use OMH executor-runtime-readiness for: Can this task run in Codex, Claude Code, or Hermes coding?",
        next_action="prepare_executor_runtime_readiness",
        user_value="Users can choose Codex, Claude Code, Hermes, or plugin runtimes without guessing hidden capabilities.",
        evidence_boundary="Runtime readiness is not executor dispatch, plugin load, tool invocation, code execution, review, CI, or merge evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect executor-runtime-readiness", "omh harness inspect executor-runtime-readiness"),
        keywords=("codex", "claude code", "runtime", "executor", "missing tools", "handoff mode", "omx", "omc", "omo", "코덱스", "클로드"),
    ),
    UseCase(
        goal="G7",
        priority=7,
        id="deliverable-package",
        title="Deliverable file package",
        hermes_use_case="Track PPT, PDF, XLSX, DOCX, HWP, Markdown, and attachments through prepared/generated/QA/attached states.",
        current_gap="OMH had materials-package, but not a Hermes deliverable attachment UX lane.",
        primary_skill="deliverable-package",
        playbook="deliverable-package",
        harness="deliverable-package",
        feature_surface="deliverable-package skill: file deliverable plan and prepared/generated/attached status card.",
        direct_skill_invocation="$deliverable-package Turn this research into PPT and PDF with attachment status.",
        hermes_chat_prompt="Use OMH deliverable-package for: Turn this research into PPT and PDF with attachment status.",
        next_action="prepare_deliverable_package",
        user_value="Users can ask for files in chat and see exactly whether they are planned, generated, QAed, approved, or attached.",
        evidence_boundary="A deliverable package card is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect deliverable-package", "omh harness inspect deliverable-package"),
        keywords=("deliverable", "file", "attachment", "ppt", "pdf", "xlsx", "docx", "hwp", "keynote", "자료", "첨부", "파일"),
    ),
    UseCase(
        goal="G8",
        priority=8,
        id="voice-operator",
        title="Voice and mobile operator",
        hermes_use_case="Convert terse voice/mobile commands into clarify, plan, status, handoff, or confirmation actions.",
        current_gap="OMH had setup language UX, but no voice-first workflow guidance.",
        primary_skill="voice-operator",
        playbook="voice-operator",
        harness="voice-operator",
        feature_surface="voice-operator skill: short command normalization, ambiguity check, and safe confirmation card.",
        direct_skill_invocation="$voice-operator 'release before lunch, check risky parts' from mobile.",
        hermes_chat_prompt="Use OMH voice-operator for: 'release before lunch, check risky parts' from mobile.",
        next_action="prepare_voice_operator_card",
        user_value="Voice and mobile users get concise, safe routing instead of long CLI-like responses.",
        evidence_boundary="A voice operator card is not speech recognition proof, mobile notification delivery, platform action, or accepted execution evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect voice-operator", "omh harness inspect voice-operator"),
        keywords=("voice", "mobile", "accessibility", "short command", "spoken", "hands free", "음성", "모바일", "접근성"),
    ),
    UseCase(
        goal="G9",
        priority=9,
        id="toolbelt-readiness",
        title="MCP and external toolbelt readiness",
        hermes_use_case="Check which MCP servers, CLIs, APIs, credentials, and connectors a workflow needs before claiming it can run.",
        current_gap="OMH setup had MCP preference, but workflow-specific MCP/tool recommendation and verification was weak.",
        primary_skill="toolbelt-readiness",
        playbook="toolbelt-readiness",
        harness="toolbelt-readiness",
        feature_surface="toolbelt-readiness skill: workflow tool requirements, installed/missing/credential matrix, and next setup action.",
        direct_skill_invocation="$toolbelt-readiness What MCP or CLI tools do I need for weekly Linear and GitHub triage?",
        hermes_chat_prompt="Use OMH toolbelt-readiness for: What MCP or CLI tools do I need for weekly Linear and GitHub triage?",
        next_action="prepare_toolbelt_readiness",
        user_value="Users see missing MCP/CLI/API pieces before an automation or handoff overclaims readiness.",
        evidence_boundary="A toolbelt readiness card is not MCP server installation, credential validation, API access, connector invocation, or successful workflow execution evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect toolbelt-readiness", "omh harness inspect toolbelt-readiness"),
        keywords=("mcp", "toolbelt", "tools", "connector", "credential", "cli", "api", "missing tool", "커넥터", "외부 도구"),
    ),
    UseCase(
        goal="G10",
        priority=10,
        id="ops-observability-card",
        title="Ops observability and cost card",
        hermes_use_case="Keep automation and loop work from failing silently by showing token/cost/latency/run-history/failure-mode telemetry boundaries.",
        current_gap="OMH evidence boundaries were strong, but runtime cost/latency telemetry contract was weak.",
        primary_skill="ops-observability-card",
        playbook="ops-observability-card",
        harness="ops-observability-card",
        feature_surface="ops-observability-card skill: wrapper-safe token, cost, latency, run history, queue, and failure-mode status card.",
        direct_skill_invocation="$ops-observability-card Show token, cost, latency, and last run status for this loop.",
        hermes_chat_prompt="Use OMH ops-observability-card for: Show token, cost, latency, and last run status for this loop.",
        next_action="prepare_ops_observability_card",
        user_value="Operators can see health/cost signals without confusing estimates with provider truth or completion evidence.",
        evidence_boundary="An ops observability card is not billing truth, provider quota truth, complete tracing, performance proof, or workflow completion evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect ops-observability-card", "omh harness inspect ops-observability-card"),
        keywords=("observability", "cost", "latency", "token", "run history", "telemetry", "failure mode", "비용", "토큰", "관측성"),
    ),
)


def list_use_cases() -> dict[str, Any]:
    return {
        "schema_version": USE_CASE_CATALOG_SCHEMA_VERSION,
        "count": len(USE_CASES),
        "use_cases": [_public_case(case) for case in USE_CASES],
    }


def inspect_use_case(case_id: str) -> dict[str, Any]:
    case = _find_case(case_id)
    if case is None:
        raise KeyError(case_id)
    return {
        "schema_version": USE_CASE_CATALOG_SCHEMA_VERSION,
        "use_case": _public_case(case),
    }


def recommend_use_cases(query: str, *, limit: int = 3) -> dict[str, Any]:
    clean_query = " ".join(query.split())
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if not clean_query:
        raise ValueError("task description must not be empty")
    tokens = _tokens(clean_query)
    scored: list[tuple[int, int, UseCase]] = []
    for case in USE_CASES:
        score = _score_case(case, tokens, clean_query)
        if score:
            scored.append((score, case.priority, case))
    if not scored:
        scored = [(1, case.priority, case) for case in (USE_CASES[4], USE_CASES[5], USE_CASES[8])]
    scored.sort(key=lambda item: (-item[0], item[1]))
    recommendations = []
    for score, _, case in scored[:limit]:
        payload = _public_case(case)
        payload["score"] = score
        payload["confidence"] = _confidence(score)
        recommendations.append(payload)
    return {
        "schema_version": USE_CASE_RECOMMENDATION_SCHEMA_VERSION,
        "query": clean_query,
        "recommendations": recommendations,
        "boundary": "Use-case recommendations prove only routing/product-fit guidance; they are not runtime, connector, delivery, file, memory, or execution evidence.",
    }


def validate_use_cases() -> dict[str, Any]:
    from .playbooks import list_playbooks
    from .skill_pack import builtin_harnesses, builtin_skill_templates

    skill_names = {skill.name for skill in builtin_skill_templates()}
    harness_names = {harness.name for harness in builtin_harnesses()}
    playbook_ids = {str(playbook["id"]) for playbook in list_playbooks()["playbooks"]}
    validations = []
    errors = []
    for case in USE_CASES:
        checks = {
            "skill_exists": case.primary_skill in skill_names,
            "playbook_exists": case.playbook in playbook_ids,
            "harness_exists": case.harness in harness_names,
            "direct_skill_invocation_present": case.direct_skill_invocation.startswith(f"${case.primary_skill} "),
            "hermes_chat_prompt_present": case.primary_skill in case.hermes_chat_prompt,
            "feature_surface_present": case.primary_skill in case.feature_surface,
            "proof_surfaces_present": len(case.proof_surfaces) >= 3,
            "proof_surfaces_valid": all(
                _proof_surface_supported(surface, playbook_ids=playbook_ids, harness_names=harness_names)
                for surface in case.proof_surfaces
            ),
            "boundary_has_evidence_guard": _boundary_has_evidence_guard(case.evidence_boundary),
            "next_action_present": bool(case.next_action.strip()),
            "user_value_present": bool(case.user_value.strip()),
        }
        missing = [name for name, ok in checks.items() if not ok]
        if missing:
            errors.append({"goal": case.goal, "id": case.id, "missing": missing})
        validations.append(
            {
                "goal": case.goal,
                "priority": case.priority,
                "id": case.id,
                "title": case.title,
                "primary_skill": case.primary_skill,
                "playbook": case.playbook,
                "harness": case.harness,
                "feature_surface": case.feature_surface,
                "direct_skill_invocation": case.direct_skill_invocation,
                "hermes_chat_prompt": case.hermes_chat_prompt,
                "proof_surfaces": list(case.proof_surfaces),
                "evidence_boundary": case.evidence_boundary,
                "checks": checks,
                "ok": not missing,
            }
        )
    return {
        "schema_version": USE_CASE_VALIDATION_SCHEMA_VERSION,
        "ok": not errors,
        "count": len(USE_CASES),
        "validated": validations,
        "errors": errors,
        "boundary": "Validation proves the 10 OMH feature surfaces are registered as skills, playbooks, harnesses, and invocation examples; it is not proof that any external runtime action happened.",
    }


def _proof_surface_supported(surface: str, *, playbook_ids: set[str], harness_names: set[str]) -> bool:
    clean = " ".join(surface.split())
    if clean in {"omh recommend", "omh ops blueprint"}:
        return True
    if clean.startswith("omh playbook inspect "):
        return clean.removeprefix("omh playbook inspect ") in playbook_ids
    if clean.startswith("omh harness inspect "):
        return clean.removeprefix("omh harness inspect ") in harness_names
    if clean.startswith("omh cases inspect "):
        return _find_case(clean.removeprefix("omh cases inspect ")) is not None
    return False


def _boundary_has_evidence_guard(boundary: str) -> bool:
    lowered = boundary.casefold()
    return "not " in lowered and "evidence" in lowered


def _public_case(case: UseCase) -> dict[str, Any]:
    payload = asdict(case)
    payload["proof_surfaces"] = list(case.proof_surfaces)
    payload["keywords"] = list(case.keywords)
    return payload


def _find_case(case_id: str) -> UseCase | None:
    normalized = case_id.strip().casefold()
    for case in USE_CASES:
        if normalized in {case.goal.casefold(), case.id.casefold(), f"{case.goal}-{case.id}".casefold()}:
            return case
    return None


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9가-힣_+-]+", value)}


def _score_case(case: UseCase, tokens: set[str], query: str) -> int:
    lowered = query.casefold()
    score = 0
    for keyword in case.keywords:
        key = keyword.casefold()
        if " " in key:
            if key in lowered:
                score += 3
        elif key in tokens:
            score += 2
        elif key and key in lowered:
            score += 1
    if case.primary_skill.casefold() in lowered or case.playbook.casefold() in lowered:
        score += 4
    return score


def _confidence(score: int) -> str:
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"
