# Adversarial Consensus Protocol

Load this reference when running the rounds. The always-loaded skill body states the rules; this is the per-round procedure, the wording that keeps a perspective independent, and the failure modes that make a run look adversarial while producing agreement.

Everything here is a prepared prompt contract. OMH runs no perspective and observes no round. A stated round transition is a declaration, not evidence that the round happened.

## 1. The Roster

Seat 3-5 perspectives. The suggested roster is `skeptic`, `validator`, `researcher`, `architect`, `creative`, and each seat is defined by the angle it attacks from, not by a job title:

| Seat | Attacks from |
| --- | --- |
| `skeptic` | The claim that is being assumed rather than shown. Asks what breaks if the load-bearing assumption is false. |
| `validator` | Verifiability. Asks how anyone would know this worked, and what the failing case looks like. |
| `researcher` | Prior art and current behavior. Asks what the sources, upstream docs, or the existing code already say. |
| `architect` | Structure and blast radius. Asks what else this couples to and what it makes impossible later. |
| `creative` | The unexamined framing. Asks what a different shape of the solution would cost, including doing nothing. |

Substitute a domain seat (security, cost, operations, accessibility) when the problem needs one. Two seats arguing the same angle is a duplicate, not a perspective: the roster's value is coverage, and a duplicated angle buys none while making the run look broader than it is.

## 2. The Rounds, In Order

1. independent findings
2. cross-attack
3. defend, refine, or concede

The order is the contract. Independence exists only before any seat has read another's findings, and an attack round placed after a defense round is agreement with extra steps.

### Round 1 - independent findings

Each perspective produces its findings without seeing any other perspective's output. Prompt each seat separately with the same problem statement, and give each one the same context: the proposal, the decision it must inform, and the known constraints. Nothing else.

Every finding names its evidence or labels itself an assumption. "This will not scale" is not a finding; "this holds every session in one process, and the deploy target runs four replicas behind a round-robin balancer" is.

Record all findings before opening round two. If the host cannot keep a seat blind -- one context window, one transcript, one agent playing every part in sequence -- say so and mark the round's independence as caveated. A caveated round is still useful. A run that silently claims independence it did not have is not.

### Round 2 - cross-attack

Every perspective attacks other perspectives' findings, and never defends or restates its own. Self-defense in this round is the single most common way the exercise collapses: the moment a seat is allowed to answer its critics, the round turns into a debate the loudest seat wins, and the objections stop being independent.

Each attack names the finding it targets and the specific reason it fails: unsupported evidence, a case it does not cover, a cost it does not price, or a conflict with another finding. A perspective with no objection to any other seat says so explicitly. An empty attack round is a roster defect -- state which angle is missing and fix the roster -- not consensus.

### Round 3 - defend, refine, or concede

Now, and only now, each perspective answers the objections against it. Exactly one verdict per objection:

- **Defend** - the objection is answered with evidence the original finding already had or can now cite.
- **Refine** - the objection lands partially; the finding is narrowed to what survives.
- **Concede** - the objection lands; the finding is struck from the record.

A conceded finding is struck, not softened into a hedge. "Possibly a concern" is how a conceded finding survives to become a Hard Constraint it never earned.

## 3. Distillation - The Lead Subtracts Only

The lead distills. Nothing new enters at distillation: every line in the bundle traces back to a finding that survived round three, and it goes into exactly one of these buckets:

- **Hard Constraints**
- **Decisions**
- **Risks**
- **Open Questions**

- **Hard Constraints** are the non-negotiables the plan must satisfy. A constraint here is one no surviving objection disputes.
- **Decisions** are what the rounds actually settled, each with the reason it settled that way.
- **Risks** are surviving objections that were refined rather than conceded: real, priced, and not blocking.
- **Open Questions** are the disputes the rounds could not settle and the evidence that would settle them.

The bucket set is closed. If distillation seems to need a fifth bucket, the extra content is a plan trying to escape -- move it into the handoff, not into a new bucket. An unsupported objection is an **Open Questions** entry, never a **Hard Constraints** one.

## 4. The Mandatory Handoff

The run ends with the bundle handed to a separate planning pass, and it ends there.

State plainly that the bundle (**Hard Constraints**, **Decisions**, **Risks**, **Open Questions**) is INPUT to planning, name the follow-on workflow -- `ralplan` when the plan itself needs review gates, `plan` when the shape is already agreed -- and stop.

**The anti-pattern:** treating the bundle as the plan. The four buckets read like a plan's front matter, which is exactly why the substitution is tempting and exactly why it is wrong. The bundle contains no sequence, no owner, no acceptance criteria, and no verification commands, because producing those is the planner's job and this workflow deliberately never did it. Emitting steps here skips the reviewed-plan gate and ships a task list that nobody planned.

## 5. Failure Modes

| Looks like | Actually is | Fix |
| --- | --- | --- |
| Every seat agrees in round one | The seats were not independent, or the roster duplicates an angle | Re-run the seats separately; replace a duplicate seat |
| Round two is polite | Self-defense leaked into the attack round | Restate the round rule and re-run round two |
| Buckets full of "consider", "possibly", "may want to" | Conceded findings were softened instead of struck | Strike them; a hedge is not a constraint |
| The bundle has steps and an order | The distillation became a plan | Move it to the planner handoff |
| One long transcript, all seats | Independence was structural, not real | Keep it, and mark the caveat rather than claiming independence |

## 6. Attribution

The round structure, the no-self-defense rule, and the distill-only discipline are adapted from published multi-agent planning practice; no upstream text is reproduced. The bucket set, the closed-set rule, and the `prepared_not_observed` claim boundary are OMH's own contract vocabulary.
