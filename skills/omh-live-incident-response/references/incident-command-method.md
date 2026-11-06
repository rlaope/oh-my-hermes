# Live Incident Command Method

The ladders, entry shapes, and cadences the workflow body points at. Open this while the incident is open; the body carries the rules that hold whether or not it is open.

This commands an incident that is still running. Once it is closed, the postmortem, the SLO consequence, and the remediation follow-ups belong to `omh-reliability-review`, which reads the timeline this workflow wrote.

## 1. Severity is declared state, not an adjective

Severity is a value somebody set at a time, from an observed fact. Record the level, the fact, the person, and the timestamp; a change appends a new entry and never overwrites the old level.

| Level | What makes it this level | Consequence |
| --- | --- | --- |
| SEV1 | A core flow is unavailable or wrong for most users, or data is being lost or corrupted | page immediately, commander required, customer notice drafted before mitigation lands |
| SEV2 | A core flow is degraded, or one flow is unavailable for a bounded set of tenants or regions | page the owning team, commander required, customer notice prepared |
| SEV3 | A non-core flow is degraded, or a core flow has a working workaround | owning team handles in hours, commander optional, no customer notice unless asked |

Two rules the ladder cannot state for you. Severity is set from observed blast radius, never from how alarming the alert text reads. And an unknown blast radius is declared at the higher level until measured, then lowered by an appended entry that names the measurement.

## 2. Roles

One person per role, and one role per person while the incident is small.

- **Commander** — owns decisions and the severity level. Does not debug. When the commander starts debugging, the incident has no commander.
- **Operations** — the only person changing production during the incident. Every change is announced to the commander before it is made and appended afterwards.
- **Communications** — owns the customer notice, the status-page text, and internal updates. Writes them; `omh-apps` sends them.
- **Scribe** — owns the timeline. Appends what was observed, changed, and decided, with times.

A role nobody filled is recorded unfilled with the reason, never left blank. Below SEV3 the commander may hold scribe; the commander may never hold operations.

## 3. Timeline entries are append-only

Three types, no others:

| Type | What it records | Required fields |
| --- | --- | --- |
| `observation` | something seen: a metric, an error, a customer report | time, actor, source, the value or quote |
| `action` | something changed: a restart, a flag flip, a rollback, a scale-up | time, actor, what changed, where, whether it is temporary |
| `decision` | something chosen: a severity change, a mitigation approved, a role handed over | time, actor, the choice, the reason at the time |

A correction is a fourth entry of the matching type that names the entry id it corrects and says what was wrong. Never edit, never delete, never reorder. The value of the timeline afterwards is that it records what was believed when, and an edited entry destroys exactly that.

Record the reason at the time it was believed, not the reason that turned out to be right. A timeline rewritten with hindsight teaches the review nothing.

## 4. Mitigation is not a fix

A mitigation stops the damage; a fix removes the cause. Record every mitigation with four fields: what changed, where, `temporary` or `permanent`, and what removes it.

Mitigations that are almost always temporary, and so almost always need the removal recorded: a feature flag turned off, traffic shifted away from a region, a rate limit lowered, a cache extended, a consumer paused, a job disabled, a rollback to an older build.

An undeclared temporary mitigation becomes permanent because nobody wrote down that it was supposed to come back. That follow-up is the one item this workflow hands to the review even when the incident is otherwise clean.

## 5. Recovery verification

Recovery is an observation, never an inference. Before anything is called recovered, four things must be on the record:

1. The signal, named before the mitigation was applied where possible.
2. The value that counts as healthy, stated as a number with its unit and window.
3. The observed value, with its time.
4. Who observed it.

If the signal is itself down — the dashboard, the alerting pipeline, the log stream — the incident stays open and the record says which signal is unavailable. A recovery claim resting on a mitigation being applied is the failure this step exists to prevent.

## 6. Communication ledger

Every outbound message has two states and never both: `prepared` (text written, target named, nothing sent) and `observed` (a connector returned a result, with what it returned and when).

| Channel | Prepared here | Sent by |
| --- | --- | --- |
| Page to on-call | who to page, why, at which severity | `omh-apps` |
| Status page | the public sentence, the affected components, the next update time | `omh-apps` |
| Customer notice | the draft, the audience, the facts it may state | `omh-apps` |
| Internal update | the channel, the cadence, the next update time | `omh-apps` |

Every public message states the next update time, and a missed update time is itself a timeline entry. What a message may state is bounded by the timeline: no cause that has not been observed, no restoration that has not been verified, no apology that commits to remediation nobody has decided.

## 7. Handing over

An incident that outlives one shift hands over explicitly: the incoming commander reads the timeline back, states the current severity and the open mitigations, and the handover itself is a `decision` entry naming both people. An implicit handover is how two people both believe the other is commanding.

## 8. Closing

Close when the recovery verification is on the record and every temporary mitigation is either removed or carried as a named follow-up. Then hand the record to `omh-reliability-review`: the postmortem, the error-budget consequence, and the remediation tracking are its work, and the timeline is its source.
