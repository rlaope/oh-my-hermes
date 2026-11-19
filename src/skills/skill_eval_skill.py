"""Check an agent skill folder against the hosts that will load it, offline, before it ships."""
from __future__ import annotations

from .catalog_types import SkillDefinition, SkillExample

REFERENCE_PATH = "references/with-without-eval.md"

DEFINITION = SkillDefinition(
    "skill-eval",
    "Agent skill to check before shipping it: run `omh skill-eval` on the folder to see, host by host, whether "
    "Hermes, Claude Code, Codex, OpenClaw, OpenCode and Copilot CLI load it, load it degraded, or skip it, and fix "
    "each finding at its source.",
    (
        "skill-eval",
        "skill eval",
        "evaluate my skill",
        "is my skill any good",
        "skill harness check",
        "will my skill load",
        "skill compatibility",
    ),
    (
        "Use when a SKILL.md folder or a folder of skills is about to be shared or installed and the question is "
        "whether each agent host will find, list and read it; `omh skill-eval` reads files only, with no key, no "
        "network and no model call."
    ),
    category="operations",
    phase="skill-eval",
    hermes_role="tracker",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "Hermes runs `omh skill-eval`, reads its rows and proposes the fixes. Edits to the skill's files follow the "
        "user's normal review; a with/without lift run uses `delegate_task` on the session's own model and only with "
        "the user's go-ahead."
    ),
    required_inputs=(
        "the skill folder (with SKILL.md) or the folder of skills to check",
        "where it will be installed: .agents/skills, .claude/skills, ~/.hermes/skills, or another host root",
        "the hosts that matter, and the model's context window when it is known",
    ),
    expected_outputs=(
        "omh_skill_eval/v1",
        "a fix list ordered by effect: not_loaded first, then degraded",
    ),
    artifact_expectations=(
        "omh_skill_eval/v1 is the command's own JSON: one row per host with status, root and findings, the catalog "
        "size and description total, overlap groups, and static findings, each finding with its message and fix",
    ),
    safety_rules=(
        "Report only what `omh skill-eval` printed; a host verdict is a load-and-list fact, never proof the skill "
        "helps a task.",
        "Never say a skill improves results without a with/without run on the same tasks; until then, say it was not "
        "measured.",
        "A lift run uses the user's subscription model and costs nothing extra by default; run a paid model only "
        "after the user approves that spend.",
    ),
    quality_bar=(
        "Run `omh skill-eval <dir>` (add `--catalog` for a folder of skills, `--install-root` when the folder is a "
        "source pack, `--json FILE` to keep the payload) and quote its rows; `--strict` exits 1 on any not_loaded or "
        "degraded row for CI.",
        "Read each host row as ✅ loads, ⚠️ degraded (listed but cut, shortened or partly unread) or ❌ not_loaded "
        "(the host never sees it), and a root of not_checked as unknown, not as fine.",
        "Fix at the source: put the situation or trigger first in the description so a short listing window keeps "
        "it, move long detail from SKILL.md into references/ files, name every toolkit/ or other unlisted path in "
        "SKILL.md so the agent can open it, and shrink the catalog (shorter descriptions, fewer skills per root) when "
        "a list budget is exceeded.",
        "Treat an overlap group (several skills opening the same way) as a routing risk: give each its own opening.",
        f"Load `{REFERENCE_PATH}` before claiming the skill makes answers better; a host verdict says nothing about lift.",
    ),
    why_this_exists=(
        "`skill-eval` exists because a skill that reads well can still be skipped or cut by the host that loads it: "
        "the wrong root, a description past the listing window, a catalog over its budget, a file the agent cannot "
        "open. The check is offline and cites the host fact behind each finding, so the fix lands before users do."
    ),
    opening_steps=(
        "Ask which folder to check and where it will be installed, then run `omh skill-eval <dir>` with "
        "`--install-root` when the path does not show it.",
        "Report the host rows and the final count line first, then the fixes for not_loaded rows before degraded ones.",
    ),
    do_not_use_when=(
        "The ask is a dashboard of the whole skill portfolio's drift, stale surfaces or pending amendments; use "
        "`skill-health`.",
        "The ask is finding an existing skill to adopt before writing one; use `skill-scout`.",
        "The ask is comparing coding agents or models on the same task; use `agent-evaluation`.",
        "OMH itself is not installed or its skills do not appear at all; use `doctor`.",
    ),
    good_example=SkillExample(
        prompt="I wrote a skill in ./my-skills/pdf-tables. Will it load in Claude Code and Codex?",
        expected=(
            "Run `omh skill-eval ./my-skills/pdf-tables --install-root .claude/skills`, then again for "
            ".agents/skills, quote each host row and give the fix for every ❌ and ⚠️ finding."
        ),
        why="The question is whether named hosts load the folder, which the offline check answers row by row.",
    ),
    bad_example=SkillExample(
        prompt="All hosts show ✅, so tell the team the skill makes our PDF answers better.",
        expected="Say the check shows only that it loads; offer the with/without run before any claim about results.",
        why="Loading is not lift; a better-results claim needs the same tasks run with and without the skill.",
    ),
    final_checklist=(
        "Every host verdict quoted came from `omh skill-eval` output in this session.",
        "Each ❌ and ⚠️ finding has a fix at its source file, or is named as accepted.",
        "No claim that the skill improves results unless a with/without table was observed.",
    ),
    recovery_notes=(
        "If every root reads not_checked, rerun with `--install-root` for the root the user will install into.",
        "If `omh` is not on PATH, install or update OMH first; the check has no other implementation to fall back on.",
    ),
    situations=(
        "my SKILL.md does not show up in claude code",
        "check a skill before I publish it",
        "will codex pick up this skill folder",
        "description too long for the skill list",
        "does the skill actually help or just load",
    ),
)


