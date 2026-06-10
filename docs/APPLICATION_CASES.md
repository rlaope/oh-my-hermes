# Application Cases

This guide documents the first three proof cases for `oh-my-hermes-agent`.
Each case is designed to show visible skill impact without claiming hidden
Hermes runtime behavior.

## Case 1: Coding Request Handling

### Setup

Install the Hermes skill pack through Hermes' native skill surface:

```sh
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes
```

If the deployment needs the managed bootstrap path, install and verify the same
Hermes-visible state through OMH:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
omh doctor
```

Restart Hermes Agent after installation so it can reload its configured skill
directories.

### User Prompt Shape

Ask Hermes for a concrete coding task, such as a focused bug fix, review, or
small feature request.

Strong signals include:

- a file path
- an error message
- a function or module name
- explicit verification requirements

### Expected Hermes-Facing Behavior

Hermes should use the installed `oh-my-hermes` router guidance and the
`coding-handling` harness to keep the response scoped around:

- target behavior
- relevant repo context
- changed files
- verification evidence
- remaining risks

If the prompt is too broad, the harness directs Hermes to ask one concise
clarification question before editing.

### Verification

After installation, inspect the managed skill list:

```sh
omh list
```

For repository development, verify the generated router content through tests:

```sh
python3 -m unittest discover -s tests
```

Artifact-backed verification can be recorded without capturing prompt bodies:

```sh
run_json="$(omh runtime record --skill oh-my-hermes --harness coding-handling --status started)"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed
omh runtime show "$run_id"
```

This proves the workflow was tracked locally while preserving the distinction
between requested review/delegation and delegation that Hermes actually exposed.

### Current Limit

This case verifies installed prompt guidance and generated skill content.
It does not prove that Hermes has a hidden runtime hook or automatic internal
router beyond Hermes' normal skill loading behavior.

## Case 2: Goal, Planning, and Deep Interview Flow

### Setup

Confirm the skill pack is installed through Hermes or registered through the
OMH bootstrap path:

```sh
hermes skills install deep-interview
hermes skills install ralplan
omh setup
omh doctor
```

### User Prompt Shape

Use this flow when the user describes a broad product or coding objective that
needs clarification before execution.

Strong signals include:

- unclear scope
- missing non-goals
- a request to plan before coding
- a long-running objective that needs checkpoints

### Expected Hermes-Facing Behavior

Hermes should use:

- `deep-interview` when intent, boundaries, or decision authority are unclear
- `planning` when requirements are clear enough for sequencing and test shape
- `goal-execution` when the work needs durable checkpoints or finish-until-done
  pressure

The expected output is a clarified brief or plan before implementation starts.
When Hermes lacks a dedicated goal tool, the compatibility contract tells it to
use a file-backed checklist or explicit local ledger.

### Verification

Inspect generated skills after install:

```sh
omh list
```

Repository maintainers can verify generated content through tests:

```sh
python3 -m unittest discover -s tests
```

Artifact-backed verification:

```sh
run_json="$(omh runtime record --skill ultragoal --harness goal-execution --status started)"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed
omh runtime show "$run_id"
```

Use `not_observed` when the active Hermes surface does not expose a separate
goal runner or planner identity.

### Current Limit

This case is prompt-level workflow guidance unless a future Hermes extension
surface provides deeper state or goal integration.

## Case 3: Specialist Harness Flow

### Setup

Install the skill pack through Hermes, or make sure Hermes can read the same
config that `omh apply` updated when using the bootstrap path:

```sh
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes
omh setup
omh doctor
```

For Discord bot deployments, install in the same runtime context that starts
the bot, then restart the bot process.

### User Prompt Shape

Use this flow for work that needs stronger review or a release-quality answer.

Strong signals include:

- architecture or integration risk
- public documentation changes
- user-visible workflow changes
- release or quality-gate language
- requests for critique, QA, or docs review

### Expected Hermes-Facing Behavior

Hermes should shape the work through the representative specialist harnesses:

- `research` for current, official, or source-backed evidence gathering
- `architect` for boundaries, integration choices, and maintainability
- `critic` for consistency, missing checks, and residual risk
- `qa-specialist` for adversarial scenarios and pass/fail evidence
- `docs-specialist` for accurate commands, examples, and limitations

These are quality lanes. They are not proof that Hermes spawned a separate
runtime role unless the active Hermes environment exposes that capability.

### Verification

The router skill should include each specialist harness name, inputs, outputs,
verification expectations, quality tier, evidence ladder, wrapper actions,
overclaim guards, and fallback behavior.

Repository maintainers can verify this with:

```sh
python3 -m unittest discover -s tests
```

Artifact-backed verification:

```sh
run_json="$(omh runtime record --skill code-review --harness critic --status completed)"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed --evidence-ref run.json
omh runtime show "$run_id"
```

If a bot wrapper can observe separate specialist outputs, it can record
`--observed --result completed --participants architect,critic`. Otherwise the
artifact should remain explicit that delegation was not observed.

### Current Limit

If Hermes delegation is unavailable, the harness still improves response
quality by making Hermes run the specialist checks sequentially in the current
conversation.

## Case 4: Situation Playbook Pipeline

### Setup

No additional end-user setup is required beyond Hermes seeing the installed
OMH skills. Wrapper operators can use a working `omh` command to inspect the
same playbook contracts locally.

### User Prompt Shape

Use this flow when a wrapper or maintainer wants to decide the whole pipeline
for a natural request before choosing low-level commands.

Strong signals include:

- a safe feature or refactor request
- a request for current source-backed research
- an ambiguous goal that needs interview before planning
- a recurring process or pipeline buildout
- release-readiness, QA, CI, or merge-readiness review

### Expected Hermes-Facing Behavior

The playbook layer picks a situation-level path above individual skills:

- `safe-feature-change` for plan-first coding handoff
- `source-backed-research` for Hermes-owned research
- `research-to-strategy-brief` for evidence into strategy and meeting topics
- `meeting-prep-to-record` for agendas, discussion prompts, and record templates
- `feedback-triage` for customer signals before roadmap or coding work
- `weekly-ops-review` for status, risks, blockers, priorities, and follow-ups
- `market-scan-to-strategy` for competitor evidence into strategic options
- `deep-interview-to-plan` for ambiguity reduction
- `local-pipeline-buildout` for repeatable wrapper process design
- `idea-to-deploy` for app ideas that need decision, handoff, release, deploy,
  and monitor status in one stage rail
- `cto-loop` for CTO/PM-style roadmap, architecture, delivery risk, release
  readiness, and follow-up cadence
- `deploy-and-monitor` for release checklists, go/no-go, health signals,
  rollback gates, and post-deploy status
- `release-readiness-review` for review, QA, CI, and merge-readiness status

The playbook response names which stages stay with Hermes, which stages become
executor handoffs, and which claims must stay pending until evidence is
observed.

### Verification

Inspect the playbook catalog:

```sh
omh playbook list
omh playbook inspect safe-feature-change
omh playbook recommend "I want to safely add a feature to this repo"
omh playbook recommend "take this product idea from plan to deploy and monitor safely"
omh playbook recommend "run a CTO loop for roadmap architecture tradeoffs delivery risk and release readiness"
omh playbook recommend "deploy and monitor this release with rollback and health checks"
```

Repository maintainers can verify playbook behavior through tests:

```sh
PYTHONPATH=tests python3 -m unittest tests/test_cli.py -v
```

### Current Limit

Playbooks are deterministic local contracts. They do not launch coding
executors or prove that a later stage happened. Runtime status must still come
from observed evidence records.

## Case 5: Company Workflows Without CLI Knowledge

### Setup

Install OMH once through the same Hermes-visible skill path:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh setup
```

