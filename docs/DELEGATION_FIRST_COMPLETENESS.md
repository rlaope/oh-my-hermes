# Delegation-First Completeness

## Direction

The product charter is `docs/DIRECTION.md`. This document expands the
delegation-first completion slice of that charter.

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
| `omh chat interact` | Composes route, plan, delegation, and status into one wrapper-native `chat_interaction/v1` response for Discord, Slack, and hosted Hermes adapters. | `src/wrapper/contract.py`, `tests/test_wrapper_contract.py`, `tests/test_cli.py` |
| `omh chat session` | Persists metadata-only chat session decisions, executor/runtime selection, plan acceptance/revision/cancel state, prompt-only handoffs, runtime handoffs, and accepted Codex lifecycle links. | `src/wrapper/sessions.py`, `tests/test_wrapper_sessions.py`, `tests/test_cli.py` |
| `omh chat session open-executor`, `attach-executor`, `record-executor`, `request-verification` | Backend actions for wrapper-rendered buttons such as Open in Codex, Open in Claude Code, Attach session, Refresh status, Record completed, Record blocked, and Ask Hermes to verify. They write `executor_session/v1` metadata and do not launch hidden executors. | `src/wrapper/executor_sessions.py`, `tests/test_wrapper_sessions.py`, `tests/test_cli.py` |
| `omh chat route` | Deterministically routes plain chat into a workflow decision before wrapper dispatch. | `src/routing/chat.py`, `tests/test_cli.py` |
| `omh hermes plan` | Produces Hermes-facing plan scaffolds and wrapper contracts under `.hermes/plans`. | `src/hermes_planning.py`, `docs/ARCHITECTURE.md` |
| `omh coding delegate` | Prepares metadata-only coding handoffs, executor/runtime-choice contracts, prompt-only payloads, and Hermes/OMX/OMO/OMC runtime contracts without overclaiming execution. | `src/coding_delegation.py`, `src/runtime/artifacts.py` |
| `omh coding lifecycle` | Tracks Codex-selected handoff dispatch, executor result, verification, and reportable status from existing runtime evidence. | `src/wrapper/lifecycle.py`, `tests/test_coding_lifecycle.py`, `tests/test_cli.py` |
| `omh memory inspect/pack/apply` | Reviews OMH-local and wrapper-supplied context, creates `memory_review_card/v1`, and attaches only conflict-free `handoff_context_pack/v1` summaries to executor handoffs. | `src/memory.py`, `tests/test_memory.py` |
| `omh runtime wrapper` | Lets wrappers record what they actually observed after dispatch. | `src/runtime/artifacts.py`, `README.md` |
| `omh runtime observe` | Records metadata-only `runtime_observation/v1` events for Hermes/OMX/OMO/OMC runtime handoffs: runtime start, worktree creation, worker dispatch/result, verification, review, CI, merge-readiness, and merge. | `src/runtime/artifacts.py`, `src/runtime/records.py`, `tests/test_cli.py`, `tests/test_runtime_artifacts.py` |
| `omh runtime review`, `omh runtime ci`, `omh runtime merge` | Records observed review, CI, merge-readiness, and merge evidence under the run ledger. | `src/runtime/artifacts.py`, `src/runtime/records.py`, `tests/test_cli.py` |
| `omh runtime validate/export` | Validates and exports local evidence without storing prompt bodies by default. | `src/runtime/artifacts.py`, `tests/test_runtime_artifacts.py` |
| `examples/wrapper-golden/` | Provides platform-neutral golden chat responses for wrapper button/thread/status UX. | `examples/wrapper-golden/status-ladder.json`, `tests/test_wrapper_golden_examples.py` |

The strongest existing path is:

1. A Discord or Slack wrapper receives a plain user message.
2. The wrapper runs `omh chat interact` and renders the returned
   `chat_response/v1` in the original channel or thread.
3. If the wrapper needs restart recovery, it records the turn with
   `omh chat session start`.
4. For planning-shaped work, the wrapper presents the draft plan and records
   accept/revise/cancel decisions with `omh chat session`.
5. For accepted implementation-shaped work, the wrapper records executor or
   runtime selection. Codex selection prepares a lifecycle handoff and links
   the session to the runtime run id; Claude Code and generic agents prepare a
   prompt-only handoff; Hermes/OMX/OMO/OMC prepare a runtime handoff without a
   lifecycle run. Runtime handoffs now include runtime-specific templates and a
   `runtime_observation/v1` contract so wrappers know exactly which events must
   be observed later.
6. The wrapper renders executor-session buttons instead of asking the user to
   type backend commands. When it observes Open in Codex, Attach session, Record
   completed, Record blocked, or Ask Hermes to verify, it writes
   `executor_session/v1` metadata and derives status lines such as
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
- `omh coding delegate --executor hermes`, `--executor omx-runtime`,
  `--executor omo-runtime`, or `--executor omc-runtime` returns a runtime
  handoff contract with team/swarm, worker-protocol, and worktree guidance, but
  still does not create a lifecycle run.
- Runtime handoff contracts include safe invocation templates such as
  `$ultragoal {message}`, `$team {message}`, `$ultrawork {message}`, or
  Hermes retained coding-skill prompts, plus an observation contract explaining
  how to record what actually happened later.
- `omh runtime observe --run <id>` or `omh runtime observe --session <id>`
  appends one observed, blocked, failed, or not-observed runtime ladder event
  without upgrading missing events into evidence.
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
  - runtime-specific templates when an oh-my or Hermes runtime is selected
  - a runtime observation contract for runtime handoffs
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
   prompt-only handoff, prepares a Hermes/OMX/OMO/OMC runtime handoff, or
   prepares a Codex lifecycle handoff.
3. Runtime handoff templates show the selected runtime what to run, but the
   runtime observation ladder still starts empty.
4. Executor execution is pending, running, blocked, completed, or not observed
   according to wrapper evidence.
5. Review, verification, CI, and merge status stay separate from prepared
   delegation until observed.
6. Status readers evaluate the full run ledger conservatively. A later
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
`start_hermes_coding`, `prepare_worktree`, `start_team`, `start_swarm`,
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
render handoff, execution, verification, review, CI, merge-ready, and merged
steps without parsing prose.

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
