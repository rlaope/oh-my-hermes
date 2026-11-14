# Wiki Organization Patterns

Pick one model, name why it fits, and say what would break it. A model presented without its breaking
conditions is a guess wearing a name. Pair with `references/wiki-operations.md` for the rules that keep
the chosen model alive.

## PARA

Split by actionability: projects, areas, resources, archive.

Fits when:
- Most pages exist to support work that is currently moving.
- The same person both writes and acts on the notes.
- Finished work should stop competing with live work for attention.

Breaks when:
- Reference knowledge outlives the project that produced it and gets archived with it.
- Several people disagree about whether something is still a live area.

Skeleton: `projects/`, `areas/`, `resources/`, `archive/`

Audience: Strong for personal and small-group vaults; needs an explicit owner per area before a team can trust it.

## Zettelkasten / evergreen notes

One idea per page, densely linked, titles written as claims.

Fits when:
- The value is in connections between ideas, not in a filing location.
- The same concepts keep resurfacing across unrelated work.
- The author rereads and revises pages rather than appending to them.

Breaks when:
- Pages are procedural steps that must be followed in order.
- Readers need one canonical answer instead of a network to traverse.
- Nobody has time to revise pages, so links rot into a dead graph.

Skeleton: `notes/`, `index or entry note`, `link conventions`

Audience: Best solo. In a team it needs a curator, or two people write two competing notes on one idea.

## Diátaxis

Split by reader intent: tutorial, how-to, reference, explanation.

Fits when:
- Readers arrive with different needs against the same subject.
- New people must be onboarded without a guide sitting next to them.
- Mixing conceptual background into task steps is already hurting.

Breaks when:
- The corpus is small enough that four quadrants leave most of them empty.
- The subject is decisions and history rather than a product someone uses.

Skeleton: `tutorials/`, `how-to/`, `reference/`, `explanation/`

Audience: Made for shared and public documentation; overkill for a personal vault.

## Map of Content (MOC)

Hand-curated entry pages that route to everything below them.

Fits when:
- Search alone does not tell readers what exists.
- The structure has to change without moving or renaming files.
- A few high-traffic topics deserve a curated front door.

Breaks when:
- Nobody maintains the maps, so they silently drift from the pages.
- The page count is small enough that a flat list already works.

Skeleton: `maps/`, `topic pages`, `one root entry map`

Audience: Works at both scales; in a team, name an owner per map or the maps go stale first.

## Docs-as-code

Markdown in the repository, changed by pull request, reviewed like code.

Fits when:
- Knowledge describes a codebase and goes stale when the code changes.
- Review and history matter as much as the content.
- Contributors already live in the repository.

Breaks when:
- Contributors do not use git, so the review step blocks writing entirely.
- The knowledge is not about a single repository.

Skeleton: `docs/`, `docs/adr/`, `docs/runbooks/`

Audience: Team-first. For personal use the review step is friction with no reviewer.

## Decision log (ADR)

Append-only records of what was decided, why, and what was rejected.

Fits when:
- The same arguments keep getting relitigated.
- New people ask why something is the way it is.
- Context behind a choice matters longer than the choice itself.

Breaks when:
- Used as the only structure, so day-to-day reference has nowhere to live.
- Records are edited in place, which destroys the history that justified the log.

Skeleton: `decisions/`, `one file per decision`, `status field`

Audience: Valuable at every scale, and the single highest-return page type for a team.

Models combine. A decision log inside a docs-as-code repository, or maps of content over a
Zettelkasten, are normal. Combining more than two is how a wiki becomes unmaintainable.
