# Agent Board: Preparing a Request

The repository's operator page is not part of an installed skill, so the fields a `prepare` call needs are here. OMH prepares; Hermes invokes the returned `native_action` through its normal tool loop.

## 1. The two calls

- `prepare`: `request_id`, `coordination`, `operation`, `board`, `profile`, `arguments`; optional `task_id` and `expected_observation_ref`. A call missing a required field is refused with `invalid_prepare_input` and the missing names in `fields`.
- `status`: only `action` and `request_id`; anything more is `invalid_status_input`. It returns the bounded receipt and no action text or native output.

## 2. Fields

| Field | Value |
| --- | --- |
| `request_id` | a new unique string per request; repeating a `create` with the same `request_id` returns the task already observed, so reuse an id only to repeat the same create |
| `coordination` | `durable` for work that must survive a restart or be picked up across profiles (a `kanban_<operation>` action); `bounded_research` for one short `delegate_task` child |
| `operation` | one of `create`, `link`, `comment`, `heartbeat`, `request_review`, `request_changes`, `block`, `unblock`, `complete`, `show`, `list`, `attachments` |
| `board` | the named board; a `board` that is not the one bound to this host is a foreign board and is refused |
| `profile` | the host profile being coordinated |
| `arguments` | closed per operation: an unknown key is refused |

Refusals that name no reason beyond `invalid_request_or_board_store` mean the engine rejected the request: an unknown key, a foreign board, a `task_id` that differs from the request, a self-link, a `complete` without summary or result, an unknown block kind, an `idempotency_key` that differs from the `request_id`, or a `status` for a `request_id` that was never prepared. Correct the field and prepare again; do not retry the same call.

A durable `create` may state `lane_role` (`builder`, `verifier`, `reviewer`, `docs` or `qa`): OMH fills that lane's skills and workspace kind, refuses a verifier or reviewer that declares no parents, and removes the role before the native action.

## 3. What must exist on the host

OMH checks none of these; it reports the gap it can see as `unavailable` with `missing_capabilities`.

- The `kanban` toolset enabled for the platform, and a fresh chat started afterwards.
- The board database created (`hermes kanban init`).
- A gateway running with `kanban.dispatch_in_gateway` enabled; only that dispatcher turns a `ready` row into a worker.
- An `assignee` that names an existing Hermes profile, with every `skills` entry installed in that profile.

## 4. States

`prepared` (validated, not invoked), `unavailable` (a capability is missing; zero native calls), `denied`, `observed` (the paired post callback returned a bound result), `failed`. A prepared or unavailable record is a card, not a task. After `failed` or `requires_reconciliation`, run an observed `show` on the same task before the next mutation.

## Boundary

A prepared request is not dispatch, acceptance, review, CI, or merge. No native `kanban_dispatch` tool exists: dispatch stays `unavailable`, and an operator claim is the observed path.
