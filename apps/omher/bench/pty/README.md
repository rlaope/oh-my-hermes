# PTY flow bench

`run.mjs` builds the shell's tests in release and runs each scenario of `src-tauri/src/pty_bench.rs` three times,
every run in its own process, so one run's memory never counts in the next. Real programs (`/bin/cat` of a
generated 200 MB file, `/usr/bin/yes`) run through the same `Sessions::spawn` a session uses.

```
/usr/bin/lockf -k /tmp/omher-heavy.lock node bench/pty/run.mjs bench/pty/after.json
/usr/bin/lockf -k /tmp/omher-heavy.lock node bench/pty/run.mjs bench/pty/sweep.json --sweep
node bench/pty/run.mjs out.json --only=slice_yes,echo
```

## What stands in for the page (and what this is not)

No webview runs here. The page is a model in Rust, in three forms:

- `sink_*`: the sink itself takes the time for a message, then acknowledges it.
- `page_*`: the sink returns at once, as the Tauri channel's `send` does, and a page thread takes the messages from
  a queue without a limit, spends a fixed time on each, and acknowledges once per 12 ms of work.
- `slice_*`: that page draws 100 MB/s for one 12 ms slice, acknowledges what the slice drew, and waits 4 ms: the
  way xterm 6.0.0 takes its write queue (`WriteBuffer.ts`, `WRITE_TIMEOUT_MS = 12`). 100 MB/s is about what the
  engine lane's render bench had recorded for 20 MB of plain lines in Playwright WebKit on this machine when this
  was written (medians of 194 to 214 ms across its renderer settings). It is a round figure, not a measurement of
  the app.

So these numbers are the shell's (reader, pipe, credit) against a page of a stated speed. None of them is the
app's: `session_ack` has never crossed the real Tauri IPC in a measurement, and no number here was taken in the
Tauri window. Read in xterm's source and not observed here: a write throws and its data is discarded once more than
50 MB wait in xterm's queue (`DISCARD_WATERMARK`).

- before: `f9fab5d17 (the seam commit's shell, unchanged) + the bench`. Its `sessions.rs` is the seam commit's plus
  a test-only counter of bytes read.
- after: `abb724589 + FLOW_HIGH 2 MiB / FLOW_LOW 1 MiB (the tree of the commit that adds this file)`.
- Machine: Darwin 25.6.0 arm64; Apple M4 Pro; 14 cores; 48 GB. Release build. Other lanes' jobs shared the machine
  between runs; the heavy lock keeps them from running beside a bench. Load average at the start: before 10.4, 7.7,
  7.1 (the `slice_*` rows were measured later, 7.1, 8.4, 9.2), after 9.8, 7.2, 7.0.
- Short sleeps run long on this machine under load, and the `sink_*` and `page_*` models sleep for their time per
  message. See "Worse" below for what that does to the slow-page and Ctrl+C rows.
- `baseline.json` and `after.json` were measured before the bench reported message size and time per message for
  the two slow scenarios. Those three numbers are only in `slow-page.json`.

## Result

Medians of 3 runs with the smallest and largest run. "within the spread" means the two sets of runs overlap.

