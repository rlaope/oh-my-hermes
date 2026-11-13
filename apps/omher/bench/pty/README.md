# PTY flow bench

`run.mjs` builds the shell's tests in release and runs each scenario of `src-tauri/src/pty_bench.rs` three times,
every run in its own process, so one run's memory never counts in the next. Real programs (`/bin/cat` of a
generated 200 MB file, `/usr/bin/yes`) run through the same `Sessions::spawn` a session uses.

```
OMHER_PTY_BENCH_BUSY_PAGE=1 /usr/bin/lockf -k /tmp/omher-heavy.lock node bench/pty/run.mjs bench/pty/after.json
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
  render bench recorded for 20 MB of plain lines in Playwright WebKit on this machine when the model was written
  (medians of 194 to 214 ms). It is a round figure, not a measurement of the app.

So these numbers are the shell's (reader, pipe, credit) against a page of a stated speed. None of them is the
app's: `session_ack` has never crossed the real Tauri IPC in a measurement, and no number here was taken in the
Tauri window. Read in xterm's source and not observed here: a write throws and its data is discarded once more than
50 MB wait in xterm's queue (`DISCARD_WATERMARK`).

- before (`baseline.json`): `f9fab5d17 (the seam commit's shell, unchanged) + the bench; page time is busy time`.
  Its `sessions.rs` is the seam commit's plus a test-only counter of bytes read.
- after (`after.json`): `a61590199 (the merge of main and the three lanes) with one uncommitted change, a bundle
  resource added in tauri.conf.json`. The files the bench exercises (`sessions.rs`, `pty_bench.rs`, `lib.rs`,
  `Cargo.toml`, `Cargo.lock`, `bench/pty/run.mjs`) are the same at the head of the pull request. Other files of the
  same crate are not: a later merge of main changed the chat adapters (`agent_chat.rs` and two more), which the
  bench does not run. The alternated run below was taken after that merge (`3f0f41947`).
- The page's time per message is **busy time** in both (`OMHER_PTY_BENCH_BUSY_PAGE=1`), not a sleep: under load
  this machine stretches a 2 ms sleep to 7 or 8 ms and a 20 ms sleep to 55 to 90 ms, which put the machine's timers
  into every slow-page and Ctrl+C number. The flow lane's first pair of files used sleeps; they are in this
  folder's history (commit `d10ae8413`) and `slow-page.json` keeps the comparison of the two.
- Machine: Darwin 25.6.0 arm64; Apple M4 Pro; 14 cores; 48 GB. Release build. Other work shared the machine; the
  heavy lock keeps another bench or test run from running beside this one. Load average at the start: before 6.8,
  5.3, 5.7, after 6.3, 5.1, 5.4. Before and after ran one after the other in one turn with the lock (3 runs of each
  scenario), except the rows under "Run alternately".

## Result

Medians of 3 runs with the smallest and largest run. "within the spread" means the two sets of runs overlap.

| what | unit | before: median (min to max) | after: median (min to max) | change | |
|---|---|---|---|---|---|
| `yes` 10 s, page takes 20 ms a message: read from the program and not yet drawn | MB | 1,068 (1,067 to 1,071) | 1.81 (1.75 to 1.81) | -99.8% | see "Run alternately" |
| same run: most memory the process held | MB | 1,211 (1,205 to 1,211) | 15.2 (15.2 to 15.2) | -98.7% | see "Run alternately" |
| same run: drawn | MB/s | 3.12 (3.12 to 3.12) | 2.96 (2.96 to 2.96) | -5.3% | see "Run alternately" |
| same run: mean message | KB | 64.0 (64.0 to 64.0) | 60.6 (60.6 to 60.6) | -5.3% |  |
| same run: time per message | ms | 20.0 (20.0 to 20.0) | 20.0 (20.0 to 20.0) | +0.0% |  |
| same run: of it in the page | ms | 20.0 (20.0 to 20.0) | 20.0 (20.0 to 20.0) | +0.0% |  |
| `yes` 10 s, sink takes 2 ms a message: read and not yet drawn | MB | 902 (893 to 904) | 0.12 (0.09 to 0.13) | -100.0% | better |
| same run: most memory the process held | MB | 945 (937 to 948) | 10.8 (10.7 to 10.8) | -98.9% | better |
| same run: drawn | MB/s | 31.0 (31.0 to 31.1) | 31.2 (31.2 to 31.2) | +0.4% | unchanged (under 1%) |
| same run: mean message | KB | 64.0 (64.0 to 64.0) | 64.0 (64.0 to 64.0) | -0.1% |  |
| same run: time per message | ms | 2.02 (2.01 to 2.02) | 2.01 (2.00 to 2.01) | -0.4% |  |
| same run: of it in the page | ms | 2.00 (2.00 to 2.00) | 2.00 (2.00 to 2.00) | +0.0% |  |
| Ctrl+C under `yes`, page takes 20 ms a message: until the last byte is drawn | ms | 69,188 (67,486 to 74,943) | 341 (340 to 352) | -99.5% | better |
| same run: drawn after the key | MB | 216 (211 to 234) | 1.00 (0.95 to 1.00) | -99.5% | better |
| Ctrl+C under `yes`, page takes 2 ms a message: until the last byte is drawn | ms | 5,329 (5,288 to 5,331) | 46.1 (33.8 to 52.6) | -99.1% | better |
| same run: drawn after the key | MB | 167 (165 to 167) | 1.38 (0.94 to 1.62) | -99.2% | better |
| Ctrl+C under `yes`, sink takes 2 ms a message: until the last byte is drawn | ms | 6,130 (5,950 to 6,135) | 5.28 (5.00 to 5.37) | -99.9% | better |
| same run: drawn after the key | MB | 190 (185 to 190) | 0.12 (0.12 to 0.13) | -99.9% | better |
| Ctrl+C under `yes`, page draws 100 MB/s in 12 ms slices: until the last byte is drawn | ms | 403 (2.84 to 733) | 16.4 (11.6 to 17.4) | -95.9% | see "Run alternately" |
| same run: drawn after the key | MB | 30.7 (0.25 to 55.4) | 1.25 (0.92 to 1.37) | -95.9% | see "Run alternately" |
| `cat` of 200 MB, sink returns at once | MB/s | 154 (152 to 158) | 204 (199 to 208) | +32.6% | better |
| same run: CPU time of the shell's process | ms/MB | 6.47 (6.32 to 6.53) | 2.90 (2.86 to 2.95) | -55.2% | better |
| `yes` 5 s, sink returns at once | MB/s | 111 (111 to 112) | 117 (114 to 117) | +5.0% | better |
| same run: messages handed to the sink | /s | 1,781 (1,776 to 1,783) | 1,871 (1,827 to 1,880) | +5.0% |  |
| `cat` of 200 MB, page draws at once behind a queue | MB/s | 150 (150 to 151) | 202 (198 to 209) | +34.4% | better |
| same run: CPU time of the shell's process | ms/MB | 6.64 (6.64 to 6.64) | 3.01 (2.88 to 3.05) | -54.7% | better |
| `yes` 5 s, page draws at once behind a queue | MB/s | 108 (107 to 110) | 116 (115 to 116) | +7.3% | better |
| same run: messages handed to the sink | /s | 1,729 (1,705 to 1,762) | 1,856 (1,848 to 1,857) | +7.4% |  |
| `cat` of 200 MB, page draws 100 MB/s in 12 ms slices | MB/s | 75.6 (75.5 to 75.7) | 75.7 (75.6 to 75.7) | +0.1% | unchanged (under 1%) |
| same run: CPU time of the shell's process (the page's busy drawing counts in it) | ms/MB | 19.8 (19.7 to 19.8) | 16.1 (16.0 to 16.1) | -18.8% |  |
| `yes` 5 s, page draws 100 MB/s in 12 ms slices | MB/s | 75.7 (70.6 to 75.7) | 75.7 (75.7 to 75.7) | -0.0% | unchanged (under 1%) |
| same run: messages handed to the sink | /s | 1,676 (1,138 to 1,710) | 1,214 (1,214 to 1,215) | -27.5% |  |
| one keystroke's echo, 200 keys: median | ms | 31.8 (30.7 to 32.6) | 23.2 (23.2 to 23.9) | -26.9% | see "Run alternately" |
| same run: p95 | ms | 36.1 (35.9 to 36.1) | 36.0 (35.9 to 36.0) | -0.0% | see "Run alternately" |

