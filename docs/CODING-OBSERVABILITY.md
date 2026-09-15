# Seeing What Coding Work Is Running

Multi-session coding work used to be invisible in three specific ways. Each is
now fixed, and each fix has a boundary worth knowing.

## What you get

```
Running work — 3 unit(s), 2 running

unit              runtime            model              status     elapsed   tokens       session
research-sweep    claude-code        opus xhigh         running    35m       10,000,000   sess_9f2c4a
api-ratelimit     codex              gpt-5.6-sol xhigh  running    4m        128,400      019a7b3e
docs-pass         omo-runtime (pi)   glm-4.6            completed  12m       unknown      unknown
```

Ask in chat — "what's running", "지금 뭐 돌고 있어", "what models are running" —
or run the command directly:

```sh
omh coding status-board [--limit N] [--json]
```

Both renderers take a `locale`: `render_status_board_text(payload, locale=...)`
for the aligned board and `status_board_messenger_body(payload, locale=...)`
for a chat surface. The copy comes from `src/catalogs/briefing_vocabulary.py`
and answers every locale either locale set uses — the four `--language` accepts
and the three more the chat-copy set resolves from a message. The CLI does not
yet pass one, so the command still prints English; an adapter that already
knows its reader's language can pass it today.

## What was actually broken

**The model was dropped.** The runtime (`codex` / `claude_code`) was tracked
end to end, but no progress surface carried the model. `_safe_signal` was a
closed key allow-list with no model key. So OMH knew *which CLI* was running
and could not say *which model* it was running on.

**Token counts had no write site.** `omh coding fanout brief` already read
`tokens_total` and `session_ref` and rendered columns for them. Nothing in
`src/` ever wrote either key, so both columns printed `unknown` on every row,
forever.

**A running unit could not report itself.** Dispatch is blocking —
`subprocess.run` inside a thread pool — so the dispatching process cannot
narrate its own progress. There was no way for a second session to see that a
unit was mid-flight, which is exactly the multi-session case that matters.

## The honesty contract

This is the part that makes "100% reliable" true rather than aspirational.

**Runtime and model are always exact when present.** OMH itself chose them and
put them on the command line, so there is nothing to infer.

**Tokens, session refs, and elapsed-for-unfinished-units are observed or
explicitly unknown.** They are never estimated, and never derived from the
Hermes conversation's own token budget — that belongs to a different actor and
using it would be a category error. A number on the board is a number an
executor reported. An absent count renders as the literal `unknown`, never as
`0`, because a zero reads as an observation.

**A start marker cannot prove liveness.** In-flight markers carry
`liveness: "unknown"` on purpose. A marker left by a process that died looks
identical to one left by a process still working, so the board reports an
observed start without an observed end rather than claiming the unit is alive.

**A live process is not moving work.** On 2026-09-11 a unit stayed alive for
36 minutes retrying the same git workaround while its supervisor read "PID
alive" as progress. So "a process exists" and "the work is moving" are now two
different readings with two different words. The dispatch word (`running`,
`completed`, `failed`, …) stays on the row's `status`, and what the unit's own
stdout showed goes in `unit_state` beside it — see the table below. Anything
`unit_state` calls stuck replaces the dispatch word wherever a row is rendered:
the status board, the plugin running-work block, and the DAG line in the TUI
widget. A unit with no assessed snapshot carries no `unit_state` at all, which
is not the same as "moving".

A supervisor polls the same answer machine-readably with
`omh coding fanout status --fanout-id <id> --json`. Every roster row carries
`unit_state`, `terminal` (via `is_terminal`), `unit_state_source`
(`inflight_marker` while the unit is in flight, `dispatch_summary` after it
exits, `none` when nothing observed it), and `progress.reason` /
`progress.seconds_since_new_output`. The roster carries `all_units_terminal`
and `stuck_units` so the loop's stop condition is computed once rather than
re-derived per caller. `terminal` follows the SOURCE, not the state word: a
dispatch-summary row is written after the dispatch ended, so it is terminal
whatever word it carries — including a unit the workspace preflight refused
before its spawn, which is stuck, needs a human, and will never move on its
own. A marker means the unit is in flight now, so its state is read literally. None of this moves `lifecycle_state`, which still
advances on journal events alone — and `all_units_terminal` is false for an
empty roster, because "nothing to wait for" and "everything finished" are
different answers.

### Unit execution states

Vocabulary in `src/coding/unit_execution_state.py`; the mid-run verdict is
derived by `src/coding/unit_progress.py` from the stdout snapshots the dispatch
already takes, and the two terminal states are assigned only after exit.

