# Negotiation Preparation

This is the output mode where the objective is a redline rather than an
assessment: proposed language, fallbacks, and a concession order, prepared for
the person who will negotiate.

The boundary from the rest of this workflow carries through unchanged. This is
preparation material, never legal advice. A proposed clause says "here is
language that matches the playbook position, and here is what it gives up"; it
never says whether to accept a term, whether a clause is enforceable, or what
the law requires. The authority-citation and counsel-hold rules apply to every
row.

## Requires a playbook

Preparation is against the organization's OWN positions. Without a playbook -
standard terms, approved deviations, and what needs escalation - a proposal is
an invented position, and inventing a position is the failure this whole
workflow exists to prevent. If none is supplied, ask for it, or say that rows
are being prepared against the counterparty's draft alone and carry no approved
position behind them.

## The row

One row per contested clause:

| Field | Content |
| --- | --- |
| `clause` | the counterparty's language, by its own reference |
| `playbook_position` | the standard position, cited to the playbook clause |
| `gap` | what the draft does that the position does not allow |
| `proposed` | the replacement language |
| `fallback` | the next acceptable position if the proposal is refused |
| `walk_away` | the point past which escalation is required, and to whom |
| `counsel_hold` | open or closed, from the hold register |

`fallback` and `walk_away` are not optional. A redline with a proposal and
nothing behind it puts the negotiator in front of a counterparty with one
position and no room, and the first refusal becomes an escalation that could
have been planned.

**An open counsel hold blocks the row.** A clause with an unresolved
enforceability, privilege, uncapped-liability, or regulatory-deadline trigger
gets a counsel question, not a proposal. Proposing language over an open hold is
how preparation turns into advice.

## Concession order across rows

Rank the rows by what the organization actually loses, not by how contested
they are. Then state which are linked - a concession on liability that assumes a
cap elsewhere is one position, and trading it away separately loses both halves.
Record what each concession buys: an ordering with no exchange is a list of
things to give away.

Three rows that usually rank higher than they read: an indemnity whose cap is
set elsewhere in the document, a termination-for-convenience clause with an
asymmetric notice period, and an audit right with no scope or frequency limit.

## What the negotiator gets

The rows, the concession order with its linkages, the counsel questions that
are still open, and an explicit statement of what was not reviewed - clauses
outside the supplied instruments, exhibits that were not provided, and any
version uncertainty. A preparation pack that does not say what it did not see
reads as complete.

## Boundary

Prepared negotiation material is not legal advice, counsel sign-off, an
accepted position, an executed amendment, or a communication to the
counterparty. Every authority-dependent statement in a row traces to supplied
authority with an exact locator and status, exactly as in the issue matrix, and
an unresolved hold blocks a final determination here as it does everywhere else
in this workflow.
