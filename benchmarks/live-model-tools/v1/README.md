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

OMH remains Hermes-native: core OMH makes no provider call, and the explicit
benchmark command launches the local Hermes CLI under the existing isolated
child-process contract. The one non-Hermes path is the comparison harness
`omp` (below), which runs oh-my-pi on the same instances so the two harnesses
can be graded side by side; it is not an OMH runtime path.

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
stdout, stderr, credentials, and config content are never persisted. The
isolated-child path reports no tool metric: its child runs as
`hermes chat --query-file -`, the one Hermes transport that reads a prompt from
stdin, and Hermes writes its usage report for `-z` alone, so its token and cost
figures are read after exit from the `sessions` rows of the child's disposable
`HERMES_HOME/state.db` and are `null` when that ledger records no API call
(#1831); the current-session path keeps its `-z --usage-file` telemetry.

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

`--harness omp` runs oh-my-pi (`omp -p --mode json`) in the workspace with the
`baseline` condition prompt, byte for byte what the Hermes arms send, and the
same validators. It accepts no other condition and no `--edit-directive` (both
name OMH or Hermes specifics). `--omp-executable` should be a launcher that
rebuilds omp's environment itself (an isolated `HOME`, no inherited provider
keys), so omp can reach only the routes configured for it. The record keeps
scalar metrics only (`harness_metrics`: tokens by direction, tool calls by name,
stop reason, whether the last assistant text carries `changed_paths`); omp keeps
its own transcript in its own home. Every live record now has `wall_seconds`.

```bash
python benchmarks/live-model-tools/v1/bench.py run --harness omp \
  --omp-executable <isolated omp launcher> \
  --extra-model "id=claude-haiku-4-5-20251001,provider=cpa,effort=medium,family=claude" \
  --model claude-haiku-4-5-20251001 --split impact-ab \
  --git-init-workspace --test-env --allow-paid-live --max-paid-calls 12
```

Before a paid `hermes_current_session` run, set a turn cap in every profile the run uses
(`hermes -p <profile> config set agent.max_turns 120`). The harness timeout stops only the
`hermes` client; the gateway keeps running the turn until the cap. Count tokens as well as
paid calls: watch each profile's `state.db` during the run for sessions still writing past
their timeout.

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

Two more conditions measure the shared unit head, the block every real
dispatched fanout unit prompt starts with:

- `unit` sends the product's own head: the `shared_head` blocks of
  `assemble_unit_prompt()` (`src/coding/unit_prompt_assembly.py`, the
  assembler every dispatch path uses) with a fixed goal line, so it tracks
  `src/` and stays byte-identical across instances, the way sibling units
  share it.
  The `optimized` calibration follows the head, then a deliverable-precedence
  note, then the same task and completion contract as every other condition.
  The head tells a unit to end with a `fanout_unit_result/v1` block and to
  return `input_required` to a parent. Neither exists in a benchmark run, so
  the note states that `.omh-benchmark-answer.json` is the graded deliverable
  and takes precedence over any other return format named above it. Both
  unit arms carry the note.
- `unit_lean` sends `unit` with the head blocks named in
  `UNIT_LEAN_OMITTED_BLOCKS` (`lib/omh_live.py`) removed, and nothing else.
  The names are the assembler's block names, and the assembler rejects one
  it does not know. The first set is `head.parent_clarification`, which also
  holds the head's only JSON example. A later arm can vary the set by name.

Every run record carries `prompt_digest`, the SHA-256 of the exact prompt text
its condition sent (the text itself is never kept). It also carries
`head_omitted_blocks`: `[]` for `unit`, the omitted names for `unit_lean`, and
`null` for conditions without the head. The offline `fake` harness receives
the condition prompt built with an empty route (no calibration) and echoes its
digest, so the offline matrix covers both arms. Pair the arms with
`--baseline-condition unit --optimized-condition unit_lean`:

```bash
python benchmarks/live-model-tools/v1/bench.py run --harness fake --condition unit
python benchmarks/live-model-tools/v1/bench.py run --harness fake --condition unit_lean
python benchmarks/live-model-tools/v1/bench.py run \
  --harness omh --condition unit --allow-paid-live --max-paid-calls 240
python benchmarks/live-model-tools/v1/bench.py run \
  --harness omh --condition unit_lean --allow-paid-live --max-paid-calls 240
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

  Since the 2026-10-13 shipped table this is the default shape: GPT-6.1
  Sol heads `unspecified-high`, ahead of Claude Opus 5.5 and Kimi K3 (Kimi
  K3.1 Pro since 2026-10-24). Neither GPT-6.1 Sol nor K3.1 Pro has been
  run on this corpus.

- Effort routing did nothing for Astra here: `low` and `xhigh` produced the
  same passes, tokens, and wall clock, so no claim is made for it.
- No arm passes a read or lsp task; 18 / 30 is this corpus's ceiling for
  every model measured, so no routing can raise pass rate here. Pass-rate
  claims need a corpus with headroom (#1333).

Results describe this pinned corpus, OMH version, Hermes version, model IDs,
and conditions only. They do not establish universal model superiority.

### 2026-09-13 `deepseek-flash` five-arm evaluation (issue #1463)

The `deepseek-v4.1-flash` exact-model override
(`MODEL_HIGH_EFFORT_CALIBRATIONS["deepseek-v4.1-flash"]`, #1465) measured
against the block it replaced, on the first day a served V4.1 Flash route
existed on the owner machine (the `og` gateway added `deepseek/deepseek-flash`
that morning; route receipt: a one-shot `hermes` call whose usage file names
`model deepseek/deepseek-flash`, `provider custom`, `cost_status unknown`).
Same pinned evaluation corpus (30 instances, digest
`c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33`),
`hermes_current_session` path, `og` / `deepseek/deepseek-flash`
(`--current-session-provider og`), omh 2.0.3 (calibration text read
in-process from the bench checkout at `2299e386`; the `revised` arm from the
branch that ships it), Hermes Agent 0.21.1 (2026.9.7), targeted manifest with
that one live entry at `high` (a second manifest at `low` for the last arm).
Arms ran sequentially, all on 2026-09-13 UTC (a Sunday, so the gateway billed
every arm at DeepSeek's off-peak rate): baseline (09:03–09:17Z) → family
(09:17–09:28Z) → optimized (a first attempt died at 13 / 30 when the machine
ran out of memory and was discarded; the complete run is 09:34–09:49Z) →
optimized at `low` (09:49–10:00Z) → revised (10:00–10:10Z). Not
counterbalanced within an arm. Only validator passes count as success.

| Arm | What the prompt carries | Passed | Total tokens | Mean tokens | Tool calls | API turns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline | bare contract, no calibration | 15 / 30 | 3,360,197 | 112,007 | 521 | 295 |
| family | inherited `HIGH_EFFORT_CALIBRATIONS["deepseek"]` | 15 / 30 | 2,564,954 | 85,498 | 434 | 244 |
| optimized | original `deepseek-v4.1-flash` override (#1465 wording) | 16 / 30 | 3,214,839 | 107,161 | 462 | 277 |
| revised | `deepseek-v4.1-flash` override as shipped after this run | 14 / 30 | 2,327,037 | 77,568 | 368 | 230 |
| optimized @ `low` | original override, effort `low` | 17 / 30 | 2,816,261 | 93,875 | 438 | 257 |

Tool calls and API turns are out-of-harness observations read afterwards
from the Hermes `sessions` table for each arm's contiguous window. The same
rows split the tokens: cache-miss input / output / cache-hit input per arm
were 288,558 / 103,191 / 2,968,448 (baseline), 266,171 / 79,647 / 2,219,136
(family), 294,698 / 100,813 / 2,819,328 (optimized), 255,280 / 66,125 /
2,005,632 (revised), 276,706 / 88,995 / 2,450,560 (`low`). Hermes replays
`reasoning_content` on every DeepSeek tool turn, so cache hits are 85–90% of
every arm's tokens and the harness `tokens` figure is that sum. The gateway
reports no price (`cost_status unknown`, `cost_usd 0` in every record); at the
gateway's published off-peak rates that day (0.15 / 0.60 / 0.003 per MTok)
the arms cost about $0.114, $0.094, $0.113, $0.084 and $0.102 respectively —
double that at the vendor's peak list rate.

Per template (passes out of 3 / tokens over the 3 seeds):

| Template (class) | baseline | family | optimized | revised | optimized @ low |
| --- | ---: | ---: | ---: | ---: | ---: |
| RENAME (edit) | 3 / 249,606 | 3 / 238,386 | 3 / 338,124 | 3 / 247,060 | 3 / 292,791 |
| BUGFIX (edit) | 3 / 472,272 | 3 / 308,894 | 3 / 462,369 | 3 / 272,843 | 3 / 325,661 |
| PRECEDENCE (read) | 0 / 249,579 | 0 / 215,772 | 0 / 256,632 | 0 / 240,847 | 0 / 221,275 |
| CALLFLOW (read) | 0 / 238,005 | 0 / 212,421 | 0 / 260,169 | 0 / 215,863 | 0 / 261,379 |
| REFERENCES (search) | 1 / 202,556 | 3 / 154,555 | 3 / 197,527 | 2 / 163,690 | 3 / 156,160 |
| PREDICATE (search) | 2 / 221,474 | 0 / 227,872 | 1 / 242,374 | 0 / 235,281 | 2 / 211,412 |
| DEFINITION (lsp) | 0 / 617,275 | 0 / 405,835 | 0 / 400,306 | 0 / 328,377 | 0 / 439,031 |
| DIAGNOSTICS (lsp) | 0 / 770,839 | 0 / 484,117 | 0 / 752,817 | 0 / 332,247 | 0 / 647,609 |
| SCALE (routing) | 3 / 203,697 | 3 / 199,863 | 3 / 167,634 | 3 / 145,617 | 3 / 140,903 |
| EXPLICIT (routing) | 3 / 134,894 | 3 / 117,239 | 3 / 136,887 | 3 / 145,212 | 3 / 120,040 |

Paired token deltas per instance (10,000-sample bootstrap, seed 20260813):

| Pair (b − a) | Mean Δ tokens | CI95 | b > a |
| --- | ---: | ---: | ---: |
| family − baseline | −26,508 | [−40,668, −13,894] | 6 / 30 |
| optimized − baseline | −4,845 | [−20,027, +11,261] | 18 / 30 |
| optimized − family | +21,663 | [+6,550, +42,944] | 24 / 30 |
| revised − family | −7,931 | [−22,782, +3,395] | 18 / 30 |
| revised − optimized | −29,593 | [−50,559, −12,636] | 7 / 30 |
| low − optimized | −13,286 | [−36,871, +8,209] | 4 / 30 |
| low − family | +8,377 | [−6,045, +28,137] | 18 / 30 |

Pass rate is indistinguishable across the arms (McNemar p = 1.0 for every
`analyze.py` pair except optimized vs revised at p = 0.5, two discordant
instances), but unlike the Astra run the per-template sets are not identical:
the two search templates flip between arms of this model (REFERENCES 1 / 3 /
3 / 2 / 3, PREDICATE 2 / 0 / 1 / 0 / 2), which reads as run-to-run variance on
those templates rather than a calibration effect, and the edit, routing, read
and lsp classes are constant. The decision rests on cost, and cost was clear:
the original override gave back most of what the family block had saved —
+21,663 tokens per instance over the family block (CI entirely positive,
more in 24 / 30) with the excess in `DIAGNOSTICS` (+268,700 over three seeds,
0 / 3 in both arms), `BUGFIX` (+153,475) and `RENAME` (+99,738): the model
re-ran checks on tasks it was not going to pass and over-verified tasks it
passed either way. The two phrases with that reading were "the visible reply
carries … the verification output" and "report the blocker with the observed
output"; the family block's closing rule ("make the smallest correct change,
verify once, and stop") was the sentence the override had dropped. The revised
block removes both phrases and restores that rule verbatim; it lands at
−7,931 per instance against the family block (CI spans zero — indistinguishable,
not better), −29,593 against the original, with the fewest tool calls and API
turns of any arm. That is the wording now in `unit_prompt_protocol.py`; the
`optimized` row is the wording it replaced.

The `low` arm measures the override's `unspecified-low` placement: at `low`
the original override cost −13,286 per instance against itself at `high` (CI
spans zero) and +8,377 against the family block at `high`, with the same edit
and routing passes — so on this corpus the rung buys no pass and a modest,
uncertain saving; the documented `low` / `high` / `max` ladder is real but this
corpus cannot rank it. Not measured: the composer block (no fanout in this
harness), `max`, and any claim beyond this corpus. Records, manifests,
receipts and analyses are archived outside git at
`.omc/research/deepseek-flash-bench-2026-09-13/` in the owner's main checkout.

Results describe this pinned corpus, OMH version, Hermes version, gateway,
model id and conditions only. They do not establish universal model
superiority.

### 2026-09-29 `codestral-2508` four-arm evaluation (issue #1056)

The `codestral` family block (`HIGH_EFFORT_CALIBRATIONS["codestral"]`, #1055)
measured against no block. Same pinned evaluation corpus (30 instances, digest
`c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33`),
`hermes_current_session` path, `codestral-2508` on Mistral's API through a
Hermes custom provider (`--current-session-provider mistral`), omh 3.0.0 at
`0075338c` (calibration text read in-process from that checkout), Hermes Agent
0.21.5 (2026.9.24) with a fresh `HERMES_HOME` and no plugins, targeted manifest
with that one live entry at `high`. The account's tier served Codestral only:
Mistral Large was refused and Medium and Small allowed zero requests, so the
`mistral` family is not measured here.

Codestral rejects a top-level `reasoning_effort` at any value (HTTP 400,
"reasoning_effort is not enabled for this model", including `none`), and
Hermes sends it whenever `--reasoning` is set, which this harness always does.
Every arm therefore ran with the provider's `base_url` at
`http://api.mistral.ai/v1` and `HTTP_PROXY` pointing at a loopback proxy that
deleted that one field from each `/v1/chat/completions` body and forwarded the
request over HTTPS; Hermes still saw the `api.mistral.ai` host, so none of its
local-endpoint behavior applied. The field was removed from every chat request
in every arm.

