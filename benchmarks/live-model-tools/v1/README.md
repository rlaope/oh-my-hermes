# OMH-native Hermes Agent model calibration benchmark

`omh_live_model_tool_benchmark/v1` compares baseline and model-family-calibrated
OMH prompts on a pinned synthetic coding corpus.

The live path measures the product under test:

1. resolve the selected model through `omh coding model-route`;
2. build baseline and optimized prompts from the same task, adding only the
   calibration selected by `unit_prompt_protocol.py`;
3. dispatch through the explicit
   `omh coding hermes-child dispatch --confirm-dispatch` boundary;
4. grade the final workspace and machine answer with controller-only validators;
5. read tool, token, and cost metrics from authenticated
   `routing_observation/v1` evidence.

There is no OMO execution path. OMH remains Hermes-native: core OMH makes no
provider call, and the explicit benchmark command launches the local Hermes CLI
under the existing isolated child-process contract.

There are two explicit live execution paths:

- `omh` preserves the official isolated `omh coding hermes-child dispatch`
  contract. It deliberately cannot read the caller's Hermes profile credentials.
- `hermes_current_session` invokes `hermes --oneshot` with the current Hermes
  configuration, so a model already authenticated in that profile can run. It is
  explicitly labeled `hermes_current_session` in every run artifact and does
  not use the isolated child boundary.

Both paths use the same pinned corpus and controller-only validators. In either
case prompts are passed only on stdin, temporary usage telemetry is discarded
once scalar observed tool/token/cost metrics are recorded, and raw prompts,
stdout, stderr, credentials, and config content are never persisted.

## Safety and claim boundary

- `fake` is the default offline harness.
- `omh` requires `--allow-paid-live`; it can trigger paid provider calls through
  the local Hermes CLI.
- Prompts are sent over stdin and are never persisted by OMH.
- Missing token or cost telemetry stays `null`; the benchmark never estimates it.
- A completed child process is not a passing task. Controller-only semantic
  validators determine pass/fail.
- Results describe the pinned corpus, OMH version, Hermes version, model IDs, and
  conditions only. They do not establish universal model superiority.

## Commands

```bash
python benchmarks/live-model-tools/v1/bench.py doctor
python benchmarks/live-model-tools/v1/bench.py corpus --verify
python benchmarks/live-model-tools/v1/bench.py smoke

# Explicit paid live smoke (isolated official child):
python benchmarks/live-model-tools/v1/bench.py smoke \
  --harness omh \
  --model qwen3-coder-next \
  --condition optimized \
  --allow-paid-live \
  --max-paid-calls 1

# Current-profile live smoke (models authenticated in this Hermes config):
python benchmarks/live-model-tools/v1/bench.py smoke \
  --harness hermes_current_session \
  --model moonshotai/kimi-k3-ultrafast \
  --current-session-provider kimi_k3 \
  --condition optimized \
  --allow-paid-live \
  --max-paid-calls 1
```

`--current-session-provider` is only for `hermes_current_session`: use it when
the active Hermes profile registered the selected model under a local custom
provider ID (for example, `kimi_k3`) that differs from the manifest's provider.
It never changes the isolated `omh` harness. A failed live invocation still
writes a metadata-only record with a redacted failure classification and receipt;
raw stdout, stderr, prompts, credentials, and config remain unpersisted.

Run baseline and optimized matrices separately so every condition uses the same
pinned instances. A third condition, `family`, sends the block the model would
inherit from its family with any exact-model override skipped; it exists so an
override (for example `gpt-6-astra` over the `gpt` block) is measured against
what it replaced and not only against no calibration. Pair it with `analyze.py
--baseline-condition family` so the override is the `optimized` side:

```bash
python benchmarks/live-model-tools/v1/bench.py run \
  --harness omh --condition baseline --allow-paid-live --max-paid-calls 240
python benchmarks/live-model-tools/v1/bench.py run \
  --harness omh --condition optimized --allow-paid-live --max-paid-calls 240
```

The manifest currently covers Qwen3-Coder, current DeepSeek, and GLM agent
routes in addition to the existing comparison families. Prompt controls are
version-aware:

- Qwen3-Coder is treated as a non-thinking coding-agent model.
- DeepSeek preserves the distinction between current thinking-mode models and
  legacy R1 guidance.
- GLM can benefit from interleaved reasoning between tool results when the
  Hermes/provider contract exposes and preserves that context.

Provider parameters are not claimed unless Hermes actually exposes them and the
observation records them.

