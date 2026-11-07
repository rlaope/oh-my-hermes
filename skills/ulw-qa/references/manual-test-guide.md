# Manual Test Guide

Load this reference when part of a change cannot be proved by a check that runs on its own and a person has to try it by hand: a CLI flag, a migration, a config change, a daemon restart, an install on a real machine. If the surface RENDERS -- a page, an image, a TUI frame -- its guide is `omh-visual-qa`'s viewport and state matrix instead, and that skill owns the capture rules this page does not repeat.

## The Guide Is a Handover Artifact, Never Evidence

Writing the steps does not run them. A finished guide is `prepared_not_observed`, and nothing the writer does moves it out of that state -- only a run can, and a run produces its own separate record.

In `omh-verification-gate` vocabulary: each written step is a `verification_matrix/v1` row with no result yet. A person who runs one can supply what that skill declares as "observed_check_results/v1 with command (verbatim, not a description of it), source (this checkout, a CI job, or an operator report), exit status, summary (what the output said), scope (what that run covered, since a narrower run proves less), freshness (when it ran, and whether the tree has moved since), and origin (for a failing check: introduced, pre_existing, or unknown)" -- quoted from its own artifact expectations rather than restated, so this page cannot drift from the gate it defers to. That row is the evidence, never the step it came from. Freshness is the field a manual run most needs and most often loses: a person's report is the likeliest stale output there is, and the gate refuses stale output as evidence outright. A report of "looks fine" supplies none of the fields at all, and is the self-referential shape (`TBD`, `works as expected`) that gate already refuses; a spoken report earns no exemption from the refusal.

The row is also where the evidence stops. OMH persists no verification output (#1782), so a row a person reports lives in this session's context and nowhere else -- the same thing `omh-wiki/references/handover-artifacts.md` marks with its "Held where" column. A later reader cannot re-read the result; they can only run the step again, which is one more reason every step names the build it ran against.

`ulw-work/references/tdd-red-green.md` refuses manual testing as a way to close a tests-first lane, because it leaves no output to paste and no command to rerun. That refusal is unchanged here. This page is what to write when a check genuinely cannot be automated; it is not a second route to the claim the other page denies.

## A Step Earns Its Place Only When No Check Can Hold It

A step that could be an automated test is an automated test: write the test and drop the step. A guide is otherwise where unwritten tests accumulate, and each one then costs a person's time on every release instead of a machine's on every commit.

Four reasons admit a step, and the step names the one it claims:

| Reason | What it means |
| --- | --- |
| `needs_real_install` | The behavior appears only in an installed generation on a real machine -- packaging, update, `PATH`, or a host that loads the artifact with its own interpreter. |
| `needs_external_service` | A service, credential, account, or device the harness cannot reach. |
| `needs_human_judgement` | The outcome is whether a person understood, noticed, or recovered -- not a value a comparison can settle. |
| `needs_destructive_state` | Reaching the state destroys something the test environment cannot afford to lose or cannot restore. |

A step carrying none of the four is a test that was not written. Say so, and write the test.

## What One Step Holds

| Field | What it holds | What fails it |
| --- | --- | --- |
| Setup | The exact build -- a revision, or an installed generation and how it got installed -- plus every starting condition the behavior depends on: config keys with their values, files that must exist, the version the data sits at, and what to restore afterwards. | "on a recent build". A setup that does not name its build describes the writer's machine. |
| Do | One action, written as the literal command, keystroke, or click. | A paraphrase. The reader retypes what is written, so a paraphrased command is a different command. |
| Expect | One observable to compare against: an exact output line, an exit status, a file that now exists, a count, a row that appears. | "it should work". That moves the judgement to the reader and records nothing either of you can cite afterwards. |
| Broken | The signal that says this failed -- above all the NEAR-MISS, the wrong result that reads like the right one. | Only the obvious failure. The obvious failure needs no guide. |

`Broken` is the field usually left out and the one that earns the guide. Two shapes out of this repository's own history: a command that exits `0` over work that failed, so a reader checking only the status is told it worked; and an `ImportError` naming a stale build directory rather than the branch, which reads as this change's regression and belongs to the environment. A reader who was not told which wrong-looking result is the known one will report the known one and miss the new one.

## Enumerate, Do Not Sample

The rule `omh-visual-qa` holds for pages, states, and viewports holds here for everything else. List every flag and its default, every config value that changes the path taken, every version a migration can be reached from (fresh, previous, two behind), and every platform whose behavior differs. A guide that walks the happy path exercises the case that already worked.

Each step also names what it depends on, so a reader whose step 3 fails knows whether steps 4 through 9 still mean anything. A partial run is the ordinary outcome, and it has to stay readable.

## Where the Material Comes From

The same source discipline as `omh-wiki/references/handover-artifacts.md`, which owns the full table; read it there rather than from a copy. Three points decide this artifact:

- The plan record (`omh runtime todo show`) is the only source that outlives the session. Its `blocked_reason` fields are where the judgement calls that now need a manual check were recorded while they were still true.
- Verification-gate, review, and QA output live in this session's context and nowhere else, so a guide written late in a long story may find nothing left in them. Record which sources you could actually read; never reconstruct what is gone.
- This artifact has one source the three closing artifacts do not: the diff and the repository's own documentation, which the next reader can re-derive from as well. A step taken from them says so, and anybody can check it.

Every step either restates a source you could read or is marked as the writer's own inference. There is no third category.

## When the Phase Does Not Apply

`VI. Manual test guide` is a phase of the `code-story` plan template, and a change with no surface a person can reach by hand owes no guide. The phase still does not leave the plan: it is carried `state: done` with a `blocked_reason` saying why, and the coverage rule refuses a stamped plan that is missing it.

The reason is the deliverable in that case, so write one worth reading. Name the surfaces that were considered and found unreachable by hand rather than writing "no UI" -- a later reader deciding whether the skip still holds needs to know what was looked at.

## What `done` Means Here

`done` on `VI. Manual test guide` says the guide exists. It does not say anyone followed it, and no record can say that: OMH observes declarations, never work.

A completion claim citing this guide is therefore citing a plan. `omh-verification-gate` returns HOLD or BLOCK on it with the manual checks listed as not-run, which is the correct verdict. The guide's job is to make that list short, specific, and cheap for somebody to close.