| State | What was observed | Terminal |
| --- | --- | --- |
| `running` | The work is producing new evidence: output growing, tests starting and ending, result records appearing. The only state that means progressing. | no |
| `awaiting_input` | The output ends at a question or a prompt and has been still for `UNIT_PROMPT_QUIET_SECONDS` (60s). The quiet window is the guard: one poll step of silence after a question mark is a tool call in progress, not a unit blocked on a human. | no |
| `permission_blocked` | A permission or sandbox denial stopped the work. Retrying under the same permissions cannot clear it. | no |
| `account_limit` | The provider refused for account reasons: session or usage limit, quota, credits. | no |
| `data_missing` | Objects the work needs are absent in its isolation — partial-clone blobs, a missing base commit, a ref that was described but never fetched. | no |
| `progress_stalled` | The process is alive and the work is not moving: no new output past the threshold (15 minutes, `UNIT_STALL_AFTER_SECONDS`), **or** the same *failure-shaped* line repeating three times even while bytes grow. Repetition alone is not a stall — a green run prints `... ok` endlessly — so only lines matching `_FAILURE_SHAPED_WORDS` are counted. | no |
| `failed` | The process ended without a verified result. Exit code 0 with the required result record missing is this state, with reason `result_missing` — never `verified`. | yes |
| `verified` | The result record validated against the contract and its verification was observed. The only success state. | yes |

The three non-`running` mid-run states above the stall are conditions retrying
cannot clear, so they are reported the moment the tail matches rather than
waited out. A matched shape is not provider, filesystem, or repository truth —
it is what the output looked like.

**Runtimes without structured output report `unknown` and say so.** The
omo-runtime lane (pi / senpi / opencode) has no structured token surface, so
its token columns stay unknown by design rather than being filled with a guess.

## Why the token number is a sum, and what that means

Neither CLI reports a total. Verified by capturing real output:

```
claude  usage: {input_tokens: 2, cache_creation_input_tokens: 14441,
                cache_read_input_tokens: 15273, output_tokens: 4}
codex   usage: {input_tokens: 27305, cached_input_tokens: 6912,
                cache_write_input_tokens: 0, output_tokens: 5,
                reasoning_output_tokens: 0}
```

Two things follow. Reporting `input_tokens` alone would have shown **2** for a
claude run that consumed roughly **29,700** input tokens. And reading only
`total_tokens` — which neither CLI emits — would have left the column `unknown`
on every real run.

So the board shows `tokens_billable`: the sum of the components the CLI itself
printed, carrying `tokens_billable_source: "summed_reported_components"` in the
record. Summing numbers a provider stated is aggregation. It is not the
estimation this system refuses to do, and a provider-reported `total_tokens`
still wins when one exists.

The two CLIs also name the same categories differently
(`cache_read_input_tokens` vs `cached_input_tokens`,
`cache_creation_input_tokens` vs `cache_write_input_tokens`), so the parser
normalizes both vocabularies onto one set of keys.

## Where the data comes from

| Source | Provides |
| --- | --- |
| `~/.omh/coding/fanout/<id>/inflight/<unit>.json` | start time, and the last assessed `unit_state` with its reason, stall age, repeat count, and phase markers |
| `dispatch_summary.json` | owner, model, effort, status, duration, tokens, session |
| executor progress bindings | live cross-unit state and latest observed event |

Tokens and session ids are parsed from the spawned CLI's own structured output
by `parse_unit_telemetry`, which is pure: no file I/O, no clock, no network.
This does not reverse the privacy decision in `codex_progress` — that module
strips token fields from *visible text* collection, while this one reads the
same keys as integers into a metadata-only counter and emits no text.

## Rendering to a messenger

The board is deliberately plain: no bold, no italics, no links, no headings, no
tables. That means no Slack `mrkdwn` or Telegram MarkdownV2 escaping is needed
and there is nothing to over-saturate.

Fenced blocks now survive as a `code_block` body block with newlines and
leading whitespace preserved. Before that fix a fence collapsed into one
run-on paragraph on **both** render profiles, which destroyed the column
alignment the board is made of. On limited-markdown surfaces (Discord, Slack,
Telegram) the board renders as one bullet per unit instead of a table, since
all three render fences but none render tables well.

The chat envelope's `messenger_rendering` block now does the platform-shaping
work so adapters do not have to:

- **Deterministic chunking.** `chunked_body_texts` is an adapter-ready split
  of `body_text` under the resolved platform's
  `chunking.max_recommended_chars`: paragraph boundaries first, then line
  boundaries, then a hard character split as the last resort. A fenced block
  that must span chunks is closed at the chunk end and reopened at the next
  chunk start (same marker and run length, no language tag), so no chunk ever
  carries an unbalanced fence. A single element means the body fits one
  message.
- **Fence language tags are stripped on limited bodies.** Only Discord
  renders the language tag on a fence line; Slack and Telegram print it as
  literal text, so every `limited_markdown` `body_text` (and every
  `fallback_body_text`) drops fence info strings. Nothing is lost for
  adapters that can highlight: `body_blocks` still carries each
  `code_block.language`. Recorded as the `fence_language_tags_stripped`
  transform.
