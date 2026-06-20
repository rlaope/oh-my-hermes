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
uv run python examples/discord-adapter-shim.py examples/wrapper-events/discord-command-preview.json
uv run python examples/slack-adapter-shim.py examples/wrapper-events/slack-command-preview.json
uv run python examples/telegram-adapter-shim.py examples/wrapper-events/telegram-command-preview.json
uv run python examples/discord-adapter-shim.py --route-hint examples/wrapper-events/discord-route-hint-visual.json
uv run python examples/slack-adapter-shim.py --route-hint examples/wrapper-events/slack-route-hint-missed-route.json
uv run python -m src.cli chat route-hint --source discord "make an image explaining the cron feature"
uv run python -m src.cli chat native-command --source discord
uv run python -m src.cli chat native-command --source slack
uv run python -m src.cli chat native-command --source telegram
uv run python -m src.cli demo orchestration
```

The first command renders the fixture event in
`examples/wrapper-events/discord-safe-feature.json`. The second command renders
the full deterministic path:

```text
recommend -> chat response -> Hermes plan -> selected executor/runtime handoff -> status card
```

## Messenger-Native OMH Entry

For platforms that support registered commands or bot menus, wrappers can load
the deterministic OMH command contract:

```sh
omh chat native-command --source discord
omh chat native-command --source slack
omh chat native-command --source telegram
```

Those commands return `omh_native_command_surface/v1` with the platform's `/omh`
or menu registration shape plus the same evidence boundary used by the chat
contract. If the user sends only `./` or `/` in a normal chat message and the
platform cannot show live autocomplete, the wrapper can render the fallback
card returned by `omh_native_command_render/v1`:

```text
Hermes Agent  BOT
Open OMH

Choose `omh` to open the workflow picker. The picker appears before any
workflow, plan, handoff, or execution is selected.

[ Open omh ]

State
- Response kind: command_preview
- Opens: omh_skill_picker/v1
- Claim boundary: preview/card rendering is not workflow selection or execution evidence.
```

User-facing effect:

- Typing `./` does not expose every workflow name at once.
- Discord can register `/omh`, Slack can register `/omh` or a shortcut, and
  Telegram can register the `omh` bot command menu.
- If native command preview is limited by the platform, the user still gets an
  `Open omh` card in the same Hermes conversation.
- The card only opens the picker; it does not claim that a workflow started.

## Catalog Questions Without Shell Approval

If the user asks "what OMH commands are available?" or "skill들은 뭐 있어?",
wrappers should call `omh chat interact` and render
`chat_response.kind == skill_picker`:

```text
Hermes Agent  BOT
[omh] oh-my-hermes - Here are the OMH workflows.

You do not need to run a shell command for this. Pick a workflow here, or choose
Route for me and Hermes will select the safest next step.

[ Choose workflow ] [ Search workflows ] [ Show status ]
```

The wrapper should not ask the user to approve `omh list` merely to show the
catalog. `omh_skill_picker/v1` carries the workflow labels, direct invocation
text, harness names, and routing-only claim boundary. Catalog-question
responses also include `omh_capability_summary/v1`, so Hermes can summarize the
larger lanes, representative playbooks, and evidence boundary before or beside
the picker.

## Plugin Route Hints

When the optional OMH plugin bridge is loaded, `pre_llm_call` can add a bounded
`omh_route_hint/v1` context block for messages that look like workflow-shaped
work. The hint does not include the raw user message. It carries only message
hash/length metadata, matched cue labels, a candidate workflow, adjacent
workflows, the next action, and the same prepared-vs-observed boundary.

Example effect:

```text
User
make an image explaining the cron feature

Hermes Agent
[OMH Route Hint]
- workflow=img-summary; lane=materials_and_visuals; next_action=prepare_visual_prompt_card
- workflow=automation-blueprint; lane=automation_and_status; next_action=prepare_scheduled_ops_blueprint
```

The wrapper still owns rendering and state recording. The route hint is prompt
context only; it is not workflow execution, image generation, scheduled job
creation, review, CI, or delivery evidence.

Wrappers do not need to wait for plugin load to show the same kind of hint. They
can call the transport-free backend preview:

```sh
omh chat route-hint --source discord "make an image explaining the cron feature"
```

Capability-specific catalog questions should also stay workflow-native. If the
user asks "이미지 생성 기능 뭐 있어?", "does OMH support image generation?", or
"what image generation features does OMH have?", the wrapper should render the
`img-summary` card with `show_visual_prompt_card`, `choose_image_generator`, and
`image_generation_setup/v1` actions instead of falling back to the generic OMH
workflow picker.

The same rule applies to other specific capability questions. A broad question
such as "OMH 기능 뭐 있어?" still opens `omh_skill_picker/v1`, but "does OMH
support scheduled automation?", "can OMH help with MCP setup?", "does OMH
support memory cleanup?", "does OMH support voice commands?", or "OMH로 GitHub
issue webhook 처리 가능해?" should open the matching workflow card directly.
Selection remains routing intent only; host automation, credentials, memory
updates, platform actions, and webhook effects stay unobserved until separate
evidence is recorded.

That returns `chat_route_hint/v1` with a `chat_response` card the adapter can
render immediately:

```text
Hermes Agent  BOT
[omh] img-summary looks relevant.

