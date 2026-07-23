---
name: physical-device-readiness
description: [omh] Hermes readiness workflow for robots, 3D printers, IoT relays, sensors, and lab hardware before hardware trials.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: device-readiness
    role: operator
    quality_tier: workflow-surface-gated
---

# Physical Device Readiness

This is a Hermes-native `physical-device-readiness` workflow skill.

## Why This Exists

`physical-device-readiness` exists so Hermes users can ask for this workflow in chat and receive a structured, evidence-bounded OMH operating surface instead of ad hoc narration.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.

## Examples

Good example:

- Prompt: physical-device-readiness check Snapmaker printer safety with camera gate, slicer dry-run, heat command approval, and emergency-stop evidence before printing.
- Expected behavior: Produce `prepare_physical_device_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: physical-device-readiness start the printer, heat the bed, flip relays, and claim the robot is safe without observed operator approval or device telemetry.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Device scope, actuator and hazard classes, sensor/camera gates, operator approval, dry-run policy, emergency stop, and stop condition are explicit.
- Physical actions, heat commands, relay toggles, robot movement, print starts, camera inspections, and telemetry readings are marked observed, missing, risky, or not_observed.
- Route external APIs or provider setup to external-connector-readiness, terminal commands to command-operator, safety concerns to security-safety-review, visual/camera checks to visual-qa, and missing tools to toolbelt-readiness.
- Do not claim device movement, heat, print, relay, robot, camera, sensor, or emergency-stop success without observed device-trial evidence.

## Recovery Notes

- If the device, workspace, actuator, or authority is unclear, keep readiness blocked until the missing safety context is named.
- If the user asks to execute commands, move hardware, heat a bed/nozzle, flip a relay, or start a print, route to command-operator or connector-operator and require observed operator approval before any execution claim.
- If camera or telemetry evidence is required but unavailable, route to visual-qa or toolbelt-readiness and keep the physical device readiness card prepared_not_observed.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+30 more`) - schedules, status, health, and ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use before preparing or adopting a workflow that could move, heat, print, actuate, unlock, or otherwise affect physical devices so safety envelope, sensor/camera gates, dry-run policy, operator approval, emergency stop, and observation requirements are explicit.

    Strong routing signals: `physical-device-readiness`, `physical device readiness`, `device safety readiness`, `physical device safety`, `hardware safety gate`, `3d printer readiness`, `3D printer safety`, `snapmaker printer safety`, `snapmaker readiness`, `moonraker klipper safety`, `camera-gated print start`, `camera gate`, `heat command approval`, `iot relay safety`, `sensor relay safety`, `robotics safety`, `robot control readiness`, `vla robot readiness`, `mushroom cultivation relay safety`, `raspberry pi relay safety`, `물리 장비 안전`, `하드웨어 안전`, `3d 프린터 안전`, `프린터 안전`, `로봇 제어 준비`, `iot 릴레이 안전`, `센서 릴레이 안전`

## Catalog Metadata

Category: `operations`
Phase: `device-readiness`
Hermes role: `operator`
Quality tier: `workflow-surface-gated`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- physical_device_readiness_card/v1
- device_safety_envelope/v1
- hazard_and_actuator_inventory/v1
- sensor_camera_gate_policy/v1
- operator_approval_policy/v1
- dry_run_and_simulation_policy/v1
- emergency_stop_and_rollback_plan/v1
- device_trial_manifest/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- physical_device_readiness_card/v1 metadata-only wrapper card when prepared
- device_safety_envelope/v1 with device, workspace, hazards, actuator classes, human/property risk, owner, authority, and stop condition
- hazard_and_actuator_inventory/v1 separating motion, heat, pressure, electrical, relay, network, credential, and environmental risks
- sensor_camera_gate_policy/v1 for camera/OCR, sensor telemetry, stale readings, manual inspection, and blocked/no-camera fallback
- operator_approval_policy/v1 with explicit human authority, confirmation moment, disallowed autonomous actions, and emergency contact or stop owner
- dry_run_and_simulation_policy/v1 for slicer/G-code dry-runs, command previews, mock relays, simulated robot paths, and no-hardware trial mode
- emergency_stop_and_rollback_plan/v1 with stop command, power/network isolation, recovery boundary, and abort condition
- device_trial_manifest/v1 only when real telemetry, camera capture id, dry-run output, command transcript, operator confirmation, or hardware observation is recorded

Safety rules:

- A physical device readiness card is not device discovery, network pairing, credential validation, slicer output, G-code safety, camera inspection, sensor reading, relay actuation, robot movement, heat command, print start, emergency stop test, or successful hardware trial evidence unless observed device-trial evidence records it.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `physical-device-readiness`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill physical-device-readiness --harness physical-device-readiness --status started
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
