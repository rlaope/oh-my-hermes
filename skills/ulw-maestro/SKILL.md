---
name: "ulw-maestro"
description: "[omh] Coding owner already chosen, handoff pending: prepares the handoff for the coding agent you already chose, composing its prompt from that agent's own installed skills; never selects the owner and never executes the work itself. Use when the user says: ulw-maestro, coding handoff, prepare the handoff, prepare a coding handoff, hand off the coding work, external executor handoff, handoff prompt, delegation prompt."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, execution]
    category: execution
    phase: external-handoff
    role: handoff-guide
    quality_tier: handoff-gated
    related_skills: [omh-executor-runtime-readiness, ulw-work, claude-code, codex, opencode]
---

# Maestro

This is a Hermes-native `maestro` workflow skill.

## Why This Exists

`maestro` exists so a handoff to an already-chosen external coding CLI carries that CLI's own installed skills, a stated dispatchability boundary, and a captured session id instead of a guessed prompt; absent an explicit coding-owner choice, work runs inside the Hermes harness and no external coding CLI is selected, and this engine only loads once that explicit choice is already made.

## Do Not Use When

- No coding owner is chosen yet for this run; the Hermes harness stays the default and this engine never picks one.
- The request is a concept question about maestro, prepared handoffs, or a coding-agent name, or a filename that happens to contain one -- answer directly instead.
- The user wants advice on which coding owner to pick -- ask, don't compose.
- The user is asking whether an owner CAN run right now -- use `omh-executor-runtime-readiness` instead.
- The request is lane-splitting or a full delivery cycle rather than one lane's handoff -- use `ulw-work`, which enters this engine for lanes with an external owner.
- The user wants a coding task handed straight to the Claude Code, Codex, or opencode CLI in the terminal, with no prompt composed from that CLI's own installed skills -- load Hermes' bundled `claude-code`, `codex`, or `opencode` skill instead of this one.

## Examples

Good example:

- Prompt: $maestro codex already agreed to take this -- compose the handoff prompt for the retry-queue fix.
- Expected behavior: Confirm codex as the accepted owner, discover its installed skills, compose a role-arranged prompt with the required sections, and state the dispatchable handoff mode.
- Why: The coding owner is already explicit and the work needs a skill-aware prompt, not owner selection.

Bad example:

- Prompt: 맡길 사람 아직 안 정했는데 그냥 maestro로 프롬프트 만들어줘.
- Expected behavior: Ask `choose_executor` for the coding owner before composing anything; never pick one on the user's behalf.
- Why: No coding owner has been explicitly chosen yet, so composing a handoff would select the owner silently.

## Completion Checklist

- The selected coding or runtime owner is named before any implementation claim.
- Prepared handoff, dispatch, execution, verification, review, CI, and merge states are separated.
- The final status cites observed runtime evidence or keeps the work prepared_not_observed.
- When Hermes is the selected coding owner this engine does not apply -- Hermes-native selection uses the Hermes runtime path, never this engine.
- Dispatch never merges: collect each unit's fanout_unit_result/v1 evidence, verify the integrated combination of units (not just each one alone -- disjoint file scopes can still conflict at integration), and report merged/unmerged per unit in the closing brief. Merging the unit branches remains an explicit operator or reviewing-agent action; a dispatch receipt is never merge evidence.
- The closing brief ends with the observed `omh_run_summary` summary_text verbatim, or an explicit run-summary not_available line -- never a model-estimated number.

## Recovery Notes

- If the selected executor is unavailable, ask for Codex, Claude Code, Hermes, or another runtime before retrying.
- If dispatch or result evidence is missing, keep the handoff prepared_not_observed and expose the next observable action.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+28 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use once a lane's coding owner is an explicit external CLI and the work needs a prompt composed from that CLI's own installed skills, its readiness and permission checked, and its session captured for steering.

    Strong routing signals: `$maestro`, `ulw-maestro`, `coding handoff`, `prepare the handoff`, `prepare a coding handoff`, `hand off the coding work`, `external executor handoff`, `handoff prompt`, `delegation prompt`, `コーディング委任`, `委任プロンプト`, `ハンドオフを準備`, `外部の実行エージェントに渡す`, `코딩 위임`, `위임 프롬프트`, `핸드오프 준비`, `외부 실행기 위임`, `코딩 에이전트에 넘기`, `编码委托`, `移交提示词`, `准备交接`, `交给编码代理`, `siapkan handoff coding`, `buat prompt delegasi untuk agen coding`, `susun instruksi implementasi untuk eksekutor coding`, `siapkan serah terima ke agen coding pilihan saya`, `bantu bikin brief untuk eksekutor coding`, `kemas tugas coding untuk agen yang sudah dipilih`

