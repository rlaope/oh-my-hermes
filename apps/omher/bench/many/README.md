# Many-terminals bench

`bench.mjs` opens omher on the mock host and starts N Shell terminals through the session store, the way the
TERMINALS + menu does. It is a Playwright script, not part of the e2e suite. Numbers are from a Playwright browser
against the vite dev server and the mock host, never from the Tauri window (WKWebView on macOS).

```
/usr/bin/lockf -k /tmp/omher-heavy.lock node bench/many/bench.mjs --n 20 --mb 2 --secs 8 --runs 3 --label base \
  --port 5391 --mock 5392 [--engine chromium|webkit] [--profile]
```

Per run:

- **fill**: every terminal gets `--mb` MiB of 120-column coloured lines. `heapFillMB` is the JS heap after a forced GC
  (Chromium only). `bufMB` adds up the typed arrays xterm keeps per buffer line (outside most heap counters).
- **bg**: the last terminal is on screen and idle. The other N-1 are hidden and print an agent-like status line every
  100 ms for `--secs` (a spinner rewritten in place, plus a new line every fifth tick). This scenario measures:
  - `scriptMs` / `taskMs` / `styleMs` / `layoutMs`: main-thread time from CDP `Performance.getMetrics`.
  - `updates`: session-store notifications, which re-render the sidebar.
  - `domMutations`: DOM changes outside `.xterm`, i.e. sidebar work.
  - `renders` / `rendersHidden`: xterm row renders on the shown and the hidden terminals.
  - `selHidden`: selection redraws that reached a hidden terminal's renderer. Each one redraws every row. It is
    counted on the renderer's `handleSelectionChanged`. That path calls the renderer's `renderRows` directly, not
    through the RenderService's `_renderRows`, so `rendersHidden` does not count it.
  - `longFrames` (> 50 ms) and `maxGapMs`: gaps between `requestAnimationFrame` callbacks.
- `--profile` prints the top self-time functions and call chains of the bg scenario.

`raw/<label>-<engine>.json` keeps every run and the median/min/max summary.

## Baseline (main `b61d9c6ab`)

`raw/base-chromium.json`: N=20, 2 MiB each, 8 s, 3 runs. The load average was 21.5, from other work on the machine.
Read these numbers against a run taken under similar load, not as absolute values.

| metric | median (min-max) |
|---|---|
| xterm buffers after fill | 170.9 MB (20 x ~5,000 lines x 120 cols) |
| JS heap after fill | 34.7 MB |
| main-thread script time, 8 s bg | 1929 ms (1891-2119) |
| store updates, 8 s bg | 513 (513-532) |
| frames over 50 ms | 46 (46-56) |

The profile of the bg scenario (N=20, 6 s) showed:

- About 1.7 s of React work re-rendering every TERMINALS row (`TermRow`, `TermRowMark` and their icons). Each
  hidden terminal's output patches its row's `lastOut`/`lastLine`, which replaces the whole session list.
- About 1.0 s in xterm's DOM row renderer (`createRow`, `_measure`) for terminals that are not on the page. The
  chain is: output scrolls a hidden terminal, the selection service redraws, and
  `RenderService.handleSelectionChanged` renders rows whether or not the terminal is paused. xterm's own
  IntersectionObserver pause does not cover this path.

## Hidden lane: a terminal that is not on the page draws nothing

Change: `src/sessions/term/engine-hidden.ts`. While a terminal is hidden, the selection redraw that output scrolling
triggers is held back. The selection is kept, and when the terminal is shown its screen and selection are drawn once.

Run: `node bench/many/bench.mjs --n 20 --mb 1 --secs 8 --runs 3`. Base is a detached worktree of `5cac3df06` running
this bench.mjs; head is `perf/omher-mt-hidden`. There were 4 rounds of 3 runs per side (12 runs each), each round in
its own process. Rounds 1-2 ran base then head; rounds 3-4 ran head then base. Load average at round start was 10 to
53. Files: `raw/{base,head}-hidden-r{1..4}-chromium.json`.

| metric (8 s bg) | base median (min-max) | head median (min-max) |
|---|---|---|
| `selHidden`: full redraws of hidden terminals | 238 (209-266) | 0 (0-0) |
| `rendersHidden`: `_renderRows` on hidden terminals | 0 (0-0) | 0 (0-0) |
| `scriptMs` | 2758 (1525-3312) | 1637 (843-2017) |
| `taskMs` | 3239 (1727-3879) | 1998 (984-2422) |
| `longFrames` (> 50 ms) | 61.5 (56-64) | 62 (57-77) |
| `maxGapMs` | 192 (150-283) | 159 (133-300) |
| `updates` (store) | 476 (437-513) | 485 (456-532) |

Script time was lower on head in every round. The round medians were:

| round | base ms (load) | head ms (load) |
|---|---|---|
| 1 | 2884 (40) | 1797 (26) |
| 2 | 1582 (23) | 922 (10) |
| 3 | 2674 (43) | 1690 (23) |
| 4 | 3203 (40) | 1791 (53) |

Round 4 is the one where head ran under the higher load.

- `longFrames` did not improve: 61.5 on base, 62 on head, inside the spread. The long frames come from the sidebar's
  re-renders (the sidebar lane), not from xterm.
- `rendersHidden` was already 0 on base, because xterm's IntersectionObserver pause covers `_renderRows`. The hidden
  work was all on the selection path, which `selHidden` counts.