- **Slack gets its own dialect.** A resolved `slack` source converts Markdown
  to mrkdwn *outside* fences — headings become `*bold*` lines, `**bold**`
  becomes `*bold*`, `[text](url)` links become `<url|text>` — recorded as the
  `slack_dialect_markdown` transform. Fenced code and inline `` `code` ``
  spans stay byte-identical. The dialect applies to `body_text` and
  `chunked_body_texts` only: `body_blocks` stay canonical, dialect-neutral
  Markdown, and `transforms_applied` describes those text fields, not the
  blocks.
- **Telegram defaults to plain text.** The `telegram` platform hint says to
  post `body_text` without `parse_mode`; opting into MarkdownV2 means
  escaping every reserved character yourself.
- **Per-platform ceilings remain the source of truth.** The `chunking` hint
  carries `max_recommended_chars` / `hard_limit_chars` for the resolved
  platform (Discord 1700/1900, Slack 2700/2900, Telegram 3700/3900, generic
  1600/1800), and `chunked_body_texts` is computed against the recommended
  ceiling.

The plain-text `omh coding fanout brief` output respects the generic 1600
soft ceiling too: past it, the brief keeps the longest row prefix that fits
and states the omission as its own `… +N more units` line pointing at
`--json`, so a truncated brief is never mistaken for a complete one.

## External effects, and why a check row no longer prints a link

Everything above is activity *inside* this machine. The moment a status report
says something happened outside it — a message was sent, a review landed, CI
ran, a branch moved — the report is describing an effect OMH cannot perform and
therefore cannot vouch for on its own.

Those effects are tracked separately, as `external_effect_receipt/v1` records in
`~/.omh/runtime/journal/external_effect_receipts.jsonl`. A status report splits
them five ways:

| State | Means |
| --- | --- |
| `requested` | the run's own records say the effect is needed; nothing has started |
| `attempted` | the effect has started; no acting surface has reported an outcome |
| `succeeded` | a surface observed the effect complete, and named it |
| `failed` | a surface observed the effect not happen |
| `unknown` | a surface observed a terminal state it cannot classify, or a success it cannot name |

`requested` and `attempted` are the two states that matter most here, because
they are the ones a status board used to render as silence. Both are projected
from the *absence* of a receipt — from what the run's own records asked for and
how far they say it got — and neither is ever minted from a record nothing
observed. A gate recorded as `pending` writes `observed: false`, so it mints
nothing and shows as `attempted` because the run asked for it, not because
anyone saw it. Only `succeeded`, `failed`, and `unknown` come from a receipt.

A success claim carries its citation. `omh runtime delegation-status` names the
receipt id and the acting surface behind every `succeeded` effect, and
`safe_summary` prints the citation in the sentence that makes the claim. The
`ci_observed` and `merged` rungs need a receipt that observed *that* effect
*succeed* from the surface that gate is observed by: a `failed` or `attempted`
receipt satisfies neither, and one rung's receipt never satisfies another's.

### Runs recorded before receipts existed

A run written by an earlier version has no receipts, and that is not a fault.
`omh runtime validate` stays green for it, and it keeps every claim rung through
`review_observed` — handoff prepared, executor dispatched, execution observed,
verification observed, review observed all still hold, because none of them
describes anything outside this machine.

What such a run cannot do is claim `ci_observed` or `merged`. Both assert an
external effect, and nothing on record names the surface that saw it, so
`omh conformance check` blocks them with a reason that says exactly that. The
data is intact; the claim is refused.

#### The supported upgrade path

Record each already-observed gate again, in ladder order, with the result you
observed. Writing the record is what mints the receipt:

```sh
omh runtime ci    --run <id> --status passed --provider <provider> --check <name>:passed
omh runtime merge --run <id> --merged --target-branch <branch> --merge-commit <sha>
```

Nothing else is needed and nothing else is supported. Two properties make this
honest:

- **Every status you type is one the run already recorded.** The commands
  re-state `ci passed` and `merge merged`, which is what the run's own
  `ci.json` and `merge.json` already say. You never have to write a status you
  did not observe to get back to one you did.
- **Re-recording is allowed only from a completed gate.** These commands
  normally refuse a status the run has not reached — recording `merge merged`
  on a run still awaiting its executor stays refused, and says so. A run that
  has already passed the gate sits at `next_action: report_merged`,
  `report_merge_ready`, or `report_completion_with_evidence`, and from there
  recording the same gate again is a restatement rather than a transition, so
  the preflight admits it.

Recording the same observation twice still mints once, so running the sequence
again is harmless. Run `omh runtime delegation-status --run <id>` afterwards:
`merge.receipt.receipt_id` and `merge.receipt.acting_surface` are the citation,
and `safe_summary` carries it in the sentence that makes the claim.

