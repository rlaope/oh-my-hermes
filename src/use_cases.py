from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from .paths import OmhPaths


USE_CASE_CATALOG_SCHEMA_VERSION = "omh_use_case_catalog/v1"
USE_CASE_DEMO_CARD_SCHEMA_VERSION = "omh_use_case_demo_card/v1"
USE_CASE_DEMO_COLLECTION_SCHEMA_VERSION = "omh_use_case_demo_collection/v1"
USE_CASE_RECOMMENDATION_SCHEMA_VERSION = "omh_use_case_recommendation/v1"
USE_CASE_VALIDATION_SCHEMA_VERSION = "omh_use_case_validation/v1"
USE_CASE_ARTIFACT_SCHEMA_VERSION = "omh_use_case_artifact/v1"
USE_CASE_ARTIFACT_COLLECTION_SCHEMA_VERSION = "omh_use_case_artifact_collection/v1"
USE_CASE_ARTIFACT_WRITE_SCHEMA_VERSION = "omh_use_case_artifact_write/v1"
USE_CASE_ARTIFACT_INDEX_SCHEMA_VERSION = "omh_use_case_artifact_index/v1"
USE_CASE_REPLAY_SCHEMA_VERSION = "omh_use_case_replay/v1"
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,159}$")


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


@dataclass(frozen=True)
class UseCaseReplayFixture:
    fixture_id: str
    goal: str
    locale: str
    message: str


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
        feature_surface="github-event-ops router surface: PR/issue/CI event classification with label/review/fix-handoff actions.",
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
        feature_surface="agent-board agent context: task/handoff/heartbeat/block/complete cards connected to OMH status.",
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
        feature_surface="gateway-intent-card router surface: origin, thread, delivery, silence, attachment, and status-update policy.",
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
        feature_surface="executor-runtime-readiness harness surface: runtime matrix, missing tools, and handoff mode.",
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
        feature_surface="voice-operator agent context: short command normalization, ambiguity check, and safe confirmation card.",
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
        feature_surface="toolbelt-readiness harness surface: workflow tool requirements, installed/missing/credential matrix, and next setup action.",
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
        feature_surface="ops-observability-card harness surface: wrapper-safe token, cost, latency, run history, queue, and failure-mode status card.",
        direct_skill_invocation="$ops-observability-card Show token, cost, latency, and last run status for this loop.",
        hermes_chat_prompt="Use OMH ops-observability-card for: Show token, cost, latency, and last run status for this loop.",
        next_action="prepare_ops_observability_card",
        user_value="Operators can see health/cost signals without confusing estimates with provider truth or completion evidence.",
        evidence_boundary="An ops observability card is not billing truth, provider quota truth, complete tracing, performance proof, or workflow completion evidence.",
        proof_surfaces=("omh recommend", "omh playbook inspect ops-observability-card", "omh harness inspect ops-observability-card"),
        keywords=("observability", "cost", "latency", "token", "run history", "telemetry", "failure mode", "비용", "토큰", "관측성"),
    ),
)