## Latest measured status

The 2026-08-13 evaluation run completed the full offline fake matrix:

| Harness | Condition | Passed | Scheduled | Delta |
| --- | --- | ---: | ---: | ---: |
| `fake` | baseline | 30 | 30 | |
| `fake` | optimized | 30 | 30 | `0.0` |

This proves the pinned corpus, controller validators, pairing, analysis, and
audit pipeline execute end to end. It is not model-performance evidence.

### 2026-08-14 `hermes_current_session` live evaluation

Live runs through the `hermes_current_session` path on the pinned evaluation
corpus (30 instances, digest
`c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33`). Only
validator passes count as success. These results are separate from, and must
not be mixed with, the official isolated `omh` child harness.

| Model | Condition | Passed | Total tokens |
| --- | --- | ---: | ---: |
| GPT-5.6 Sol (`openai-codex`) | baseline | 17 / 30 | 1,919,268 |
| GPT-5.6 Sol (`openai-codex`) | optimized | 17 / 30 | 1,896,666 |
| Kimi K3 ultrafast (`moonshotai/kimi-k3-ultrafast`) | baseline | 11 / 30 | 2,196,714 |
| Kimi K3 ultrafast (`moonshotai/kimi-k3-ultrafast`) | optimized | 10 / 30 | 1,959,490 |
| GLM 5.2 ultrafast (`z-ai/glm-5.2-ultrafast`) | baseline | 14 / 30 | 2,340,947 |
| GLM 5.2 ultrafast (`z-ai/glm-5.2-ultrafast`) | optimized | 13 / 30 | 2,416,909 |

Per-class pass counts (out of 3 instances each):

| Class | Sol base | Sol opt | Kimi base | Kimi opt | GLM base | GLM opt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RENAME (edit) | 3 | 2 | 3 | 2 | 3 | 3 |
| BUGFIX (edit) | 2 | 3 | 2 | 1 | 3 | 1 |
| PRECEDENCE (read) | 0 | 0 | 0 | 0 | 0 | 0 |
| CALLFLOW (read) | 0 | 0 | 0 | 0 | 0 | 0 |
| REFERENCES (search) | 3 | 3 | 0 | 1 | 2 | 3 |
| PREDICATE (search) | 3 | 3 | 0 | 0 | 0 | 0 |
| DEFINITION (lsp) | 0 | 0 | 0 | 0 | 0 | 0 |
| DIAGNOSTICS (lsp) | 0 | 0 | 0 | 0 | 0 | 0 |
| SCALE (routing) | 3 | 3 | 3 | 3 | 3 | 3 |
| EXPLICIT (routing) | 3 | 3 | 3 | 3 | 3 | 3 |

