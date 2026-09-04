# Model Routing and Safe Local State Inspection

Load this reference for model-chain behavior, coding-owner routing, capability
policy, installed-profile questions, or where OMH stores local metadata.

## Public Routing Facts

For published behavior, read the current `MODEL_OPTI.md`, `docs/FANOUT.md`,
`docs/INSTALLATION.md`, relevant command help, and implementation at the
disclosed official ref. Treat documented defaults as versioned product facts,
not proof that this machine uses them.

## Passive Local Commands

Prefer these before opening files:

```sh
omh list --json
omh model-chains show
omh coding category-maestro show
omh capability-policy status
omh status
omh <command> --help
```

`omh doctor --json` is a diagnostic, not passive inspection: when its state
store is writable it records `last_doctor`, and failed health checks can return
a nonzero exit code while still emitting useful JSON. Disclose the
`state-write side effect` before running it, then interpret the payload rather
than treating a nonzero status as command absence.

Record the command, selected profile/home, and observed OMH version or commit.
Do not reinterpret a command's absence as a product-wide capability claim.

## Resolve the Active Home First

Use the current CLI metadata and `src/system/paths.py` to resolve exactly one
active home before opening a path. The user-scope default is `~/.omh`, but
`OMH_HOME` and `--omh-home` can override it, while `--scope project` resolves
to the repository's `.omh`. Do not probe several guessed homes.

Installer-managed skills can be served through an atomic generation pointer
such as `current/skills`; do not assume the active pack is a literal
`~/.omh/skills/` directory.

## Narrow Resolved-Home Fallback

Only when no passive command answers the question, inspect the minimum metadata
path needed under the one resolved home. Documented areas can include:

- `manifest.json` and `setup-profile.json`;
- the active managed skill generation and its `current/skills` pointer;
- `routing/` model chains, route provenance, provider entitlements,
  model-provider mappings, price overrides, dispatch defaults, and
  category-specific routing;
- target registries and goal, loop, state, or runtime metadata;
- memory and learning stores;
- generated operator artifacts described by the current docs.

Presence varies by OMH version, setup profile, enabled capability, scope, and
whether a workflow has ever produced that artifact. Report
`not_present_for_this_install` rather than treating every documented path as
mandatory.

## Secret and Privacy Boundary

Never read or print credentials, tokens, auth files, `.env` values, provider
secrets, raw private logs, raw prompts/transcripts, or unrelated user content.
Do not recursively list the home directory. Inspect filenames, schemas,
versions, counts, and non-secret routing metadata only when the question
requires them.

## Mutation Requests

This reference does not authorize mutation requests. For setup, install,
update, repair, capability policy, model-chain, category routing, provider, or
price changes, identify the appropriate specialized public workflow and stop
before writing. A separately authorized mutation begins a different workflow
with its own preview and verification contract.
