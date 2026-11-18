# Chat Wrapper Examples

This page shows how a Discord-style Hermes Agent surface can render OMH output
as a normal chat response. The example is generated from local fixtures so the
contract is easy to inspect.

The commands on this page are for wrapper developers and maintainers. Chat users
interact with the rendered Hermes response and do not run these backend commands.

For the operator runbook that ties these examples to state transitions,
responsibilities, and evidence boundaries, read
[Hermes Agent Integration Runbook](HERMES_AGENT_INTEGRATION_RUNBOOK.md).

## Wrapper / Maintainer Commands Used

```sh
uv run python examples/discord-adapter-shim.py
uv run python examples/discord-adapter-shim.py examples/wrapper-events/discord-command-preview.json
uv run python examples/slack-adapter-shim.py examples/wrapper-events/slack-command-preview.json
uv run python examples/telegram-adapter-shim.py examples/wrapper-events/telegram-command-preview.json
uv run python examples/discord-adapter-shim.py --plugin-interact examples/wrapper-events/discord-workflow-catalog.json
uv run python examples/slack-adapter-shim.py --plugin-interact examples/wrapper-events/slack-risky-refactor.json
uv run python examples/discord-adapter-shim.py --route-hint examples/wrapper-events/discord-route-hint-visual.json
uv run python examples/slack-adapter-shim.py --route-hint examples/wrapper-events/slack-route-hint-missed-route.json
uv run python -m omh.cli chat route-hint --source discord "make an image explaining the cron feature"
uv run python -m omh.cli chat route-hint --source discord --summary "make an image explaining the cron feature"
uv run python -m omh.cli chat native-command --source discord
uv run python -m omh.cli chat native-command --source slack
uv run python -m omh.cli chat native-command --source telegram
uv run python -m omh.cli demo orchestration
uv run python -m omh.cli demo orchestration --executor hermes
uv run python -m omh.cli demo chat-card-coverage --summary
uv run python -m omh.cli demo route-hint-alignment --summary
uv run python -m omh.cli demo localized-chat-copy --summary
```

The first command renders the fixture event in
`examples/wrapper-events/discord-safe-feature.json`. The second command renders
the full deterministic path:

```text
recommend -> chat response -> Hermes plan -> selected executor/runtime handoff -> status card
```

By default `omh demo orchestration` leaves the coding owner unselected and shows
the `choose_executor` state. Add `--executor codex`, `--executor claude-code`,
or `--executor hermes` when the demo should show the selected Codex lifecycle,
Claude Code prompt handoff, or Hermes runtime handoff path. In every case the
status card remains prepared-only until separate dispatch or runtime evidence
is observed.

## Coding Route Decisions

Setup does not ask who owns coding work; it records `choose` so Hermes resolves
the owner at the first coding request. Two surfaces report that resolution with
the same vocabulary:

- `awareness_route_hint(...)["primary_coding_route_decision"]`, mirrored on each
  coding-delivery hint as `hints[].coding_route_decision`.
- `omh chat interact ...` -> `coding_route_decision`, mirrored on
  `delegation.coding_route_decision`.

Direct `ulw-work` invocations, broad coding delivery, and test-until-pass
requests all report the same lane action, `prepare_one_cycle_delivery`. The lane
action says which lane to prepare; it deliberately says nothing about who owns
the code. Ownership is the separate `coding_route_decision.next_action`, which
is always one of four states:

| `next_action` | `source` | Meaning |
| --- | --- | --- |
| `prepare_named_executor_handoff` | `request_named_executor` | The request (or an explicit `--executor` target) named the coding agent. |
| `prepare_recorded_owner_handoff` | `recorded_setup_preference` | A persisted setup profile already names the owner. |
| `prepare_compatible_route_handoff` | `request_capability_match` | The request named the owner *shape* it needs, so a compatible route family was matched. |
| `choose_executor` | `user_choice_required` | Nothing resolves the owner safely, so the user picks. |

Every decision carries `source`, `reason`, `confidence`
(`high`/`medium`/`low`), `choice_required`, and `matched_cues`. A
`prepare_compatible_route_handoff` decision reports
`selected_route_family` (`prompt_only_handoff` or `runtime_handoff`) rather than
a vendor, so no single coding agent becomes an implicit default.

`choose_executor` is retained on purpose. The decision falls back to it whenever
the request names more than one coding agent, asks for more than one route
family, or reaches for merge, release, production, or credential authority.

A coding route decision is prepared guidance about ownership. It is not executor
dispatch, implementation, review, CI, merge-readiness, or merge evidence, and
its `claim_boundary` field repeats that on every payload.

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

Render the picker in this order:

- `featured_options` first, usually `Route for me`
- `groups` next, so users see intent-to-plan, ops, deliverables, and
  coding/runtime sections instead of one long flat list
- `options` only as the backward-compatible flat-list fallback
- `claim_boundary` visibly, because choosing a workflow is only routing intent
- `search_skills` for the full catalog when the compact picker is not enough

This lets Hermes answer catalog questions without asking the user to approve
`omh list`.

## Compact OMH Context For Hermes

When a wrapper only needs to prime Hermes before ordinary chat, image, file,
search, or coding tools, use `omh_context_brief/v1` instead of asking the user
to approve a shell command. The backend form is:

```sh
omh context brief --source discord --json "make an image card for this PR"
```

The CLI returns the full brief. It contains OMH lanes, capability family cards,
workflow context cards, common cues, a generic-tool checkpoint, an optional
route hint, catalog-question guidance, and the response contract. The raw
prompt is represented by hash/length metadata only.

The plugin-native form is the `omh_context` tool, and it returns a compact view
of the same brief. The tool's result rides every later model call of the
session, so the view makes three changes:

- It leaves out the capability family cards and workflow context cards.
  `omh_capabilities` action=summary returns both unchanged.
