# Application Cases

This guide documents the first three proof cases for `oh-my-hermes-agent`.
Each case is designed to show visible skill impact without claiming hidden
Hermes runtime behavior.

## Case 1: Coding Request Handling

### Setup

Install and apply the managed skill pack:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
omh doctor
```

Restart Hermes Agent after installation so it can reload its configured skill
directories.

### User Prompt Shape

Ask Hermes for a concrete coding task, such as a focused bug fix, review, or
small feature request.

Strong signals include:

- a file path
- an error message
- a function or module name
- explicit verification requirements

### Expected Hermes-Facing Behavior

Hermes should use the installed `oh-my-hermes` router guidance and the
`coding-handling` harness to keep the response scoped around:

- target behavior
- relevant repo context
- changed files
- verification evidence
- remaining risks

If the prompt is too broad, the harness directs Hermes to ask one concise
clarification question before editing.

### Verification

After installation, inspect the managed skill list:

```sh
omh list
```

For repository development, verify the generated router content through tests:

```sh
python -m unittest discover -s tests
```

Artifact-backed verification can be recorded without capturing prompt bodies:

```sh
run_json="$(omh runtime record --skill oh-my-hermes --harness coding-handling --status started)"
run_id="$(printf '%s' "$run_json" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed
omh runtime show "$run_id"
```

This proves the workflow was tracked locally while preserving the distinction
between requested review/delegation and delegation that Hermes actually exposed.

### Current Limit

This case verifies installed prompt guidance and generated skill content.
It does not prove that Hermes has a hidden runtime hook or automatic internal
router beyond Hermes' normal skill loading behavior.

## Case 2: Goal, Planning, and Deep Interview Flow

### Setup

Confirm the skill pack is installed and registered:

```sh
omh doctor
```

### User Prompt Shape

Use this flow when the user describes a broad product or coding objective that
needs clarification before execution.

Strong signals include:

- unclear scope
- missing non-goals
- a request to plan before coding
- a long-running objective that needs checkpoints

### Expected Hermes-Facing Behavior

Hermes should use:

- `deep-interview` when intent, boundaries, or decision authority are unclear
- `planning` when requirements are clear enough for sequencing and test shape
- `goal-execution` when the work needs durable checkpoints or finish-until-done
  pressure

The expected output is a clarified brief or plan before implementation starts.
When Hermes lacks a dedicated goal tool, the compatibility contract tells it to
use a file-backed checklist or explicit local ledger.

### Verification

Inspect generated skills after install:

```sh
omh list
```

Repository maintainers can verify generated content through tests:

```sh
python -m unittest discover -s tests
```

Artifact-backed verification:

```sh
run_json="$(omh runtime record --skill ultragoal --harness goal-execution --status started)"
run_id="$(printf '%s' "$run_json" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed
omh runtime show "$run_id"
```

Use `not_observed` when the active Hermes surface does not expose a separate
goal runner or planner identity.

### Current Limit

This case is prompt-level workflow guidance unless a future Hermes extension
surface provides deeper state or goal integration.

## Case 3: Specialist Harness Flow

### Setup

Install the skill pack and make sure Hermes can read the same config that
`omh apply` updated:

```sh
omh doctor
```

For Discord bot deployments, install in the same runtime context that starts
the bot, then restart the bot process.

### User Prompt Shape

Use this flow for work that needs stronger review or a release-quality answer.

Strong signals include:

- architecture or integration risk
- public documentation changes
- user-visible workflow changes
- release or quality-gate language
- requests for critique, QA, or docs review

### Expected Hermes-Facing Behavior

Hermes should shape the work through the representative specialist harnesses:

- `research` for current, official, or source-backed evidence gathering
- `architect` for boundaries, integration choices, and maintainability
- `critic` for consistency, missing checks, and residual risk
- `qa-specialist` for adversarial scenarios and pass/fail evidence
- `docs-specialist` for accurate commands, examples, and limitations

These are quality lanes. They are not proof that Hermes spawned a separate
runtime role unless the active Hermes environment exposes that capability.

### Verification

The router skill should include each specialist harness name, inputs, outputs,
verification expectations, quality tier, evidence ladder, wrapper actions,
overclaim guards, and fallback behavior.

Repository maintainers can verify this with:

```sh
python -m unittest discover -s tests
```

Artifact-backed verification:

```sh
run_json="$(omh runtime record --skill code-review --harness critic --status completed)"
run_id="$(printf '%s' "$run_json" | python -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
omh runtime delegate --run "$run_id" --requested --not-observed --result not_observed --evidence-ref run.json
omh runtime show "$run_id"
```

If a bot wrapper can observe separate specialist outputs, it can record
`--observed --result completed --participants architect,critic`. Otherwise the
artifact should remain explicit that delegation was not observed.

### Current Limit

If Hermes delegation is unavailable, the harness still improves response
quality by making Hermes run the specialist checks sequentially in the current
conversation.

## Release Review Checklist

Before using these cases as public release evidence, verify:

- The one-command installer still works.
- `omh doctor` reports the managed skill directory and Hermes config
  registration clearly.
- The generated router includes the representative harness registry.
- `omh docs workflows --json` exposes `harness_quality/v1` style quality data
  for wrapper rendering and status decisions.
- The three cases above match actual generated skill behavior.
- The three cases above can create `.omh/runtime/runs/<run-id>/` artifacts.
- `delegation.json` separates requested delegation from observed delegation.
- `omh probe` output is captured before any native hook, plugin, app, MCP, or
  internal routing claim is made.
- Public docs avoid comparisons to other projects.
- Any real Hermes runtime behavior that could not be automated is listed as a
  manual check.