Arms ran sequentially on 2026-09-29 UTC: A1 baseline (13:42 to 13:47Z), A2
optimized (13:47 to 13:52Z), A3 optimized again for same-text drift
(13:52 to 13:56Z), then A4 baseline again (13:59 to 14:11Z). A4 was added after
A1 to A3 were read, with its pooled decision rule written before it ran. Not
counterbalanced within an arm. Only validator passes count as success. Every
record reports `cost_usd` 0.

| Arm | What the prompt carries | Passed | Total tokens | Mean tokens | Tool calls | API turns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A1 baseline | bare contract, no calibration | 4 / 30 | 671,854 | 22,395 | 130 | 122 |
| A2 optimized | `HIGH_EFFORT_CALIBRATIONS["codestral"]` | 3 / 30 | 813,221 | 27,107 | 153 | 142 |
| A3 optimized | same as A2, repeated | 6 / 30 | 680,631 | 22,688 | 144 | 121 |
| A4 baseline | same as A1, repeated | 1 / 30 | 725,578 | 24,186 | 140 | 131 |

Tool calls and API turns are out-of-harness observations read from the Hermes
`sessions` table for each arm's window. No session compacted in any arm. In A4,
five chat requests hit an upstream connection reset before any response
headers and Hermes resent them, which is why A4 took twice as long; wall clock
is not compared.

Per template (passes out of 3 / tokens over the 3 seeds):

| Template (class) | A1 baseline | A2 optimized | A3 optimized | A4 baseline |
| --- | ---: | ---: | ---: | ---: |
| RENAME (edit) | 0 / 56,700 | 0 / 87,413 | 0 / 73,253 | 0 / 63,262 |
| BUGFIX (edit) | 2 / 98,662 | 1 / 122,595 | 2 / 62,289 | 1 / 91,514 |
| PRECEDENCE (read) | 0 / 65,360 | 0 / 78,998 | 0 / 73,624 | 0 / 70,903 |
| CALLFLOW (read) | 0 / 100,469 | 0 / 103,232 | 0 / 79,078 | 0 / 56,106 |
| REFERENCES (search) | 0 / 60,132 | 0 / 66,404 | 0 / 61,087 | 0 / 65,682 |
| PREDICATE (search) | 0 / 62,938 | 0 / 47,726 | 0 / 63,979 | 0 / 57,643 |
| DEFINITION (lsp) | 0 / 60,299 | 0 / 49,753 | 0 / 56,384 | 0 / 72,666 |
| DIAGNOSTICS (lsp) | 0 / 30,890 | 0 / 112,064 | 0 / 84,438 | 0 / 134,845 |
| SCALE (routing) | 2 / 76,903 | 1 / 66,311 | 2 / 60,662 | 0 / 59,111 |
| EXPLICIT (routing) | 0 / 59,501 | 1 / 78,725 | 2 / 65,837 | 0 / 53,846 |

Paired token deltas per instance (10,000-sample bootstrap, seed 20260813):

| Pair (b − a) | Mean Δ tokens | CI95 | b > a |
| --- | ---: | ---: | ---: |
| A2 − A1 (block vs none) | +4,712 | [−1,954, +11,665] | 19 / 30 |
| A3 − A2 (block, same text twice) | −4,420 | [−9,856, +819] | 13 / 30 |
| A4 − A1 (no block, same text twice) | +1,791 | [−3,945, +7,641] | 12 / 30 |
| mean(A2, A3) − mean(A1, A4) | +1,607 | [−2,451, +5,788] | 16 / 30 |

Every pass in every arm is in `BUGFIX`, `SCALE` or `EXPLICIT`, and 6 to 10
records per arm fail with `invalid_final_json`: this model often leaves no
valid answer file, so it sits far below the 18 / 30 ceiling other models reach
on this corpus. Pass rate separates nothing (McNemar p = 1.0 for A1 vs A2,
0.25 for each same-text repeat). The rule written before A1 (A2 not below A1
on passes, and A2 − A1 tokens no larger than the A3 − A2 drift) failed
narrowly on both counts, 3 vs 4 passes and +4,712 against 4,420, while each
condition's own repeat moved as far (3 to 6 passes, 4 to 1 passes). Pooled over
both runs of each condition, the block passed 9 / 60 against 5 / 60 and its
token cost has a CI spanning zero, which meets the pooled rule: no measurable
effect either way, and the block is kept. Not measured: the composer block (no
fanout in this harness), efforts below `high` (the block does not fire there),
and any claim beyond this corpus. Records, manifests, the proxy and the
analysis scripts are archived outside git and linked from the pull request
that added this section.

Results describe this pinned corpus, OMH version, Hermes version, provider,
model id and conditions only. They do not establish universal model
superiority.

### 2026-10-30 round-end consistency check in `pre_verify`: off vs on, five measurements

Measurements 1 to 4 failed their gates. The owner then relaxed the token clause to 1.4x
("Owner decision" below). Measurement 5, with the sentinel swap, passed every clause it was
registered against. Each measurement is recorded below as it ran.

One question, from oh-my-pi's prewalk checklist and its delivery rules: after a turn
that edited code, does one short checklist at the first stop (consistency, scope,
verification) make the model's diff more correct? The checklist is
`ROUND_END_CHECKLIST` in `src/plugin_bundle/omh/hooks/verify_hooks.py`; `pre_verify`
returns it at `attempt == 0` when the turn's changed paths include a source file, so a
turn sees it at most once. No new tool.

The setup, fixed before the first live run:

- The pinned `E-BUGFIX` and `E-RENAME` templates, plus a new split `consistency-ab`
  (`--split consistency-ab`; the evaluation corpus and its digest are unchanged):
  - `C-DUPLICATE`: a cent-rounding bug in two copies of a helper. The task names the
    first copy's symptom; the second module says it is kept in step with the first.
    Fixing only the first scores `copy_not_updated`.
  - `C-SCOPE-TRAP`: a one-line duration bug next to an unused import and a size table
    whose `kib` entry looks wrong. Changing either scores `unrequested_edit`.
  - Both allow any new or changed file under `tests/`.
- 3 seeds each, 12 instances per model per arm, effort `medium`, condition `baseline`.
- Both arms: `--edit-directive`, `--git-init-workspace`, `--test-env`,
  `--harness hermes_current_session`, toolsets `file,terminal`.
