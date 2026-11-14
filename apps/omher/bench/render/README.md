# Terminal render bench

`bench.mjs` opens omher on the mock host, opens a Claude Code session as a terminal and feeds the terminal through
the real `feed()` of `src/sessions/term/engine.ts`. It is a Playwright script, not part of the e2e suite.

```
OMHER_PORT=5381 OMHER_MOCK_PORT=5382 /usr/bin/lockf -k /tmp/omher-heavy.lock \
  node bench/render/bench.mjs --engine webkit|chromium-metal|chromium --modes seam,off,on,auto --label final --runs 3
node bench/render/report.mjs     # baseline.json, after.json and the tables below, from raw/final-*.json
# scenario D alone, with the old auto rule's WebGL probe as a mode of its own:
node bench/render/bench.mjs --engine webkit --modes seam,off,auto,probe,on --label echo --only D --runs 9
```

| scenario | what is fed |
|---|---|
| A | 20 MB of plain 80-column lines |
| B | 20 MB of colour-heavy output (SGR on every word) |
| C | full-screen TUI redraw, alt screen, 120x40, 2,000 frames, 200 foreground colours (worst case for a glyph atlas) |
| C2 | C fed twice; the second pass is measured (glyphs already cached) |
| C3 | C with 6 foreground colours, the palette of a real TUI |
| D | typing echo: one character every 16 ms while B streams; ms from `feed` to the next frame |

Per run: wall ms until xterm's write callback of the last chunk, frames over 50 ms and the worst gap (from
`requestAnimationFrame`), JS heap after (Chromium only: WebKit exposes none). Chunks are 32 KB with at most 32 in
flight. Three runs per cell, the table shows the median; the raw files hold min and max. The modes run round-robin
in one process (run 1 of every mode, then run 2 ...), so machine load hits them equally.

- `seam` is the engine of the seam commit `f9fab5d17` (`seam-engine.ts`, served in place of `engine.ts`): no
  add-ons, the standard renderer. This is `baseline.json`.
