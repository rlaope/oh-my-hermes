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

## Result: all four lanes together (`perf/omher-many-terminals`)

The merged branch (rust, sidebar, hidden and park lanes, plus `origin/main`) against the base `5cac3df06`, Playwright
Chromium on the mock host, N=20, 2 MiB each, 8 s. Three rounds, each running `bg` then `park` once per side, the order
alternating (round 1 and 3 base first, round 2 head first), every run in its own process under
`/usr/bin/lockf -k /tmp/omher-heavy.lock`, ports 5431/5432. Base ran this branch's `bench.mjs` copied into a detached
worktree of `5cac3df06` (the base has no `--park` or `selHidden`). Load average 4.7 to 7.6 at the start of each run.
Files: `raw/{base,head}-int2-{bg,park}-r{1,2,3}-chromium.json`.

| scenario | metric | base `5cac3df06` median (min-max) | head median (min-max) |
|---|---|---|---|
| bg | main-thread script time (`scriptMs`) | 1333 ms (1321-1903) | 124 ms (119-266) |
| bg | main-thread task time (`taskMs`) | 1487 ms (1470-2108) | 230 ms (227-482) |
| bg | store updates (`updates`) | 513 (494-513) | 0 (0-0) |
| bg | full redraws of hidden terminals (`selHidden`) | 285 (285-285) | 0 (0-0) |
| bg | DOM changes outside `.xterm` (`domMutations`) | 464 (464-502) | 502 (464-502), **worse** |
| bg | frames over 50 ms (`longFrames`) | 59 (54-76) | 71 (54-72), **worse** |
| bg | longest frame gap (`maxGapMs`) | 133 ms (133-133) | 133 ms (133-150) |
| bg | output ticks delivered in 8 s (`ticks`) | 77 (76-77) | 79 (73-79) |
| park | xterm buffers after fill (`bufMB`) | 170.9 MB (170.9-170.9) | 170.9 MB (170.9-170.9) |
| park | JS heap after fill (`heapFillMB`) | 34.5 MB (33.9-34.7) | 33.6 MB (33.5-34.2) |
| park | terminals parked | 0 (0-0) | 19 (19-19) |
| park | xterm buffers after the park wait (`bufParkMB`) | 170.9 MB (170.9-170.9) | 10 MB (10-10) |
| park | snapshots (`snapMB`) | 0 MB (0-0) | 11 MB (11-11), **worse** |
| park | JS heap after the park wait (`heapParkMB`) | 34.6 MB (34.5-35) | 14.5 MB (14.4-15.3) |
| park | **total after the wait** (buffers + snapshots + heap) | 205.5 MB (205.4-205.9) | 35.5 MB (35.4-36.3) |

- `bg`: script time drops by 91% (1333 to 124 ms), because hidden output no longer re-renders the sessions list
  (sidebar lane, `updates` 513 to 0) and hidden terminals no longer redraw their rows on a selection refresh (hidden
  lane, `selHidden` 285 to 0).
- `park`: after the wait, the 19 hidden terminals are parked. Buffers, snapshots and heap total 35.5 MB, against
  205.5 MB on base (83% less). The snapshots themselves are new memory (11 MB) and are labelled worse.
