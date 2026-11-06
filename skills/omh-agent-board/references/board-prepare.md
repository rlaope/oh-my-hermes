# Agent Board: Preparing a Request

The repository's operator page is not part of an installed skill, so the fields a `prepare` call needs are here, read from the board engine. OMH prepares; Hermes invokes the returned `native_action` through its normal tool loop.

## 1. The two calls

- `prepare`: `request_id`, `coordination`, `operation`, `board`, `profile`, `arguments`; optional top-level `task_id` and `expected_observation_ref`. A call with no `board` is refused as `board_required`; one missing another field is refused as `invalid_prepare_input` with the missing names in `fields`.
- `status`: only `action` and `request_id`; anything more is `invalid_status_input`. It returns the bounded receipt and no action text or native output.

## 2. Fields

| Field | Value |
| --- | --- |
| `request_id` | a new string for every request, matching `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`: letters, digits, `_ . : -`, no spaces, at most 128 characters; reusing an id for a different request is denied, and repeating the same `create` returns the task already observed |
| `coordination` | `durable` for a `kanban_<operation>` action that survives a restart or crosses profiles; `bounded_research` for one `delegate_task` |
| `operation` | with `durable`, one of the operations in section 3; with `bounded_research`, only `research` |
| `board` | the named board; a board other than the one bound to this host is refused |
| `profile` | the host profile being coordinated |
| `arguments` | closed per operation, section 3; an unknown key is refused |
| `task_id` | top level, not inside `arguments`: required for every durable operation except `create`, `link` and `list`, and refused (`unexpected_task_id`) on those three |

## 3. Durable operations and their arguments

| Operation | Top-level `task_id` | Required `arguments` | Optional `arguments` |
| --- | --- | --- | --- |
| `create` | refused | `title`, `assignee` | `body`, `parents`, `skills`, `workspace_kind`, `workspace_path`, `priority`, `max_runtime_seconds`, `idempotency_key`, `initial_status`, `model`, `provider`, `completion_contract`, `goal_mode`, `goal_max_turns` |
| `link` | refused | `parent_id`, `child_id` | none |
| `comment` | required | `body` | none |
| `heartbeat` | required | none | `note` |
| `request_review` | required | `summary` | `reviewer`, `metadata` |
| `request_changes` | required | `reason` | none |
| `block` | required | `reason` | `kind` |
| `unblock` | required | none | none |
| `complete` | required | none | `summary`, `result`, `metadata`, `created_cards` |
| `show` | required | none | none |
| `list` | refused | none | `assignee`, `status`, `tenant`, `include_archived`, `limit` |
| `attachments` | required | none | none |

`task_id` always goes at the top level of the call, never only inside `arguments`: a call without it is refused as `invalid_reference` for every operation marked required, even `show` and `heartbeat`. If `arguments` repeats it, the two must match.

Beyond the key sets: `complete` needs `summary` or `result`; a block `kind` is one of `dependency`, `needs_input`, `capability`, `transient`; a `list` `status` is any board status except `review` and `scheduled`; `initial_status` is one of `todo`, `running`, `blocked`, `triage`; `workspace_kind` is `scratch`, `dir` or `worktree`, and a `workspace_path` needs a `workspace_kind` of `dir` or `worktree`; a `link` may not join a task to itself.

`bounded_research`, operation `research`: `arguments` is exactly `{"tasks": [{"goal": "...", "context": "..."}]}`, one or more tasks, each with exactly `goal` and `context`, and no top-level `task_id`.

A durable `create` may state `lane_role` (`builder`, `verifier`, `reviewer`, `docs` or `qa`): OMH fills that lane's skills and workspace kind, refuses a verifier or reviewer that declares no parents, and removes the role before the native action.

## 4. Refusals

The tool answers `invalid_request_or_board_store` for every engine refusal and does not say which. The usual causes are an unknown key (`unsupported_argument`), a missing required argument (`missing_argument`), a `request_id` or `task_id` outside the pattern (`invalid_reference`), a `bounded_research` call with any other operation or shape (`invalid_bounded_research`), a foreign board or task, a self-link, an `idempotency_key` that differs from the `request_id`, or a `status` for a `request_id` that was never prepared. Correct the field and prepare again; do not retry the same call.

## 5. What must exist on the host

OMH checks none of these; it reports the gap it can see as `unavailable` with `missing_capabilities`.

- The `kanban` toolset enabled for the platform, and a fresh chat started afterwards.
- The board database created (`hermes kanban init`).
- A gateway running with `kanban.dispatch_in_gateway` enabled; only that dispatcher turns a `ready` row into a worker.
- An `assignee` that names an existing Hermes profile, with every `skills` entry installed in that profile.

## 6. States

`prepared` (validated, not invoked), `unavailable` (a capability is missing; zero native calls), `denied`, `observed` (the paired post callback returned a bound result), `failed`. A prepared or unavailable record is a card, not a task. After `failed` or `requires_reconciliation`, run an observed `show` on the same task before the next mutation.

## Boundary

A prepared request is not dispatch, acceptance, review, CI, or merge. No native `kanban_dispatch` tool exists: dispatch stays `unavailable`, and an operator claim is the observed path.
