# Opt-in work campaigns

This is an **agent/wrapper/operator reference**, not a new everyday human
command. Ask Hermes to use `campaign-orchestrator` only after accepting a goal,
acceptance criteria, exact write boundaries, verification target, and at least
two separable units. Ordinary chat and ordinary `ulw-work` do not enter this
code path. There is no campaign plugin tool, classifier, default prompt
expansion, provider client, scheduler, or daemon.

The agent-facing recipe is the on-demand skill reference
`skills/ulw-work/references/campaign-orchestrator.md`, generated from
`src/skills/render.py`. Hermes loads it only after the user has named
`campaign-orchestrator`; the always-loaded `ulw-work` skill body carries no
pointer to it and is byte-identical with or without the reference installed.
This document is the operator and wrapper companion to that reference: it
covers the host boundary, the CLI, and the evidence states in more detail.

## Ownership and host boundary

The normal Hermes chat parent retains its model and narrates progress. One
campaign orchestrator uses the existing configurable `architect` chain
(its shipped head by default). It owns planning, dependency changes, dispatch,
results, conflicts, the broad verification queue, and go/no-go. Workers use
the independently configurable `ultrabrain` chain (its shipped head by default).
Owner and worker model/provider/effort overrides take precedence independently.
Routes describe resolved preparation, not which model actually executed.

`CampaignHostAdapter` in `coding/work_campaign_host.py` is the trusted wrapper
boundary. It must derive the invoking session from host context, atomically
bind each attempt to an immutable route, enforce leaf tools and write scope,
observe execution evidence, and revoke routes/stop tasks on expiry. These are
host capabilities, not model-supplied booleans or prompt promises. No CLI flag
can supply an owner session or declare verification observed.

The root is runnable before the leaves: **no root dependency on unfinished
workers**. Worker dependency edges name actual sibling dependencies only, never
the running orchestrator. The root plans/dispatches the graph and integrates
its results; it is not a reviewer started only after someone else coordinated
the work. The adapter bounds the tree to one root and at most sixteen leaves,
with no recursive leaf delegation, terminal/execute-code escape, continuation
campaign, or leaf broad-suite execution. Host enforcement is required; the
standalone TASK/DELIVERABLE/SCOPE/VERIFY/STOP WHEN text is only guidance.

### Installed Hermes capability boundary

Hermes at `f159e581` has no native per-task model/provider/effort binding for
`delegate_task`. Campaign code never rewrites `delegation.*`, and does not
infer support from a version or schema field.

