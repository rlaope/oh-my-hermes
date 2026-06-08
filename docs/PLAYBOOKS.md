# Playbooks

Playbooks are situation-level pipelines for chat-facing Hermes wrappers.

Skills answer "which workflow guidance should Hermes use?" Playbooks answer
"what should the whole wrapper experience do next, and which layer owns each
stage?"

They are local, deterministic, and transport-free. A Discord, Slack, or hosted
adapter can use playbooks to render a natural request as a plan, research lane,
status card, or coding handoff without requiring the user to know command
names.

## Commands

```sh
omh playbook list
omh playbook inspect safe-feature-change
omh playbook recommend "I want to safely add a feature to this repo"
omh playbook recommend "research latest official sources"
omh playbook recommend "prepare weekly ops review from customer feedback and release risks"
```

Each command returns JSON. The output is meant for wrappers, docs, demos, and
maintainers who need to understand the product pipeline without reading source
files.

## Included Playbooks

| Playbook | Use When | Primary Shape |
| --- | --- | --- |
| `safe-feature-change` | A user wants a safe feature, bug fix, or refactor flow. | Recommend -> plan -> accept -> coding handoff -> status card. |
| `source-backed-research` | A user needs current, official, comparative, or citation-backed evidence. | Clarify scope -> gather sources -> synthesize -> report confidence. |
| `research-to-strategy-brief` | A user wants business or customer evidence shaped into strategy. | Scope research -> evidence table -> meeting topics -> strategy options -> decision record. |
| `meeting-prep-to-record` | A user wants context turned into a meeting agenda and record template. | Context -> agenda -> prompts -> decisions needed -> record template. |
| `feedback-triage` | A user brings customer feedback, bug signals, or feature asks. | Source boundary -> clusters -> severity/opportunity -> next workflow. |
| `weekly-ops-review` | A user wants a recurring status, risk, blocker, and priority review. | Scope -> observed status -> risks/blockers -> priorities -> follow-ups. |
| `market-scan-to-strategy` | A user wants competitor or market evidence shaped into strategy. | Scope scan -> evidence matrix -> implications -> strategy brief. |
| `deep-interview-to-plan` | A broad goal lacks scope, non-goals, or acceptance criteria. | One question -> clarified brief -> plan -> decision gate. |
| `local-pipeline-buildout` | A maintainer wants a repeatable local process for recurring work. | Catalog route -> wrapper contract -> plan gate -> lifecycle status. |
| `release-readiness-review` | A change needs public-facing quality, QA, CI, or merge-readiness review. | Review -> QA -> CI/status -> merge-readiness report. |

## Ownership Boundary

Playbooks deliberately separate ownership:

- Wrappers own platform UX: buttons, threads, message edits, credentials, and
  posting.
- Hermes owns conversation, clarification, source-backed research, planning,
  and status narration.
- OMH owns deterministic local contracts, playbook selection, prepared handoff
  payloads, and metadata-only evidence records.
- Codex-like executors own main coding work after dispatch.

Prepared handoff remains `prepared_not_observed` until the wrapper or operator
records dispatch and result evidence. A playbook recommendation is not execution evidence.
It is also not plan acceptance, review, CI, merge-readiness, or merge evidence.

## Wrapper Rendering

Wrappers should render these fields directly:

| Field | Purpose |
| --- | --- |
| `recommendations[].id` | Stable playbook id for buttons, analytics, and session state. |
| `recommendations[].pipeline` | Ordered high-level stages to show as a progress rail. |
| `recommendations[].wrapper_actions` | Platform-neutral action ids for the current stage. |
| `recommendations[].retained_by_hermes` | Work that should stay with Hermes. |
| `recommendations[].delegated_to_executor` | Work that should become an explicit executor handoff. |
| `recommendations[].not_evidence_until_observed` | Claims the wrapper must not make before evidence exists. |

Use `omh playbook inspect <id>` when the wrapper needs full stage-level
contracts, evidence requirements, and acceptance criteria.

## Example

```sh
omh playbook recommend "I want to safely add a feature to this repo"
```

The top playbook is `safe-feature-change`. A wrapper can show a planning-first
response, keep handoff disabled until plan acceptance, then show `Send to
Codex` and `Show status` actions after a prepared handoff exists.

The user-facing improvement is simple: the user describes the work naturally,
and the wrapper turns it into the right pipeline without exposing shell
commands.

For business work, a prompt like:

```text
결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘
```

routes to `feedback-triage` instead of a coding handoff. The wrapper can show
that Hermes will classify feedback, rank severity or opportunity, and recommend
the next workflow. It should not show `Send to Codex` unless the user later
accepts a plan with explicit code work.