- It trims each checkpoint route to five fields: its tool family, workflow,
  next action, fallback action, and not-evidence list.
- It adds `view: "compact"` and an `expand` line saying where the dropped
  parts are.

The view keeps `schema_version: omh_context_brief/v1`, and every key it keeps
has the full brief's value; `view` tells the two apart.

When the message asks what OMH commands, workflows, or skills are available,
the payload includes `catalog_question.schema_version ==
omh_catalog_question_hint/v1`. Hermes can then summarize the lanes and offer
`omh_skill_picker/v1` or call `omh_capabilities` with `{"action":"summary"}`
without asking the user to approve `omh list`.

For an image request, Hermes can then say:

```text
Hermes Agent  BOT
[omh] omh-image-cards looks relevant.

This sounds like a visual summary request, so I will prepare the OMH
omh-image-cards prompt card first. Image generation, visual QA, and delivery are
not evidence yet until your connected image tool or wrapper records them.

[ Open omh-image-cards ] [ Choose image tool ] [ Record visual evidence ]
```

For a web visual QA request that should later show screenshot attachments in a
Discord-like surface, Hermes can prepare the capture package without claiming
the capture, upload, delivery, or multimodal review already happened:

```text
Hermes Agent  BOT
[omh] visual-qa - I can prepare rendered visual QA without pretending screenshots exist.

I will prepare web_visual_qa_package/v1 with captures[], criteria[],
criteria_results[], optional host-observed multimodal_reviews[], and
message_attachment_projection/v1 for chat attachment candidates. Auto-routing
starts at prepare_capture when no screenshot evidence is observed; higher-risk
or unresolved evidence routes to operator review.

[ Prepare visual QA ] [ Show capture package ] [ Prepare attachments ] [ Record capture ] [ Record multimodal review ]

Claim boundary: This is not screenshot capture, message upload, platform
delivery, visual PASS, or a multimodal model call by OMH.
```

The wrapper may render the attachment projection as a message UI preview only
after capture paths or URIs are observed. `delivery_observed` remains false
until the Discord, Slack, or other platform adapter records upload and delivery
evidence. Multimodal review is allowed as host-supplied observed evidence, but
OMH core does not call a vision model or treat model availability as free.

The wrapper should not ask the user to approve `omh list` merely to show the
catalog. `omh_skill_picker/v1` carries the workflow labels, direct invocation
text, harness names, and routing-only claim boundary. Catalog-question
responses also include `omh_capability_summary/v1`, so Hermes can summarize the
larger lanes, representative playbooks, and evidence boundary before or beside
the picker. When an operator or trusted backend already has permission to query
the local install, `omh list --json` also includes
`omh_installed_skill_catalog_context/v1` plus per-skill descriptions, routing
hints, and evidence boundaries, so a catalog answer does not degrade into a flat
name list.

## Task Abstraction Before Workflow Routing

Some requests are bigger than one workflow name. If a user says "reproduce this
Hermes and Friren setup on another MacBook, back it up to private GitHub, and
make sure only one Discord bot answers", OMH should not invent a narrow
`migration` workflow. The wrapper can render the `omh_task_card/v1` that sits
above the workflow rails:

```text
Hermes Agent  BOT
[omh] task-card - I will frame this as a high-level task first.

This is a runtime portability task, not a migration workflow. First safe
action: inventory configs, local state, plugin paths, managed skills, gateways,
and secret locations before packaging. Use workflow rails:
agent-ops-review, toolbelt-readiness, gateway-intent-card, doctor. Secret
policy: encrypt before private GitHub upload. Gateway invariant: exactly one
active responder. Not observed yet: encrypted backup archive, private GitHub
upload, runtime restore on the second machine, gateway responder cutover.

[ Open ops review ] [ Show status ] [ Record learning trace ]
```

The task card is still prepared guidance only. Backup creation, private repo
upload, restore, gateway transfer, liveness, and verification remain
observed-only claims until a wrapper or operator records matching evidence.
If the user says the routing model itself was wrong, including Korean feedback
such as "피드백인데 OMH 라우팅 설계가 잘못됐어", the same abstraction layer routes
to `workflow-learning` instead of customer `feedback-triage`.

## Plugin-Native Chat Interaction

When the managed OMH plugin is loaded, a Hermes wrapper can call the plugin
tool `omh_interact` directly. That path returns the same renderable
`chat_interaction/v1` envelope as `omh chat interact`, and it can also record a
metadata-only wrapper session with `record_provenance.producer == plugin_tool`.

The transport-free shims can render this without touching your real `~/.omh` or
`~/.hermes` state:

```sh
uv run python examples/discord-adapter-shim.py --plugin-interact examples/wrapper-events/discord-workflow-catalog.json
uv run python examples/slack-adapter-shim.py --plugin-interact examples/wrapper-events/slack-risky-refactor.json
```

Example catalog effect:

```text
Hermes Agent  BOT
[omh] oh-my-hermes - Here are the OMH workflows.

You do not need to run a shell command for this. OMH covers planning, ops,
deliverables, coding handoffs, loops, and status.

[ Choose workflow ] [ Search workflows ] [ Show status ]

Plugin session
- tool: omh_interact
- wrapper_session: recorded
- producer: plugin_tool
- state scope: temporary example
```

Example plan effect:

```text
Hermes Agent  BOT
[omh] ulw-plan - I routed this to `ulw-plan` because it needs a safe plan first.

Accept or revise the plan first; choose the executor before handoff if needed.
A draft plan is still only planning evidence.

[ Accept plan ] [ Revise plan ] [ Choose coding agent ] [ Prepare handoff disabled ]
```

These examples are locked by
`examples/wrapper-golden/plugin-interact.json`. The plugin observation and
wrapper session record prove only that the plugin tool produced metadata for
the wrapper. They do not prove workflow execution, executor dispatch,
verification, review, CI, or merge.