- Two Hermes profiles that differ only in the OMH plugin bundle and OMH home: `off`
  links the bundle at origin/main `5cc1ed311` (the branch's base), `on` links this
  branch. The bundles differ only in `verify_hooks.py`. `agent.max_turns: 120` in both.
- Hermes runs from its own venv entry point (`~/.hermes/hermes-agent/.venv/bin/hermes
  -p <profile>`), not the `hermes` launcher. This does not make the bench timeout stop
  the turn: `--oneshot` is a client, and the turn runs in the one Hermes gateway that
  serves every profile. A runaway turn is bounded in the profile instead, by
  `agent.max_turns: 120` and `agent.run_budget_seconds: 600`.
- Subscription routes only: Claude through the local proxy (`claude-proxy`), GPT through
  Hermes `openai-codex`.

| Weak | Strong |
| --- | --- |
| `claude-haiku-4-5-20251001`, `claude-haiku-5-5`, `gpt-6-luna` | `claude-sonnet-5-5`, `claude-opus-5-5`, `gpt-6.1-sol` |

`gpt-6-luna` is the smallest model the Codex subscription served on 2026-10-30
(`gpt-6.1-sol`, `gpt-6-astra`, `gpt-6.1-terra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-*`).

The merge gate, fixed before the first live run. Runs are scored as in the sections
below: a run with no completed record is a fail.

- Total passes, all six models and both splits: on at least off + 3.
- Strong models: on at least off - 1.
- `mutation_outside_scope` count: on at most off.
- Median tokens per run over all runs: on at most 1.3x off. No on run above 3x the off
  median of its model and template.
- The checklist fired in at least 90% of on-arm coding sessions, and at most once per
  turn. A coding session is a completed on-arm session with a `patch` or `write_file`
  call on a `.py` path. Firing is read from the session database: an assistant row with
  `finish_reason = 'verify_hook_continue'`. These tasks touch no served surface and keep
  no plan, so a second such row in a session (a one-shot run is one turn) would be a
  repeat. The off arm is checked for zero such rows.

Measurement 1 (checklist text at `0c0e1c5e2`) failed one clause: on-arm median tokens
were 1.434x off (302,806 vs 211,211). Every other clause passed, with 66 on vs 57 off.
After the checklist the on arm ran pytest 62 times, in 49 of 72 sessions. For
comparison, the off arm ran it 24 times after its last code edit. The verification line
said "run a check". Measurement 2 (`185abfc78`) changes only that line: it asks for the
command already run after the last edit, and says to run one only if none was. It
re-runs both arms on two fresh profiles (`cebench-off2`, `cebench-on2`), with
`agent.run_budget_seconds: 600` set from the start. The gate does not change.

Measurement 2 passed every clause as written: omh `185abfc78` on origin/main `5cc1ed311`;
Hermes Agent v0.22.5 · stable · local bf0203a794a0; 144 of 144 run records, all
completed.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 9 / 12 | 9 / 12 | 252,983 | 266,655 |
| `claude-haiku-5-5` | 12 / 12 | 12 / 12 | 216,944 | 286,772 |
| `gpt-6-luna` | 8 / 12 | 8 / 12 | 178,550 | 276,370 |
| `claude-sonnet-5-5` | 10 / 12 | 12 / 12 | 171,288 | 231,342 |
| `claude-opus-5-5` | 12 / 12 | 12 / 12 | 208,235 | 248,666 |
| `gpt-6.1-sol` | 10 / 12 | 12 / 12 | 174,745 | 200,312 |
| **Total** | **61 / 72** | **65 / 72** | 14.9M total | 19.3M total |

Per template, off vs on: `E-BUGFIX` 17 vs 17, `E-RENAME` 18 vs 18, `C-DUPLICATE` 8 vs 12,
`C-SCOPE-TRAP` 18 vs 18. Failure codes: `copy_not_updated` 10 vs 6,
`mutation_outside_scope` 1 vs 1, `unrequested_edit` 0 vs 0.

Measurement 2 against the gate:

- Total, on at least off + 3: 65 vs 61.
- Strong models, on at least off - 1: 36 vs 32.
- `mutation_outside_scope`, on at most off: 1 vs 1.
- Median tokens, on at most 1.3x off: 247,577 vs 204,806, 1.21x. No on run above 3x its
  off pair's median.
- Fired in 71 of 72 on-arm coding sessions (98.6%), never twice in a session; 0 rows in
  the off arm.

Measurement 1, for the record (same setup, profiles `cebench-off`/`cebench-on`):

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 9 / 12 | 10 / 12 | 267,697 | 318,877 |
| `claude-haiku-5-5` | 10 / 12 | 12 / 12 | 236,284 | 365,807 |
| `gpt-6-luna` | 8 / 12 | 9 / 12 | 245,026 | 336,545 |
| `claude-sonnet-5-5` | 9 / 12 | 11 / 12 | 171,681 | 288,278 |
| `claude-opus-5-5` | 12 / 12 | 12 / 12 | 210,593 | 319,305 |
| `gpt-6.1-sol` | 9 / 12 | 12 / 12 | 173,697 | 199,080 |
| **Total** | **57 / 72** | **66 / 72** | 15.9M total | 22.0M total |

`C-DUPLICATE` went from 4 to 13; the other templates were even. During measurement 1
another session stopped the shared Hermes gateway (01:59:52 to 02:01:13 KST), which
interrupted every running turn and failed the next runs at launch. Every cell (model,
arm, template) with a run overlapping that window was moved aside and run again in full,
and `agent.run_budget_seconds: 600` was added to both profiles then.

**Neither measurement can ship the checklist.** An independent review found a defect
that the gate did not measure: the checklist displaced the turn's final answer. Hermes
keeps the answer the model stopped with only as an interim message, and returns
whatever the model says after the nudge as the turn's final response. That is the
response `--oneshot`, API and delegating callers receive. The checklist ended "say so in
one line and finish", so models finished with a report on the check. The bench missed
this because it grades the answer file. Read from the session databases, the last
assistant message contained the task's `changed_paths` answer in these sessions:

| | off | on |
| --- | ---: | ---: |
| Measurement 1 | 48 / 72 | 3 / 72 |
| Measurement 2 | 53 / 72 | 3 / 72 |

The token figures were also re-counted. The on arm ran pytest 62 times in 49 sessions
after the checklist in measurement 1, and 10 times in 10 sessions in measurement 2. The
off arm ran it 24 and 23 times after its last code edit. Counted by `session_counts.py`.
A sentence in earlier commits said "62 of 72 sessions": that was the number of calls,
not of sessions.

What measurements 1 and 2 show, and what they do not:

- The pass margin is inside noise. The off arm ran identical code both times and moved
  from 57 to 61. Measurement 2's 65 vs 61 alone has a two-sided Fisher exact p of 0.45,
  and measurement 1's 66 vs 57 has 0.057. Pooled over both, the totals are 131 vs 118 of
  144 (p = 0.038).
- The one effect that stands out is `C-DUPLICATE`: pooled, 25 vs 12 of 36 (p = 0.004).
  A model fixed a second copy of the logic that the task did not name, after searching
  for other uses: `search_files` and `read_file` were most of the 1.8 extra calls per
  session in measurement 2.
- `C-DUPLICATE` plants exactly the defect the checklist names, and the corpus had no
  negative case for it. Measurement 3 adds one (`C-DECOY`, below).
- Scope did not move. No model took the `C-SCOPE-TRAP` bait in either arm. The one
  `mutation_outside_scope` in each arm is `gpt-6-luna` on the same `E-BUGFIX` seed.
- Weak models gained in measurement 1 (27 to 31) and not in measurement 2 (29 to 29).
  Strong models gained in both (30 to 35, 32 to 36). n = 12 per model per arm.
- The one measurement-2 coding session without the checklist (opus, `E-BUGFIX`) was
  dropped by Hermes, not by OMH. The profile log reads "Hook 'pre_verify' callback
  pre_verify skipped after previous timeout or while still running". `pre_verify` has no
  entry in `_HOOK_CALL_IDENTITY_FIELDS` (`hermes_cli/plugins_dispatch.py`). So two
  sessions of one profile that reach the hook at the same moment share one gate key, and
  the second call is skipped.

#### Measurement 3, pre-registered before its first run

Changes from measurement 2:

- The checklist's last line now asks for the final answer to the task again, in full and
  in the form the task asked for, because it replaces the answer just given. It also
  says not to answer with a report on the check.
- Delegated children (`platform == "subagent"`) get no checklist.
- New template `C-DECOY`, the negative case for `C-DUPLICATE`. It has the same rounding
  bug in one module, next to a look-alike helper whose half-to-even rounding is
  required, documented, and pinned by a test. Changing the look-alike's code scores
  `decoy_changed`.
- 5 templates × 3 seeds = 15 runs per model per arm, 90 per arm. Same panel, same flags,
  subscription routes only. Fresh profiles `cebench-off3` and `cebench-on3`, both with
  `agent.max_turns: 120` and `agent.run_budget_seconds: 600`.

The gate keeps every clause above unchanged, now over 90 runs per arm, and adds two:

- Final answer kept: the number of runs whose last assistant message contains
  `changed_paths` is, in the on arm, at least the off arm's minus 2. It is read from the
  session databases.
- `C-DECOY`: on at least off - 1.

If measurement 3 fails a clause, it is recorded here and the checklist does not merge.

#### Measurement 3 result: gate failed, the checklist does not merge

omh `4f5c4a053` on origin/main `5cc1ed311`, Hermes Agent v0.22.5 · stable · local
bf0203a794a0. 180 of 180 run records, all completed. No gateway outage.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 12 / 15 | 12 / 15 | 238,984 | 388,392 |
| `claude-haiku-5-5` | 15 / 15 | 15 / 15 | 243,744 | 284,464 |
| `gpt-6-luna` | 12 / 15 | 13 / 15 | 217,959 | 326,159 |
| `claude-sonnet-5-5` | 13 / 15 | 15 / 15 | 171,075 | 243,310 |
| `claude-opus-5-5` | 15 / 15 | 15 / 15 | 208,441 | 280,784 |
| `gpt-6.1-sol` | 14 / 15 | 15 / 15 | 173,835 | 218,535 |
| **Total** | **81 / 90** | **85 / 90** | 19.0M total | 27.2M total |

Per template, off vs on: `E-BUGFIX` 18 vs 17, `E-RENAME` 18 vs 18, `C-DUPLICATE` 9 vs 15,
`C-SCOPE-TRAP` 18 vs 17, `C-DECOY` 18 vs 18.

The gate:

- Total, on at least off + 3: 85 vs 81. Pass.
- Strong models, on at least off - 1: 45 vs 42. Pass.
- `mutation_outside_scope`, on at most off: 1 vs 0. **Fail.** The one run was
  `claude-haiku-4-5-20251001`, `E-BUGFIX`.
- Median tokens, on at most 1.3x off: 281,158 vs 207,898, 1.35x. **Fail.**
- No on run above 3x its off pair's median. **Fail, two runs:** `gpt-6-luna`
  `E-RENAME` (3.20x) and `C-DECOY` (3.19x).
- Fired in at least 90% of coding sessions, at most once per turn: 90 / 90, never
  twice; 0 rows in the off arm. Pass.
- Final answer kept, on at least off - 2: 90 / 90 vs 58 / 90. Pass.
- `C-DECOY`, on at least off - 1: 18 vs 18. Pass.

What measurement 3 shows:

- The final-answer line works. Every on-arm run ended on a message carrying the task's
  answer, which is more than the off arm, where models often end with prose.
- It costs tokens again. Told to give the answer "again, in full", models re-ran their
  tests before answering: 48 pytest runs in 46 of 90 sessions after the checklist,
  against 10 in 10 of 72 in measurement 2. The off arm had 26 after its last code
  edit. Counted by `session_counts.py`. Median tokens went from 1.21x to 1.35x.
- The decoy did not catch a false consistency fix. No model changed the documented
  half-to-even look-alike in either arm. So the `C-DUPLICATE` gain is not this
  checklist making models change look-alike code blindly. This corpus has one decoy
  shape only.
- Scope moved the wrong way, at n = 1 each: one on-arm `mutation_outside_scope`
  (haiku-4-5, `E-BUGFIX`). There was also one on-arm `unrequested_edit` (`gpt-6-luna`,
  `C-SCOPE-TRAP`), where the off arm had none. Neither is established as caused by the
  checklist.
- `C-DUPLICATE` is still the only effect that stands out: 9 vs 15 here (p = 0.075).
  Pooled over the three measurements it is 21 vs 40 of 54 (two-sided Fisher exact
  p = 0.0004). The total margin, 85 vs 81, has p = 0.40.

The checklist branch stays unmerged. Changing the wording again (for example, asking
for the answer without re-running checks) needs the owner's decision and a new
pre-registered measurement.

#### Measurement 4, pre-registered before its first run (the last one)

This is the fourth measurement of this feature family against one gate, so a pass
should be read with that in mind. The owner chose a fourth and final attempt. If it
fails any clause, the PR closes and there is no fifth.

The feature is narrower, not reworded. Only the consistency check holds across
measurements: `C-DUPLICATE`, pooled over measurements 1 to 3, is 40 vs 21 of 54. The
scope and verification lines showed no effect, and the "check again" and "answer again
in full" wording drove the token cost through test re-runs. So the continuation now
carries one check: look for other copies or call sites of the logic changed this turn
that have to change with it, and fix any found. It also says:

- do not re-run tests or re-check anything else;
- restate the final answer exactly as given, in the form the task asked for, updated
  only if something more changed;
- give no report on this check.

The subagent skip stays.

The setup is that of measurement 3:

- the same panel and the same five templates (including `C-DECOY`), 15 runs per model
  per arm;
- subscription routes only;
- fresh profiles `cebench-off4` and `cebench-on4`, each with `agent.max_turns: 120` and
  `agent.run_budget_seconds: 600`.

The gate is the same eight clauses with unchanged thresholds:

- Total: on at least off + 3.
- Strong models: on at least off - 1.
- `mutation_outside_scope`: on at most off.
- Median tokens: on at most 1.3x off.
- No on run above 3x the off median of its model and template.
- The check fires in at least 90% of on-arm coding sessions, and at most once per turn.
- Final answer kept: on at least off - 2.
- `C-DECOY`: on at least off - 1.

The result is reported here with pooled `C-DUPLICATE` over all four measurements.

#### Measurement 4 result: gate failed, item closed

omh `530068797` on origin/main `5cc1ed311`, Hermes Agent v0.22.5 · stable · local
bf0203a794a0. 180 of 180 run records, all completed.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 12 / 15 | 15 / 15 | 268,730 | 318,424 |
| `claude-haiku-5-5` | 15 / 15 | 15 / 15 | 243,538 | 302,141 |
| `gpt-6-luna` | 12 / 15 | 14 / 15 | 241,621 | 306,662 |
| `claude-sonnet-5-5` | 13 / 15 | 15 / 15 | 172,363 | 246,287 |
| `claude-opus-5-5` | 15 / 15 | 15 / 15 | 207,843 | 283,440 |
| `gpt-6.1-sol` | 14 / 15 | 15 / 15 | 174,484 | 216,839 |
| **Total** | **81 / 90** | **89 / 90** | 19.5M total | 25.9M total |

Per template, off vs on: `E-BUGFIX` 18 vs 17, `E-RENAME` 18 vs 18, `C-DUPLICATE` 9 vs 18,
`C-SCOPE-TRAP` 18 vs 18, `C-DECOY` 18 vs 18.

The gate:

- Total, on at least off + 3: 89 vs 81. Pass.
- Strong models, on at least off - 1: 45 vs 42. Pass.
- `mutation_outside_scope`, on at most off: 1 vs 0. **Fail.** The one run was
  `gpt-6-luna`, `E-BUGFIX`.
- Median tokens, on at most 1.3x off: 280,668 vs 207,804, 1.35x. **Fail.**
- No on run above 3x its off pair's median. Pass.
- Fired in at least 90% of coding sessions, at most once per turn: 90 / 90, never
  twice; 0 rows in the off arm. Pass.
- Final answer kept, on at least off - 2: 89 / 90 vs 61 / 90. Pass.
- `C-DECOY`, on at least off - 1: 18 vs 18. Pass.

What the four measurements show together:

- **Consistency is a real effect on this corpus.** `C-DUPLICATE` was 18 vs 9 in
  measurement 4 (two-sided Fisher exact p = 0.001). Pooled over all four measurements it
  is 58 vs 30 of 72 (p < 0.0001). This is the fourth measurement of one feature family,
  and the template plants exactly the miss the check names. `C-DECOY` (18 vs 18 in
  measurements 3 and 4) shows the check did not make models change a documented
  look-alike. It is one decoy shape.
- **The cost does not come from re-running tests.** The consistency-only text stopped
  test re-runs entirely: 0 pytest calls after the check, against 48 in measurement 3.
  Median tokens still rose 1.35x. The cost is the extra round itself: about two more
  model calls, each re-sending the whole context, to search for other uses and restate
  the answer. On these short tasks, about 200k tokens each, that round is a large
  fraction. No wording change removes it.
- **Scope failed at n = 1 in measurements 3 and 4, a different model each time.** Each
  was one on-arm `mutation_outside_scope` on `E-BUGFIX`, against none off. Whether the
  extra round causes stray edits is not established.
- Weak models gained 39 to 44 and strong 42 to 45 in measurement 4.

Item B closes here, unmerged, as the owner decided before the run. The code stays on
branch `feature/round-end-checklist` (`530068797`). A future attempt would need a gate
that prices the extra round differently, or a cheaper way to ask for the check than a
continuation. Either is a new decision for the owner.

The owner later reversed this. See "Owner decision, 2026-10-30 (after measurement 4)" below.

#### Owner decision, 2026-10-30 (after measurement 4)

After measurement 4, the owner relaxed the median-token clause from 1.3x to 1.4x and chose
to merge the measurement-4 design, the consistency-only check at `530068797`. The owner gave
these reasons:

- The runs go through subscription routes.
- Measurement 4 gained 8 passes in total (89 vs 81), and `C-DUPLICATE` went from 9 to 18.
- Pooled over all four measurements, `C-DUPLICATE` is 58 vs 30 of 72 (two-sided Fisher
  exact p of about 3e-6).
- The decoy was even, 18 vs 18.
- The final answer was kept in 89 of 90 runs.

This does not mean measurement 4 passed the gate it was registered against. It did not:
it failed the token clause (1.35x against 1.3x) and the scope clause. Against the relaxed
gate, measurement 4 passes every clause except scope. That is `mutation_outside_scope` 1 vs
0, one `gpt-6-luna` `E-BUGFIX` run, and its cause is not established. The owner accepted
that miss with the merge. The thresholds above and the measurement records are unchanged.

#### Measurement 5, pre-registered before its first run

A second review of the measurement-4 design, after the owner decision, found two
conflicts in the joined message.

- **The served-surface gate.** Its "run the smallest real load or check" request
  sat beside the check's "do not re-run tests or re-check anything else".
- **The open-plan directive.** It sat beside "restate your final answer".

The owner chose a fix and one more measurement, merging if it passes. Measurement
5 is the fifth measurement of this feature family. The changes from measurement 4:

- **The check is scoped.** It now says "Do not re-run tests for this check", and a
  served-surface request beside it stands.
- **One closing sentence.** It goes last, and only when no plan directive is open.
  With an open plan the message has no closing and nothing is stashed. The order is
  served-surface gate, consistency check, plan directive, closing. #2410's impact
  note goes between the gate and the check once it lands.
- **The sentinel.**
  - The closing asks for one fixed line, `OMH: no further changes.`, when nothing
    more changed, or the full updated answer otherwise.
  - `pre_verify` stashes the answer the turn stopped with, in process, per session,
    bounded and aged out.
  - `transform_llm_output` swaps the sentinel back to that answer before Hermes
    persists the final row, and clears the stash on every turn end. It never swaps
    without a stash.
- **The OMH TUI** keeps the streamed sentinel line instead of printing the restored
  answer a second time.

The setup is that of measurement 4, on fresh profiles `cebench-off5` and
`cebench-on5`: the same panel, the same five templates including `C-DECOY`, 15 runs
per model per arm, subscription routes only, `agent.max_turns: 120` and
`agent.run_budget_seconds: 600`.

The gate keeps the measurement-4 clauses, with the token clause at the owner's 1.4x.
The scope clause is stated as registered, and its result is reported as measured.

- Total: on at least off + 3.
- Strong models: on at least off - 1.
- `mutation_outside_scope`: on at most off.
- Median tokens: on at most 1.4x off.
- No on run above 3x the off median of its model and template.
- The check fires in at least 90% of on-arm coding sessions, and at most once per
  turn.
- Final answer kept: the last assistant message contains `changed_paths`, on at
  least off - 2.
- `C-DECOY`: on at least off - 1.
- Swap fidelity, new.
  - Read from the session DB: in every on-arm session where the sentinel was used,
    the persisted final answer equals the pre-check answer byte for byte.
  - Both rows are persisted: the pre-check answer is the interim row with
    `finish_reason = 'verify_hook_continue'`, and the final answer is the last
    assistant row.
  - The model's raw reply is not stored once swapped. So a session counts as having
    used the sentinel when its final row equals its interim row byte for byte, or
    when its final row is still the sentinel line.
  - The clause fails if any session's final row is the sentinel line (a swap that
    did not happen).

