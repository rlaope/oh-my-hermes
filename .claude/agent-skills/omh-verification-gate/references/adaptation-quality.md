# Adaptation Quality Preservation

Load this only when importing, porting, wrapping, or replacing an existing
capability, meaning a skill, plugin, or tool whose output quality a user sees
(media, rendering, generation). An ordinary code port or API wrapper is not one:
verify it with the requirement coverage map. Unrelated tasks do not require
upstream execution. This procedure
uses the existing plan, requirement coverage map, node prompts, and verification
matrix; it adds no engine, executable schema, or automatic service call.

## Pin the requested outcome

Before accepting an adaptation plan, record the baseline revision and target
revision (or current target tree plus a later final revision), source paths,
intended consumers, and the complete requested capability. Inspect the operative
code, assets, references, tools, render/export options, and defaults that produce
the baseline result; a README or example thumbnail is not that inventory.

Use the existing FR-### / SC-### ids and requirement -> task -> evidence map.
Make a component/quality table with columns:

| Source component/default | User-visible behavior or craft contribution | reuse / adapt / omit | Target path and owner task | user-visible loss and reason | Acceptance comparison/evidence |
| --- | --- | --- | --- | --- | --- |

Include the engine and entry points, companion tools, assets/fonts, timing or
other craft references, quality-affecting defaults, dependencies, and output
formats. A renamed workflow with missing operative components is not parity.
Record user-agreed exclusions against their criteria, including who agreed and
the exact narrower outcome. A parent's lane brief is not user agreement to drop
a requested capability. Carry the full goal and these rows into the accepted
plan and every builder/verifier handoff, not only a package-test VERIFY command.

Do not silently replace a requested executable adaptation with a recipe or methods-only outcome.
If only documentation or methods are intended, declare methods-only explicitly:
name what cannot execute, what the user must supply, and which parity claims are
out of scope. If the user requested executable retention, obtain their agreement
to the concrete losses before accepting that narrower outcome; otherwise keep
those criteria open. A fallback cannot quietly redefine the original goal.

## Reuse before rewriting

Prefer retaining working source components and their quality-bearing defaults
over reconstructing a simplified substitute. For each reuse/adapt/omit choice,
check license and notices, dependency and packaging compatibility, security,
permissions, and authority/budget boundaries. Reuse is conditional on those
checks, not permission to copy incompatible code, install dependencies, execute
untrusted scripts, or invoke providers. Record why a rewrite is necessary and
which behavior and craft obligations it must preserve.

A missing credential is not permission to call a service, use another account,
or certify a silent fallback. Mark the comparison blocked/unobserved and offer
an authorized local alternative with its losses disclosed; a user must agree to
any changed acceptance target. Keep requested tool, safety, spend, and scope
limits intact.

## Compare early

Before broad decomposition or expensive implementation, select the same
representative task for baseline and target: fixed inputs, success criteria,
and a task that exercises the quality-bearing components, not just a trivial
smoke case. Define separate technical and output-quality criteria from the
source contributions and requested outcome; name the reviewer and review method
for subjective criteria. Make an early end-to-end baseline/target comparison,
then inspect actual outputs in their intended medium (play motion/audio, inspect
rendered UI, or evaluate domain output as appropriate). Use the result to adjust
tasks before multiplying a reduced design across lanes.

Record exact invocations, artifact paths, input/asset versions, tools/models,
settings/defaults, permissions, time/token/money budgets, and environment for
both sides. Name every difference and its likely effect; unequal tools or
budgets cannot silently support an equal-quality claim. When source execution
or review is unavailable, cite what was inspected and keep the missing
comparison unobserved. Preparation may continue within authority, but neither
parity nor goal completion follows from that preparation.

## Compare the shipped result

After implementation, run the final same-task comparison against the pinned
baseline and final target revision using the agreed inputs and criteria. Reuse
the early protocol, record changed tools, settings, permissions, or budgets, and
explain output differences, regressions, and remaining losses component by
component. Include installed/distributed output checks when shipping capability:
exercise the packaged entry point and companions/assets/references from an
isolated installed or distribution tree, not just repository imports. Record
missing permissions or execution as gaps; do not weaken refusal checks to run it.

Carry the rows and early evidence through existing TASK, DELIVERABLE, SCOPE,
VERIFY, STOP WHEN prompts and dependency handoffs. The verifier checks the whole
goal, including retained capability and output quality, against fresh artifacts
rather than trusting producer summaries. Repairs, retries and extensions retain
the same goal and acceptance rows; a local green command never replaces them.
A passing render can prove the reduced substitute works without proving retained capability or craft.

## Report two verdicts

Return a technical verdict for tests/build, packaging, safety and executable
behavior, and a distinct output-quality verdict for the agreed same-task output
criteria and subjective review. Use the existing PASS/HOLD/BLOCK vocabulary and
evidence rows; do not create an aggregate PASS that hides an unmet dimension.
List observed outputs and reviewers, failed criteria, accepted exclusions, and
unobserved comparisons separately. If output review was not performed, its
verdict is HOLD with that gap, even if technical checks pass. Methods-only work
may satisfy its explicitly agreed documentation criteria, never executable or
output-quality parity it did not demonstrate.

Structural native_capability_quality_gate checks are not output-quality evidence.
Procedure/link contract tests prove delivery of these instructions, not artistic
validation, live-agent compliance, or that any future adaptation preserves quality.
