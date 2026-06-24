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
        omh_surface="`hermes skills ...` compatible skill pack, `omh setup`, and the managed `~/.hermes/plugins/omh` bridge.",
        status="available",
        evidence=(
            "skills/*/SKILL.md",
            "src/omh/plugin_bundle/omh/plugin.yaml",
            "src/omh/plugin_pack.py",
            "src/omh/plugin_observations.py",
            "src/omh/commands/plugin.py",
        ),
        missing_piece="Live Hermes plugin load/use is now recordable, but it still requires host or wrapper-supplied evidence.",
        v1_decision="Keep skills as the default surface and plugin as a thin metadata bridge.",
        user_value="Users install OMH once and then talk to Hermes; operators can still verify the local payload.",
        claim_boundary=(
            "Plugin install/import/register smoke is not proof that Hermes loaded or used the plugin; "
            "omh_plugin_host_observation/v1 proves only the recorded host plugin event."
        ),
    ),
    ParityCapability(
        id="specialist_roles",
        title="Specialist role/profile system",
        common_pattern="Expose reusable specialist roles so the agent can route planning, implementation, review, research, and operations work consistently.",
        omh_surface="Skill catalog role metadata, operating models, optional visible profile packs, wrapper role narration, and plugin `omh_role` / `[omh-role:name]` context injection.",
        status="available",
        evidence=("src/omh/catalogs/roles.py", "src/omh/plugin_bundle/omh/omh_roles.py", "src/omh/plugin_bundle/omh/tools/role_tool.py", "src/omh/plugin_bundle/omh/hooks/tool_hooks.py"),
        missing_piece="Observed role execution still requires wrapper or runtime evidence; role context is not a hidden live agent.",
        v1_decision="Make role context native to the plugin while keeping profile packs optional and evidence claims conservative.",
        user_value="Hermes can route to a responsibility lane and inject bounded role context without making users manage long role prompts.",
        claim_boundary="Role context is prompt guidance, not observed delegation, worker start, execution, review, CI, or merge evidence.",
    ),
    ParityCapability(
        id="bounded_evidence_probe",
        title="Bounded evidence probe",
        common_pattern="Let the host agent run explicitly allowlisted local verification commands and return structured pass/fail output.",
        omh_surface="Plugin `omh_gather_evidence` runs shell-free allowlisted local probes such as OMH doctor, harness validation, docs checks, unittest, compileall, and git diff whitespace checks.",
        status="available",
        evidence=("src/omh/plugin_bundle/omh/tools/evidence_tool.py", "src/omh/plugin_bundle/omh/config.yaml", "tests/test_plugin_distribution.py"),
        missing_piece="It is not a general command runner and does not observe executor dispatch, PR review, CI, merge, or Hermes plugin runtime load.",
        v1_decision="Ship a narrow explicit verification probe before any broader evidence runner or connector tool.",
        user_value="Hermes can gather basic local verification evidence without asking users to paste terminal output or granting arbitrary shell access.",
        claim_boundary="Evidence probes prove only the allowlisted local command result they ran.",
    ),
    ParityCapability(
        id="team_swarm_workers",
        title="Team, swarm, and worker protocol",
        common_pattern="Coordinate multiple lanes with explicit worker ownership, status, handoff, and review boundaries.",
        omh_surface="`team`, `ultrawork`, `omh runtime team-readiness`, runtime handoff payloads, worker-protocol guidance, wrapper sessions, and runtime observations.",
        status="available",
        evidence=(
            "skills/team/SKILL.md",
            "skills/ultrawork/SKILL.md",
            "src/omh/team_readiness.py",
            "src/omh/runtime/records.py",
            "src/omh/wrapper/sessions.py",
        ),
        missing_piece="Live worker launch and pane/session management still require the selected host runtime to act and record observations.",
        v1_decision="Provide the team/swarm worker contract, readiness verifier, wrapper actions, and observation ledger; real worker launch stays with Hermes, Codex, Claude Code, OMX, OMO, OMC, or another selected runtime.",
        user_value="A chat wrapper can show Start team, Attach session, Record worker result, and Review status without asking the user to type raw backend commands.",
        claim_boundary="Prepared worker lanes are not worker dispatch, result, review, CI, or merge evidence.",
    ),
    ParityCapability(
        id="worktree_isolation",
        title="Worktree and project-session isolation",
        common_pattern="Use isolated workspaces so parallel agents can work without stepping on each other's files.",
        omh_surface="`worktree_session_isolation/v1` plans inside coding handoffs, wrapper Prepare worktree actions, `omh worktree prepare/list/bind`, executor-session status cards, loop queue metadata, and runtime observations for worktree creation.",
        status="available",
        evidence=("src/omh/isolation.py", "src/omh/worktree_creator.py", "src/omh/commands/worktree.py", "src/omh/wrapper/executor_sessions.py", "tests/test_worktree_creator.py"),
        missing_piece="OMH can explicitly create a local Git worktree and return binding recipes, but it does not auto-launch executors or claim host agent sessions without wrapper/runtime evidence.",
        v1_decision="Make worktree mutation explicit and opt-in: the wrapper may show Prepare worktree, create it through the backend, then bind the selected coding agent with a recipe.",
        user_value="Teams see when same workspace is acceptable, when an isolated worktree is recommended, and how to open or attach the chosen coding agent from that worktree.",
        claim_boundary=(
            "A worktree plan is not a created worktree; an OMH-created worktree is "
            "workspace-isolation evidence only, and a binding recipe is session-start guidance only, "
            "not executor dispatch or implementation evidence."
        ),
    ),
    ParityCapability(
        id="hud_session_observability",
        title="HUD, status, and session observability",
        common_pattern="Show compact live state plus post-session artifacts so operators can inspect what happened.",
        omh_surface="`omh hud`, plugin `omh_recommend`/`omh_hud`/`omh_status` tools, wrapper sessions, runtime runs, memory inspect, and status cards.",
        status="available",
        evidence=("src/omh/hud.py", "src/omh/plugin_bundle/omh/tools/hud_tool.py", "src/omh/wrapper/sessions.py", "src/omh/runtime/artifacts.py"),
        missing_piece="Live host HUD rendering depends on Hermes/plugin runtime support and is not inferred from local files alone.",
        v1_decision="Keep the HUD compact: version, plugin readiness, target topology, coding-agent state, and evidence boundary.",
        user_value="Hermes can answer status questions without mixing prepared handoff with observed execution.",
        claim_boundary="A HUD line summarizes local state; it is not execution proof.",
    ),
    ParityCapability(
        id="mcp_tool_bridge",
        title="MCP and tool bridge",
        common_pattern="Offer tool/MCP bridge configuration so the host agent can reach external capabilities through a controlled surface.",
        omh_surface="`omh setup --with-mcp`, `omh mcp manifest`, `omh mcp config-recipe`, `omh mcp serve`, `omh probe`, and MCP preference/host-config/runtime-call separation.",
        status="available",
        evidence=("src/omh/mcp_bridge.py", "src/omh/commands/mcp.py", "src/omh/probe.py", "tests/test_mcp_bridge.py"),
        missing_piece="OMH does not auto-enable a host MCP config or independently inspect live host sessions; the host or wrapper must record load/session evidence.",
        v1_decision="Ship a dependency-free stdio bridge with only allowlisted local status, recommendation, and probe tools.",
        user_value="Operators can connect OMH to MCP-capable hosts with copy-paste host recipes without exposing arbitrary shell or hidden execution.",
        claim_boundary="MCP bridge availability and host config are not connector invocation, coding dispatch, implementation, review, CI, merge, or host-load proof.",
    ),
    ParityCapability(
        id="loop_autopilot",
        title="Loop and autopilot workflow",
        common_pattern="Turn large goals into repeated research, plan, execute, verify, feedback, and continuation cycles.",
        omh_surface="`loop`, `ultraprocess`, `ralplan`, `ultragoal`, loop queue ticks, verification tiers, and failure-mode status cards.",
        status="available",
        evidence=("src/omh/goal_loop.py", "src/omh/commands/loop.py", "skills/loop/SKILL.md", "skills/ultraprocess/SKILL.md"),
        missing_piece="Scheduling, connector I/O, worktree creation, and subagent execution remain prepared or delegated until observed.",
        v1_decision="Make loop engineering safe and inspectable before adding unattended execution.",
        user_value="Hermes can keep ambitious goals moving while preserving verification gaps and human judgment points.",
        claim_boundary="A loop tick prepares orchestration; it is not proof that external work ran.",
    ),
    ParityCapability(
        id="release_doctor_update",
        title="Doctor, update, uninstall, and release smoke",
        common_pattern="Give operators maintenance commands that verify installation health, update state, and release readiness.",
        omh_surface="`omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh release checklist`, `omh release product-readiness`, and `omh release hermes-smoke`.",
        status="available",
        evidence=("src/omh/commands/setup.py", "src/omh/doctor.py", "src/omh/release.py", "install.sh"),
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
        "recommended_next_prs": [],
        "claim_boundary": (
            "The parity matrix is a product and operator contract. It does not claim hidden worker launch, "
            "automatic worktree creation, host-observed MCP load, plugin runtime load, executor execution, review, CI, or merge evidence."
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
        "plugin_runtime_observed": by_name.get("plugin_runtime_observed", "unknown"),
        "plugin_runtime_active": "available" if probe_payload.get("plugin_runtime_active") else "unverified",
        "mcp_preference": by_name.get("mcp_preference", "unknown"),
        "mcp_bridge_server": by_name.get("mcp_bridge_server", "unknown"),
        "mcp_bridge_runtime": by_name.get("mcp_bridge_runtime", "unknown"),
        "mcp_host_session": by_name.get("mcp_host_session", "unknown"),
        "mcp_host_config": by_name.get("mcp_host_config", "unknown"),
        "team_worker_readiness": by_name.get("team_worker_readiness", "unknown"),
        "team_worker_presentation": str(probe_payload.get("team_worker_presentation_status", "unknown")),
        "worktree_creator": by_name.get("worktree_creator", "unknown"),
        "target_topology": by_name.get("target_topology", "unknown"),
        "wrapper_metadata": by_name.get("wrapper_metadata", "unknown"),
    }
