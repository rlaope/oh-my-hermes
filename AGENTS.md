# OMH Agent Contract

The operating contract for every coding agent working on oh-my-hermes: Codex,
Claude Code, Hermes runtime/handoff paths, and generic executor profiles.
`CLAUDE.md` is the engineering manual for all of them, not only Claude Code
(commands, gates, the generated-artifact map, known pitfalls); read it before
running gates or editing generated output. `CONTEXT.md` is the glossary.

## Product Direction

Read `docs/DIRECTION.md` before changing architecture, workflow behavior,
wrapper contracts, generated skill guidance, or coding delegation semantics.

OMH is a Hermes-native wrapper orchestration layer. Hermes owns chat intake,
clarification, source-backed research, planning, and status narration. Main
coding work goes to the selected coding owner through explicit prepared
handoffs and observed evidence.

Codex, Claude Code, and Hermes runtime/handoff paths are all first-class
product surfaces. A user may pick one coding owner for a task, but feature
design, contracts, docs, setup, memory recall, and status/reporting consider
all three unless a change is explicitly scoped to one executor. Name the
selected owner (`codex`, `claude-code`, `hermes`, a runtime profile, or a
generic executor); use Codex-specific wording only for Codex-only lifecycle
features. Where support differs, document the difference as a capability
boundary.

Do not turn OMH into a hidden Hermes runtime patch, transport bot, network
service, LLM router, or secret coding executor. Every sanctioned exception is
explicit and opt-in, never hidden and never a default, and is listed under
Implementation Boundaries.

## Command Audience

Natural-language Hermes chat is the normal product surface. Most people should
only need `omh setup`, `omh update`, and `omh doctor`; removal and repair
commands are exceptional maintenance paths, not the day-to-day OMH workflow.

`omh chat`, `omh coding`, `omh runtime`, `omh memory`, `omh loop`, `omh goal`,
`omh harness`, `omh capabilities`, `omh release`, `omh state`, and similar
control-plane groups exist for Hermes Agent, wrappers, coding agents,
automations, and maintainers. Public docs may show them as integration or
operator references, labeled with their audience, never as something a normal
user must memorize. Describe the human action as an intent or outcome (asking
Hermes to prepare coding work) and keep the backend command in the
agent-facing reference.

## Delivery Grain

One user goal should normally produce one PR.

Plan, explain, and report at the full user-goal grain. Do not frame a
recommendation as "the first PR", "initial PR", "first slice", or a similar
partial unit unless the user asks for phased delivery or an independent
release/rollback boundary forces a split. When a split is forced, state the
complete target capability first, then the split reason and the remaining gap.

Planning docs, tests, implementation, code-review fixes, CI fixes, and small
follow-up docs for the same goal belong in the same PR, as focused commits.
Do not split review feedback or small follow-up fixes into new PRs merely
because a previous commit exists. Split only when the next change is a
different user-facing goal, has independent release or rollback value, would
make the current PR too risky to review, is blocked by an external decision,
or the user asks for separate PRs.

When the user asks to merge, finish review fixes in the current PR first,
rerun verification, wait for required checks, then merge if authority is
clear.

## Pull Request Reports

PR descriptions must read like a useful feature report, not a terse changelog.
Use the repository PR template and fill every relevant section with concrete,
reviewable detail:

- What capability, workflow, command, or contract changed.
- Why the change exists: the user problem, product gap, or operational failure
  behind it.
- What the user or operator can do after the change that they could not do
  before.
- How it works at the boundary level: modules, commands, generated files,
  persisted state, or wrapper contracts touched.
- What verification was actually observed: CI, targeted tests,
  generated-output checks, dry-runs, or manual Hermes/TUI gaps.
- What risks, rollout notes, compatibility concerns, or follow-ups remain.

Prefer a short narrative plus bullets that make the feature's origin, behavior,
and evidence obvious to a reviewer reading the PR without the chat history.

## Implementation Boundaries

- No LLM, API, Discord, Slack, GitHub, or network calls inside core `omh`
  features unless the user explicitly approves a scoped integration. The
  approved ones follow.
- **Fanout dispatch bridge** (`omh coding fanout dispatch`, plus its
  `omh coding run` entry that builds and dispatches a one-unit contract
  through the same engine): an explicit operator command that spawns LOCAL
  agent CLIs (they make their own network calls; omh makes none) in per-unit
  worktrees against a frozen `fanout_contract/v2`, recording every spawn and
  exit as observed journal evidence. It never runs by default, never merges
  branches, never persists raw prompts under `.omh`, and never executes
  outside an explicit `dispatch`/`run` invocation against an explicitly named
  owner. Chat-prepared handoffs stay prompt-only for prompt-only profiles.
