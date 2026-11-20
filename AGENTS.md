# OMH Agent Contract

This file is the operating contract for every coding agent on oh-my-hermes
(Codex, Claude Code, Hermes runtime/handoff paths, generic executor profiles):
product boundaries, delivery grain, PR reports, commit trailers. `CLAUDE.md`
holds the engineering manual (commands, gates, the generated-artifact map,
pitfalls) for all of them; read it before running gates or editing generated
output. `CONTEXT.md` is the glossary. Detail lives in
`docs/IMPLEMENTATION-BOUNDARIES.md` and `docs/ENGINEERING-PITFALLS.md`.

## Product Direction

Read `docs/DIRECTION.md` before changing architecture, workflow behavior,
wrapper contracts, generated skill guidance, or coding delegation semantics.

OMH is a Hermes-native wrapper orchestration layer. Hermes owns chat intake,
clarification, source-backed research, planning, and status narration. Main
coding work goes to the selected coding owner through explicit prepared
handoffs and observed evidence.

Codex, Claude Code, and Hermes runtime/handoff paths are all first-class
product surfaces. Feature design, contracts, docs, setup, memory recall, and
status/reporting consider all three unless a change is explicitly scoped to
one executor. Name the selected owner (`codex`, `claude-code`, `hermes`, a
runtime profile, or a generic executor); use Codex-specific wording only for
Codex-only lifecycle features. Where support differs, document the difference
as a capability boundary.

Do not turn OMH into a hidden Hermes runtime patch, transport bot, network
service, LLM router, or secret coding executor. Every sanctioned exception is
explicit and opt-in, never hidden and never a default, and is listed under
Implementation Boundaries.

## Command Audience

Natural-language Hermes chat is the normal product surface. Most people should
only need `omh setup`, `omh update`, and `omh doctor`; removal and repair
commands are exceptional maintenance paths, not the day-to-day OMH workflow.
Every other command group is a control plane for Hermes Agent, wrappers,
coding agents, automations, and maintainers; public docs label its audience
(`docs/DIRECTION.md`, Command Audience).

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
Use the repository PR template and fill every relevant section:

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
  features unless the user explicitly approves a scoped integration. Each
  approved one is explicit and opt-in, and follows.
