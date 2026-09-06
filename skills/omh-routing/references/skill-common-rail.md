# OMH Skill Common Rail

Every generated OMH workflow skill shares this policy. It is kept here once instead of
inside each `SKILL.md` so an install does not pay the same bytes 88 times per turn.
Each workflow skill still states its own harness, its own runtime-record command, its
own evidence boundary, and a pointer to this file.

Load this reference when harness selection, a missing Hermes runtime capability,
multi-agent target topology, or the generic execution checklist is in play.

## OMH Context Rail

- OMH is a Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultrawork.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing/cards/handoffs/artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Hermes Compatibility Contract

- Preserve workflow intent and stop conditions; verify before claiming completion.
- Use Hermes-native tools, file operations, and subagent/delegation features when available; do not require unavailable runtime tools, role prompts, or overlays.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Mechanism Translation

When a runtime-specific mechanism appears in imported instructions, translate it to a
Hermes-native artifact:

- goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
- question renderers -> one concise question in the current Hermes interface,
- native subagents -> Hermes delegation when available, otherwise sequential lanes,
- shell bridge commands -> optional bridge mode only.

## Delegation Records

Skills record their own start with `omh runtime record --skill <name> --harness <harness> --status started`.
The delegation result is generic:

```sh
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is
unavailable, keep the result explicit as `not_available` or `not_observed`. A recorded run is
preparation, not execution, review, CI, merge-readiness, or merge evidence.

## Delegation Transparency

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]` — the user must see WHAT was asked, not just that something was.
- Name every delegated or parallel lane's model and, when the host exposes it, its reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; when no effort is exposed, show the model alone as `(model)` rather than writing a placeholder like `unknown` beside a known model, and never emit empty parentheses. Carry token and elapsed figures the same way in these narration lines: report observed figures and omit unobserved ones — when the user asks for a figure directly, say it was not observed instead of omitting it; a rendered status-board column keeps its own `unknown` cell.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it — a plain-text one-shot that hides its session id strands the work when the run stalls or times out.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is `~/.claude/settings.json` and project scope is `<dispatch cwd>/.claude/settings.local.json` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

## Waiting On Long-Running Work

Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism. Ladder and terminal states: shared rail.

Pick the row that matches the work, then the best mechanism the host actually supports. Degrade down the
column and say which capability was missing; never degrade silently, and never substitute a status loop for a
row you cannot satisfy.

| Work | Preferred | If unavailable | Last resort |
| --- | --- | --- | --- |
| Command finishing inside one tool call | one foreground call with a duration-sized timeout | background run with completion notification | one bounded watcher, then adaptive backoff |
| Longer terminal command | background run with completion notification | one bounded watcher with a hard deadline | adaptive backoff outside model turns |
| Delegated lane | the lane's delivered final result | background run with completion notification | one bounded watcher, then adaptive backoff |
| CI, PR, deploy, file, port, log line, external session | the host's monitor or subscription | ONE bounded watcher with a hard deadline | adaptive backoff outside model turns |

Every armed wait carries a hard deadline, a cancellation path, and a fallback, and closes in exactly one
terminal state: `completed`, `failed`, `cancelled`, `timed_out`, `lost_handle`. Consume the completion once; a repeated notification does not reopen a
closed wait. The midpoint-peek budget is 1 per wait, spendable only on a peek whose
result changes a decision; a user-requested status check is always allowed and never charged against it.

`omh_execution_wait_strategy/v1` is the metadata-only record of that choice — the observed handle,
the condition, the mechanism, the deadline, the cancellation path, and the fallback. Selecting or arming one
is preparation; it is never dispatch, execution, review, CI, merge-readiness, or merge evidence.

## Follow-On Engine Gate

Finishing one workflow never authorizes starting the next one. An accepted plan, a clarified
brief, or a routing recommendation is planning evidence, not permission: recommend the follow-on
engine that fits the work's shape with a one-line reason, and start it only after the user's
explicit go-ahead in this conversation.

## Multi-Agent Target Awareness

Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.

When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.

## Memory Context

When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
