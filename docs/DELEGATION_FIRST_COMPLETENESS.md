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
| `omh chat route` | Deterministically routes plain chat into a workflow decision before wrapper dispatch. | `src/chat_router.py`, `tests/test_cli.py` |
| `omh hermes plan` | Produces Hermes-facing plan scaffolds and wrapper contracts under `.hermes/plans`. | `src/hermes_planning.py`, `docs/ARCHITECTURE.md` |
| `omh coding delegate` | Prepares metadata-only coding handoffs and records `prepared_not_observed` evidence. | `src/coding_delegation.py`, `src/runtime_artifacts.py` |
| `omh runtime wrapper` | Lets wrappers record what they actually observed after dispatch. | `src/runtime_artifacts.py`, `README.md` |
| `omh runtime validate/export` | Validates and exports local evidence without storing prompt bodies by default. | `src/runtime_artifacts.py`, `tests/test_runtime_artifacts.py` |

The strongest existing path is:

1. A Discord or Slack wrapper receives a plain user message.
2. The wrapper runs `omh chat route`.
3. For planning-shaped work, the wrapper runs `omh hermes plan --record`.
4. After plan acceptance, the wrapper uses the plan `wrapper_contract` to run
   `omh coding delegate --record`.
5. Separate wrapper/runtime evidence is required before OMHM can say execution,
   review, verification, or merge-readiness was observed.

## Completeness Gaps

| Priority | Gap | Why it matters | Target story |
| --- | --- | --- | --- |
| P0 | Codex is implied as a generic `coding-agent`, not named as an executor target. | Wrappers still need to invent the Codex handoff shape, which weakens interoperability. | Implement Codex executor handoff contract. |
| P0 | Prepared handoff and observed executor status are not connected by a Codex-oriented contract. | A wrapper cannot cleanly narrate "Hermes prepared this, Codex is now responsible, here is what is observed." | Expose wrapper-facing delegation status evidence. |
| P1 | Planning quality is good locally, but the post-plan path should expose stricter executor acceptance fields. | Codex handoff quality should be closer to high-discipline implementation briefs: scope, constraints, verification, review, and stop condition. | Implement Codex executor handoff contract. |
| P1 | Runtime exports validate local evidence, but do not yet summarize a delegation chain as a user-facing status. | Chat wrappers need concise status messages that do not overclaim. | Expose wrapper-facing delegation status evidence. |
| P2 | Roadmap still speaks broadly about integration rather than delegation-first product completeness. | Future contributors may add Hermes-internal coding behavior instead of strengthening the safer contract boundary. | Complete docs, tests, review, and PR gate. |

## First Implementation Contract

The next deterministic feature should make Codex the explicit coding executor
target without launching Codex from `omh`.

Expected behavior:

- `omh coding delegate` continues to work for generic wrappers.
- A wrapper can request a Codex-oriented handoff payload, either through a new
  option on the existing command or a narrowly named subcommand.
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

## Success Criteria

- The next implementation PR adds an explicit Codex handoff contract while
  preserving existing `coding_delegation/v1` callers.
- Tests prove no raw prompt body is stored in runtime records by default.
- Tests prove hostile shell text remains a placeholder in any argv/template
  contract.
- README and architecture docs describe Hermes as the orchestrator and Codex as
  the main coding executor for implementation work.
- Runtime validation remains local-only and deterministic.