There is deliberately no command that mints a receipt directly: a receipt an
operator can type is exactly the self-reported evidence this store exists to
replace.

Receipts are metadata-only, which is why `format_check_rollup` stopped printing
the URL from `gh pr checks` output. A check row now ends in a redacted receipt
reference (`ref-<digest>`) instead: stable, so rows still deduplicate and
correlate, and non-navigable, so a status report never republishes a link, a
credential embedded in one, or anything else the check output happened to
carry. The same guard covers every string field on a receipt, by class rather
than by name. Identifiers — `receipt_id`, `effect_id`, `run_id`, `observed_at`,
`external_ref`, `supersedes_receipt_ref`, and each `evidence_ref` — must be
opaque metadata references: bounded, non-navigable, and free of control
characters. `action`, `target_class`, `acting_surface`, and `observed_result`
are closed vocabularies. `summary` is bounded free text. Each class is enforced
in all three places a receipt is handled — when it is built, when it is
validated, and when it is rendered — so a hand-edited store line cannot reach a
citation: a link, a path, a secret, or anything with a newline or an ANSI escape
in it becomes `[redacted]` in free text and a `ref-<digest>` handle in an
identifier, and a value outside a closed vocabulary renders empty.

## Language diagnostics, and why "clean" is not "verified"

A language server answers one narrow question fast: at this revision, which
positions in these files does the analyser object to? That is genuinely useful
right after an edit, and it is the single most over-read signal in a coding
report. "No diagnostics" gets written up as "verified", and the reader hears
compilation, tests, review, and CI — none of which a diagnostic pass performs.

`language_diagnostic_evidence/v1` records the narrow answer with the narrow
label attached. OMH installs no language server, starts no process, and opens
no socket; the diagnostics are supplied by a caller that ran the provider
itself, and the record is metadata only — severity, code, workspace-relative
path, and position. A diagnostic *message* is not a field, and an input
carrying one is refused by key name, because a message is where a source body
would arrive.

The verdict is derived from what the caller supplied, never accepted from it:

| Verdict | Means |
| --- | --- |
| `no_new_diagnostics_observed` | a fresh, attributable check found nothing new |
| `new_diagnostics_observed` | a fresh, attributable check found N new diagnostics |
| `attribution_unavailable` | no workspace, no baseline revision, or no end revision |
| `stale_diagnostics` | the diagnostics were observed at a revision other than the interval end |
| `freshness_unknown` | the caller did not say which revision the diagnostics came from |
| `provider_unsupported` | no diagnostic provider was available for this workspace |
| `provider_failed` | the provider ran and failed |
| `not_observed` | no check happened |

The last six are preserved rather than collapsed, because a provider that never
ran and a provider that found nothing are exactly the two states this record
exists to keep apart. A zero-diagnostic result observed at the wrong revision
is `stale_diagnostics`, not a clean run.

One predicate decides what any of it proves.
`language_diagnostic_supports_claim` returns `True` only for
`fresh_language_diagnostic_check`, and only for the first two verdicts. Asked
about verification, compilation, tests, review, CI, merge-readiness, or merge,
it returns `False` for every record the contract can build, including a
perfectly clean one — there is no argument that reaches a `True`, and no verdict
in the vocabulary that reads as verification. The human-readable
`summary_label` is derived too, so a caller cannot hand in prose that upgrades
its own result, and validation re-derives freshness, attribution, verdict, and
label on the read path so a hand-edited record cannot reach a status line.

Operators and wrappers can scope one supplied observation without recording
anything:

```sh
omh quality-evidence language-diagnostics \
  --owner claude-code --provider <provider> \
  --workspace <id> --baseline-revision <sha> --end-revision <sha> \
  --diagnostics-revision <sha> [--introduced <json>] [--resolved <json>] [--json]
```

It is read-only in both directions: it starts nothing and writes nothing. Plain
text is the default and prints the claim support next to the verdict, so the
line a reader quotes already says what the check does not settle.

### Running that check right after a unit goes GREEN

The record above needs someone to supply an observation. Fan-out dispatch can
now ask for one at the single moment it is worth the most, right after a unit's
verification passed, without changing what that pass means.

Agent/operator surface:

```sh
omh coding fanout dispatch <fanout-id> --goal-file goal.txt \
  --run-verification --diagnostics
```

`--no-diagnostics` is the default. When the operator types `--diagnostics`,
the repository-owned adapter discovers the closed local command set
(`pyright`, `basedpyright`, and `ruff`) from `PATH`; it installs nothing,
accepts no executable override, invokes no shell, and opens no socket. A
caller-supplied engine remains the executor-neutral extension seam. If none of
the built-in commands is available, the diagnostic result is explicitly
`unsupported`/`held` rather than silently clean.