def skill_eval_definition() -> SkillDefinition:
    return DEFINITION


def skill_eval_reference_templates():
    from .render import SkillReferenceTemplate, loadable_skill_mentions

    return [SkillReferenceTemplate(DEFINITION.name, REFERENCE_PATH, loadable_skill_mentions(REFERENCE_TEXT))]


REFERENCE_TEXT = '''# With/without lift measurement

`omh skill-eval` answers whether a host loads a skill. Whether the skill makes the
agent's answers better is a separate question, and only this measurement answers it.
Until it has run, say "not measured"; never infer lift from a ✅ host row.

## Design

1. Fix a task set before running anything: 5 to 20 tasks the skill is meant for,
   plus 2 to 5 it should not change. Write each with a scripted check: a test, an
   exact expected value, a file that must exist, or a grep that must match. A check
   that needs a person's judgment is recorded as such, not scored by the agent.
2. Run every task twice, in separate fresh children, with the same prompt and model:
   - **with**: the child is told to load the skill (`skill_view(name)`) first;
   - **without**: the child gets the same prompt and is told not to load it.
   In Hermes each run is one `delegate_task` child; give the two arms the same
   toolsets and working copy, reset the working copy between runs, and record the
   model each child reports.
3. Run each arm at least twice per task when the check is noisy; report every run,
   not the best one.

## Cost

Children run on the session's model, which is the user's subscription by default:
cost 0 beyond that plan. Do not route an arm to a paid API model unless the user
approved that spend in this conversation, and name the model and its price first.

## Results table

| task | check | with: pass/runs | without: pass/runs | note |
|---|---|---|---|---|

Under the table: the model, the date, the skill's commit or file digest, and the
totals per arm. Lift is the difference in pass counts on the same tasks. A
difference of one task on a small set is noise; say so instead of calling it lift.

## What it does not show

- It does not show the skill loads on another host; `omh skill-eval` does that.
- It does not generalize past the task set and model it ran on.
- A task the skill should not change that now fails is a regression: report it
  next to the lift, not below it.
'''
