# Generated-Artifact Provenance

Editing a generated file is caught after the fact, if at all: the change looks
correct, review passes, and the byte gate rejects it - or worse, nothing
rejects it and the edit disappears at the next regeneration. This row asks the
question while the diff is still being written.

## The map is declared, never inferred

A generated path is one the repository says is generated. Look, in order, for:

- A generated-artifact table in the contributor docs (`CLAUDE.md`, `AGENTS.md`,
  `CONTRIBUTING.md`) pairing source, output, regeneration command, and gate.
- A codegen config that names its outputs (`buf.gen.yaml`, `openapi-generator`
  config, `protoc` invocations, `sqlc.yaml`, schema-to-type generators).
- Build or CI steps that regenerate and then fail on a dirty tree - a
  `--check`, `--verify`, or `git diff --exit-code` step names its outputs.
- A lockfile or vendor directory the tooling owns.

If none of these exists, the answer is `map_not_declared`. Say that and stop.

**Never guess from filename patterns.** `*.generated.ts`, a `dist/` or `gen/`
directory, and a "DO NOT EDIT" header are conventions, not declarations: plenty
of hand-maintained code lives in `gen/`, and plenty of generated code carries no
marker. The asymmetry decides this. A false positive tells someone their
correct edit belongs in a generator that does not produce that file, and they
either obey and lose the change or stop trusting the check. A miss costs one
regeneration. Report the uncertainty instead of resolving it.

## The row

One row per touched generated path:

| Field | Content |
| --- | --- |
| `path` | the generated file the diff touches |
| `source_of_truth` | the file or schema the generator reads |
| `regenerate` | the exact command, copyable |
| `gate` | the check that fails when the two disagree, or `no_gate` |
| `declared_by` | where the map was read from |

`no_gate` is worth recording on its own: a generated artifact nothing verifies
drifts silently, which is a finding about the repository rather than about this
diff.

## A generator and its output together is the correct shape

The whole point of the redirect is to move the edit into the source, and the
source change regenerates the output, so both appear in the same diff. That is
success, not a violation. Report a finding only when the output moved and its
source did not.

Two shapes that look like violations and are not: a regeneration that changes
formatting across many files after a generator version bump, and an output
committed alone because its source lives in another repository. Both are
answered by the `declared_by` field, not by the path.

## Where this sits among the gate's other rows

Provenance runs before the checks, not among them. The other rows ask whether
the change is proven; this one asks whether the change is in the right file at
all, and it is cheapest to answer before the work is done. It is also not a
substitute for the gate: a diff that edits the source correctly still has to
regenerate and still has to pass the byte check.

## Boundary

A provenance row is read from a declaration and a diff. It is not a
regeneration, not a passing gate, and not proof that the named command produces
the committed bytes; running the command and observing a clean tree is separate
observed evidence.