## Run alternately

Three scenarios were run again with the seam shell and the integrated head taking turns (5 runs each,
`interleaved.json`; both test programs built first and copied aside, since the two trees build to one path in a
shared target folder). Whatever the machine does to timers at a given minute then hits both the same.

| what | unit | before: median (min to max) | after: median (min to max) | change | |
|---|---|---|---|---|---|
| `yes` 10 s, page takes 20 ms a message: read from the program and not yet drawn | MB | 1,053 (1,049 to 1,055) | 1.75 (1.75 to 1.88) | -99.8% | better |
| the 20 ms page run: most memory the process held | MB | 1,201 (1,191 to 1,205) | 15.2 (15.2 to 15.5) | -98.7% | better |
| the 20 ms page run: drawn | MB/s | 3.12 (3.12 to 3.12) | 2.96 (2.95 to 2.96) | -5.3% | **worse** |
| the 20 ms page run: mean message | KB | 64.0 (64.0 to 64.0) | 60.6 (60.6 to 60.6) | -5.3% |  |
| the 20 ms page run: time per message | ms | 20.0 (20.0 to 20.0) | 20.0 (20.0 to 20.1) | -0.1% |  |
| the 20 ms page run: of it in the page | ms | 20.0 (20.0 to 20.0) | 20.0 (20.0 to 20.0) | +0.0% |  |
| Ctrl+C under `yes`, page draws 100 MB/s in 12 ms slices: until the last byte is drawn | ms | 865 (600 to 887) | 13.6 (11.7 to 16.4) | -98.4% | better |
| the Ctrl+C run: drawn after the key | MB | 65.6 (45.4 to 67.4) | 1.00 (0.88 to 1.29) | -98.5% | better |
| one keystroke's echo, 200 keys: median | ms | 31.7 (30.3 to 32.9) | 31.1 (30.2 to 33.3) | -2.0% | within the spread |
| the echo run: p95 | ms | 35.9 (35.8 to 36.1) | 36.0 (35.8 to 36.1) | +0.2% | unchanged (under 1%) |

