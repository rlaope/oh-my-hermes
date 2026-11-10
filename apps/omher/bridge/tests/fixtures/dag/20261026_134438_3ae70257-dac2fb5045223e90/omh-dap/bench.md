# bench node handoff

Status: DONE. Commit `54ef5c7f2` on `feature/omh-dap` (signed-off, not pushed). Only files under benchmarks/live-model-tools/v1/ were touched.

## What changed
- `lib/omh_live.py`: `--edit-surface dap` uses toolsets `file,terminal,omh-dap`. `_current_session_environment` now also pops `OMH_DAP_TOOLS` and sets it to 1 for the dap arm only. Added `debug_directive(patch|dap)`, the exact spec.md pair, which `directive_text(..., "debug")` returns. The patch, hashline and rename texts are unchanged.
- `bench.py`: added `dap-ab` to `--split`, `dap` to `--edit-surface` and `debug` to `--edit-directive`. A non-patch surface on a non-current-session harness is still refused, and so is `debug` with lsp or hashline.
- `lib/runner.py`: `--test-env` installs `pytest debugpy` (both arms). The task text is unchanged. In a fake `dap-ab` run, each record's `observation.toolsets` holds the patch and dap argv toolsets, built offline and never executed.
- `lib/corpus.py`: new `dap-ab` split with 3 templates (D-MUTABLE-DEFAULT, D-ALIASED-STATE, D-ORDER-DEPENDENT) × seeds 104729/130363/155921. The seed sets the names, prices and rates. Goldens are private: test names, assert count and hidden checks. The prompt names `python -m pytest -q tests/<file>` and says "Find and fix the cause", with no hint at the cause. `generate_public` is untouched.
- `lib/validation.py`: dap grading checks four things. Changed paths must be under `src/benchapp/` or `tests/`. The test functions must be kept, with no fewer asserts. The workspace tests run in file order, and the hidden checks run. Both kinds of check run in a fresh interpreter with `PYTHONPATH=<ws>/src`.
- `adapters/fake_harness.py`: `DAP_FIXES` holds the reference fixes.
- `tests/test_dap_ab.py`: for every template × seed, the untouched fixture fails, the reference fix passes and the named wrong fix fails. The wrong fixes are `lines.clear()` in build_order, `copy.copy(plan)` in upgrade, and a cache key of `id(SETTINGS)`. Also covered: weakened-test and out-of-scope cases, seed variation, prompt wording, a fake run of 9/9 with toolsets for both arms, the argv for all 4 surfaces, the env pop, the directive pair plus the unchanged existing directives, the CLI guards, and debugpy in the test env (skipped without uv).

## VERIFY (literal output)
- pytest: `55 passed, 15 subtests passed in 126.97s`
- corpus --verify: exit 0, `corpus_digest c4ea899a…7b33` (unchanged), `verified: true`
- fake run dap-ab: `"scheduled": 9`, `"graded": 9`, `"passed": 9`, exit 0
- ruff: only the 3 pre-existing F841 (runner.py:28, validation.py:17, validation.py:19)
- `git diff --stat origin/main -- …/corpus …/manifest.json`: empty

## Open
- No live or paid run was made. The debugpy env test did really install debugpy through uv and import `debugpy.adapter`.
- The untouched fixtures fail exactly 1 test each under real pytest, which I checked by hand. In the MUTABLE-DEFAULT and ORDER-DEPENDENT templates the failure depends on test order (the second test fails), which matches the intent.
