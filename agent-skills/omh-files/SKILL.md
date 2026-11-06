---
name: "omh-files"
description: "[omh] Folder cleanup, renames, or deletions: policy overlay for local file tasks - add path scoping and destructive-action gates after preferring native file tools for ordinary list, search, organize, copy, move, and rename actions. Use when the user says: workspace-file-operator, workspace file operator, file operator, file operation, file operations, filesystem task, filesystem operation, file system task."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, filesystem]
    category: filesystem
    phase: file-task
    role: guide
    quality_tier: workflow-surface-gated
---

# Workspace File Operator

This is an OMH `workspace-file-operator` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`workspace-file-operator` exists because a delete, overwrite, or bulk move often has no undo point: it scopes the path, confirms each destructive step, records beforehand whether a checkpoint covers the target (Hermes takes none unless checkpoints are on), and reports only what file evidence shows.

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

## Completion Checklist

- The path root, allowed file operations, excluded paths, destructive-operation policy, and stop condition are explicit.
- Delete, overwrite, move, rename, permission change, archive mutation, upload, and download are gated, or marked missing and not run.
- With nobody to answer the confirmation (a scheduled job, a one-shot run, a webhook run), an irreversible or externally visible action is not run: it is handed to a person's turn and its confirmation is recorded as missing.
- Checkpoint availability is recorded before any destructive step, and the confirmation gate holds either way; without an observed checkpoint covering the target, a reversible copy or a move to trash comes first.
- Directory listings, file contents, hashes, diffs, and operation results are reported only from observed file evidence.

## Recovery Notes

- If the target path or folder is missing, ask for the smallest path scope needed before preparing the operation.
- If delete, overwrite, move, rename, chmod, or irreversible cleanup is requested, require an explicit confirmation gate.
- If the request is file conversion, deck/PDF export, or attachment delivery, route to materials-package or deliverable-package instead.
- On Hermes, when a checkpoint covers the change, the user's `/rollback` restores it and `/diff session` shows what the session changed since the checkpoint baseline; cite either only after the user runs it.
- On Hermes, a write that its own file guards refuse or hold for approval (a sensitive system path, a protected instruction file) is that gate's outcome to record, `blocked` or the user's answer, never a write to retry through another tool.



## When to Use

Use when Hermes should prepare or supervise local workspace/file-system operations such as listing, searching, organizing, copying, moving, renaming, archiving, or deleting files without claiming the operation ran.

    Strong routing signals: `workspace-file-operator`, `workspace file operator`, `file operator`, `file operation`, `file operations`, `filesystem task`, `filesystem operation`, `file system task`, `file system operation`, `list files`, `list folder`, `list directory`, `find local files`, `search files`, `organize files`, `organize folder`, `move file`, `move files`, `copy file`, `copy files`, `rename file`, `rename files`, `delete file`, `delete files`, `remove file`, `remove files`, `archive files`, `downloads folder`, `reports folder`, `folder cleanup`, `file cleanup`, `파일 작업`, `파일 조작`, `파일 정리`, `파일 검색`, `파일 찾아`, `파일 이동`, `파일 복사`, `파일 이름 변경`, `파일 삭제`, `폴더 정리`, `다운로드 폴더`, `디렉터리 목록`

## Catalog Metadata

Category: `filesystem`
Phase: `file-task`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

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
- session_file_activity/v1 (`omh quality-evidence file-activity --hermes-session <id> --json`) cited in that manifest for which workspace files a Hermes session's read_file, write_file, and patch calls named and the outcome Hermes recorded; never as file-content, hash, diff, test, review, CI, or merge evidence
- file_confirmation_gate/v1 for delete, overwrite, move, rename, chmod, archive mutation, or irreversible cleanup, recording checkpoint availability before the step and keeping the confirmation either way: on Hermes, checkpoints are off unless the user turned them on (`checkpoints.enabled`, or a session started with the `--checkpoints` flag), and one covers only the directory Hermes snapshots for the step (for a terminal command, its working directory), minus its excludes (among them archives, media, logs, `.env` files, and dependency and build folders) and its limits (a file over the size cap, 10 MB by default, or a directory with more than 50,000 entries), so record `available` only when the user's `/rollback` lists checkpoints for a directory that holds the target and the target is not excluded or over a limit, `not_available` otherwise, and `not_observed` until then

Safety rules:

- A workspace file operator card is not file read, file write, copy, move, rename, delete, archive, upload, download, permission change, or destructive filesystem evidence unless observed file-operation output records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
