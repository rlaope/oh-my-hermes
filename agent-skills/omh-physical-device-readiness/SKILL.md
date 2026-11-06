---
name: "omh-physical-device-readiness"
description: "[omh] Agent control of a robot, 3D printer, or IoT relay: gate robots, 3D printers, IoT relays, sensors, and lab hardware before trials; use external-connector-readiness for provider or connector adoption and toolbelt-readiness for missing control tools. Use when the user says: physical-device-readiness, physical device readiness, device safety readiness, physical device safety, hardware safety gate, 3d printer readiness, 3D printer safety, snapmaker printer safety."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: device-readiness
    role: operator
    quality_tier: workflow-surface-gated
---

# Physical Device Readiness

This is an OMH `physical-device-readiness` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`physical-device-readiness` exists because a robot, heater, or relay acts on the physical world, where a wrong command can hurt someone or damage property: it fixes the safety envelope, sensor and camera gates, dry runs, operator approval, and emergency stop before any trial, and turns the commands the agent must never run into a proposed deny list the user applies.

## Do Not Use When

- The device is reached through a provider or connector the user has not adopted yet; use `omh-external-connector-readiness`.
- The tool that would control the device is missing; use `omh-toolbelt-readiness`.
- The user asks to run the command, move the hardware, or start the print now; use `omh-terminal` or `omh-apps`, which need observed operator approval before any execution claim.

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



## When to Use

Use before preparing or adopting a workflow that could move, heat, print, actuate, unlock, or otherwise affect physical devices so safety envelope, sensor/camera gates, dry-run policy, operator approval, emergency stop, and observation requirements are explicit.

    Strong routing signals: `physical-device-readiness`, `physical device readiness`, `device safety readiness`, `physical device safety`, `hardware safety gate`, `3d printer readiness`, `3D printer safety`, `snapmaker printer safety`, `snapmaker readiness`, `moonraker klipper safety`, `camera-gated print start`, `camera gate`, `heat command approval`, `iot relay safety`, `sensor relay safety`, `robotics safety`, `robot control readiness`, `vla robot readiness`, `mushroom cultivation relay safety`, `raspberry pi relay safety`, `물리 장비 안전`, `하드웨어 안전`, `3d 프린터 안전`, `프린터 안전`, `로봇 제어 준비`, `iot 릴레이 안전`, `센서 릴레이 안전`

## Catalog Metadata

Category: `operations`
Phase: `device-readiness`
Quality tier: `workflow-surface-gated`
Reasoning demand: `light`

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
- operator_approval_policy/v1 with explicit human authority, confirmation moment, disallowed autonomous actions, and emergency contact or stop owner, plus a proposed `approvals.deny` glob list for the terminal commands that actuate the device: on Hermes a match blocks the command for the agent even under yolo; the user applies the list, OMH writes no host config, and a device driven through an MCP or HTTP tool rather than a terminal command stays outside it
- dry_run_and_simulation_policy/v1 for slicer/G-code dry-runs, command previews, mock relays, simulated robot paths, and no-hardware trial mode
- emergency_stop_and_rollback_plan/v1 with stop command, power/network isolation, recovery boundary, and abort condition
- device_trial_manifest/v1 only when real telemetry, camera capture id, dry-run output, command transcript, operator confirmation, or hardware observation is recorded

Safety rules:

- A physical device readiness card is not device discovery, network pairing, credential validation, slicer output, G-code safety, camera inspection, sensor reading, relay actuation, robot movement, heat command, print start, emergency stop test, or successful hardware trial evidence unless observed device-trial evidence records it.
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
