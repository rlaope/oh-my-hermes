---
name: "omh-app-debugging"
description: "[omh] Application code misbehaves: a wrong value, a flaky test, a lost update; reproduce it first, form competing hypotheses, discriminate them with the cheapest observation, and only then fix the demonstrated root cause. Use when the user says: app-debugging, app debugging, application debugging, root cause, root-cause, find the root cause, root cause analysis, flaky test."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: app-root-cause
    role: reviewer
    quality_tier: root-cause-evidence-gated
    related_skills: [omh-native-debugging, omh-build-failure-triage, omh-agent-debug, omh-verification-gate, systematic-debugging]
---

# App Debugging

Required: the wrong behaviour as observed, and the behaviour that was expected, the command, request, or test that shows it, and how often it shows it, language, framework, and what changed recently when known, logs, stack traces, or failing assertions already captured, observed reproduction and verification evidence for any root-cause or fix claim. Output: reproduction_record/v1, competing_hypotheses/v1 with at least three hypotheses on distinct axes, discriminating_observation_plan/v1, root_cause_record/v1, fix_handoff/v1 blocked until reproduction_record/v1 reads observed, observed_fix_verification/v1 when observed.

**Do Not Use When:** Hermes' bundled `systematic-debugging` skill is already loaded for this bug; follow its phases instead of loading this one too, unless the reproduction, the rival hypotheses, and the observation that separated them must be kept as a record.

## Why This Exists

`app-debugging` exists because a wrong result in application code had no owner: `omh-native-debugging` covers native binaries, `omh-build-failure-triage` covers red builds, and `omh-agent-debug` covers agent misbehaviour, so the most common debugging request dispatched straight to an execution lane that skipped the diagnosis.

## First Steps

- Ask for, or plan, the one command that shows the wrong behaviour, and record its observed output before naming a cause.
- Refuse to prepare a fix while the reproduction reads not_observed; plan the observation that would establish it instead.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when application code -- a Python, TypeScript, Go, or JVM service, library, or test -- behaves wrongly and the cause is unknown: a wrong value, an intermittent or order-dependent test, a race or lost update, or a bug that moves when observed. The work is a demonstrated root cause: an observed reproduction, competing hypotheses, the cheapest observation that separates them, and only then a fix.

    Strong routing signals: `app-debugging`, `app debugging`, `application debugging`, `root cause`, `root-cause`, `find the root cause`, `root cause analysis`, `flaky test`, `flaky tests`, `test is flaky`, `intermittent test failure`, `fails intermittently`, `fails one run in`, `passes locally but fails in ci`, `heisenbug`, `bug disappears`, `disappears when i add a print`, `race condition`, `lost update`, `update is lost`, `wrong return value`, `returns the wrong value`, `reproduce the bug`, `minimal reproduction`, `почини баг`, `найди баг`, `приложение падает с ошибкой`, `флаки тест`, `исправь баг`, `баг в коде`, `исправить баг`, `найди ошибку в коде`, `отладь`

## Catalog Metadata

Category: `verification`
Phase: `app-root-cause`
Hermes role: `reviewer`
Quality tier: `root-cause-evidence-gated`
Reasoning demand: `standard`

Quality bar:

- State the symptom and the expected behaviour separately from any suspected cause.
- Record the reproduction with its hit rate; an intermittent fault is reproduced when its rate over N runs is measured, not when it happened once.
- A reproduction counts for this bug only when its `symptom_match` shows the failure the user reported; a different failure near the same code is another bug, and this record stays not_observed.
- `minimised` is filled before `competing_hypotheses/v1`: an input, caller, config value, or step leaves the reproduction only when the loop rerun without it still shows the symptom (for an intermittent fault, the same rate at the same N), and the record lists what left and what stayed; `fix_handoff/v1` builds the regression test from what stayed.
- Load `references/hypothesis-and-race-method.md` for the hypothesis table, flaky-test tactics, and race patterns instead of improvising them.
- Pick the next observation by cost and by how many hypotheses its result eliminates, and record the eliminations.
- Keep reproduction, root cause, fix, and verification as separate observed states.
- Size the effort to the depth and name it: a quick survey of one area runs at medium; tracing one suspected cause across several systems runs at high (category `deep`); several causes that may interact run at xhigh (category `forensics`). Finished means the reported symptom's root cause is shown by an observation and the fix passes the same reproduction; be exhaustive in the hypothesis table and its eliminations, not in reading code no hypothesis touches.
- Count a fix as failed when an executed run of the same reproduction command still shows the original symptom or shows a new symptom the fix caused rather than unmasked; planned runs and other commands do not count. After the third failed fix, prepare no fourth; re-examine the architecture assumptions every fix shared, per the method reference, and offer the user the next step as a question.
- Before the fix handoff names a regression test, load `skill_view(name='omh-verification-gate', file_path='references/test-authoring.md')` for the seam, the shapes of tests that guard nothing, fakes only at system boundaries, and the no-correct-seam outcome.
- When Hermes' bundled `systematic-debugging` skill is loaded for the same bug, follow its phases and write this skill's records at each; a breakpoint read through `python-debugpy` or `node-inspect-debugger` is one discriminating observation. Load `references/debugging-skill-composition.md` for the mapping.

Handoff policy:

Keep the symptom statement, the hypothesis set, the discriminating observations, and the root-cause verdict in Hermes. Record every reproduction run, probe output, and fix verification only from executor or wrapper observed evidence.

Safety rules:

- No fix before an observed reproduction: `fix_handoff/v1` stays blocked while `reproduction_record/v1` reads not_observed, and a proposed change without one is a guess, not a fix.
- Do not claim a reproduction, a probe result, a root cause, or a passing fix from a prepared plan.
- Require at least three hypotheses on distinct axes before planning observations; one hypothesis makes every reading confirmatory.
- Never treat a symptom's disappearance as a root cause; a bug that stops after a print statement, a retry, or a sleep is an open timing fault.
- Do not execute tests, debuggers, or commands from OMH core; the executor runs them and the record takes only what it observed.
- Redact before recording: reproduction commands read credentials from environment variables by name, quoted output keeps only the lines that carry the signal with each secret replaced by `<redacted>`, and a capture too redacted to diagnose is reported as such, never recorded unredacted.

## Completion Checklist

- The reproduction names its command, observed output, expected output, and hit rate, and reads observed before any fix is prepared.
- At least three hypotheses on distinct axes were written before the first observation was chosen.
- Each observation records which hypotheses its result eliminated.
- The root cause cites the demonstrating observation and the observation that ruled out each rival.
- The fix handoff carries the reproduction as a regression test that fails before and passes after, or records `regression_seam: none_correct` with the reason, with the reproduction loop observed red before the fix and green after it.
- An observed search for the session's probe tag returns nothing, and every throwaway harness file is deleted or listed.

## Recovery Notes

- If the fault does not reproduce, make reproduction the first hypothesis and plan the loop, seed, or ordering that would establish it; when no test reaches the fault, choose a loop from the method reference's loop table; if none can be built, the record stays not_observed with each attempt and what stopped it, and the request to the user is for an environment, a redacted capture, or permission for tagged temporary instrumentation.
- If every hypothesis is eliminated, record that, widen the axes, and keep root cause unclaimed rather than promoting the last survivor.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill app-debugging --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
