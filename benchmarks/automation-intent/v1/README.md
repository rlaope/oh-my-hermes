# Automation intent: does a request become the right automation?

`benchmarks/automation-intent/v1` asks one question:

> Given a plain-language request and the state around it, does the arm prepare
> the automation the request asks for (schedule, target, delivery, filters,
> silence), or correctly ask, decline, or edit the job that already exists?

It is the baseline for the `automation-blueprint` skill text
(`skills/omh-automation-blueprint/`). Later changes to that text are measured
against it, so it exists before them.

Audience: operator and maintainer. Nothing here is a user command, and nothing
here runs in CI or by default.

## What one scenario is

`corpus/tuning.json` and `corpus/held-out.json` each hold
`omh_scenario_corpus/v1` scenarios:

| Field | What it is |
| --- | --- |
| `id`, `category` | identity, for the report; never shown to the arm |
| `request` | the person's words |
| `prior_state` | existing jobs (`automations`), earlier turns, the person's timezone |
| `expect` | the outcome, and for an automation the projection it must match |
| `why` | why the expectation is what it is; for the reader, never shown to the arm |

Categories:

| Category | What it checks |
| --- | --- |
| `schedule` | cron and interval forms, weekday ranges, a timezone the request names over the profile's |
| `github` | the repository a watch reads, and the item kind and state it narrows to |
| `slack` | Slack as the source (a channel watch) versus Slack as the destination |
| `filters` | labels, authors, branches, paths, severities: every stated one kept, none invented |
| `results-to` | where results go: a named channel, two destinations, email, or this chat by default |
| `ask` | a value the job needs is missing, so the right move is one clarifying question |
| `no-automation` | a one-off send, a question about cron, a listing, a recurring payment, a delivery check |
| `edit` | the existing job changes (time, filter, state, destination) and no second job appears |

The scenario counts per split are pinned in `manifest.json` and checked by
`bench.py validate`.

## The decision an arm records

An arm writes one JSON object (the contract is `DECISION_CONTRACT` in
`src/quality/automation_intent_grading.py`):

```json
{"outcome": "prepared_automation",
 "automation": {"schedule": "0 9 * * 1-5", "timezone": "Asia/Seoul",
                "deliver": ["slack:#eng-review"],
                "target": {"kind": "github_repo", "ref": "rlaope/oh-my-hermes"},
                "filters": {"event_types": ["pull_requests"], "states": ["open"]},
                "silence": "report_each_run"},
 "artifact": {"schema_version": "prepared_native_blueprint/v1", "...": "..."}}
```

`schedule` and `deliver` are the `cronjob_manage` arguments of the same names.
`target` and `filters` are the job's scope, which a `prepared_native_blueprint/v1`
keeps only in its prompt text; the projection states them so they can be graded
without parsing prose. `artifact` is optional: the prepared
`prepared_native_blueprint/v1` or `hermes_recurring_intent/v1` record itself.

## How a decision is graded

`grade_automation_intent` is a pure function from a scenario and one
observation to a list of failures. No failure is a pass. No model judges.

