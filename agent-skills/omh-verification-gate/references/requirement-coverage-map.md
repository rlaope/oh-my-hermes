# Requirement Coverage Map

`verification-gate` names which commands count as evidence. This names what the
evidence has to cover. Load it when a change answers to a written spec, plan, or
issue and the question is whether anything was left unbuilt, not whether the
build passed.

The pass is **strictly read-only**. It reads the requirement text, the task
list, and the diff, and it writes one report. It never edits a spec, never ticks
a box, and never re-runs the work. A coverage map is something a model fills and
a person or CI then checks; the filled map is not itself evidence that anything
was verified.

## Stable ids come first

Every requirement gets an id before anything is mapped, because a finding that
points at a paraphrase cannot be looked up twice.

- `FR-###` for a functional requirement: something the system must do.
- `SC-###` for a success criterion: a measurable outcome that gates acceptance.
- Reuse an id the source document already assigns. Never renumber; a renumbered
  map silently invalidates every prior report.
- When the source has no ids, assign them in document order and say in the
  report that the ids are assigned by this pass, not by the spec.

Exclude from `SC-###` any outcome that no work item could produce - adoption
targets, revenue, ticket volume. They are real goals and they are not coverage
gaps. A criterion earns an id when some buildable task could satisfy it.

## The three-column map

One row per requirement id. The row is the unit of the whole pass.

| Column | What it holds | Filled by |
| --- | --- | --- |
| Requirement | `FR-###` / `SC-###` plus a one-line restatement | this pass |
| Tasks | every task id that claims to satisfy it, or `none` | this pass |
| Evidence | the command, test name, or artifact path that would fail if it regressed, or `none` | this pass |

A task id in the second column is a claim. The third column is where the claim
becomes checkable, and `none` there is the finding this map exists to produce: a
requirement with a task and no evidence is work that nothing would catch
breaking.

Map a task to a requirement by an explicit id reference where one exists. Where
the task only names the behavior, say so in the row - an inferred mapping and a
declared mapping are not the same claim, and a report that hides the difference
launders a guess into coverage.

## Six passes, run separately

Run each pass over the whole map before starting the next. Bundling them
produces one undifferentiated list in which the cheap findings bury the
expensive ones.

1. **Duplication** - two requirements asserting the same thing under different
   ids. Keep the one that is measurable; mark the other for consolidation.
2. **Ambiguity** - an unquantified adjective standing where a threshold belongs
   (fast, secure, robust, intuitive), or an unresolved placeholder left in the
   text.
3. **Underspecification** - a requirement with a verb and no object, no
   measurable outcome, or an acceptance criterion nothing could fail.
4. **Principle conflict** - a requirement that contradicts a non-negotiable
   project principle. See `omh-plan/references/project-constitution.md`; a
   conflict found here is automatically the top severity.
5. **Coverage gaps** - a requirement with no task, a task mapped to no
   requirement, or an `SC-###` whose satisfying work is absent from the list.
6. **Inconsistency** - one concept under two names across documents, an entity
   present in the plan and absent from the spec, or an ordering that puts
   dependent work ahead of what it depends on.

## Severity

Four levels, assigned by what the finding costs if it ships, never by how
confident the reader feels.

- **Critical** - conflicts with a non-negotiable principle, or a requirement
  with zero coverage that blocks the change's stated purpose.
- **High** - conflicting requirements, an unquantified security or performance
  attribute, or an acceptance criterion no command could fail.
- **Medium** - one concept under two names, a non-functional requirement with no
  task, an edge case named and not specified.
- **Low** - wording and redundancy that does not change what gets built.

## Finding ids and the cap

Prefix each finding with its pass initial and number within that pass: `D1`,
`A1`, `U1`, `P1`, `C1`, `I1`. Ids are per-pass and stable, so re-running against
unchanged inputs produces the same ids and the same counts. A report whose ids
move on a no-op re-run cannot be diffed against the previous one.

Cap the findings table at fifty rows. Order by severity, then by pass order.
When more than fifty qualify, list the top fifty and add one overflow line
naming how many were withheld and in which passes they fell - never silently
truncate, and never drop a Critical to make room.

## Metrics block

Close the report with these, and nothing derived by hand from them:

- requirements mapped, by kind
- tasks mapped, and tasks mapped to no requirement
- coverage percentage: requirements with at least one task, over requirements
- requirements with zero tasks
- requirements with a task and no evidence
- findings by severity

Coverage percentage answers one question only: how much of the written
requirement set something claims to address. It is not a pass rate, and a high
percentage over a map whose evidence column is mostly `none` is the worst state
this pass can find, not a good one.

## What the report may end with

Recommendations, addressed to a person. Name the requirement id, the pass that
found it, and the smallest change that would close it. Never apply one. When the
map is clean, say so with the metrics block attached; a zero-finding report with
its counts shown is a result, and a zero-finding report without them is a
missing measurement.