- **Hermes-native child boundary** (`omh coding hermes-child dispatch`): one
  isolated local Hermes single-query process (`hermes chat --query-file -`,
  the Hermes transport that reads a prompt from stdin). It requires
  `--confirm-dispatch`, takes prompts only through stdin/files, enforces a
  depth-one recursion limit and safe-mode file tools, records authenticated
  `routing_observation/v1` evidence, and never runs automatically. Two front
  doors reuse it without adding a process authority:
  - `omh coding paired-run dispatch` for confirmed evaluation cells: one
    digest-matching task file per frozen task, task bytes over child stdin,
    detached per-cell worktrees under an atomically unique invocation-owned
    parent, signed evaluation bindings, removal of only the paths that
    invocation reserved, and no persisted task body. Executors without a
    receipt-capable adapter are refused without substitution;
    caller-injected adapters stay the executor-neutral seam.
  - `omh coding fanout dispatch --final-review`, after dispatcher-observed
    integration GREEN: the explicit flag, a clean integrated tree, named
    Hermes provider/model settings; four read-only lenses in disposable,
    write-denied detached worktrees under fixed concurrency, parsing only a
    closed verdict token, unable to merge or mutate the integrated checkout.
- **Fanout diagnostics** (`omh coding fanout dispatch --diagnostics`): only
  the closed local diagnostic command set, after producer verification GREEN.
  Binaries come from `PATH`; no shell text or user-selected executable;
  detached fixed-revision worktrees; messages and absolute paths stripped;
  child environment redacted; concurrency, time and output capped; the
  provider's whole process tree always reaped and every temporary worktree
  removed. On Windows the provider starts suspended, enters a kill-on-close
  Job Object, and resumes only after ownership succeeds; clean evidence
  requires the Job Object to report zero active processes.
- **`omh_jev_ask`**, the one scoped network integration: the plugin tool POSTs
  typed questions to Jev with the user's own key and returns probabilities.
  It runs only when the person's own message for that turn names Jev (a
  per-turn marker `pre_llm_call` records; otherwise it returns
  `consent_not_observed` and opens no socket), and only when a route
  resolves: `TYPESAFE_API_KEY`, or `OPENROUTER_API_KEY` plus
  `{"openrouter_route": true}` in `<omh_home>/jev/settings.json`, which OMH
  never writes. Stdlib only, HTTPS only, a fixed two-host route table, no
  redirects, bounded bodies, no retry after a sent request times out. It
  persists no key, `state`, question text, or reply; one metadata-only ledger
  row per ask. `src/plugin_bundle/omh/jev_ask_client.py` is the only
  in-process network client in `src/`, and only `tools/jev_ask_tool.py` may
  import it. Third-party Jev plugins are never called, and `omh doctor` reads
  no credential value.
