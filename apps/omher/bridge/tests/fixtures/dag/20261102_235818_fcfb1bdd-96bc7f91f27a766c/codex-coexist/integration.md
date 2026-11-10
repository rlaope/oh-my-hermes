# t1-hermes / t4-fence / t3-doctor — parent integration note (for t5-verify)

Written by the parent. All producers are integrated on `/w/oh-my-hermes-worktrees/codex-coexist` (`fix/codex-agent-skills-coexist`):

```
c74e9646a docs(changelog): Codex skill discovery, fence scratch env and pack refresh
ba4b3ae1e test(agents): keep update and doctor off the developer's real Codex pack   <- parent fix
b75a31af6 fix(fanout): point zsh TMPPREFIX and UV_CACHE_DIR into the fence scratch dir  <- t4-fence (cherry-pick of 51b1f0b55)
e8708d5bd fix(coding): discover Codex skills from the roots Codex itself loads          <- t1-hermes (cherry-pick of 7723d45f8)
113478347 fix(doctor): warn when the Codex/.agents OMH pack is stale or edited          <- t3-doctor
9aac531bf fix(agents): report the primary pack's real state and refresh it on update    <- t2 (Codex diff, parent commit)
```

Parent fix ba4b3ae1e: the update CLI tests ran the real `cmd_update`, which now refreshes `Path.home()/.agents/skills`, so a local test run rewrote the developer's real pack (manifest mtime 1793681735 → 1793682592 during `test_update_refreshes_hermes_skill_dirs`). Update and doctor now resolve the home via `agent_skills_user_home()` (`OMH_AGENT_SKILLS_HOME` override), `tests/_local_package.py` sets it to the temp root, `test_home_isolation` pins it. After the fix the same run left the mtime unchanged. NOTE for verify: the real `~/.agents/skills` was therefore refreshed to the current HEAD catalog by that test run (and possibly by an earlier child run at 13:55), so the live "stale" probes will now read `fresh`; to observe stale/warning, copy the pack to a scratch home, edit its manifest `catalog_revision`, and point `OMH_AGENT_SKILLS_HOME` at it.

Also: fanout_dispatch.py docstring updated (the t1 handoff's leftover). Disclosed t1 judgement: Codex discovery skips symlinked skill dirs that resolve outside their root; on this Mac 39 `vg-*` dirs in `~/.agents/skills` are such symlinks, but Codex itself lists none of them in its prompt input (`codex debug prompt-input` showed 0 `vg-*` entries, while it does list `hyperframes`, `media-use`, `archify`), so the skip matches Codex.
