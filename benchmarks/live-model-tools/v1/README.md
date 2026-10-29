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

There is no pi-family runtime execution path. OMH remains Hermes-native: core OMH makes no
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
