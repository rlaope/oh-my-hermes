# Dependency and Framework Upgrades

A major upgrade is a boundary-changing refactor whose direction was decided by
somebody else. The phase contract in `references/refactor-phases.md` carries
the execution shape unchanged - reconnaissance, contracts-first order,
per-phase verification and rollback, the files table, the approval gate. Four
things are specific to an upgrade, and all four are read before the first
phase is ordered.

## 1. Advisory intake

Establish why the upgrade is happening, because it sets the deadline and the
acceptable risk:

- Which advisories or CVEs the current version carries, with their identifiers
  and severity, and whether a patch release fixes them without the major jump.
- Whether the current version is still supported upstream, and the end-of-life
  date if one is published.
- Whether any advisory is reachable from this codebase. An advisory in a code
  path nothing calls is a different deadline from one in the request handler,
  and saying which is a finding, not a detail.

A security-driven upgrade and a housekeeping upgrade produce different phase
plans: the first may ship the version bump alone and defer the API migration,
which is a legitimate split; the second has no reason to.

## 2. License delta

The new version may not carry the old licence. Read the licence file at the
target version rather than the package metadata, which lags. Record the
before and after, and flag a change from permissive to copyleft, a change to a
source-available or dual licence, and any new attribution requirement, as a
blocker for the user's decision rather than a note in the plan. The same
applies to transitive dependencies the upgrade adds - a new direct dependency
is visible in the diff, a new transitive one is visible only in the lockfile.

## 3. The upstream migration guide is an input, not a summary

Read the upstream migration guide and the changelog between the two versions,
and record for each breaking change: the upstream item, whether this codebase
is affected, and which phase handles it. A breaking change nobody checked is
not "probably fine", and a guide that does not mention something this codebase
does is a gap to record, not silence to interpret.

Two things the guide will not tell you and the reconnaissance must: deprecated
APIs this codebase uses that still work in the target version - they are the
next upgrade's breaking changes - and behaviour changes that are not API
changes, such as a different default, a changed error type, or a changed
ordering guarantee. Those pass the typechecker and fail in production.

## 4. Lockfile discipline

The lockfile is the artifact the upgrade actually produces.

- The lockfile changes in the same commit as the manifest. A manifest bump
  without its lockfile is a change nobody can reproduce.
- Regenerate it with the project's own tooling and version; a lockfile written
  by a different package-manager version reorders or reshapes entries and
  buries the real delta.
- Review the transitive delta, not only the direct one: read what was added,
  removed, and moved, and pair each unexpected addition with the direct
  dependency that pulled it in.
- Never hand-edit a lockfile to force a version. Constrain it in the manifest
  and regenerate, or the next regeneration silently undoes it.
- A monorepo with several lockfiles upgrades them together or states which are
  deliberately pinned behind and why.

## Phase order for an upgrade

The contracts-first order still holds, read for this shape: the version bump
and lockfile are the first phase and must end green on their own; adapters for
renamed or moved APIs come next; call sites follow in reviewable groups; test
and fixture updates follow those; removal of the compatibility shims is the
cleanup phase. Rolling back the first phase is reverting two files, which is
why it is first.

## Boundary

Advisory identifiers, licence text, and changelog entries are read from what
the user or the repository supplies; OMH fetches nothing. An upgrade plan is
not an applied upgrade, a passing suite, or evidence that the advisory is
resolved - the regenerated lockfile and a green run are separate observed
evidence.
