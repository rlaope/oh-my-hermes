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

## 5. Call-site readiness gate

"Safe to merge" for a bump - including one a bot opened - is a verdict over
this table, not a reading of the changelog. One row per breaking change
between the two versions:

| Breaking change | Call sites in this repo | Stage | Rollback |
| --- | --- | --- | --- |
| upstream item, quoted | `path:line` per site, or the search run and its observed empty result | which stage handles it | how that stage is undone |

The plan is not ready, and the bump is not safe to merge, while any row has
an empty call-site cell or an empty rollback cell. A search that was prepared
but not run is an empty cell. An empty call-site list is a finding only when
the search that produced it is named, because an unrun search and a clean one
look the same in a summary.

## Phase order for an upgrade

The contracts-first order still holds, read for this shape. Each stage states
its own rollback:

| Stage | What it does | Rollback |
| --- | --- | --- |
| Prepare | compatibility shims and adapters that work on both versions | revert the shim commits; the old version still runs |
| Bump | manifest and lockfile together, ending green on their own | revert two files |
| Adapt | call sites move off the removed APIs, in reviewable groups | revert the group; the shims still cover it |
| Remove shims | cleanup, from a tagged rollback point | return to the tag |

Shims that run on both versions go first, so the bump stays a two-file revert
and every call site is covered while the adapt stage lands.

When no dual-version shim is possible (an ESM-only or peer-dependency major, a
framework whose old and new APIs cannot be imported together, a runtime or
language upgrade), say so, run the upgrade on a branch or behind a flag, and
make the rollback that branch plus the previous lockfile.

A runtime or toolchain upgrade (Python, Node, JDK, a compiler) adds its own
inputs: the version fields (`engines`, `requires-python`, `rust-version`), the
CI matrix, the base image, native-extension wheels or prebuilt binaries for the
new version, and the peer-dependency ranges of every direct dependency.

## Boundary

Advisory identifiers, licence text, and changelog entries are read from what
the user or the repository supplies; OMH fetches nothing. An upgrade plan is
not an applied upgrade, a passing suite, or evidence that the advisory is
resolved - the regenerated lockfile and a green run are separate observed
evidence.