I can open `img-summary` first because this request matches the materials and
visuals lane. Next action: `prepare_visual_prompt_card`.

[ Open img-summary ] [ Route for me ] [ Open omh ]

State
- Hint only: no workflow has been selected or executed.
- Safe to render without shell approval.
- Plugin load is not required.
```

Use `--prompt-context` only when a wrapper intentionally injects the compact
`[OMH Route Hint]` text into Hermes context itself. The default response is the
safer card/JSON contract and never echoes the raw prompt.

The transport-free adapter shims can render the same card directly from fixture
events:

```sh
uv run python examples/discord-adapter-shim.py --route-hint examples/wrapper-events/discord-route-hint-visual.json
uv run python examples/slack-adapter-shim.py --route-hint examples/wrapper-events/slack-route-hint-missed-route.json
```

Those examples lock the wrapper behavior in `examples/wrapper-golden/route-hints.json`:

```text
Hermes Agent  BOT
[omh] img-summary looks relevant.

I can open `img-summary` first because this request matches the materials and
visuals lane. Next action: `prepare_visual_prompt_card`.

[ Open img-summary ] [ Route for me ] [ Open omh ]
```

For missed OMH usage feedback, the Slack fixture routes to `workflow-learning`
instead of treating the message as normal prose. The card still stays
metadata-only and hint-only until the user or wrapper chooses a workflow.

## Missed OMH Route Capture

If Hermes or the user says a response did not use the expected OMH workflow, the
wrapper can record that as review material without storing the raw chat prompt:

```sh
omh learning missed-route \
  --source discord \
  --expected-workflow img-summary \
  --expected-harness img-summary \
  --expected-next-action prepare_visual_prompt_card \
  --fixture-message "make an image explaining the cron feature" \
  "make an image explaining the cron feature"
```

This returns `learning_missed_route_result/v1`: a metadata-only trace, eval
summary, regression-case id, and human-review candidate id. The command does
not patch routing, rerun Hermes, execute a workflow, or prove future behavior is
fixed. If the wrapper omits `--fixture-message`, OMH records a non-replayable
placeholder and asks for an operator-minimized fixture before regression replay.

## Discord-Style Plan Response

```text
# repo-planning

maintainer-1
I want to safely add a feature to this repo

Hermes Agent  BOT
[omh] plan - I routed this to `plan` because it needs a safe plan first.

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
- Hermes Agent explains why the request became a plan-first workflow and shows
  the visible OMH trace prefix on the first line.
- The wrapper can show `Accept plan` and `Revise plan` immediately.
- `Prepare handoff` is visible but disabled until the plan is accepted.
- The response names what is not evidence yet instead of sounding like coding
  already happened.

## Visible OMH Trace And Messenger Formatting

Every wrapper-facing `chat_response/v1` can render a first-line usage marker
from `chat_response.usage_trace.visible_prefix`, for example:

```text
[omh] web-research - I know which workflow should handle this.
```

That marker is product status, not a command the user has to learn. The same
response includes `chat_response.messenger_rendering`, which tells Discord,
Slack, Telegram, Hermes TUI, web, and other adapters which rendering profile OMH
selected for that surface. Render `chat_response.messenger_rendering.body_text`
for the selected profile. Narrow messenger profiles convert wide Markdown
tables into messenger-safe lists when possible, while rich Markdown profiles
preserve tables for TUI or web surfaces. If a rich response must be relayed into
a narrower chat surface, use
`chat_response.messenger_rendering.fallback_body_text`.
If a legacy response does not include `body_text`, render the original
`chat_response.body` and keep a warning visible in adapter diagnostics rather
than posting an empty message.

Apply the prefix once at the first line of one rendered response. Do not repeat
`[omh] <workflow>` on every paragraph or every line. If an adapter splits a
long answer into separate Discord/Slack messages, it can repeat the same prefix
once at the start of each chunk.

## First-Use Coding Agent Readiness

Coding handoff responses include `executor_readiness/v1` so the wrapper can
check Codex, Claude Code, Hermes coding, or oh-my runtime availability once per
profile instead of discovering it after the user presses a handoff button.

```sh
omh coding executor-readiness --executor codex
omh coding executor-readiness --executor claude-code
```

If readiness is `missing` or `blocked`, show a human choice instead of failing
silently: choose another coding agent, configure the command path, continue in
Hermes, or keep a prompt/runtime handoff. After the user changes that state,
retry the readiness check once. The probe only proves local availability; it is
not dispatch, implementation, review, CI, or merge evidence.

## Discord-Style Handoff Status Card

