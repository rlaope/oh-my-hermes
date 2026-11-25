# Workspace File Operator

Load this on-demand contract after the compact `workspace-file-operator` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- An ordinary list, search, read, or one-file edit inside a known folder; use the native file tools directly.
- The request converts files or produces a deck, PDF, or attachment; use `omh-materials-package` or `omh-deliverable-package`.

## Examples

Good example:

- Prompt: workspace-file-operator list files in the reports folder and move old PDFs into archive after confirmation.
- Expected behavior: Produce `prepare_workspace_file_operator_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: workspace-file-operator delete every matching file without path scope or confirmation.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- workspace_file_task_card/v1
- file_operation_scope/v1
- file_observation_manifest/v1 when observed
- file_confirmation_gate/v1 when destructive
- next action
- prepared-vs-observed boundary

Artifact expectations:

- workspace_file_task_card/v1 metadata-only wrapper card when prepared
- file_operation_scope/v1 with path root, allowed operations, excluded paths, and stop condition
- file_observation_manifest/v1 only when directory listings, file stats, hashes, diffs, or operation output are observed
- file_confirmation_gate/v1 for delete, overwrite, move, rename, chmod, archive mutation, or irreversible cleanup, recording checkpoint availability before the step and keeping the confirmation either way: on Hermes, checkpoints are off unless the user turned them on (`checkpoints.enabled`, or a session started with the `--checkpoints` flag), and one covers only the directory Hermes snapshots for the step (for a terminal command, its working directory), minus its excludes (among them archives, media, logs, `.env` files, and dependency and build folders) and its limits (a file over the size cap, 10 MB by default, or a directory with more than 50,000 entries), so record `available` only when the user's `/rollback` lists checkpoints for a directory that holds the target and the target is not excluded or over a limit, `not_available` otherwise, and `not_observed` until then
