# t3-doctor handoff

- Worktree: `/w/oh-my-hermes-worktrees/codex-coexist` (branch `fix/codex-agent-skills-coexist`, on top of T2 `9aac531bf`)
- Commit: `113478347 fix(doctor): warn when the Codex/.agents OMH pack is stale or edited` (signed off, all 7 trailers; not pushed)
- Files: `src/maintenance/doctor.py` (+64), `tests/test_doctor_agent_skills.py` (new, 113)

## Behaviour
`_agent_skills_pack_check()` runs in `run_doctor` right after `_flat_skill_layout_check`. It reads only `Path.home()/.agents/skills` and writes nothing.
- No receipt: ok, "OMH Agent Skills pack for Codex/.agents hosts is not installed at …", no warning.
- Receipt with `target_dirs == ["."]`: single-target status. Otherwise exactly 2 absolute dirs give target+mirror (`target_dirs[1]`). Any other shape is ValueError, so it shows as "could not read".
- Fresh: ok, "… matches catalog <revision[:12]>".
- Locally modified (checked before stale): warning, "<n> locally-modified file(s) …", `next_action` = the status payload's `next_action`.
- Stale or missing projection: warning, "… is stale: <n> file(s) differ from the current catalog". The count is the symmetric diff of the receipt's file digests against the current catalog, and the ": <n> …" part is left out when the count is 0 (revision-only drift). `next_action="omh update"`.
- `(OSError, ValueError, UnicodeDecodeError)`: warning, "could not read …", `observed=False`.
- Every branch is `ok=True`, so `doctor_ok` and the exit code never change.

## VERIFY (literal tail, /w/.hermes/profiles/kami/cache/scratch/t3-verify.log)
```
PYTHONPATH=tests uv run python -m unittest test_doctor_agent_skills test_doctor_advisory test_doctor_privacy_controls test_tui_doctor test_broad_exception_policy test_module_patch_policy
----------------------------------------------------------------------
Ran 114 tests in 99.700s

OK (skipped=1)
EXIT=0
uv run --group lint ruff check src/maintenance/doctor.py tests/test_doctor_agent_skills.py
All checks passed!
```
New module alone: `Ran 9 tests in 0.402s / OK`.
Mutation: with the stale branch disabled (`if False:`), `test_stale_revision_warns_with_omh_update` and `test_catalog_change_counts_differing_files` FAIL. The file was restored before VERIFY.
Live read-only run on this Mac: `ok | OMH Agent Skills pack at /w/.agents/skills matches catalog c408094695b3` (the editable build's catalog; this pack was apparently already refreshed).

## Judgement calls
- `WARNING_NEXT_ACTION_PRIORITY`: nothing added. The pack is optional, and a stale Codex pack should not displace first-run headline actions. The warning still shows in the list with its own next action.
- doctor imports the module (`from ..install import agent_skills_projection`), not its names, so tests that patch `projection.agent_skill_files` cover both the status call and the diff count. It uses the module-private `_read_manifest` so the receipt is validated the same way status and refresh validate it.
- Locally modified takes precedence over stale. `omh update` refuses edited toolkit files, so pointing at it first would fail.
- Unlike `refresh_installed_agent_skills`, there is no extra check that `target_dirs[0] == target`. Status reads both roots anyway. The "could not read" path covers malformed counts and relative paths.
- Cost: `agent_skill_files()` takes about 1.7 s cold (lru-cached after). It runs only when a receipt exists.
- No existing assertions changed.
