# OMH Skill-Lift Benchmark (`benchmarks/skill-lift/v1`)

Measures whether an OMH skill delivers statistically meaningful lift over a bare
frontier model (`without_skill` vs `with_skill`) without breaking negative controls
or inflating token cost.

## Verdict Rules (2-Model Live Gate)

A skill **passes** live admission/retention only when across **both** frontier models:

1. **Deterministic lift**: `pass_rate_delta >= +15.0%p` OR `failure_reduction_rate >= 50.0%`
   (computed with `omh_reported_rate/v1`; an empty denominator reports `percent: null`,
   `basis: "no_observations"`, and fails rather than passing).
2. **Zero negative-control regressions**: `negative_control_regressions == 0`.
3. **Bounded token overhead**: `token_overhead_ratio <= 1.5`.

Skills failing lift on both models enter the consolidation/retirement queue.

## Offline CI Usage (Free, Deterministic)

```sh
uv run python benchmarks/skill-lift/v1/bench.py validate
uv run python benchmarks/skill-lift/v1/bench.py run --adapter fake --models model-a,model-b
```

## Paid Live Usage (Explicit Opt-In Only)

Never runs automatically or in CI. Requires `--allow-paid-live` and `--confirm` and
dispatches isolated single-query children via `omh coding hermes-child dispatch`:

```sh
uv run python benchmarks/skill-lift/v1/bench.py run \
  --adapter hermes-child \
  --models <provider/model-a>,<provider/model-b> \
  --allow-paid-live --confirm
```