- **Hermes-native child boundary** (`omh coding hermes-child dispatch`): one
  isolated local Hermes single-query process (`hermes chat --query-file -`,
  the Hermes transport that reads a prompt from stdin). It requires
  `--confirm-dispatch`, takes prompts only through stdin/files, enforces a
  depth-one recursion limit (OMH dispatch depth; inside a paired-run arm,
  Hermes' own one-level `delegate_task` children are allowed when the run's
  `--arm-toolsets` names `delegation`), runs safe-mode file tools by default, records
  authenticated `routing_observation/v1` evidence, and never runs
  automatically. Two front doors reuse it without adding a process authority:
  - `omh coding paired-run dispatch` for confirmed evaluation cells: one
    digest-matching task file per frozen task, task bytes over child stdin,
    detached per-cell worktrees under an atomically unique invocation-owned
    parent, signed evaluation bindings, removal of only the paths that
    invocation reserved, and no persisted task body. Both arms run
    `--toolsets file,skills`; only the explicit `--arm-toolsets` opt-in may
    add `terminal` and `delegation`, to both arms identically, signed into
    each cell and checked at fan-in, with Hermes' command approval left on;
    with `delegation` both arm homes pin the same child cap and the arm's
    model for every child, and fan-in refuses a cell whose child sessions ran
    another model. Executors without a
    receipt-capable adapter are refused without substitution;
    caller-injected adapters stay the executor-neutral seam. It is the one
    caller that leaves safe mode: each arm runs a declared, receipt-signed
    arm setup in its own disposable Hermes home (the variant with the OMH
    plugin, a disposable OMH home and its frozen `exposed_skills`, the
    baseline with neither; both the run's declared toolsets), served by a
    harness-owned `hermes gateway run` in its own process group that the
    invocation warms before timing and stops on exit, never a service
    manager. A custom provider is declared by base URL (https, or http to a
    loopback host), API mode and key variable name; its secret arrives only
    by environment. Fan-in refuses a cell whose signed setup contradicts its
    arm.
  - `omh coding fanout dispatch --final-review`, after dispatcher-observed
    integration GREEN: the explicit flag, a clean integrated tree, named
    Hermes provider/model settings; four read-only lenses in disposable,
    write-denied detached worktrees under fixed concurrency, parsing only a
    closed verdict token, unable to merge or mutate the integrated checkout.
- **The other scoped exceptions**, each pinned by
  `tests/test_handoff_safety_contract_enforcement.py` and stated in full in
  `docs/IMPLEMENTATION-BOUNDARIES.md`; read it before touching one:
  - **Fanout dispatch bridge** (`omh coding fanout dispatch`, `omh coding run`)
    and **Fanout diagnostics** (`--diagnostics`).
  - **Local proofreader** (`src/tui/proofread.py`, loopback LanguageTool).
  - **`omh_jev_ask`** (`src/plugin_bundle/omh/jev_ask_client.py`), a scoped
    network integration.
  - **The OMH TUI's update notice** (`src/tui/update_notice.py`), a scoped
    network integration.
  - **Show-reel provider scripts** and the **Channel watch collector**: inert
    package data only the user runs.
  - **The OMH TUI** (bare `omh`) and its gateway child: a foreground frontend over
    Hermes' own gateway; read
    [`docs/OMH-TUI-BOUNDARY.md`](docs/OMH-TUI-BOUNDARY.md) before touching
    `src/tui/`.
  - **omher** (`apps/omher/`): not core; every widening is a numbered rule in
    [docs/OMHER-BOUNDARY.md](docs/OMHER-BOUNDARY.md), pinned by
    `tests/test_omher_boundary.py`; read it before touching the app.
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
  `--language` or `OMH_LANG`; never auto-detect the OS locale. The TUI and CLI
  frame stays English whatever language the conversation is in
  (`docs/OMH-TUI-BOUNDARY.md`, Frame language).
- OMH is an open-source product for every user on every terminal. Design a
  fix or a look for all of them, never tuned to the maintainer's own machine,
  terminal, theme or language. A capability-detected enhancement may sit on
  top of a fix that works everywhere, but never replaces it.
- Reply to Korean user messages in polite Korean; no banmal or casual endings
  unless the user asks for that tone. Name what exists, what is missing, and
  the complete target behavior, rather than process labels.
- Keep public claims conservative and test-backed.
- No new dependency unless the user approves it and its packaging story.

## Verification

Use the smallest check that proves the claim, then broaden when the touched
surface is shared. Before claiming done, run the gates listed in `CLAUDE.md`
(Build & Test) and the full suite; for a docs or contract change those include
`uv run python -m omh.cli docs navigation --check` and
`uv run python -m omh.cli docs claims --check --json`. For direction, docs,
generated skill, wrapper contract, lifecycle, or runtime artifact changes, add
or update tests that lock the public contract.

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

A headline number in a commit, PR, or report names the arm, the corpus, the
selection rule, and the committed artifact it came from; without those it is
`prepared_not_observed`, not a result.

## Repository Maintenance Procedures

When asked to triage, label, review the backlog, or onboard a model, read the
matching file and follow it rather than improvising; each states its own
allowlist and dry-run default, and none runs in CI.

| Procedure | File |
| --- | --- |
| Triage sweep | `docs/TRIAGE-SWEEP.md` |
| Review sweep | `docs/REVIEW-SWEEP.md` (against `REVIEW.md`) |
| Model onboarding | `docs/MODEL-ONBOARDING.md` |

`.github/labels.yml` is the entire label allowlist; never apply or create a
label outside it.

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
