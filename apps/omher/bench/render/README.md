# Terminal render bench

`bench.mjs` opens omher on the mock host, opens a Claude Code session as a terminal and feeds the terminal through
the real `feed()` of `src/sessions/term/engine.ts`. It is a Playwright script, not part of the e2e suite.

```
OMHER_PORT=5385 OMHER_MOCK_PORT=5386 /usr/bin/lockf -k /tmp/omher-heavy.lock \
  node bench/render/bench.mjs --engine webkit|chromium-metal|chromium --modes seam,off,on,auto --label final --runs 3
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

## Engines (and what they are not)

- `webkit`: Playwright WebKit 27.2. The macOS app runs in WKWebView, which is WebKit, so macOS decisions follow these
  numbers. Its WebGL is the Apple GPU.
- `chromium-metal`: the full Chromium build (`channel: "chromium"`), WebGL is ANGLE on Metal (the GPU).
- `chromium`: Playwright's headless shell. Its WebGL is **SwiftShader, software**: `on` is slow here because the GL is
  software. It stands for a machine without a GPU, not for the app.
- None of them is the Tauri window. Not measured: WebView2 (Windows), WebKitGTK (Linux).
- Machine: Apple M4 Pro, macOS 26.6.2. Other lanes' jobs shared the machine between runs (load average 4 to 5 at
  the start of each engine's run); the heavy lock keeps them from running at the same time as a bench.
- `raw/baseline-*.json` is an earlier, independent baseline of the seam engine (scenarios A to D, not round-robin).
  It agrees with `baseline.json` within the spread.

## Result

Each cell: wall ms until the last write callback, frames over 50 ms ("slow"), worst frame gap in ms; medians of 3. "change" is the wall time against the seam engine. Min and max are in `raw/` and `after.json`.

**webkit** 27.2, Apple M4 Pro, darwin 25.6.0, load average 4.3 at start; `gpu: auto` drew with: standard

| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |
|---|---|---|---|---|---|---|---|
| A | 214 ms, 0 slow, worst 41 | 214 ms, 0 slow, worst 40 | +0% | 194 ms, 0 slow, worst 41 | -9% | 206 ms, 0 slow, worst 38 | -4% |
| B | 402 ms, 1 slow, worst 55 | 412 ms, 1 slow, worst 54 | +2% | 405 ms, 1 slow, worst 54 | +1% | 378 ms, 1 slow, worst 61 | -6% |
| C | 128 ms, 0 slow, worst 35 | 128 ms, 0 slow, worst 46 | +0% | 129 ms, 0 slow, worst 36 | +1% | 369 ms, 4 slow, worst 132 | +188% |
| C2 | 120 ms, 0 slow, worst 25 | 133 ms, 0 slow, worst 26 | +11% | 131 ms, 0 slow, worst 27 | +9% | 279 ms, 2 slow, worst 98 | +133% |
| C3 | 125 ms, 0 slow, worst 31 | 112 ms, 0 slow, worst 34 | -10% | 111 ms, 0 slow, worst 46 | -11% | 128 ms, 1 slow, worst 53 | +2% |
| D | 442 ms, 1 slow, worst 51 | 430 ms, 0 slow, worst 49 | -3% | 431 ms, 0 slow, worst 48 | -2% | 384 ms, 2 slow, worst 69 | -13% |

Typing echo (D), median feed-to-frame ms / p95, and JS heap after the run:

| | before (seam) | gpu off | gpu auto | gpu on |
|---|---|---|---|---|
| echo p50 / p95 | 17 / 55 | 16 / 54 | 28 / 55 | 21 / 67 |
| heap after B | n/a | n/a | n/a | n/a |

**chromium-metal** 158.0.8127.18, Apple M4 Pro, darwin 25.6.0, load average 5.1 at start; `gpu: auto` drew with: standard

| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |
|---|---|---|---|---|---|---|---|
| A | 342 ms, 4 slow, worst 67 | 379 ms, 2 slow, worst 67 | +11% | 394 ms, 3 slow, worst 67 | +15% | 421 ms, 5 slow, worst 83 | +23% |
| B | 401 ms, 3 slow, worst 67 | 425 ms, 2 slow, worst 67 | +6% | 434 ms, 6 slow, worst 67 | +8% | 447 ms, 3 slow, worst 67 | +11% |
| C | 193 ms, 2 slow, worst 67 | 171 ms, 2 slow, worst 67 | -11% | 190 ms, 1 slow, worst 67 | -2% | 445 ms, 5 slow, worst 100 | +131% |
| C2 | 214 ms, 2 slow, worst 67 | 202 ms, 3 slow, worst 67 | -6% | 231 ms, 1 slow, worst 67 | +8% | 273 ms, 2 slow, worst 83 | +28% |
| C3 | 190 ms, 2 slow, worst 67 | 185 ms, 3 slow, worst 67 | -3% | 193 ms, 1 slow, worst 67 | +2% | 208 ms, 2 slow, worst 83 | +9% |
| D | 404 ms, 2 slow, worst 67 | 362 ms, 1 slow, worst 67 | -10% | 385 ms, 2 slow, worst 67 | -5% | 473 ms, 3 slow, worst 67 | +17% |

Typing echo (D), median feed-to-frame ms / p95, and JS heap after the run:

| | before (seam) | gpu off | gpu auto | gpu on |
|---|---|---|---|---|
| echo p50 / p95 | 37.8 / 86.8 | 28.9 / 69.4 | 39.8 / 78.2 | 45.5 / 94.5 |
| heap after B | 9.8 MB | 9.9 MB | 10.1 MB | 11.9 MB |

**chromium** 158.0.8127.18, Apple M4 Pro, darwin 25.6.0, load average 4.9 at start; `gpu: auto` drew with: standard

| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |
|---|---|---|---|---|---|---|---|
| A | 352 ms, 2 slow, worst 67 | 377 ms, 3 slow, worst 67 | +7% | 359 ms, 2 slow, worst 67 | +2% | 803 ms, 7 slow, worst 83 | +128% |
| B | 412 ms, 2 slow, worst 67 | 415 ms, 3 slow, worst 83 | +1% | 411 ms, 3 slow, worst 67 | 0% | 697 ms, 7 slow, worst 67 | +69% |
| C | 186 ms, 2 slow, worst 67 | 172 ms, 1 slow, worst 50 | -8% | 208 ms, 2 slow, worst 83 | +12% | 518 ms, 7 slow, worst 100 | +178% |
| C2 | 201 ms, 2 slow, worst 67 | 204 ms, 2 slow, worst 67 | +1% | 234 ms, 2 slow, worst 67 | +16% | 478 ms, 7 slow, worst 100 | +138% |
| C3 | 153 ms, 0 slow, worst 50 | 170 ms, 1 slow, worst 50 | +11% | 199 ms, 1 slow, worst 67 | +30% | 409 ms, 4 slow, worst 67 | +167% |
| D | 413 ms, 4 slow, worst 67 | 386 ms, 4 slow, worst 67 | -7% | 420 ms, 4 slow, worst 83 | +2% | 836 ms, 7 slow, worst 84 | +102% |

Typing echo (D), median feed-to-frame ms / p95, and JS heap after the run:

| | before (seam) | gpu off | gpu auto | gpu on |
|---|---|---|---|---|
| echo p50 / p95 | 38.1 / 84 | 38 / 85.2 | 46.5 / 89.7 | 44.9 / 102.4 |
| heap after B | 9.6 MB | 9.7 MB | 9.8 MB | 11.4 MB |

## Reading it

- **Standard renderer, seam against this branch (`off`)**: no change beyond the run-to-run spread in any scenario
  in WebKit (-10 % to +11 %, the same size as the spread between runs). The Unicode 11 add-on costs nothing
  measurable.
- **GPU renderer (`on`) in WebKit, the macOS engine**: 4 to 13 % faster on streaming text (A, B, D), but 2.3 to 2.9
  times slower on a full-screen redraw with many colours (C: 128 -> 369 ms, C2: 120 -> 279 ms) and 4 frames over 50 ms
  where the standard renderer has none. With a TUI-sized palette (C3) it is level. Typing echo p50 is 16 ms with the
  standard renderer and 21 ms with the GPU.
- **Chromium on Metal**: `on` is slower or level in every scenario (C +131 %, D +17 %).
- **`gpu: "auto"` therefore stays on the standard renderer on macOS** (`decideWebgl` in `engine-policy.ts`), so
  no scenario is worse with `auto` than with `off` on this machine: the two are the same renderer and their
  difference in the table is the noise floor. Everywhere else `auto` uses the add-on when WebGL2 is there and the
  renderer is not a software one; that was not measured on Windows or Linux, and the add-on is not a measured win
  there either. `gpu: "on"` is the person's choice to use it.
- **Output slicing (`feed`)**: not added. In WebKit, scenarios A and B show 0 to 1 frames over 50 ms and a worst
  gap of 55 ms with the seam engine and the same with this one; xterm already parses in 12 ms slices. In
  Chromium's headless shell 2 to 4 frames of 67 to 83 ms appear per 0.4 s flood, on both engines. Slicing in `feed`
  would trade the flood's 0.2 to 0.4 s wall time for smoothness the macOS engine does not need. `done` stays exactly
  `term.write`'s callback (once per call, in order; `e2e/term-engine.spec.ts` checks it).
- Heap after B in Chromium: 9.6 -> 9.7 MB (`off`), 11.4 MB with the GPU renderer.