The result is reported here, with pooled `C-DUPLICATE` over all five measurements.
If measurement 5 fails a clause, it is recorded and there is no further iteration.

#### Measurement 5 result: every clause passes

omh `b707b6281` on origin/main `4b7674616`, Hermes Agent v0.22.5 · stable · local
bf0203a794a0. 180 of 180 run records, all completed. A three-run smoke on a separate
profile (`cebench-smoke5`) checked the swap before the run, and is not counted here.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 12 / 15 | 15 / 15 | 268,044 | 388,258 |
| `claude-haiku-5-5` | 15 / 15 | 15 / 15 | 216,739 | 317,480 |
| `gpt-6-luna` | 10 / 15 | 15 / 15 | 226,839 | 335,894 |
| `claude-sonnet-5-5` | 14 / 15 | 15 / 15 | 172,393 | 248,950 |
| `claude-opus-5-5` | 15 / 15 | 15 / 15 | 208,639 | 280,572 |
| `gpt-6.1-sol` | 12 / 15 | 15 / 15 | 174,684 | 217,182 |
| **Total** | **78 / 90** | **90 / 90** | 19.3M total | 26.7M total |

Per template, off vs on: `E-BUGFIX` 16 vs 18, `E-RENAME` 18 vs 18, `C-DUPLICATE` 8 vs 18,
`C-SCOPE-TRAP` 18 vs 18, `C-DECOY` 18 vs 18. Failure codes: off has `copy_not_updated`
10 and `mutation_outside_scope` 2; on has none.

The gate:

- Total, on at least off + 3: 90 vs 78. Pass.
- Strong models, on at least off - 1: 45 vs 41. Pass.
- `mutation_outside_scope`, on at most off: 0 vs 2. Pass.
- Median tokens, on at most 1.4x off: 283,865 vs 206,990, 1.37x. Pass.
- No on run above 3x its off pair's median. Pass.
- Fired in at least 90% of coding sessions, at most once per turn: 90 / 90, never twice;
  0 rows in the off arm. Pass.
- Final answer kept, on at least off - 2: 67 / 90 vs 61 / 90. Pass.
- `C-DECOY`, on at least off - 1: 18 vs 18. Pass.
- Swap fidelity: 67 sessions used the sentinel and their final row equals the pre-check
  answer byte for byte; 0 final rows are still the sentinel line. Pass.

What it shows, and what it does not:

- **`C-DUPLICATE` is 18 vs 8** (two-sided Fisher exact p = 0.0003). Pooled over all five
  measurements it is 76 vs 38 of 90 (p ≈ 5e-9). That is five measurements of one feature
  family, and the template plants exactly the miss the check names. `C-DECOY` stayed
  even in all three measurements that had it.
- **Weak models gained most:** 37 to 45. Strong models went from 41 to 45.
- **Tokens are 1.37x** the off median, with no test re-runs after the check (0 calls).
  The cost is the extra round itself. Measured only on these short tasks of about 200k
  tokens; whether long turns pay proportionally less is not measured.
- **A residual, inside the gate.** In 23 on-arm sessions the model did not use the
  sentinel. For 11 of them the final answer was an updated answer that carried
  `changed_paths`: 8 from gpt-6-luna, gpt-6.1-sol, sonnet and haiku-5-5, and 3 from
  haiku-4-5. For 12 of the 15
  `claude-haiku-4-5-20251001` sessions it was a report on the check ("No other call
  sites exist ...") rather than the answer. So that model's final response is still
  displaced. The final-answer clause passes because, read by `changed_paths`, the off
  arm also often ends on prose.
- **Swap fidelity is read from the DB only.** The model's raw reply is not stored once
  swapped, so "the sentinel was used" is inferred from final == pre-check byte for byte.

Measurement 5 passed the gate registered for it at `b707b6281`. The owner decided to
merge if it passed.

After measurement 5, a review changed the stash lifecycle. That is why the description
above, written for `b707b6281`, no longer matches the shipped code.

- The stash is now consumed only by a sentinel match. A non-sentinel
  `transform_llm_output` no longer clears it, because Hermes's background-review fork
  shares the session id and could otherwise take it.
- A leftover stash is cleared at the session's next turn start (`pre_llm_call`).
- The sentinel also matches when wrapped in `**`, `*`, `_`, backticks or quotes, or
  written without its period.
- A delegated child that gets only the impact note is asked for its full answer, and
  nothing is stashed for it.
- The OMH TUI dedupes only when Hermes marks the reply `response_transformed`.

None of these changes the measured path: no review fork ran in these one-shot bench
sessions, and no bench run is a delegated child. Measurement 5 was not re-run.

Pass counts come from the run records. Firing, final answers and tool calls come from
each profile's session DB.
### 2026-10-30 impact check: callers broken by an edit, off vs on (`impact_check` + `lsp_diagnostics`), gate passed

One question, from oh-my-pi's workspace diagnostics: when an edit changes a definition, does
telling the model which files that import it now have new type errors help it fix every caller?
Hermes checks diagnostics only for the file an edit wrote.

How the check works (opt-in, setting `impact_check` or env `OMH_IMPACT_CHECK`): on the turn's
first `patch` / `write_file` of an existing `.py` file, `pre_tool_call` finds up to 30 workspace
files that import it (an `ast` import scan, following one package re-export) and records their
language-server errors. At the turn's first stop, `pre_verify` re-checks those files against the
disk and, when an error appeared that the baseline did not have, continues the turn with at most
15 lines of `path:line: message`. It says nothing otherwise. `lsp_diagnostics(path|glob)` joins the
opt-in `omh-lsp` toolset so the model can re-check.

The setup:

- Split `impact-ab` (`--split impact-ab`; the evaluation corpus and its digest are unchanged),
  four templates, 3 seeds each, 12 instances per model per arm. Only the edited module has a test
  in the workspace; the controller exercises every caller in a fresh interpreter.
  - `I-SIGNATURE`: a required parameter added to a function called directly, through an alias,
    through the module and through a package re-export under another name.
  - `I-RETURN-SHAPE`: a dict return turned into a frozen dataclass, read by key in three modules
    (alias, module attribute, `.get`).
  - `I-KWARG`: a keyword-only parameter renamed; one caller passes it through `**options`, which
    a type checker cannot see, one through a module alias.
  - `I-CONTROL`: an edit that breaks no caller, next to an importer with an unrelated
    pre-existing type error. The check must stay silent.
- Both arms: `--edit-directive` (the patch rule, byte-identical in both arms),
  `--git-init-workspace`, `--test-env`, effort `medium`. Arm `off` is `--edit-surface patch`
  (toolsets `file,terminal`); arm `on` is `--edit-surface impact` (toolsets
  `file,terminal,omh-lsp`, profile settings `impact_check: true` and `lsp_tools: true`, so the
  four `omh-lsp` tools are listed). Two profiles that differ only in those settings, the toolset
  and the OMH home; `agent.max_turns: 120` and `tools.tool_search` off in both.
- Subscription routes only. Claude through the local CPA proxy (`claude-proxy`), GPT through
  Hermes `openai-codex`. Weak: `claude-haiku-4-5-20251001`, `claude-haiku-5-5`, `gpt-5.6-luna`
  (the smallest model the Codex subscription served on 2026-10-30). Strong: `claude-sonnet-5-5`,
  `claude-opus-5-5`, `gpt-6.1-sol` (the Codex flagship).

The merge gate, fixed here before the first live run:

- Weak models, on at least off + 3 (summed over the three weak models).
- Strong models, on at least off - 1 (summed over the three strong models).
- No on-arm run above 3x its pair's median tokens (the off arm's median for the same model and
  template).
- The note fired in at least half of the on-arm sessions with a broken caller. Over the three
  edit templates, a session counts as having a broken caller when the note fired or its final
  tree still fails the controller's check; a note "fired" when the profile's log has an
  `impact_check round_end` line for the session with `new_errors` above 0.
- 0 notes on `I-CONTROL`.
- Added round-end latency, p95 of the check's own time at `pre_verify` (the `ms` of the same log
  line), at most 20 s.

A failed clause means the feature does not merge; the result is recorded here as the DAP run was.

Amendment, fixed before run 2 (below) and after run 1. When `pre_verify` continues a turn, Hermes
keeps the answer the model already gave only as an interim message
(`agent/turn_stop_gates.py`), and whatever the model says after the note becomes the turn's final
answer: the `--oneshot` or API result, or a delegated child's return. Run 1's note ended on a
request to re-check, and models answered it with a report about the fix. The note now ends by
asking for the task's final answer again, in full, and the gate gains a seventh clause:

- Final answer preserved after a note: over the on-arm sessions of the three edit templates where
  the note fired, the number whose last assistant message (read from the session database)
  contains the task's requested answer, a JSON object with `changed_paths`, is at least
  round(p x n) - 2. Here n is the number of those sessions and p is the share of off-arm sessions of
  the same three templates whose last assistant message contains it.

The other six clauses are unchanged.

Amendment 2, fixed before run 3 and after run 2. A second review changed the measured path:
- Each check's time is now a share of the profile's `plugins.hook_callback_timeout`. That is 8 s
  and 10 s at the default 30 s, and the check is skipped when its share would be under 2 s.
- The importer scan stops at that deadline.
- A session with no language server is skipped before the scan.
- Module names that shadow the standard library are not matched, and names count from the
  checkout when the session starts in a sub-directory.
- Hermes tells hooks nothing about a session's toolsets, so the note now names `lsp_diagnostics`
  only as optional ("if your tools include it").
- The note's header says that another writer's changes would show up too.
The seven clauses are unchanged. Run 3, on the plugin with these changes, is the reported result;
runs 1 and 2 stay recorded below.

Run 3, plugin `de9ddab71` (reported). Every clause passes, so the check ships, off by default.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 8 / 12 | 12 / 12 | 291,260 | 353,263 |
| `claude-haiku-5-5` | 11 / 12 | 12 / 12 | 219,708 | 225,544 |
| `gpt-5.6-luna` | 9 / 12 | 11 / 12 | 145,068 | 175,135 |
| `claude-sonnet-5-5` | 12 / 12 | 12 / 12 | 178,670 | 180,781 |
| `claude-opus-5-5` | 12 / 12 | 12 / 12 | 214,839 | 220,788 |
| `gpt-6.1-sol` | 12 / 12 | 12 / 12 | 135,548 | 149,799 |
| **Total** | **64 / 72** | **71 / 72** | 14.6M | 16.6M |

Per template, off vs on: `I-SIGNATURE` 11 vs 18, `I-RETURN-SHAPE` 18 vs 18, `I-KWARG` 17 vs 17,
`I-CONTROL` 18 vs 18.

- Weak models, on at least off + 3: 35 vs 28, pass.
- Strong models, on at least off - 1: 36 vs 36, pass.
- No on-arm run above 3x its pair's median tokens: none; the highest is 2.22x (haiku 4.5
  `I-SIGNATURE`).
- The note fired in 10 of the 11 on-arm sessions with a broken caller, pass (9 `I-SIGNATURE`,
  1 `I-KWARG`); every session that got a note ended passing. The one broken session without a
  note is gpt-5.6-luna `I-KWARG`.
