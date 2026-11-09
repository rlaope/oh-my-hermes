# T0 + T3: Runs model, dag adapter, Runs tab (lane runs, wt v02-runs)

Status: **done**. Every VERIFY passes. Nothing pushed.

## Commits (branch in `oh-my-hermes-worktrees/v02-runs`, on base 8a6d72016)
- `12a0b535f` feat(omher): AgentRun model, dag adapter, runs.list / runs.get bridge ops
- `e29e8ba35` feat(omher): Runs tab with a read-only layered graph

Both commits are signed off (`-s`) and carry the trailers Constraint, Rejected, Confidence, Scope-risk, Directive, Tested and Not-tested.

## What was built
**T0**
- `apps/omher/src/lib/runs.ts`:
  - The `AgentRun`, `RunNode`, `RunAttempt`, `AgentRunSummary` (with `counts`) and `RunDetail` types.
  - `layerOf`: longest-path layering; throws on a cycle.
  - `summary`: renders "7 nodes · 3 done · 1 running · 1 failed".
  - `countsOf`, `sortRuns` (running first, then newest) and `span`.
  - `fromDag`: the dag adapter.
- Bridge (`bridge/omher_bridge.py`):
  - `omh_home_for(profile)` takes the profile's `plugins.entries.omh.settings.omh_home`, else `OMH_HOME`, else `~/.omh`.
  - `layer_of` and `dag_to_run` use the same mapping as `fromDag`.
  - The `DagRuns` reader keeps an mtime+size cache, and keeps the last good parse when a record is caught mid-write.
  - A run belongs to a bot when its `session_id` is in the bot's `state.db` sessions (read with `ro_uri`).
  - A handoff is read only when it is a plain file inside the dag dir. Symlinked files and folders are refused, and text is capped at 8000 chars.
  - A record with a cycle or a bad shape is skipped, never raised.
  - New ops: `runs.list {bot}` returns `{runs}`, and `runs.get {bot, run}` returns `{run, handoffs}`. Both go through `asyncio.to_thread`. No new subprocess.
- State mapping. A node's state comes from its last attempt:

  | Last attempt | Node state |
  |---|---|
  | `accepted` | done |
  | `failed` | failed |
  | `blocked` | blocked |
  | `parked` | parked |
  | `retry` | waiting |
  | handed out, not settled | running |
  | none | waiting |

  - `cancelled_at` makes the run cancelled, and its live or waiting nodes cancelled.
  - The run state follows OMH's own derivation: a failed node counts as settled when its latest repair group is all accepted, and older groups are superseded. On the real dag dir the results matched OMH's own `dag_run.derive`/`run_state` for every run I checked.
- Store and protocol: `PanelTabId` gains `runs`. Added `ui.runId`, `openRun(run)`, `runsList` and `runsGet`, plus protocol entries for both ops.
- Fixtures:
  - `bridge/tests/fixtures/dag/` holds three real runs with their handoffs:
    - codex-coexist: a fan-out with a failed attempt and a repair.
    - omh-dap: a cancelled run.
    - route-hint-dedup: a small run.
  - Redaction: `/w` → `/w`, names and emails removed, secret patterns stripped, prompts dropped. A grep for owner, org, `/Users/` and `sk-` finds 0.
  - `dag-truncated.json` is a record cut in half.
  - `src/lib/__fixtures__/` holds the same records, a live variant (`codex-coexist-live`: one node out, one never handed out), and `runs-bridge.json`, which is the real `dag_to_run` output used by the vitest parity test and the mock.
- Tests:
  - `runs.test.ts` (12 tests): layering, cycles, summary, state mapping on all 3 fixtures plus the live one, and field-for-field parity with the bridge output.
  - Bridge `Runs` and `RunsOps` (7 tests):
    - list/get on a temp dag dir, with no mtime changing anywhere;
    - a truncated file keeps the last good parse, and a fresh reader skips it;
    - a symlinked handoff file and a symlinked run folder are refused;
    - a missing dir means no runs;
    - a cyclic record is skipped;
    - **a copy of the real `~/.omh/runtime/dag` (moved to tmp) lists ≥1 run**;
    - the ops over the socket, including bad_request, not_found and unknown_bot.
