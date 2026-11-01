# Hermes `/plan` and `plan`

Hermes ships a built-in planning command, `/plan`. This page says where its turn ends and this skill begins, so one request does not end up with two plans or two acceptance rules.

## The `/plan` turn

`/plan <task>`, or `/plan` alone to plan whatever the conversation is about, makes Hermes send a turn of its own that opens `[/plan — plan mode]`. That turn allows read-only inspection and nothing that changes the project apart from one markdown file: `.hermes/plans/<timestamp>-<slug>.md` in the workspace, or a path the runtime supplies. It closes with a short reply naming the file and an offer to carry the plan out.

In that turn, follow its instructions: write the file, reply, and stop. OMH's router does not route a turn Hermes wrote, and nothing in this skill overrides it there.

## After it: the file is the draft

When the user then asks to review, refine, accept, or hand off the plan, read that file and run this skill on it instead of writing another plan:

- Add what the file lacks among goals, non-goals, risks, acceptance criteria, and verification shape, and when it describes code changes, the `Review Focus` section, each task's id, dependencies, write scope and done check, and the closing gate task.
- Hold every step to this skill's step shape.
- Run the proportion check. `/plan` asks for complete code inside its steps, and this skill keeps code bodies out of a plan: reduce each body to the test name and what it asserts, an exact signature and its file, or a command and the output that passes. Say which steps you reduced. The file is the user's; change it only as part of the plan you put to them for acceptance.
- Take acceptance from the user's own answer, exactly as for any plan. The file existing is not acceptance, and neither is `/plan`'s offer to carry it out: nothing is handed off or started until the user accepts.

## Two stores

The file stays where `/plan` wrote it. A reviewed plan that `ralplan` records goes under `.omh/plans/`; when a task has both, the closing brief names the one the user accepted.
