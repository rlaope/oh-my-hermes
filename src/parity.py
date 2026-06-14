from __future__ import annotations

from dataclasses import dataclass


PARITY_MATRIX_SCHEMA_VERSION = "omh_parity_matrix/v1"


@dataclass(frozen=True)
class ParityCapability:
    id: str
    title: str
    common_pattern: str
    omh_surface: str
    status: str
    evidence: tuple[str, ...]
    missing_piece: str
    v1_decision: str
    user_value: str
    claim_boundary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "common_pattern": self.common_pattern,
            "omh_surface": self.omh_surface,
            "status": self.status,
            "evidence": list(self.evidence),
            "missing_piece": self.missing_piece,
            "v1_decision": self.v1_decision,
            "user_value": self.user_value,
            "claim_boundary": self.claim_boundary,
        }


PARITY_CAPABILITIES: tuple[ParityCapability, ...] = (
    ParityCapability(
        id="skill_plugin_distribution",
        title="Skill and plugin distribution",
        common_pattern="Install a native skill/plugin payload, then let the host agent surface workflows without making users memorize backend commands.",
        omh_surface="`hermes skills ...` compatible skill pack, `omh setup`, and the optional `~/.hermes/plugins/omh` bridge.",
        status="available",
        evidence=("skills/*/SKILL.md", "src/plugin_bundle/omh/plugin.yaml", "src/plugin_pack.py", "src/commands/setup.py"),
        missing_piece="Observed Hermes plugin load/use still requires runtime evidence from the host.",
        v1_decision="Keep skills as the default surface and plugin as a thin metadata bridge.",
        user_value="Users install OMH once and then talk to Hermes; operators can still verify the local payload.",
        claim_boundary="Plugin install/import/register smoke is not proof that Hermes loaded or used the plugin.",
    ),
    ParityCapability(
        id="specialist_roles",
        title="Specialist role/profile system",
        common_pattern="Expose reusable specialist roles so the agent can route planning, implementation, review, research, and operations work consistently.",
        omh_surface="Skill catalog role metadata, operating models, optional OMH-prefixed visible profile packs, and wrapper role narration.",
        status="partial",
        evidence=("src/skills/catalog.py", "src/profiles/team.py", "src/team_profiles.py", "skills/oh-my-hermes/SKILL.md"),
        missing_piece="OMH does not claim hidden live specialist agents unless Hermes or a wrapper records target-specific role evidence.",
        v1_decision="Keep role profiles optional and Hermes-facing instead of forcing a CTO/PM/Dev/QA organization model at setup.",
        user_value="Hermes can explain who owns the next step without pretending a separate runtime role acted.",
        claim_boundary="Role metadata is routing guidance, not observed delegation evidence.",
    ),
    ParityCapability(
        id="team_swarm_workers",
        title="Team, swarm, and worker protocol",
        common_pattern="Coordinate multiple lanes with explicit worker ownership, status, handoff, and review boundaries.",
        omh_surface="`team`, `ultrawork`, runtime handoff payloads, worker-protocol guidance, wrapper sessions, and runtime observations.",
        status="partial",
        evidence=("skills/team/SKILL.md", "skills/ultrawork/SKILL.md", "src/coding_delegation.py", "src/runtime/records.py"),
        missing_piece="OMH does not launch a hidden tmux team, spawn workers, or manage real worker panes itself.",
        v1_decision="Support executor-neutral team handoff and observation first; real worker launch stays with Hermes, Codex, Claude Code, OMX, OMO, OMC, or another selected runtime.",
        user_value="A chat wrapper can show Start team, Attach session, Record worker result, and Review status without asking the user to type raw backend commands.",
        claim_boundary="Prepared worker lanes are not worker dispatch, result, review, CI, or merge evidence.",
    ),
    ParityCapability(
        id="worktree_isolation",
        title="Worktree and project-session isolation",
        common_pattern="Use isolated workspaces so parallel agents can work without stepping on each other's files.",
        omh_surface="Coding runtime handoff contracts, loop queue metadata, and runtime observations for worktree creation.",
        status="partial",
        evidence=("src/coding_contracts.py", "src/goal_loop.py", "src/runtime/records.py", "docs/DELEGATION_FIRST_COMPLETENESS.md"),
        missing_piece="OMH records and requests worktree isolation but does not create Git worktrees or bind host agent sessions directly.",
        v1_decision="Keep worktree operations explicit and observed; add richer runbook/checklist support before any creator command.",
        user_value="Teams get the safety language and status boundary now, while actual workspace creation remains in the chosen executor/runtime.",
        claim_boundary="A worktree plan is not a created worktree; only runtime observation can mark it observed.",
    ),
    ParityCapability(
        id="hud_session_observability",
        title="HUD, status, and session observability",
        common_pattern="Show compact live state plus post-session artifacts so operators can inspect what happened.",
        omh_surface="`omh hud`, plugin `omh_hud`/`omh_status` tools, wrapper sessions, runtime runs, memory inspect, and status cards.",
        status="available",
        evidence=("src/hud.py", "src/plugin_bundle/omh/tools/hud_tool.py", "src/wrapper/sessions.py", "src/runtime/artifacts.py"),
        missing_piece="Live host HUD rendering depends on Hermes/plugin runtime support and is not inferred from local files alone.",
        v1_decision="Keep the HUD compact: version, plugin readiness, target topology, coding-agent state, and evidence boundary.",
        user_value="Hermes can answer status questions without mixing prepared handoff with observed execution.",
        claim_boundary="A HUD line summarizes local state; it is not execution proof.",
    ),
    ParityCapability(
        id="mcp_tool_bridge",
        title="MCP and tool bridge preference",
        common_pattern="Offer tool/MCP bridge configuration so the host agent can reach external capabilities through a controlled surface.",
        omh_surface="`omh setup --with-mcp`, `omh probe`, and MCP preference/host-config separation.",
        status="partial",
        evidence=("src/commands/setup.py", "src/probe.py", "docs/INSTALLATION.md"),
        missing_piece="OMH does not ship or auto-enable a real MCP server/tool bridge in v1.",
        v1_decision="Record MCP intent and host-file evidence separately until a stable Hermes MCP bridge contract exists.",
        user_value="Operators can prepare for MCP without accidentally claiming a tool host loaded or ran OMH.",
        claim_boundary="MCP preference and MCP host config are not MCP tool-call evidence.",
    ),
    ParityCapability(
        id="loop_autopilot",
        title="Loop and autopilot workflow",
        common_pattern="Turn large goals into repeated research, plan, execute, verify, feedback, and continuation cycles.",
        omh_surface="`loop`, `ultraprocess`, `ralplan`, `ultragoal`, loop queue ticks, verification tiers, and failure-mode status cards.",
        status="available",
        evidence=("src/goal_loop.py", "src/commands/loop.py", "skills/loop/SKILL.md", "skills/ultraprocess/SKILL.md"),
        missing_piece="Scheduling, connector I/O, worktree creation, and subagent execution remain prepared or delegated until observed.",
        v1_decision="Make loop engineering safe and inspectable before adding unattended execution.",
        user_value="Hermes can keep ambitious goals moving while preserving verification gaps and human judgment points.",
        claim_boundary="A loop tick prepares orchestration; it is not proof that external work ran.",
    ),
    ParityCapability(
        id="release_doctor_update",
        title="Doctor, update, uninstall, and release smoke",
        common_pattern="Give operators maintenance commands that verify installation health, update state, and release readiness.",
        omh_surface="`omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh release checklist`, and `omh release hermes-smoke`.",
        status="available",
        evidence=("src/commands/setup.py", "src/doctor.py", "src/release.py", "install.sh"),
        missing_piece="Live release smoke still needs an explicit target Hermes profile or operator confirmation before mutation.",
        v1_decision="Keep maintenance local by default and make live Hermes mutation opt-in.",
        user_value="A company can install, repair, update, uninstall, and prepare releases without guessing what happened.",
        claim_boundary="Release checklists are plans until their commands are run and evidence is attached.",
    ),
)