Kanban has task-local model/provider/effort columns. `bind` observes existing
rows and exact dependency edges through a read-only database connection. It
also inspects an explicit worker profile. The per-task lane overlay a prepared
`create` may carry and the profile-as-envelope rule are recorded in
[`docs/AGENT-BOARD.md`](AGENT-BOARD.md#lane-fields-on-create). However, the actual installed host
resolver adds `kanban` even to a profile listing only `file`. A profile setting
does not prove a scoped leaf sandbox or authenticated verification capture.
The shipped CLI therefore reports `prepared_binding_observed`, **not running**.
`start`/native binding explicitly falls back to the current parent-led path
with the graph intact. Unsupported hosts never silently start a worker.

There is no shipped live execution adapter in this initial contract scope.
A wrapper implementing the full trusted protocol can use the controller;
protocol fixtures prove those transitions, not Fable/Astra execution.
Do not run `hermes kanban daemon` or `dispatch` as a campaign QA shortcut.
The host's `create_task` idempotency lookup precedes its internal transaction;
a capable adapter must use the host's outer write transaction for atomic
lookup/create. A naked concurrent `kanban create` is not a uniqueness proof.

## Operator CLI

The full `omh coding campaign` parser, as currently registered in
`src/commands/work_campaign.py`. Every subcommand also accepts `--json`.

```sh
omh coding campaign prepare --goal GOAL --units UNITS.json --acceptance CRITERION [--acceptance ...] \
  --verify COMMAND --workspace DIR --accept [--spawn-plan PLAN.json] \
  [--owner-model M] [--owner-provider P] [--owner-effort E] \
  [--worker-model M] [--worker-provider P] [--worker-effort E]
omh coding campaign show CAMPAIGN_ID
omh coding campaign start CAMPAIGN_ID
omh coding campaign bind CAMPAIGN_ID [--binding {native,kanban}] [--tasks TASKS.json] [--worker-profile NAME]
omh coding campaign plan CAMPAIGN_ID --units UNITS.json
omh coding campaign dispatch CAMPAIGN_ID --unit UNIT_ID
omh coding campaign accept CAMPAIGN_ID --unit UNIT_ID
omh coding campaign conflict CAMPAIGN_ID --unit UNIT_ID [--unit ...] --invariant TEXT
omh coding campaign resolve CAMPAIGN_ID
omh coding campaign queue-broad CAMPAIGN_ID
omh coding campaign complete CAMPAIGN_ID
omh coding campaign cancel CAMPAIGN_ID
omh coding campaign fail CAMPAIGN_ID
omh coding campaign timeout CAMPAIGN_ID
omh coding campaign recover CAMPAIGN_ID
omh coding campaign fallback CAMPAIGN_ID
omh coding campaign canary [--input OBSERVATIONS.json]
```

`--binding` defaults to `kanban`. `start` and `bind --binding native` are the
same native-activation path, and on the installed host both end in
`fallback_parent_led` (see the capability boundary above). Without `--accept`,
`prepare` is refused by the parser; if the facade is called with any mode
other than `campaign-orchestrator` it returns nothing and the CLI reports
that campaign mode was not selected.

Prepare accepts a JSON list of units, for example:

```json
[
  {"unit_id":"parser","file_scope":["src/parser.py"],"artifacts":["src/parser.py"],
   "acceptance":["parser_cases_pass"],"verification_command":"python -m unittest tests.test_parser"},
  {"unit_id":"format","file_scope":["src/format.py"],"artifacts":["src/format.py"],
   "acceptance":["format_cases_pass"],"verification_command":"python -m unittest tests.test_format"}
]
```

```sh
omh coding campaign prepare --goal 'Accepted goal' --units units.json \
  --acceptance all_checks_pass --verify 'python -m unittest' \
  --workspace /path/to/worktree --accept --json
omh coding campaign show CAMPAIGN_ID --json
omh coding campaign bind CAMPAIGN_ID --tasks existing-host-task-ids.json \
  --worker-profile bounded-worker --json
omh coding campaign bind CAMPAIGN_ID --binding native --json
omh coding campaign cancel CAMPAIGN_ID --json
omh coding campaign canary --json
```

Use `--owner-model`, `--owner-provider`, `--owner-effort` and the independent
`--worker-*` flags for explicit choices. `--spawn-plan` supplies the existing
fanout justification above four units. A binding file maps `orchestrator`
and every unit ID to existing host task IDs. Rows must match attempt keys,
routes, worker assignee, no-retry settings and sibling dependency edges.
The observer never creates or schedules host tasks. `show` emits the stored
record; the Python `kanban_task_manifests` projection supplies the recipe.

CLI identity is the OS-observed invoking wrapper process, not a claimed chat
session. Keep related commands under the same supervising operator/wrapper
process. This CLI identity does not authenticate arbitrary Hermes sessions;
a live wrapper must supply the trusted host adapter instead. The parent may
display/cancel its own run, but cannot impersonate another campaign owner.
Ordinary CLI refusal follows OMH's exit-code-2 convention.

## Evidence, recovery, and limits

Campaign/unit/attempt identities are stable. Records live only under the
selected OMH home's `runtime/campaigns`, capped at 64 campaigns, 64 KiB per
record and 64 recent events. Store saturation fails closed; operators retain
or remove their own terminal records deliberately. No prompt body, transcript,
provider error or raw verification log is stored.

The controller locks the complete read-modify-write operation and records an
unknown attempt before crossing the dispatch boundary. A crash does not mean
the worker did nothing. Unknown attempts cannot be dispatched again. Results
are accepted once, with exact campaign/attempt/task identity, actual contained
artifact paths and matching content digests, observed changed paths, revision
and diff identity, and bounded verification output digest/size plus exit code.
Supplying a plausible summary or `--verification-observed` cannot complete work.

Canonical path spellings (including backslashes) pass through the existing
fanout structural/DAG gate. Overlapping paths and shared invariants freeze the
frontier and name one integration owner. That owner resolves prepared
conflicts through inspected integration evidence without adding another leaf.
Unknown in-flight effects require external reconciliation, never blind retry.
The broad suite is assigned once to the orchestrator after producer fan-in;
completion requires its observed evidence and route cleanup. PR/merge
authorization remains separate.

Completion, cancellation, failure, timeout, exception and restart recovery
expire pending routes and read back ordinary inheritance. Failed cleanup is
reported and can be retried by `recover`; it cannot reopen dispatch. Explicit
parent fallback preserves the graph and never promotes an implementation leaf.

## Canary evidence

The default report has no observations: rates are `percent: null`, never 0%.
`canary --input observations.json` accepts bounded paired baseline/campaign
measurements. Each row's `measurement_provenance` object names an actual `record_path`, matching
SHA-256 `record_digest`, accepted `input_path` and matching `input_digest`, and
`run_ref`. The input is re-read within a 64 KiB cap and its digest must also be
bound into the observation receipt. The
referenced `host_campaign_measurement/v1` receipt must carry the identical
measurement and `execution_source: host_runtime`. Pair selection uses matching
input digests; fixture/prepared/unpaired rows are excluded. Imported receipts
are operator evidence, not cryptographically authenticated provider invoices.
Missing provider accounting stays null. Completion/accepted-unit rates use
`reported_rate` with named buckets and exclusions. No default recommendation
changes automatically, even when an imported comparison is favorable.

Each arm of `work_campaign_canary/v1` emits a `measurement_provenance` list
containing only `source`, `record_path`, `record_digest`, `input_path`,
`input_digest`, and `run_ref`. This receipt-binding metadata is distinct from
the model-selection vocabulary read by `route_provenance()` from
`coding_model_route/*`; it never selects or changes a route. The
canary contract uses `measurement_provenance` on both input rows and output
arms, not the earlier `provenance` spelling; there is no compatibility alias.
Observed failed, cancelled, and unknown outcomes count in the completion
denominator, but not its `complete` numerator. Prepared, fixture, unverified,
and unpaired rows contribute to neither count.

The isolated QA script records actual CLI inputs, host DB pins/idempotency,
toolset resolution, native refusal, concurrency, cancellation and cleanup.
Model execution and measured quality benefit are **not_observed** until
authorized comparable provider campaigns exist. The generated opt-in skill
reference is finalized; the full integration suite remains a separate lead
gate.
