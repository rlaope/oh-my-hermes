---
name: "omh-skill-eval"
description: "[omh] Agent skill to check before shipping it: run `omh skill-eval` on the folder to see, host by host, whether Hermes, Claude Code, Codex, OpenClaw, OpenCode and Copilot CLI load it, load it degraded, or skip it, and fix each finding at its source. Use when the user says: skill-eval, skill eval, evaluate my skill, is my skill any good, skill harness check, will my skill load, skill compatibility, 스킬 평가."
license: MIT
compatibility: "Requires the omh CLI on PATH (pip install oh-my-hermes)."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: skill-eval
    role: operator
    quality_tier: evidence-gated
---

# Skill Eval

This is an OMH `skill-eval` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`skill-eval` exists because a skill that reads well can still be skipped or cut by the host that loads it: the wrong root, a description past the listing window, a catalog over its budget, a file the agent cannot open. The check is offline and cites the host fact behind each finding, so the fix lands before users do.

## First Steps

- Ask which folder to check and where it will be installed, then run `omh skill-eval <dir>` with `--install-root` when the path does not show it.
- Report the host rows and the final count line first, then the fixes for not_loaded rows before degraded ones.

## Do Not Use When

- The ask is a dashboard of the whole skill portfolio's drift, stale surfaces or pending amendments; use `omh-skill-health`.
- The ask is finding an existing skill to adopt before writing one; use `omh-skill-scout`.
- The ask is comparing coding agents or models on the same task.
- OMH itself is not installed or its skills do not appear at all.

## Examples

Good example:

- Prompt: I wrote a skill in ./my-skills/pdf-tables. Will it load in Claude Code and Codex?
- Expected behavior: Run `omh skill-eval ./my-skills/pdf-tables --install-root .claude/skills`, then again for .agents/skills, quote each host row and give the fix for every ❌ and ⚠️ finding.
- Why: The question is whether named hosts load the folder, which the offline check answers row by row.

Bad example:

- Prompt: All hosts show ✅, so tell the team the skill makes our PDF answers better.
- Expected behavior: Say the check shows only that it loads; offer the with/without run before any claim about results.
- Why: Loading is not lift; a better-results claim needs the same tasks run with and without the skill.

## Completion Checklist

- Every host verdict quoted came from `omh skill-eval` output in this session.
- Each ❌ and ⚠️ finding has a fix at its source file, or is named as accepted.
- No claim that the skill improves results unless a with/without table was observed.

## Recovery Notes

- If every root reads not_checked, rerun with `--install-root` for the root the user will install into.
- If `omh` is not on PATH, install or update OMH first; the check has no other implementation to fall back on.



## When to Use

Use when a SKILL.md folder or a folder of skills is about to be shared or installed and the question is whether each agent host will find, list and read it; `omh skill-eval` reads files only, with no key, no network and no model call.

    Strong routing signals: `skill-eval`, `skill eval`, `evaluate my skill`, `is my skill any good`, `skill harness check`, `will my skill load`, `skill compatibility`, `스킬 평가`, `스킬 점검`, `스킬 호환성`

## Catalog Metadata

Category: `operations`
Phase: `skill-eval`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Run `omh skill-eval <dir>` (add `--catalog` for a folder of skills, `--install-root` when the folder is a source pack, `--json FILE` to keep the payload) and quote its rows; `--strict` exits 1 on any not_loaded or degraded row for CI.
- Read each host row as ✅ loads, ⚠️ degraded (listed but cut, shortened or partly unread) or ❌ not_loaded (the host never sees it), and a root of not_checked as unknown, not as fine.
- Fix at the source: put the situation or trigger first in the description so a short listing window keeps it, move long detail from SKILL.md into references/ files, name every toolkit/ or other unlisted path in SKILL.md so the agent can open it, and shrink the catalog (shorter descriptions, fewer skills per root) when a list budget is exceeded.
- Treat an overlap group (several skills opening the same way) as a routing risk: give each its own opening.
- Load `references/with-without-eval.md` before claiming the skill makes answers better; a host verdict says nothing about lift.

Required inputs:

- the skill folder (with SKILL.md) or the folder of skills to check
- where it will be installed: .agents/skills, .claude/skills, ~/.hermes/skills, or another host root
- the hosts that matter, and the model's context window when it is known

Expected outputs:

- omh_skill_eval/v1
- a fix list ordered by effect: not_loaded first, then degraded

Artifact expectations:

- omh_skill_eval/v1 is the command's own JSON: one row per host with status, root and findings, the catalog size and description total, overlap groups, and static findings, each finding with its message and fix

Safety rules:

- Report only what `omh skill-eval` printed; a host verdict is a load-and-list fact, never proof the skill helps a task.
- Never say a skill improves results without a with/without run on the same tasks; until then, say it was not measured.
- A lift run uses the user's subscription model and costs nothing extra by default; run a paid model only after the user approves that spend.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