## Plugin Route Hints

When the managed OMH plugin bridge is loaded, `pre_llm_call` can add a bounded
`omh_context_brief/v1` payload plus an `omh_route_hint/v1` context block for
messages that look like workflow-shaped work. The payload and hint do not
include the raw user message. They carry only message hash/length metadata,
matched cue labels, candidate workflows, adjacent workflows, next actions, the
generic-tool checkpoint, the first response shape, fallback action, and the
same prepared-vs-observed boundary.

Example effect:

```text
User
make an image explaining the cron feature

Hermes Agent
[OMH Route Hint]
intent=unknown; selected=img-summary; confidence=medium
- selected=img-summary; lane=materials_and_visuals; next_action=prepare_visual_prompt_card
  first_response_shape=Separate copy/layout/package prep from generated file or image evidence, then offer revise/copy/generate/record actions.
  fallback_action=choose_image_generator_or_prompt_only_when_missing.
- selected=automation-blueprint; lane=automation_and_status; next_action=prepare_scheduled_ops_blueprint
  first_response_shape=Show the prepared status, schedule, or learning shape, name the missing evidence, and expose refresh, repair, or review actions.
  fallback_action=confirm_schedule_delivery_and_tools.
```

The wrapper still owns rendering and state recording. The context brief and
route hint are prompt/context guidance only; they are not workflow execution,
image generation, scheduled job creation, review, CI, or delivery evidence.
If a route-hint or managed-skill change has just shipped, a live Hermes Agent
or gateway may still show the old injected hint until the installed OMH package
and managed plugin are refreshed with `omh update` or `omh setup`, then the
Hermes Agent or gateway process is restarted or reloaded.

OMH-owned wrapper and progress reports must render only bounded summaries from
Codex/background output. They must not echo process completion wrappers such as
`Background process ... Here's the final output`, raw JSONL `turn.completed` or
`usage` token objects, token counts, or `Self-improvement review` lines into
normal chat progress/completion copy. The host process tool may still emit its
own notification outside OMH control; adapters should treat that as a separate
Hermes/gateway surface, not as OMH's report body.

Wrappers do not need to wait for plugin load to show the same kind of hint. They
can call the transport-free backend preview:

```sh
omh chat route-hint --source discord "make an image explaining the cron feature"
omh chat route-hint --source discord --json "make an image explaining the cron feature"
```

The preview payload also includes `generic_tool_checkpoint.routes`, so adapters
do not need to parse prose before opening generic tool surfaces. The default
terminal form prints status, primary workflow, next action, matched cues, hint
details, checkpoint, and evidence boundary for operator QA. Adapters should pass
`--json` for the complete machine-readable payload.

Release QA should also run:

```sh
omh demo route-hint-alignment --summary
```

That gate compares the public chat router, chat-card payload, and plugin
awareness hint over the grounded operator and chat-card scenario corpus. It
catches cases where Hermes would route to the right OMH workflow but the
injected route hint says `no_hint` or names a different workflow.

The current OMH-first map is:

- image tools -> `img-summary` / `prepare_visual_prompt_card`
- file tools -> `materials-package` / `prepare_material_package`
- search tools -> `research` / `gather_source_backed_evidence`
- coding tools -> `ultrawork` first, with `ralplan`, `code-review`, and
  `agent-ops-review` as adjacent options

These routes are advisory. They tell Hermes which OMH workflow to consider
before a generic tool, while image generation, file export, search retrieval,
coding dispatch, review, CI, and merge remain observed-only claims.

The managed plugin does not mirror this checkpoint from its `pre_tool_call`
hook. That hook enforces user-authored toolcall rules (returning the host's
block directive on a match) and does not copy raw tool input into injected
context. An unknown OMH role in a `delegate_task` goal is warned in the child's
own turn, by `pre_llm_call`.

Capability-specific catalog questions and short image requests should also stay
workflow-native. If the user asks "이미지 생성 기능 뭐 있어?", "이미지 생성해줘",
"does OMH support image generation?", or "generate an image", the wrapper should
render the `img-summary` card with `show_visual_prompt_card`,
`choose_image_generator`, and `image_generation_setup/v1` actions instead of
falling back to the generic OMH workflow picker or a generic clarification.
If the user says the generator is blocked because an image connector, API key,
or credential is missing, route to `toolbelt-readiness` first. Examples include
"FAL_KEY 없어서 이미지 생성이 막히면 어떻게 연결해야 해?" or "the image tool is
not connected." That card should explain the missing tool/credential and the
safe setup action before any `img-summary` generation claim.

For first-use explanation questions, avoid dropping the user into the full
catalog immediately. If the user asks "what is OMH and how do I use it?" or
"OMH가 뭐야? 어떻게 써?", `omh chat interact` returns
`chat_response.kind == context_brief` with `[omh] context`, a compact mental
model, the structured `omh_context_brief/v1`, and actions to open the picker or
quickstart card. Use the picker for "what workflows are available?" and similar
catalog questions.

The same rule applies to other specific capability questions. A broad question
such as "OMH 기능 뭐 있어?" still opens `omh_skill_picker/v1`, but "does OMH
support scheduled automation?", "can OMH help with MCP setup?", "does OMH
support memory cleanup?", "does OMH support voice commands?", or "OMH로 GitHub
issue webhook 처리 가능해?" should open the matching workflow card directly.
The first visible action should be the matching workflow action, such as
`prepare_scheduled_ops_blueprint`, `prepare_toolbelt_readiness`,
`prepare_memory_sync`, `prepare_voice_operator_card`, or
`prepare_github_event_ops_card`, followed by a status action. Selection remains
routing intent only; host automation, credentials, memory updates, platform
actions, and webhook effects stay unobserved until separate evidence is
recorded.

