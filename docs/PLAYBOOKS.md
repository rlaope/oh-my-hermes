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
omh playbook inspect request-to-handoff
omh playbook recommend "I want to safely add a feature to this repo"
omh playbook recommend "research latest official sources"
omh playbook recommend "prepare weekly ops review from customer feedback and release risks"
omh playbook recommend "take this product idea from plan to deploy and monitor safely"
omh playbook recommend "run a CTO loop for roadmap architecture tradeoffs delivery risk and release readiness"
omh playbook recommend "deploy and monitor this release with rollback and health checks"
```

Each command returns JSON. The output is meant for wrappers, docs, demos, and
maintainers who need to understand the product pipeline without reading source
files.

## Included Playbooks

| Playbook | Use When | Primary Shape |
| --- | --- | --- |
| `request-to-handoff` | A user sends a natural request and needs the first role-owned next action. | Route request -> select role -> plan or prepare -> handoff or retain -> status card. |
| `safe-feature-change` | A user wants a safe feature, bug fix, or refactor flow. | Recommend -> plan -> accept -> coding handoff -> status card. |
| `source-backed-research` | A user needs current, official, comparative, or citation-backed evidence. | Clarify scope -> gather sources -> synthesize -> report confidence. |
| `research-to-strategy-brief` | A user wants business or customer evidence shaped into strategy. | Scope research -> evidence table -> meeting topics -> strategy options -> decision record. |
| `meeting-prep-to-record` | A user wants context turned into a meeting agenda and record template. | Context -> agenda -> prompts -> decisions needed -> record template. |
| `feedback-triage` | A user brings customer feedback, bug signals, or feature asks. | Source boundary -> clusters -> severity/opportunity -> next workflow. |
| `weekly-ops-review` | A user wants a recurring status, risk, blocker, and priority review. | Scope -> observed status -> risks/blockers -> priorities -> follow-ups. |
| `market-scan-to-strategy` | A user wants competitor or market evidence shaped into strategy. | Scope scan -> evidence matrix -> implications -> strategy brief. |
| `deep-interview-to-plan` | A broad goal lacks scope, non-goals, or acceptance criteria. | One question -> clarified brief -> plan -> decision gate. |
| `local-pipeline-buildout` | A maintainer wants a repeatable local process for recurring work. | Catalog route -> wrapper contract -> plan gate -> lifecycle status. |
| `idea-to-deploy` | A user wants a product or app idea to feel like a full delivery loop. | Idea -> decision -> plan -> handoff -> verification/release -> deploy/monitor status. |
| `cto-loop` | A user wants CTO/PM-style operating cadence and decision quality. | Signals -> risks -> architecture tradeoffs -> decision -> follow-up handoffs -> status. |
| `deploy-and-monitor` | A user wants release operations and monitoring status without OMH running infrastructure. | Release scope -> checks -> deploy decision -> monitor signals -> rollback gate -> post-deploy record. |
| `release-readiness-review` | A change needs public-facing quality, QA, CI, or merge-readiness review. | Review -> QA -> CI/status -> merge-readiness report. |

## Ownership Boundary

Playbooks deliberately separate ownership:

- Wrappers own platform UX: buttons, threads, message edits, credentials, and
  posting.
- Hermes owns conversation, clarification, source-backed research, planning,
  and status narration.
- OMH owns deterministic local contracts, playbook selection, prepared handoff
  payloads, and metadata-only evidence records.
- Selected coding executors own main coding work after dispatch or prompt
  handoff.

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

The top playbook is `request-to-handoff`. A wrapper can show why that flagship
path was chosen, name the responsible role, keep handoff disabled until plan
acceptance, then show executor selection, `Send to executor`, prompt handoff,
and `Show status` actions based on the configured executor profile. `Send to
Codex` is only a compatibility alias when the Codex lifecycle profile is
selected.

The user-facing improvement is simple: the user describes the work naturally,
and the wrapper turns it into the right pipeline without exposing shell
commands.

For business work, a prompt like:

```text
결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘
```

routes to `feedback-triage` instead of a coding handoff. The wrapper can show
that Hermes will classify feedback, rank severity or opportunity, and recommend
the next workflow. It should not show executor actions unless the user later
accepts a plan with explicit code work.

For app operations, a prompt like:

```text
take this product idea from plan to deploy and monitor safely
```

routes to `idea-to-deploy`. The wrapper can show one complete stage rail:
shape idea, record the decision gate, draft the delivery plan, prepare a
selected executor handoff if code is needed, check verification and release
readiness, then record deploy and monitor status. This feels like a finished
product loop to the operator, but deploy, health, rollback, and monitoring stay
unobserved until the wrapper or operator records evidence.

Leadership and release operation prompts are similarly explicit:

```text
run a CTO loop for roadmap architecture tradeoffs delivery risk and release readiness
deploy and monitor this release with rollback and health checks
```

`cto-loop` gives Hermes a CTO/PM-style operating cadence without claiming
hidden role agents ran. `deploy-and-monitor` gives Hermes a release checklist,
go/no-go decision, health-signal watchlist, rollback gate, and post-deploy
status boundary without making OMH an infrastructure executor.
