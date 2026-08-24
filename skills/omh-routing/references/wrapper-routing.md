# OMH Wrapper Routing

This reference is for Discord, Slack, hosted Hermes, plugin, or backend adapters. It is not normal end-user UX.

## Chat Routing

Wrappers can run `omh chat route` before dispatching a plain chat message to Hermes:

```sh
omh chat route --source discord --record "risky refactor"
```

Use `route.routing_prompt_template` with `{message}` replaced by the received chat message as the prompt forwarded to Hermes. If the wrapper wants a pre-expanded prompt, pass `--include-message` and forward `route.routing_prompt`.

Prefer `omh_interact` when the plugin/tool surface is available because it returns `chat_interaction/v1` and can record a metadata-only wrapper session. Use `omh_recommend` only when Hermes needs route hints without a session record. The plugin-authored metadata has producer provenance so it stays distinguishable from wrapper/backend metadata.

Do not make a normal chat user approve `omh list`, `omh recommend`, `omh chat interact`, or other backend commands just to see workflow options. Render compact summaries, context briefs, pickers, quickstart, probe, or status cards instead.

Bare `./omh`, `/omh`, `./skills`, or `/skills` opens the workflow picker. A leading `/omh` or `./omh` command followed by an imperative task remainder routes to `meta-router`, which consults the live catalog and selects or chains the right workflow(s); the picker owns only the bare forms and workflow questions.

## Skill Name Display Prefix

Installed OMH skills render a prefixed frontmatter `name` so the host status line is distinguishable from a Hermes built-in: domain skills carry `omh-` and the workflow-engine skills carry `ulw-` (for example `Reading skill ulw-work` for `ultrawork`, `ulw-plan` for `ralplan`, `ulw-loop` for `loop`). The router skill renders as `omh-routing`.

That label names the installed `skills/<label>/` directory and the host status line only. The canonical catalog name still owns the install manifest `name`, routing keys, and every `omh` CLI argument, so `omh recommend`, `omh runtime record --skill <name>`, and trigger strings keep using canonical names. Earlier label eras (`omh-ultrawork`, `ulw-ultrawork`) remain accepted as routing aliases of the same workflow, so text echoed from a stale install still resolves — but always render the current label.

Two host-side consequences follow, both accepted. Host slash commands derive from the same frontmatter `name`, so an explicit invocation is `/ulw-work` or `/omh-visual-qa`, never the bare canonical form. And because installed skills share the `omh-`/`ulw-` stems, a bare `/omh` is an ambiguous multi-candidate command on hosts that complete slash commands by prefix; treat it as the picker alias described above rather than as a single resolved skill, and disambiguate by completing the full label.

## Coding Delegation

When a chat message is implementation-shaped and a wrapper wants a concrete executor handoff, run `omh coding delegate` after or instead of generic chat routing:

```sh
omh coding delegate --source discord --executor codex --record "risky refactor"
```

The payload is deterministic local adapter data: recommended workflow, harness, executor/runtime profile, acceptance criteria, verification expectations, and handoff prompt template. Hermes still narrates the user-facing state.

Implementation-shaped has a floor. A settings-only or single configuration change (a gateway channel policy, a mention rule, one config key) that the wrapper or Hermes can apply directly is a direct configuration action: apply it, verify the new value, and report it. Do not open a durable goal ledger, start a goal loop, or prepare an executor handoff for it. Escalate to a coding handoff only when the request needs code edits, tests, or multi-step implementation work that configuration cannot express.

Check `executor_readiness/v1` for Codex, Claude Code, Hermes, or oh-my runtime profiles before first dispatch. If readiness is `missing` or `blocked`, ask the user to choose another coding agent, configure PATH, continue in Hermes, or use prompt/runtime handoff; retry only after that state changes. A readiness probe is not dispatch, execution, verification, review, CI, or merge evidence.

With `--record`, Codex-selected real executor handoffs create `.omh/runtime/runs/<run-id>/` prepared runtime runs with `observation_status: prepared_not_observed`. Executor-choice, prompt-only, runtime-handoff, clarify, and fallback responses remain wrapper/session state.

### Code-Mode Batching

Use code-mode batching only when the selected profile's declared `code_mode_batching` capability is `supported`. When it is `unsupported` or `unknown`, skip this paragraph entirely and issue one tool call per step; an undeclared capability is not a permission.

