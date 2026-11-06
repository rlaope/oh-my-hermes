# Composing with Hermes' `spike`

Hermes bundles `spike` (MIT, adapted from the GSD project), a method for throwaway feasibility experiments. It and `decision-prototype` can load for the same request. `spike` owns how an experiment is built; this skill owns what the result may settle and how it is recorded. When both are loaded, build the way `spike` says and keep every record below.

## Who owns what

| Concern | Owner |
| --- | --- |
| Breaking an idea into questions, ordering them, building each experiment | `spike` |
| One decision id, its alternatives, and a falsifiable hypothesis | this skill. A `spike` table of several questions is several decisions: take the one planning is blocked on, or HOLD |
| Budgets with units, the scratch boundary, the observed cleanup | this skill |
| The verdict | `spike` writes one per experiment; this skill turns it into the receipt `ralplan` reads |

## Taken from `spike`

- Order experiments by how likely each is to kill the preferred option, and run the likeliest first; proving an easy part before the hard one buys nothing.
- Two approaches to one question are two arms of one experiment, numbered `002a` and `002b`, built one after the other, or as two `delegate_task` lanes when each arm is substantial, and closed with one side-by-side table on the measurement the decision named.
- Prefer an artifact someone can run and watch over output that only reports success, and try more than the happy path before calling an option supported.

## Verdict to record

| `spike` verdict | `execution_status` | Receipt |
| --- | --- | --- |
| `VALIDATED` | `observed` | the supported option, with the fixture and environment limits it was shown under |
| `PARTIAL` | `inconclusive` | the constraints it held under become evidence limits and unresolved questions; no option is chosen past them |
| `INVALIDATED` | `observed` | the rejected option, as a result: an experiment that kills an option has done its job |

A verdict from a single run, or from output nobody observed, is not `observed`.

## Where the files go

`spike` keeps its experiments under `spikes/` at the repository root and leaves them there. This skill writes only inside the declared scratch boundary, so point the experiment directory into it: a temporary worktree or a scratch directory. A `spikes/` directory left in the repository is a write outside the boundary unless the user approved it, `discarded` is reported only after the cleanup is observed, and experiment code reaches production only through a separate accepted plan.

Without `spike` loaded, the contract in `references/full-contract.md` runs exactly as before.
