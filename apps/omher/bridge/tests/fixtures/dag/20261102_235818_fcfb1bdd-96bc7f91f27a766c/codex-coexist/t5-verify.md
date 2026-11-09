# t5-verify handoff (second, independent verifier)

Tree: `fix/codex-agent-skills-coexist` HEAD `c74e9646a`, base `333e8e323`. This is a review only; no code was changed. Scratch work is in `/w/.hermes/profiles/kami/cache/scratch/codex-coexist/verify/second/`.

## Verdict: HOLD

Most of the change holds up: discovery, fence env, status semantics, the update dry run and malformed receipts, doctor's warning-only branches, and test isolation. The HOLD rests on finding 1: a mirrored user pack under a HOME path that contains a symlink makes `omh update` exit 1 on every run, and makes doctor report a fresh pack as stale. Base exits 0. Finding 2 is a smaller breach of the t3 exception and exit-code criterion. Each fix is a few lines (listed under the finding). Everything else below is non-blocking.

## Tests (run here)
`env TMPDIR=/var/folders/45/9gtdct614mz4rplqs209nykm0000gn/T/ PYTHONPATH=tests uv run python -m unittest test_executor_skill_discovery test_fanout_confinement test_update_agent_skills test_doctor_agent_skills test_home_isolation`, on HEAD (`second/head-tests.log`):
```
Ran 150 tests in 11.639s

OK (skipped=19)
EXIT=0
```
The 19 skips are the Linux bwrap classes. `test_zsh_heredoc_runs_inside_the_fence` ran live (sandbox-exec) and passed (`second/fence-verbose.log`). The real `~/.agents/skills/.omh-agent-skills-manifest.json` was sha256 `828186c0…0df5`, mtime `1793682592.027780302`, both before and after all my runs. A stat listing of `~/.agents` and `~/.codex/skills` showed no difference before vs after (`real-home-before.txt` / `real-home-after.txt`).

## Parent evidence I confirmed
- Parent's 512-test run: `head-final.log` reads `TMPDIR=/var/folders/…` / `Ran 512 tests in 253.922s` / `OK (skipped=20)`. Base `base-tests.log` reads `Ran 422 tests` / `OK (skipped=1)`. I read both files but did not re-run them.
- Logs from the first verifier, read but not re-run: ruff on HEAD and base both say `All checks passed!` with EXIT=0, and `release drift` says `No drift. 29 checks passed.`
- Claude parity: `head-claude-parity.out` and `base-claude-parity.out` are byte-identical. The script pops `observed_at` and `shadowed_name_count` before comparing.
- Fanout (`fanout-comparison.json`): HEAD recommends `$omh-plan`, `$omh-build-failure-triage`, `$omh-code-review` for coupons, cart and tests. The base arm of this run is `executor_not_ready`/`blocked_by_dependency` with no recommendations, so the base `$generate2dsprite` claim still rests on the earlier inspection run, as the draft says.

## Spot checks re-run (scratch copies of the real packs; `second/spot-checks.log`)
| probe | HEAD | base | matches first verifier |
| --- | --- | --- | --- |
| discovery `d('codex')` | `135 121 {codex_prompts: absent, codex_skills: present, codex_user_agent_skills: present} 0` | `6 0 {…} None` | yes |
| `install --target agents --scope user --status --json`, stale copy | projection `stale`, primary `stale`, mirror `missing`, 1 warning | projection `missing` | yes |
| doctor `agent_skills_pack`, stale copy | ok=True, warning, `omh update` | check absent | yes |

## Codex upstream (read-only `gh api`, `host_roots.rs` @ 28cade4f5a7a, 2026-10-27) and live `codex debug prompt-input` (codex-cli 0.166.0-alpha.5.1, scratch HOME)
- Root order (`host_roots.rs:119-158`, then `:99-107`) is: project `.codex/skills`, `$CODEX_HOME/skills`, `~/.agents/skills`, `$CODEX_HOME/skills/.system`, `/etc/codex/skills`, plugin and extra roots, then repo `.agents/skills` from the project root down to cwd. `dedupe_skill_roots_by_path` (`:395-398`) dedupes roots by path only.
- Skills are deduped by SKILL.md path, not by name. They are then sorted by scope rank, Repo < User < System < Admin, then by name (`loader/host_merge.rs:228-229, 241-247, 260-266`). A plain `$name` mention is selected only when exactly one skill has that name (`skills/selection.rs:181-193`).
- Directory symlinks are followed for User, Repo and Admin roots and ignored for System (`loader/host.rs:164-166`). The walk does no root-confinement check (`exec-server/local_file_system.rs:837`).

