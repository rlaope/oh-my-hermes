# Delegation-First Completeness

## Direction

The product charter is `docs/DIRECTION.md`. This document expands the
delegation-first completion slice of that charter.

This is an implementation and integration reference. Users ask Hermes to handle
coding work in natural language; Hermes Agent, wrappers, and coding agents use
the command and schema surfaces documented below.

OMH should raise Hermes toward a mature workflow-layer experience without
pretending that Hermes is the primary coding executor.

The intended boundary is:

- Hermes owns chat intake, clarification, planning, routing, status narration,
  and user-facing workflow continuity.
- The selected coding executor owns main implementation, code review,
  verification, and merge-readiness work when work leaves Hermes.
- `omh` owns deterministic local contracts between those surfaces: it prepares
  handoffs, records metadata-only evidence, and keeps observed execution
  separate from prepared intent.

This direction keeps OMH useful for Discord, Slack, and hosted Hermes wrappers
while preserving the current project constraints: no hidden Hermes core patching,
no LLM/API/network calls inside `omh`, and no runtime claim unless local wrapper
evidence exists.

## Current Local Surfaces

| Surface | Current role | Evidence |
| --- | --- | --- |
| plugin `omh_interact`, `omh chat interact` | Compose route, plan, delegation, and status into one wrapper-native `chat_interaction/v1` response for Discord, Slack, and hosted Hermes adapters. The plugin path can also record a metadata-only wrapper session. | `src/plugin_bundle/omh/tools/chat_tool.py`, `src/wrapper/contract.py`, `tests/test_plugin_capabilities.py`, `tests/test_wrapper_contract.py`, `tests/test_cli.py` |
| `omh chat session` | Persists metadata-only chat session decisions, executor/runtime selection, plan acceptance/revision/cancel state, prompt-only handoffs, runtime handoffs, and accepted Codex lifecycle links. | `src/wrapper/sessions.py`, `tests/test_wrapper_sessions.py`, `tests/test_cli.py` |
| `omh chat session open-executor`, `attach-executor`, `record-executor`, `request-verification` | Backend actions for wrapper-rendered buttons such as Start Codex session, Start Claude Code session, Attach coding session, Refresh status, Record completed, Record blocked, and Ask Hermes to verify. They write `executor_session/v1` metadata after Hermes or the wrapper observes a coding-session event; OMH itself does not launch hidden executors. | `src/wrapper/executor_sessions.py`, `tests/test_wrapper_sessions.py`, `tests/test_cli.py` |
| `omh chat route` | Deterministically routes plain chat into a workflow decision before wrapper dispatch. | `src/routing/chat.py`, `tests/test_cli.py` |
| `omh hermes plan` | Produces Hermes-facing plan scaffolds and wrapper contracts under `.hermes/plans`, with accept/revise/cancel lifecycle events. | `src/workflows/hermes_planning.py`, `docs/ARCHITECTURE.md` |
| `omh hermes readiness` | Inspects local Hermes Agent home/config/skills/plugins/sessions/state/source-checkout markers and maps them to OMH memory, learning, loop, wiki/external-knowledge, runtime-observation, and subagent/handoff reinforcement. | `src/workflows/hermes_readiness.py`, `src/commands/hermes.py` |
| `omh hermes retained-context` | Inspects metadata-only Hermes sessions/state/memory-provider markers alongside OMH memory, workflow-learning, runtime journal, loop, and external knowledge-store markers so wrappers can show what durable context can actually be reinforced without reading raw retained artifacts or claiming opaque Hermes memory contents. | `src/workflows/hermes_retained_context.py`, `src/workflows/hermes_retained_context_probes.py`, `tests/test_hermes_retained_context.py` |
| `omh coding delegate` | Prepares metadata-only coding handoffs, executor/runtime-choice contracts, prompt-only payloads, runtime contracts, and accepted-plan `--from-plan` Codex handoffs without overclaiming execution. Hermes selection also exposes an optional coding team path with solo, durable-goal, team, and swarm start choices plus a read-only `hermes_coding_harness/v1` projection over builder, verifier, reviewer, docs, and PR lanes. Handoffs include an executor-neutral task prompt contract; Codex lifecycle handoffs also include a prepared-only session observation contract for future executor-session adapters. | `src/coding/coding_delegation.py`, `src/coding/hermes_harness.py`, `src/runtime/artifacts.py` |
| `worktree_session_isolation/v1` | Adds deterministic workspace-isolation guidance to coding handoffs and executor-session status: same workspace ok, worktree recommended, or worktree required. | `src/coding/isolation.py`, `src/wrapper/executor_sessions.py`, `tests/test_wrapper_sessions.py` |
| `omh coding lifecycle` | Tracks Codex-selected handoff dispatch, executor result, verification, and reportable status from existing runtime evidence. | `src/wrapper/lifecycle.py`, `tests/test_coding_lifecycle.py`, `tests/test_cli.py` |
| `omh memory status/capture/review/approve/reject/recall` plus `inspect/pack/apply` | Captures typed OMH project-memory candidates, keeps reviewed records separate, recalls `memory_recall_pack/v1` into prepared coding handoffs, and reviews OMH-local or wrapper-supplied context before attaching conflict-free `handoff_context_pack/v1` summaries. | `src/workflows/memory.py`, `tests/test_memory.py` |
| `omh runtime wrapper` | Lets wrappers record what they actually observed after dispatch. | `src/runtime/artifacts.py`, `README.md` |
| `omh runtime observe` | Records metadata-only observation journal events for prepared-to-observed lifecycle status, and preserves `runtime_observation/v1` compatibility for Hermes/OMX/OMO/OMC runtime handoffs: runtime start, worktree creation, worker dispatch/result, verification, review, CI, merge-readiness, and merge. | `src/runtime/artifacts.py`, `src/runtime/records.py`, `tests/test_cli.py`, `tests/test_runtime_artifacts.py` |
| `omh runtime review`, `omh runtime ci`, `omh runtime merge` | Records observed review, CI, merge-readiness, and merge evidence under the run ledger. | `src/runtime/artifacts.py`, `src/runtime/records.py`, `tests/test_cli.py` |
| `omh runtime validate/export` | Validates and exports local evidence without storing prompt bodies by default. | `src/runtime/artifacts.py`, `tests/test_runtime_artifacts.py` |
| `omh conformance check --run <run-id>` | Projects existing runtime validation, delegated-status evidence, and runtime-owned claim vocabulary into one safe-claim verdict, such as prepared-only, execution observed, verification missing, or merge-ready. This is not a new ledger; it answers which claim is currently allowed. | `src/conformance/checker.py`, `src/runtime/artifacts.py`, `src/runtime/claims.py`, `tests/test_conformance.py` |
| `examples/wrapper-golden/` | Provides platform-neutral golden chat responses for wrapper button/thread/status UX, including plugin-native `omh_interact` examples. | `examples/wrapper-golden/status-ladder.json`, `examples/wrapper-golden/plugin-interact.json`, `tests/test_wrapper_golden_examples.py` |

