---
name: frontend
description: [omh] Hermes frontend workflow: prepare design-system-driven web UI creation, redesign, polish, accessibility, performance, and visual QA handoffs.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, materials]
    category: materials
    phase: frontend-design
    role: operator
    quality_tier: frontend-design-gated
---

# Frontend

This is a Hermes-native `frontend` workflow skill.

## Why This Exists

`frontend` gives OMH a first-class web UI creation and polishing workflow so Hermes can prepare high-quality layout, design-system, accessibility, performance, and visual-QA handoffs without becoming the hidden coding or browser runtime.

## Do Not Use When

- The user needs a broad premium-quality gate across web, deck, PDF, poster, or publishing outputs; use `design-quality-gate`.
- The user only needs a file, deck, PDF, spreadsheet, HWP, or attachment package; use `materials-package` or `deliverable-package`.
- The user only needs an image card or infographic prompt; use `img-summary`.
- The user asks to mark a UI as visually passed without fresh rendered evidence; use `visual-qa` and keep PASS blocked until observed.

## Examples

Good example:

- Prompt: frontend 이 대시보드가 AI 티 안 나게 레이아웃과 디자인 시스템을 잡아줘.
- Expected behavior: Prepare frontend_design_brief/v1, design_system_contract/v1, route/state matrix, implementation handoff, and visual_qa_required/v1.
- Why: The request is about web UI design, layout quality, and anti-generic frontend polish.

Bad example:

- Prompt: frontend 코드도 안 봤지만 Lighthouse랑 시각 QA 통과했다고 해줘.
- Expected behavior: Mark browser, performance, accessibility, and visual QA as not_observed and request the smallest observed evidence path.
- Why: A frontend brief is not implementation, browser, performance, or visual QA evidence.

## Completion Checklist

- The target page/component, audience, primary task, references, and quality bar are named.
- Greenfield work includes frontend_initial_generation_contract/v1 before implementation handoff.
- The design_system_contract/v1 covers typography, spacing, palette, components, layout, motion, and responsive rules.
- The frontend_route_state_matrix/v1 covers pages, 375/768/1280-style breakpoints, empty/loading/error, interaction, and CJK/locale risks.
- The frontend_component_state_inventory/v1 covers reusable primitives and their default/hover/focus/active/disabled/loading/empty/error states.
- The handoff names the executor/runtime owner and keeps code, browser, Lighthouse, accessibility, deployment, and visual QA evidence observed-only.
- The next action is prepare_frontend_handoff, route to visual-qa, or report the missing evidence blocker.

## Recovery Notes

- If the target surface is unclear, prepare the brief with a route/component gap instead of inventing pages.
- If no visual reference exists, set a domain-fit quality bar and request references only when the decision changes layout or brand direction.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Materials and visual summaries** (`design-quality-gate`, `frontend`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`) - web, visual QA, files, image cards, and packages.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit/security-safety-review; verify->verification-gate; code->codegraph-refresh/codebase-onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should shape or improve a web/frontend surface before implementation: layout, design system, responsive states, accessibility, performance, motion, and anti-generic visual quality.

    Strong routing signals: `frontend`, `front-end`, `front end`, `frontend skill`, `web ui`, `ui ux`, `ui/ux`, `landing page`, `web app layout`, `responsive layout`, `responsive design`, `design system`, `component polish`, `layout polish`, `visual polish`, `styling`, `animation`, `motion design`, `accessibility`, `wcag`, `lighthouse`, `core web vitals`, `make it beautiful`, `make it premium`, `make it less ai`, `ai-looking ui`, `ai slop ui`, `generic ui`, `broken layout`, `layout broken`, `frontend qa`, `frontend layout`, `프론트엔드`, `웹 ui`, `웹 화면`, `랜딩페이지`, `레이아웃`, `레이아웃 깨짐`, `깨짐`, `디자인 자연스럽게`, `자연스러운 디자인`, `화려하게`, `고급스럽게`, `ai 티`, `ai틱`, `ai 틱`, `반응형`, `접근성`

## Catalog Metadata

Category: `materials`
Phase: `frontend-design`
Hermes role: `operator`
Quality tier: `frontend-design-gated`

Quality bar:

- Name the product goal, audience, target surfaces, routes, states, and visual quality bar.
- Use references and domain fit to avoid generic AI-looking frontend output.
- Prepare a concrete design-system contract before implementation handoff.
- For first-time UI creation, name the initial generation branch, reference direction, reusable primitives, state coverage, and required visual QA path.
- Cover responsive layout, empty/loading/error states, hover/focus/active states, CJK text, accessibility, and performance expectations.
- Prefer native UI controls, stable dimensions, and realistic content over decorative cards, blobs, and placeholder-heavy screens.
- Keep implementation, browser verification, accessibility/performance checks, visual QA, and deployment as observed-only evidence.

Handoff policy:

Keep product framing, reference selection, design-system contract, viewport/state matrix, and implementation brief in Hermes. Record code changes, browser screenshots, Lighthouse/Core Web Vitals, accessibility scans, and visual QA only from executor or wrapper observed evidence.

Required inputs:

- target app, page, route, or component
- audience and primary user task
- existing design system or missing-system gap
- style references or quality bar
- initial generation mode or redesign mode
- DESIGN.md or design-system source of truth when available
- framework/stack when known
- routes, states, breakpoints, and locale/CJK risks
- accessibility and performance constraints
- observed browser evidence for completion claims

Expected outputs:

- frontend_design_brief/v1
- frontend_initial_generation_contract/v1 when greenfield
- design_system_contract/v1
- design_reference_selection/v1
- reference_packet/v1 when supplied
- frontend_route_state_matrix/v1
- frontend_component_state_inventory/v1
- frontend_implementation_handoff/v1
- accessibility_performance_expectations/v1
- visual_qa_required/v1
- observed_browser_evidence/v1 when observed

Artifact expectations:

- frontend_design_brief/v1 when prepared
- frontend_initial_generation_contract/v1 declares DESIGN.md/design-system work, reference lane, token extraction, reusable primitives, and visual QA path before new UI code
- design_system_contract/v1 with layout, spacing, typography, color, component, motion, and responsive rules
- design_reference_selection/v1 names supplied references or the domain-fit style direction and explicitly avoids copying third-party logos, assets, or brand copy
- frontend_route_state_matrix/v1 with pages, states, viewports, CJK/locale, empty/loading/error, and interaction states
- frontend_component_state_inventory/v1 with default, hover, focus, active, disabled, loading, empty, and error states for reusable primitives
- frontend_implementation_handoff/v1 for the selected executor/runtime
- browser screenshots, accessibility reports, Lighthouse/Core Web Vitals, and visual QA only when observed

Safety rules:

- Do not claim implementation, browser verification, deployment, Lighthouse, accessibility pass, or visual QA from a prepared frontend brief.
- Reject generic AI-looking UI: one-note palettes, weak hierarchy, cramped cards, ungrounded gradients, decorative filler, and placeholder-heavy copy.
- Require a design-system contract before broad visual changes.
- For greenfield UI, require an initial generation contract before implementation handoff so the first generated screen has tokens, references, primitives, states, and QA expectations.
- Require fresh rendered evidence after the last UI edit before PASS.
- For Korean/CJK text, clipped glyphs, awkward line breaks, orphan particles, tiny copy, and overflow block visual QA.
- Do not call external design, image, browser, LLM, or network services from OMH core.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `frontend`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill frontend --harness frontend --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