## Findings

### Blocking
1. **A symlinked HOME plus a mirrored user receipt makes `omh update` fail on every run and doctor report false staleness.** Code: `src/install/agent_skills_projection.py:222`, then `:227` and `:237`; `src/maintenance/doctor.py:1481`.
   - Input: run `omh install --target agents --scope user` (no `--host`) when the HOME path contains a symlink. The receipt then records resolved paths (`:71` uses `Path.home().resolve()`). `agent_skills_user_home()` returns `Path.home()` unresolved, and `:227` only calls `.absolute()`. So `Path(directories[0]) != target` and the refresh raises `ValueError: Invalid installed user Agent Skills target_dirs`.
   - Observed through `cmd_update` (`second/update-cases.log`): `exit 1 {"agent_skills": null, "failures": [{"phase": "agent_skills", …}], "status": "partial"}`, and the same again on a second run. Base, same input: `exit 0 … "status": "ok"` (`update-cases-base.log`).
   - Doctor on the same, freshly installed pack via the symlinked home gives `warning … is stale`, `next_action: omh update`. That update then fails, so the user loops. Via the real path doctor says `ok` (`edge-probes.log` B.*). Status compares the string `target_dirs` at `:170`, which is why it reads stale.
   - The same root cause makes the mirror-absent warning (`:182`) say `--scope repo` for a user install (`status-scope.log`).
   - This breaks t2 B ("one listing absolute dirs is a mirrored install (refresh those dirs as target+mirror)") and t3 ("Fresh → ok"). The tests miss it because both new test files `.resolve()` their temp home. An unresolved macOS `/var/folders` temp dir would expose it.
   - Fix: resolve in `agent_skills_user_home()`, or compare resolved paths in refresh, doctor and `:182`.
2. **Doctor can crash instead of warning on Python 3.11–3.13.** `src/maintenance/doctor.py:1482`: `(target / MANIFEST_NAME).is_file()` sits outside the `try`. On Python 3.11–3.13 (pyproject `>=3.11`), when `~/.agents/skills` has no search permission, `is_file()` raises `PermissionError`, which escapes `run_doctor`.
   - Observed: `3.13.15 0o0 ESCAPES main(): PermissionError [Errno 13]`. With the same input, 3.14.7 gives `EXIT 1 ok …not installed` and base on 3.13 gives `EXIT 1` (`doctor-cli-perm*.log`).
   - The input is unusual, but it breaks t3's "catch (OSError, ValueError, UnicodeDecodeError) → warning" and "never change the doctor exit code". `quickstart.py:137` also calls `run_doctor`.
   - Fix: move the probe inside the `try`.

