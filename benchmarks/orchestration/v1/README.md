# Orchestration: does the parent hand coding to the named owner?

`benchmarks/orchestration/v1` asks one question:

> Given a request, the repositories and coding-owner choice around it, and the
> evidence already observed, does the parent hand coding to the owner the
> person named (and only then), target the right repository, cite only links
> the evidence returned, and keep the reply within its word budget?

It is the baseline for the skill text that governs hand-off: `dag-ulw`
(`skills/dag-ulw/SKILL.md`, "Coding nodes go to an external coding CLI only
when the person named that owner") and the shared rail
(`skills/omh-routing/references/skill-common-rail.md`). Later changes to that
text are measured against it, so it exists before them.

Audience: operator and maintainer. Nothing here is a user command, and nothing
here runs in CI or by default.

## What one scenario is

`corpus/tuning.json` and `corpus/held-out.json` each hold
`omh_scenario_corpus/v1` scenarios:

| Field | What it is |
| --- | --- |
| `id`, `category` | identity, for the report; never shown to the arm |
| `request` | the person's words |
| `prior_state` | `repositories` (slug and local path), `current_repository`, earlier turns, and `coding_owner_choice` (`owner`, `made_in`: `this_request` or `earlier_request`, `age_hours`), the corpus's record of when an owner was named; the arm never sees that record, only the request and the turns |
| `evidence` | what the parent already observed: each item's source, summary, and the links its tool actually returned |
| `expect` | `handoff` (`required` or `forbidden`), the owner and repository of a required one, `parent_may_edit` for a forbidden one, `word_budget` (shown to the arm as `reply_word_budget`), and links the reply `must_cite` |
| `why` | why the expectation is what it is; for the reader, never shown to the arm |

Categories:

| Category | What it checks |
| --- | --- |
| `handoff` | the person named an owner in this request: the coding goes to that owner, and the parent edits nothing |
| `no-handoff` | nobody chose an owner (the default Hermes lane may edit), the choice was made in an earlier request, the tools are only the subject of research, or the request is a question, status read or scoped review |
| `repository` | the hand-off targets the repository the request is about, named by slug, path or in words, against a different current repository |
| `links` | the reply cites only observed links: no guessed PR, no CI run nobody fetched, no URL from memory after a failed lookup |
| `budget` | the reply stays within the budget the request or scenario sets |

Every scenario is graded on all of its checks, not only its category's. The
scenario counts per split are pinned in `manifest.json` and checked by
`bench.py validate`.

## The decision an arm records

```json
{"handoffs": [{"owner": "codex", "repository": "rlaope/oh-my-hermes", "summary": "fix the flaky test"}],
 "parent_edits": [],
 "reply": "Handed the flaky timeout test to Codex."}
```

## How a decision is graded

`grade_orchestration` is a pure function from a scenario and one observation
to a list of failures. No failure is a pass. No model judges.

| Check | Fails when |
| --- | --- |
| `handoff` | a required hand-off is missing |
| `handoff.owner` | a hand-off names another owner (`Claude Code`, `claude_code`, `claude` and `claude-code` are one owner) |
| `handoff.repository` | a hand-off targets another repository; the expected one may be given by slug, by path, or as a GitHub URL |
| `parent_edits (parent coded instead of handing off)` | the parent edited files when the work was the named owner's |
| `handoff (not allowed)` | anything was handed off where nothing should be |
| `parent_edits (not allowed)` | the parent edited files where the scenario allows none |
| `reply.links (not in observed evidence)` | the reply holds a link (with a scheme, or a bare host such as `example.com/x`) the evidence did not return |
| `reply.must_cite` | an observed link the person asked for is missing |
| `reply.word_budget` | the reply has more whitespace-separated words than the budget |
| `handoffs`, `parent_edits`, `reply` | the decision is malformed (graded as a failure, never raised) |

Links are read by splitting the reply on whitespace after replacing the
characters that wrap a link in prose or markdown (brackets of every kind,
quotes, backticks, pipes and asterisks) with spaces. A token carries a link
from its first `http://` or `https://` in any case, or when it is a bare
host link (`example.com/x`, `www.example.com`; a host whose last label is a
common file extension, as in `README.md/CHANGELOG.md`, counts only after
`www.`); the link ends at the first non-ASCII character
(so a Korean particle written onto it is not part of it), and trailing
punctuation, markdown emphasis and a trailing `/` are dropped. Scheme and host
compare case-insensitively, and so does a github.com path. Observed evidence is the scenario's own plus
any `evidence_links` the harness recorded on the observation. A link the model
wrote in its decision file is never evidence: the live harness keeps only the
decision contract's keys.

Words are whitespace tokens. Korean is spaced by word phrase, so its budgets
count those; a Japanese or Chinese reply would count far fewer tokens than it
has words, and the corpus has no such scenario.

## Two splits, kept apart

The held-out split is never used to tune skill text, prompts, or the grader.
It is enforced by structure and tested by `tests/test_scenario_suites.py`: two
files, `tuning` read unless `--split held-out` is named, a held-out run over
the whole split, no shared id or request, every category in both, a held-out
share between a fifth and three tenths, a held-out report with totals only
(no per-category rate, scenario id, decision or failure) that needs an
observation of every held-out scenario, a split-mismatched observations file
refused, and no
held-out id or request in any skill, agent-skill, skill producer, routing or
catalog source. The observations file of a held-out run still holds the arm's
replies; do not read it while editing skill text.

## Observation classes, report, arms, safety

These are the same as in
[`automation-intent/v1`](../../automation-intent/v1/README.md#observation-classes-and-the-report):
`arm_did_not_run`, `timeout`, `transport_error` and `not_observed` are excluded
by name; every rate is `omh_reported_rate/v1` with a Wilson 95% interval, and
an empty denominator is `percent: null` with basis `no_observations`; the
`skill-text` and `bare` arms run one scenario at a time through `omh coding
hermes-child dispatch --confirm-dispatch` behind `--allow-paid-live`,
`--max-paid-calls` and `--confirm`, with the prompt on stdin and never
persisted.

The arm is told to record the hand-off it would make, not to make it. The
child has the `file` toolset only, so it cannot start a coding CLI, push a
branch or open a pull request. That is also the limit of what this suite
measures: it grades the decision and the reply, not an executed hand-off. A
measurement of the parent actually calling `omh_dag` export or `omh coding
fanout dispatch` needs a recorded Hermes session as an external arm.

## Commands

```bash
uv run python benchmarks/orchestration/v1/bench.py validate
uv run python benchmarks/orchestration/v1/bench.py grade --text \
  --observations benchmarks/orchestration/v1/fixtures/recorded-observations.json
uv run python benchmarks/orchestration/v1/bench.py run \
  --arm my-model-skill --arm-kind skill-text \
  --model <alias> --provider <alias> --reasoning <alias> \
  --output benchmarks/orchestration/v1/artifacts/tuning-skill.json \
  --allow-paid-live --max-paid-calls <scenarios> --confirm
```

The fixture's numbers measure nothing; do not quote them.

## Files

| Path | Role |
| --- | --- |
| `corpus/tuning.json`, `corpus/held-out.json` | the two splits |
| `manifest.json` | split digests and counts, arms and skill files, execution policy |
| `fixtures/recorded-observations.json` | hand-written observations exercising every grading path |
| `bench.py` | `validate`, `grade`, `run` |
| `src/quality/orchestration_grading.py` | scenario schema and grader |
| `src/quality/scenario_suite.py` | splits, observation classes, report, prompt, child argv |

Tests: `tests/test_scenario_suite_graders.py`, `tests/test_scenario_suites.py`.

## Latest measured status

`prepared_not_observed`. No live arm has been run, and there is no headline
number. Running one is an operator decision, because it spends money.
