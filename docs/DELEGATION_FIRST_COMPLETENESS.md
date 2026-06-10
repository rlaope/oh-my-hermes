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
| `omh chat session` | Persists metadata-only chat session decisions, executor selection, plan acceptance/revision/cancel state, prompt-only handoffs, and accepted Codex lifecycle links. | `src/wrapper/sessions.py`, `tests/test_wrapper_sessions.py`, `tests/test_cli.py` |
| `omh chat route` | Deterministically routes plain chat into a workflow decision before wrapper dispatch. | `src/routing/chat.py`, `tests/test_cli.py` |
| `omh hermes plan` | Produces Hermes-facing plan scaffolds and wrapper contracts under `.hermes/plans`. | `src/hermes_planning.py`, `docs/ARCHITECTURE.md` |
| `omh coding delegate` | Prepares metadata-only coding handoffs, executor-choice contracts, and prompt-only payloads without overclaiming execution. | `src/coding_delegation.py`, `src/runtime/artifacts.py` |
| `omh coding lifecycle` | Tracks Codex-selected handoff dispatch, executor result, verification, and reportable status from existing runtime evidence. | `src/wrapper/lifecycle.py`, `tests/test_coding_lifecycle.py`, `tests/test_cli.py` |
| `omh memory inspect/pack/apply` | Reviews OMH-local and wrapper-supplied context, creates `memory_review_card/v1`, and attaches only conflict-free `handoff_context_pack/v1` summaries to executor handoffs. | `src/memory.py`, `tests/test_memory.py` |
| `omh runtime wrapper` | Lets wrappers record what they actually observed after dispatch. | `src/runtime/artifacts.py`, `README.md` |
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
5. For accepted implementation-shaped work, the wrapper records executor
   selection. Codex selection prepares a lifecycle handoff and links the session
   to the runtime run id; non-Codex selection prepares a prompt-only handoff
   without a lifecycle run.
6. Separate wrapper/runtime evidence is required before OMH can say execution,
   review, verification, CI, merge, or merge-readiness was observed.

## Hermes Surface Readiness

| Priority | Focus | Why it matters | Target story |
| --- | --- | --- | --- |
| P0 | Hermes Agent consumes OMH contracts. | OMH should read as a Hermes-native capability layer, not as a separate bot product. | Keep OMH focused on fixture-backed chat contracts and local status artifacts. |
| P1 | Hermes-facing examples should stay concrete. | Golden JSON locks the wrapper contract, but operators still need examples for rendering replies, actions, status cards, and thread keys. | Add fixture-backed examples that show chat UX without implying missing platform code. |
| P2 | Run-backed lifecycle reporting is Codex-only in Phase 1. | Other executor targets are supported as prompt-only handoffs until a tested lifecycle contract exists. | Generalize only after another executor contract exists. |

## First Implementation Contract

The completed deterministic feature makes executor selection explicit without
launching any coding executor from `omh`.

Expected behavior:

- `omh coding delegate` continues to work for generic wrappers.
- `omh coding delegate --executor choose` returns a human-in-the-loop executor
  choice contract.
- `omh coding delegate --executor codex` returns a dispatch-capable Codex
  lifecycle handoff that can be tracked through `omh coding lifecycle`.
- `omh coding delegate --executor claude-code`, `--executor omx-runtime`,
  `--executor omo-runtime`, `--executor omc-runtime`, or `--executor generic`
  returns a prompt-only handoff that does not create a lifecycle run.
- The payload names the selected executor target and includes:
  - executor target and handoff mode
  - a prompt template or instruction payload for the selected executor
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
2. OMH either asks the user to choose an executor, prepares a prompt-only
   handoff, or prepares a Codex lifecycle handoff.
3. Executor execution is pending, running, blocked, completed, or not observed
   according to wrapper evidence.
4. Review, verification, CI, and merge status stay separate from prepared
   delegation until observed.
5. Status readers evaluate the full run ledger conservatively. A later
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
`copy_prompt_handoff`, `send_to_executor`, `show_status`,
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
  selected executor as the main coding owner for implementation work, while
  preserving Codex-only lifecycle tracking in Phase 1.
- Runtime validation remains local-only and deterministic.