The strongest existing path is:

1. A Discord or Slack wrapper receives a plain user message.
2. The wrapper or Hermes plugin calls `omh_interact` or `omh chat interact` and
   renders the returned `chat_response/v1` in the original channel or thread.
3. If the wrapper needs restart recovery and did not use plugin session
   recording, it records the turn with `omh chat session start`.
4. For planning-shaped work, the wrapper presents the draft plan and records
   accept/revise/cancel decisions with `omh chat session`.
5. For accepted implementation-shaped work, the wrapper records executor or
   runtime selection. Codex selection prepares a lifecycle handoff and links
   the session to the runtime run id; Claude Code and generic agents prepare a
   prompt-only handoff; runtime profiles prepare a runtime handoff without a
   lifecycle run. When Hermes itself is selected, the runtime handoff also
   includes `hermes_coding_team_path/v1` so chat surfaces can show solo,
   durable-goal, team, and swarm start choices. It also includes
   `hermes_coding_harness/v1`, a read-only projection that answers what Hermes
   is doing now across intake, scope, plan, workspace, build, verify, review,
   docs sync, PR preparation, and handover without creating a second evidence
   ledger. Runtime handoffs include runtime-specific templates and a
   `runtime_observation/v1` contract so wrappers know exactly which events must
   be observed later. Coding handoffs also include
   `worktree_session_isolation/v1`, which tells the wrapper
   whether the current workspace is acceptable, an isolated worktree is
   recommended, or an isolated worktree is required before starting a coding
   session.
