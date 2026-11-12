# Wiki Operating Rules

Each row is a decision that has to be made once. The personal and shared answers differ because a solo
vault and a multi-person wiki fail differently. Record the answer in the blueprint's `maintenance` and
`conventions` fields rather than leaving it implicit.

## Entry point

- Personal or small group: One index note listing live areas; search covers the rest.
- Team or organization: One README or home page that answers 'what is here and where do I start'.
- Skipped: Readers land in a flat file list, conclude nothing is here, and ask in chat instead.

## Naming

- Personal or small group: Whatever the author will recognize later; consistency matters more than the scheme.
- Team or organization: One written rule, since two people will otherwise pick two schemes for one topic.
- Skipped: The same subject accumulates three pages under three names and none of them is complete.

## Linking

- Personal or small group: Link freely; a dangling link is a to-do, not an error.
- Team or organization: Link to canonical pages only, so readers do not have to guess which copy is current.
- Skipped: Knowledge fragments into islands that only their author can navigate.

## Ownership

- Personal or small group: Implicitly the author; say so rather than pretending it is managed.
- Team or organization: A named owner per section, because shared ownership means nobody updates it.
- Skipped: Pages age with no one responsible, and readers stop trusting all of them equally.

## Update cadence

- Personal or small group: On touch: update the page when the work touches it again.
- Team or organization: A stated review interval per section, plus a last-reviewed date on the page.
- Skipped: A confidently wrong page outlives the truth and costs more than no page.

## Duplication

- Personal or small group: Merge on sight; the author is the only one holding the map.
- Team or organization: Search before writing, and merge into the canonical page rather than adding a near-copy.
- Skipped: Two pages disagree and readers cannot tell which one to believe.

## Retirement

- Personal or small group: Archive rather than delete; keep it out of the search path.
- Team or organization: Mark superseded with a pointer to the replacement, and keep the record.
- Skipped: Deleted context makes old decisions unexplainable; kept-but-unmarked context misleads.

## Access

- Personal or small group: Not a question until someone else needs to read it.
- Team or organization: Decide who can read and who can write before the first sensitive page exists.
- Skipped: Either the wiki holds secrets it should not, or the people who need it cannot open it.

Moving from personal to shared is the moment these change, and shared starts at two writers.
When a solo vault gains a second writer, revisit naming, ownership, and access before adding pages.

## When an agent is one of the readers

A person skimming a page infers its scope from layout and recovers from a moved file. An agent does
neither: it cites paths, retrieves whole pages without their neighbours, and cannot tell a stale page
from a fresh one. These are additional to the rules above, not a replacement for them.

- **Stable page identity** — Give each page a path that survives reorganization, and redirect rather than move.
  - Skipped: An agent cites a page by its location, so every earlier answer points at a file that is no longer there.
- **One topic per page** — Split a page that answers more than one question.
  - Skipped: Retrieval returns whole pages, so a page covering five topics drags four irrelevant ones into context.
- **Machine-readable header** — Put title, one-line summary, and last-reviewed date in front matter on every page.
  - Skipped: An agent cannot infer scope or freshness from visual layout the way a person skimming can.
- **Self-contained pages** — Avoid 'see above', 'as mentioned', and meaning that depends on the neighbouring page.
  - Skipped: Retrieval delivers one page without its siblings, so the missing context is silently filled in wrong.
- **Enumerable index** — Keep a listing file an agent can read, not only a visual home page.
  - Skipped: The agent cannot discover what exists and answers from whatever it happened to match.
