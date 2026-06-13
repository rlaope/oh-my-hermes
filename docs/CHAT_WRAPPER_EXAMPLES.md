# Chat Wrapper Examples

This page shows how a Discord-style Hermes Agent surface can render OMH output
as a normal chat response. The example is generated from local fixtures so the
contract is easy to inspect.

For the operator runbook that ties these examples to state transitions,
responsibilities, and evidence boundaries, read
[Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md).

## Commands Used

```sh
uv run python examples/discord-adapter-shim.py
uv run python -m src.cli demo orchestration
```

The first command renders the fixture event in
`examples/wrapper-events/discord-safe-feature.json`. The second command renders
the full deterministic path:

```text
recommend -> chat response -> Hermes plan -> selected executor/runtime handoff -> status card
```

## Discord-Style Plan Response

```text
# repo-planning

maintainer-1
I want to safely add a feature to this repo

Hermes Agent  BOT
I routed this to `plan` because it needs a safe plan first.

Accept or revise the plan first; the handoff button stays disabled until
acceptance. A draft plan is still only planning evidence.

[ Accept plan ] [ Revise plan ] [ Prepare handoff ] disabled

State
- Phase: planning
- Next action: present_plan
- Claim boundary: A draft plan is not execution evidence.
```

User-facing effect:

- The user does not need to know an `omh` command.
- Hermes Agent explains why the request became a plan-first workflow.
- The wrapper can show `Accept plan` and `Revise plan` immediately.
- `Prepare handoff` is visible but disabled until the plan is accepted.
- The response names what is not evidence yet instead of sounding like coding
  already happened.

## Discord-Style Handoff Status Card

After the wrapper prepares the handoff, the demo status card can be rendered as
a progress block in the same thread:

```text
Hermes Agent  BOT
A coding-runtime handoff is ready.

I have prepared the handoff, but runtime start or executor/runtime dispatch is not
observed yet.

Status
[ready]   Handoff
[pending] Execution
[pending] Verification
[n/a]     Review
[pending] CI
[pending] Merge Ready
[pending] Merged

Primary action: Show runtime handoff or send to executor
Claim boundary: Preparation is not execution evidence.
```

User-facing effect:

- Prepared handoff is presented as ready to dispatch, not completed work.
- If the selected profile is Codex, the wrapper can use the handoff's
  `$skill {message}` invocation, such as `$ai-slop-cleaner {message}`, rather
  than asking the chat user to run it. Hermes/OMX/OMO/OMC profiles render a
  runtime handoff with team/swarm, worker-protocol, and worktree guidance.
  Claude Code and generic profiles render a copyable prompt handoff instead of
  lifecycle evidence.
- Execution, verification, CI, merge-readiness, and merge stay separate.
- The wrapper can keep editing the same thread as evidence arrives.

## Grounded Operator Examples

The following examples were run through `omh chat interact --source discord`.
They show how different natural-language messages should produce different
wrapper-native responses instead of forcing every request into coding.

### Startup Product Triage

```text
# product-feedback

operator
결제 실패 이슈가 자주 나와

Hermes Agent  BOT
I routed this to `plan` because it needs a safe plan first.

Accept or revise the plan first; the handoff button stays disabled until
acceptance. A draft plan is still only planning evidence.

[ Accept plan ] [ Revise plan ] [ Prepare handoff ] disabled

Claim boundary: A draft plan is not execution evidence.
```

What gets better for the team:

- The message is treated as product/bug triage, not instant implementation.
- The next step is investigation and reproduction planning before any coding
  handoff.
- The future handoff can carry acceptance criteria and verification checks.

### Real-World QA Check

```text
# cloudy-qa

operator
쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?

Hermes Agent  BOT
I know which workflow should handle this.

I will prepare a safe next step for `ultraqa` before claiming any work happened.

[ Show status ]

Claim boundary: Routing is not execution evidence.
```

What gets better for the team:

- The request stays in a Hermes-retained QA workflow.
- `omh coding delegate` does not emit a dispatchable executor or runtime
  handoff for this scenario until a concrete code change is accepted.
- QA scenarios, expected behavior, and observed results can be recorded without
  pretending the product was fixed.

### Product Feature Shaping

```text
# product

pm
온보딩을 더 부드럽게 만들고 싶어

Hermes Agent  BOT
This needs a clarification workflow before planning.

I will ask one blocking question in the same thread before any plan or handoff
is treated as ready.

[ Answer clarification ] [ Cancel ]

Claim boundary: No plan or execution has started.
```

What gets better for the team:

- Broad product language becomes deep interview before implementation.
- Hermes asks for the missing decision instead of sending vague work to a coding
  executor.
- Planning and handoff buttons stay behind the clarification gate.

### Release Evidence Review

```text
# release

maintainer
릴리즈 전에 README claim이 실제 코드와 맞는가, doctor/harness가 통과하는가 봐줘

Hermes Agent  BOT
I know which workflow should handle this.

Surface findings separately from any code changes; fixes need their own executor evidence.

[ Show status ]

Claim boundary: A review recommendation is not a completed review or fix evidence.
```

What gets better for the team:

- Release claims are routed to review instead of implementation theater.
- Findings, fixes, verification, CI, and merge readiness stay separate.
- Any later fix still needs executor evidence before completion is reported.

## JSON-to-UI Mapping

| Rendered UI | Source field |
| --- | --- |
| Bot headline | `chat_response.headline` |
| Bot body | `chat_response.body` |
| Button ids | `chat_response.actions[].id` |
| Thread key | `thread_key` |
| Current phase | `chat_response.state.phase` |
| Evidence boundary | `chat_response.claim_boundary` |
| Status headline | `status_card.headline` |
| Status rows | `status_card.steps[]` |
| Primary status action id | `status_card.primary_action` |
| Primary status button label | `status_card.primary_action_label`, `status_card.executor_next_action_label`, or the matching `executor_actions[].label` |
| User-facing executor status | `status_card.executor_display_status_lines[]` |

Hermes Agent surfaces should render these fields natively and keep OMH focused
on the routing, handoff, status, and evidence contract.