6. The wrapper renders executor-session buttons instead of asking the user to
   type backend commands. Start-session buttons carry `executor_launch/v1` with
   the configured executor profile. The v1 safety fields stay copyable and
   metadata-only for compatibility; wrappers should read
   `terminal_launch_available` and `session_start_capability` to decide whether
   Codex/Claude Code command templates are safe to render. Attach/record buttons
   stay metadata-only. If isolation is recommended or required, the first action
   is `prepare_worktree`; the later launch payload carries a workspace hint for
   the selected executor. When Hermes or the wrapper observes Prepare worktree,
   Start Codex session, Attach coding session, Record completed, Record blocked,
   or Ask Hermes to verify, it writes
   `executor_session/v1` metadata and derives status lines such as
   `workspace-isolation: worktree_recommended(prepared_not_observed)`,
   `coding-agent: running(codex)`, `dispatch: observed`, and
   `verification: requested`.
7. Separate wrapper/runtime evidence is required before OMH can say execution,
   review, verification, CI, merge, or merge-readiness was observed.

## Hermes Surface Readiness

| Priority | Focus | Why it matters | Target story |
| --- | --- | --- | --- |
| P0 | Hermes Agent consumes OMH contracts. | OMH should read as a Hermes-native capability layer, not as a separate bot product. | Keep OMH focused on fixture-backed chat contracts and local status artifacts. |
| P1 | Hermes-facing examples should stay concrete. | Golden JSON locks the wrapper contract, but operators still need examples for rendering replies, actions, status cards, and thread keys. | Add fixture-backed examples that show chat UX without implying missing platform code. |
| P2 | Run-backed Codex lifecycle reporting remains Codex-only, but runtime observation is available for Hermes/OMX/OMO/OMC handoffs. | Other targets are supported without overclaiming: prompt-only for Claude Code/generic agents, runtime handoff templates for Hermes/OMX/OMO/OMC, and `runtime_observation/v1` records for observed runtime ladder steps. | Keep lifecycle dispatch/result semantics separate from runtime observation until another executor exposes an equivalent lifecycle contract. |

## First Implementation Contract

The completed deterministic feature makes executor selection explicit without
launching any coding executor from `omh`.

Expected behavior:

- `omh coding delegate` continues to work for generic wrappers.
- `omh coding delegate --executor choose` returns a human-in-the-loop executor
  choice contract.
- `omh coding delegate --executor codex` returns a dispatch-capable Codex
  lifecycle handoff that can be tracked through `omh coding lifecycle`.
- `omh coding delegate --executor claude-code` or `--executor generic` returns
  a prompt-only handoff that does not create a lifecycle run.
- `omh coding delegate --executor hermes` returns a runtime handoff plus
  `hermes_coding_team_path/v1` with solo, durable-goal, team, and swarm start
  choices. The path stays prepared-only until matching runtime observations are
  recorded.
- `omh coding delegate --executor hermes` also returns
  `hermes_coding_harness/v1`, a read-only projection over existing session,
  runtime handoff, status-card, worktree isolation, harness-progress, and
  `runtime_observation/v1` evidence. The harness keeps builder, verifier,
  reviewer, docs, and PR lanes separate even when one Hermes agent owns all
  lanes. Its nested `verification_matrix`, `docs_sync`, and `pr_preparation`
  sections are guidance until matching observed evidence exists.
- Runtime-profile executor selections return a runtime handoff contract with
  team/swarm, worker-protocol, and worktree guidance, but still do not create a
  lifecycle run.