Normal users should then talk to Hermes, not manually run `omh recommend` or
`omh playbook recommend`.

### User Prompt Shape

Use this flow for non-coding company work such as:

- customer feedback triage
- business or market research
- strategy memo preparation
- meeting agenda and record preparation
- weekly operating review

Example prompts:

```text
결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘
prepare weekly ops review from customer feedback and release risks
we need a competitor market scan and strategy memo for next week's leadership meeting
```

### Expected Hermes-Facing Behavior

Hermes should use the business workflow skills:

- `research-brief` for source-scoped business research
- `strategy-brief` for options, tradeoffs, and decision notes
- `meeting-brief` for agenda, prompts, decisions needed, and record templates
- `feedback-triage` for customer signal clustering and next-workflow routing
- `ops-review` for evidence-bound status, risks, blockers, and follow-ups

These skills stay Hermes-retained by default. They should not create coding
handoffs, product roadmaps, release claims, or meeting outcomes unless a later
accepted artifact provides the missing evidence.

### Verification

Wrapper operators can inspect the deterministic backend contract:

```sh
omh chat interact --source discord "결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘"
omh coding delegate --executor codex --source discord "prepare weekly ops review from customer feedback and release risks"
```

Expected behavior:

- chat interaction routes to a business workflow such as `feedback-triage` or
  `ops-review`
- coding delegation does not emit `executor_handoff`
- harness quality uses `customer-insight-triage`, `ops-review`,
  `strategy-synthesis`, `meeting-facilitation`, or `business-research` rather
  than `coding-handling`

### Evidence Boundary

OMH supplies deterministic routing, plan, handoff, and status contracts for
Hermes Agent. It still requires observed source evidence before Hermes can
claim data was actually reviewed.

## Grounded UltraQA Scenario Matrix

These scenarios are grounded in deterministic local contract behavior, not
written as aspirational examples. Operators can reproduce each natural message
with:

```sh
omh chat interact --source discord "<message>"
omh playbook recommend "<message>" --limit 1
omh coding delegate --executor codex --source discord "<message>"
```

The purpose of the matrix is to keep Hermes users command-agnostic while giving
wrapper operators a concrete contract result to render.

| Scenario | User message tested | Chat route | Playbook | Coding handoff behavior |
| --- | --- | --- | --- | --- |
| Startup SaaS product triage | `결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘` | `feedback-triage` / `triage_feedback` | `feedback-triage` | No coding handoff is emitted by default; Hermes classifies feedback and recommends the next workflow. |
| OSS issue-to-PR preparation | `이 이슈 PR로 만들 수 있게 정리해줘` | `ralplan` / `present_plan` | `safe-feature-change` | Handoff includes reviewed-plan expectations and verification criteria. |
| AI agent product QA | `쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?` | `ultraqa` / `dispatch_to_workflow` | `release-readiness-review` | No dispatchable executor handoff is emitted from `coding delegate`; QA stays Hermes-retained until code work is accepted. |
| Discord dev-team routing | `이거 위험한 리팩터링 같아` | `ai-slop-cleaner` / `present_plan` | `safe-feature-change` | A selected executor handoff can be prepared for behavior-preserving cleanup after the safe plan. |
| AI coding safety audit | `AI가 했다고 했는데 실제로 뭐 했는지 모르겠다` | `code-review` / `prepare_review_or_followup_handoff` | `release-readiness-review` | Review/fix handoff is separate from observed execution, verification, CI, and merge evidence. |
| Product feature shaping | `온보딩을 더 부드럽게 만들고 싶어` | `deep-interview` / `answer_clarification` | `deep-interview-to-plan` | No coding handoff is emitted; Hermes asks one blocking question before planning. |
| Release gate review | `릴리즈 전에 README claim이 실제 코드와 맞는가, doctor/harness가 통과하는가 봐줘` | `code-review` / `prepare_review_or_followup_handoff` | `release-readiness-review` | Fixes remain executor work; review and validation evidence must be observed separately. |
| Repeated refactor workflow | `레거시 서비스를 위험 분석, 변경 범위 제한, 테스트 전략, Codex 구현, 리뷰, 회귀 테스트 순서로 리팩터링하고 싶어` | `ai-slop-cleaner` / `present_plan` | `safe-feature-change` | Prepared cleanup handoff names scope, tests, review, and regression expectations. |
| Personal multi-agent work hub | `지금은 Hermes가 답할 차례인지, coding handoff를 준비할 차례인지, review gate를 열 차례인지 정리해줘` | `plan` / `present_plan` | `local-pipeline-buildout` | The wrapper can plan the hub contract before any coding executor is needed. |
| Consulting/agency operating template | `고객사 프로젝트별 요구사항 정리, 조사, 구현 handoff, QA, 리뷰, 릴리즈 보고 운영 템플릿이 필요해` | `plan` / `present_plan` | `local-pipeline-buildout` | Handoff is available only after the operator accepts the recurring workflow plan. |

User-facing effect:

- The chat user does not need to decide whether the request is a bug,
  investigation, implementation, release gate, QA scenario, or product shaping
  task.
- Hermes can say why the next step is plan, deep interview, QA, review, or
  handoff preparation without pretending implementation already happened.
- Wrappers can render buttons and status from `chat_response.actions`,
  `next_action`, and `claim_boundary`.
- `prepared_not_observed` remains explicit until dispatch, executor result,
  verification, review, CI, or merge readiness evidence is actually recorded.

## Release Review Checklist

Before using these cases as public release evidence, verify:

- The one-command installer still works.
- `hermes skills tap add rlaope/oh-my-hermes-agent` and
  `hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes`
  are documented as the primary install path when Hermes taps are available.
- `omh setup` reports the managed skill directory, equivalent Hermes install
  intent, and Hermes config registration clearly.
- `omh doctor` reports the managed skill directory as healthy after setup.
- The generated router includes the representative harness registry.
- `omh docs workflows --json` exposes `harness_quality/v1` style quality data
  for wrapper rendering and status decisions.
- `omh playbook recommend` returns situation-level pipelines for safe coding,
  source-backed research, research-to-strategy briefs, meeting prep, feedback
  triage, ops review, app operation loops, local pipeline buildout, and
  release-readiness review.
- The grounded cases above match actual generated skill and playbook behavior.
- Runtime-backed cases above can create `.omh/runtime/runs/<run-id>/`
  artifacts.
- `delegation.json` separates requested delegation from observed delegation.
- `omh probe` output is captured before any native hook, plugin, app, MCP, or
  internal routing claim is made.
- Public docs avoid comparisons to other projects.
- Any real Hermes runtime behavior that could not be automated is listed as a
  manual check.