- Notes on `I-CONTROL`: 0, pass.
- Round-end latency p95 139 ms (max 354 ms) over the 65 sessions that reached a round-end check,
  pass.
- Final answer preserved after a note: 6 of 10, against round(28 / 54 x 10) - 2 = 3, pass.
- First-edit baseline: median 0.4 s, p90 2.9 s, max 9.4 s. In 7 of 72 sessions the server gave no
  verdict for any importer within the 8 s share, so the baseline recorded nothing and the round
  end had nothing to check (those 7 sessions all passed). The full test suite was running on the
  same machine during this run; run 2, without it, had a baseline max of 0.9 s. The overrun past 8 s
  is the bridge's 2 s loop margin, well inside the 30 s host timeout.
- Tools in the on arm: `lsp_diagnostics` 20 calls, no other `lsp_*` tool. The off arm made none.
- omh `de9ddab71`, Hermes Agent v0.22.5 (`bf0203a794`), fresh on/off profile pair per model,
  2026-10-30 10:58-11:24 KST (run 3 pre-registered in `de9ddab71`, committed 10:58:16; first
  run started 10:58:24). 144 of 144 records completed, none failed, timed out or was retried.

What the gain covers. All of it is on `I-SIGNATURE`. There were 23 off-arm `I-SIGNATURE` failures
across the three runs (8, 8 and 7), and every one of them missed the caller that reaches the
function through a renamed package re-export (`cli.py`: `from benchapp import fee`). Four of them
also missed the alias caller: 1 in run 2, and 3 in run 3, all haiku 4.5. None missed the direct or
module-attribute caller. The importer scan's unit test, written in the same change, covers the
same shape. So the measured outcome gain is for callers reached through a renamed re-export, and
in a few weak-model sessions for an aliased import. The other templates did not separate the arms.

Run 2, plugin `41e91a195` (superseded by run 3). Every clause passed:

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 7 / 12 | 10 / 12 | 311,080 | 362,475 |
| `claude-haiku-5-5` | 10 / 12 | 12 / 12 | 221,306 | 225,507 |
| `gpt-5.6-luna` | 9 / 12 | 12 / 12 | 145,850 | 182,656 |
| `claude-sonnet-5-5` | 12 / 12 | 12 / 12 | 174,693 | 182,988 |
| `claude-opus-5-5` | 12 / 12 | 12 / 12 | 215,642 | 220,399 |
| `gpt-6.1-sol` | 12 / 12 | 12 / 12 | 148,557 | 173,769 |
| **Total** | **62 / 72** | **70 / 72** | 14.2M | 16.8M |

Per template, off vs on: `I-SIGNATURE` 10 vs 18, `I-RETURN-SHAPE` 18 vs 18, `I-KWARG` 16 vs 16,
`I-CONTROL` 18 vs 18.

- Weak models, on at least off + 3: 34 vs 26, pass.
- Strong models, on at least off - 1: 36 vs 36, pass.
- No on-arm run above 3x its pair's median tokens: none; the highest is 2.20x (gpt-6.1-sol
  `I-KWARG`).
- The note fired in 12 of the 14 on-arm sessions with a broken caller, pass (9 `I-SIGNATURE`,
  1 `I-RETURN-SHAPE`, 2 `I-KWARG`); every session that got a note ended passing. The two broken
  sessions without one are haiku 4.5 `I-KWARG`, the `**options` caller.
- Notes on `I-CONTROL`: 0, pass.
- Round-end latency p95 48 ms (max 71 ms) over 72 sessions, pass; the first-edit baseline added
  p95 0.5 s (max 0.9 s).
- Final answer preserved after a note: 8 of 12, against round(31 / 54 x 12) - 2 = 5, pass. In run 1,
  whose note ended on "re-check", it was 1 of 10.
- Tools in the on arm: `lsp_diagnostics` 20 calls, `lsp_references` 4 (haiku 5.5),
  `lsp_definition` and `lsp_rename` none. The off arm made no `lsp_*` calls.
- omh `41e91a195`, Hermes Agent v0.22.5 (`bf0203a794`), fresh on/off profile pair per model,
  2026-10-30 02:59-03:17 KST; 144 of 144 records completed, none failed, timed out or was retried.

Run 1, plugin as of `c5e4fc02c` (note without the final-answer request; superseded by run 2). Six
clauses passed; the seventh did not exist yet:

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 8 / 12 | 11 / 12 | 296,656 | 384,301 |
| `claude-haiku-5-5` | 11 / 12 | 12 / 12 | 223,303 | 225,588 |
| `gpt-5.6-luna` | 9 / 12 | 12 / 12 | 144,621 | 159,372 |
| `claude-sonnet-5-5` | 11 / 12 | 12 / 12 | 166,064 | 179,680 |
| `claude-opus-5-5` | 12 / 12 | 12 / 12 | 216,821 | 221,162 |
| `gpt-6.1-sol` | 12 / 12 | 12 / 12 | 156,092 | 174,620 |
| **Total** | **63 / 72** | **71 / 72** | 14.2M | 16.2M |

Per template, off vs on: `I-SIGNATURE` 10 vs 18, `I-RETURN-SHAPE` 18 vs 18, `I-KWARG` 17 vs 17,
`I-CONTROL` 18 vs 18. All of the gain is on the signature change (haiku 4.5 and gpt-5.6-luna
0 / 3 each in the off arm).

- Weak models, on at least off + 3: 35 vs 28, pass.
- Strong models, on at least off - 1: 36 vs 35, pass.
- No on-arm run above 3x its pair's median tokens: none; the highest is 1.74x (gpt-6.1-sol
  `I-KWARG`).
- The note fired in 10 of the 11 on-arm sessions with a broken caller, pass. Seven
  `I-SIGNATURE` notes and three `I-KWARG` notes; every session that got a note ended passing.
  The one broken session without a note is haiku 4.5 `I-KWARG`, whose remaining break was the
  caller passing the keyword through `**options`, which the type checker cannot see.
- Notes on `I-CONTROL`: 0, pass. The importer with the pre-existing type error was not reported.
- Round-end latency: p95 1.4 s, max 1.9 s over 72 sessions, pass. The baseline at the first
  edit (`pre_tool_call`) added p95 1.6 s, max 4.0 s.

What it shows, and what it does not:

- The on arm lists the four `omh-lsp` tools. Over the scored sessions, `lsp_diagnostics` was called
  17 times, `lsp_references` 3 times (haiku 5.5), and
  `lsp_definition` / `lsp_rename` never. No off-arm session called an `lsp_*` tool.
- A first full run was stopped at 73 of 144 records and is not reported: its probe ran each
  workspace test file with a bare `runpy`, so a correct gpt-6.1-sol `I-RETURN-SHAPE` edit whose new
  test imported pytest was scored as a fail in both arms. impact-ab now checks the definition and
  every caller and leaves the model's own tests to the model; the matrix was rerun in full. The
  gate was not changed.
- The run used omh `feature/lsp-impact-check` `29940f8a5` (plugin code as of `c5e4fc02c`) on
  origin/main `5cc1ed311`, Hermes Agent v0.22.5 (`bf0203a794`), one on/off profile pair per model,
  6 models in parallel, 2026-10-30 02:02-02:26 KST. 144 of 144 records completed; none failed,
  timed out or was retried.
- After run 1, an independent review changed the plugin (`985bec3c3`). The baseline now fits
  the host hook timeout, state does not carry across turns, bare module names no longer match the
  standard library, and deleted modules are not baselined. Under the new rules the impact-ab
  importers resolve the same: 6 per `I-SIGNATURE` instance and 4 per `I-CONTROL` instance. A live
  re-smoke on that commit (haiku 4.5, on arm, 6 runs) passed 3 / 3 `I-SIGNATURE`, with a note in
  each, and 3 / 3 `I-CONTROL` with no note. The table above is from the plugin as of `c5e4fc02c`.
- Python and pyright only. The type checker cannot follow `**options`, `getattr` or string
  dispatch, so those callers still break silently. A deleted or moved module is not checked.
  n = 12 per model per arm.

### 2026-10-30 big files: read outline off vs on (`bigfile-ab`), gate failed