| what | unit | before: median (min to max) | after: median (min to max) | change | |
|---|---|---|---|---|---|
| `yes` 10 s, page takes 20 ms a message: read from the program and not yet drawn | MB | 1,096 (1,084 to 1,107) | 1.25 (1.06 to 1.50) | -99.9% | better |
| same run: most memory the process held | MB | 1,238 (1,232 to 1,259) | 14.9 (14.8 to 14.9) | -98.8% | better |
| same run: drawn | MB/s | 0.96 (0.93 to 1.02) | 0.83 (0.81 to 0.89) | -12.9% | **worse** |
| `yes` 10 s, sink takes 2 ms a message: read and not yet drawn | MB | 1,134 (1,101 to 1,137) | 0.13 (0.13 to 0.13) | -100.0% | better |
| same run: most memory the process held | MB | 1,186 (1,152 to 1,189) | 10.7 (10.7 to 10.7) | -99.1% | better |
| same run: drawn | MB/s | 8.47 (8.23 to 8.54) | 7.93 (7.72 to 8.05) | -6.3% | **worse** |
| Ctrl+C under `yes`, page takes 20 ms a message: until the last byte is drawn | ms | 291,596 (244,000 to 293,682) | 1,480 (1,159 to 1,587) | -99.5% | better |
| same run: drawn after the key | MB | 220 (206 to 225) | 1.25 (1.00 to 1.25) | -99.4% | better |
| Ctrl+C under `yes`, page takes 2 ms a message: until the last byte is drawn | ms | 23,725 (23,277 to 24,835) | 177 (151 to 255) | -99.3% | better |
| same run: drawn after the key | MB | 207 (199 to 215) | 1.25 (1.06 to 1.75) | -99.4% | better |
| Ctrl+C under `yes`, sink takes 2 ms a message: until the last byte is drawn | ms | 29,254 (27,532 to 29,755) | 18.5 (10.7 to 19.7) | -99.9% | better |
| same run: drawn after the key | MB | 237 (234 to 240) | 0.12 (0.10 to 0.12) | -99.9% | better |
| Ctrl+C under `yes`, page draws 100 MB/s in 12 ms slices: until the last byte is drawn | ms | 890 (855 to 912) | 16.7 (16.5 to 17.0) | -98.1% | better |
| same run: drawn after the key | MB | 67.4 (64.7 to 69.1) | 1.33 (1.30 to 1.34) | -98.0% | better |
| `cat` of 200 MB, sink returns at once | MB/s | 158 (152 to 161) | 195 (193 to 201) | +23.1% | better |
| same run: CPU time of the shell's process | ms/MB | 6.24 (6.19 to 6.45) | 3.02 (2.90 to 3.03) | -51.6% | better |
| `yes` 5 s, sink returns at once | MB/s | 111 (110 to 111) | 117 (115 to 117) | +5.1% | better |
| same run: messages handed to the sink | /s | 1,773 (1,758 to 1,777) | 1,864 (1,838 to 1,874) | +5.2% |  |
| `cat` of 200 MB, page draws at once behind a queue | MB/s | 152 (147 to 154) | 207 (202 to 210) | +36.2% | better |
| same run: CPU time of the shell's process | ms/MB | 6.53 (6.46 to 6.77) | 2.89 (2.87 to 2.98) | -55.7% | better |
| `yes` 5 s, page draws at once behind a queue | MB/s | 110 (107 to 110) | 114 (112 to 116) | +4.4% | better |
| same run: messages handed to the sink | /s | 1,751 (1,706 to 1,755) | 1,829 (1,794 to 1,855) | +4.5% |  |
| `cat` of 200 MB, page draws 100 MB/s in 12 ms slices | MB/s | 75.4 (75.3 to 75.7) | 75.4 (75.2 to 75.5) | -0.1% | unchanged (under 1%) |
| same run: CPU time of the shell's process (the page's busy drawing counts in it) | ms/MB | 19.8 (19.6 to 19.8) | 16.3 (16.2 to 16.3) | -17.8% |  |
| `yes` 5 s, page draws 100 MB/s in 12 ms slices | MB/s | 75.7 (75.7 to 75.7) | 75.7 (75.5 to 75.7) | +0.0% | unchanged (under 1%) |
| same run: messages handed to the sink | /s | 1,735 (1,726 to 1,741) | 1,213 (1,213 to 1,219) | -30.1% |  |
| one keystroke's echo, 200 keys: median | ms | 15.7 (15.0 to 19.1) | 15.4 (14.9 to 16.1) | -1.8% | within the spread |
| same run: p95 | ms | 20.1 (20.1 to 20.1) | 20.1 (20.1 to 20.1) | -0.1% | unchanged (under 1%) |

## Worse: the rate drawn through a slow page

