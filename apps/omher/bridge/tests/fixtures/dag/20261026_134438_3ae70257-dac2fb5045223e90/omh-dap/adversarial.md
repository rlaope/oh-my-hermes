# omh-dap / adversarial: handoff

Verdict: **fix_first**. Cases a-i, the ones in the brief, all PASS against real debugpy 1.8.22. I also ran an extra case, j, outside the brief. It found two defects, and both have cheap fixes (below).

Tree: worktree dap-nav at HEAD d9f0b36a9, read-only (no repo edits). The real `debug_python_handler` ran under the scratch venv python (debugpy 1.8.22, Python 3.13.15) with `PYTHONPATH=<worktree>/src`. OMH_LSP_TOOLS, OMH_HASHLINE_TOOLS, OMH_DAP_TOOLS, PYTHONPATH and HERMES_HOME were unset (`run.sh`). The root comes from `TERMINAL_CWD` (the handler's fallback when no Hermes tree is present). No paid calls were made.

Command for each case: `cd ~/.hermes/profiles/kami/cache/scratch/dap-adv && ./run.sh <x>`. It runs `case_<x>.py` and writes `logs/<x>.log`, whose last line is `EXIT <rc>`.

| case | what | exit | result | output tail (literal, trimmed) |
|---|---|---|---|---|
| a | `../`, absolute path outside the root, `/etc/hosts`, file symlink, dir symlink, `src/../../` as program and as breakpoint path | 0 | PASS 11/11 | `{"ok": false, "error": "scope_mismatch", "hint": "'link_out.py' resolves outside the workspace root ..."}`; `a:no adapter launched before=[] after=[]` |
| b | missing, non-exec, directory, empty, int, `/usr/bin/python3` (no debugpy), `/bin/echo`, `/usr/bin/true` | 0 | PASS 10/10 | missing/non-exec/dir/empty/int -> `invalid_argument` in 0.0s; `/usr/bin/python3` -> `adapter_unavailable` in 0.2s with `stderr_tail: "...No module named 'debugpy'"`; echo/true -> `adapter_unavailable` in 0.0s; `before=[] after=[]` |
| c | `while True: pass`, no breakpoint, launch timeout=25 | 0 | PASS 11/11 | launch -> `timeout` in 28.0s; continue(5) -> `timeout` in 5.0s; inspect/step -> `not_stopped`; terminate in 2.0s, `output_tail: "spinning\n"`; no adapter and no spin.py left; then `no_session` |
| d | 1 MB of lines + one 5 MB write, then a breakpoint | 0 | PASS 6/6 | stop reply len=170; `session ring <= 64KB ring=65536`; exit reply len=2064, tail_len=2000 |
| e | 10k list, 1 MB str, 5k dict, 100 locals | 0 | PASS 11/11 | inspect: 40 locals, `locals_omitted=63`, max repr 200, reply 1279 B; evaluate `s` -> 2041 B; `1/0` -> `adapter_error "ZeroDivisionError: division by zero"`, session survives; frame 99 -> `invalid_argument` |
| f | second launch, same task_id; tasks A and B in different roots | 0 | PASS 13/13 | 2nd launch -> `session_active` in 0.0s, still 1 adapter; A `cart=[1, 2]`, B `cart=[70, 80]`; roots pinned per session; distinct adapter pids; terminating A leaves B ok |
| g | SIGKILL the adapter while stopped | 0 | PASS 8/8 | inspect -> `adapter_error "the debug adapter exited: ... Broken pipe"` in 0.0s; later calls -> `no_session`; no orphaned launcher/debuggee; relaunch stops at line 9 in 3.3s |
| h | gate | 0 | PASS 13/13 | off for: no env + empty/missing/other-setting/`dap_tools: off` config, and env `0`/`false`/``/`2`; on for env `1`/` YES ` and profile `dap_tools: true`; `register_tool(... check_fn=_dap_tools_enabled)`, toolset `omh-dap` |
| i | AST import/spawn scan | 0 | PASS 14/14 | client: `[collections, itertools, json, queue, subprocess, threading, time, typing]`; session/tool: no subprocess, no network imports, no dynamic imports; exactly one `subprocess.Popen(list(argv), ..., shell=False)`; argv `[python, "-m", "debugpy.adapter"]` |
| j (extra) | output flood while running; two launches on the same task_id at once | 1 | **FAIL 3/7** | `client._output after 20s launch timeout = 241397098 bytes`, then `363545891`; `j2 results: ['ok', 'ok'] adapters live: 2`; after terminate: `['80778 ... -m debugpy.adapter']` |

Case f failed on the first run (10/11) because of my fixture: `cart = add(p)` overwrites the marker. I fixed the fixture and reran f: 13/13.

## Defects

1. **Output buffer is unbounded while the program runs** (`dap_client.DapClient._sort` appends to `self._output` with no cap; the 64 KB ring is applied only in `Session.collect_output` at stop/exit). A program that prints in a loop and never stops grows the Hermes process by about 12 MB/s: 241 MB after a 20 s launch, 364 MB 10 s later. The maximum timeout is 180 s, so that is about 2 GB per call. Replies stay bounded, so only memory is at risk.
   Repro: `flood.py` = `import sys\nwhile True: sys.stdout.write('F'*65536+'\n')`; `launch(program=flood.py, timeout=20)`; then `len(''.join(SESSIONS._sessions['t1'].client._output))`.
   Fix: trim `_output` in `_sort` to the last OUTPUT_RING characters (keep a running size, like `_stderr`).
2. **Two launches racing on the same task_id leak an adapter and its debuggee.** `SessionManager.launch` checks `key in self._sessions` under the lock, releases it, spawns and handshakes, then stores `self._sessions[key] = session`, which overwrites any session already stored. Two parallel calls both pass the check, and both get `ok` with a stopped reply. The first session is orphaned: `terminate` closes only the second, and the first `python -m debugpy.adapter`, its launcher and the paused pytest stay alive until Hermes exits. Hermes runs parallel tool calls concurrently, so one turn with two `launch` calls is enough to trigger it.
   Repro: two threads, each calling `debug_python_handler({"action":"launch","python":PY,"args":["-q","tests"],"breakpoints":[{"path":"src/app/cart.py","line":9}]}, task_id="R")`, then one `terminate` on R. `pgrep -f debugpy.adapter` still shows one pid.
   Fix: reserve the key under the lock before spawning (a placeholder or a "launching" set), so the second call gets `session_active`; remove the reservation on failure.

## Non-blocking observations
- When `python` is not an interpreter (e.g. `/bin/echo`), the hint still says "is debugpy installed? run: /bin/echo -m pip install debugpy". The code is right; the wording is odd.
- A launch timeout of 25 s returned after 28.0 s: the 25 s wait plus about 2 s of handshake. That is within bound.
- `evaluate` returns up to 2000 chars of result plus JSON overhead, about 2.04 KB. That matches the spec.

## VERIFY
- Every case a-i has a recorded command, exit code and result (table above; logs in `scratch/dap-adv/logs/`).
- `pgrep -fl debugpy.adapter` after the whole run: empty, rc=1. `pgrep -fl 'debugpy|flood.py|spin.py'`: empty. Case j's leaked adapter (pid 80778) was SIGKILLed by the cleanup loop at the end of `case_j.py`.

## Files (all scratch, no repo edits)
`~/.hermes/profiles/kami/cache/scratch/dap-adv/`: `common.py`, `case_a.py`..`case_j.py`, `run.sh`, `logs/*.log`, `ws/` (temporary workspaces).

## Open
- After the two fixes, rerun `./run.sh j` (expect 7/7), plus `./run.sh d` and `./run.sh f` as regressions.
- Not tested: Windows, and the idle timeout after 10 minutes (the 600 s path was not run live).
