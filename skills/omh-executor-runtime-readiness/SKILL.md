---
name: omh-executor-runtime-readiness
description: [omh] Executor runtime readiness - compare Codex, Claude Code, Hermes coding, and oh-my runtimes by tools and handoff mode; use external-connector-readiness for a named plugin or API, and toolbelt-readiness for the whole capability inventory. Use when the user says: executor-runtime-readiness, executor readiness, runtime readiness, codex readiness, claude code readiness, hermes coding readiness, executor tools, missing tools.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, executor-readiness]
    category: executor-readiness
    phase: runtime-selection
    role: handoff-guide
    quality_tier: workflow-surface-gated
---

# Executor Runtime Readiness

This is a Hermes-native `executor-runtime-readiness` workflow skill.

## Why This Exists

`executor-runtime-readiness` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: executor-runtime-readiness can this task run in Codex, Claude Code, or Hermes coding?
- Expected behavior: Produce `prepare_executor_runtime_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: executor-runtime-readiness claim Codex already started the session.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- The selected coding or runtime owner is named before any implementation claim.
- Prepared handoff, dispatch, execution, verification, review, CI, and merge states are separated.
- The final status cites observed runtime evidence or keeps the work prepared_not_observed.
- When Hermes is the selected coding owner, use `hermes_coding_harness/v1` to keep builder, verifier, reviewer, docs, and PR lanes separate.
- Report the current harness stage, owner, next action, and missing evidence without claiming PR creation, review, CI, merge-readiness, or merge until matching runtime observations exist.

## Recovery Notes

- If the selected executor is unavailable, ask for Codex, Claude Code, Hermes, or another runtime before retrying.
- If dispatch or result evidence is missing, keep the handoff prepared_not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `ultrawork`, `+6 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when a user may choose Codex, Claude Code, Hermes coding, or another runtime and needs tool/credential gaps before handoff.

    Strong routing signals: `executor-runtime-readiness`, `executor readiness`, `runtime readiness`, `codex readiness`, `claude code readiness`, `hermes coding readiness`, `executor tools`, `missing tools`, `missing runtime tools`, `runtime tools`, `coding agent readiness`, `coding runtime`, `handoff mode`, `handoff readiness`, `codex or claude`, `codex vs claude`, `codex tools`, `claude code tools`, `hermes coding`, `agent runtime`, `subagent readiness`, `worktree readiness`, `codex로 넘길지 claude`, `claude code로 넘길지 codex`, `codex랑 claude`, `claude code 중`, `넘길지 codex`, `넘길지 claude`, `runtime migration`, `omx`, `omc`, `omo`, `코덱스`, `클로드 코드`, `헤르메스 코딩`, `코딩 에이전트`, `서브에이전트`, `작업트리`, `준비성`, `실행 런타임`, `어떤 런타임`, `런타임으로 넘겨`

## Catalog Metadata

Category: `executor-readiness`
Phase: `runtime-selection`
Hermes role: `handoff-guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Delegation transparency:

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]` — the user must see WHAT was asked, not just that something was.
- Name every delegated or parallel lane's model and reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; write the literal `unknown` when the host does not expose a value, never empty parentheses, and carry token and elapsed figures the same way.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it — a plain-text one-shot that hides its session id strands the work when the run stalls or times out.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and the home-directory `settings.local.json` is not a file Claude Code reads — user scope is `settings.json` under `~/.claude` and project scope is `settings.local.json` under `<dispatch cwd>/.claude` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- executor-runtime-readiness/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- executor-runtime-readiness/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- Runtime readiness is not executor dispatch, plugin load, tool invocation, repository mutation, review, CI, or merge evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `executor-runtime-readiness`.

```sh
omh runtime record --skill executor-runtime-readiness --harness executor-runtime-readiness --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.
