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

Check that the installed router skill contains the representative harness
registry:

```sh
omh install --dry-run
omh list
```

For repository development, run:

```sh
python -m unittest discover -s tests
```

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

- `architect` for boundaries, integration choices, and maintainability
- `critic` for consistency, missing checks, and residual risk
- `qa-specialist` for adversarial scenarios and pass/fail evidence
- `docs-specialist` for accurate commands, examples, and limitations

These are quality lanes. They are not proof that Hermes spawned a separate
runtime role unless the active Hermes environment exposes that capability.

### Verification

The router skill should include each specialist harness name, inputs, outputs,
verification expectations, and fallback behavior.

Repository maintainers can verify this with:

```sh
python -m unittest discover -s tests
```

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
- The three cases above match actual generated skill behavior.
- Public docs avoid comparisons to other projects.
- Any real Hermes runtime behavior that could not be automated is listed as a
  manual check.