USE_CASE_REPLAY_FIXTURES: tuple[UseCaseReplayFixture, ...] = (
    UseCaseReplayFixture("g1-daily-digest-en", "G1", "en", "Every morning send a competitor digest to Slack only if changed."),
    UseCaseReplayFixture("g1-automation-ko", "G1", "ko", "매일 아침 경쟁사 뉴스를 Slack으로 보내줘."),
    UseCaseReplayFixture("g2-ci-review-en", "G2", "en", "PR opened with failing CI and needs review label or fix handoff."),
    UseCaseReplayFixture("g2-github-ko", "G2", "ko", "깃허브 PR CI failed 리뷰 라벨링이 필요해."),
    UseCaseReplayFixture("g3-board-en", "G3", "en", "Coordinate multiple Hermes profiles on a Kanban board with blockers."),
    UseCaseReplayFixture("g3-agent-ko", "G3", "ko", "여러 에이전트 칸반 blocker heartbeat 상태를 정리해줘."),
    UseCaseReplayFixture("g4-memory-en", "G4", "en", "Review stale MEMORY.md facts and duplicate skills before cleanup."),
    UseCaseReplayFixture("g4-memory-ko", "G4", "ko", "기억 메모리 중복 충돌 정리할 후보를 보여줘."),
    UseCaseReplayFixture("g5-gateway-en", "G5", "en", "Discord gateway thread should send silent attachment status updates."),
    UseCaseReplayFixture("g5-discord-ko", "G5", "ko", "디스코드 스레드 첨부 상태 업데이트 정책을 잡아줘."),
    UseCaseReplayFixture("g6-runtime-en", "G6", "en", "Can this run in Codex Claude Code or Hermes coding with missing tools?"),
    UseCaseReplayFixture("g6-coding-ko", "G6", "ko", "코덱스 클로드 hermes coding missing tools runtime 확인해줘."),
    UseCaseReplayFixture("g7-deliverable-en", "G7", "en", "Prepare a PPT PDF XLSX deliverable and show attachment status."),
    UseCaseReplayFixture("g7-materials-ko", "G7", "ko", "PPT PDF XLSX 자료 첨부 상태를 패키지로 준비해줘."),
    UseCaseReplayFixture("g8-voice-en", "G8", "en", "Voice mobile request release before lunch check risky parts."),
    UseCaseReplayFixture("g8-mobile-ko", "G8", "ko", "음성 모바일로 release before lunch 위험한 부분 확인해."),
    UseCaseReplayFixture("g9-toolbelt-en", "G9", "en", "Which MCP CLI API credentials are needed for Linear GitHub triage?"),
    UseCaseReplayFixture("g9-mcp-ko", "G9", "ko", "MCP CLI API credential connector missing tool 점검해줘."),
    UseCaseReplayFixture("g10-observability-en", "G10", "en", "Show token cost latency run history and loop failure modes."),
    UseCaseReplayFixture("g10-cost-ko", "G10", "ko", "토큰 비용 latency run history failure mode를 보여줘."),
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


def demo_use_case(case_id: str) -> dict[str, Any]:
    case = _find_case(case_id)
    if case is None:
        raise KeyError(case_id)
    return _demo_card(case)


def demo_all_use_cases() -> dict[str, Any]:
    return {
        "schema_version": USE_CASE_DEMO_COLLECTION_SCHEMA_VERSION,
        "count": len(USE_CASES),
        "cards": [_demo_card(case) for case in USE_CASES],
        "boundary": (
            "Use-case demo cards are wrapper rendering artifacts. They prove OMH "
            "can shape a Hermes-facing card for the scenario; they are not runtime, "
            "connector, delivery, file, memory, or execution evidence."
        ),
    }


def build_use_case_artifact(case_id: str) -> dict[str, Any]:
    case = _find_case(case_id)
    if case is None:
        raise KeyError(case_id)
    card = _demo_card(case)
    artifact = {
        "schema_version": USE_CASE_ARTIFACT_SCHEMA_VERSION,
        "artifact_id": _artifact_id(case),
        "goal": case.goal,
        "id": case.id,
        "title": case.title,
        "status": "prepared",
        "observation_status": "prepared_not_observed",
        "source": "omh_use_case_catalog",
        "summary": case.user_value,
        "route": card["route"],
        "chat_surface": card["chat_surface"],
        "wrapper_card": card["wrapper_card"],
        "workflow_contract": {
            "primary_skill": case.primary_skill,
            "playbook": case.playbook,
            "harness": case.harness,
            "next_action": case.next_action,
            "direct_skill_invocation": case.direct_skill_invocation,
            "hermes_chat_prompt": case.hermes_chat_prompt,
        },
        "operator_steps": _artifact_operator_steps(case),
        "proof_surfaces": [
            *case.proof_surfaces,
            f"omh cases demo {case.goal} --json",
            f"omh cases artifact {case.goal} --json",
            "omh cases validate --json",
        ],
        "evidence": {
            "state": "prepared_not_observed",
            "claim_boundary": case.evidence_boundary,
            "not_evidence_until_observed": card["evidence"]["not_evidence_until_observed"],
            "observed_evidence_required": [
                "wrapper or Hermes record that the user accepted this case route",
                "runtime, connector, file, memory, executor, review, CI, merge, or delivery record matching the claimed action",
                "human approval record before treating suggested skill, memory, or workflow changes as applied",
            ],
        },
        "release_quality": {
            "fixture_safe": True,
            "contains_raw_user_prompt": False,
            "eligible_for_release_smoke": True,
            "recommended_gate": "omh cases artifact --all --json",
        },
        "boundary": (
            "Use-case artifacts are prepared runbook metadata for Hermes and wrapper tests. "
            "They are not observed runtime execution, connector, delivery, file, memory, executor, review, CI, merge, or billing evidence."
        ),
    }
    errors = validate_use_case_artifact(artifact)
    if errors:
        raise ValueError("; ".join(errors))
    return artifact


def build_all_use_case_artifacts() -> dict[str, Any]:
    return {
        "schema_version": USE_CASE_ARTIFACT_COLLECTION_SCHEMA_VERSION,
        "count": len(USE_CASES),
        "artifacts": [build_use_case_artifact(case.goal) for case in USE_CASES],
        "boundary": (
            "This collection is a prepared application-case artifact bundle. "
            "It proves catalog-to-artifact projection only, not runtime execution."
        ),
    }


def write_use_case_artifact(paths: OmhPaths, artifact: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    errors = validate_use_case_artifact(artifact)
    if errors:
        raise ValueError("; ".join(errors))
    artifact_id = str(artifact["artifact_id"])
    path = _use_case_artifact_path(paths, artifact_id)
    existed = path.exists()
    if existed and not force:
        raise ValueError(f"use-case artifact already exists: {artifact_id}; pass --force to replace it")
    atomic_write_json(path, artifact, private=True)
    _write_use_case_artifact_index(paths)
    return {
        "schema_version": USE_CASE_ARTIFACT_WRITE_SCHEMA_VERSION,
        "ok": True,
        "mode": "write",
        "artifact": artifact,
        "artifact_path": str(path),
        "index_path": str(paths.use_case_artifacts_index_path),
        "replaced": existed and force,
        "boundary": artifact["boundary"],
    }


def write_all_use_case_artifacts(paths: OmhPaths, *, force: bool = False) -> dict[str, Any]:
    written = []
    for artifact in build_all_use_case_artifacts()["artifacts"]:
        if not isinstance(artifact, dict):
            continue
        written.append(write_use_case_artifact(paths, artifact, force=force))
    return {
        "schema_version": USE_CASE_ARTIFACT_WRITE_SCHEMA_VERSION,
        "ok": True,
        "mode": "write_all",
        "count": len(written),
        "artifacts": [
            {
                "artifact_id": item["artifact"]["artifact_id"],
                "goal": item["artifact"]["goal"],
                "title": item["artifact"]["title"],
                "artifact_path": item["artifact_path"],
                "replaced": item["replaced"],
            }
            for item in written
        ],
        "index_path": str(paths.use_case_artifacts_index_path),
        "boundary": (
            "Writing all use-case artifacts records prepared metadata only. "
            "It is not evidence that any runtime, connector, delivery, file, memory, executor, review, CI, or merge action happened."
        ),
    }


def list_use_case_artifacts(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for artifact_path in sorted(paths.use_case_artifacts_dir.glob("*.json")):
        record, error = read_json_object_result(artifact_path)
        if error or not record:
            continue
        records.append(record)
    records.sort(key=lambda item: str(item.get("goal", "")))
    if limit is not None:
        if limit < 1:
            return []
        records = records[-limit:]
    return records


def show_use_case_artifact(paths: OmhPaths, artifact_id: str) -> dict[str, Any]:
    if not _valid_artifact_id(artifact_id):
        raise FileNotFoundError(artifact_id)
    record = read_json_object(_use_case_artifact_path(paths, artifact_id))
    if record is None:
        raise FileNotFoundError(artifact_id)
    return record


def validate_use_case_artifact(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != USE_CASE_ARTIFACT_SCHEMA_VERSION:
        errors.append("schema_version must be omh_use_case_artifact/v1")
    artifact_id = str(record.get("artifact_id", ""))
    if not artifact_id:
        errors.append("artifact_id is required")
    elif not _valid_artifact_id(artifact_id):
        errors.append("artifact_id must contain only letters, digits, and hyphens, and must not contain path separators")
    goal = str(record.get("goal", ""))
    case = _find_case(goal)
    if case is None:
        errors.append("goal must reference a known G1-G10 use case")
    elif artifact_id != _artifact_id(case):
        errors.append("artifact_id must match the canonical use-case artifact id")
    if record.get("status") != "prepared":
        errors.append("status must be prepared")
    if record.get("observation_status") != "prepared_not_observed":
        errors.append("observation_status must be prepared_not_observed")
    for key in ("route", "chat_surface", "wrapper_card", "workflow_contract", "evidence", "release_quality"):
        if not isinstance(record.get(key), dict):
            errors.append(f"{key} must be an object")
    for key in ("operator_steps", "proof_surfaces"):
        if not isinstance(record.get(key), list) or not record.get(key):
            errors.append(f"{key} must be a non-empty list")
    route = record.get("route") if isinstance(record.get("route"), dict) else {}
    workflow = record.get("workflow_contract") if isinstance(record.get("workflow_contract"), dict) else {}
    wrapper = record.get("wrapper_card") if isinstance(record.get("wrapper_card"), dict) else {}
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    if case is not None:
        if route.get("primary_skill") != case.primary_skill:
            errors.append("route.primary_skill must match use-case primary skill")
        if route.get("next_action") != case.next_action:
            errors.append("route.next_action must match use-case next action")
        if workflow.get("hermes_chat_prompt") != case.hermes_chat_prompt:
            errors.append("workflow_contract.hermes_chat_prompt must match catalog prompt")
    if wrapper.get("component") != "omh_use_case_card":
        errors.append("wrapper_card.component must be omh_use_case_card")
    if wrapper.get("status") != "prepared_not_observed":
        errors.append("wrapper_card.status must be prepared_not_observed")
    if evidence.get("state") != "prepared_not_observed":
        errors.append("evidence.state must be prepared_not_observed")
    boundary = str(evidence.get("claim_boundary", ""))
    if "not " not in boundary.casefold() or "evidence" not in boundary.casefold():
        errors.append("evidence.claim_boundary must preserve a not-evidence guard")
    if not isinstance(evidence.get("not_evidence_until_observed"), list) or "executor_dispatch" not in evidence.get("not_evidence_until_observed", []):
        errors.append("evidence.not_evidence_until_observed must include executor_dispatch")
    release_quality = record.get("release_quality") if isinstance(record.get("release_quality"), dict) else {}
    if release_quality.get("contains_raw_user_prompt") is not False:
        errors.append("release_quality.contains_raw_user_prompt must be false")
    return errors


def validate_use_case_artifact_store(paths: OmhPaths) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for artifact_path in sorted(paths.use_case_artifacts_dir.glob("*.json")):
        record, error = read_json_object_result(artifact_path)
        if error:
            errors.append(f"{artifact_path}: {error}")
            continue
        if not record:
            continue
        records.append(record)
        artifact_id = str(record.get("artifact_id", ""))
        if artifact_id in seen:
            errors.append(f"duplicate artifact_id: {artifact_id}")
        seen.add(artifact_id)
        for item_error in validate_use_case_artifact(record):
            errors.append(f"{artifact_id or '<unknown>'}: {item_error}")
    missing_goals = sorted({case.goal for case in USE_CASES} - {str(record.get("goal", "")) for record in records})
    index = read_json_object(paths.use_case_artifacts_index_path)
    if index and index.get("schema_version") != USE_CASE_ARTIFACT_INDEX_SCHEMA_VERSION:
        errors.append("use-case artifact index cache has unsupported schema_version")
    return {
        "schema_version": "omh_use_case_artifact_validation/v1",
        "ok": not errors,
        "artifact_count": len(records),
        "expected_count": len(USE_CASES),
        "missing_goals": missing_goals,
        "errors": errors,
        "index_authority": "cache_only",
        "boundary": "Validation proves local prepared artifact shape only, not runtime execution.",
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


def replay_use_case_fixtures(*, limit: int | None = None) -> dict[str, Any]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    fixtures = list(USE_CASE_REPLAY_FIXTURES)
    if limit is not None:
        fixtures = fixtures[:limit]
    results = []
    for fixture in fixtures:
        case = _find_case(fixture.goal)
        if case is None:
            results.append(
                {
                    "fixture_id": fixture.fixture_id,
                    "goal": fixture.goal,
                    "locale": fixture.locale,
                    "status": "failed",
                    "message": fixture.message,
                    "expected": {"goal": fixture.goal, "primary_skill": ""},
                    "observed": {"goal": "", "primary_skill": "", "score": 0, "confidence": "none"},
                    "errors": ["fixture goal is not registered in USE_CASES"],
                }
            )
            continue
        recommendation = recommend_use_cases(fixture.message, limit=1)["recommendations"][0]
        observed_goal = str(recommendation.get("goal", ""))
        observed_skill = str(recommendation.get("primary_skill", ""))
        errors = []
        if observed_goal != case.goal:
            errors.append(f"expected goal {case.goal}, observed {observed_goal or '<none>'}")
        if observed_skill != case.primary_skill:
            errors.append(f"expected primary_skill {case.primary_skill}, observed {observed_skill or '<none>'}")
        results.append(
            {
                "fixture_id": fixture.fixture_id,
                "goal": fixture.goal,
                "locale": fixture.locale,
                "message": fixture.message,
                "status": "failed" if errors else "passed",
                "expected": {
                    "goal": case.goal,
                    "primary_skill": case.primary_skill,
                    "next_action": case.next_action,
                },
                "observed": {
                    "goal": observed_goal,
                    "primary_skill": observed_skill,
                    "score": recommendation.get("score", 0),
                    "confidence": recommendation.get("confidence", ""),
                    "next_action": recommendation.get("next_action", ""),
                },
                "errors": errors,
            }
        )
    failed = [result for result in results if result.get("status") != "passed"]
    replayed_goals = {str(result.get("goal", "")) for result in results}
    covered_goals = [case.goal for case in USE_CASES if case.goal in replayed_goals]
    return {
        "schema_version": USE_CASE_REPLAY_SCHEMA_VERSION,
        "status": "passed" if not failed else "failed",
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "expected_total": len(USE_CASE_REPLAY_FIXTURES),
        "expected_goals": [case.goal for case in USE_CASES],
        "covered_goals": covered_goals,
        "results": results,
        "boundary": (
            "Use-case replay checks deterministic recommendation routing for synthetic operator fixtures only. "
            "It does not execute workflows, call connectors, create files, mutate memory, dispatch executors, review code, run CI, merge, deliver messages, or prove live Hermes chat behavior."
        ),
    }


def validate_use_cases() -> dict[str, Any]:
    from .playbooks import list_playbooks
    from .skill_pack import (
        builtin_harnesses,
        installable_skill_definitions,
        routable_definitions,
        skill_exposure_payload,
    )

    routable_names = {skill.name for skill in routable_definitions()}
    installable_names = {skill.name for skill in installable_skill_definitions()}
    harness_names = {harness.name for harness in builtin_harnesses()}
    playbook_ids = {str(playbook["id"]) for playbook in list_playbooks()["playbooks"]}
    validations = []
    errors = []
    for case in USE_CASES:
        exposure = skill_exposure_payload(case.primary_skill)
        install_visibility = bool(exposure["install_visibility"])
        checks = {
            "skill_exists": case.primary_skill in routable_names,
            "surface_routable": case.primary_skill in routable_names,
            "exposure_valid": exposure["exposure"]
            in {"direct_skill", "workflow_skill", "router_only", "harness_only", "agent_context"},
            "install_visibility_matches": (case.primary_skill in installable_names) == install_visibility,
            "installed_skill_visible": (case.primary_skill in installable_names)
            if install_visibility
            else case.primary_skill not in installable_names,
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
                **exposure,
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
        "boundary": "Validation proves the 10 OMH feature surfaces are routable and registered with the right exposure, playbook, harness, and invocation metadata; it is not proof that any external runtime action happened.",
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
    from .skill_pack import skill_exposure_payload

    payload = asdict(case)
    payload.update(skill_exposure_payload(case.primary_skill))
    payload["proof_surfaces"] = list(case.proof_surfaces)
    payload["keywords"] = list(case.keywords)
    return payload


def _demo_card(case: UseCase) -> dict[str, Any]:
    exposure = _public_case(case)
    return {
        "schema_version": USE_CASE_DEMO_CARD_SCHEMA_VERSION,
        "goal": case.goal,
        "id": case.id,
        "title": case.title,
        "route": {
            "primary_skill": case.primary_skill,
            "playbook": case.playbook,
            "harness": case.harness,
            "exposure": exposure["exposure"],
            "install_visibility": exposure["install_visibility"],
            "compatibility_alias": exposure["compatibility_alias"],
            "next_action": case.next_action,
        },
        "chat_surface": {
            "source": "hermes_agent_chat",
            "suggested_user_prompt": case.hermes_chat_prompt,
            "direct_skill_invocation": case.direct_skill_invocation,
            "headline": f"[omh] {case.title}",
            "body_lines": [
                case.hermes_use_case,
                f"Route: {case.primary_skill} -> {case.next_action}.",
                case.user_value,
            ],
            "status_line": f"prepared_not_observed | {case.primary_skill} | {case.next_action}",
        },
        "wrapper_card": {
            "component": "omh_use_case_card",
            "render_profile": "chat_first",
            "status": "prepared_not_observed",
            "headline": f"[omh] {case.title}",
            "summary": case.user_value,
            "sections": [
                {
                    "id": "why_this_route",
                    "title": "Why this workflow",
                    "body": case.hermes_use_case,
                },
                {
                    "id": "what_omh_prepares",
                    "title": "What OMH prepares",
                    "body": case.feature_surface,
                },
                {
                    "id": "evidence_boundary",
                    "title": "What is not evidence yet",
                    "body": case.evidence_boundary,
                },
            ],
            "chips": [case.goal, case.primary_skill, exposure["exposure"], case.next_action],
        },
        "actions": [
            {
                "id": case.next_action,
                "label": _action_label(case.next_action),
                "kind": "hermes_prompt",
                "style": "primary",
                "value": case.hermes_chat_prompt,
            },
            {
                "id": "inspect_playbook",
                "label": "Inspect playbook",
                "kind": "operator_command",
                "style": "secondary",
                "value": f"omh playbook inspect {case.playbook} --json",
            },
            {
                "id": "inspect_harness",
                "label": "Inspect harness",
                "kind": "operator_command",
                "style": "secondary",
                "value": f"omh harness inspect {case.harness} --json",
            },
            {
                "id": "show_boundary",
                "label": "Show evidence boundary",
                "kind": "static_boundary",
                "style": "secondary",
                "value": case.evidence_boundary,
            },
        ],
        "operator_commands": [
            f"omh cases inspect {case.goal} --json",
            f"omh playbook inspect {case.playbook} --json",
            f"omh harness inspect {case.harness} --json",
        ],
        "evidence": {
            "state": "prepared_not_observed",
            "claim_boundary": case.evidence_boundary,
            "not_evidence_until_observed": [
                "runtime_execution",
                "connector_invocation",
                "delivery_or_attachment",
                "file_generation",
                "memory_mutation",
                "executor_dispatch",
                "executor_result",
                "verification",
                "review",
                "ci",
                "merge",
            ],
        },
        "case": exposure,
    }


def _action_label(action: str) -> str:
    return action.replace("_", " ").capitalize()


def _artifact_operator_steps(case: UseCase) -> list[dict[str, str]]:
    return [
        {
            "id": "inspect_case",
            "kind": "operator_command",
            "label": "Inspect use case",
            "value": f"omh cases inspect {case.goal} --json",
        },
        {
            "id": "render_demo_card",
            "kind": "operator_command",
            "label": "Render wrapper card",
            "value": f"omh cases demo {case.goal} --json",
        },
        {
            "id": "inspect_playbook",
            "kind": "operator_command",
            "label": "Inspect playbook",
            "value": f"omh playbook inspect {case.playbook} --json",
        },
        {
            "id": "inspect_harness",
            "kind": "operator_command",
            "label": "Inspect harness",
            "value": f"omh harness inspect {case.harness} --json",
        },
        {
            "id": "start_in_hermes",
            "kind": "hermes_prompt",
            "label": "Start in Hermes",
            "value": case.hermes_chat_prompt,
        },
        {
            "id": "record_observed_evidence",
            "kind": "boundary",
            "label": "Record observed evidence only after host/runtime action",
            "value": case.evidence_boundary,
        },
    ]


def _artifact_id(case: UseCase) -> str:
    return f"{case.goal.lower()}-{case.id}"


def _use_case_artifact_path(paths: OmhPaths, artifact_id: str) -> Path:
    if not _valid_artifact_id(artifact_id):
        raise ValueError("artifact_id must contain only letters, digits, and hyphens, and must not contain path separators")
    path = paths.use_case_artifacts_dir / f"{artifact_id}.json"
    root = paths.use_case_artifacts_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("artifact_id escapes use-case artifact storage")
    return path


def _write_use_case_artifact_index(paths: OmhPaths) -> None:
    records = list_use_case_artifacts(paths)
    ensure_dir(paths.use_cases_dir, private=True)
    atomic_write_json(
        paths.use_case_artifacts_index_path,
        {
            "schema_version": USE_CASE_ARTIFACT_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "authority": "cache_only",
            "artifacts": [
                {
                    "artifact_id": record.get("artifact_id", ""),
                    "goal": record.get("goal", ""),
                    "id": record.get("id", ""),
                    "title": record.get("title", ""),
                    "primary_skill": (record.get("route") or {}).get("primary_skill", "")
                    if isinstance(record.get("route"), dict)
                    else "",
                    "observation_status": record.get("observation_status", ""),
                }
                for record in records
            ],
        },
        private=True,
    )


def _valid_artifact_id(value: str) -> bool:
    return bool(_ARTIFACT_ID_RE.fullmatch(str(value)))


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