That returns `chat_route_hint/v1` with a `chat_response` card the adapter can
render immediately:

The same primary-action rule applies to normal routed workflow cards, not only
catalog capability questions. For example, `research`,
`strategy-brief`, `code-review`, `gateway-intent-card`,
`ops-observability-card`, and `report-package` responses should place the
workflow `next_action` first, then a status action. A route such as
`run_hermes_research`, `prepare_strategy_brief`,
`prepare_review_or_followup_handoff`, `prepare_gateway_intent_card`,
`prepare_ops_observability_card`, or `prepare_report_package` is still only a
prepared wrapper action until observed work or evidence is recorded.

Release QA can guard this with the deterministic card coverage gate:

```sh
omh demo chat-card-coverage --summary
```

That gate checks the important user-facing workflow routes, confirms they render
dedicated card kinds instead of generic `ack`, and verifies next action, primary
action availability, claim boundary copy, and not-yet-observed evidence. It is
wrapper-contract coverage only; it does not prove live Hermes chat rendering,
platform delivery, executor work, review, CI, or merge.

For common non-English operator prompts, wrappers can also run:

```sh
omh demo localized-chat-copy --summary
```

That gate verifies local card framing, expected card kind, and next action for
Japanese, Chinese, Spanish, French, German, and Korean fixtures without calling a
translation API. It remains local copy-contract coverage only; live messenger
rendering and translation quality still require separate evidence.

```text
Hermes Agent  BOT
[omh] omh-image-cards looks relevant.

I can open `omh-image-cards` first because this request matches the materials and
visuals lane. Next action: `prepare_visual_prompt_card`. Checkpoint: Before
generic tools, check OMH prep/status/learning; if relevant, name the workflow
first.

[ Open omh-image-cards ] [ Route for me ] [ Open omh ]

State
- Hint only: no workflow has been selected or executed.
- OMH-first checkpoint: visible before image/file/search/coding tools.
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
[omh] omh-image-cards looks relevant.

I can open `omh-image-cards` first because this request matches the materials and
visuals lane. Next action: `prepare_visual_prompt_card`. Checkpoint: Before
generic tools, check OMH prep/status/learning; if relevant, name the workflow
first.

[ Open omh-image-cards ] [ Route for me ] [ Open omh ]
```

The card's `kind` says which of three cards it is:

- `workflow_route_hint`: the hint names a workflow. The actions open it, route
  the message, or open the picker.
- `no_route_hint`: nothing matched. The actions open the picker or ask Hermes
  to clarify.
