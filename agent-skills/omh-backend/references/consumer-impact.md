# Consumer Impact and Sunset

The contract's shape and the contract's evolution belong to the same owner.
Split across two skills, the response envelope and the deprecation window drift
apart, and the surface ends up with a rule for how it looks and no rule for how
it changes.

## Enumerate consumers before designing the change

Work the sources in order, and record which ones were searched - the list is
only as good as its coverage, and the coverage is the part a reader cannot
reconstruct later:

| Source | Finds |
| --- | --- |
| This repository | internal callers, generated clients, fixtures and contract tests naming the field |
| Generated client packages | published SDKs whose consumers you cannot see |
| Access logs by API key, user agent, or client id | who actually calls the endpoint, and how often |
| The spec's own history | who asked for the field, in the commit or PR that added it |
| Partner or integration registries | named external consumers under an agreement |

Then say what the search could not reach. Consumers outside the repository are
unknowable from it: a public API, a published SDK, a webhook anybody may
subscribe to, and an internal caller in another team's repo are all invisible
to a code search.

**An empty consumer list is a claim.** Reporting zero consumers says the search
was complete and found nothing, which is a much stronger statement than "the
search covered this repository and no more". When the set cannot be closed,
report `consumers_not_enumerable` and name what was searched, so the reader
knows the shape of the gap rather than reading confidence into silence.

## Grade what breaks, per consumer

Not every change breaks every caller. Say which, and say why:

- **Removing a field** breaks readers that require it; a reader tolerating
  unknown fields is unaffected by an addition but not by a removal.
- **Narrowing a type or an enum** breaks writers sending the old range, and
  silently breaks readers that switch exhaustively.
- **Adding a required request field** breaks every existing caller.
- **Changing an error code, status, or error body shape** breaks retry and
  error-handling logic, which is the breakage nobody's contract test covers.
- **Changing pagination, ordering, or default limits** breaks clients that
  depend on the old behaviour without declaring it - the hardest class to find
  and the one access logs answer better than code search.

## The window, the path, and the date

A deprecation with no date is a warning nobody acts on:

- **Compatibility window** - how long both behaviours are served, stated as a
  date and not a release count. Size it against the slowest consumer you
  identified, not the median, and against `consumers_not_enumerable` if the set
  is open.
- **Migration path** - what a consumer does, concretely, including the new
  field or endpoint and any semantic difference. "Use v2" is not a path.
- **Announcement** - where consumers are told, and the observation that proves
  they were told. A changelog entry nobody reads is prepared, not delivered.
- **Sunset date** - when the old behaviour stops. Name what is observed before
  it arrives: the old surface's traffic falling to zero, or to a known set of
  consumers who have accepted the break.
- **What happens after** - the removed surface returns a specific status and
  error body rather than a generic 404, so a late caller gets a diagnosis.

An open consumer set does not block the deprecation; it changes the window and
the announcement, and it must say so rather than shortening the window on an
assumption.

## Boundary

A consumer list, a window, and a sunset date are prepared. Traffic figures,
access-log analysis, and the observation that consumers migrated are observed
evidence and come from the operator; a prepared sunset plan is not a removed
endpoint and not proof that anybody was told.
