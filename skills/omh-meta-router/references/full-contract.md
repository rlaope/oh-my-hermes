# Meta Router

Load this on-demand contract after the compact `meta-router` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The /omh token is not the leading command token.
- The message is a bare picker alias or an OMH catalog/entrypoint question — those belong to `omh-routing`.

## Examples

Good example:

- Prompt: /omh migrate this service off the deprecated API and add tests
- Expected behavior: Consult `omh recommend` on the remainder, then name the recommended chain and start only its first stage; each later engine waits for the user's go-ahead, with explicit observed-vs-prepared evidence boundaries.
- Why: A leading /omh command with an imperative remainder is a meta-routing request that reasons over the live catalog rather than a memorized list.

Bad example:

- Prompt: omh add dark mode
- Expected behavior: Do not meta-route; a bare `omh` alias without a leading slash command is a picker/other-lane signal.
- Why: Meta-routing triggers only on a leading /omh or ./omh command token, not on a bare alias.

## Full Input, Output, and Artifact Expectations

Required inputs:

- leading /omh or ./omh command with an imperative remainder
- live OMH catalog via bounded `omh recommend --json` queries
- available shell/CLI or plugin tool surface

Expected outputs:

- selected workflow or chain with rationale
- consulted catalog evidence from the bounded recommend output
- observed-vs-prepared evidence boundary for the routing decision

Artifact expectations:

- runtime run record when a wrapper can observe the meta-routing decision
