# Refactor Passes

The pass contract for behavior-preserving UI refactors. Preview is the default
mode: analyze the whole target, emit the structured change plan, touch nothing.
Apply is a second, explicit step - and a change that cannot be applied safely
in isolation (a rename that spans files, a moved export) is reported under
Notes, never half-applied.

## Behavior invariants (every pass, every change)

- Outputs, return values, and side effects stay identical.
- No error handling is removed or weakened, and no branch is silently dropped.
- No public surface - exports, props, emitted events, URL contract - is renamed
  without flagging a breaking change; cross-file renames go to Notes.
- Never refactor: export names, signatures or parameter order, file merges or
  splits, async execution models (a `.then` chain expressing parallelism stays),
  algorithmic logic that would merely get shorter, or test files.
- The line between apply and Notes: a change inside one file that keeps every
  component's props, exports, and file layout is applied. A change that alters
  props, exports, or events, or adds, merges, or splits a file, is a breaking
  change: it goes to Notes as a proposal and is applied only on the user's
  explicit second decision. The macro tiers below are read through this line.
- Never in a refactor: a new dependency, or a change in observable timing,
  remounting, caching, or network behavior. Such items are marked
  `[behavior-changing]` and go to Notes for `omh-frontend` or a feature request.

## Preview output, per change

Category, `[line N]`, before/after snippet, and one sentence on why it is safe.
Close with a per-category count table, omit empty categories, and say plainly
when nothing was found.

## The micro pass — single file, fixed order

Run categories in this order and finish one before starting the next:

1. **DEAD** - unused imports, bindings, and unexported functions; commented-out
   blocks of two or more lines (version control preserves history); unreachable
   code after return/throw/break/continue.
2. **NAMING** - cryptic names (loop `i`/`j`/`k` exempt); booleans without an
   `is`/`has`/`should`/`can` prefix; magic numbers and strings to named
   constants (`0`, `1`, `-1` exempt).
3. **SIMPLIFY** - guard clauses over nested precondition `if`s; early returns
   over inverted pyramids; `flag === true` to `flag`; an if/else assigning one
   variable to a conditional expression.
4. **MODERN** - `var` to `const`/`let` only when no use precedes the
   declaration, nothing is redeclared, and no closure captures a loop variable
   (hoisting, the temporal dead zone, and per-iteration binding change
   behavior); `.then` chains to async/await except where the chain expresses
   parallelism or fire-and-forget; spread over `Object.assign({}, ...)` only
   when the target has no setters; arrows for callbacks that use none of
   `this`, `arguments`, `new`, or `bind`.

## The macro pass — architecture, ordered by impact

Take these in impact order; stop at the first tier the diff budget allows.

1. **Component architecture** - props explosion to composition; render props to
   hooks; container/presentational split; compound components over config-object
   props; client-boundary directives pushed to leaf components.
2. **State architecture** - the whole of `references/state-discipline.md`; run
   it before any naming or style work, because a state fix usually deletes the
   code the style pass would have polished.
3. **Hook patterns** - extract when the behavior is nameable; one
   responsibility per hook; compose hooks instead of nesting them; stabilize
   dependencies instead of silencing the linter.
4. **Decomposition** - the scroll test: a component you must scroll to read is
   the entry point; extract along independent change reasons, completely - a
   half-extracted component is two coupled ones; inline a premature abstraction
   before re-extracting it properly. Premature means the deletion test passes:
   removing the component or hook makes its complexity vanish because it only
   forwarded, renamed, or re-wrapped. One that hides a parser, a policy, or a
   formatting rule behind a small interface stays, whatever its caller count.
5. **Coupling** - break circular imports with an intermediate module; import
   from public surfaces, not sibling internals.

## The safety gate

Before any macro change: characterization tests on the current behavior - what
it renders for known props/state, what it calls when interacted with. Snapshot
tests do not count; they lock markup, not behavior. Prefer behavior-level
integration tests over implementation-detail unit tests, and write them BEFORE
the refactor, not after.

Green tests do not prove the render is unchanged. Extraction adds wrapper
elements that break child-combinator, flex-child, and grid-child selectors,
and reordering merged class names changes which style wins. So when a change
alters DOM nesting, element type, or class composition, capture the affected
component before and after apply at one viewport and compare the two (capture
mechanics: `omh-frontend/references/screenshot-loop.md`). A visible
difference is a behavior change under the invariants above: revert it or
record it as a finding.

## Boundary

A preview plan and a pass report are prepared context; behavior preservation
is claimed only from the observed test runs before and after apply, and a pass
report is never review, CI, or merge evidence.
