# Campaign Orchestrator Recipe

Load this reference only after the user has explicitly selected `campaign-orchestrator` for an accepted `ultrawork` run. Nothing in ordinary `ulw-work` points here: there is no classifier, no recommendation step, no extra model call, and no plugin tool that decides work is "large enough" for a campaign. If the user did not name the mode, close this file and stay on the parent-led path.

The recipe composes existing primitives. It adds no model category, no scheduler, and no always-loaded context. Prepared routes are not model execution, review, CI, PR readiness, or merge authorization.

## Eligibility

The mode is eligible only when all of the following are already accepted, not merely proposed:

- one objective and its final binary acceptance criteria;
- exact write boundaries for every unit;
- one broad verification target owned by the campaign;
- at least two genuinely separable units (the contract accepts two to sixteen).

A single-owner task, a small parallel task, or an open-ended loop is not a campaign. Say so and route normally.

## Ownership Shape

```text
current chat parent (model unchanged, narrates, may display or cancel)
  -> exactly one campaign orchestrator on the `architect` route (its shipped chain head by default)
       -> bounded leaves on the `ultrabrain` route (its shipped chain head by default)
       -> conflict decisions and one integration fan-in
  -> one integrated, verified result back to the chat parent
```

The chat parent keeps its current model and stays the user-facing narrator. It never redispatches a unit while the campaign owner is active.

The orchestrator is the actual graph owner. It is runnable before any leaf exists and has no dependency on unfinished workers. It owns the executable plan, dependency edges, dispatch ledger, result fan-in, conflict decisions, the single broad-suite assignment, and the final go/no-go. A Fable reviewer attached after someone else coordinated the work is the wrong shape; that is a terminal-only integrator, not a campaign owner.

Leaves depend only on actual sibling units, never on the running orchestrator. Each leaf receives one standalone `TASK` / `DELIVERABLE` / `SCOPE` / `VERIFY` / `STOP WHEN` contract, runs its focused check, and returns its result to the orchestrator under the original unit and attempt IDs. A leaf cannot delegate, widen scope, start a continuation campaign, run the broad suite, or treat another worker's incoming result as fresh work. Host enforcement of those limits is required; the prompt text is guidance, not a boundary.

## Routes and Overrides

Both routes reuse the existing configurable mixture chains. `architect` and `ultrabrain` keep their ordinary meanings and remain independently usable outside a campaign. Owner and worker model, provider, and effort overrides are separate inputs and each takes precedence over its chain. Every resolved route carries the actual alias, wire model, provider, effort, and source; the chain head is never assumed to have run.

Campaign code never writes profile-global `delegation.*` keys. Writing those keys and hoping the intended child starts first is dispatch ordering, not an ownership boundary, and a concurrent session could consume the route.

## Host Binding Boundary

A campaign may run only through a trusted host adapter that can, as host capabilities rather than model-supplied booleans:

- derive the invoking session from host context (no caller-selected owner);
- bind each attempt atomically and immutably to its route, scoped tools, and recipient, with host idempotency;
- enforce the leaf write scope and a file-only toolset with no terminal, code execution, or delegation;
- observe execution evidence itself (diff, revision, verification output), not worker summaries;
- revoke pending routes and stop in-flight work on expiry.

Any host missing one part fails closed. The controller then records `fallback_parent_led` with the graph intact, and the current parent owns the work through ordinary `ulw-work`.

Installed Hermes at `f159e581` has no native per-dispatch model, provider, or effort binding for `delegate_task`, so the native binding is unsupported and is never inferred from a version number or schema field. Kanban rows carry task-local model, provider, and effort pins; the CLI reads existing rows and dependency edges through a read-only database connection and treats them as observed metadata only. Pins are not execution and not confinement. The installed profile resolver also adds `kanban` to a profile that lists only `file`, so the host cannot attest the leaf tool boundary this recipe needs. Because of that, `bind` reports `prepared_binding_observed` with execution `not_observed`, and `start` (native binding) returns `fallback_parent_led` instead of claiming a live Fable or Astra run. A wrapper implementing the full adapter protocol can drive the controller; that wrapper is not shipped here.

## Ledger, Fan-In, and Conflicts

- Campaign, unit, and attempt IDs are stable and derived; the accepted unit set and each unit's scope, acceptance, artifacts, and focused verification command are immutable after preparation. Only dependency edges may be re-planned, and only before any dispatch.
- The controller locks the whole read-modify-write and records an attempt as `unknown` before crossing the dispatch boundary. A crash or exception after that point does not turn the attempt back into undispatched work, and an `unknown` attempt is never blindly retried. External reconciliation is the only way forward.
- A unit dispatches once. Duplicate dispatch, duplicate results, late results, foreign results, and forged identities are counted and refused; none can reopen accepted work or trigger a second dispatch.
- A result is accepted only with exact campaign, attempt, and task identity, actual contained artifact paths with matching content digests, observed changed paths, revision and diff identity, and bounded verification output digest, size, and exit code. A plausible summary completes nothing.
- Overlapping paths (after canonical spelling, including backslashes) and shared invariants freeze the affected frontier, expire in-flight attempts on that frontier, and name one integration owner. That owner resolves the conflict through inspected evidence; the recipe never adds another leaf to escape a conflict.
- The broad suite is queued exactly once, to the orchestrator, after every producer result is accepted and every conflict is resolved. Leaves run focused checks only.

## Terminal States and Cleanup

Terminal states are `complete`, `cancelled`, `failed`, `unknown`, `cleanup_pending`, and the explicit `fallback_parent_led`. Every terminal transition expires pending routes and reads back the ordinary delegation route; a later ordinary delegation inheriting the parent route is the proof that cleanup worked. When expiry or the read-back fails, the record stays in `cleanup_pending` with the intended terminal state attached, never a false success, and `recover` may retry cleanup without reopening dispatch.

Explicit fallback preserves the graph, returns ownership to the current parent session, and resets untouched units to prepared. It never promotes an implementation leaf into campaign ownership. Completion requires the observed broad-suite evidence plus observed cleanup. PR creation and merge remain separate user-authorized actions.

## Operator CLI

This is an agent, wrapper, and operator surface under `omh coding`, not an everyday human command. The argv below is the current parser; `--json` is accepted by every subcommand.

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

`prepare` refuses without `--accept` and returns nothing unless the mode is `campaign-orchestrator`. `--spawn-plan` is the existing fanout justification and is required above four units. `bind --binding kanban` needs both `--tasks` (a JSON object mapping `orchestrator` and every unit ID to an existing host task ID) and `--worker-profile`; it verifies pins, idempotency keys, zero retries, assignee, and sibling edges against the stored record and refuses on any mismatch. CLI identity is the OS-observed supervising process, so related commands must run under the same operator or wrapper process; there is no `--owner-session` flag and no flag that declares verification observed. Refusals use OMH's ordinary exit-code-2 convention. Full operator detail lives in `docs/WORK-CAMPAIGN.md`.

## Evidence Boundary

Records live only under the selected OMH home's `runtime/campaigns`, bounded in count, size, and event history, with no prompt bodies, transcripts, provider errors, or raw logs. The default canary report has no observations and reports rates as `null`, never zero. Imported comparisons must be paired baseline and campaign measurements with actual record and input digests and a host-runtime measurement receipt; fixture or unpaired rows are excluded.

No authorized provider campaign has run through this recipe, so Fable and Astra execution, coordination quality, duplicate-work reduction, cost, and latency all remain `not_observed`. One maintainer field report justified building the opt-in mode; it does not justify a default change. Keep the mode explicit until repeated comparable campaigns show a measured benefit.
