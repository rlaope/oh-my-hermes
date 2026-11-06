# Review Lenses

`code-review` runs one bug-first pass. This splits the reading into five named
lenses run as separate passes over the same diff. Load it when a change is large
enough, or its failure mode quiet enough, that one pass will find the first
class of problem and stop looking.

One pass finds what its opening question primes it to find. Load
`references/risk-selection.md` to select additional passes from changed risk and
budget, not to require all five. Keep this order among selected lenses and record
which actually ran; a two-lens review is not a five-lens review.

## The verification-gap lens

This is the lens with no equivalent elsewhere in OMH, and the one to run when
only one is affordable. It asks a different question from every other lens: not
*is this correct*, but **if this behavior broke tomorrow, would anything go
red**.

Work it in order.

1. **Is there a behavioral change at all?** Formatting, comments, pure renames,
   and type-only edits that cannot change a return value, a raised error, a
   visible side effect, or observable state are non-behavioral; stop and report
   zero findings. One exception: a test-only change that deletes or weakens
   verification is in scope, because that is the gap itself.
2. **Name what changed.** The return value, the branch taken, the error path,
   the payload shape, the default, the validation rule. Handle each separately.
   A dependency, toolchain, or data-file change is behavioral even when no line
   of logic moved.
3. **Trace to where it is observed.** Direct callers, registered entry points,
   schema and event consumers. Follow a path only while the changed behavior is
   still reachable and still unverified. Stop at the nearest boundary where a
   test would fail, or where the next hop is guesswork.
4. **State the smallest regression the consumer would see** - invert the branch,
   drop the default, omit the field, return the previous error code. Then read
   the test that should catch it and ask whether that regression would make an
   assertion fail.

Three shapes qualify as findings:

- **Regression gap** - the change can regress at that consumer and no test
  covering it would fail.
- **Missing-adoption gap** - a site that should now use the new behavior still
  does its own thing, and nothing flags the omission. This qualifies only with a
  supersession signal, meaning the change itself shows the new behavior is
  intended to replace the local one. Without that signal it is a refactor
  suggestion.
- **Broken-verification gap** - a test looks like it covers the behavior and
  would not protect it: skipped, not in the normal run, or asserting something
  that passes either way.

A test counts only if it runs in the normal verification path and an assertion
observes the changed value. These do not count: no-throw and snapshot-only
checks, mock-call assertions, a test that mocks away the integration under
review, and an end-to-end test that exercises the path without checking the
changed output.

**Read the test before saying what it covers.** Before claiming no test exists,
search the repository by symbol and by import reference; the file where it ought
to live is not enough. Then say in the finding how far you looked. "None of the
tests I read cover this" is a reportable observation. "There is no test" is a
claim about the whole repository and needs the search behind it.

## The other four

- **Adversarial** - read the diff as someone trying to make it fail. This pass
  must produce at least one finding or an explicit statement of what was
  attacked and held; "looks fine" is not a result of an adversarial pass.
- **Edge case** - walk every branch and every boundary the change introduces:
  empty, one, many, maximum, absent, malformed, concurrent, and the error path
  out of each.
- **Structure** - the shape of the change against the shape of the codebase.
  Misplaced responsibility, a seam in the wrong place, an abstraction that will
  need undoing before the next change. When ownership, contracts, dependencies,
  or reuse change, load `references/architecture-delta.md`, including its
  extraction proof rubric; a file move or large file alone is not a defect.
- **Prose** - comments, docstrings, commit and report text. A comment that
  overclaims what a guard proves is a review finding here, not a nitpick: the
  next reader trusts it instead of re-deriving it.

## Findings

Each lens reports under its own name, so a reader can tell a structural opinion
from a verification gap. Within the verification-gap lens, do not assign
severity, confidence, or priority: a gap is present or it is not, and ranking
invites resolving it by argument instead of by a test. The other four lenses
carry severity as `code-review` already defines it.

Put these gap rows in `verification_gaps`, not in `findings`. Require `path`,
`line_range`, and `evidence`; include the regression and search scope in the
evidence. Keep `priority`, `confidence`, and `severity` absent. An independently
established defect may also have an ordinary ranked finding, but a missing assertion alone
does not prove one. Gaps do not automatically block; apply repository policy.

Drop any finding that cannot be grounded in something read. A lens that returns
nothing returns nothing, and reports it.
