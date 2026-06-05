# Delegation-First Completeness

## Direction

OMHM should raise Hermes toward a mature workflow-layer experience without
pretending that Hermes is the primary coding executor.

The intended boundary is:

- Hermes owns chat intake, clarification, planning, routing, status narration,
  and user-facing workflow continuity.
- Codex-like coding agents own main implementation, code review, verification,
  and merge-readiness work.
- `omh` owns deterministic local contracts between those surfaces: it prepares
  handoffs, records metadata-only evidence, and keeps observed execution
  separate from prepared intent.

This direction keeps OMHM useful for Discord, Slack, and hosted Hermes wrappers
while preserving the current project constraints: no hidden Hermes core patching,
no LLM/API/network calls inside `omh`, and no runtime claim unless local wrapper
evidence exists.

## Current Local Surfaces

| Surface | Current role | Evidence |
| --- | --- | --- |
| `omh chat interact` | Composes route, plan, delegation, and status into one wrapper-native `chat_interaction/v1` response for Discord, Slack, and hosted Hermes adapters. | `src/wrapper_contract.py`, `tests/test_wrapper_contract.py`, `tests/test_cli.py` |
| `omh chat route` | Deterministically routes plain chat into a workflow decision before wrapper dispatch. | `src/chat_router.py`, `tests/test_cli.py` |
| `omh hermes plan` | Produces Hermes-facing plan scaffolds and wrapper contracts under `.hermes/plans`. | `src/hermes_planning.py`, `docs/ARCHITECTURE.md` |
| `omh coding delegate` | Prepares metadata-only coding handoffs and records `prepared_not_observed` evidence. | `src/coding_delegation.py`, `src/runtime_artifacts.py` |
| `omh coding lifecycle` | Tracks Codex handoff dispatch, executor result, verification, and reportable status from existing runtime evidence. | `src/coding_lifecycle.py`, `tests/test_coding_lifecycle.py`, `tests/test_cli.py` |
| `omh runtime wrapper` | Lets wrappers record what they actually observed after dispatch. | `src/runtime_artifacts.py`, `README.md` |
| `omh runtime validate/export` | Validates and exports local evidence without storing prompt bodies by default. | `src/runtime_artifacts.py`, `tests/test_runtime_artifacts.py` |

The strongest existing path is:

1. A Discord or Slack wrapper receives a plain user message.
2. The wrapper runs `omh chat interact` and renders the returned
   `chat_response/v1` in the original channel or thread.
3. For planning-shaped work, the wrapper presents the draft plan and waits for
   acceptance before preparing a handoff.
4. For accepted implementation-shaped work, the wrapper starts a Codex lifecycle
   handoff and dispatches that handoff outside OMHM.
5. Separate wrapper/runtime evidence is required before OMHM can say execution,
   review, verification, CI, merge, or merge-readiness was observed.

## Completeness Gaps

| Priority | Gap | Why it matters | Target story |
| --- | --- | --- | --- |
| P0 | Actual Discord and Slack adapters are not implemented in this repository. | The core contract is ready, but platform auth, retries, edits, and posting still belong to wrapper projects. | Build example adapter shims only after transport dependencies and packaging are approved. |
| P0 | Review, CI, and merge evidence are still represented as wrapper-observed gaps rather than first-class records. | Coding lifecycle reports must keep blocking final completion for review-heavy tasks. | Add explicit review/CI/merge observation records or document the wrapper evidence shape. |
| P1 | Plan acceptance is represented by wrapper actions, but no persisted acceptance event exists yet. | Wrappers need durable recovery when a platform process restarts between plan acceptance and Codex dispatch. | Add a metadata-only plan acceptance record keyed by `thread_key` and `run_id`. |
| P1 | Chat response examples are schema-level, not transport-level. | Adapter authors need clear button/thread/status update examples without duplicating policy. | Add Discord/Slack pseudocode fixtures and golden JSON examples. |
| P2 | Lifecycle reporting is Codex-oriented only. | Future executor targets may need the same state machine without weakening the Codex default. | Generalize only after another executor contract exists. |

## First Implementation Contract

The completed deterministic feature makes Codex the explicit coding executor
target without launching Codex from `omh`.

Expected behavior:

- `omh coding delegate` continues to work for generic wrappers.
- A wrapper can request a Codex-oriented handoff payload through
  `omh coding delegate --executor codex` or track it through
  `omh coding lifecycle`.
- The payload names Codex as the executor target and includes:
  - executor target and handoff mode
  - a prompt template or instruction payload for Codex
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

- Do not invoke Codex, Hermes, GitHub, Discord, Slack, or any network service.
- Do not change Hermes core behavior.
- Do not claim implementation, review, CI, or merge evidence.
- Do not store raw prompt bodies unless an existing explicit include flag is
  used for stdout-only wrapper dispatch.

## Wrapper Narrative Contract

Wrappers should be able to express the chain in human terms:

1. Hermes received and clarified or planned the request.
2. OMHM prepared a Codex coding handoff.
3. Codex execution is pending, running, blocked, completed, or not observed
   according to wrapper evidence.
4. Review, verification, CI, and merge status stay separate from prepared
   delegation until observed.

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
`prepare_handoff`, `send_to_codex`, `show_status`, and `cancel`. Action labels
remain product-level labels; they do not expose CLI commands, argv arrays, or
shell text.

## Success Criteria

- The implementation adds a wrapper-native chat interaction contract while
  preserving existing `coding_delegation/v1` callers.
- Tests prove no raw prompt body is stored in runtime records by default.
- Tests prove hostile shell text remains a placeholder in any argv/template
  contract.
- README and architecture docs describe Hermes as the orchestrator and Codex as
  the main coding executor for implementation work.
- Runtime validation remains local-only and deterministic.