Kimi K3 ultrafast and GLM 5.2 ultrafast were served through
[OpenGateway](https://opengateway.ai/) — one API for every LLM, built for
production — via the local `kimi_k3` provider registration. Claude Fable 5 was
not measured: the profile's Anthropic OAuth credential was rejected by the
provider with "Third-party apps now draw from your extra usage" (HTTP 400) and
no extra-usage credit was available. The local SGLang GLM proxy
(`HERMES_CUSTOM_SGLANG_PROXY_API_KEY`) was also unusable (HTTP 401 invalid API
key), so GLM ran through OpenGateway instead.

Two earlier GPT-5.6 Sol baseline attempts on the same day are invalid and
excluded: the first (30 runs, 0/30) passed the task on stdin, which
`hermes --oneshot` does not read, so the model never saw the task; the second
(30 runs, 2/30) leaked the caller's `TERMINAL_CWD` into the child, so the
model read and mutated files in the user's home directory instead of the
benchmark workspace. Both defects were harness bugs, not model results; the
records are kept as `*-invalid-stdin.jsonl` and `*-invalid-cwd.jsonl` for
audit only.

Harness corrections made for this measurement (benchmark correctness only):
`.py` launchers now run under the current interpreter on every platform, the
oneshot prompt is passed as the flag's argument with `--in <workspace>` and a
workspace-pinned `TERMINAL_CWD`, and tool byproducts (`.venv`, `.pytest_cache`,
`__pycache__`, `uv.lock`, symlinks) no longer count as model mutations.

Results describe this pinned corpus, OMH version, Hermes version, model IDs,
and conditions only. They do not establish universal model superiority.

### 2026-09-05 `gpt-6-astra` four-arm evaluation (issue #1310)

The first exact-model override (`MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"]`,
#1307) measured against the block it replaced. Same pinned evaluation corpus
(30 instances, digest `c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33`),
`hermes_current_session` path, `openai-codex` / `gpt-6-astra` at `xhigh`,
omh 2.0.0, Hermes Agent 0.21.0, targeted manifest with that one live entry.
Arms ran sequentially in the order optimized → family → baseline → revised
(not counterbalanced within an arm; the harness runs one condition per
invocation). Only validator passes count as success.

| Arm | What the prompt carries | Passed | Total tokens | Mean tokens | Tool calls | API turns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | bare contract, no calibration | 18 / 30 | 1,550,904 | 51,697 | 310 | 203 |
| family | inherited `HIGH_EFFORT_CALIBRATIONS["gpt"]` | 18 / 30 | 1,513,367 | 50,446 | 286 | 194 |
| optimized | original `gpt-6-astra` override (#1307 wording) | 18 / 30 | 1,675,942 | 55,865 | 310 | 206 |
| revised | `gpt-6-astra` override as shipped after this run | 18 / 30 | 1,532,241 | 51,075 | 294 | 192 |

Tool calls and API turns are not harness metrics on this path (the usage
file carries neither); they were read afterwards from the Hermes `sessions`
table for the sessions each arm created, joined by run order, and are
reported as out-of-harness observations.

Per template (passes out of 3 / tokens over the 3 seeds):

| Template (class) | baseline | family | optimized | revised |
| --- | ---: | ---: | ---: | ---: |
| RENAME (edit) | 3 / 159,187 | 3 / 159,894 | 3 / 163,757 | 3 / 163,468 |
| BUGFIX (edit) | 3 / 228,497 | 3 / 189,869 | 3 / 233,835 | 3 / 205,791 |
| PRECEDENCE (read) | 0 / 106,910 | 0 / 109,283 | 0 / 109,617 | 0 / 109,779 |
| CALLFLOW (read) | 0 / 161,874 | 0 / 174,767 | 0 / 165,916 | 0 / 163,897 |
| REFERENCES (search) | 3 / 160,587 | 3 / 156,328 | 3 / 154,761 | 3 / 161,001 |
| PREDICATE (search) | 3 / 133,311 | 3 / 119,482 | 3 / 120,176 | 3 / 119,834 |
| DEFINITION (lsp) | 0 / 156,716 | 0 / 149,832 | 0 / 172,126 | 0 / 148,439 |
| DIAGNOSTICS (lsp) | 0 / 233,511 | 0 / 227,993 | 0 / 322,645 | 0 / 227,300 |
| SCALE (routing) | 3 / 116,522 | 3 / 124,772 | 3 / 128,995 | 3 / 128,785 |
| EXPLICIT (routing) | 3 / 93,789 | 3 / 101,147 | 3 / 104,114 | 3 / 103,947 |

Paired token deltas per instance (10,000-sample bootstrap, seed 20260813):

| Pair (b − a) | Mean Δ tokens | CI95 | b > a |
| --- | ---: | ---: | ---: |
| family − baseline | −1,251 | [−3,763, +1,300] | 15 / 30 |
| optimized − baseline | +4,168 | [−324, +9,100] | 23 / 30 |
| optimized − family | +5,419 | [+1,444, +10,150] | 26 / 30 |
| revised − family | +629 | [−1,109, +2,445] | 24 / 30 |
| revised − optimized | −4,790 | [−9,336, −1,075] | 7 / 30 |

Pass rate tied across every arm (McNemar p = 1.0 for both `analyze.py`
pairs), so the decision rests on cost. The original override spent more than
the block it replaced, with the excess in `BUGFIX` and `DIAGNOSTICS`: the
model kept working on instances it did not pass. Its first sentence ("carry
them to completion instead of pausing for sign-off") was the one clause with
that reading; the revised block replaces it with "nothing outside them is
owed", keeps the assumption-over-question and test-sizing sentences, and
lands within the family block's cost. That is the wording now in
`unit_prompt_protocol.py`; the `optimized` row is the wording it replaced.

The read and lsp classes scored 0 in every arm, as they did for every model
in the 2026-08-14 run; that is a property of those templates against the
current validators, not of the calibration. The traits the Astra override was
written for (clarifying questions, delegation, test breadth) are never
provoked by this corpus; #1327 tracks the templates and counters that would
measure them.

Results describe this pinned corpus, OMH version, Hermes version, model IDs,
and conditions only. They do not establish universal model superiority.

### 2026-09-05 routing lanes: Hermes alone vs OMH on the same 30 tasks

Same pinned evaluation corpus and day as the four-arm run above. Each row is
one model at one effort through `hermes_current_session`, except the last
three, which compose an OMH-routed outcome per task from the single-model
rows: every task goes to the arm the router's class resolves to on this
machine, and its measured record is taken as is. The routing decision comes
from `omh coding complexity` on the task text alone; no benchmark result
feeds the scorer.

Cost is OMH's list-price table applied to each session's input and output
tokens (`APPROX_PRICE_PER_MTOK`), so rows are comparable even where the host
reports the call as included or unknown. Tool calls, turns, and wall clock
come from the Hermes `sessions` table, joined by run order.

| Arm | Passed | Tokens | List-price cost | Cost / pass | Tool calls | Turns | Median s / task | Total min |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hermes alone: machine default, `gpt-5.6-sol` medium | 18 / 30 | 2,469,798 | $0.96 | $0.053 | 337 | 321 | 47 | 24.8 |
| `gpt-6-astra` xhigh, no calibration | 18 / 30 | 1,550,904 | $4.29 | $0.239 | 310 | 203 | 39 | 23.3 |
| `gpt-6-astra` xhigh + OMH calibration (shipped block) | 18 / 30 | 1,532,241 | $4.30 | $0.239 | 294 | 192 | 37 | 22.5 |
| `gpt-6-astra` low (the effort the light tier would set) | 18 / 30 | 1,522,932 | $4.64 | $0.258 | 302 | 203 | 39 | 22.3 |
| `quick` head alone: `z-ai/glm-5.2-ultrafast` low | 14 / 30 | 1,693,078 | $0.06 | $0.004 | 226 | 217 | 4 | 2.1 |
| `unspecified-high` head alone: `moonshotai/kimi-k3-ultrafast` medium | 11 / 30 | 1,975,651 | $0.36 | $0.032 | 308 | 242 | 9 | 7.6 |
| OMH routed, before `exhaustive_search` (all 30 → `quick`) | 14 / 30 | 1,693,078 | $0.06 | $0.004 | 226 | 217 | 4 | 2.1 |
| OMH routed, after the signal, shipped chains (6 search → Kimi, 24 → GLM) | 12 / 30 | 1,732,236 | $0.10 | $0.008 | 244 | 222 | 5 | 2.5 |
| OMH routed, after the signal, `unspecified-high` head = `gpt-5.6-sol` | 18 / 30 | 1,821,874 | $0.18 | $0.010 | 243 | 235 | 5 | 5.2 |

Per template, the `quick` head tied the flagship on eight of ten (edit,
read, lsp, routing: identical pass counts) and lost only the two
exhaustive-search templates, REFERENCES 2 / 3 and PREDICATE 0 / 3 against
3 / 3 and 3 / 3. Before this run the scorer read those prompts as light
(score 0, no signal); `exhaustive_search` (+4) now lifts "find every
reference / all usages / every occurrence" to `standard` on its own, and the
30-task classification changed for exactly those six.

What the numbers say, and no more:

- Against the machine default (Sol medium), OMH routing with a GPT head for
  the `standard` class keeps the pass rate (18 / 30) at 19% of the cost and
  21% of the wall clock: $0.18 vs $0.96, 5.2 min vs 24.8 min.
- Against the flagship at `xhigh`, the same routing keeps the pass rate at
  4% of the cost and 22% of the wall clock.
- With the shipped `unspecified-high` head (Kimi K3) the signal does not
  recover the six search tasks on this machine (0 / 6 for Kimi ultrafast),
  so the routed result is 12 / 30. The head has to pass exhaustive search;
  Sol did (6 / 6), Astra did (6 / 6), GLM (2 / 6) and Kimi (0 / 6) did not.
  An owner who wants the 18 / 30 row puts a GPT model first for that class:

  ```json
  {"schema_version": "mixture_chain_overrides/v1",
   "categories": {"unspecified-high": [
     {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
     {"model": "kimi-k3", "reasoning_effort": "medium"}]}}
  ```

- Effort routing did nothing for Astra here: `low` and `xhigh` produced the
  same passes, tokens, and wall clock, so no claim is made for it.
- No arm passes a read or lsp task; 18 / 30 is this corpus's ceiling for
  every model measured, so no routing can raise pass rate here. Pass-rate
  claims need a corpus with headroom (#1333).

Results describe this pinned corpus, OMH version, Hermes version, model IDs,
and conditions only. They do not establish universal model superiority.
