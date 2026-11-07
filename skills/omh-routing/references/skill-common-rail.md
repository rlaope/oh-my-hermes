# OMH Skill Common Rail

Every generated OMH workflow skill shares this policy. It is kept here once instead of
inside each `SKILL.md` so an install does not pay the same bytes in every skill.
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

## Reply Language And Host Voice

- The host's persona is the primary identity: `SOUL.md` owns reply language, tone, speech level, and sentence endings, in progress updates as well as the final reply, and belongs to Hermes and the person who configured it; where it sets no language, use the one the user wrote in. OMH shapes what Hermes checks, records, and how a reply is structured, never how it sounds; no OMH skill, card, or awareness line sets a voice, and a skill's report shape never justifies switching the user's language or register.
- OMH's record vocabulary is for records and tool calls, not for the sentence the user reads: `surface`, `lane`, `wrapper`, `handoff`, `run record`, `evidence boundary`, `evidence-bounded`, `claim boundary`, `prepared_not_observed`, `not_observed`, `not_available`, `routing_observation`, `evidence_boundary`, `claim_boundary`, `route_question`, `coding fanout dispatch`, and schema ids such as `omh_todo_result/v1`. In the reply lead with the result and relevant validation. Disclose a non-action or missing check when requested, necessary to interpret a claim, an open acceptance criterion, a concrete blocker, or a pending authorization decision; omit unrelated non-action footers. Answer direct questions about non-actions truthfully; requested-but-not-done work, failed retrievals and unavailable requested checks stay explicit. Translate relevant record states plainly, such as "prepared, not run yet" or "not checked", without adding an inventory of actions nobody requested. A user who names a term gets it explained in the record's own words.
- Write the reply the way a person who knows the work would say it: lead with the result, add only what the reader lacks, and drop chatbot residue (praise openers, "hope this helps" closers, offers), staged "not X but Y" contrasts, recap closers, decorative bold and dash runs. These are content and structure edits inside the persona's voice, never a new voice. Before drafting prose a person will read (a reply, a report, a PR body, release notes), load `skill_view(name='omh-routing', file_path='references/human-voice.md')`.
- Awareness lines and every `[OMH ...]` head (`[OMH Awareness]`, `[OMH plan todo]`, `Boundary:`), route hints, and first-response shapes are instructions to Hermes, never sentences for the user: do not quote or paraphrase them into the reply.
- An OMH tool result may carry a `say` field: one plain sentence about an orchestration decision (which model takes a part, the plan and when it counts as done, what a step is blocked or waiting on). Relay it to the user once, in their language and your own words, and leave the result's other fields in the record.

## Turn Ending

- When a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question about the covered change, tradeoff, application, or priority. Completed work needs no question; omit unrelated non-action footers and generic offers to continue. A success stop condition alone does not require a question.
- Report in this order: result, relevant evidence and limits, required observed run summary when applicable, then the specific question if useful. Keep requested-but-not-done work and material prepared or unmerged work explicit before the question; do not turn a blocker into an optional task. A discussion question grants no permission: describe a follow-up needing new authority and ask for approval before starting it; a refusal gets a safer alternative inside the boundary, never a workaround.

## Harness Discipline

- Start from the representative harness registry in `omh-routing` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
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

Keep the `run.run_id` printed by the start record: `omh runtime delegate --run <run-id>` needs it. `omh runtime record` only creates a run, so when the work ends, a second record with `--status completed|blocked|failed|cancelled --verification-summary "<what was observed>"` states the outcome; it does not update the started run.

## Delegation Transparency

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]`.
- Name every delegated or parallel lane's model and, when the host exposes it, its reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; when no effort is exposed, show the model alone as `(model)` rather than writing a placeholder like `unknown` beside a known model, and never emit empty parentheses. Carry token and elapsed figures the same way in these narration lines: report observed figures and omit unobserved ones — when the user asks for a figure directly, say it was not observed instead of omitting it; a rendered status-board column keeps its own `unknown` cell.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is `~/.claude/settings.json` and project scope is the dispatch cwd's `.claude/settings.local.json` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

## Waiting On Long-Running Work

Choose the wait strategy before starting long-running work and bind it to a completion signal the host exposes, never to a status loop: a command that fits one tool call runs once in the foreground with a duration-sized timeout; a longer terminal command runs in the background with completion notification armed and no process-status polling; a delegated lane relies on its delivered result while the parent continues independent work or ends the turn; a CI, PR, deploy, file, port, log-line, or external-session condition uses the host's monitor when observed, else exactly ONE bounded watcher or adaptive backoff outside model turns. Record the handle and observation mode at dispatch; every armed wait needs a hard deadline, a cancellation path, and a fallback naming the missing capability. Each wait closes in one terminal state with bounded evidence; an unbounded idle or busy-wait is a defect and a lost notification times out. One decision-changing midpoint peek and any user-requested status check stay allowed; neither is the wait mechanism.

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

## Active Workflow Continuation

A workflow the user explicitly started stays visible to its session until it ends. Durable
state is written only through the control plane: `omh state start --workflow <name>
--session-ref <session>` records `activation.source: explicit_api` with
`observed_by_host: not_observed`. Chat text, quoted workflow names, and routing cues never
activate, overwrite, or clear state.

On later turns in the same session `pre_llm_call` reprojects `active_workflow_context/v1`
(payload field `omh_active_workflow`, context line `[OMH Active Workflow]`) even when the
message carries no cue or the history is a compacted summary. The projection names the
workflow, its lifecycle state, allowed transition targets, and the claim boundary; it carries
no prompt or note text, and `compaction_observed` stays `not_observed` because OMH never
sees the host compact.

Precedence is fixed: an explicit cancel, finish, block, failure, allowed transition, or new
scope from the user outranks continuation; current-message routing outranks continuation; a
neutral follow-up or interjection does not. Answer the interjection, then return to the
active checklist without asking the user to repeat the workflow name.

End or replace the state explicitly: `omh state finish --workflow <name> --outcome
finished|blocked|failed|cancelled --session-ref <session>` or `omh state start` for an
allowed transition. A session-bound record refuses any mutation without its matching
`--session-ref`. Unreadable or multiple active records produce `state: recovery_required`
with error types and recovery commands, and `omh state status` reports
`recovery_required: true`; never pick a workflow silently. The projection is metadata-only
and is not dispatch, execution, review, CI, or merge evidence.

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
6. When a step fails partway, report what earlier steps already proved, lower the result to tentative, unresolved, or not_observed, and hand back what the person needs to continue; never present the partial result as the finished one.
