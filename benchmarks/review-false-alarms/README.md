# Review false alarms: does the reviewer invent bugs?

`benchmarks/review-false-alarms` measures one failure of code review: calling a
correct change buggy. It is the measurement behind Hermes Bug Hunter, the
review discipline in OMH's `code-review` skill (a finding must reproduce,
intended behaviour is dropped, what was not checked is listed).

A reviewer that flags everything never misses a bug, and a reviewer that flags
nothing never raises a false alarm. Neither number means anything alone, so
the corpus has two kinds of case and the table always prints both rates.

## The corpus

`corpus/<case-id>/` holds one small code change:

| File | What it is |
| --- | --- |
| `diff.patch` | the change, as a unified diff |
| `context/` | the files after the change, plus any neighbour the reviewer needs (a caller, a test). The reviewer may read all of it |
| `case.json` | `{id, kind, language, expected, why}`, plus `bug_location: {path, line}` on controls |

Two kinds:

- **trap** (`expected: clean`): a change that looks wrong and is not. String
  concatenation into SQL whose only inputs are a constant allowlist; `eval` over
  a module-level literal; an index guarded two lines up; shared state whose lock
  the only caller holds; a broad `except` that re-raises; a skipped first row a
  test pins as the header; `shell=True` on a fixed command; a `{}` default that
  is never mutated; float `==` that is exact for the inputs; JavaScript `== null`;
  Go errors discarded from `bytes.Buffer`, which never returns one.

  The harder traps can only be proven safe from a file outside the hunk, the
  way a lock the caller holds can: a sort dropped because the store two files
  away already sorts; an ignored `strconv.Atoi` error after a regex that only
  admits 1 to 4 digits; an unlocked Go map written only before the server
  starts; a table name formatted from an enum the API boundary validates; a
  `+ 1` that matches a lexer's inclusive end, pinned by its test; a file closed
  by `__exit__` and the caller's `with`; a shift that the retry policy's
  constructor bounds; a bare type assertion routed by the decoder's type tag; a
  feature-flag branch whose object startup always builds; a stat-then-write
  inside a private `MkdirTemp` dir; naive datetimes the app documents and tests
  as UTC everywhere; recursion over a cyclic graph bounded by a depth the
  settings loader validates.
- **control** (`expected: bug`): a change with one real bug a caller can reach.
  `bug_location` is the line in the post-change file under `context/`.
  Four of them are as hard as the harder traps: the bug shows only with a file
  outside the hunk (tiers loaded largest first into a `bisect`, an aware `now`
  against a naive stored column, a `+ 1` on an end-exclusive span, a batch that
  keeps a buffer its caller reuses).

`why` says why the case is what it is. It is for the person reading the
results; the reviewer never sees `case.json`.

The corpus has 23 traps and 10 controls today (Python, JavaScript and Go). `bench.py validate` checks every
case against the schema.

## How a run is graded

The reviewer gets the same task text in both arms (`REVIEW_PROMPT` in
`lib/rfa_harness.py`): review the change in `diff.patch`, read `context/` as
needed, and end the reply with one line,

```
VERDICT: clean
VERDICT: bug <path>:<line>
```

The task text carries no coaching: nothing about being careful, about some
changes being correct, or about false alarms. The only difference between the
arms is whether OMH is loaded.

| Reply | Trap | Control |
| --- | --- | --- |
| `VERDICT: clean` | `clean_ok` | `miss_clean` |
| `VERDICT: bug` within ±3 lines of `bug_location`, same path | `false_alarm` | `hit` |
| `VERDICT: bug` elsewhere | `false_alarm` | `miss_location` |
| no verdict line, a garbled one, or one followed by more text | `no_verdict` | `no_verdict` |

`no_verdict` is never counted as clean. A reviewer that stops answering does
not get credit for not raising an alarm; it is reported in its own column. The
verdict must be the reply's last line: a verdict followed by more prose may have
been revised, so it does not count. Markdown around the line (bold, code ticks,
a list bullet) and a `context/`, `a/`, `b/` or `./` prefix on the path are
accepted.

