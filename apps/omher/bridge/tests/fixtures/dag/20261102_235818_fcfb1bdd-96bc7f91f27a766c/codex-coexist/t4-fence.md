# t4-fence handoff

Commit: `51b1f0b554b4e0c08a2614a8964cfab786cb5572` fix(fanout): point zsh TMPPREFIX and UV_CACHE_DIR into the fence scratch dir
Branch: fix/codex-coexist-fence (worktree `/w/oh-my-hermes-worktrees/codex-coexist-fence`), not pushed. Signed off, all spec trailers present.

## Files
- `src/coding/fanout_confinement.py`: `FanoutFilesystemConfinement.command_environment` now also sets `TMPPREFIX=<work>/.omh/confinement-tmp/zsh` and `UV_CACHE_DIR=<work>/.omh/confinement-tmp/uv-cache` under the same condition as TMPDIR (enforced fence, `sandbox-exec`/`bwrap`). A caller value is kept only if it is absolute and its realpath is inside a write root. New private helper `_within_write_roots`. The fence profile, write roots and mach services are unchanged.
- `tests/test_fanout_confinement.py`: 3 new tests plus 1 changed pin (below).
  - `FanoutConfinementPolicyTests.test_zsh_and_uv_scratch_follow_tmpdir_only_for_an_enforced_fence`
  - `FanoutConfinementPolicyTests.test_caller_uv_cache_and_tmpprefix_are_kept_only_inside_a_write_root` (inside the worktree is kept; outside `~/.cache/uv`-style, `/tmp/zsh` and a relative path are replaced)
  - `FanoutFilesystemConfinementTests.test_zsh_heredoc_runs_inside_the_fence` (live; darwin class skip plus a skip when sandbox-exec or zsh is missing; caller TMPPREFIX=/tmp/zsh gets replaced and the heredoc prints `ok`)

Scratch dir creation: `<work>/.omh/confinement-tmp` is already created during preparation by `_write_scratch_ignore` (called from `prepare_fanout_filesystem_confinement` for sandbox-exec/bwrap). zsh only needs the parent of the prefix (`.../confinement-tmp`) to exist, and uv creates its cache dir itself, so no new mkdir was added. The live test and the probe both pass on that basis.

## Changed existing pin
`test_fanout_confinement.FanoutConfinementPolicyTests.test_bwrap_command_environment_keeps_toolchain_scratch_in_the_worktree`
old: `{"PATH", "OMH_MARK", "TMPDIR": <scratch>}` → new: the same keys plus `"TMPPREFIX": <scratch>/zsh` and `"UV_CACHE_DIR": <scratch>/uv-cache`. Why: the env delta now intentionally includes the two new redirects.

## Tests (literal tail)
`PYTHONPATH=tests uv run python -m unittest test_fanout_confinement test_fanout_dispatch test_broad_exception_policy test_module_patch_policy`
```
----------------------------------------------------------------------
Ran 252 tests in 200.768s

OK (skipped=19)
```
`uv run --group lint ruff check src/coding/fanout_confinement.py tests/test_fanout_confinement.py`
```
All checks passed!
```

## Probe
Copy: `/w/.hermes/profiles/kami/cache/scratch/codex-coexist/fence_probe_t4.py` (sys.path → fence worktree), run with the fence worktree's `.venv/bin/python`.

Before (base, original probe):
```
zsh_heredoc: rc=1 out='' err="zsh:1: can't create temp file for here document: operation not permitted"
zsh_heredoc_tmpprefix: rc=0 out='heredoc-ok' err=''
uv_version: rc=0 out='uv 0.12.5 (Homebrew 2026-08-14 aarch64-apple-darwin)' err=''
uv_cache_dir: rc=0 out='/w/.cache/uv' err=''
uv_pip_list: rc=2 out='' err='error: Failed to initialize cache at `/w/.cache/uv`\n  Caused by: failed to open file `/w/.cache/uv/sdists-v9/.git`: Oper'
```
After (fence worktree):
```
zsh_heredoc: rc=0 out='heredoc-ok' err=''
zsh_heredoc_tmpprefix: rc=0 out='heredoc-ok' err=''
uv_version: rc=0 out='uv 0.12.5 (Homebrew 2026-08-14 aarch64-apple-darwin)' err=''
uv_cache_dir: rc=0 out='/private/var/folders/45/9gtdct614mz4rplqs209nykm0000gn/T/fence-probe-wpqkbal8/.o' err=''
uv_pip_list: rc=0 out='Package      Version Editable project location\n------------ ------- ------------' err='Using Python 3.14.7 environment at: /w/oh-my-hermes-worktrees/codex-coexist-fence/.venv'
```

## Not tested
- Linux bwrap live path (no bwrap on this host; the bwrap env pin is unit-tested).
- Reusing a warm uv cache across units. Each unit gets a cold cache on purpose.