After the wrapper prepares the handoff, the demo status card can be rendered as
a progress block in the same thread:

```text
Hermes Agent  BOT
[omh] status - A coding-runtime handoff is ready.

I have prepared the handoff, but runtime start or executor/runtime dispatch is not
observed yet.

Status
[ready]   Workspace isolation
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
- `Start Codex session` and `Start Claude Code session` include an
  `executor_launch/v1` payload. The legacy v1 safety fields remain conservative:
  `ui_only`, `not_backend_execution`, and `execution_policy:
  copyable_instruction_only` do not mean OMH launched the executor. New renderers
  should use `terminal_launch_available` and `session_start_capability` to decide
  whether to show a Codex or Claude Code terminal command for the configured
  coding agent. Prompt placeholders use `{executor_prompt_shell_quoted}`;
  workspace command templates use `{workspace_path_shell_quoted}` for shell-safe
  paths. After Hermes or the wrapper observes that the coding session exists, it
  records the backend open action; a prepared command is still not execution
  evidence. Executors without a deterministic local command expose prompt-copy
  guidance only, not a terminal command.
- If `worktree_session_isolation/v1` says worktree recommended or required,
  render `Prepare worktree` before the open button. The action prepares wrapper
  UX and operator guidance; only `runtime_observation/v1` worktree evidence can
  mark the worktree as observed.
- After a worktree is prepared, the wrapper can call
  `omh worktree bind --path <worktree> --executor codex --session <session-id>`
  to get `worktree_executor_binding/v1`. That payload contains resolved launch
  command templates and messenger actions such as `Open in Codex`,
  `Attach existing session`, and `Record opened`. For `claude-code`, it returns
  Claude Code launch templates. For `hermes`, `omx-runtime`, `omo-runtime`, and
  `omc-runtime`, it returns prompt/runtime guidance plus a separate runtime
  observation recipe. The bind payload is still not executor dispatch or result
  evidence.
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
[omh] feedback-triage - I know which workflow should handle this.

Cluster feedback and recommend the next workflow; do not create a coding handoff
unless code work is explicit.

[ Show status ]

Claim boundary: Feedback triage is not a roadmap, implementation plan, or coding handoff by default.
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
[omh] ultraqa - I know which workflow should handle this.

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
[omh] deep-interview - This needs a clarification workflow before planning.

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
[omh] code-review - I know which workflow should handle this.

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
| Bot headline without prefix | `chat_response.plain_headline` |
| Bot body for rich/web surfaces | `chat_response.messenger_rendering.body_text` when `render_profile` is `rich_markdown` |
| Messenger-safe bot body | `chat_response.messenger_rendering.body_text` when `render_profile` is `limited_markdown`, or `chat_response.messenger_rendering.fallback_body_text` as a downgrade |
| Messenger body blocks | `chat_response.messenger_rendering.body_blocks`; use `fallback_body_blocks` when downgrading |
| Visible OMH workflow marker | `chat_response.usage_trace.visible_prefix` |
| Selected workflow/harness | `chat_response.usage_trace.selected_workflow`, `chat_response.usage_trace.selected_harness` |
| Workflow pattern card | `chat_response.state.workflow_explanation.workflow_context_card.label`, `.user_examples`, `.first_response_shape`, and `chat_response.usage_trace.workflow_context_id` |
| Why/next/not-evidence card | `chat_response.state.workflow_explanation.why_this_workflow`, `chat_response.state.workflow_explanation.next_action_label`, `chat_response.state.workflow_explanation.not_evidence_yet` |
| Rendering profile and hints | `chat_response.messenger_rendering.render_profile`, `chat_response.messenger_rendering.transforms_applied`, `chat_response.messenger_rendering.fallback_transforms_applied`, `chat_response.messenger_rendering.preferred_blocks`, `chat_response.messenger_rendering.avoid_blocks`, `chat_response.messenger_rendering.table_policy`, `chat_response.messenger_rendering.prefix_policy` |
| Button ids | `chat_response.actions[].id` |
| Thread key | `thread_key` |
| Current phase | `chat_response.state.phase` |
| Evidence boundary | `chat_response.claim_boundary` |
| Status headline | `status_card.headline` |
| Status rows | `status_card.steps[]` |
| Primary status action id | `status_card.primary_action` |
| Primary status button label | `status_card.primary_action_label`, `status_card.executor_next_action_label`, or the matching `executor_actions[].label` |
| Executor launch command UI | `status_card.executor_actions[].payload.launch.command_templates[]`, `status_card.executor_actions[].payload.launch.copy_blocks[]` |
| User-facing executor status | `status_card.executor_display_status_lines[]` |
| Coding work briefing | `coding_briefing.user_facing_lines[]` |
| Coding progress ladder | `coding_briefing.progress[]` |
| Missing coding evidence | `coding_briefing.pending_gaps[]` |

Hermes Agent surfaces should render these fields natively and keep OMH focused
on the routing, handoff, status, and evidence contract.
