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
host link: `www.<host>`, a host of three or more labels followed by a path
(`docs.example.org/x`), or a two-label host on a generic web TLD followed by a
path (`example.com/x`). Other two-label names (`socket.io/client`,
`Node.js/Deno`) and hosts whose last label is a file extension
(`README.md/CHANGELOG.md`) read as prose and count only with their scheme.
The link ends at the first non-ASCII character
(so a Korean particle written onto it is not part of it), and trailing
punctuation, markdown emphasis and a trailing `/` are dropped. Scheme and host
compare case-insensitively, `http` and `https` count as one link, and a
github.com path compares case-insensitively too. Observed evidence is the scenario's own plus
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
(no per-category or per-group rate, scenario id, decision or failure) that
needs an observation of every held-out scenario and at least three quarters of
them graded, a split-mismatched observations file refused, and no held-out id
or request in any skill, agent-skill, skill producer, routing or catalog
source. None of this is secrecy: the corpus, held-out expectations included,
is public in this repository, and a held-out run's observations file holds
the arm's replies. Keeping the held-out split out of tuning is the operator's
discipline; do not read either while editing skill text.

What the held-out split can and cannot show: its scenarios are near siblings
of tuning ones (the same kinds of request with different repositories,
channels and jobs), so it measures near transfer, not generalisation to new
kinds of request. It is also small: a perfect score on a split this size has a
Wilson 95% interval whose lower bound is only around 60-70%, so a held-out number is a
check against over-fitting the tuning split, not a precise rate.

## Which numbers measure the skill text

A tuning report splits its scenarios into `request_derivable` (any arm can
derive the expectation from the request, its prior state, its evidence and
the decision contract) and `skill_rule`. A `skill_rule` scenario rests on a
rule the request does not carry, which only the skill text states: here
`owner_named_in_this_request`, from `skills/dag-ulw/SKILL.md` ("No external
coding CLI runs unless the person named it as the coding owner in this
request"). Every coding request that names no owner in this request is in
that group, whether nobody chose an owner or the choice came from an earlier
request: without the rule, handing it to an external CLI is a defensible
reading. The `skill-text` arm gets that file inlined; the `bare` arm is never
told the rule, so the gap between the arms on that group is what the skill
text teaches.

The `skill_rule` group is small by design: a few scenarios in each split, with
the counts pinned in `manifest.json` (`skill_rule_scenarios`) and at least two
in every split. It can show whether inlining the skill text moves an arm on
the rule that text states, as a gap between the `skill-text` and `bare` arms
on the same scenarios. It cannot give a precise rate (its Wilson interval is
wide), and on the held-out split it is never reported on its own, because a
held-out report carries totals only.

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

The fixture's numbers measure nothing; do not quote them. A run whose number
will be quoted is committed under `results/` in the lane and graded from
there, as in
[`automation-intent/v1`](../../automation-intent/v1/README.md#commands).

## Files

| Path | Role |
| --- | --- |
| `corpus/tuning.json`, `corpus/held-out.json` | the two splits |
| `manifest.json` | split digests and counts, arms and skill files, execution policy |
| `fixtures/recorded-observations.json` | hand-written observations exercising every grading path |
| `bench.py` | `validate`, `grade`, `run`, through the shared `benchmarks/scenario_suite_bench.py` |
| `src/quality/orchestration_grading.py` | scenario schema and grader |
| `src/quality/scenario_suite.py` | splits, observation classes, report, prompt, child argv |

Tests: `tests/test_scenario_suite_graders.py`, `tests/test_scenario_suites.py`.

## Latest measured status

`prepared_not_observed`. No live arm has been run, and there is no headline
number. Running one is an operator decision, because it spends money.