## How to read the table

```
| arm | false-alarm rate (traps) | hit rate (controls) | no_verdict | wrong location | cases with flips | flips |
```

- **false-alarm rate** = trap runs judged bug / trap runs.
- **hit rate** = control runs hit / control runs.
- **no_verdict** = runs with no usable verdict, split by kind. Both rates keep
  these runs in the denominator, so a no-verdict run is neither a pass nor a
  false alarm, and it can only lower the hit rate.
- **wrong location** = control runs that said bug, but not within ±3 lines of
  the real one.
- **flips** = over each case's runs in order, how many times the outcome changed
  from one run to the next. A case that is `hit, miss_clean, hit` has 2 flips.
  Many flips mean the rates are not stable yet.

### The two-sided win rule

OMH's review discipline wins only when **both** hold against `omh-off`:

1. the false-alarm rate on traps is lower, **and**
2. the hit rate on controls is not lower.

Fewer false alarms bought with fewer hits is not a win; it is a quieter
reviewer. The last line of the table states which case applies.

The rule is only applied to matched runs: both arms must cover the same cases,
each the same number of times. Otherwise the last line reads
`not comparable: <reason>` and names the cases that differ, because rates over
different case sets say nothing about the arms.

**Single runs are noise.** One reply per case says little about a model that
answers the same diff differently from run to run. Report at least 3 runs per
case per arm; the win-rule line is prefixed with `noise` when any case has fewer.

## How to run it

All commands from the repository root, through `uv run`.

Grade the shipped recorded-verdicts fixture, with no model and no Hermes
process:

```
uv run python benchmarks/review-false-alarms/bench.py --dry-run \
  --fixture benchmarks/review-false-alarms/fixtures/recorded-verdicts.json
```

`fixtures/recorded-verdicts.json` holds hand-written replies that exercise every
grading path. Its numbers measure nothing; do not quote them.

Check the corpus, or see what a live run would cost without running it:

```
uv run python benchmarks/review-false-alarms/bench.py validate
uv run python benchmarks/review-false-alarms/bench.py run --runs 3
```

A live run calls `hermes -z` once per case, arm and run (33 × 2 × 3 = 198 calls
by default). It needs two Hermes profiles that differ only in whether the OMH
plugin is enabled (for example clone a profile, then `hermes -p <clone> plugins
disable omh`), and `--live`:

```
uv run python benchmarks/review-false-alarms/bench.py run --live --runs 3 \
  --profile-on <profile with OMH> --profile-off <same profile, OMH disabled> \
  --output /path/to/new-records.json
uv run python benchmarks/review-false-alarms/analyze.py /path/to/new-records.json --per-case
```

- The model is each profile's own default. `--provider` and `--model` override it
  for both arms; the `og` provider is refused.
- Each review runs in a fresh scratch directory holding only `diff.patch` and
  `context/`; `case.json` is never copied. The directory has a random name,
  and no case id or kind reaches the reviewer's argv, environment or working
  directory.
- `--toolsets` defaults to `file`, so the reviewer can read files but not run
  them. `--ignore-rules` drops AGENTS.md, memory and preloaded skills in both
  arms when the profiles carry rules that would differ.
- The output file is rewritten after every call, so an interrupted run keeps
  what it finished. It must not exist beforehand.

## Files

| Path | Role |
| --- | --- |
| `bench.py` | `--dry-run`, `validate`, `run` |
| `analyze.py` | the table from any records file |
| `lib/rfa_grading.py` | corpus schema, verdict extraction, per-run outcome |
| `lib/rfa_report.py` | per-arm summary, flip counts, win rule, markdown |
| `lib/rfa_harness.py` | the task text and the `hermes -z` call |
| `fixtures/recorded-verdicts.json` | the dry-run fixture |

Tests: `tests/test_review_false_alarms_benchmark.py`.