- **Show-reel provider scripts**: `src/skills/show_reel_toolkit/scripts/eleven.py`
  and `narrate.py` (ElevenLabs TTS/STT/SFX/music by spawning `curl`, key from
  `ELEVENLABS_API_KEY` only, passed on curl's stdin) and `codex_ref_image.sh`
  (the user's signed-in codex CLI) ship as inert package data. Only the user
  runs them, with their own credential; without it they exit 2 and send
  nothing. OMH core, install, update, routing and doctor never import or
  execute them; `eleven.py` is in INVARIANT 1's `PROCESS_SPAWN_ALLOWLIST`, and
  the companion-nonexecution tests cover both Python scripts.
- **The OMH TUI** (bare `omh`) is a foreground frontend over Hermes' own
  gateway, not an execution surface: it relays only what the person types,
  answers no request on their behalf, and makes no model call. Its gateway
  child, `src/tui/attach/gateway_attach.py`, runs on Hermes' interpreter under
  INVARIANT 2's `HERMES_INTERPRETER_SCRIPTS` allow list. Read
  [`docs/OMH-TUI-BOUNDARY.md`](docs/OMH-TUI-BOUNDARY.md) before touching
  `src/tui/`.
- No Hermes core patching.
- Runtime artifacts are local, deterministic, schema-versioned, and
  metadata-only by default.
- Preserve prepared versus observed boundaries. `prepared_not_observed` is not
  execution, review, CI, merge-readiness, or merge evidence.
- Wrapper sessions own chat continuity and plan decisions only. Linked runtime
  runs own handoff, dispatch, execution, verification, review, CI, and merge
  evidence.
- Project memory lives under `.omh/memory/` as reviewed OMH-local prepared
  context. Keep candidates separate from approved records, preserve
  review-first defaults, and never present recall packs as execution, review,
  CI, merge, or Hermes internal-memory evidence.
- Never hand-edit a generated file or marked region: edit its producer,
  regenerate, and commit producer and output together (the map is in
  `CLAUDE.md`, Generated Artifacts Map; every gate is byte-exact).

## Coding Style

- Code, docs, commit messages, PR text, and user-facing CLI output are
  English by default. Localized output (ko/ja/zh) is explicit opt-in through
  `--language` or `OMH_LANG`; never auto-detect the OS locale.
- Reply to Korean user messages in polite Korean; no banmal or casual endings
  unless the user asks for that tone. Name what exists, what is missing, and
  the complete target behavior, rather than process labels or "small first
  PR" framing.
- Keep public claims conservative and test-backed.
- No new dependency unless the user approves it and its packaging story.
- A routing or policy change ships negative cases beside its positive ones
  and moves the reviewed count pins in the same commit (details in
  `CLAUDE.md`, Code Conventions).

## Verification

Use the smallest check that proves the claim, then broaden when the touched
surface is shared. Before claiming done, run the gates listed in `CLAUDE.md`
(Build & Test) and the full suite; for a docs or contract change those include
`uv run python -m omh.cli docs navigation --check` and
`uv run python -m omh.cli docs claims --check --json`.

For direction, docs, generated skill, wrapper contract, lifecycle, or runtime
artifact changes, add or update tests that lock the public contract.

CodeGraph (`docs/CODEGRAPH.md`) is a navigation aid before broad exploration;
its index under `.codegraph/` is machine-local, and only
`.codegraph/.gitignore` is committed. Its output is prepared context, never
execution, review, CI, merge-readiness, or merge evidence.

### Reporting Our Own Numbers

A rate OMH computes about itself is a claim, so it carries what it divided.
Every percentage in a payload uses the `omh_reported_rate/v1` shape
(`src/quality/reported_rate.py`, checked by `reported_rate_shape_errors()`):
the buckets its numerator summed, what its denominator counted, and every
observation class excluded before either count. Two traps:

- **An empty denominator is not 0%.** `max(1, count)` in a divisor turns an
  empty corpus into a confident zero. Report `percent: null` with basis
  `no_observations`, and let an unmeasured rate fail its target rather than
  pass it.
- **A composed numerator says so.** When a rate sums more than one outcome
  bucket, name them in the payload, not only in a text formatter; every
  non-human consumer reads the JSON.

The same rule governs prose: a headline number in a commit, PR, or report names
the arm, the corpus, the selection rule, and the committed artifact it came
from. A number without those is `prepared_not_observed`, not a result.

## Repository Maintenance Procedures

Three maintainer procedures are executor-neutral: any coding agent runs them
the same way. When asked to triage, label, review the backlog, or onboard a
model, read the matching file and follow it rather than improvising. Each
states its own allowlist, dry-run default, and boundaries; the two sweeps are
manual and default to a dry run, and none runs in CI.

| Procedure | File | What it does |
| --- | --- | --- |
| Triage sweep | `docs/TRIAGE-SWEEP.md` | Labels issues and PRs that have no `area/` label, deriving a PR's areas from its changed files against `.github/labels.yml` |
| Review sweep | `docs/REVIEW-SWEEP.md` | Reviews PRs carrying no review at their current head commit, against `REVIEW.md` |
| Model onboarding | `docs/MODEL-ONBOARDING.md` | Moves a new model generation or sibling through recognition, research, calibration, both routing lanes, pricing, machine placement, gates, and the measurement close |

- `REVIEW.md` defines a blocking finding in this repository. Nothing loads it
  automatically; a reviewer reads it.
- `.github/labels.yml` is the label manifest and the path globs that map a
  changed file to an `area/` label. It is the entire allowlist; never apply or
  create a label outside it.
- `.claude/skills/triage-sweep/`, `.claude/skills/review-sweep/` and
  `.claude/skills/model-onboarding/` only make these reachable as Claude Code
  slash commands. They defer to the files above, which stay the single source
  of truth.

## Git And Commits

Branch before the first edit, unless the current branch is already dedicated to
that exact user goal. Name the branch by the kind of change, never by the
executor: `feature/<topic>` for a new or extended capability, `fix/<topic>`
for a defect, `omh/<topic>` for everything else (docs, release, maintenance,
measurement). Existing branches keep their names.

Every commit carries DCO signoff and the Lore-style trailers:

```text
Constraint: <external constraint that shaped the decision>
Rejected: <alternative considered> | <reason>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <forward-looking warning>
Tested: <what was verified>
Not-tested: <known gaps>
Signed-off-by: <name> <email>
```

Never revert user changes or unrelated untracked files. If an unrelated file is
dirty, leave it alone and report it.