## Catalog Metadata

Category: `execution`
Phase: `external-handoff`
Hermes role: `handoff-guide`
Quality tier: `handoff-gated`
Reasoning demand: `heavy`

Quality bar:

- Planning is not execution permission. Handoff requests authorize preparation only; explicit execution requests authorize only their scope, subject to readiness and permission probes. Clarify missing authority.
- Require an explicit owner choice for this run: named now, confirmed when asked, or recorded as `accepted_explicit_choice`. Recommendations, plan mentions and previous owners do not count. For a missing, ambiguous or unready owner, ask `choose_executor` once and stop; never choose for the user.
- Owner selection alone is not dispatch permission: `prepare a Codex handoff only` or `use Codex, do not dispatch` stays preparation-only. `Use Codex to implement this now` supplies both the owner choice and dispatch permission within scope, with no redundant confirmation. After readiness and permission probes, invoke the fanout-dispatch bridge (`omh coding run` for one unit); clarify missing owner or action authority first.
- State the handoff mode before composing: claude-code is prompt-only (`coding_prompt_handoff/v1` -- the prepared handoff record is never dispatchable and never described as a run; only the fanout-dispatch bridge -- `omh coding fanout dispatch` or its `omh coding run` single-run entry -- ever spawns a CLI), codex is a dispatchable `coding_executor_handoff/v1`, and omx-runtime/omo-runtime/omc-runtime are `coding_runtime_handoff/v1`.
- Compose the prompt from the selected profile's DISCOVERED skills via `omh coding executor-skills --profile <profile>`: arrange the returned skills by the unit's role recipe, one named skill per step, using each skill's own invocation string verbatim (`/name`, `/pack:name` from its manifest, `$name` for a codex pack) -- never a guessed prefix. Empty discovery gets one explicit line -- "no installed skills discovered for <profile>; prompt composed generically" -- then compose generically. Load `references/executor-prompt-composition.md` for the full procedure.
- A discovered skill is declared, never observed: a `SKILL.md` on disk is evidence the file exists, not that the receiving agent loads, enables, or honours it -- its own registry is the authority.
- Hold every composed prompt to the executor prompting contract: the ten required sections in order (Goal, Do, Don't, Known context, Unknowns and decision rule, Expected result, Test, Progress and blockers, Evidence boundary, Task), a greppable `Docs consulted:` block (URL plus version, or the explicit none-line), and the six-section session summary shape on report-back.
- Keep the composed prompt cache-stable: an invariant head that stays byte-identical across units and re-dispatches, with only the tail varying.
- Before real dispatch, observe execution (a `--version` or no-op call) and read the configured model from the executor's own config or output; a binary on PATH plus an auth file is `prepared`, never `observed`. Run a bounded permission probe before the real dispatch.
- When the user names a model for this delegated run (for example "opus로 돌려줘", "fable로 돌려줘", "use opus"), pass it through `omh coding run`'s `--model` flag (or the unit's `model` field under `omh coding fanout dispatch`) using the executor's own accepted identifier -- codex and claude-code both take `--model`, so an alias like `opus` or a full id like `claude-opus-5-5` reaches the CLI unmodified; Claude Code's `opus` alias tracks the provider's recommended Opus (Opus 5.5 needs Claude Code v2.1.280 or later; on Microsoft Foundry it resolves to Opus 4.6).
- That named model is handed to the executor verbatim, unvalidated; an unknown or unentitled value surfaces as the executor's own observed exit failure, never a silent fallback to the dispatch-model preference or the executor's own default.
- The fanout-dispatch bridge -- `omh coding fanout dispatch` for a multi-unit split, or `omh coding run` for one unit -- is the only executing surface, explicit per invocation, and it never merges; preparing, composing, or showing a prompt is never dispatch, and a dispatch receipt is never review, CI, or merge evidence.
- To carry the files the Hermes session already touched into the handoff, cite `session_file_activity/v1` (`omh quality-evidence file-activity --hermes-session <id> --json`): the workspace files its read_file, write_file, and patch calls named, with the outcome Hermes recorded -- never file-content, diff, test, review, CI, or merge evidence.
- Capture the executor's session id at dispatch (`--output-format json` -> `session_id` for Claude Code, `--json` -> `thread_id` for Codex) and carry it into every status line; a missing id is reported as unsteerable, never silently attached.
- Observe to a terminal state with ONE bounded watcher, never a status poll in your own turns: after dispatch, start `omh coding fanout status --fanout-id <fanout-id> --wait --timeout 600` once -- when `terminal` is in your tool list or tool_search finds it, as `terminal(command=..., background=true, notify=true)`, otherwise in the foreground. Then do independent work or end the turn, unless the spawn result says this session cannot receive the completion: then wait on that process the way the result names before ending the turn. It re-reads the roster itself and its exit code says why it stopped: 3 when the roster's own `stuck_units` names a unit, 0 when `all_units_terminal` is true and every unit is `verified`, 1 when all are terminal and one is not, 65 when they all verified but the journal had unreadable lines (a unit may be missing from the roster), 124 when the timeout passed first. Any other code means the watcher itself did not finish (an error, a crash, or a kill). On any exit, read the roster once with `omh coding fanout status --fanout-id <fanout-id> --json` and act on the units it names; after a code the watcher did not choose, start a fresh watcher only if units are still running. Per unit, `terminal` is the answer and `unit_state` is why -- a `lifecycle_state` of `unit_verification_observed` or `integration_ready`, or a recorded `failure_diagnostic`, is what makes a finished unit terminal -- with `last_event_age_seconds` the time since that unit's last observed output, `progress.seconds_since_new_output` the time since its output last grew, and `capacity.next_action` the reason a refused unit was refused. A unit that is `progress_stalled`, `awaiting_input`, `account_limit`, `permission_blocked`, or `data_missing` needs intervention NOW, not more waiting: a live process with no new evidence is not progress, and re-running under the same account, the same credentials, or the same missing objects repeats the failure exactly. Never end a turn on "waiting for the worker" while a unit sits in one of those states; exit 3 is that moment. `all_units_terminal` is also false when the roster is empty and when a unit has neither a marker nor a summary row, which is why the watcher has a deadline: on exit 124 a unit whose `unit_state` is still `unknown` is a missing record to chase, not a unit to keep waiting on, only a unit still `running` gets a fresh watcher, and a wait with no bound is the stall it was meant to catch.
- A finished dispatch is an event to act on in the same turn, not a status to report: verify that unit's result, record the outcome on the plan (done, or blocked with its reason), then run the recovery or start the next item. Never announce a continuation that has not actually started -- a closing sentence promising the next step, with no dispatch and no plan change in the same turn, is the failure this rule exists for.
- Write every steering delta as more than a restated brief: name the changed constraint, the new evidence, the required action, and whether the verification target moved.
- A mid-run user message is an interjection, not a stop: answer it briefly and, in the same reply, continue the run — re-read the phase todo when one is active and dispatch or advance the next pending step, or name the armed wait it is waiting on -- handle, bound completion signal, deadline -- instead of re-reading status. Only the user's explicit stop or cancel, or the engine's own completion gate, ends the run; when the interjection changes scope, say so and update the declared plan or todo instead of silently abandoning it. A mid-run message is the latest steering for the active task, not automatically a replacement objective: it replaces the objective when the user says so and steers the current one otherwise.
- A follow-up that needs new authority, materially expands the scope, or changes external state not already authorized is described first and started only on the user's approval: the turn ends by naming that next action and asking whether to take it, as one question carrying the choices the user has, never by declaring what will not be done; persistence never broadens the authorized scope. A refused escalation is answered the same way, with a safer alternative inside the boundary or the authorization the boundary asks for — never a workaround or an indirect execution.
- The closing brief scales to the change: one or two sentences plus the observed validation for a simple change, more only when the complexity earns it. Lead with the result or decision, in the user's words; omit abandoned approaches unless they explain a tradeoff the reader needs; narrate no internal bookkeeping (todo transitions, waits). When the work stops at a boundary or at a decision the user owns, end with the next action offered as a question, and state what was left undone as the option it leaves open, never as a refusal. Required closing lines stay outside this scaling: the observed run summary, and any prepared-not-observed or unmerged work, are stated whatever the brief's length.
- Entered from an `ulw-work` lane, own that lane's handoff only -- lane framing, disjointness, integration verification, and the closing brief stay with `ulw-work`; report back in that lane's evidence vocabulary.
- Close with the localized `omh_run_summary` summary_text verbatim as the final lines, or an explicit run-summary not_available line -- never an estimated number.