- `off`, `on`, `auto` are this branch's engine with that `gpu` setting. `after.json` has all three.
- `probe` is `auto` after the page has made and lost one throw-away WebGL2 context (what `auto` first did to read
  the renderer's name). Only the scenario D run at the end uses it.

## Engines (and what they are not)

- `webkit`: Playwright WebKit 27.2. The macOS app runs in WKWebView, which is WebKit, so macOS decisions follow these
  numbers. Its WebGL is the Apple GPU.
- `chromium-metal`: the full Chromium build (`channel: "chromium"`), WebGL is ANGLE on Metal (the GPU).
- `chromium`: Playwright's headless shell. Its WebGL is **SwiftShader, software**: `on` is slow here because the GL is
  software. It stands for a machine without a GPU, not for the app.
- None of them is the Tauri window. Not measured: WebView2 (Windows), WebKitGTK (Linux).
- Machine: Apple M4 Pro, macOS 26.6.2. Other work shared the machine between runs (the load average at the start
  of each engine's run is in its table's heading); the heavy lock keeps another bench or test run from running at
  the same time as this one.
- `raw/baseline-*.json` is an earlier, independent baseline of the seam engine (scenarios A to D, not round-robin).
  It agrees with `baseline.json` within the spread.

## Result

Measured on the integrated branch at `de53275d9` (main and the three lanes merged, with the integration's own
changes). Each cell: wall ms until the last write callback, frames over 50 ms ("slow"), worst frame gap in ms;
medians of 3. "change" is the wall time against the seam engine. Min and max are in `raw/` and `after.json`. The
two Chromium runs had other work on the machine (load average 8.2 and 5.6 at their start, frame gaps of 133 ms in
every mode including the seam engine): read their columns against each other, not against the WebKit run.

**webkit** 27.2, Apple M4 Pro, darwin 25.6.0, load average 3.7 at start; `gpu: auto` drew with: standard

| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |
|---|---|---|---|---|---|---|---|
| A | 243 ms, 0 slow, worst 29 | 242 ms, 0 slow, worst 29 | 0% | 225 ms, 0 slow, worst 30 | -7% | 234 ms, 0 slow, worst 30 | -4% |
| B | 456 ms, 0 slow, worst 46 | 463 ms, 0 slow, worst 48 | +2% | 459 ms, 0 slow, worst 44 | +1% | 423 ms, 1 slow, worst 68 | -7% |
| C | 112 ms, 0 slow, worst 34 | 112 ms, 0 slow, worst 33 | +0% | 107 ms, 0 slow, worst 32 | -4% | 379 ms, 3 slow, worst 119 | +238% |
| C2 | 98 ms, 0 slow, worst 19 | 99 ms, 0 slow, worst 19 | +1% | 99 ms, 0 slow, worst 20 | +1% | 212 ms, 1 slow, worst 87 | +116% |
| C3 | 94 ms, 0 slow, worst 31 | 97 ms, 0 slow, worst 31 | +3% | 95 ms, 0 slow, worst 31 | +1% | 121 ms, 1 slow, worst 61 | +29% |
| D | 447 ms, 0 slow, worst 44 | 432 ms, 0 slow, worst 45 | -3% | 451 ms, 1 slow, worst 55 | +1% | 413 ms, 2 slow, worst 63 | -8% |

Typing echo (D), median feed-to-frame ms / p95, and JS heap after the run:

| | before (seam) | gpu off | gpu auto | gpu on |
|---|---|---|---|---|
| echo p50 / p95 | 17 / 54 | 16 / 54 | 28 / 41 | 20 / 68 |
| heap after B | n/a | n/a | n/a | n/a |

**chromium-metal** 158.0.8127.18, Apple M4 Pro, darwin 25.6.0, load average 8.2 at start; `gpu: auto` drew with: standard

| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |
|---|---|---|---|---|---|---|---|
| A | 558 ms, 5 slow, worst 133 | 458 ms, 5 slow, worst 117 | -18% | 457 ms, 4 slow, worst 133 | -18% | 489 ms, 4 slow, worst 100 | -12% |
| B | 490 ms, 5 slow, worst 133 | 492 ms, 4 slow, worst 133 | +0% | 599 ms, 6 slow, worst 133 | +22% | 566 ms, 3 slow, worst 133 | +16% |
| C | 216 ms, 2 slow, worst 133 | 156 ms, 2 slow, worst 117 | -28% | 168 ms, 2 slow, worst 133 | -22% | 370 ms, 3 slow, worst 133 | +71% |
| C2 | 231 ms, 3 slow, worst 117 | 238 ms, 2 slow, worst 133 | +3% | 271 ms, 3 slow, worst 133 | +17% | 322 ms, 3 slow, worst 83 | +39% |
| C3 | 177 ms, 1 slow, worst 117 | 195 ms, 2 slow, worst 133 | +10% | 176 ms, 2 slow, worst 117 | -1% | 174 ms, 0 slow, worst 50 | -2% |
| D | 518 ms, 5 slow, worst 133 | 550 ms, 4 slow, worst 133 | +6% | 521 ms, 4 slow, worst 133 | +1% | 546 ms, 6 slow, worst 100 | +5% |

Typing echo (D), median feed-to-frame ms / p95, and JS heap after the run:

| | before (seam) | gpu off | gpu auto | gpu on |
|---|---|---|---|---|
| echo p50 / p95 | 66.6 / 146.1 | 76.1 / 145 | 84.5 / 154.3 | 74.2 / 130.9 |
| heap after B | 10.1 MB | 10.2 MB | 10.2 MB | 12.2 MB |

**chromium** 158.0.8127.18, Apple M4 Pro, darwin 25.6.0, load average 5.6 at start; `gpu: auto` drew with: standard

| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |
|---|---|---|---|---|---|---|---|
| A | 454 ms, 4 slow, worst 133 | 472 ms, 3 slow, worst 100 | +4% | 438 ms, 4 slow, worst 133 | -4% | 720 ms, 7 slow, worst 133 | +59% |
| B | 551 ms, 5 slow, worst 133 | 560 ms, 2 slow, worst 117 | +2% | 552 ms, 4 slow, worst 133 | +0% | 753 ms, 7 slow, worst 133 | +37% |
| C | 225 ms, 2 slow, worst 133 | 242 ms, 3 slow, worst 133 | +8% | 196 ms, 2 slow, worst 117 | -13% | 584 ms, 5 slow, worst 133 | +160% |
| C2 | 283 ms, 3 slow, worst 133 | 243 ms, 2 slow, worst 133 | -14% | 313 ms, 3 slow, worst 133 | +11% | 506 ms, 6 slow, worst 117 | +79% |
| C3 | 205 ms, 1 slow, worst 117 | 194 ms, 2 slow, worst 117 | -5% | 230 ms, 1 slow, worst 133 | +12% | 405 ms, 3 slow, worst 133 | +98% |
| D | 466 ms, 4 slow, worst 133 | 445 ms, 4 slow, worst 117 | -5% | 498 ms, 5 slow, worst 117 | +7% | 732 ms, 7 slow, worst 117 | +57% |

Typing echo (D), median feed-to-frame ms / p95, and JS heap after the run:

| | before (seam) | gpu off | gpu auto | gpu on |
|---|---|---|---|---|
| echo p50 / p95 | 79.2 / 163.4 | 57.2 / 135.7 | 75.6 / 136.6 | 71.2 / 160.6 |
| heap after B | 9.8 MB | 9.9 MB | 9.9 MB | 11.6 MB |

## Reading it

- **Standard renderer, seam against this branch (`off`)**: no change beyond the run-to-run spread in WebKit (0% to
  +3% on A, B, C, C2 and C3, -3% on D). What now loads with a terminal (the Unicode 11 widths, the link add-on)
  shows no cost in these six scenarios; none of them hovers a link or runs a search.
- **GPU renderer (`on`) in WebKit, the macOS engine**: 4% to 8% faster on streaming text (A, B, D), but 2.2 to 3.4
  times slower on a full-screen redraw with many colours (C: 112 -> 379 ms, C2: 98 -> 212 ms), with frames over 50
  ms where the standard renderer has none, and 29% slower with a TUI-sized palette (C3). The lane's own run of the
  same bench had 2.9 and 2.3 times for C and C2. Those are this run's numbers. Two later runs on the same machine,
  whose raw files are not kept here, had 3.0, 1.7 and 1.2 times for C, C2 and C3, then 2.05, 2.03 and 1.03 times:
  the full-screen redraw is slower in every run, by an amount that moves from run to run, and the six-colour
  case (C3) was within the spread in the last one.
- **Chromium on Metal**: `on` is 1.4 to 1.7 times slower on C and C2, and from -12% to +16% on the rest.
  **Chromium's headless shell** (software WebGL): `on` is 1.4 to 2.6 times slower in every scenario.
- **`gpu: "auto"` is the standard renderer on every platform** (`decidePlatform` in `engine-policy.ts`): on macOS
  because of the numbers above; on Windows (WebView2) and Linux (WebKitGTK) because nothing was measured there, and
  a default does not follow a guess. `auto` asks the page for no WebGL context to decide. `gpu: "on"` tries the
  add-on anywhere and falls back by itself. When somebody measures the add-on faster on a platform, that platform
  returns null from `decidePlatform`, the hardware rule (`decideHardware`) decides for it, and the numbers go here.
- `auto` and `off` are the same renderer on this machine, so the difference between their columns is the noise
  floor of the bench: up to 7% in WebKit and up to 29% in the two Chromium runs.
- **Output slicing (`feed`)**: not added. In WebKit, scenarios A and B show no frame over 50 ms with the seam
  engine and none with this one; xterm already parses in 12 ms slices. `done` stays exactly `term.write`'s callback
  (once per call, in order; `e2e/term-engine.spec.ts` and `e2e/term-integrated.spec.ts` check it).
- Heap after B in Chromium on Metal: 10.1 -> 10.2 MB (`off`), 12.2 MB with the GPU renderer.

## Typing echo (scenario D): `auto` 28 ms against `off` 16 ms is not a difference

The table above shows it again: echo p50 17 ms for the seam engine, 16 for `off`, 28 for `auto`, although `off` and
`auto` draw with the same renderer. Scenario D was run again alone, 9 runs per mode instead of 3, round-robin, with
every sample kept (`raw/echo-webkit-*.json`; WebKit 27.2, load average 4.0 at the start). `probe` is `auto` plus
the throw-away WebGL2 context the first auto rule made to read the renderer's name.

| mode | renderer | p50 of each run, ms | median of those | all samples | their median, ms | within one frame (20 ms or less) | runs that ended in the slow state |
|---|---|---|---|---|---|---|---|
| seam engine | standard | 17, 17, 16, 29, 29, 29, 29, 16, 18 | 18 | 140 | 20.0 | 50% | 5 of 9 |
| gpu off | standard | 17, 26, 29, 17, 16, 29, 16, 28, 17 | 17 | 140 | 18.5 | 51% | 4 of 9 |
| gpu auto | standard | 16, 29, 28, 16, 29, 17, 30, 17, 28 | 28 | 141 | 28.0 | 48% | 5 of 9 |
| gpu auto + the old probe | standard | 17, 17, 30, 28, 16, 16, 16, 17, 17 | 17 | 142 | 17.0 | 63% | 2 of 9 |
| gpu on | gpu | 21, 18, 16, 18, 24, 19, 21, 21, 17 | 19 | 136 | 20.0 | 54% | 0 of 9 |

- A run is not spread around one value. Its first three samples are slow in every mode (medians 56, 29 and 28 ms
  over the 36 standard-renderer runs: the flood starting). After that a sample is either about 16 ms (the next
  frame; 291 of 455 samples, median 16.0) or about 29 ms (146 samples, median 29.0), and a run that has gone to 29
  stays there. A run that changes over before its middle sample reports about 28 ms as its p50; one that changes
  over later, or not at all, reports about 16.
- The seam engine does it too (5 of 9 runs ended in the slow state), as often as `off` (4 of 9) and `auto` (5 of
  9). With three runs per mode the median of p50 is whichever state two of the three were in, so 28 against 16 is
  one run falling the other way. Over all samples `off` and `auto` are level: 51% and 48% within one frame.
- The probe is not the cause: with it, fewer runs ended in the slow state (2 of 9), and `auto` makes no such
  context any more.
- **Not established:** why a run changes state. It happens with the seam commit's engine in place of this one, so
  the engine's changes did not bring it; the rest of the page in that mode is still this branch's, and the seam
  commit's own page was not run here. Whether it is xterm's write queue, WebKit's frame timing under a flood, or
  the bench's own 16 ms typing timer against a 16.7 ms frame was not separated. Also only observed, not explained:
  no `on` run (0 of 9) ended in the slow state.
- For comparing echo across modes, use the share of samples within one frame over many runs, not a median of three.