For each selected provider, OMH retains at most 201 changed paths from Git:
the extra sentinel path makes an over-200 scope explicitly unsupported instead
of silently truncating it, and no provider receives more than its 200-file
bound. OMH materializes each fixed revision in a detached temporary worktree
and runs only the provider's fixed argv template. Global concurrency is two and
per-provider concurrency is one; the pyright-family providers are marked
stateful and serialized across overlapping requests. Each process has the
provider timeout, an allowlisted environment with credentials removed, and
hard-capped stdout/stderr drainers. The owned process group/tree is always
terminated and reaped after the provider leader exits, including exit zero;
an unproved cleanup becomes a crashed observation rather than clean evidence.
On Windows the provider is created suspended, assigned to a kill-on-close Job
Object, and resumed only after that assignment succeeds. The Job Object must
report zero active processes before the observation can be clean.
Provider messages, snippets, stderr, absolute paths, and raw JSON are discarded
after normalization. The temporary revision worktree is removed before the
observation returns, and a moved or dirty execution checkout becomes stale
rather than clean.

Four conditions gate each unit's check, and all four must hold:

| Condition | Why |
| --- | --- |
| a discovered local or caller-supplied engine is enabled | no missing provider is inferred to have run |
| the unit's verification passed | a diagnostic pass on a red unit answers a question nobody asked |
| producer evidence exists | the unit's own result has to be attributable first |
| both revisions are fixed 40-hex Git object identities | a check "at HEAD" is stale by construction, so it never runs here |

What lands on the unit entry is metadata: a `diagnostic_status` of `observed`
or `held`, the engine's own execution status, and one
`language_diagnostic:<record_id>` reference per
`language_diagnostic_evidence/v1` record. Nothing else moves. A held or
non-clean diagnostic outcome does not fail the unit, does not reopen
verification, and does not change the unit's rung on the evidence ladder. It is
an observation recorded next to the result, not a gate in front of it.

## Why is this run unhealthy

A status board says what is happening. It does not say why a run is slow,
stale, retrying, or missing the evidence that would settle it — and each coding
owner narrates that in its own words, so the same unhealthy run used to read
differently depending on who was executing it.

`run_health_summary/v1` is the one answer shape. It is a read-only projection:

```sh
omh runtime health-summary --input run_health_input.json [--json]
```

A run that dispatched, explored, then failed its tests twice reads like this
(the `Boundary:` and `--json` footer lines are elided):

```
Run health summary (OMH projection)
Run: run-834
Owner: claude-code (progress lane: yes, evidence ceiling: verified)
Observed events: 6 (observed at 9000 ms)
Freshness: fresh (idle 3000 ms, stale after 300000 ms)
Failure class: verification_failed
Total duration: 5000 ms
Phase durations:
- dispatch: 1000 ms
- execution: 1000 ms
- verification: 1000 ms
Counts:
- retries: 1
- evidence gaps: 0
- unobserved phases: 1
Efficiency claim: unclaimed (baseline: none, evaluator: none, gate: no_named_baseline_and_evaluator)
```

The retry is the second `tests_started`: it moves the run backwards through the
phase order, which is what a retry is regardless of which word the owner used
for it. The unobserved phase is `completion` — nothing said the executor
finished, which is exactly why the run is worth asking about.

**One vocabulary, whatever the owner.** The projection runs over *normalized*
progress events, never over raw per-owner event shapes. A codex run narrating
`dispatch_to_executor / item.completed / turn.completed` and a Claude Code run
narrating `system / assistant / result` normalize to the same three words, so
they produce byte-identical summaries apart from the owner attribution block.
`health_digest` is that equality in one comparison — it deliberately excludes
the owner, so two owners agreeing is one `==`.

The equality is not vacuous. An owner whose stream this repo cannot read
carries a lower evidence ceiling, so an `omo-runtime` `full_tests_passed`
normalizes to `unmapped_source_event` rather than `tests_passed`. That run gets
a different summary, with an evidence gap counted where a verification would
otherwise have been claimed. That is the correct answer, not a gap to close by
guessing.

**Three absences, and none of them is a number.** Every metric is a
`{state, value, reason}` triple:

| state | meaning | value |
| --- | --- | --- |
| `observed` | both bounds were observed, with clocks | the number, possibly a genuine `0` |
| `unknown` | the EVENT that bounds the metric was never observed | `null`, plus the reason |
| `unavailable` | the event was observed but carried no clock | `null`, plus the reason |

A phase nothing later closed stays `unknown`. Closing it with the observation
instant is the one estimate a projection like this is tempted to make, and it
would turn an in-flight run into a measured one. Nothing substitutes the
observation instant, the last event, or a neighbouring phase for a bound it did
not observe — for the same reason an absent token count on the board renders
`unknown` and never `0`.

A run with nothing observed reports every metric as `unknown`, not `0` retries
and `0` evidence gaps. Zero retries is an observation; nobody made it.