- **A keystroke's echo is not faster.** In the table above its median is -26.9% and the two sets of runs do not
  overlap, which would read as a gain. Run alternately it is -2.0% and the runs overlap. The same shell gave 31.7
  ms here and 15.7 ms in the flow lane's run on this machine some hours earlier, so the figure moves more between
  sittings than between the two shells; a difference between two sets of runs taken minutes apart is not evidence.
  Why it sits so far above the 4 ms window (the lane's reading: the machine stretches a short wait) was not
  measured apart. p95 is the same in every run.
- **The other rows marked "better" in the first table were not run alternately.** They rest on two sets of runs
  taken one after the other, the kind of comparison that misread the echo. For the slow pages and Ctrl+C the
  difference is 70 to 1,000 times, far outside anything the machine does between sittings. For a sink that returns
  at once it is not: `cat` is +32.6% with the shell's CPU time per MB at 2.90 ms against 6.47, and `yes` is +5.0%.
  The flow lane's own run, hours earlier, had the same direction (+23.1%, 3.02 against 6.24 ms, +5.1%), so two
  sittings agree, but no alternated run backs these rows and no cause was isolated.
- **Ctrl+C against the fast page** holds: 865 ms and 65.6 MB still to draw before, 13.6 ms and 1.00 MB after. The
  before figure depends on how far `yes` got ahead of the page in the two seconds before the key, and that varies
  with the machine: one of the three runs in the table above had almost no backlog.

## Worse: the rate drawn through a 20 ms page

One number is worse. A page that takes 20 ms for every message, whatever its size, draws 5.3% fewer bytes a second
(3.12 to 2.96 MB/s), and all of it is message size: the time per message is the same (20.0 and 20.0 ms) and the
mean message is 60.6 KB instead of 64.0 (-5.3%). The 2 ms sink is not slower (+0.4%): a session whose page
acknowledges inside the sink never reaches the high mark, and its messages stay 64 KB.

- Why the messages are smaller, read in the code and not measured apart: when the reader stops at the high mark,
  the message it was filling is handed on short once the 4 ms window ends.
- Not fixed. One thing to try is to fill the message under way before the reader stops. It is untried, and it
  changes what a session can have undrawn.
- This is a page model with a fixed cost per message. xterm's cost is per byte (the `slice_*` model), and there the
  rate is unchanged.

The flow lane measured the same two scenarios with the page's time once as a sleep and once as busy time, seam and
new shell alternately (`slow-page.json`, on its own tree; no runner for it is in the repo):

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

With the time as a sleep the sleep itself ran longer in the new shell's process (a 2 ms sleep 7.36 ms before and
7.95 ms after, a 20 ms sleep 56.5 ms before and 87.5 ms after), which made both rates look worse than they are. Why
a sleep runs longer in the process whose reader is mostly waiting is **not established**: one guess (a busy sibling
thread keeps the process's timers prompt) was tried in a C probe and not borne out. That is why `baseline.json` and
`after.json` now use busy time.

## The marks: 2 MiB high, 1 MiB low

`sweep.json`, measured by the flow lane on the tree of the commit that added the credit (not run again here); each
pair was set through `OMHER_PTY_BENCH_MARKS`. Medians of 3. Its 20 ms page column used a sleep for the page's time,
and its "no limit" row is the lane's first baseline.

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

- 2 MiB / 1 MiB is the smallest pair that feeds the fast page within 0.2% of no limit. The best smaller pair
  reaches 72.9 MB/s.
- What a bigger pair costs is what a page still has to draw after Ctrl+C: between the low mark (16 messages of 64
  KiB) and the high one (32).
- The seconds in the last column are stretched by the sleep. With the page's time exact (`after.json`) a 20 ms page
  at these marks finishes 341 (340 to 352) ms after Ctrl+C, having 1.00 (0.95 to 1.00) MB still to draw: 16
  messages of 20 ms.

## Not measured

- The app. The Tauri window, WKWebView's real drawing speed, the cost of a `session_ack` call over the real IPC.
- A window that is hidden or whose page the system has suspended: a page that stops drawing stops the program once
  2 MiB are unacknowledged, where before the program ran on and memory grew. (That a session which is merely not
  the one on screen keeps acknowledging is checked in the page, `e2e/term-integrated.spec.ts`, against the mock
  host.)
- Windows (ConPTY) and Linux. The bench and every test that starts a program are unix-only; macOS is the only place
  they ran.
