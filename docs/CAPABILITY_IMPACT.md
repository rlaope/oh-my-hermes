# Capability Impact

OMH should improve what Hermes does after setup, not merely add more files or
commands. The impact contract therefore answers six separate questions:

1. Did OMH select the right workflow?
2. Does the selected workflow carry useful quality and safety guidance?
3. Did the Hermes host actually load the native OMH tools and hooks?
4. Are optional external providers available for the requested work?
5. Was the produced artifact checked at the surface where users consume it?
6. Did OMH produce a better result than a comparison setup?

Run the local report with:

```sh
omh capabilities impact
omh capabilities impact --json
```

## Current Evidence

The report deliberately has no aggregate score. A single percentage would make
strong local routing evidence look interchangeable with an unavailable video
provider or an unrun comparative benchmark.

| Dimension | Current status | What the status means |
| --- | --- | --- |
| Route selection | `passing_local_contract` | Fixed precision, common-request coverage, and representative cases all pass as in-repo contracts; representative cases remain implementation smoke checks, not independent outcome evidence. |
| Guidance depth | `partially_proven` | Skill quality bars and evidence boundaries are inspectable; better task outcomes still need paired evaluation. |
| Native execution availability | `requires_host_observation` | Tool and hook registration exists, but only host load and invocation records prove availability in a real Hermes session. |
| Provider execution availability | `requires_provider_observation` | Browser, connector, image, and video providers vary by installation. |
| Artifact verification | `partially_proven` | OMH can request the right served-surface check; the check result must still be observed. |
| Comparative outcome quality | `requires_external_evaluator` | “Better than another setup” remains unproven until blinded paired tasks are scored externally. |

The deterministic report currently evaluates three route sets:

- 144 fixed routing boundaries: 47 negative controls and 97 expected
  interventions, including over-route and missed-intervention checks
- 90 common Hermes requests spanning 10 popular plugin-style families
- 22 representative English and Korean requests, including focused intents and
  collision-prone near neighbors

The focused cases lock distinctions that broad keyword matching commonly gets
wrong: TDD versus an article about testing, literature review versus project
memory, screenshot layout QA versus OCR, deployment versus production audit,
session recovery versus handoff status, image editing versus image summary, and
video generation versus video summarization.

## Focused Skill Selection

OMH does not treat the installed skill count as a quality score. The router
should select the smallest useful workflow set and keep unrelated guidance out
of context. This direction matches the SkillsBench finding that curated skills
can improve results while small two- or three-skill bundles outperform large
comprehensive bundles in the reported aggregate analysis.

References:

- [SkillsBench paper](https://arxiv.org/html/2602.12670v4)
- [Hermes Agent hook documentation](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md)
- [Hermes Agent releases](https://github.com/NousResearch/hermes-agent/releases)

## Served-Surface Verification

The OMH plugin registers a narrow `pre_verify` hook only when the Hermes host
advertises that lifecycle. Older hosts that do not expose `pre_verify` skip the
hook without warnings while keeping the rest of the OMH plugin available.
After edited code reaches Hermes verification, the hook requests one additional
check only for surfaces where ordinary code tests are insufficient:

- plugin manifest changes require a real plugin load and registration smoke
- frontend changes require rendered desktop and mobile checks
- dependency or build metadata changes require installation or import smoke
- CI workflow changes require a syntax check or the workflow's local command

The hook is one-shot, fail-open, and metadata-only. It does not store raw
changed paths or final responses, and its message is guidance rather than proof
that verification, review, CI, or merge readiness occurred.

## Growth Gate

The next product-quality claim should come from paired outcome evaluation, not
from adding more catalog entries. A representative benchmark should run the
same Hermes tasks with and without OMH, blind the outputs, and score correctness,
completeness, evidence use, artifact quality, recovery behavior, and wasted
tool/context cost. Until that evaluator exists, OMH can prove routing and local
contracts, but it should not claim overall superiority.
