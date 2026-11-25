# Physical Device Readiness

Load this on-demand contract after the compact `physical-device-readiness` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The device is reached through a provider or connector the user has not adopted yet; use `omh-external-connector-readiness`.
- The tool that would control the device is missing; use `omh-toolbelt-readiness`.
- The user asks to run the command, move the hardware, or start the print now; use `omh-terminal` or `omh-apps`, which need observed operator approval before any execution claim.

## Examples

Good example:

- Prompt: physical-device-readiness check Snapmaker printer safety with camera gate, slicer dry-run, heat command approval, and emergency-stop evidence before printing.
- Expected behavior: Produce `prepare_physical_device_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: Heat and motion act within seconds; the card holds the emergency stop, camera gate, and approval wording first.

Bad example:

- Prompt: physical-device-readiness start the printer, heat the bed, flip relays, and claim the robot is safe without observed operator approval or device telemetry.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

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
- emergency_stop_and_rollback_plan/v1 with stop command, power/network isolation, recovery boundary, and abort condition, naming the stop that still works when the agent, host, and network are gone (a physical e-stop, switch, or power cut) and who is within reach of it; for any heater, whether firmware thermal-runaway protection is on and verified, and that heating never starts unattended without a camera or sensor gate
- device_trial_manifest/v1 only when real telemetry, camera capture id, dry-run output, command transcript, operator confirmation, or hardware observation is recorded