### Non-blocking
3. **Codex keeps duplicate names; OMH reports only the first.** `executor_skill_discovery.py:163-167, 178-184`. The comment says "Codex resolves a duplicate skill name to the first root". Upstream (above) and a live probe say otherwise: with `dup-skill` in both `$CODEX_HOME/skills` and `~/.agents/skills`, Codex lists both (`r0` and `r1`, `codex-dup-probe/`). Selection then refuses a plain `$dup-skill` because the count is 2. OMH lists one copy and still recommends `$dup-skill`. This matches the t1 brief as written; the brief's premise is what's wrong. No effect on this Mac (`shadowed_name_count` 0). Repo ordering (Repo before User) does agree with Codex's scope sort.
4. **The symlink skip diverges from Codex, and the integration note's justification for it is wrong.** `executor_skill_discovery.py:515`. Codex follows escaping skill-dir symlinks: a scratch `escaping-skill` linked outside `~/.agents/skills` is listed (`codex-symlink-probe/`). On the real pack Codex lists all 39 `vg-*` skills, named `org-marketing:vg-*` through the target repo's plugin manifest (`codex-realpack-probe/`). The note says "`codex debug prompt-input` showed 0 `vg-*` entries", but that grep missed the namespaced form. The skip is what the t1 brief asked for, and it avoids recommending a wrong bare `$vg-*` name. The record should not say it "matches Codex", though.
5. **Roots and depths OMH does not probe.** These were out of scope for t1 and are listed as gaps: the project `.codex/skills` root, `/etc/codex/skills`, plugin roots, `.agents/skills` in subdirectories between the project root and cwd, and nested skill dirs (Codex walks recursively; OMH reads direct children only).
6. **Doctor and refresh validate the receipt differently.** `doctor.py:1488-1493` vs `agent_skills_projection.py:236-238`. With `target_dirs` `[<other>, <home>/.claude/skills]`, doctor says stale and points to `omh update`, and update then rejects the receipt. With `[target, target]`, doctor says ok and update rejects. Doctor's looser check was disclosed in the t3 handoff (`edge-probes.log` A.*).
7. **Refresh follows any absolute mirror path in the receipt.** `agent_skills_projection.py:236-239`. A receipt naming e.g. `/srv/x` as the mirror is accepted, and a real run would write the pack there. On macOS `/tmp/...` is refused only because `/tmp` is a symlink. The module docstring changed from "Roots come from the invocation, never the manifest" to trusting the receipt. That matches t2 B, but it is a trust change worth the parent knowing about.
8. **`omh update` re-creates a mirror the user deleted.** Mirrored receipt, user ran `rm -rf ~/.claude/skills` as `docs/AGENT-SKILLS.md#duplicate-copies` advises: status reports `fresh / missing / fresh`, and `omh update` then rebuilds `~/.claude/skills` (`2.mirror_recreated: True`). This sits awkwardly with t2's "Never create a pack that is not there" and with the new "a missing mirror is not stale" status meaning. It needs a parent decision.
9. **`refreshed_files` counts files written, not files changed.** `agent_skills_projection.py:249`. Every `omh update` rewrites the whole pack and prints "refreshed N files" even when `projection_before` is `fresh`.
10. **One fence keep-rule edge case.** `fanout_confinement.py:309-313`. A caller `TMPPREFIX` equal to a write root itself (for example the worktree) is kept. zsh treats TMPPREFIX as a filename prefix, so its temp files land in the root's parent, outside the fence. Shown with zsh: `TMPPREFIX=<root>` → `can't create temp file`, `TMPPREFIX=<root>/zsh` → ok. Everything else in the keep rule behaved correctly (`edge-probes.log` D.*): inside kept; `..` escape, inside symlink pointing out, `<work>-evil` sibling, relative, empty and `~/.cache/uv` all replaced.
11. **The test seam covers update and doctor only.** `OMH_AGENT_SKILLS_HOME` is honoured at `setup.py:555` and `doctor.py:1481`. `Path.home()` still decides the user pack for `install/--status` (`agent_skills_projection.py:71`, intentionally), for status scope wording (`:182`), and for Codex discovery (read-only; tests pass `home=`). No test path writes the real pack: the real manifest was unchanged across every run above.
12. **The status `projection` change checks out.** With the primary present and no mirror manifest, `projection` takes the primary's state plus a warning. With the primary manifest deleted and the mirror fresh, it is `missing` (`edge-probes.log` C.*). The two changed assertions both delete a two-root install's mirror receipt and keep their intent: `test_agent_skills_projection.py:650` `missing`→`fresh`, still followed by the repair run, and `:721` `missing`→`stale`, still not fresh. `projection` has no consumers in `src` other than doctor and the CLI print. No defect found.
13. **Malformed `target_dirs` is handled.** Empty, three entries, a relative pair, `.`+abs, a wrong first entry, a mirror equal to the target, wrong types and invalid JSON all raise `ValueError` (JSONDecodeError is a ValueError subclass). `cmd_update` turns that into a failure row, dry run raises the same way, and nothing is written. No defect beyond findings 6 and 7.
14. **Doctor exit-code neutrality holds apart from finding 2.** Every branch returns `ok=True`, so `doctor_ok` is unchanged. Doctor exits 1 on HEAD and on base for unrelated checks (`live-probes.log`). Live bwrap and Windows symlink behaviour remain untested.

## Files (all under `verify/second/`)
`head-tests.log`, `edge_probes.py`/`edge-probes.log`, `update_cases.py`/`update-cases.log`/`update-cases-base.log`, `spot_checks.py`/`spot-checks.log`, `doctor_perm.py`/`doctor-perm.log`, `doctor_cli_perm.py`/`doctor-cli-perm.log`/`doctor-cli-perm-base.log`, `status_scope.py`/`status-scope.log`, `fence-verbose.log`, `host_roots.rs` + `codex-src/` (upstream sources), `codex-symlink-probe/`, `codex-realpack-probe/`, `codex-dup-probe/`, `real-home-before.txt`/`real-home-after.txt`.