**No efficiency claim without two names.** `efficiency_claim.direction` may be
`unclaimed`, `improved`, `regressed`, or `unchanged`, and anything other than
`unclaimed` requires both a named `baseline_ref` and a named `evaluator_ref`.
The rule is enforced twice: the parser refuses to build such a payload, and
`validate_run_health_summary` refuses to read one back, so a hand-edited record
claiming "faster" with nobody named is rejected rather than rendered. `gate` is
derived from the two refs, so it cannot be hand-set to agree with the claim.

**Deterministic.** The module reads no clock. The observation instant arrives
as `observed_at_ms` on the input, and `health_digest` excludes it along with
every field derived from it (`idle_duration_ms`, `staleness`), so comparing two
runs' health never turns into comparing two wall clocks. The validator
re-derives every metric, the staleness verdict, the claim gate, the owner
attribution, and the digest from the stored observations.

### Asking the same question about a fan-out or paired run

The input file above assumes someone already assembled one. A fan-out run can
now record its own lifecycle while it dispatches, and the same command reads it
back by id.

Agent/operator surfaces:

```sh
omh coding fanout dispatch <fanout-id> --goal-file goal.txt --health-events
omh runtime health-summary --run-id <fanout-id> [--json]
omh runtime health-summary --run-id <paired-decision-id> [--json]
```

`--health-events` is off unless typed, and `--no-health-events` states the
default explicitly. When it is on, dispatch appends bounded metadata-only
lifecycle observations to the run's own
`critical_path_health_events.jsonl` inside that fan-out's contract directory:
queued, started, and finished marks for units, retries, verification, and the
review phase. Each event carries a task id, its dependencies, a resource class,
a phase, the observed stage revision, a retry counter, a monotonic millisecond
stamp, and, on a finished event, a terminal status from a closed vocabulary.
Executor, model, and environment identify the aggregate projector
(`fanout_dispatch`, `frozen_contract`, `omh`); they do not infer which provider
caused a delay. There is no prompt, output, path, or free text in the journal.

`--run-id` then projects that journal into a committed `critical_path_health/v1`
section and upgrades the record to `run_health_summary/v2`. The section reports
wall-clock, active, queue, and critical-path milliseconds, peak concurrency,
overlap savings, repeated cost, stale count, cleanup tail, and reused task
count, and it carries `privacy: "metadata_only"`. `--input` still reads a
`run_health_input/v1` or `/v2` file for callers that assemble one themselves,
and the two flags are mutually exclusive.

Three properties are worth knowing before quoting the numbers:

- **The typed journal wins, and its absence is not an error.** A run dispatched
  without `--health-events` has no journal, so the projector falls back to the
  observation journal it already keeps. Dispatch is the only timestamped
  process-start evidence there, so a fallback projection is coarser by
  construction.
- **An unreconcilable lifecycle reports gaps, not metrics.** A dependency cycle
  or an out-of-order dependency leaves `metrics` as `null` and lists explicit
  `evidence_gaps` entries naming the task and the reason. A malformed or
  hand-edited journal line does the same. The reader caps bytes, line length,
  and record count before parsing; crossing a bound yields
  `health_event_journal_limit`, no partial event set, and no metrics. The
  projection would rather say what it could not reconcile than average its way
  past it.
- **The owner is recorded as `fanout`, deliberately.** This reads an aggregate,
  not one named executor's progress stream, so the committed section stays the
  only place its timings can be claimed from.

Confirmed paired-run execution records the same bounded event schema
automatically: every cell is queued before admission, starts after its
global/executor/provider/shared-resource gates open, and finishes with its
terminal state; worktree cleanup is a separate dependency-bound cleanup node.
The aggregate identity is `paired_run` / `frozen_matrix`, while resource rows
retain the recorded executor class. `--run-id <decision-id>` detects that
journal and projects it without requiring a fan-out contract or a hand-authored
intermediate file.

## Reviewing the integrated result, in four lanes at once

A unit passing its own verification says nothing about the combination. The
final-review wave is the shape for reviewing what integration produced, and its
point is that four reviewers looking at four different things cannot quietly
look at four different revisions.

Four lenses are declared in a fixed reporting order: `requirement`, `quality`,
`safety`, `real_surface`. They run concurrently within the configured limits,
and every lane is bound read-only to one immutable 40-hex integrated revision.
A lane that mutates anything, or that reports an observation from any other
revision, is refused rather than merged into the aggregate.
The fan-out hook also probes the clean integrated tree before and after the
wave and records one execution reference per observed lane. A complete-looking
engine result with no matching lane observations, or a dirty or changed
checkout after review, is `BLOCK`, never `PASS`.

The wave reduces to exactly three verdicts:

| Verdict | When |
| --- | --- |
| `PASS` | integration is green, producer evidence exists, and every lane completed at that exact revision |
| `HOLD` | integration is not green, producer evidence is missing, or a lane has not finished yet |
| `BLOCK` | the revision is not immutable, a lane drifted off it, mutated, went missing, went stale, failed, timed out, or was cancelled |

The verdict is derived from lane states in lens order, so the blocking lens is
named rather than guessed, and remediation invalidates the wave instead of
patching a stale lane back into a pass. Two boundaries follow. A `PASS` is
review evidence at one revision and nothing more: it is not CI, not
merge-readiness, and not merge, and no OMH command merges anything.

The normal operator path is explicit:

```sh
omh coding fanout dispatch <fanout-id> --goal-file goal.txt \
  --run-verification \
  --integration-worktree <clean-checkout> \
  --integration-revision <HEAD-tree-sha> \
  --final-review \
  --hermes-provider <provider> --hermes-model <model>
```

The built-in adapter reuses four sanctioned Hermes children, one per lens.
Each child receives its own detached checkout whose commit/tree is rechecked
against the integrated revision, whose filesystem write bits are removed
before spawn, and whose path is removed in `finally`. A child that bypasses
the write denial still touches only its disposable checkout, and any resulting
Git change blocks that exact lane before cleanup; the integrated checkout is
never its working directory. Only an exact `<verdict>PASS</verdict>` or
`<verdict>FAIL</verdict>` response is interpreted; missing or malformed output
blocks the lane. Without `--final-review`, the existing dispatch result is
unchanged, and caller-injected engines remain the extension seam.

## Dispatching a committed paired-run decision

Comparing two arms, a baseline and a variant, across a task matrix is easy to
turn into a machine that quietly launches things. This surface is built so that
it cannot.

Operator/maintainer surface. Normal users never touch it; they describe the
comparison they want to Hermes.

```sh
omh coding paired-run dispatch --decision decision.json --dry-run
omh coding paired-run dispatch --decision decision.json --confirm-dispatch \
  --task-file task-a=task-a.txt --repo . --provider <provider>
```

`--dry-run` parses a committed `paired_run_decision/v1` document, builds the
plan, prints it, and launches nothing. Without `--dry-run`, dispatch refuses
unless `--confirm-dispatch` is typed. A confirmed Hermes matrix then reuses the
already-sanctioned Hermes-child process boundary; it is not a third subprocess
path. Each `--task-file TASK_ID=PATH` is read through the bounded no-follow
reader, checked against the decision's input digest, held only in memory, and
delivered to the child over stdin. `--repo` must resolve the decision's exact
40-hex execution commit, and each invocation atomically reserves a unique
parent before any cell starts. Every cell worktree lives under that parent;
cleanup refuses any path the invocation did not reserve, so two concurrent
dispatches of the same decision cannot remove each other's workspace.
Independent cells run with a derived global/executor/provider ceiling of two;
a shared-resource key still serializes only the cells that name it. The
Hermes-child bridge's normal
single-dispatch guard remains the default for every other caller, while this
confirmed matrix path opts into the paired-run scheduler's own bounded guard.

The built-in receipt-capable adapter currently supports decision arms whose
executor is `hermes`. A Codex, Claude Code, or generic arm is refused before
Git or child execution rather than silently substituted. Those executors use
the same public runner boundary when a caller supplies an adapter capable of
returning the authenticated receipt contract. This is an explicit capability
boundary, not a default-to-Hermes rule.

Each confirmed run also writes bounded metadata-only critical-path events under
the paired decision id. The same `omh runtime health-summary --run-id
<decision-id>` surface therefore reports observed queueing, execution, and
cleanup timing for evaluation cells directly; no task body or child output is
part of that journal.

A timed-out or failed Git worktree command is contained as one `crashed` cell.
The adapter attempts removal of the known partial path, records the cleanup
result on that cell and in the health journal, and continues the matrix rather
than leaking a raw subprocess exception.

The plan is derived from the frozen decision, never from CLI overrides. Arms,
tasks, executors, models, and the maximum dispatch seconds come out of the
parsed document, so an operator cannot widen a committed comparison from the
command line. What the payload states:

- **Isolation.** Each cell gets its own workspace id, plus the shared-resource
  mode, the shared-resource keys in play, and the launch waves those keys force.
  Cells that contend serialize into separate waves rather than racing.
- **Budgets.** Global, per-executor, and per-provider concurrency, plus local
  and provider cost/time bounds. Serial and parallel runs of the same matrix
  stay scope-equivalent; parallelism changes the peaks, not what each cell may
  touch.
- **The boundary itself.** `local_runner_boundary` records that a confirmed
  dispatch uses an explicit confirmed adapter, that the built-in Hermes adapter
  reuses the sanctioned child bridge, and that `paired_run_decision/v1`
  carries no raw task content.

