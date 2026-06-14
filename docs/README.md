# Documentation

This directory is the public operating map for oh-my-hermes.

Read `docs/DIRECTION.md` first when a change could affect product identity,
wrapper behavior, planning quality, coding delegation, or public claims. Read
`AGENTS.md` alongside it when changing code in this repository; it is the
repo-local contract for Codex agents working here.

## Reading Paths

| Goal | Read |
| --- | --- |
| Understand what OMH is and is not | [Direction](DIRECTION.md) |
| Understand module boundaries and local artifacts | [Architecture](ARCHITECTURE.md) |
| Compare common oh-my runtime axes and OMH gaps | [Parity Matrix](PARITY.md) |
| Understand chat wrapper UX, sessions, and handoffs | [Delegation-First Completeness](DELEGATION_FIRST_COMPLETENESS.md) |
| Review stale local context and executor handoff packs | [Memory Context Review](MEMORY_CONTEXT.md) |
| Operate a Hermes-agent wrapper safely | [Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md) |
| Install from an AI-agent protocol | [Agent Install Protocol](../INSTALL_FOR_AGENTS.md) |
| Understand responsibility roles and operating models | [Role Surface](ROLES.md) |
| Choose a situation-level pipeline | [Playbooks](PLAYBOOKS.md) |
| See Discord-style wrapper responses | [Chat Wrapper Examples](CHAT_WRAPPER_EXAMPLES.md) |
| Render workflow quality gates in wrappers | [Harness Quality Contract](HARNESS_QUALITY.md) |
| Install Hermes-native skills or bootstrap managed skills | [Installation](INSTALLATION.md) |
| Run deterministic backend demos | [`omh demo orchestration`](../README.md#backend--operator-surface) and [fixture shims](../examples) |
| See realistic user-facing flows | [Application Cases](APPLICATION_CASES.md) |
| Check generated skill and harness metadata | [Workflow Reference](WORKFLOWS.md) |
| Prepare or verify a release | [Release](RELEASE.md) |
| Track public sequencing | [Roadmap](ROADMAP.md) |
| Review the public website source | [GitHub Pages site](../site/index.html) |

## Direction Summary

OMH is a Hermes-native wrapper orchestration layer.

The product should make chat surfaces feel capable without hiding who did what.
Hermes should own intake, clarification, research, business briefs, meeting
prep, feedback triage, operating records, report packages, reliability reviews,
app operation loops, planning, status narration, and handoff UX. The selected
coding executor should own main coding work when work leaves Hermes. OMH should
own the deterministic local contract between those worlds: generated skill
guidance, playbooks, wrapper sessions, prepared handoff payloads, and evidence
records.

The most important boundary is prepared versus observed evidence. A prepared
handoff is useful, but it is not execution, review, CI, merge readiness, or a
merge.

Runtime handoffs for Hermes/OMX/OMO/OMC use `runtime_observation/v1` records
when wrappers or operators later observe runtime start, worktree, worker,
verification, review, CI, or merge ladder events.

Executor session buttons use `executor_session/v1` records when a wrapper
observes Open in Codex, Open in Claude Code, Attach session, Record completed,
Record blocked, or Ask Hermes to verify. They update chat status without
requiring normal users to type backend commands.

Operating models are setup defaults for Hermes collaboration posture. They
should not be described as installed agents unless a separate profile pack is
selected.

## Flagship Command Set Families

![OMH flagship command sets poster](../assets/omh-flagship-workflows-poster.png)

| Family | What Hermes owns | Plain request |
| --- | --- | --- |
| `deep-interview` / `ralplan` / `ultragoal` / `loop` | Turn vague intent into a concrete goal, accepted plan, execution-ready path, or direct ambitious goal loop. | "Make onboarding feel smoother." |
| `feedback-triage` / `research-brief` / `strategy-brief` | Run non-coding company and product operating workflows for customer signals, evidence, meetings, and strategy. | "Payment failures keep coming up." |
| `operating-rhythm` / `report-package` / `reliability-review` | Keep operating cadence, report packages, and service reliability review in independent artifact-backed lanes. | "Prepare meeting history, the monthly report, and the incident review." |
| `idea-to-deploy` / coding handoff / executor selection | Prepare scoped handoffs for Codex, Claude Code, another runtime, or Hermes coding skills while preserving observed-evidence boundaries. | "Turn this issue into a PR-ready plan and hand it to implementation." |

## Documentation Contracts

- Public docs should describe local deterministic behavior, not hidden runtime
  magic.
- Chat users should remain command-agnostic. Wrapper docs should describe
  buttons, threads, status, and handoff states rather than asking end users to
  run shell commands.
- Installation docs should lead with Hermes skill tap/install when available.
  `omh setup` should be described as a bootstrap, repair, validation, and
  wrapper/backend path that creates the same Hermes-visible skill state.
- Operator runbooks should use document titles, not command-like names, when
  they describe wrapper responsibilities and status evidence.
- Demo and shim examples should stay fixture-backed, deterministic, and
  Hermes Agent-facing unless a scoped integration explicitly opts into a
  different runtime surface.
- Playbook docs should describe situation-level pipelines for company work, app
  operation loops such as idea-to-deploy / CTO loop / deploy-and-monitor,
  operations artifacts such as operating-rhythm / report-package /
  reliability-review, and coding handoffs, plus ownership boundaries, rather
  than becoming a second skill catalog.
- Role docs should describe responsibility lanes, not runtime agents. A role can
  explain the next action, but it cannot prove execution without matching
  observed evidence.
- Operating model docs should stay lighter than team profile pack docs. They
  record routing and narration defaults only.
- Coding-heavy requests should be described as delegated work unless there is
  observed evidence that a coding executor actually ran.
- Generated workflow docs should come from `src/skills/catalog.py`; update the
  catalog before refreshing generated references.
- Harness quality gates should stay machine-readable through
  `harness_quality/v1` instead of being prose-only wrapper behavior.
- Harness catalog changes should pass `omh harness validate`, and user-facing
  harness examples should stay backed by conformance tests.
- Release checks should include `omh release checklist --json`,
  `omh release hermes-smoke`, and installed command smoke (`omh --help`); use
  `--live` only from the target Hermes profile when an operator wants real
  install evidence.
- Runtime and wrapper docs should preserve the separation between wrapper
  session state and run-level evidence.
- Parity docs should map common oh-my runtime capability axes to OMH's
  Hermes-native evidence model instead of promising hidden workers, worktrees,
  MCP tools, or plugin runtime load without observation.
- Goal execution docs should describe `.omh/goals` metadata-only ledgers,
  `goal_completion_gate/v1`, `goal_status_card/v1`, and
  `goal_continuation/v1` as wrapper contracts that name the next action before
  completion is claimed.
- Loop docs should describe `.omh/loops` metadata-only `loop_cycle/v1` state,
  `loop_runtime/v1` tick queues, `verification_plan` metadata,
  `failure_mode_summary` warnings, small-loop guidance, and
  `loop_status_card/v1` next actions as orchestration evidence only; goal
  completion still belongs to linked `goal_ledger/v1` evidence.
- Memory/context docs should state that OMH reviews local or wrapper-supplied
  context only; it does not read or mutate opaque Hermes internal memory.
- The GitHub Pages site should stay a short public entry point that links back
  to this docs set instead of becoming a second source of truth.

## Update Checklist

When changing docs, check whether the same claim needs to be updated in:

- [README](../README.md)
- [Direction](DIRECTION.md)
- [Architecture](ARCHITECTURE.md)
- [Parity Matrix](PARITY.md)
- [Delegation-First Completeness](DELEGATION_FIRST_COMPLETENESS.md)
- [Memory Context Review](MEMORY_CONTEXT.md)
- [Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md)
- [Role Surface](ROLES.md)
- [Agent Install Protocol](../INSTALL_FOR_AGENTS.md)
- [Playbooks](PLAYBOOKS.md)
- [Harness Quality Contract](HARNESS_QUALITY.md)
- [Application Cases](APPLICATION_CASES.md)
- [Workflow Reference](WORKFLOWS.md)
- [GitHub Pages site](../site/index.html)
- [AGENTS](../AGENTS.md)

Run the focused documentation checks before calling the change complete:

```sh
PYTHONPATH=tests uv run python -m unittest tests/test_router_content.py -v
uv run python -m src.cli harness validate
uv run python -m src.cli docs workflows --check
git diff --check
```
