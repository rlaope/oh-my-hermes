---
name: "omh-files"
description: "[omh] Folder cleanup, renames, or deletions: policy overlay for local file tasks - add path scoping and destructive-action gates after preferring native file tools for ordinary list, search, organize, copy, move, and rename actions. Use when the user says: workspace-file-operator, workspace file operator, file operator, file operation, file operations, filesystem task, filesystem operation, file system task."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, filesystem]
    category: filesystem
    phase: file-task
    role: guide
    quality_tier: workflow-surface-gated
    related_skills: [omh-materials-package, omh-deliverable-package]
---

# Workspace File Operator

Required: user request, target context, delivery or status expectation, known missing evidence. Output: workspace_file_task_card/v1, file_operation_scope/v1, file_observation_manifest/v1 when observed, file_confirmation_gate/v1 when destructive, next action, prepared-vs-observed boundary.

## Why This Exists

`workspace-file-operator` exists because a delete, overwrite, or bulk move often has no undo point: it scopes the path, confirms each destructive step, records beforehand whether a checkpoint covers the target (Hermes takes none unless checkpoints are on), and reports only what file evidence shows.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should prepare or supervise local workspace/file-system operations such as listing, searching, organizing, copying, moving, renaming, archiving, or deleting files without claiming the operation ran.

    Strong routing signals: `workspace-file-operator`, `workspace file operator`, `file operator`, `file operation`, `file operations`, `filesystem task`, `filesystem operation`, `file system task`, `file system operation`, `list files`, `list folder`, `list directory`, `find local files`, `search files`, `organize files`, `organize folder`, `move file`, `move files`, `copy file`, `copy files`, `rename file`, `rename files`, `delete file`, `delete files`, `remove file`, `remove files`, `archive files`, `downloads folder`, `reports folder`, `folder cleanup`, `file cleanup`, `파일 작업`, `파일 조작`, `파일 정리`, `파일 검색`, `파일 찾아`, `파일 이동`, `파일 복사`, `파일 이름 변경`, `파일 삭제`, `폴더 정리`, `다운로드 폴더`, `디렉터리 목록`

## Catalog Metadata

Category: `filesystem`
Phase: `file-task`
Hermes role: `guide`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Safety rules:

- A workspace file operator card is not file read, file write, copy, move, rename, delete, archive, upload, download, permission change, or destructive filesystem evidence unless observed file-operation output records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.
- Cite `session_file_activity/v1` (`omh quality-evidence file-activity --hermes-session <id> --json`) in `file_observation_manifest/v1` for which workspace files a Hermes session's read_file, write_file, and patch calls named and the outcome Hermes recorded; never as file-content, hash, diff, test, review, CI, or merge evidence.

## Completion Checklist

- The path root, allowed file operations, excluded paths, destructive-operation policy, and stop condition are explicit.
- Delete, overwrite, move, rename, permission change, archive mutation, upload, and download are gated, or marked missing and not run.
- With nobody to answer the confirmation (a scheduled job, a one-shot run, a webhook run), an irreversible or externally visible action is not run: it is handed to a person's turn and its confirmation is recorded as missing. The one exception is a bot whose person turned on its PR delivery grant (`omh capability-policy pr-delivery on`, which only the person runs; the bot only tells them the command): it may push a new branch under the grant's branch prefix, open a pull request from that branch, and push fix commits to and comment on a pull request it opened, and nothing else. Merging, force-pushing, pushing to the default branch, and anything on a pull request it did not open stay a person's, grant or no grant.
- Before a bulk change, list the exact paths and the destination names that already exist; never overwrite a name the confirmation did not name, and compare the listing after the run with the plan.
- Checkpoint availability is recorded before any destructive step, and the confirmation gate holds either way; without an observed checkpoint covering the target, a reversible copy or a move to trash comes first.
- Directory listings, file contents, hashes, diffs, and operation results are reported only from observed file evidence.

## Recovery Notes

- If the target path or folder is missing, ask for the smallest path scope needed before preparing the operation.
- If delete, overwrite, move, rename, chmod, or irreversible cleanup is requested, require an explicit confirmation gate.
- If the request is file conversion, deck/PDF export, or attachment delivery, route to `omh-materials-package` or `omh-deliverable-package` instead.
- On Hermes, when a checkpoint covers the change, the user's `/rollback` restores it and `/diff session` shows what the session changed since the checkpoint baseline; cite either only after the user runs it.
- On Hermes, a write that its own file guards refuse or hold for approval (a sensitive system path, a protected instruction file) is that gate's outcome to record, `blocked` or the user's answer, never a write to retry through another tool.

## Runtime Evidence

Preferred harness for this skill: `workspace-file-operator`.

```sh
omh runtime record --skill workspace-file-operator --harness workspace-file-operator --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
