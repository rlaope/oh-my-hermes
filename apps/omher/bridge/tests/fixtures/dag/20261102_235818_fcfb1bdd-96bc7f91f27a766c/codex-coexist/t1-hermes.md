# t1-hermes handoff — Codex skill discovery roots

Commit: `7723d45f8` — fix(coding): discover Codex skills from the roots Codex itself loads
Branch: fix/codex-coexist-t1 (worktree `/w/oh-my-hermes-worktrees/codex-coexist-t1`), not pushed.

## Files changed
- `src/coding/executor_skill_discovery.py` (+86/-9)
- `tests/test_executor_skill_discovery.py` (+130)

## Behaviour
- Codex sources in Codex precedence order: `codex_repo_agent_skills` (`<project_root>/.agents/skills`, only when project_root is given), `codex_prompts` (`<codex_home>/prompts`, `/name`), `codex_skills` (`<codex_home>/skills`, `$name`), `codex_user_agent_skills` (`base/.agents/skills`, `$name`).
- `<codex_home>` = `$CODEX_HOME` (stripped, `~`-expanded) when set, non-empty, AND `home` was not passed; else `base/.codex`.
- New payload field `shadowed_name_count` (int, every profile; 0 for claude-code / pi-family-runtime / unsupported).
- Codex skill-dir sources use `confine_to_root=True`: a symlinked child that resolves outside the root (or cannot resolve) is skipped; symlinks resolving inside the root are kept. Claude sources unchanged (no confinement) so claude-code output is byte-identical apart from the new 0 field.
- Real-home check (read-only, this Mac): codex sources = prompts absent, codex_skills present, codex_user_agent_skills present; 135 skills, shadowed 0, rejected 0; implementation sequence now `$omh-plan` → `$omh-build-failure-triage` → `$omh-code-review` (was `$generate2dsprite` → `$game-video-feedback-loop`).

## Verify (literal tails)
`PYTHONPATH=tests uv run python -m unittest test_executor_skill_discovery test_unit_prompt_assembly test_fanout_dispatch test_broad_exception_policy test_module_patch_policy`:
```
Ran 276 tests in 306.041s

OK
```
`uv run --group lint ruff check src/coding/executor_skill_discovery.py tests/test_executor_skill_discovery.py`:
```
All checks passed!
```

## Changed existing assertions
None. No test pins the payload key set exactly (grep for `rejected_name_count`/payload keys outside this test file found nothing); the new field needed no assertion change.

## Judgement calls
1. Dedup key is the resolved invocation (`$name` / `/name`), not the bare name: a Codex prompt `/planner` and skill `$planner` are distinct commands, so they don't shadow each other (test `test_codex_prompt_and_skill_with_one_name_do_not_shadow`). Across the three `$name` skill roots this is exactly "same name → first wins".
2. Hidden dirs: Codex's real `~/.codex/skills/.system` has no SKILL.md of its own, so it's skipped by the existing SKILL.md check; a hidden dir that does carry SKILL.md is rejected by `_safe_name` and counted in `rejected_name_count` (existing behaviour, kept).
3. Symlink confinement is only on for the Codex roots. Today `_skill_dir_source` follows every symlink (is_dir() follows). On this Mac `~/.agents/skills` has 39 `vg-*` symlinks into `~/Desktop/owner/org-marketing-skills/...` (outside the root), so they are now skipped in Codex discovery — intended per brief, but the parent should know those personal `vg-*` skills no longer appear for Codex. Claude roots (`~/.claude/skills` has the same symlinks) keep following them so claude-code output stays unchanged.
4. Extra tests beyond the brief list: `test_codex_prompt_and_skill_with_one_name_do_not_shadow`, `test_claude_code_payload_gains_only_a_zero_shadowed_count`.

## Left undone
- `fanout_dispatch.py` docstring at ~L1019 still says repo-local `.claude/skills` only; out of write scope.
- Windows symlink behaviour not exercised (test self-skips if symlinks are unavailable).