Status: the gate failed and the feature did not merge (PR #2408, draft, branch `feature/read-outline`). The outline code, the `bigfile-ab` split, `lib/bigfile.py` and `tests/test_read_outline.py` exist only on that branch, not on main; the commands and file names below refer to the branch, and this section records the measurement only.

One question, from oh-my-pi's read summary: when a `read_file` result is truncated, does
appending an outline of the whole file (classes, functions and methods with their line ranges)
let the model jump to the right offset instead of paging? OMH's version (on the branch) appends and never cuts:
`src/plugin_bundle/omh/read_outline.py`, Python only (stdlib `ast`), once per file version per
session, at most 60 lines, for files of at least 400 lines.

The setup, fixed before the first live run:

- Split `bigfile-ab` (branch only; `--split bigfile-ab`, `lib/bigfile.py`; the evaluation corpus and its
  digest are unchanged). One generated module, `src/benchapp/tariffs.py`, of 4,750-5,030 lines
  (past both of Hermes' read limits: 2,000 lines and 100,000 characters). Two templates, 3 seeds
  each, 6 instances per model per arm:
  - `B-DEEP-BUG`: a pricing helper defined past line 3,000 has an off-by-one threshold. The
    task names the failing test and the symptom ("a shipment of exactly N pieces is quoted as if
    it got no crate discount"), never the helper, the module path or the line. Graded on hidden
    quotes from the correct module, so editing the test does not pass.
  - `B-DEEP-RENAME`: rename a public function defined past line 3,000, used near the top of the
    module, deep in it, in a second module and in the tests, next to a same-named method, a log
    string and a comment that must stay. Graded by AST plus behaviour.
- Both arms: no edit directive, `--git-init-workspace`, `--test-env`, effort `medium`, toolsets
  `file,terminal`. Two profiles that differ only in `plugins.entries.omh.settings.read_outline`
  (`true` / `false`) and the OMH home; `agent.max_turns: 120`; `tools.tool_search` off.
  `OMH_READ_OUTLINE` is unset in the run environment.
- Subscription routes only. Weak: `claude-haiku-4-5-20251001`, `claude-haiku-5-5` (Hermes
  provider `claude-proxy`, the local CPA at `http://127.0.0.1:8317/v1`) and `gpt-5.6-luna`
  (Hermes provider `openai-codex`). Strong: `claude-sonnet-5-5`, `claude-opus-5-5`
  (`claude-proxy`) and `gpt-6.1-sol` (`openai-codex`). Both Codex ids answered a one-word probe
  through the off profile on 2026-10-30; the subscription also serves `gpt-6-luna`, and the
  older-generation small tier, `gpt-5.6-luna`, is the weak model. Condition `baseline` (no
  family calibration), as in the sections below.
- Hermes runs through `~/.hermes/hermes-agent/.venv/bin/python -m hermes_cli.main -p <profile>`,
  never the `hermes` launcher. `--oneshot` is a client of the host gateway, which runs the turn
  and loads each profile's plugins (reloaded for both profiles after they were configured), so
  the harness timeout only detaches the client. After every run that did not complete, the
  driver sends the gateway `session.interrupt` (the RPC behind the chat client's `/stop`) for
  that run's sessions; a smoke check stopped a detached turn this way.

The merge gate, written before the first live run:

- Weak models, on at least off + 3 passes (of 18 per arm).
- Strong models, on at least off - 1 passes (of 18 per arm).
- The on arm's median tokens per run, over all its runs, at most the off arm's.
- No on-arm run above 3x the median tokens of its model's off-arm runs on the same template.
- The outline fired (a `read_file` result carried `omh_read_outline`) in at least half of the
  on-arm sessions, counted from the on profile's session database; and in no off-arm session.
- Small and untruncated reads byte-identical: `tests/test_read_outline.py` (branch)
  (`test_small_and_untruncated_reads_are_byte_identical`).

A run with no record, or one that timed out, is scored as a fail; its tokens come from the
session database when the session can be found, and are reported as unobserved otherwise, never
imputed. If the gate fails, the outline does not merge and the result is recorded here. It failed.

The result: on this corpus the outline changes nothing measurable, and the weak-model clause
fails, so the outline does **not** merge.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 6 / 6 | 5 / 6 | 579,517 | 591,108 |
| `claude-haiku-5-5` | 6 / 6 | 6 / 6 | 291,562 | 293,271 |
| `gpt-5.6-luna` | 6 / 6 | 6 / 6 | 226,699 | 208,058 |
| `claude-sonnet-5-5` | 6 / 6 | 6 / 6 | 136,573 | 139,692 |
| `claude-opus-5-5` | 6 / 6 | 6 / 6 | 189,040 | 190,275 |
| `gpt-6.1-sol` | 6 / 6 | 6 / 6 | 265,919 | 269,421 |
| **Total** | **36 / 36** | **35 / 36** | 239,844 | 228,715 |

Token medians are per model over its 6 runs per arm; the total row is the median over all 36
runs per arm. Session-database sums: 11.85M off, 10.91M on.

The gate, clause by clause:

- Weak models, on at least off + 3: **fail**, 17 vs 18. The off arm passed every weak run, so
  no arm could have cleared + 3; the one on-arm fail is a `claude-haiku-4-5` rename that left a
  reference behind (1.09M tokens).
- Strong models, on at least off - 1: pass, 18 vs 18.
- On-arm median tokens at most the off arm's: pass, 228,715 vs 239,844.
- No on-arm run above 3x its model's off-arm median on the same template: pass, none.
- Outline fired in at least half of the on-arm sessions: pass, 29 of 37 on-profile sessions
  (every session that had a truncated `read_file` result; the other 8 never had one), and in 0
  of 38 off-profile sessions.
- Small and untruncated reads byte-identical: pass (`tests/test_read_outline.py`, branch).

What it shows, and what it does not:

- Every model, weak ones included, finds the deep helper by searching for names from the test
  and the call site, then reads a window around the hit. `read_file` calls per session have the
  same median in both arms (4). The outline arrives, and the models do not need it: the corpus
  does not reproduce the paging loop of #1723, where the model never searched.
- A fair test of the outline needs a task where search does not lead to the location (a symptom
  with no searchable name) or a model that pages instead of searching. Neither is in this split.
- Infrastructure: at 01:59:51 KST the shared host gateway received SIGTERM from its supervisor
  (another session's action, not this run) and interrupted 15 turns. The 17 runs that ended in
  that window (exit 130, then exit 1 within 3 s) were moved out of the records and run again on
  the same routes; no completed record was removed. An earlier smoke, before the bench
  profiles' plugins were reloaded in the gateway, had no outline and is not counted.
- After the outage the bench profiles also set `agent.run_budget_seconds: 600`. No run in the
  table timed out or needed a stop.
- omh `feature/read-outline` `237321b92` on origin/main `5cc1ed311`; Hermes Agent checkout `bf0203a794` (with uncommitted gateway changes from another session).
  n = 6 per model per arm, Python only.

### 2026-10-30 shell edits: the built-in shell-edit rule, off vs on, gate failed

Status: the gate failed and the feature did not merge (PR #2411, draft, branch `feature/shell-edit-rules`). The rule, the `shell-ab` split and the harness changes exist only on that branch, not on main; the commands and file names below refer to the branch, and this section records the measurement only.

One question, from oh-my-pi's bash interceptor (shipped off there): when a model may use the
terminal however it likes, does refusing in-place shell edits of source files (`sed -i`,
`perl -i`, a `python -c` that rewrites a file, `>`/`>>`/`tee` onto an existing source file) and
naming `patch`/`write_file` instead make it pass more tasks? The rule (on the branch) is
`src/plugin_bundle/omh/shell_edit_rules.py`, run at `pre_tool_call` after the person's own
`toolcall_rules`; it matches on `shlex`-parsed shell segments, never refuses reads, searches,
tests, `git`, new files, non-source files or anything under a generated directory such as
`build/`, and lets through any command it cannot parse.

The setup, fixed before the first live run:

- Pinned `E-RENAME` and `E-BUGFIX` (3 seeds each), **without**
  `--edit-directive`, so the model is free to edit through the shell.
- The negative template `S-GENERATED` in the separate split `shell-ab` (branch only; 3 seeds, the pinned
  corpus and its digest are unchanged): every write it needs is a new file under `build/` made by
  shell redirection (a generated `.py` module and a test log), plus `git apply --check` on a patch
  that must not be applied, and a line read from a source file. It fails if any existing file
  changes.
- Both arms: `--git-init-workspace`, `--test-env`, effort `medium`, toolsets `file,terminal`.
  Two profiles that differ only in `plugins.entries.omh.settings.shell_edit_rules` (true/false)
  and OMH home, both loading the same plugin snapshot; `agent.max_turns: 120`,
  `agent.run_budget_seconds: 600`. Arm order alternates per instance.
- Subscription routes only. Weak: `claude-haiku-4-5-20251001`, `claude-haiku-5-5`
  (`claude-proxy`), `gpt-6-luna` (`openai-codex`). Strong: `claude-sonnet-5-5`,
  `claude-opus-5-5` (`claude-proxy`), `gpt-6.1-sol` (`openai-codex`).
- A run classified `rate_limited` / `provider_error` is retried on the same route; every other
  outcome, a timeout included, is final and scored as recorded.
- Ceiling check before the result run: a smoke of the off arm on the weak models. If the off arm
  passes every smoke run, the main split is too easy to show a gain, and harder rename templates
  where a text replace misleads (`L-RENAME-ALIAS`, `L-RENAME-SHADOW` from `lsp-ab`) are added to
  both arms; the choice is written here before the result run.
- Ceiling smoke result (off arm, seed 104729, the three weak models): 9 / 9 passed, and 0
  terminal calls edited source. Every edit went through `patch` / `write_file` without any
  directive. So, as stated above, `L-RENAME-ALIAS` and `L-RENAME-SHADOW` (3 seeds each) join the
  main split in both arms: 12 main instances per model per arm. The smoke runs are not counted.
- Free data from earlier sessions (no directive, same panel, the 2026-10-30 read-outline split
  on a 3,600-line file): only `claude-sonnet-5-5` and `claude-opus-5-5` edited source through
  the shell (`sed -i ''` with line addresses, 3 of 6 sessions each, in both profiles); the weak
  models and both GPT models made 0 such calls. That off arm passed 36 / 36, so those shell edits
  did not fail. The weak-model clause may therefore have nothing to act on; it stays as written.

The merge gate, written before the first live run. Counts are passes over the main split
(everything except `S-GENERATED`) unless a clause says otherwise.

1. Weak models: on at least off + 2.
2. Strong models: on at least off - 1.
3. Shell edits that ran in the on arm: at most 1 in total. Counted over every terminal call in
   the on arm's session DBs that was not refused, by a broad text match independent of the
   rule's parser (`sed`/`perl`/`ruby` with an in-place flag; `python` code that opens a file for
   writing or calls `write_text`/`write_bytes`; `>`, `>>` or `tee` onto a path with a source
   suffix), each hit checked by hand against the workspace's existing files.
4. No on-arm session with more than 5 consecutive refusals (refusal tool results with no other
   tool result between them).
5. No on-arm run above 3x the median tokens of the same model's off-arm runs on the same
   template.
6. Final answer preserved: on-arm sessions whose last assistant message carries the task's
   answer key (`changed_paths` for `E-*`, `generated_lines` for `S-GENERATED`) at least the
   off arm's count minus 2, counted from the session DBs.
7. Negative template: `S-GENERATED` passes, all models pooled, on at least off - 1.

The result. On this panel the rule does not make any model pass more tasks, so the branch
(`feature/shell-edit-rules`) does not merge and main has no such rule.

| Model | off | on | off tokens (median) | on tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `claude-haiku-4-5-20251001` | 12 / 12 | 11 / 12 | 268,489 | 259,064 |
| `claude-haiku-5-5` | 12 / 12 | 12 / 12 | 223,649 | 223,204 |
| `gpt-6-luna` | 11 / 12 | 12 / 12 | 229,689 | 240,554 |
| `claude-sonnet-5-5` | 12 / 12 | 12 / 12 | 134,980 | 207,348 |
| `claude-opus-5-5` | 12 / 12 | 12 / 12 | 169,812 | 210,912 |
| `gpt-6.1-sol` | 9 / 12 | 9 / 12 | 152,544 | 155,859 |
| **Total** | **68 / 72** | **68 / 72** | 18.3M total | 19.3M total |

Pass counts are the main split (`E-RENAME`, `E-BUGFIX`, `L-RENAME-ALIAS`, `L-RENAME-SHADOW`);
token medians and totals are over every run of the model, `S-GENERATED` included. Per template,
off vs on: `E-RENAME` 18 vs 18, `E-BUGFIX` 18 vs 17, `L-RENAME-ALIAS` 14 vs 15, `L-RENAME-SHADOW`
18 vs 18, `S-GENERATED` 18 vs 17. 180 of 180 records, all `completed`, no retries, no timeouts.

The gate, clause by clause:

1. Weak, on at least off + 2: 35 vs 35, **fail**.
2. Strong, on at least off - 1: 33 vs 33, pass.
3. Shell edits that ran in the on arm, at most 1: 0, pass. The broad text match flagged 21
   calls; by hand every one wrote a new file under `build/` or the answer JSON.
4. At most 5 consecutive refusals: the longest streak was 1, pass. 21 refusals in 21 of 90
   on-arm sessions.
5. No on run above 3x its pair median: none, pass.
6. Final answer preserved, on at least off - 2: 69 vs 61 sessions, pass.
7. `S-GENERATED`, on at least off - 1: 17 vs 18, pass. The on-arm fail is a `claude-haiku-4-5`
   run that copied the generator's output by hand without the last newline and reported 4 lines
   for 5; no refusal in that session.

What it shows:

- Weak models and both GPT models do not edit source through the shell here. They use `patch` /
  `write_file` without being told to, so the rule has nothing to refuse for them, and the
  weak-model clause cannot move. The smoke and the earlier session DBs said the same before the
  run.
- `claude-sonnet-5-5` and `claude-opus-5-5` reach for `sed -i ''` on renames: in the on arm every
  one of their `E-RENAME` and `L-RENAME-*` sessions was refused once (18 of 18) and then finished
  with `patch`. Their shell edits in the off arm passed anyway, so the refusal bought nothing and
  cost tokens: sonnet's renames went from about 133k-135k to 207k-249k median tokens, opus's
  from 136k-206k to 207k-288k (+40% to +84%). Below the 3x clause, but a real cost for no gain.
- Three of the 21 refusals were wrong: `gpt-6-luna` and `gpt-6.1-sol` ran `python` programs on
  `S-GENERATED` that hashed every existing file and wrote only `build/` output and the answer.
  The detector fell back to "the program writes something and names an existing source file" when
  a write path was `root / 'build/...'` or `outputs[0]`. Fixed after the run: joins and indexed
  lists are now read as paths, and the fallback only counts source literals the program hands to
  its own helper functions (`def sub(p): open(p, 'w')`, which opus used and which is still
  refused). Replaying all 482 terminal calls of this run against the measured detector
  (`ebaf7c6ac`) and the fixed one changes 7 verdicts, all on `S-GENERATED` (3 on-arm refusals and
  4 off-arm calls that would have been refused), and none on the main split; the fixed detector
  refuses no call on `S-GENERATED`. The pass counts above are from the measured detector and are
  not re-run.
- Plugin snapshot `ebaf7c6ac` (the rule as measured); the bench ran from `a9d7f848c`, which adds
  only this README's smoke record and docs. Hermes Agent v0.22.5. n = 12 main instances plus 3
  negative instances per model per arm.

### 2026-10-29 debugging: builtin `patch` vs a debugpy tool (`omh-dap`), gate failed

One question, from oh-my-pi's `debug` tool: does giving the model a debugger (breakpoints,
locals, evaluate) help it find and fix a bug that the failing assertion does not explain? On
this corpus it does not: pass counts barely move and the token clause fails, so the
`debug_python` tool (branch `feature/omh-dap`) does **not** merge.

The setup:

- Split `dap-ab`, three templates whose failing test shows only values (`assert 118 == 76`):
  `D-MUTABLE-DEFAULT` (a mutable default argument), `D-ALIASED-STATE` (a shallow copy shares
  state), `D-ORDER-DEPENDENT` (a cache keyed on the wrong thing). 3 seeds each, 9 per model
  per arm, effort `medium`, OpenGateway (`og`).
- Both arms: `--edit-directive debug` (one shared sentence plus "if the same test still fails
  after three edits, stop editing and inspect state again"), `--git-init-workspace`,
  `--test-env` (pytest and debugpy ready). Only the dap arm has toolset `omh-dap`.
- omh `feature/omh-dap` `9528a8c73` (pushed, not merged). 143 of 144 run records (one
  gpt-4.1-nano dap run left none and is scored as a fail); `artifacts/` is git-ignored, so the
  records stay local, as for the other sections here.
- qwen-flash `D-MUTABLE-DEFAULT` in both arms reuses the last smoke's records (same commit,
  same flags), decided before the run because the paid-call cap was short by four.

| Model | patch | dap |
| --- | ---: | ---: |
| `deepseek/deepseek-v4.1-flash-ultrafast` | 9 / 9 | 9 / 9 |
| `moonshotai/kimi-k3.1-pro` | 9 / 9 | 9 / 9 |
| `z-ai/glm-5.3` | 8 / 9 | 7 / 9 |
| `minimax/MiniMax-M3` | 9 / 9 | 9 / 9 |
| `x-ai/grok-4-1-fast` | 9 / 9 | 9 / 9 |
| `qwen/qwen-flash` | 0 / 9 | 2 / 9 |
| `openai/gpt-4o-mini` | 0 / 9 | 0 / 9 |
| `openai/gpt-4.1-nano` | 0 / 9 | 1 / 9 |
| **Total** | **44 / 72** | **46 / 72** |

The merge gate, fixed before the first paid run:

- Weak models, dap at least patch + 3: 12 vs 9, pass.
- Strong models, dap at least patch - 1: 34 vs 35, pass.
- No dap run above 3x its patch pair's median tokens: **fail, 7 runs**. Among runs that
  finished normally: gpt-4.1-nano 6.3x, MiniMax-M3 3.7x, grok-4-1-fast 3.3x. The rest are
  three qwen-flash timeouts and the missing nano record.
- `debug_python` used in at least half of the dap-arm sessions: 46 / 65, pass.

What it shows:

- Strong models already fix these bugs by reading the code and printing; the debugger adds
  nothing for them. Weak models mostly cannot fix them either way, and with a debugger they
  loop longer, because each debugger call is cheap.
- Four smokes before the run each found a different loop, and each was fixed in the tool:
  a statement passed to evaluate (now `not_an_expression` with the way to read a module
  value), 558 evaluates walking `lines[0]` to `lines[541]` at one stop (now 15 per stop and
  40 per session), a launch refused while a session was live (a relaunch now replaces it),
  and breakpoints that stopped during import (now says to continue). After each fix the
  weak model found another loop.
- The shared "three edits" sentence stopped the patch arm's edit/test loops in the smoke.
- Provider failures: from 22:18 KST og answered `401 model_access_denied` for qwen-flash,
  gpt-4o-mini and gpt-4.1-nano. Six gpt-4o-mini dap runs crashed within 10 s and the nano run
  left no record. The token clause fails without them.
- **A bench timeout did not stop the model.** `hermes -p <bench>` is a client of the
  profile's gateway; the 30-minute timeout killed the client, and the agent turn went on.
  Two qwen-flash sessions ran for over three hours. Over the whole DAP effort the bench
  profiles used 1.15B tokens, 87% of them in sessions that outlived their timeout, while
  the paid-call count stayed at 155 of 160. The longest passing run here took 40 model calls
  (84 in the LSP run), so every bench profile now sets `agent.max_turns: 120`; a live check
  with `max_turns: 3` stopped a turn after 3 calls. See "Before a paid run" under Commands.
- Python and debugpy only. n = 9 per model per arm.

### 2026-10-29 rename: builtin `patch` vs Hermes LSP through `omh-lsp`

One question, from oh-my-pi's "LSP wired into every write": does letting the model ask the
language server for definitions, references and a rename beat finding and editing every use
by hand? On this corpus it raises weak models' rename pass rate from 16 / 36 to 28 / 36 and
leaves strong models where they were, so the `omh-lsp` tools (`lsp_definition`,
`lsp_references`, `lsp_rename`) ship, off by default.

How the tools work: Hermes already runs pyright and other servers in `agent/lsp` for its
post-write diagnostics, but exposes no navigation tool and sends no navigation request. The
OMH plugin drives that same service; one bridge module is the only code that touches its
private attributes, and Hermes core is not patched. The symbol is located on the given line as
a whole identifier only. `lsp_rename` syncs the exact bytes it will edit to the server and
writes only if the disk still holds them (`stale_file` otherwise); a rename whose symbol is
gone from a line that already holds the new name answers `already_renamed` and writes nothing.

The setup:

- The pinned `E-RENAME` template plus two new templates in the separate split `lsp-ab`
  (`--split lsp-ab`; the evaluation corpus and its digest are unchanged). Each new template
  fails untouched, fails a naive text replace, and passes only a semantic rename:
  - `L-RENAME-ALIAS`: a module function re-exported through `__all__`, imported under an
    alias and through the module, next to a same-named method, a log string and a comment
    that must stay.
  - `L-RENAME-SHADOW`: a function whose name a parameter in another module shadows.
- 3 seeds each, 9 instances per model per arm, effort `medium`, OpenGateway (`og`).
- Both arms: `--edit-directive rename` (one sentence naming `search_files`/`patch` or
  `lsp_definition`/`lsp_references`/`lsp_rename`; only the tool names differ),
  `--git-init-workspace` (Hermes LSP only runs inside a git worktree; every earlier run in
  this README had LSP dormant) and `--test-env` (a ready interpreter with pytest and the
  workspace on `sys.path`, named in the task; without it, in the third measurement below,
  qwen-flash spent 18 and 38 terminal calls on pip installs and venv paths after a one-call
  rename). 0 `pip install` calls in either arm here.
- Two profiles that differ only in the `lsp_tools` gate and OMH home; `tools.tool_search` off
  in both. `patch` stays available in the lsp arm.
- Contamination check: 0 `lsp_*` calls in the 72 patch-arm sessions.
- omh `feature/omh-lsp-nav` `6c7976ddb` on origin/main `7a2de348a`; Hermes Agent v0.22.5
  (`hermes --version`; the run records do not store it).

| Model | patch | lsp | patch tokens (median) | lsp tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `z-ai/glm-5.3` | 9 / 9 | 9 / 9 | 146,334 | 142,246 |
| `minimax/MiniMax-M3` | 9 / 9 | 9 / 9 | 307,488 | 297,129 |
| `deepseek/deepseek-v4.1-flash-ultrafast` | 8 / 9 | 8 / 9 | 216,575 | 178,623 |
| `moonshotai/kimi-k3.1-pro` | 5 / 9 | 7 / 9 | 156,655 | 154,570 |
| `x-ai/grok-4-1-fast` | 7 / 9 | 9 / 9 | 189,137 | 218,454 |
| `qwen/qwen-flash` | 6 / 9 | 9 / 9 | 442,883 | 168,547 |
| `openai/gpt-4o-mini` | 3 / 9 | 7 / 9 | 235,446 | 171,393 |
| `openai/gpt-4.1-nano` | 0 / 9 | 3 / 9 | 108,724 | 150,237 |
| **Total** | **47 / 72** | **61 / 72** | 20.2M | 14.5M |

Token medians are over each model's 9 runs per arm; the two failed patch runs (below) have no
token count in their records and are left out of their model's median. Totals are the
session-database sums for all 72 sessions per arm and include them; without the
gpt-4o-mini timeout (3.55M) the patch total is 16.6M.

Per template, patch vs lsp: `E-RENAME` 20 vs 19, `L-RENAME-ALIAS` 13 vs 20,
`L-RENAME-SHADOW` 14 vs 22. The gain is where a text search misleads: aliases, re-exports
and shadowing names. On the plain rename the two arms are even.

The merge gate, fixed before the first paid run, passes on every clause:

- Weak models (grok, qwen, gpt-4o-mini, gpt-4.1-nano), lsp at least patch + 3: 28 vs 16.
- Strong models (deepseek, glm, kimi, minimax), lsp at least patch - 1: 33 vs 31.
- No lsp run above 3x its patch pair's median tokens: none (highest 2.85x, gpt-4.1-nano).
- `lsp_rename` used in at least half of the lsp-arm sessions: 70 / 72.

What it shows, and what it does not:

- Two patch-arm runs failed: a kimi process crash before any model call, and a gpt-4o-mini
  timeout after 3.55M tokens. Both are recorded as `failed` and scored as fails. No lsp-arm
  run failed that way.
- This is the fourth lsp-arm measurement; only this one is reported as the result.
  1. 59 / 72, gate passed, but an independent verifier made `lsp_rename` write a corrupted
     file (preview, outside edit, apply) while reporting success. Fixed by syncing the bytes
     it edits.
  2. 58 / 72, token clause failed: gpt-4o-mini called `lsp_rename` 42 more times on lines it
     had already renamed (8.2x), and qwen-flash looped on pytest setup (7.8x). Fixed the first
     with `already_renamed`.
  3. 63 / 72, token clause failed: qwen-flash pytest-setup loops (3.08x, 14.3x). Fixed with
     `--test-env`, applied to both arms, so both arms were measured again.
  4. The table above.
- After the table's run a second verifier found that the symbol lookup fell back to a
  substring match (`LIMIT` inside `LIMIT_ALIAS`), so a repeated `LIMIT -> MAX_LIMIT` rename
  renamed `LIMIT_ALIAS` and reported success. Whole-identifier matching fixes it. Replaying
  all 220 lsp calls of this run against the fixture lines they targeted, none needed the
  substring path, so the numbers above are unchanged by the fix.
- The gate was written into the plan before any paid run (plan 22:54 KST, first paid record
  23:27 KST, 2026-10-28) and was not changed after.
- Rename only. Definition and references are exercised as steps of a rename, not measured on
  their own; the corpus `lsp` class still cannot pass under `hermes_current_session`, which
  records no tool events.
- Python and pyright only. n = 9 per model per arm.

Pass counts come from the run records. Tool-call counts come from each profile's session DB.

### 2026-10-28 edit surface: builtin `patch` vs hash-anchored `hashline_edit` (supersedes 2026-10-27)

One question, from oh-my-pi's hashline result (Grok Code Fast 1 6.7% -> 68.3%
on its own corpus): does addressing lines by a content hash instead of
retyping old text raise edit pass rates for the models OMH routes to? On this
corpus it does not, and weak models get worse, so the hashline tools are not
merged. Their code, with the not-found recovery below, stays on branch
`feature/hashline-edit` (`e29c341be`).

**The 2026-10-27 table that stood here was invalid.** Its patch arm ran in a
profile that also enabled the hashline gate, so `--toolsets file,terminal`
exposed `hashline_read`/`hashline_edit` too: gpt-4o-mini called them in 4 of 6
patch sessions and grok-4-1-fast in 3 of 6. The table below replaces it.

The setup:

- The pinned evaluation corpus, `--templates E-RENAME,E-BUGFIX` only (3 seeds
  each, 6 instances per arm), effort `medium`, OpenGateway (`og`).
- `--edit-directive` on both arms: one sentence names `read_file`/`patch` or
  `hashline_read`/`hashline_edit` and forbids editing through the shell.
  Without it the first smoke made 7 `terminal` calls and no edit-tool call.
- Two profiles that differ only in the hashline gate and OMH home:
  `patch` arm `--toolsets file,terminal` with the gate off; `hashline` arm
  `--toolsets omh-hashline,terminal` with the gate on. `tools.tool_search` is
  off in both, so plugin tools are not deferred behind tool search.
- Contamination check: 0 hashline calls across the 48 patch-arm sessions.
- The hashline arm carries the not-found recovery (`similar_files`, a
  root-relative fallback for absolute paths, and a repeat hint).
- omh `feature/hashline-edit` on origin/main `bbf278ab3`; Hermes Agent
  v0.22.5 · stable · local bf0203a794a0.

| Model | patch | hashline | patch tokens (median) | hashline tokens (median) |
| --- | ---: | ---: | ---: | ---: |
| `z-ai/glm-5.3` | 6 / 6 | 6 / 6 | 187,545 | 144,394 |
| `x-ai/grok-4-1-fast` | 6 / 6 | 6 / 6 | 319,764 | 281,736 |
| `deepseek/deepseek-v4.1-flash-ultrafast` | 6 / 6 | 5 / 6 | 226,100 | 244,568 |
| `moonshotai/kimi-k3.1-pro` | 6 / 6 | 4 / 6 | 176,586 | 149,377 |
| `minimax/MiniMax-M3` | 4 / 6 | 5 / 6 | 515,527 | 701,143 |
| `qwen/qwen-flash` | 5 / 6 | 0 / 6 | 164,094 | 405,057 |
| `openai/gpt-4o-mini` | 3 / 6 | 0 / 6 | 137,174 | 1,382,215 |
| `openai/gpt-4.1-nano` | 0 / 6 | 0 / 6 | 97,254 | 175,894 |
| **Total** | **36 / 48** | **26 / 48** | 13.1M total | 22.8M total |

The merge gate, fixed before the run, fails on every clause:

- Weak models (grok, qwen, gpt-4o-mini, gpt-4.1-nano), hashline must be at
  least patch: 6 vs 14.
- Strong models (deepseek, glm, kimi, minimax), hashline must be at least
  patch - 1: 20 vs 22.
- No hashline run over 3x its patch pair's median tokens: six were over, four
  from gpt-4o-mini (3.8x to 39.9x, worst 5.47M against 137k) and two from
  qwen-flash (3.2x and 3.6x).

What it shows:

- **No gain where patch already works.** Strong-model hashline failures are
  all BUGFIX `mutation_outside_scope`, not failed edits.
- **The not-found recovery fires but does not stop the loop.** gpt-4o-mini made
  647 `hashline_edit` calls in six runs and got 131 not-found and 74 repeat
  answers. It ignores "Stop retrying this path".
- **qwen-flash fails differently.** Its `hashline_edit` calls touched only the
  task files, yet all six runs scored `mutation_outside_scope`, and it made 5x
  the terminal calls of its patch arm. The extra files likely came from the
  shell, but the cause is not established.
- **Not a reproduction of oh-my-pi's number.** Their corpus and harness
  differ, and Grok 4.1 Fast passes 6 / 6 with `patch` here.
- n = 6 per arm, so single-instance differences are noise.

Pass counts come from the run records. Tool-call counts come from each
profile's session DB.

### 2026-10-27 `gpt-6.1-terra` vs `gpt-6.1-sol` (GPT-6.1 Terra onboarding)

One question from the GPT-6.1 Terra onboarding: on this corpus, does Terra
at half of Sol's list price lose anything against GPT-6.1 Sol at the same
effort? Both arms send the `gpt` family block (`--condition family`), so the
model is the only difference. Sol's exact override measured as no effect on
2026-10-02, and comparing against it would add a second variable.

The setup:

- The same pinned evaluation corpus (30 instances, digest
  `c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33`).
- The `hermes_current_session` path on the Codex subscription
  (`openai-codex`), so every record reports `cost_usd` 0.
- omh at `256262138` (origin/main the day of the run; the onboarding PR
  changes no prompt text). Hermes Agent v0.22.5 (2026.9.24) · stable · local bf0203a794a0.
- A targeted manifest with both ids at `high`. Every arm used
  `--split evaluation` and `--max-paid-calls 30`. Hermes' Codex route sends
  `high` unchanged for both ids; only `max` is clamped for Terra.

Arms ran sequentially on 2026-10-27 UTC:

- **T1:** Terra `family`, 02:33 to 02:50Z. Six instances (E-CALLFLOW-155921,
  all three E-REFERENCES, and E-PREDICATE-104729/130363) exited as
  `process_crash` within 25 seconds of each other (02:40:23 to 02:40:48Z).
  The child process failed before it produced a model answer, so this is a
  runtime interruption, not a model result. Pairs against T1 drop those six
  (n = 24).
- **T2:** Sol `family`, 02:50 to 03:14Z.
- **T3:** Terra `family` again, 03:14 to 03:28Z. This is the clean Terra arm
  and the same-model drift control.

| Arm | Model | Passed | Total tokens | Mean tokens (n) |
| --- | --- | ---: | ---: | ---: |
| T1 | `gpt-6.1-terra` | 13 / 30 (6 crashes) | 1,616,929 | 67,372 (24) |
| T2 | `gpt-6.1-sol` | 18 / 30 | 2,018,456 | 67,281 (30) |
| T3 | `gpt-6.1-terra` | 18 / 30 | 1,912,768 | 63,758 (30) |

T2 and T3 passed the same 18 instances (McNemar: zero discordant pairs, p =
1.0). Among T1's 24 completed instances, every pass agrees with T3. Paired
token deltas per instance, with a template-cluster bootstrap (10,000 draws,
seed 20260813):

| Pair | Mean delta | 95% CI | Instances lower |
| --- | ---: | --- | ---: |
| T3 − T1 (same model, drift; n = 24) | +1,039 (+1.5%) | [−2,147, +4,289] | 14 / 24 |
| T3 − T2 (Terra vs Sol) | −3,523 (−5.2%) | [−7,245, +182] | 19 / 30 |
| T1 − T2 (Terra vs Sol; n = 24) | −3,757 (−5.3%) | [−7,797, +581] | 15 / 24 |

What it shows:

- **No loss against Sol on this corpus.** Terra solved the same instances
  with about 5% fewer tokens. The CI touches zero, so the token gap is not
  claimed. At list price that means about half Sol's cost for the same pass
  set. The run itself was free on the subscription.
- **Faster wall clock, contended:** 14 minutes for T3 against 24 for T2,
  sequential on one machine. The arms ran on one provider, one after
  another, so this is a reading, not a timing claim.
- **The corpus ceiling stays at 18 / 30.** No arm passes a read or lsp
  task, so this corpus cannot show where the vendor says Sol still wins (the
  hardest coding). A placement that replaces Sol in `deep` or
  `unspecified-high` needs a corpus with headroom (#1333). Terra in a cheap
  slot does not.

Results describe this pinned corpus, OMH version, Hermes version, model IDs,
and conditions only. They do not establish universal model superiority.

### 2026-10-02 `gpt-6.1-sol` generation and override evaluation (PR #1975 follow-up)

Two questions from the GPT-6.1 Sol onboarding (#1975). Does 6.1 Sol hold the
slots GPT-6 Sol held? And does its exact-model override (GPT-6 Astra's text,
byte for byte) beat the `gpt` family block it replaced?

The setup:

- The same pinned evaluation corpus as above (30 instances, digest
  `c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33`).
- The `hermes_current_session` path on the Codex subscription
  (`openai-codex`), so every record reports `cost_usd` 0.
- omh at `1e4728607`, the PR #1975 tree. Hermes Agent 0.21.5+4533
  (`39faafb`, 2026.9.24).
- A targeted manifest with both ids at `high`, the effort `deep` routes them
  at. Every arm used `--split evaluation` and `--max-paid-calls 30`.

Arms ran on 2026-10-01/02 UTC, sequentially within the lane. A Claude lane
(below) ran in parallel on a different provider, so wall clock was contended
and is not compared.

- **G1:** 6.1 Sol `optimized`, 23:00 to 23:30Z.
- **G2:** 6.1 Sol `family`, 23:30 to 00:00Z.
- **G3:** GPT-6 Sol `optimized`, 00:00 to 00:35Z. 6 Sol has no override, so
  this arm sends the `gpt` family block.
- **G4:** 6.1 Sol `optimized` again, for same-text drift, 01:01 to 02:22Z.
  The first G4 attempt was stopped at 23 instances by a shell time limit. It
  was discarded, and the arm was rerun from the start.

The slow G4 window holds one 52-minute instance (E-CALLFLOW-104729), which
completed normally. Every record in every arm completed.

| Arm | What the prompt carries | Passed | Total tokens | Mean tokens | Tool calls | API turns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| G1 6.1 Sol optimized | `MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6.1-sol"]` | 18 / 30 | 2,006,957 | 66,898 | 351 | 203 |
| G2 6.1 Sol family | inherited `HIGH_EFFORT_CALIBRATIONS["gpt"]` | 18 / 30 | 1,970,421 | 65,680 | 360 | 204 |
| G3 6 Sol optimized | `HIGH_EFFORT_CALIBRATIONS["gpt"]` (no override) | 18 / 30 | 2,192,285 | 73,076 | 409 | 213 |
| G4 6.1 Sol optimized | same as G1, repeated | 18 / 30 | 2,032,796 | 67,759 | 352 | 204 |

Tool calls and API turns are out-of-harness observations. They were read
from the Hermes `sessions` table over each arm's exact window, and each arm
has exactly 30 root sessions.

All four arms passed the same 18 instances, so McNemar's test has zero
discordant pairs and p = 1.0. Paired token deltas per instance, with a
template-cluster bootstrap (10,000 draws, seed 20260813):

| Pair | Mean delta | 95% CI | Instances lower |
| --- | ---: | --- | ---: |
| G4 − G1 (same text, drift) | +861 (+1.3%) | [−2,879, +4,375] | 14 / 30 |
| G1 − G2 (override vs family) | +1,218 (+1.9%) | [−3,895, +6,150] | 8 / 30 |
| G4 − G2 (override vs family) | +2,079 (+3.2%) | [−877, +6,021] | 7 / 30 |
| G1 − G3 (6.1 Sol vs 6 Sol) | −6,178 (−8.5%) | [−22,358, +2,697] | 11 / 30 |
| G4 − G3 (6.1 Sol vs 6 Sol) | −5,316 (−7.3%) | [−22,547, +5,504] | 11 / 30 |

Reading:

- **The generation swap holds.** 6.1 Sol solves the same instances with
  14% fewer tool calls and about 8% fewer tokens. The token CIs span zero.
  Most of the difference sits in one template: DIAGNOSTICS took 569,062
  tokens on 6 Sol and 339,522 / 342,168 on 6.1 Sol.
- **The override shows no effect on this corpus.** Both override arms land
  1.9–3.2% above the family block, with nearly identical tool calls and
  turns. That is within one same-text drift, and every CI spans zero. It is
  not worse by the MODEL-ONBOARDING §8 rule, so it stays, recorded as
  unproven for 6.1 Sol.

### 2026-10-02 `claude-sonnet-5-5` override evaluation (PR #1975 follow-up)

This evaluation asks whether the Sonnet 5.5 override beats the `claude`
family block. The override is that block plus one clause: once the checks
pass, start no further review rounds and no reviewer sub-agents. Anthropic's
prompting guide reports that clause cutting session cost by about a third at
`max`.

The setup:

- The same corpus as above.
- The `hermes_current_session` path through Hermes' `anthropic` provider on
  the Claude Code OAuth subscription. No API key was configured.
- `claude-sonnet-5-5` at `max`.
- The same omh and Hermes builds as the 6.1 Sol evaluation, running in
  parallel with it.

Arms:

- **S1** `optimized`: 23:00Z to 00:04Z.
- **S2** `family`: 01:01Z to 02:56Z. A shell time limit stopped the first S2
  attempt at 23 instances. It was discarded and the arm was rerun from the
  start.
- **S3** `optimized` again, for same-text drift: 02:56Z to 03:51Z.

During S2 the provider slowed sharply, and one instance failed as
`process_crash` (E-BUGFIX-155921). Pairs against S2 drop that instance
(n = 29). Records report `cost_usd` as a list-price estimate, because Hermes
marks only the Codex route as subscription-included.

| Arm | What the prompt carries | Passed | Total tokens | Mean tokens | Tool calls | API turns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| S1 optimized | `MODEL_HIGH_EFFORT_CALIBRATIONS["claude-sonnet-5-5"]` | 18 / 30 | 4,817,735 | 160,591 | 402 | 230 |
| S2 family | inherited `HIGH_EFFORT_CALIBRATIONS["claude"]` | 17 / 30 (1 crash) | 4,431,596 | 152,814 (29) | 411 | 223 |
| S3 optimized | same as S1, repeated | 18 / 30 | 4,348,654 | 144,955 | 375 | 217 |

Paired token deltas per instance, with the same bootstrap:

| Pair | Mean delta | 95% CI | Instances lower |
| --- | ---: | --- | ---: |
| S3 − S1 (same text, drift) | −15,636 (−9.7%) | [−24,697, −6,831] | 22 / 30 |
| S1 − S2 (override vs family) | +6,100 (+4.0%) | [−4,186, +14,503] | 11 / 29 |
| S3 − S2 (override vs family) | −9,573 (−6.3%) | [−16,762, −2,254] | 17 / 29 |

Reading:

- **Drift is the largest effect here.** Re-running the same prompt moved
  tokens by about 10%, with a CI that excludes zero. The two override arms
  land on either side of the family arm.
- **The vendor's one-third cut does not reproduce.** This corpus may not
  exercise what the clause targets: no instance asks for a review, and the
  Hermes child path ran no reviewer sub-agents to suppress.
- **The override stays, unproven.** It is not worse by the MODEL-ONBOARDING
  §8 rule. A follow-up should use a corpus where the model actually starts
  extra review rounds.
- **Later (2026-10-04):** the override was removed in the prompt audit,
  because no shipped slot reaches it and this run could not tell it from the
  family block. Sonnet 5.5 now takes the `claude` family blocks; see
  `MODEL_OPTI.md`.

### 2026-10-04 prompt audit: Claude block vs none, and the shared unit head

The 2026-10-04 prompt audit asked two questions: is the `claude` family
block still worth sending to Fable 5.1, and does the shared unit head that
every real fanout unit carries pay for itself?

Setup:
- Corpus: the same pinned 30-instance evaluation corpus as above.
- Route: `claude-fable-5-1` at `xhigh`, then the `architect` chain head
  (third behind Opus 5.5 and GPT-6 Astra since 2026-10-13), through
  Hermes' `anthropic` provider on the Claude Code OAuth subscription.
- Builds: omh `4ab239b10` for A1–A3 and the `omh/bench-unit-head` branch for
  U1–U3; Hermes Agent 0.21.5+4533.

The arms ran one at a time in the order below. Every record completed.

| Arm | Condition | Window (UTC) | Passed | Mean tokens | Tool calls | API turns |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| A1 | baseline (no block) | 06:50–07:16 | 16 / 30 | 111,383 | 356 | 227 |
| A2 | optimized (`claude` block) | 07:16–07:40 | 17 / 30 | 99,409 | 313 | 201 |
| A3 | baseline, repeated | 07:40–08:06 | 18 / 30 | 104,155 | 348 | 215 |
| U1 | unit (head + block) | 08:36–09:05 | 18 / 30 | 97,546 | 219 | 188 |
| U2 | unit_lean (head − parent clarification) | 09:05–09:33 | 17 / 30 | 102,218 | 242 | 201 |
| U3 | unit, repeated | 09:33–10:03 | 18 / 30 | 105,478 | 236 | 202 |

Paired token deltas per instance, with a template-cluster bootstrap (10,000
draws, seed 20260813):

| Pair | Mean delta | 95% CI |
| --- | ---: | --- |
| A3 − A1 (drift) | −7,228 (−6.5%) | [−17,928, +2,240] |
| A2 − A1 (block vs none) | −11,974 (−10.7%) | [−21,404, −3,505] |
| A2 − A3 (block vs none) | −4,746 (−4.6%) | [−12,179, +1,862] |
| U3 − U1 (drift) | +7,933 (+8.1%) | [−2,845, +23,459] |
| U2 − U1 (lean vs full head) | +4,672 (+4.8%) | [−7,690, +20,755] |
| U2 − U3 (lean vs full head) | −3,260 (−3.1%) | [−7,259, +560] |
| U1 − A2 (head vs no head) | −1,864 (−1.9%) | [−16,153, +12,161] |

How to read it:
- **The `claude` block stays.** It never costs more than no block, and it
  cuts tool calls by about 11%.
- **The shared head stays.** Its token cost against no head is within drift,
  and it cuts tool calls by about 25–30%. Arms A2 and U1 ran on different
  builds on the same day; only the head differs in their prompt.
- **Dropping the parent-clarification block shows no measurable saving.**
  This corpus never needs `input_required`, so the block stays.
- **Wall clock is not compared.** Pass rate cannot separate the arms on this
  corpus.

Records, manifests, and lane scripts are in
`~/Desktop/khope/bench-archive/prompt-audit-2026-10-04/runs` (outside git).