- All executor, prompt-only, and runtime coding handoffs include
  `worktree_session_isolation/v1`. It is a prepared wrapper contract, not a Git
  worktree creator. It can add `prepare_worktree` as the next visible action
  before `open_executor_session` when the request is risky, parallel,
  multi-agent, or runtime-owned.
- All executor, prompt-only, and runtime coding handoffs include
  `executor_task_prompt_contract/v1`, which asks wrappers and selected
  executors to shape dispatched task text as `Goal / Do / Don't / Expected
  result / Test`, keep executor-facing prompts in English unless preserving
  literals, and steer active turns with delta-only corrections.
- All executor, prompt-only, and runtime coding handoffs include
  `executor_local_capability_strategy/v1`, which asks the selected coding
  owner to inspect executor-local skills, workflow packs, slash commands,
  subagents, MCP tools, repo scripts, tests, and CI metadata before falling
  back to a plain prompt. Codex handoffs explicitly name OMX/oh-my and custom
  Codex skills as examples; Claude Code handoffs explicitly name Everything
  Claude Code, user-defined Claude Code skills, slash commands, and
  agents/subagents as examples. These are prepared prompting examples, not
  OMH-observed installation or execution evidence.
- All executor, prompt-only, and runtime coding handoffs include
  `executor_local_capability_report_contract/v1`. This is distinct from the
  discovery strategy: it tells the selected coding owner how to report actual
  local capability usage after real work. Reports must include
  `local_capabilities_used`, `local_capability_evidence_refs`, and
  `local_capability_fallback_reason`, and any used capability item must carry
  an `evidence_ref`. The contract is still prepared guidance, not proof that
  OMH observed the capability, dispatch, implementation, review, CI, merge
  readiness, or merge.
- Codex lifecycle handoffs include `codex_session_observation_contract/v1`.
  This is a prepared-only requirement for a future Codex session adapter: it
  names identity fields, status fields, full-final-answer extraction,
  approval/user-input blockers, and the OMH evidence surfaces that must own
  observed state. It is not a WebSocket client, host token lookup, polling
  loop, dispatch action, auto-approval rule, or live telemetry.
- Claude Code prompt-only handoffs include
  `claude_code_session_observation_contract/v1`. It mirrors the Codex
  prepared-observation boundary while naming Claude Code session identity,
  tool-use status, subagent status, slash-command invocation, approval, and
  full-final-answer fields. Generic prompt-only handoffs do not receive this
  Claude-specific contract.
- Runtime handoff contracts include safe invocation templates such as
  `$ultragoal {message}`, `$team {message}`, `$ultrawork {message}`, or
  Hermes retained coding-skill prompts, plus an observation contract explaining
  how to record what actually happened later.
- `omh runtime observe --run <id>` or `omh runtime observe --session <id>`
  appends one observed, blocked, failed, or not-observed lifecycle event without
  upgrading missing events into evidence.
- `omh hermes plan-accept <plan.md>` and `omh coding delegate --from-plan
  <plan.md>` keep executor context file-backed. Discord/channel text is a
  summary, not the executor plan.
- `omh chat session open-executor`, `attach-executor`, `record-executor`, and
  `request-verification` are wrapper backend actions. They are meant to sit
  behind chat buttons, write `executor_session/v1`, and update status cards
  without requiring a normal chat user to type commands.
- For wrapper sessions, the observed `--runtime-profile` must match the
  prepared `coding_runtime_handoff/v1` profile. Prompt-only handoffs and Codex
  lifecycle runs do not become runtime ladders just because an observation file
  exists.
- The payload names the selected executor/runtime target and includes:
  - executor target and handoff mode
  - a prompt template, instruction payload, or runtime contract for the selected coding owner
  - task prompt and local capability report contracts for the selected coding owner
  - Codex or Claude Code session observation contracts when that selected owner has a profile-specific contract
  - runtime-specific templates when an oh-my or Hermes runtime is selected
  - a runtime observation contract for runtime handoffs
  - a worktree/session isolation plan for wrapper UX
  - scope and non-goals
  - acceptance criteria
  - verification expectations
  - review expectations
  - recording status `prepared_not_observed`