- Boundary: added BOUNDARY rule 11 (dag records are read only for the bot's own sessions, symlinks are refused, and runs are never settled, retried or cancelled). `test_omher_boundary` pins two sentences of it. The rule-count bound went from 6–10 to 6–12, because rule 11 is the 11th rule.

**T3**
- `src/elsewhere/RunsTab.tsx` and `runs.css`:
  - Runs is the 6th tab; its icon is three nodes with edges. The panel is 460px.
  - Run list: a live dot when running, the title, `3/6 · 14m`, and a Cancelled/Failed tag.
  - Graph: columns = layers, cards 112px wide, and SVG cubic edges from a dep's right-middle to the node's left-middle. The graph scrolls horizontally inside its own box.
  - Card states: done is a green ✓; running is a soft pink ring (`box-shadow`, no gradient); failed is a red rail, ✕ and class `bad`; blocked and parked are amber; waiting is dimmed.
  - Drawer: attempt k of n, model:effort · lane · duration, the last reason, earlier attempts, and the handoff through react-markdown with Show all at 1200 chars. Failed nodes add "Ask <bot> in chat to retry". There are no write buttons.
- `e2e/mock-bridge.mjs` serves `runs.list`/`runs.get` from `runs-bridge.json`, with the live run shifted to "now".
- `e2e/runs.spec.ts` (8 tests):
  - the 6th tab exists and the header keeps one control;
  - the panel is 460px, and the selection is gray;
  - list order and the live dot;
  - the fan-out shows 6 cards in 3 columns, with equal x per layer;
  - edge count = total deps (4), and each edge's endpoints equal its cards' right-mid and left-mid;
  - the failed node has `bad`;
  - the drawer shows attempt 2 of 2, the reason, the handoff and Show all;
  - no write ops appear in the mock call log;
  - the cancelled run is labelled with dimmed nodes;
  - the empty state;
  - dark and light screenshots.
- `e2e/panel.spec.ts`: the tab test now expects six tabs, with Runs last.

## VERIFY (literal tails)
```
pnpm typecheck && pnpm test
$ tsc -b --noEmit
 Test Files  4 passed (4)
      Tests  46 passed (46)
TS_EXIT=0

~/.hermes/hermes-agent/venv/bin/python -m unittest discover -s bridge/tests
Ran 59 tests in 0.812s
OK
BRIDGE_EXIT=0
(also under env -u PYTHONUTF8 LC_ALL=C LANG=C python -X utf8=0: Ran 59 tests ... OK)

OMHER_PORT=5421 OMHER_MOCK_PORT=5422 /usr/bin/lockf -k ~/.hermes/profiles/kami/cache/scratch/omher-heavy.lock \
  pnpm exec playwright test e2e/runs.spec.ts e2e/panel.spec.ts e2e/mock.spec.ts --reporter=line
  23 passed (25.6s)
E2E_EXIT=0

PYTHONPATH=tests ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_omher_boundary   (repo root)
Ran 8 tests in 3.484s
OK
BOUNDARY_EXIT=0

git diff --check 8a6d72016 HEAD  -> clean (DIFFCHECK_OK)
```
Full log: `~/.hermes/profiles/kami/cache/scratch/omher-v02/verify.log`

## Screenshots
- `~/.hermes/profiles/kami/cache/scratch/omher-v02/T3-runs-dark.png`
- `~/.hermes/profiles/kami/cache/scratch/omher-v02/T3-runs-light.png`

Both show the live fan-out with the drawer open on its failed node. A vision pass flagged faint edges and cards in light mode and two misaligned drawer lines. I fixed those by using the `--quiet` edge stroke, the `--line-strong` card border in light, waiting at 0.75 opacity, and an indent for the hint and none lines. Cards that read as "orphans" are real data: the repair nodes t1-hermes and t4-fence have no deps.

## Decisions and open items
- **Clickable dag line in chat: skipped.** No chat line or event carries a dag run id today: the bridge has no `omh_dag` detail, and the activity line shows only tool verbs. The store already exposes `openRun(runId)`, which opens the panel on Runs with that run selected, so T4/T5 can hook a run line up to it once a run id reaches the chat.
- Node `model`, `provider`, `effort`, `route` and `tokens` are not in dag JSON, so the cards show the category (non-`unspecified`) or the lane plus time, and no numbers are invented. The `omh_delegate_route` join is for the graph lane (T4/T5).
- `tests/test_omher_boundary.py` changed outside `apps/omher`: one bound and two pinned sentences. It is needed because the spec requires a numbered rule per new read surface.
- Full Playwright suite, cargo and the Windows check were not run. No Rust was touched; the full e2e suite belongs to T9.
- Scratch scripts used to build the fixtures (not committed): `~/.hermes/profiles/kami/cache/scratch/omher-v02/make_dag_fixtures.py` and `make_ts_fixtures.py`. Re-running them regenerates both fixture sets from `~/.omh/runtime/dag`.