Under that condition, plan the wave first and then run the independent reads, searches, and metadata lookups of that wave in a single evaluated cell instead of one call per turn. Batch only calls that do not consume each other's output, keep every call's target explicit so a failure names the call that failed, and never batch a mutation with the reads that justify it. The batch is a call-shape choice; it is not execution, verification, review, CI, or merge evidence, and it changes nothing about which stages are observed.

### Edit-Format Steering

Handoff prompts choose an edit format. Steer it from the profile's declared capability metadata, and name the capability that justified the choice — never a vendor, and never a promised improvement.

- When a profile declares `unsupported` or `unknown` for strict patch/diff application, ask for whole-function or whole-block replacements with surrounding anchors instead of a patch or unified-diff grammar. A rejected patch hunk costs a retry that a block replacement does not.
- After any accepted edit, require re-grounding: re-read the changed region before the next edit rather than reasoning from the pre-edit copy in context.
- Prefer narrow reads with search-before-edit — locate the symbol or string, read only the region around it, then edit — over whole-file reads that push the rest of the handoff out of context.

These are capability-conditioned prompt shapes, not performance claims. Do not claim an edit format will make an executor faster, cheaper, or more accurate; the profile metadata is descriptive, and only observed run evidence can say what happened.

### Resource References In Prepared Handoffs

A prepared handoff names resources; it does not paste them. Every named resource carries four parts:

- **Canonical locator** — the stable identifier the resource is addressed by (path, artifact ref, URL, or record id), written once and reused verbatim.
- **Read/search capability** — how the executor is expected to obtain it: read the whole thing, search within it, or fetch a named region.
- **Provenance** — where the locator came from and when it was observed, so a stale reference is visible as stale rather than as truth.
- **Local-path fallback** — the on-disk path to use when the canonical locator is unreachable, plus what to report when neither resolves.

A resource reference is not the resource. An unresolved reference is a blocked input to report, never a gap to fill by guessing the content.

### Commit Planning

When a handoff is expected to produce more than one commit, plan the commits before the edits start:

- **Overview first.** State the full change set and its ordering before the first commit, so no commit is invented mid-stream to hold leftovers.
- **Bounded diffs.** Each commit is one reviewable idea; a diff that cannot be described in one sentence is two commits.
- **Complete, non-overlapping coverage.** Every changed file belongs to exactly one commit in the plan. No file appears twice; no changed file is unassigned.
- **Dependency order.** A commit that depends on another comes after it, and each commit is expected to build and test on its own.
- **Lockfile-manifest pairing.** A dependency-manifest change and its lockfile update land in the same commit, never split across two.

A commit plan is preparation. Commits, review, CI, and merge stay separately observed.

## Large Results And Window Safety

Wrappers must keep raw Codex JSONL, tool output, process logs, and oversized
executor notes out of Hermes chat context. Use `omh chat codex-progress` or the
Codex progress fields on executor-session actions to pass only
`codex_progress_summary/v1`, `omh_context_artifact_ref/v1`, compact evidence
refs, and bounded human-readable summaries. Raw output belongs in a wrapper or
operator artifact store referenced by `raw_output_artifact`; a prepared artifact
reference is not execution, review, CI, merge-readiness, or merge evidence.

Prefer event-triggered progress over timed polling for long executor, goal,
research, or workflow runs. Emit `omh_progress_event/v1` when a meaningful state
changes: failure discovered, root cause identified, fix strategy selected, files
or area chosen, targeted tests pass/fail, full tests start/pass/fail, commit
created, PR created/updated, or blocker encountered. Keep each update to one or
two human-readable sentences with optional compact file refs, artifact refs,
severity, and status. Store raw logs, JSONL, command output, and transcripts as
artifacts; pass only event summaries and refs into Hermes chat context.

## Memory And Planning

Wrappers can run `omh memory inspect`, `omh memory pack`, and `omh memory apply` to review OMH-local or wrapper-supplied context before preparing a handoff. This emits `memory_review_card/v1` and `handoff_context_pack/v1` artifacts only; it does not read or mutate opaque Hermes internal memory.

For planning-shaped requests, wrappers or operators can run `omh hermes plan` to create a deterministic `hermes_plan/v1` scaffold. The stdout `wrapper_contract` is the adapter contract for follow-on work; after acceptance, pass the accepted plan artifact or generated context pack to `omh coding delegate --from-plan` instead of treating Discord/channel summary text as the executor plan.

## Backend Boundary

This is a deterministic wrapper-side decision layer. By default, stdout and runtime artifacts avoid duplicating the raw prompt body. It does not patch Hermes core or require platform network access from `omh`.
