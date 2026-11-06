# Agent Board: Preparing a Request

The repository's operator page is not part of an installed skill, so the fields a `prepare` call needs are here, read from the board engine. OMH prepares; Hermes invokes the returned `native_action` through its normal tool loop.

## 1. The two calls

- `prepare`: `request_id`, `coordination`, `operation`, `board`, `profile`, `arguments`; optional top-level `task_id` and `expected_observation_ref`. A call with no `board` is refused as `board_required`; one missing another field is refused as `invalid_prepare_input` with the missing names in `fields`.
- `status`: only `action` and `request_id`; anything more is `invalid_status_input`. It returns the bounded receipt and no action text or native output.

## 2. Fields

| Field | Value |
| --- | --- |
| `request_id` | a string matching `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`: letters, digits, `_ . : -`, no spaces, at most 128 characters; repeating a `create` with the same `request_id` returns the task already observed |
| `coordination` | `durable` for a `kanban_<operation>` action that survives a restart or crosses profiles; `bounded_research` for one `delegate_task` |
| `operation` | with `durable`, one of the operations in section 3; with `bounded_research`, only `research` |
| `board` | the named board; a board other than the one bound to this host is refused |
| `profile` | the host profile being coordinated |
| `arguments` | closed per operation, section 3; an unknown key is refused |
| `task_id` | top level, not inside `arguments`: required for every durable operation except `create`, `link` and `list`, and refused (`unexpected_task_id`) on those three |

## 3. Durable operations and their arguments

| Operation | Required arguments | Optional arguments |
| --- | --- | --- |
| `create` | `title`, `assignee` | `body`, `parents`, `skills`, `workspace_kind`, `workspace_path`, `priority`, `max_runtime_seconds`, `idempotency_key`, `initial_status`, `model`, `provider`, `completion_contract`, `goal_mode`, `goal_max_turns` |
| `link` | `parent_id`, `child_id` | none |
| `comment` | `task_id`, `body` | none |
| `heartbeat` | none | `task_id`, `note` |
| `request_review` | `summary` | `task_id`, `reviewer`, `metadata` |
| `request_changes` | `reason` | `task_id` |
| `block` | `reason` | `task_id`, `kind` |
| `unblock` | `task_id` | none |
| `complete` | none | `task_id`, `summary`, `result`, `metadata`, `created_cards` |
| `show` | none | `task_id` |
| `list` | none | `assignee`, `status`, `tenant`, `include_archived`, `limit` |
| `attachments` | none | `task_id` |

A required `task_id` is satisfied by the top-level `task_id`; if `arguments` repeats it, the two must match.

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
