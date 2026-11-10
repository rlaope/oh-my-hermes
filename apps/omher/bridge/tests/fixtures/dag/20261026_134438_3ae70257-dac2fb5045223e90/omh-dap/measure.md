# measure (parent-run) — verdict: GATE FAIL (clause 3)

HEAD 9528a8c73, split dap-ab, --edit-directive debug --git-init-workspace --test-env, 8 models x 2 arms x 9.
Script: scratch/dap-bench/run_all.sh; gate: scratch/dap-bench/gate_dap.py -> gate_dap.txt.
Records 143/144 (gpt-4.1-nano dap D-MUTABLE-DEFAULT-155921 missing -> scored fail).
qwen D-MUTABLE-DEFAULT both arms seeded from smoke4 (same HEAD/flags), decided before the run (cap 160 - 20 spent).

- clause 1 weak dap >= patch+3: PASS 9 -> 12 (qwen 0->2, nano 0->1, grok 9->9, 4o-mini 0->0)
- clause 2 strong dap >= patch-1: PASS 35 -> 34 (glm 8->7)
- clause 3 no dap run > 3x patch median: FAIL, 7 runs (qwen 3 timeouts 191-312x incl. orphan continuation; nano 6.27x; MiniMax 3.70x; grok 3.27x; +1)
- clause 4 adoption >= 50%: PASS 46/65 main-run dap sessions called debug_python

Infra contamination (does not change the verdict; clause 3 already fails on completed runs):
- 22:18 KST og began returning 401 model_access_denied for qwen-flash, gpt-4o-mini, gpt-4.1-nano (deepseek still OK):
  6 gpt-4o-mini dap runs crashed in 10 s, nano dap 155921 has no record.
- Timed-out runs did not stop: `hermes -p <bench>` is served by the long-lived gateway, so the bench's subprocess
  timeout kills only the client; the agent turn kept running until the 401s (qwen session 18:42 -> 22:18, 200M tokens).
  9 sessions span > 1830 s. Profile token totals over 24 h: dapbench 708M, dapbenchp 440M.
