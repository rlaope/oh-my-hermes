# t2-status-update handoff (written by the parent)

Written by the parent from fanout `fanout-32ea20834da3` (Codex, gpt-6.1-sol, 229 s). Codex implemented and staged the four scoped files but could not commit: the OMH macOS fence denied zsh's heredoc temp file (`can't create temp file for here document: operation not permitted`). The parent re-ran VERIFY in the unit worktree, applied the staged diff to the integration branch and committed it.

- Integration worktree: `/w/oh-my-hermes-worktrees/codex-coexist` (branch `fix/codex-agent-skills-coexist`)
- Commit: `9aac531bf fix(agents): report the primary pack's real state and refresh it on update`
- Files: src/commands/setup.py (+10), src/install/agent_skills_projection.py (+51/-?), tests/test_agent_skills_projection.py (+43), tests/test_update_agent_skills.py (new, 151)
- API for t3: `agent_skills_status(target, mirror=None)` now returns `primary` (`fresh|stale|missing`), `mirror` (`fresh|stale|missing|none`); `refresh_installed_agent_skills(home, *, dry_run)` in the same module.

## VERIFY observed by the parent
```
PYTHONPATH=tests uv run python -m unittest test_agent_skills_projection test_update_agent_skills test_update_refreshes_hermes_skill_dirs test_atomic_installer_update test_broad_exception_policy test_module_patch_policy
Ran 67 tests in 65.523s
OK
ruff check (4 files): All checks passed!
```

## Changed existing assertions (disclosed by Codex, checked by the parent)
- `test_repo_scope_installs_and_repairs_claude_mirror` (CLI, ~line 650): after deleting the mirror receipt of a two-root install, `--status` `projection` `missing` → `fresh` (primary is fresh; the mirror loss now shows as `mirror: missing` + warning). Intent kept: the repair run right after still restores the mirror.
- `test_manifest_revision_and_mirror_loss_are_not_fresh`: after the mirror receipt loss with a stale primary, `missing` → `stale`. Intent kept: still not fresh.