| Check | Passes when |
| --- | --- |
| `outcome` | it equals the expected outcome; nothing else is checked when it does not |
| `automation.schedule` | it normalizes to one of the accepted forms (`0 9 * * MON-FRI` = `0 9 * * 1-5`; `every 2 hours` = `every 120m`; cron and interval forms are never converted into each other, so a scenario lists both when both are right) |
| `automation.timezone` | it is one of the accepted zones, when the scenario names any (`UTC` aliases, and `KST` or `JST` for the zone they abbreviate, are accepted) |
| `automation.deliver` | the set of targets equals the expected set (Hermes' comma-joined string is read too; `origin` is this chat; `slack:#eng` and `slack:eng` are one target) |
| `automation.target` | kind and ref match one accepted target (a feed may be accepted as `rss_feed` or `url`); a GitHub ref may be a URL or end in `.git`, a channel ref may drop its `#`, a URL ref its trailing `/` |
| `automation.filters.<key>` | each expected key has the same values (case-folded; a path's trailing `/`, an author's `@` and `[bot]` dropped), and no key the request did not state is present, except a scenario's `optional_filters`, which an arm may state with values from the listed ones or leave out |
| `automation.silence`, `automation.state`, `automation.job_id` | they match, where the scenario names them; an edit that names no state change may leave `state` out but must not move it from the job's prior state |
| `asks_about` | a clarifying question asks about one or more of the topics the request leaves open (`clarify_about`), and about nothing else |
| `automation` / `artifact` absent | an ask or no-automation outcome prepared nothing |
| `artifact.*` | an attached record agrees with the projection (schedule; delivery platforms, and every channel the record names; silence), is `prepared` or `not_observed`, and a recurring intent is still `paused` |

## Two splits, kept apart

The held-out split is never used to tune skill text, prompts, or the grader.
That is enforced by structure and tested by `tests/test_scenario_suites.py`:

- The splits are two files. Every command reads `tuning` unless
  `--split held-out` is named, and a held-out run covers the whole split
  (`--scenario` is refused there).
- They share no id and no request text, every category appears in both, and the
  held-out split holds between a fifth and three tenths of the suite.
- A held-out report carries totals only. A held-out category holds a scenario
  or two, so it carries no per-category rate, and it never names which
  scenario failed or why: a held-out run cannot be read back into skill text
  one scenario at a time.
- An observations file records its split, and grading it against the other
  split is refused. A held-out file must hold an observation of every
  held-out scenario and grade at least three quarters of them (not excluded),
  or it is refused: totals over a file padded with infrastructure failures
  would name one scenario's verdict. The floor is pinned in `manifest.json`.
- No held-out id or request appears in any skill, agent-skill, skill producer,
  routing or catalog source.

None of this is secrecy. The corpus, held-out expectations included, is public
in this repository, and the observations file of a held-out run holds the
arm's decisions. Keeping the held-out split out of tuning is the operator's
discipline: do not read either while editing skill text; grade the run and
read the report.

What the held-out split can and cannot show: its scenarios are near siblings
of tuning ones (the same kinds of request with different repositories,
channels and jobs), so it measures near transfer, not generalisation to new
kinds of request. It is also small: a perfect score on a split this size has a
Wilson 95% interval whose lower bound is only around 60-70%, so a held-out number is a
check against over-fitting the tuning split, not a precise rate.

## Observation classes and the report

Each observation is `observed` (graded) or an infrastructure failure:
`arm_did_not_run`, `timeout`, `transport_error`. A scenario with no
observation is `not_observed`. All four are excluded from the denominator by
name and counted in `excluded_counts`; none is a pass or a failure. An
infrastructure failure keeps a short `reason` (the child's terminal status and
why no decision was read, at most 200 characters, never the prompt or the
child's output) so an outage can be diagnosed.

`bench.py grade` writes `omh_scenario_suite_report/v1`. Every rate is
`omh_reported_rate/v1` (`numerator_of: ["passed"]`, `denominator_of: "graded
<split> scenarios"`, the excluded classes) with a Wilson 95% interval beside
it. An empty denominator reports `percent: null`, basis `no_observations`, and
no interval. The `headline` names the arm, corpus, split, corpus digest,
selection rule, and the observations file and its digest; with nothing graded
its status is `prepared_not_observed`.

A tuning report also splits its scenarios into two groups (`per_group`):

| Group | Scenarios | What the gap between arms means |
| --- | --- | --- |
| `request_derivable` | any arm can derive the expectation from the request, its prior state and the decision contract | how well each arm follows the request and the contract |
| `skill_rule` | the expectation rests on a rule the request does not carry and only the skill text states, named by the scenario's `skill_rule` (here `spend_gate`: a recurring payment, renewal, transfer, top-up or purchase gets no automation) | what the skill text teaches; the `bare` arm is never told the rule |

The `skill_rule` group is small by design: a few scenarios in each split, with
the counts pinned in `manifest.json` (`skill_rule_scenarios`) and at least two
in every split. It can show whether inlining the skill text moves an arm on
the rule that text states, as a gap between the `skill-text` and `bare` arms
on the same scenarios. It cannot give a precise rate (its Wilson interval is
wide), and on the held-out split it is never reported on its own, because a
held-out report carries totals only.

## Arms

| Arm kind | What answers | How |
| --- | --- | --- |
| `skill-text` | a model through the Hermes-native child boundary, given the suite instructions, the decision contract, the scenario (request and prior state), and the skill files `manifest.json` names inlined in its prompt, which state the `skill_rule` rules | `bench.py run --arm-kind skill-text` |
| `bare` | the same model and prompt without the skill text, so without the `skill_rule` rules | `bench.py run --arm-kind bare` |
| external | any tool the operator likes | an `omh_scenario_observations/v1` file graded offline |

The live arms measure the named skill text when it is in the prompt. They do
not measure OMH's router choosing the skill, the plugin's hooks, or Hermes
loading the skill itself: the child runs `--safe-mode --ignore-user-config
--ignore-rules --toolsets file`, with no OMH plugin and no skills toolset.

## Safety and claim boundary

- Offline by default. `validate` and `grade` spend nothing and start nothing.
- `run` spends money and refuses without `--allow-paid-live`,
  `--max-paid-calls` (at least the number of scenarios it will run) and
  `--confirm`. It runs one scenario at a time through `omh coding hermes-child
  dispatch --confirm-dispatch`: the prompt goes on the child's stdin, never on
  argv, and is not persisted. The child writes its decision to
  `.omh-scenario-decision.json` in a fresh workspace outside the checkout (a
  `--workspace` inside it is refused, so no AGENTS.md or CLAUDE.md reaches
  the arm), under a run id unique to the invocation; only the keys of the
  decision contract are kept.
- The arm is told to record a decision, not to perform it. With the `file`
  toolset only, it has no cron, gateway, or forge tool to perform one with.
- `--output` must not exist, and it is rewritten after every scenario, so an
  interrupted run keeps what it finished.
- The dispatcher enforces `--timeout` on its own child. If it overruns that by
  the harness's backstop, it gets SIGTERM, which it relays to its Hermes child's
  process group, and SIGKILL only after a grace period, so no Hermes process is
  left behind without a parent.
- A rate describes one arm on one split of this corpus at this revision. It is
  a structural grade of a prepared decision, not evidence that a job was
  created, ran, or delivered.

## Commands

```bash
# Offline: check both splits, their isolation and the manifest pins.
uv run python benchmarks/automation-intent/v1/bench.py validate

# Offline: grade the shipped fixture. Its numbers measure nothing; do not quote them.
uv run python benchmarks/automation-intent/v1/bench.py grade --text \
  --observations benchmarks/automation-intent/v1/fixtures/recorded-observations.json

# Paid: answer the tuning split with a live arm, then grade it.
uv run python benchmarks/automation-intent/v1/bench.py run \
  --arm my-model-skill --arm-kind skill-text \
  --model <alias> --provider <alias> --reasoning <alias> \
  --output benchmarks/automation-intent/v1/artifacts/tuning-skill.json \
  --allow-paid-live --max-paid-calls <scenarios> --confirm
uv run python benchmarks/automation-intent/v1/bench.py grade \
  --observations benchmarks/automation-intent/v1/artifacts/tuning-skill.json
```

`artifacts/` is a scratch directory and is not committed. A run whose number
will be quoted is committed under `results/` in the lane (its observations file
and its graded report, side by side), and graded from there, so the report's
`headline.artifact` names it by its repository-relative path. A report graded
from a file outside the checkout names it only as
`outside-repository:<file name>`, never by an absolute local path.

`--scenario <id>` (repeatable) runs a subset of the tuning split. `--split
held-out` runs or grades the whole held-out split; name it only for a
measurement, never while tuning.

## Files

| Path | Role |
| --- | --- |
| `corpus/tuning.json`, `corpus/held-out.json` | the two splits |
| `manifest.json` | split digests and counts, arms and skill files, execution policy |
| `fixtures/recorded-observations.json` | hand-written observations exercising every grading path |
| `bench.py` | `validate`, `grade`, `run`, through the shared `benchmarks/scenario_suite_bench.py` |
| `src/quality/automation_intent_grading.py` | scenario schema and grader |
| `src/quality/scenario_suite.py` | splits, observation classes, report, prompt, child argv |

Tests: `tests/test_scenario_suite_graders.py`, `tests/test_scenario_suites.py`.

## Latest measured status

`prepared_not_observed`. No live arm has been run, and there is no headline
number. Running one is an operator decision, because it spends money.