- The payload must not include a shell command string that interpolates raw
  user text.
- If an argv-like template is included, the raw user message must remain a
  placeholder such as `{message}`.
- `--record` should write metadata-only evidence and preserve message hash,
  message length, source metadata, and prepared/observed separation.
- `omh chat interact` should expose safe user-facing copy and action buttons
  without showing `omh` command names to normal chat users.

Non-goals:

- Do not invoke coding executors, Hermes, GitHub, Discord, Slack, or any network
  service.
- Do not change Hermes core behavior.
- Do not claim implementation, review, CI, or merge evidence.
- Do not store raw prompt bodies unless an existing explicit include flag is
  used for stdout-only wrapper dispatch.

## Wrapper Narrative Contract

Wrappers should be able to express the chain in human terms:

1. Hermes received and clarified or planned the request.
2. OMH either asks the user to choose an executor/runtime, prepares a
   prompt-only handoff, prepares a runtime handoff, prepares the optional
   Hermes coding team path, or prepares a Codex lifecycle handoff.
3. Runtime handoff templates show the selected runtime what to run, but the
   runtime observation ladder still starts empty.
4. Workspace isolation is shown as same workspace ok, worktree recommended, or
   worktree required. It remains prepared-only until matching worktree/session
   evidence is recorded.
5. Executor execution is pending, running, blocked, completed, or not observed
   according to wrapper evidence.
6. Review, verification, CI, and merge status stay separate from prepared
   delegation until observed.
7. Status readers evaluate the full run ledger conservatively. A later
   `merge.json` cannot make a run look merge-ready if verification, review, or
   CI is missing, failed, blocked, or contradictory.

This avoids the most dangerous failure mode: Hermes sounding like it performed
coding work that only a prepared handoff requested.

## Current Wrapper-Native Contract

`chat_interaction/v1` is the platform-neutral adapter envelope. It includes the
source, source metadata, message hash and length, `thread_key`, mode,
`next_action`, nested route/plan/delegation/status payloads when applicable,
`chat_response/v1`, redaction policy, and overclaim guard.

`chat_response/v1` is the object adapters render directly. It includes kind,
visibility, headline, body, state, platform-neutral actions, and claim boundary.
Allowed actions include `answer:*`, `accept_plan`, `revise_plan`,
`prepare_handoff`, `choose_executor`, `show_prompt_handoff`,
`copy_prompt_handoff`, `show_runtime_handoff`, `start_runtime`,
`show_coding_team_path`, `start_hermes_coding`, `prepare_worktree`,
`start_team`, `start_swarm`, `record_runtime_observation`,
`send_to_executor`, `show_status`,
`show_memory_status`, `apply_memory_updates`, and `cancel`. Memory review
actions such as `keep_memory`, `forget_memory`, `update_memory`, and
`change_memory_scope` belong to `memory_review_card/v1`, not
`status_card/v1`. `send_to_codex` remains a compatibility alias only for
Codex-selected flows.
Action labels remain product-level labels; they do not expose CLI commands,
argv arrays, or shell text.

Planning payloads include `quality_gate` and `deep_interview` blocks so a
wrapper can distinguish a draft plan from an approved plan and a blocked request
from a guessed plan. Status payloads include `status_card/v1` so a wrapper can
render workspace isolation, handoff, execution, verification, review, CI,
merge-ready, and merged steps without parsing prose.

## Success Criteria

- The implementation adds a wrapper-native chat interaction contract while
  preserving existing `coding_delegation/v1` callers.
- Tests prove no raw prompt body is stored in runtime records by default.
- Tests prove hostile shell text remains a placeholder in any argv/template
  contract.
- README and architecture docs describe Hermes as the orchestrator and the
  selected executor, runtime, or Hermes coding skill as the main coding owner for implementation work, while
  preserving Codex-only lifecycle tracking in Phase 1.
- Runtime validation remains local-only and deterministic.
