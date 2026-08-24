# Turning OMH Capability Families On and Off

OMH groups its installable workflow skills into six capability families. Before
this existed the only lever was binary — `core` or `full` — so wanting the coding
handoff surface but not the memory surface meant taking both.

A capability policy makes that choice per family, without uninstalling OMH.

## The six families

These are the same families the product already explains itself with, so
turning one off removes a group a user can already name.

| Family id | Turns off |
| --- | --- |
| `plan_and_decide` | Planning, interviews, decision framing |
| `learn_and_gather` | Research, sources, papers, briefings |
| `retain_knowledge` | Project memory capture and recall, wiki notes |
| `create_materials_and_visuals` | Decks, reports, frontend, visual QA |
| `delegate_coding_and_ship` | Coding handoffs, review, CI, merge readiness |
| `operate_and_observe` | Status, automation, audits, ops cards |

## Changing it

Ask in chat — "turn off memory", "메모리 기능 꺼줘", "disable coding
orchestration" — and Hermes routes to the `capability-toggle` skill.

The backing commands, for agents, wrappers, and maintainers:

```sh
omh capability-policy status                          # what is offered right now
omh capability-policy disable memory --dry-run        # preview, write nothing
omh capability-policy disable memory
omh capability-policy enable retain_knowledge
```

`<family>` accepts a canonical id, its label, or a short alias
(`memory` → `retain_knowledge`, `coding` → `delegate_coding_and_ship`). An
unrecognized value is refused with all six ids listed — it never guesses,
because disabling the wrong family is worse than refusing.

## What a disable actually does

- **Withholds that family's workflows.** Disabling `retain_knowledge` withholds
  `decision-recall`, `memory-new`, `memory-sync`, and `wiki`.
- **Stops memory for real.** `retain_knowledge` is the one family with runtime
  behavior behind it: `read_project_memory_policy()` resolves to mode `off`, so
  capture returns `project_memory_disabled` and recall returns an empty pack.
  The policy does not merely stop advertising memory.
- **Never removes core skills.** `oh-my-hermes`, `doctor`, `skill`, `cancel`,
  and `agent-ops-review` survive every disable. They are the floor `omh doctor`
  checks for; removing them would turn a deliberate opt-out into a broken
  install.
- **Is reversible.** Every change prints the command that undoes it.

## Where it is stored

Inside `~/.omh/setup-profile.json`, under `capability_policy`:

```json
{
  "schema_version": "omh_capability_policy/v1",
  "disabled_families": ["retain_knowledge"],
  "enabled_families": ["create_materials_and_visuals", "delegate_coding_and_ship",
                       "learn_and_gather", "operate_and_observe", "plan_and_decide"],
  "retained_core_skills": ["agent-ops-review", "cancel", "doctor", "oh-my-hermes", "skill"],
  "files_removed": false,
  "claim_boundary": "..."
}
```

An absent key means all six families are offered, so an install written before
this key existed keeps working with no migration.

`disabled_families` is the field that is read and enforced. If a hand-edited
file contradicts itself, the disable list wins and `enabled_families` is
rebuilt from it.

Every value is a scalar or a list of scalars on purpose: the setup-profile
correct/restore path drops nested dicts and floats, so a policy that used them
would silently lose its disable list on the next repair.

## Boundaries

A capability policy records which OMH surfaces this install offers. It does not
disable Hermes itself, does not uninstall the OMH plugin, and is not execution,
review, CI, or merge evidence. To remove OMH entirely, use the uninstall path
instead.
