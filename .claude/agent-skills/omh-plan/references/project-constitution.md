# Project Constitution

A plan is checked against the request and against the codebase. This adds the
third thing it must be checked against: the project's own non-negotiable rules,
written down once at a fixed path so a plan cannot quietly argue past them. Load
it when planning inside a repository that has such a document, or when the
absence of one is why the same argument keeps being had.

## The fixed path

The constitution lives at one declared path, and the plan names that path. A
principle the planner recalls from a previous session is not a principle; it is
a memory, and it loses every argument to a confident paragraph.

Where a repository already carries its non-negotiables in its contributor
documents, that is the constitution and the path is those files. Do not create a
second home for rules that already have one - two documents of principles
disagree within a quarter, and then neither is authoritative.

## Principle shape

Each principle has a short name, the rule in normative language, and its reason.

- **MUST** is non-negotiable. A plan conflicting with a MUST is wrong, and the
  plan changes.
- **SHOULD** is a default with a stated cost to departing from it. A plan may
  depart, in writing, naming the cost it accepts.
- Nothing else. A principle written with "consider" or "prefer where possible"
  cannot be conflicted with, so it cannot be checked, so it is documentation
  rather than governance.

The reason matters as much as the rule. A principle with no recorded reason gets
reinterpreted the first time it is expensive, because nobody can tell whether
the current situation is the one it was written for.

## How a conflict resolves

This is the whole mechanism and it has one direction.

**A plan that conflicts with a MUST principle is a top-severity finding, and it
is resolved by changing the plan.** Never by reinterpreting the principle to
admit the plan, never by noting the tension and proceeding, never by scoping the
principle down to exclude this case.

If the principle is genuinely wrong, that is a separate change: amend the
constitution first, in its own commit, with its own review, and then re-plan
against the amended text. The two must not happen in one motion. A principle
amended inside the change it was blocking has been argued around, whatever the
diff says.

The direction is what gives the document force. A principle that can be
reinterpreted under pressure is advice, and advice does not need a fixed path.

## Amendment

- Amendments are versioned. A removal or redefinition is a major change, a new
  principle is a minor one, and a wording fix is a patch. State which.
- An amendment names the principles added, changed, or removed, and what they
  were before.
- Where a principle's wording changes, say whether existing plans and existing
  code were conforming under the old text. A silent tightening turns the whole
  repository non-conforming with nobody told.

## Checking a plan against it

Before a plan is accepted, walk the principles and record the check. For each
MUST, the plan either does not touch it, satisfies it, or conflicts with it -
and a conflict stops acceptance. For each SHOULD the plan departs from, the plan
carries the written cost.

Record the result as part of the plan, not as a separate note. The check is
cheap, it is the only reason the document has force, and a plan that does not
show it was performed has not been.