Two rows are worse, and their runs do not overlap. `slow-page.json` has both scenarios again, before and after run
alternately in one turn so the machine was the same for both, with the page's time per message once as a sleep (as
in the table above) and once as busy time, which is exact. No runner for it is in the repo. The after half is `node
bench/pty/run.mjs out.json --only=sink_slow_2ms,page_slow_20ms`, with and without `OMHER_PTY_BENCH_BUSY_PAGE=1`.
The before half is the same bench file in a copy of the seam commit's `src-tauri` with `ack` and `sessions` as
stubs, as for `baseline.json`. Both were built, each test program copied aside, and the runs taken in turn:

| page model | time per message is | shell | drawn MB/s | mean message KB | ms per message | of it in the page |
|---|---|---|---|---|---|---|
| sink takes 2 ms a message | a sleep | before | 8.47 (8.25 to 8.60) | 64.0 (64.0 to 64.0) | 7.38 (7.27 to 7.58) | 7.36 (7.25 to 7.57) |
| sink takes 2 ms a message | a sleep | after | 7.81 (7.78 to 7.91) | 64.0 (64.0 to 64.0) | 8.01 (7.91 to 8.03) | 7.95 (7.86 to 7.97) |
| sink takes 2 ms a message | busy time (exact) | before | 31.1 (31.1 to 31.1) | 64.0 (64.0 to 64.0) | 2.01 (2.01 to 2.01) | 2.00 (2.00 to 2.00) |
| sink takes 2 ms a message | busy time (exact) | after | 31.2 (31.2 to 31.2) | 64.0 (64.0 to 64.0) | 2.00 (2.00 to 2.00) | 2.00 (2.00 to 2.00) |
| page takes 20 ms a message | a sleep | before | 1.11 (1.04 to 1.15) | 64.0 (64.0 to 64.0) | 56.6 (54.2 to 60.3) | 56.5 (53.9 to 59.9) |
| page takes 20 ms a message | a sleep | after | 0.68 (0.66 to 0.72) | 61.2 (61.1 to 61.4) | 87.8 (83.2 to 90.5) | 87.5 (83.0 to 90.2) |
| page takes 20 ms a message | busy time (exact) | before | 3.12 (3.12 to 3.12) | 64.0 (64.0 to 64.0) | 20.0 (20.0 to 20.0) | 20.0 (20.0 to 20.0) |
| page takes 20 ms a message | busy time (exact) | after | 2.96 (2.95 to 2.96) | 60.6 (60.6 to 60.6) | 20.0 (20.0 to 20.0) | 20.0 (20.0 to 20.0) |

- With the page's time exact, the 2 ms sink is not slower (+0.4%). The 20 ms page is 5.3% slower, and all of it is
  message size: the time per message is the same (20.0 and 20.0 ms) and the mean message is 60.6 KB instead of 64.0
  (-5.4%). This page model costs a fixed time per message whatever its size, so smaller messages are fewer bytes a
  second.
- Why the messages are smaller, read in the code and not measured apart: when the reader stops at the high mark,
  the message it was filling is handed on short once the 4 ms window ends. A session whose page acknowledges inside
  the sink (`sink_*`) never reaches the mark, and its messages stay 64 KB.
