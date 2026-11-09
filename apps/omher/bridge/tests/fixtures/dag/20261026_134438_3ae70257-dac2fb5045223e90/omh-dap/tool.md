# omh-dap / tool: handoff

Status: DONE for everything this node owns. The unittest VERIFY line still exits 1, but only on failures that also happen on base 79c5308d2: the omh-lsp policy entries plus 2 Hermes-tree-absent tests. The proof is below. Commits are not pushed.

## Commits (feature/omh-dap, signed-off, on top of 54ef5c7f2 bench)
- 92f15f8f3 feat(dap): stdio DAP client and session logic for debugpy
- e1a389235 feat(dap): opt-in debug_python tool (toolset omh-dap)
- 5f90d90dd test(policy): register the omh-dap modules with the boundary gates

## Files
- New: src/plugin_bundle/omh/dap_client.py (only module importing subprocess), dap_session.py, tools/dap_tool.py, tests/test_dap_tool.py
- Registration: omh/__init__.py, tools/__init__.py (BUILTIN_TOOL_NAMES + collector), metadata.py, plugin.yaml, tests/test_plugin_distribution.py
- Budget: src/maintenance/release.py PLUGIN_TOOL_SCHEMA_CHAR_LIMIT 71831 -> 73612 (debug_python = 1781, with a reason comment); tests/test_ai_job_search_context_budget.py literal 73612
- Policy: PROCESS_SPAWN_ALLOWLIST entry for dap_client.py (with a reason); broad-except inventory: 3 dap_tool sites classified, counts 72->75 / 64->67 (re-derive at merge with lsp's 72->82 / 64->74: expect 85 / 77)
- Follows the parent's lsp patterns: schema constant `OMH_DAP_DEBUG_PYTHON_SCHEMA`; runtime_paths bound at module scope (no call-time sibling import); no asyncio/socket; native paths (os.path.join) and newline="" in the tests. The `frame` description doesn't restate its bound, so no overlap verdict is needed. No debug_python overlap finding remains.

## VERIFY (final tree, run 2026-10-29)
- uv sync: rc=0
- pytest line 1 (with debugpy): `39 passed, 26 subtests passed in 44.95s`, rc=0, 0 skipped. The interpreter there is uv's ephemeral env, which has debugpy 1.8.22. Verbose:
  `tests/test_dap_tool.py::RealDebugpyIntegrationTests::test_probe_scenario PASSED`
  `tests/test_dap_tool.py::RealDebugpyIntegrationTests::test_terminate_mid_session PASSED`
  (probe scenario: stop at src/app/cart.py:9 reason breakpoint, locals cart=[1, 2], add.__defaults__ = ([1, 2],), second hit cart=[1, 2, 5], clear + continue -> exited exit_code 1 with "assert 8 == 5" in output_tail)
- pytest line 2 (no debugpy): `85 passed, 2 skipped, 26 subtests passed`, rc=0. The 2 skips are the debugpy class, which is expected because that line has no `--with debugpy`.
- unittest line: `Ran 266 tests in 2046.665s FAILED (failures=8, skipped=2)`. All 8 also fail on a detached worktree of 79c5308d2 (scratch/dap-base-79c5308d2, logs scratch/dapbase_*.log):
  - handoff INVARIANT 2: lsp_bridge.py imports asyncio (base: same)
  - broad_exception x2: unclassified sites are lsp_bridge/lsp_nav/lsp_nav_tool only; 85 != 75 (base 82 != 72; +3 = my 3 classified dap sites)
  - plugin_bundle_standalone: tools/lsp_nav_tool.py:81 call-time import (base: same)
  - schema_overlap verdicts: lsp_*.line only (base: same)
  - schema_overlap collector: 28 != 25. The missing names are the 3 LSP_* schemas; base shows 27 != 24.
  - plugin_distribution x2 test_real_admission_*: reason hermes_code_tree_absent (base: same, environment)
  All lsp ones are fixed on origin/feature/omh-lsp-nav (515d42bd0, 8792cc79e, 296931c3a) and clear at the parent's merge.
- ruff: `All checks passed!` rc=0
- test_ai_job_search_context_budget, test_plugin_tool_surface, test_per_turn_budgets: OK

## Open
- At merge, re-derive EXPECTED_HANDLER_COUNT/ANCHOR_COUNT and PLUGIN_TOOL_SCHEMA_CHAR_LIMIT (both branches move them).
- Not tested on Windows.
- Live smoke outside the tests: launch -> stop at 6-7 s, the whole scenario takes about 7.5 s.