- `direct_answer_route_hint`: the router answers the message in chat, so the
  card says no OMH workflow is needed and offers no actions,
  `messenger_rendering.primary_action` is `null`, and
  `wrapper_contract.next_backend_commands` names no workflow. A thank-you, a
  plain question, a turn Hermes wrote from one of its own session-command
  templates, and a loop on a timer (Hermes' own `/loop`) all get it, even when
  the hint named a workflow. The hint itself stays in `route_hint`.

```text
Hermes Agent  BOT
[omh] no workflow needed.

This message needs no OMH workflow; Hermes can answer it directly in chat.
```

The direct-answer card is chosen from `route_decision.reason_code`, a stable
name for each of the router's answer-in-chat fallbacks. `direct_answer`,
`host_command_turn`, `native_loop_cadence`, `typed_loop_goal`,
`loop_construct`, and `code_backlog` (a listed backlog of four or more code
changes, made in the session without a workflow or child agents) give the
direct-answer card; `file_lookup` keeps the no-hint
card. The full route payload, `route` in both `omh chat route --json` and
`omh chat interact --json`, carries the same `reason_code`. The key is
additive: a route with none of these reasons has no `reason_code`, and
`reason` stays prose for a reader. Branch on the code, never on `reason`, which
the compact `route_decision` truncates. A wrapper that meets a `kind` it does
not know should render the headline and body as a plain chat card, as the
example shims and the native command renderer do.

For missed OMH usage feedback, the wrapper does not need to teach the user a
backend command first. Phrases such as "OMH 안 썼어", "missed route: Hermes
skipped OMH", or "Hermes did not use OMH for my image request; record this as
workflow learning" route to `workflow-learning` with `record_missed_route` as
the primary action. Domain-specific recovery phrases can still route to the
expected workflow, such as `img-summary` or `operating-rhythm`, when the user is
asking Hermes to do the work now rather than record a learning case. The card
still stays metadata-only and hint-only until the user or wrapper records the
missed-route review bundle.

## Undecidable Routes Carry A Typed Question

The deterministic router cannot always decide. A script the shipped trigger
packs do not cover, a near-tie between two candidates, or a low-confidence score
each hand the shortlist to model selection, and the same shortlist is also typed
as a question. `omh chat route`, `omh chat interact`, and the `omh_interact`
plugin tool carry it as `route.route_question`; `omh chat route-hint` carries it
as a top-level `route_question` key of `chat_route_hint/v1`. A route the router
did decide carries no question at all, so the key's presence is readable as "OMH
could not decide this one". `omh_recommend` and `omh_context` do not carry it:
they build their payload from the awareness hint and never see the core route.

```sh
omh chat route-hint --source discord --json "почему сборка падает на main"
```

Excerpted below: the payload also carries `route_hint`, `route_decision`,
`generic_tool_checkpoint`, and the rest of `chat_route_hint/v1`, and the
question carries one `fits::<workflow>` entry per candidate plus its own
`claim_boundary`, as does each answerer rung. The digest below is one observed
run; it covers the request and the shortlist together, so it moves whenever
either does. Read it as a shape and never as a constant.

```json
{
  "schema_version": "chat_route_hint/v1",
  "route_question": {
    "schema_version": "route_question/v1",
    "question_digest": "75a002019335e0417d029a244c21975a12f031c7a9abd7c7d11f2c003d1a7808",
    "reasons": ["no_trigger_coverage", "narrow_score_gap", "low_confidence"],
    "questions": {
      "route_choice": {
        "type": "choice",
        "instructions": "Which OMH workflow is the best fit for this request? This is a relative choice among the listed options: pick the closest fit, or `none` when the request asks for none of them.",
        "options": {
          "none": "No OMH workflow applies; answer the request directly.",
          "oh-my-hermes": "Choosing among OMH skills for a request: router guidance for using oh-my-hermes workflow skills inside Hermes Agent.",
          "plan": "Unplanned feature or bugfix: structured planning before execution."
        }
      },
      "fits::plan": {
        "type": "noul",
        "instructions": "Does this request ask for the work `plan` does? `plan`: Unplanned feature or bugfix: structured planning before execution. Answer for this workflow alone, independently of the others."
      }
    },
    "thresholds": {"fits_dispatch": 0.8, "fits_clarify": 0.5}
  },
  "route_question_answerers": [
    {"answerer": "main_model", "status": "available"},
    {"answerer": "none", "status": "available"}
  ]
}
```

The two question kinds answer different things and carry no invariant between
them. The Choice is relative and picks WHICH option is closest; each yes/no fit
question is absolute and judges one workflow on its own, so an answer may fit
nothing and still name a Choice. The shortlist is cut to the caller's candidate
limit, which is why `--max-hints 2` and the router's default of three produce
different digests for one message.

`route_question_answerers` reports what could answer the question on this
machine and is a report, never a recommendation. `main_model` and `none` are
always present. A `jev_plugin` rung appears only when a Jev-class plugin was
detected, at the strongest tier OMH can prove: `installed` when a manifest
declares a `jev_` tool, `enabled` when Hermes' config also lists the plugin, and
`observed` when such a tool call has reached dispatch here at least once. OMH
never calls a third-party plugin, and no text OMH injects into a turn names a
third-party tool. An `omh_jev_ask` rung comes first when OMH's own opt-in Jev
tool has a route on this machine (a `TYPESAFE_API_KEY`, or an OpenRouter key
plus the operator setting); the `omh-jev-route` skill uses it, and only after
the user asks Jev in that turn, because the ask sends the user's message off the
machine.

An answer is recorded with the `omh_route_answer` plugin tool and changes
nothing: the deterministic route stays in force whether the question is answered
or not. The record is written so the answerer can be measured: it embeds the
`routing_question_answers/v1` row that `omh chat route-questions score --answers
<dir>` reads, so a second opinion is scored against OMH's own routing corpora.
`confidence_source` names who spoke, never how good the number is:
`self_reported` when the host model answered about itself, `answerer_declared`
when a plugin reported a number OMH did not observe, and `observed_from_response`
when OMH's own `omh_jev_ask` call received it. `answered_by: omh_jev_ask` is
refused unless its `ask_id` names an answered ledger row for the same digest. An
answer whose digest names a question the message cannot produce is refused
rather than recorded.

The record also carries `message_sha256`, the sha256 of the raw request, and
repeats it on the embedded row. That is what a scorer joins on, because the
digest covers the shortlist and one shortlist serves every request the router
could not place. Send `message` and OMH derives the hash itself; send
`message_sha256` when the hash is at hand but the request text is not. Sending
both with different values is refused, since the two name different requests.
Send neither and the record identifies no request, recorded as an empty string
rather than a hash of nothing.

### Mode, decline, invalid answers, and the shadow report

The route question runs in one of two modes, read from the operator's own OMH
config at `<omh_home>/routing/route-question.json`, never from the model:

```json
{"mode": "off"}
```

- `shadow` (the default, and the behaviour before the mode existed): the
  question is attached to every undecidable route and answers are recorded
  without changing it. The payload is byte for byte what it was.
- `off`: no surface hands the question out.

Every answer record and every `omh chat route --record` routing record carries
`mode` and `mode_source`: `omh_config` when the file set it, `default` when there
is no file. A file that exists and cannot be read, parsed, or understood gives
`mode: unknown` with a `mode_error`, never the default, and the surface then
behaves as `shadow`. `{"mode": "on"}` -- a mode in which an answer would decide
the route -- is not available and reads as `unknown` with `on_not_available`.

Two records carry the route and its question summary (`built`, `asked`,
`decline_reason`, `mode`, `mode_source`) next to the request's
`message_sha256`, and never the message:

- `omh chat route --record` writes a `routing.json` for every recorded turn,
  decided or not.
- A recorded wrapper session (`omh_interact`, which records a session by
  default, or `omh chat session start`) appends one `route_question_observed`
  event to that session's `events.jsonl` on a turn that built a question. A
  decided turn writes nothing there.

`omh chat interact` without a session and `omh_interact` with
`record_session: false` record no route.

The decline verdict is one of four values:

- `acknowledgement`: a thank-you or an okay.
- `one_word_reply`: the whole message is one listed approval word, such as
  `lgtm`. A one-word request such as `refactor` still has candidates and is
  kept.
- `no_candidate`: the Choice offers only `none`.
- `single_candidate`: the Choice offers one workflow.

In `shadow` a declinable question is still asked; the reason is recorded so
the share of turns with nothing to decide is readable before anything acts on
it.

An answer whose Choice probabilities omit an option the question offered, do
not sum to one within 0.01, or do not peak at the chosen option is recorded
with `answer_verdict: invalid_answer` and the tool returns
`status: invalid_answer`. It counts as no opinion: the route is unchanged and
the turn continues. The corpus scorer applies the same rule to offline rows.
Coverage needs the question's options, which OMH re-derives only from
`message`. Without it the record says `coverage_checked: false`, and
`accepted` then covers mass and argmax only.

`omh chat route-questions report` reads the answers and both route records
above, and nothing else. It joins each answer to the newest route with the
same `message_sha256`, whichever record wrote it; the join ignores the route's
source and whether the answer came before or after it. It reports three rates:

- The decline rate counts every route that built a question, so a request
  routed twice counts twice.
- The invalid-answer rate.
- The agreement with the deterministic route. It excludes invalid answers,
  answers whose coverage was not checked, and answers with no recorded route,
  each named as an exclusion.

Each rate names its numerator, denominator, and exclusions.
`--model <alias>` prices a declared turn shape (192,000 input and 5,600 output
tokens) at that model's list price. The shape is another project's
self-reported median and is not an OMH measurement; the report says so
wherever it prints the cost.

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
[omh] ulw-plan - I routed this to `ulw-plan` because it needs a safe plan first.

Accept or revise the plan first; choose the executor before handoff if needed.
A draft plan is still only planning evidence.

Prepared staged workflow: Interviewer -> Reviewer -> Builder -> Reviewer.
Builder owner: executor choice required. Status: prepared_not_observed.

[ Accept plan ] [ Revise plan ] [ Choose coding agent ] [ Prepare handoff ] disabled

State
- Phase: planning
- Next action: present_plan
- Claim boundary: A draft plan is not execution evidence.
```

User-facing effect:

- The user does not need to know an `omh` command.
- Hermes Agent explains why the request became a plan-first workflow and shows
  the visible OMH trace prefix on the first line.
- The wrapper can show `Accept plan`, `Revise plan`, and `Choose coding agent`
  immediately.
- `Prepare handoff` is visible but disabled until the plan is accepted.
- The response names what is not evidence yet instead of sounding like coding
  already happened.

## Visible OMH Trace And Messenger Formatting

Every wrapper-facing `chat_response/v1` can render a first-line usage marker
from `chat_response.usage_trace.visible_prefix`, for example:

```text
[omh] research - Source-backed research can ground this.
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

## Pre-Handoff Coding Agent Readiness

Coding handoff responses include `executor_readiness/v1` so the wrapper can
check Codex, Claude Code, Hermes coding, or oh-my runtime availability before
the user presses a handoff button instead of discovering it afterwards.

```sh
omh coding executor-readiness --executor codex
omh coding executor-readiness --executor claude-code
```

A stored observation is reused only while it is still fresh and still bound to
the same profile, tool, permission profile, and workspace, so the check is safe
to run before every dispatch.

If readiness is `missing` or `blocked`, show a human choice instead of failing
silently: choose another coding agent, configure the command path, continue in
Hermes, or keep a prompt/runtime handoff. After the user changes that state,
retry the readiness check once.

If readiness is `stale`, an earlier observation no longer describes this
machine. The payload then carries `pre_handoff_readiness/v1` with the reason
and `pre_handoff_repair_card/v1` with the missing prerequisite and the commands
that close it:

```sh
codex --version                                       # confirm the prerequisite
omh coding executor-readiness --executor codex --force # re-observe readiness
```

Render the card and keep the handoff prepared. `--force` is the only thing that
replaces a stale observation, and the card is prepared guidance: OMH did not
install a tool, change a permission, or re-probe anything. The probe only proves
local availability; it is not dispatch, implementation, review, CI, or merge
evidence.

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
  than asking the chat user to run it. Hermes, OMX, pi-family runtime, and
  OMC profiles render a runtime handoff with team/swarm, worker-protocol, and
  worktree guidance. Claude Code and generic profiles render a copyable prompt
  handoff instead of lifecycle evidence.
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
  Claude Code launch templates. For `hermes`, `omx-runtime`, `pi-family-runtime`, and
  `omc-runtime`, it returns prompt/runtime guidance plus a separate runtime
  observation recipe. The bind payload is still not executor dispatch or result
  evidence.
- Execution, verification, CI, merge-readiness, and merge stay separate.
- The wrapper can keep editing the same thread as evidence arrives.

## Grounded Operator Examples

The following examples were run through `omh chat interact --source discord`.
They show how different natural-language messages should produce different
wrapper-native responses instead of forcing every request into coding.
Every route payload also includes `route_explanation/v1`, a compact
why/next/not-yet-evidence card that wrappers can render next to the main
response without exposing shell commands or raw prompt text. The same card now
also carries `recommended_reply`, `primary_action_label`, and
`primary_action_hint` so a chat surface can show a natural first reply and a
clear next button without inventing copy or implying execution happened.

### Startup Product Triage

```text
# product-feedback

operator
결제 실패 이슈가 자주 나와

Hermes Agent  BOT
[omh] feedback-triage - I can triage this signal before anyone codes.

I will treat this as a customer or product signal first: cluster reports,
separate bug, request, and question paths, name severity and affected surface,
then prepare investigation and reproduction questions. A coding handoff only
follows after the signal is classified and reproduction or acceptance evidence
exists.

[ Triage signal ] [ Prepare fix handoff ] disabled [ Prepare triage report ] [ Show status ]

Claim boundary: Feedback triage is not a roadmap, implementation plan, or coding handoff by default.
```

What gets better for the team:

- The message is treated as product/bug triage, not instant implementation.
- The next step is investigation and reproduction planning before any coding
  handoff.
- The future handoff can carry acceptance criteria and verification checks.

### Operating Review, Strategy, And Report Cards

```text
# weekly-ops

operator
prepare weekly ops review from customer feedback and release risks

Hermes Agent  BOT
[omh] ops-review - I can turn this into an operating review.

I will prepare a compact operating review: observed status, customer signals,
release risks, blockers, owners, and follow-up questions. Unknowns stay visible
until source, owner, delivery, or runtime evidence is recorded.

[ Prepare ops review ] [ Prepare report ] [ Show status ]

Claim boundary: An ops review is not implementation, release, CI, review, or merge evidence.
```

```text
# strategy

operator
we need a competitor market scan and strategy memo for next week's leadership meeting

Hermes Agent  BOT
[omh] strategy-brief - I can shape this into strategy options.

I will prepare the strategy brief: decision frame, options, tradeoffs,
assumptions, evidence gaps, decision owner, and open questions. Coding or
delivery work stays disabled until a decision is accepted.

[ Prepare strategy ] [ Prepare meeting brief ] [ Prepare coding handoff ] disabled [ Show status ]

Claim boundary: A strategy brief is not an accepted decision or implementation evidence.
```

```text
# leadership-report

operator
create a PPT report package for a monthly leadership status deck

Hermes Agent  BOT
[omh] report-package - I can package this into a report people can review.

I will prepare the report package: source inputs, narrative outline, missing
numbers, reviewer checkpoints, export checklist, and delivery status. Binary
export, visual QA, approval, and attachment remain observed-only.

[ Prepare report ] [ Prepare file package ] [ Show status ]

Claim boundary: A report package or PPT-ready outline is not source-review completion, stakeholder approval, presentation delivery, or binary PPTX export evidence.
```

What gets better for the team:

- Ops review, strategy, and report packaging no longer look like generic routing
  acknowledgements.
- Strategy cards make implementation handoff visibly unavailable until a
  decision exists.
- Report cards separate outline preparation from binary export, render QA,
  approval, and delivery.

### Delivery And Runtime Cards

```text
# product-delivery

operator
take this product idea from plan to deploy and monitor safely

Hermes Agent  BOT
[omh] idea-to-deploy - I can shape this into a product delivery loop.

I will prepare the idea-to-deploy loop: product intent, plan lane,
implementation boundary, release gate, monitoring checks, rollback questions,
and owner handoffs. This is not implementation, deploy, monitoring, or
customer-impact evidence.

[ Show delivery loop ] [ Prepare implementation handoff ] disabled [ Show status ]

Claim boundary: A product delivery loop is not implementation, deployment, monitoring, rollback, or customer-impact evidence.
```

```text
# runtime-choice

operator
Claude Code로 넘길지 Codex로 넘길지 정해줘

Hermes Agent  BOT
[omh] executor-runtime-readiness - I can check which coding path is ready.

I will prepare a runtime readiness card: Codex, Claude Code, Hermes, and
generic runtime options; required tools; missing setup; fallback path; and what
a wrapper can ask next. This is not executor dispatch, session attachment,
implementation, verification, or CI evidence.

[ Check coding path ] [ Choose coding agent ] [ Show status ]

Claim boundary: Runtime readiness is not executor dispatch, session attachment, implementation, verification, review, CI, or merge evidence.
```

What gets better for the team:

- Product delivery loops show the full lane without implying code was written
  or deployed.
- Coding-agent choice can be shown as a practical readiness card instead of a
  vague handoff sentence.
- The wrapper has clear disabled states before implementation or runtime
  evidence exists.

### Workflow Operations Cards

```text
# research-ops

operator
I need a weekly leadership brief from support tickets, competitor news, and release risks

Hermes Agent  BOT
[omh] research-department - I can organize this into a research department flow.

I will prepare Scout, Analyst, and Briefer lanes: source inbox, synthesis
questions, briefing format, cadence, knowledge-store readiness, and delivery
policy. Source retrieval, synthesis, verification, storage, and delivery stay
unobserved until recorded.

[ Prepare research flow ] [ Start research ] [ Prepare brief ] [ Show status ]

Claim boundary: Research department preparation is not source retrieval, synthesis, verification, storage, or delivery evidence.
```

```text
# file-package

operator
첨부한 엑셀을 월간 보고서 PDF랑 PPT로 만들 수 있게 정리해줘

Hermes Agent  BOT
[omh] materials-package - I can prepare the material package without pretending files exist.

I will prepare the material package: source files, target formats, extraction
needs, formulas or layout risks, export checklist, render QA, approval, and
delivery steps. Binary files, uploads, render checks, and attachments remain
observed-only.

[ Prepare package ] [ Prepare deliverable ] [ Show status ]

Claim boundary: A material package is not binary export, render QA, upload, attachment, approval, or delivery evidence.
```

```text
# github-events

operator
GitHub issue 들어온 걸 PR 만들 수 있게 정리해줘

Hermes Agent  BOT
[omh] github-event-ops - I can prepare this GitHub event without claiming webhook work happened.

I will prepare the GitHub event card: event type, issue or PR context, triage
labels, review path, CI questions, docs-sync needs, and follow-up handoff.
Webhook receipt, GitHub mutation, code changes, review, CI, and docs sync stay
observed-only.

[ Open event card ] [ Prepare review ] [ Prepare fix handoff ] disabled [ Show status ]

Claim boundary: A GitHub event card is not webhook receipt, GitHub mutation, code execution, review, CI, docs sync, or merge evidence.
```

```text
# github-issue-intake

operator
please file this as an issue: omh setup fails on Windows

Hermes Agent  BOT
[omh] github-issue-intake - I can prepare this GitHub issue without claiming anything was filed.

I will prepare the intake card: classification, a bounded interview of at most
three decision-changing questions, duplicate search status, a direction check
with observed evidence versus inference, and the scoped issue package. Issue
creation runs only after explicit confirmation through an authorized connector.
A maintainer transition needs authenticated wrapper actor/evidence identity.
Only the checked-in issue form can build a connector-authorizable request; an
arbitrary title, body, or label set stays prepared-only. The idempotency-keyed
request is complete only in the transient connector handoff, whose dispatch is
consumed once; the external connector enforces the key and persisted state
stores metadata, digests, and refs. Only bound read-back counts as observed
evidence.

[ Open intake card ] [ Show direction check ] [ Confirm issue creation ] disabled [ Show status ]

Claim boundary: A prepared issue package is not issue creation, GitHub mutation, label application, coding, PR, merge, or deployment evidence.
```

What gets better for the team:

- Research department, material packaging, and GitHub event requests no longer
  read like generic workflow acknowledgements.
- File and GitHub cards keep generated files, uploads, mutation, review, CI,
  docs sync, and merge separate from preparation.
- Operators can show users a concrete next action without pretending the
  external system already ran.

### Operations Support Cards

These cards make the hidden operating layer visible without asking the user to
read JSON or approve shell commands.

```text
# memory-curation

operator
Hermes가 기억하고 있는 프로젝트 맥락이 오래된 것 같아 정리해줘

Hermes Agent  BOT
[omh] memory-sync - I can review memory and context before anything is changed.

I will prepare a memory curation review: stale facts, duplicate notes,
conflicting context, source scope, target/thread ownership, and
approve/reject/update choices. Memory files, skill notes, and recalled context
stay unchanged until an approved write is observed.

[ Review memory ] [ Show memory status ] [ Show status ]

Claim boundary: Memory review is not Hermes internal memory, MEMORY.md, USER.md, skill-file modification, or approved write evidence.
```

```text
# agent-board

operator
우리 팀 Hermes agent 여러 명이 같이 일할 때 역할과 보드를 잡아줘

Hermes Agent  BOT
[omh] agent-board - I can prepare a board for multiple Hermes agents.

I will prepare the agent board: targets, roles, tasks, handoff lanes, heartbeat
expectations, blocker states, and completion rules. Other agents accepting,
working, heartbeat-ing, or completing work remains unobserved until
target-specific evidence exists.

[ Open agent board ] [ Refresh status ] [ Show status ]

Claim boundary: An agent board card is not proof that another Hermes target accepted, worked, heartbeat-ed, or completed.
```

```text
# toolbelt-and-observability

operator
show token cost latency run history and supplied Grafana service-quality gaps for this automation loop

Hermes Agent  BOT
[omh] ops-observability-card - I can prepare observability without inventing provider truth.

I will prepare a wrapper-safe observability card and service-quality board:
token, cost, latency, run history, queue, failure modes, supplied metric-provider
payloads, and evidence gaps. Local estimates and supplied exports stay separate
from provider billing, quota truth, live metric-provider access, SLO pass, incident
closure, remediation completion, performance proof, and workflow completion.

[ Open observability ] [ Refresh status ] [ Show status ]

Claim boundary: An ops observability card is not billing truth, provider quota truth, live metric-provider access, complete tracing, SLO pass, incident closure, remediation completion, performance proof, or workflow completion evidence.
```

What gets better for the operator:

- Scheduled ops, memory cleanup, multi-agent boards, gateway policy, voice
  requests, tool readiness, deliverables, and observability now get dedicated
  card kinds instead of generic acknowledgement copy.
- Wrappers can render the same primary action every time, then keep evidence
  gaps visible until a runtime record proves them.
- The user sees whether OMH is preparing a card, checking tools, reviewing
  memory, or opening an agent board without needing to know backend command
  names.

### Real-World QA Check

```text
# cloudy-qa

operator
쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?

Hermes Agent  BOT
[omh] ulw-qa - I can turn this into QA scenarios and observed checks.

I will prepare the QA lane: scenario list, expected behavior, cheap checks,
expensive checks, known gaps, and follow-up handoff options. No product
diagnosis, verification, fix, CI, or release-readiness claim is made until
matching observations exist.

[ Prepare QA workflow ] [ Prepare follow-up review ] [ Show status ]

Claim boundary: A QA workflow route is not observed scenario execution, verification, fix evidence, CI, or release readiness evidence.
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
[omh] ulw-interview - This needs a clarification workflow before planning.

I will ask one blocking question at a time in this thread - at most 6 rounds -
then hand off a clarified brief.

[ Answer clarification ] [ Cancel ]

Claim boundary: No plan or execution has started.
```

Hermes then runs the bounded interview. Each question carries a round header, and
the question itself stays in the user's language:

```text
Hermes Agent  BOT
라운드 1/6 · 명확도: 0% (0/3) · 확인 중: 목표

지금 온보딩에서 사람들이 가장 많이 막히는 지점이 어디예요?
```

What gets better for the team:

- Broad product language becomes deep interview before implementation.
- Hermes asks for the missing decision instead of sending vague work to a coding
  executor.
- Planning and handoff buttons stay behind the clarification gate.
- The round header makes the interview's length visible and bounded, so questioning
  cannot run on indefinitely.

### Release Evidence Review

```text
# release

maintainer
릴리즈 전에 README claim이 실제 코드와 맞는가, doctor/harness가 통과하는가 봐줘

Hermes Agent  BOT
[omh] code-review - I can review the claims before we call this done.

I will prepare a review lane: claims to inspect, evidence to verify, missing
tests, risk areas, and any follow-up fix handoff. Review preparation is not a
completed review, fix, CI result, or merge decision.

[ Prepare review ] [ Prepare fix handoff ] disabled [ Show status ]

Claim boundary: A review recommendation is not a completed review or fix evidence. It is not verification, CI, merge-readiness, or merge evidence.
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
| First reply guidance | `chat_response.state.workflow_explanation.recommended_reply`, `chat_response.state.workflow_explanation.primary_action_label`, `chat_response.state.workflow_explanation.primary_action_hint` |
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
| Coding steps not reached yet | `coding_briefing.pending_gaps[]` |
| Coding steps that stopped | `coding_briefing.blockers[]` (`id`, `kind`, `event`) |

Hermes Agent surfaces should render these fields natively and keep OMH focused
on the routing, handoff, status, and evidence contract.