Handoff policy:

Convert an explicitly chosen external coding owner into a prepared handoff: claude-code as a prompt-only `coding_prompt_handoff/v1` (never dispatchable, never described as a run), codex as a dispatchable `coding_executor_handoff/v1`, and omx-runtime/omo-runtime/omc-runtime as `coding_runtime_handoff/v1`. This engine loads only after that choice is made -- absent an explicit coding-owner choice, work runs inside the Hermes harness and no external coding CLI is selected -- and it never substitutes for the Hermes harness path or picks the owner itself.

Executor readiness:

- When accepted work mutates code, check `executor_readiness/v1` for the selected Codex, Claude Code, Hermes, or oh-my runtime path before first dispatch.
- If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or keep a prompt/runtime handoff; retry only after that state changes.
- A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

Delegation transparency:

- When delegating, show the composed delegate prompt in a fenced code block in the status message; truncate a long prompt to a bounded preview ending with `... [truncated, N chars total]` — the user must see WHAT was asked, not just that something was.
- Name every delegated or parallel lane's model and, when the host exposes it, its reasoning effort inline as `(model effort)` in status and briefing lines — including runtime-native subagents; when no effort is exposed, show the model alone as `(model)` rather than writing a placeholder like `unknown` beside a known model, and never emit empty parentheses. Carry token and elapsed figures the same way in these narration lines: report observed figures and omit unobserved ones — when the user asks for a figure directly, say it was not observed instead of omitting it; a rendered status-board column keeps its own `unknown` cell.
- Capture a resumable session or thread id at dispatch and report it in the status message: for non-interactive Claude Code pass `--output-format json` and read `session_id` from the result (resume with `claude -p --resume <session-id>`); for Codex pass `--json` and read `thread_id` (resume with `codex exec resume <thread-id>`, repeating `--skip-git-repo-check` outside a git repo). Never leave a delegate run with no recorded way to resume or steer it — a plain-text one-shot that hides its session id strands the work when the run stalls or times out.
- Before dispatch, grant the executor session every permission the task will need — file write/edit, command/test execution, and the working directory — on the dispatch command itself, not through settings-file guesses: for non-interactive Claude Code pass `--permission-mode acceptEdits` or an explicit `--allowedTools` list (`--dangerously-skip-permissions` only inside an isolated worktree or sandbox), and the equivalent sandbox/approval flags for other CLIs. `acceptEdits: true` is not a settings key and `~/.claude/settings.local.json` is not a file Claude Code reads — user scope is `~/.claude/settings.json` and project scope is the dispatch cwd's `.claude/settings.local.json` with rules under `permissions.allow`. Prove the grant with a bounded scratch-edit probe run before the real dispatch: a permission denial in a non-interactive run recurs identically on retry, so never redispatch until a changed grant is proven, and surface an ungrantable permission as a blocker before dispatch, not after minutes of silence.

Required inputs:

- explicit coding-owner choice for this run
- task or unit description
- the chosen profile's discovered executor skill set

Expected outputs:

- a composed executor prompt arranged by the unit's role recipe
- the handoff mode and dispatchability state named up front
- a captured session or thread id, or an explicit unsteerable note

Artifact expectations:

- prepared external handoff record when a wrapper can record it

Safety rules:

- Never prepare a handoff without an explicit owner choice for this run -- a routing recommendation, a plan mention, or a previous run's owner is not a choice for this run.
- Prepared, composed, or shown is never dispatch, execution, review, CI, or merge evidence.
- Never route a Hermes-owned lane through this engine; the Hermes harness stays the default coding path.
- Never carry a discovered skill's description text into a composed prompt -- only its name and invocation string ever leave discovery; the description stays inside the classifier.
- Never dispatch without an explicit user dispatch command; the fanout-dispatch bridge -- `omh coding fanout dispatch` or its `omh coding run` single-run entry -- is the only executing surface.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill maestro --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
