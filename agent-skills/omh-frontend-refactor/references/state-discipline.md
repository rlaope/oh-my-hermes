# State Discipline

The state-management review ladder for UI code. Work the sections in order:
an impossible-state fix or a derive-don't-store fix usually deletes the code a
later section would have restyled.

## 1. Make impossible states unrepresentable

Boolean flags multiply: four booleans is sixteen combinations, and most are
impossible. Replace flag clusters with one discriminated union -
`{status:'idle'} | {status:'loading'} | {status:'success', data} |
{status:'error', error}` - or a reducer whose one dispatch yields one valid
state. Escalate to an explicit state machine only when transitions carry
retries, resets, or concurrent-request races; the ladder is
`useState` -> reducer with a union -> machine, never machine-first.

## 2. Colocate, lift late, keep context slow

State lives with its consumers; wrap the consumers in a feature component that
owns it - check this before reaching for memoization. Lift state only when a
second component actually reads it. Context carries slow-changing values
(theme, locale, flags); a frequently-updated value in context re-renders every
consumer on every change. Shareable view state (filters, tabs, selection worth
a link) belongs in the URL [behavior-changing: it adds history entries and deep links].

## 3. Derive, don't sync

Never store what can be computed: a stored total beside its items drifts, and
an effect that copies props into state is a render cycle pretending to be
data flow. Compute during render; memoize only measured-expensive derivations.

## 4. Effects synchronize with the outside; they are not lifecycle

Gate question: is this effect syncing with an EXTERNAL system (socket, browser
API, third-party widget, DOM measurement, timer)? Props, state, derived
values, and user events are not external. If not external, in order:

- Deriving data -> compute inline during render.
- Responding to a user event -> the event handler, never an effect.
- Resetting state when a prop changes -> a `key` on the component [behavior-changing: it remounts the subtree and drops focus, scroll, uncontrolled input values, and child effect state].
- Fetching -> the query cache (section 5); an unavoidable fetch effect carries
  a stale-response guard in its cleanup.
- Notifying a parent -> call the callback in the same handler as the setState [behavior-changing: the notification moves from after render to the event, which changes its timing].
- An effect that sets state to trigger another effect -> one handler plus
  derivation; each chained effect is another full render pass.
- Subscribing to an external store -> the store-subscription hook, not manual
  listeners.

A correct effect has a nameable purpose, a cleanup, and a complete dependency
list.

## 5. Server state is not UI state

Adopting a query cache is [behavior-changing]: it adds a dependency and changes
caching, deduplication, retry, and refetch-on-focus behavior. In a refactor,
name it in Notes; do not apply it.

Remote data is asynchronous, shared, and stale-able; it belongs in a query
cache (keyed queries, stale times, retry policy), not in per-component
fetch effects or a global store. Every mutation names the query keys it
invalidates. Sibling components fetching the same data independently is the
red flag that the cache is missing.

## 6. The optimistic-update contract

Adding an optimistic update is a new feature, not a refactor [behavior-changing].
This contract is the review rule for one that already exists, and the shape a
feature request must meet.

Optimistic writes come as one triple: before the request, cancel in-flight
reads, snapshot the current data, apply the optimistic value; on error,
restore the snapshot and surface the error; on settle, invalidate so the
server answer wins. An optimistic update without its rollback path, or one
that swallows the error it rolls back from, fails review.

## 7. Closing checks

Items marked [behavior-changing] in this ladder are never applied under the
refactor invariants. List each in Notes with the observable change it causes.

- Ephemeral UI state in a global store -> local state [behavior-changing: it now resets on unmount].
- The same fact stored in two places -> one owner, derive the rest.
- Prop drilling four levels or more -> context (if slow-changing) or a store
  slice.
- No state reset on logout -> a root reset action plus cache clear [behavior-changing: it adds a behavior]; shared-
  device data leaks are a finding, not a nit, so report it and send the fix to `omh-frontend` or a feature request.

## Boundary

A state-discipline review is prepared analysis of the code as written; it is
not a performance measurement, an executed migration, review approval, CI, or
merge evidence.