- **Worse**: `longFrames` (59 to 71) and `domMutations` (464 to 502) are worse at the median. `maxGapMs` is the same
  (133 ms). Not verified: with the main thread nearly idle, the count of frames over 50 ms in a headless Chromium
  window may measure frame pacing rather than work. `domMutations` also counts text changes inside `.xterm` (see the
  sidebar lane's note), so it is not sidebar-only.
- The rust lane's shared foreground watcher is not in this table (it is not on the page). Its own bench is in its
  commit `fda9a2da1`: with 20 idle shells, the 10-second wake count drops from 189 to 9, the probe count from 189 to
  21, and the thread count from 100 to 81.
- Not measured: the Tauri window (WKWebView), WebKit, Windows.

## Sidebar lane (`perf/omher-mt-sidebar`)

Hidden output no longer goes through the sessions list. `lastOut`/`lastLine`/`oscTitle` live in a per-session store
(`src/sessions/termActivity.ts`); a memoised `TermRow` re-renders only when its spinner, age label or second line
changes.

`node bench/many/bench.mjs --n 20 --mb 1 --secs 8 --runs 1`, three runs per side, alternating base / head in separate
processes (base = detached `5cac3df06`), ports 5411/5412, Playwright Chromium. Load average 36 / 22-25 / 10.5 over
the three pairs (other lanes' work on the machine). Raw files: `raw/{base,head}-sidebar-r{1,2,3}-chromium.json` (base
files are in the base worktree and are not committed).

| metric (8 s bg, 19 hidden printing) | base median (min-max) | head median (min-max) |
|---|---|---|
| store updates (`updates`) | 475 (361-475) | 0 (0-0) |
| main-thread script time (`scriptMs`) | 3112 ms (2335-4920) | 1436 ms (902-1579) |
| main-thread task time (`taskMs`) | 3652 ms (2713-5591) | 1832 ms (1094-1867) |
| DOM changes outside `.xterm` (`domMutations`) | 426 (312-426) | 464 (464-502), worse |
| frames over 50 ms (`longFrames`) | 57 (54-59) | 63 (62-72), worse |
| longest frame gap (`maxGapMs`) | 283 ms (183-433) | 183 ms (133-250) |
| output ticks delivered in 8 s (`ticks`) | 64 (44-67) | 78 (71-78) |

Notes:
- `updates` falls to 0 because terminal output no longer notifies the sessions store at all.
- `domMutations` and `longFrames` are worse at the median. Head also delivered about 20% more output ticks in the same
  8 s, so the hidden terminals parsed more. Per tick, `domMutations` is 6.7 on base and 5.9 on head. Not verified: the
  observer's `m.target.closest` filter does not exclude text-node changes inside `.xterm`, so this count is not
  sidebar-only. Most of the remaining frame cost is the hidden-redraw chain the hidden lane owns.
- `renders`/`rendersHidden` read 0 on both sides in this run (the bench's `_renderRows` hook), so they are left out.

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

## Park lane: a terminal hidden and quiet for a while gives back its scrollback

Change: `src/sessions/term/park.ts` and the engine. A terminal off the page for 2 minutes that has printed nothing
for 60 s is serialized with `@xterm/addon-serialize`, its xterm is disposed, and the snapshot is kept as UTF-8 bytes.
Output or showing it makes a new xterm from the snapshot first.

Run: `node bench/many/bench.mjs --park --n 20 --mb 2 --runs 3`. After fill, the N-1 hidden terminals wait out park
thresholds shortened to 1 s through the dev hook; a build without parking waits 20 s. Base is a detached worktree of
`33de47302` (the hidden lane) running this bench.mjs. There were 3 rounds of 3 runs per side (9 runs each), in the
order base, head, head, base, base, head. Load average at round start was 17 to 32 (the machine had just rebooted).
Files: `raw/{base,head}-park-r{1..3}-chromium.json`.

- `bufParkMB`: xterm buffer bytes after the wait, counting the live terminals and the disposed xterm objects the
  engine still holds as map keys.
- `snapMB`: the snapshots' bytes. Like the buffers, they are typed arrays outside the JS heap's count.
- `heapParkMB`: the JS heap after a forced GC.

| metric | base median (min-max) | head median (min-max) |
|---|---|---|
| parked terminals | 0 | 19 (19-19) |
| `bufMB` after fill | 170.9 | 170.9 |
| `heapFillMB` after fill | 33.5 (33.5-34.2) | 33.6 (33.4-35.0) |
| `bufParkMB` after the wait | 170.9 | 10.0 (10.0-10.0) |
| `snapMB` | 0 | 11.0 (11.0-11.0) |
| `heapParkMB` | 33.9 (33.9-34.3) | 14.7 (14.3-15.0) |
| total after the wait (`bufParkMB + snapMB + heapParkMB`) | 204.8 (204.8-205.2) | 35.7 (35.3-36.0) |
| time until 19 are parked | - | 843 ms (602-1016) |

- The total went from 204.8 MB to 35.7 MB, 83% less. The one shown terminal keeps its 8.5 MB of buffer.
- The first try kept the snapshot as the JS string the add-on returns. That string is built from many small
  pieces, which V8 keeps as a rope several times its length: the heap after GC went from 34 to 214.6 MB with 19
  parked. Encoding it to UTF-8 bytes at park time fixed that. xterm takes the bytes in `write` directly.