- With the page's time as a sleep, the sleep itself took longer after than before: a 2 ms sleep 7.36 ms before and
  7.95 ms after, a 20 ms sleep 56.5 ms before and 87.5 ms after. That is where the rest of the lower rate is (-7.9%
  and -38.4% in this run, -6.3% and -12.9% in the table above): time inside the page model's own sleep, not in the
  shell. Why a sleep runs longer in the process whose reader is mostly waiting is **not established**. One guess (a
  busy sibling thread keeps the process's timers prompt) was tried in a C probe and not borne out.
- The same sleep is in every `*_interrupt_2ms` and `*_interrupt_20ms` time: those rows say how many seconds a page
  of that nominal speed took here, and the MB beside them say how much it had to draw.

Not fixed. One thing to try is to fill the message under way before the reader stops. It is untried, and it changes
what a session can have undrawn.

## The marks: 2 MiB high, 1 MiB low

`sweep.json`, on the tree of the commit that added the credit; each pair was set through `OMHER_PTY_BENCH_MARKS`.
Medians of 3.

| high / low | `yes` into the 100 MB/s page, MB/s | against no limit | Ctrl+C, that page: ms | Ctrl+C, 20 ms page: MB drawn after the key | and ms |
|---|---|---|---|---|---|
| 256 KiB / 64 KiB | 38.5 (38.5 to 38.5) | -49.2% | 5.00 (3.50 to 7.25) | 0.12 (0.06 to 0.21) | 293 (128 to 441) |
| 512 KiB / 128 KiB | 55.5 (55.4 to 55.6) | -26.6% | 8.32 (6.86 to 8.42) | 0.12 (0.06 to 0.50) | 315 (283 to 781) |
| 1 MiB / 256 KiB | 71.3 (71.2 to 71.4) | -5.8% | 4.96 (4.86 to 5.15) | 0.44 (0.44 to 0.50) | 748 (678 to 879) |
| 1 MiB / 512 KiB | 71.3 (71.2 to 71.3) | -5.8% | 4.54 (4.04 to 5.28) | 0.75 (0.63 to 0.81) | 1,327 (1,118 to 1,359) |
| 2 MiB / 512 KiB | 72.9 (72.8 to 72.9) | -3.7% | 10.7 (5.72 to 15.5) | 0.56 (0.50 to 0.62) | 932 (921 to 1,028) |
| 2 MiB / 1 MiB **(chosen)** | 75.5 (75.5 to 75.6) | -0.2% | 12.1 (11.5 to 16.1) | 1.69 (1.56 to 1.69) | 2,559 (2,411 to 2,580) |
| 4 MiB / 1 MiB | 75.7 (75.6 to 75.7) | -0.0% | 17.9 (12.4 to 22.5) | 2.56 (2.50 to 2.63) | 3,756 (2,968 to 3,765) |
| 8 MiB / 2 MiB | 75.7 (75.6 to 75.7) | -0.0% | 33.8 (26.3 to 84.3) | 6.50 (6.44 to 6.56) | 9,512 (7,842 to 9,552) |
| no limit (before) | 75.7 (75.7 to 75.7) | | 890 (855 to 912) | 220 (206 to 225) | 291,596 (244,000 to 293,682) |

- 2 MiB / 1 MiB is the smallest pair that feeds the fast page within 0.2% of no limit (0.18% under). The best
  smaller pair reaches 72.9 MB/s.
- What a bigger pair costs is what a page still has to draw after Ctrl+C. At 2 MiB / 1 MiB that was 1.00 to 1.69 MB
  over six runs (three in the sweep, three in `after.json`), which is 16 to 27 messages of 64 KiB: the key lands
  somewhere between the low mark (16 messages) and the high one (32).
- The seconds for the 20 ms page differ between the two files at the same marks: 2,559 (2,411 to 2,580) ms in the
  sweep, 1,480 (1,159 to 1,587) in `after.json`. Both parts moved: more messages were outstanding in the sweep's
  runs (25 to 27 against 16 to 20), and each took longer (94.7 to 96.3 ms against 72.4 to 79.3, for a nominal 20).
  The second part is the sleep described above. It was not run again with the page's time exact, so the seconds a
  20 ms page needs after Ctrl+C at these marks are not known better than that.

## Not measured

- The app. The Tauri window, WKWebView's real drawing speed, the cost of a `session_ack` call over the real IPC.
- A window that is hidden or whose page the system has suspended: a page that stops drawing stops the program once
  2 MiB are unacknowledged, where before the program ran on and memory grew.
- Windows (ConPTY) and Linux. The bench and every test that starts a program are unix-only; macOS is the only place
  they ran.