Evidence closes the loop in one direction only. An execution matrix becomes an
observed decision through an authenticated receipt fan-in, and every cell must
present a verified receipt bound to its own task, arm, and scope. Missing,
stale, mismatched, unauthenticated, partial, timed-out, cancelled, crashed,
rate-limited, and cleanup-failed cells each block the fan-in rather than
degrading it to a weaker result. Behavioral verdicts stay explicit request
values: an exit code, a process status, or anything the child printed never
decides behavior.

## Showing the shape of one prepared artifact

A prepared handoff, plan, status, or review can be a wall of structured text.
The common facade has typed projectors for those registered schema families.
The persisted wrapper path supplies prompt and runtime handoffs plus every
recorded `coding_briefing/v1` artifact: acceptance/verification, status,
evidence gaps, next action, and issue/PR follow-up. Each keeps its exact source
schema and field refs rather than being relabeled as a plan or review. A lens
whose recorded fields are insufficient remains unavailable. The shape view
answers "what does this supported source look like" without pasting unrelated
artifact content into chat.

People stay in chat and ask Hermes about the work it prepared. The projection
is a wrapper-facing selected action, so a wrapper that wires it can answer that
question with a picture; what is observed today is the agent/operator command
below reaching the same action:

```sh
omh runtime artifacts show-shape --artifact-id <id> --lens flow --json
```

`--artifact-id` is the stable id the selected work-artifact action already
hands back. `--session-id` is optional: without it, the command picks the most
recently updated current wrapper session that contains that stable id, with the
session id as the tiebreak so the selection is deterministic. The closed lens
vocabulary is `flow`, `structure`, `change`, `state`, and `ownership`; each
source schema exposes only the subset its recorded fields can support.
`--format` defaults to `ascii`.

**Every node and edge cites its source.** The projection reads recorded fields
and renders them; it infers no relationship that the source did not state, and
a node or edge without source refs does not get drawn. Bullets and graph size
are bounded, and what got cut is reported as explicit omissions rather than
silently dropped.

**Unavailable is a first-class answer with a reason.** The rendering facade is
the single availability authority, so each of these comes back as
`availability: "unavailable"`, a named reason, and an empty body:

| Reason | Means |
| --- | --- |
| `unknown_artifact_id` | no artifact in the session carries that id |
| `source_not_recorded` | the artifact exists in the index but its source was never recorded |
| `unsupported_lens` / `unsupported_format` | the requested lens or format is outside the closed vocabulary |
| `unsupported_source_schema` | the selected artifact has no registered structured projector |
| `lens_not_supported_for_source_schema` | the schema is known but its fields cannot support that lens |
| `format_requires_change_lens` | `--format diff` was asked for on a lens other than `change` |
| `mermaid_capability_not_observed` | Mermaid was requested where no Mermaid capability has been observed |
| `render_budget_exhausted` | the bounded body would have exceeded its character budget |

Mermaid is the one worth stating twice. It is never enabled by a flag being
present or by a CLI being able to spell it; it stays unavailable until a
capability is actually observed, so a diagram is never claimed for a surface
that cannot render one.

The result carries the artifact's own `evidence_state`, so a shape rendered
from a prepared handoff reads `prepared_not_observed` on its face. The action
leaves `next_action` at `show_status`: looking at a shape never advances the
session toward dispatch, and an `unchanged` change marker reports only that the
supplied source carried no observed change marker, not that two sources are
equal.

## Boundary

A status board is observed activity metadata. It is not result, verification,
review, CI, merge-readiness, or merge evidence, and a unit appearing as
`running` is not proof that it will finish.

A receipt is narrower still: it is one acting surface's observation of one
external effect, and it proves nothing about any other effect.

A language diagnostic record is narrower again: it is one language-diagnostic
check over one workspace revision interval. A clean result means no new
diagnostics were observed in that check, and nothing more.

A run health summary is narrow in a different direction: it explains observed
events and settles none of them. It is metadata-only observation, not execution,
verification, review, CI, merge-readiness, or merge evidence, and an `improved`
efficiency claim on one is a comparison a named evaluator made against a named
baseline — not a measurement OMH performed.

A critical-path health section is the same claim with timings attached. It
describes how a recorded lifecycle laid out in time, and `null` metrics beside
listed evidence gaps are its honest answer, not a degraded one.

A final-review verdict covers one immutable revision through four read-only
lenses. `PASS` is review evidence at that revision; it is not CI, not
merge-readiness, not merge, and nothing in OMH merges a branch.

A paired-run plan is prepared intent. `--dry-run` output describes cells that
have not launched, and a confirmed dispatch is still only what the explicit
local adapter did, attested by receipts, over one committed decision. It is not
a general quality claim about either arm.

An artifact shape is a picture of recorded fields. It projects what a source
stated, and it settles nothing about whether that source was dispatched, run,
verified, reviewed, merged, or read by anyone.
