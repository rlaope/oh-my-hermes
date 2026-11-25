# Mobile Release

Load this on-demand contract after the compact `mobile-release` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is a versioned release of a service or library -- what goes in, the tag, a canary, the rollback command; use `omh-release-cut`.
- A web or backend deploy is already out and the ask is watching its health; use `omh-deploy-and-monitor`.
- The ask is a readiness audit across observability, security, and operations before launch; use `omh-production-audit`.
- The app crashes or misbehaves and the ask is finding the cause in the code; use `omh-app-debugging`.

## Examples

Good example:

- Prompt: we are shipping 3.2 to the app store and google play next week
- Expected behavior: Check the signing assets' expiry, compare the privacy manifest and data safety form against the shipped SDKs, run the TestFlight and Play closed-track beta, then roll out in phases with crash-free and ANR halt thresholds and the 3.2.1 build number reserved for a hotfix.
- Why: A store build cannot be pulled back, so the halt and the replacement have to exist before the first user gets it.

Bad example:

- Prompt: just release to 100% and roll back if it crashes
- Expected behavior: Refuse the full release: a store build cannot be rolled back; stage it behind halt thresholds and reserve the hotfix build first.
- Why: Users keep the crashing build until a new one is reviewed and installed.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the platforms, the app's bundle or package id, and the version and build number going out
- how signing is set up today: certificates, provisioning profiles, the keystore or upload key, and who holds them
- the SDKs the build ships, for the privacy manifest and the data safety form
- the beta channel and testers, and what they must verify before the rollout
- the crash-free and ANR figures the rollout will be judged on, observed from the consoles or crash reporting

Expected outputs:

- signing_plan/v1
- privacy_declaration_check/v1
- beta_channel_plan/v1
- staged_rollout_plan/v1
- hotfix_plan/v1

Artifact expectations:

- signing_plan/v1 names each certificate, provisioning profile, keystore, and upload key with its expiry and where it is held, and never contains the secret itself
- privacy_declaration_check/v1 compares the iOS privacy manifest's required-reason APIs and the Play data safety form against every SDK the build ships, and names each mismatch
- beta_channel_plan/v1 names the TestFlight group or Play testing track, whether it needs beta review, the testers, and the checks that must pass before the rollout
- staged_rollout_plan/v1 lists the rollout steps (App Store phased release or Play staged percentages) with the crash-free and ANR thresholds that halt each step
- hotfix_plan/v1 halts the bad rollout, names the higher build number that replaces it, whether to request an expedited review, and any server-side flag that contains the damage first