def build_parity_matrix(probe_payload: dict[str, object] | None = None) -> dict[str, object]:
    capabilities = [capability.to_dict() for capability in PARITY_CAPABILITIES]
    counts: dict[str, int] = {}
    for capability in capabilities:
        status = str(capability.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema_version": PARITY_MATRIX_SCHEMA_VERSION,
        "basis": "OMX/OMC/OMO common public capability patterns, translated into OMH's Hermes-native evidence model.",
        "summary": {
            "capability_count": len(capabilities),
            "available": counts.get("available", 0),
            "partial": counts.get("partial", 0),
            "planned": counts.get("planned", 0),
            "deferred": counts.get("deferred", 0),
        },
        "capabilities": capabilities,
        "probe_alignment": _probe_alignment(probe_payload or {}),
        "recommended_next_prs": [
            {
                "id": "native-role-evidence",
                "title": "Record wrapper-observed role lane results",
                "why": "Closes the specialist role gap without claiming hidden Hermes agents.",
            },
            {
                "id": "worktree-runbook",
                "title": "Add worktree/session isolation runbooks and smoke fixtures",
                "why": "Makes executor-neutral worktree guidance more operational before any creator command exists.",
            },
            {
                "id": "mcp-bridge-contract",
                "title": "Define a real OMH MCP bridge contract",
                "why": "Turns MCP preference into an installable, testable bridge when Hermes support is stable enough.",
            },
        ],
        "claim_boundary": (
            "The parity matrix is a product and operator contract. It does not claim hidden worker launch, "
            "worktree creation, MCP tool calls, plugin runtime load, executor execution, review, CI, or merge evidence."
        ),
    }


def _probe_alignment(probe_payload: dict[str, object]) -> dict[str, object]:
    capabilities = probe_payload.get("capabilities", [])
    by_name = {
        str(capability.get("name", "")): str(capability.get("status", "unknown"))
        for capability in capabilities
        if isinstance(capability, dict)
    }
    return {
        "managed_skills": by_name.get("managed_skills", "unknown"),
        "external_skill_dirs": by_name.get("external_skill_dirs", "unknown"),
        "omh_plugin_bundle": by_name.get("omh_plugin_bundle", "unknown"),
        "plugin_register_smoke": by_name.get("plugin_register_smoke", "unknown"),
        "mcp_preference": by_name.get("mcp_preference", "unknown"),
        "mcp_host_config": by_name.get("mcp_host_config", "unknown"),
        "target_topology": by_name.get("target_topology", "unknown"),
        "wrapper_metadata": by_name.get("wrapper_metadata", "unknown"),
    }
