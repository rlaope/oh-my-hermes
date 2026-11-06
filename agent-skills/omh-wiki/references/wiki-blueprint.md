# Wiki Blueprint

## Interview turns

Two or three questions per turn, five turns at most. Skip what the request already answered; a full inventory is not the goal, a structure someone can start today is.

1. **Audience** — who reads it, who writes it (only me / 2-5 people / a team / the whole organization), **whether an agent is one of the readers**, and which store already exists.
2. **Content** — which two or three kinds of knowledge actually repeat: decisions, procedures, research, glossary, or troubleshooting.
3. **Retrieval** — what someone will look for and when. Entry points and naming rules are decided here, not after the pages exist.
4. **Maintenance** — cadence, owner, retirement rule. No owner means `unmaintained`, which rules out models that need curation.
5. **Proposal** — one model plus one alternative, each with rationale and breaking conditions, shown as a skeleton to approve before anything is written.

Keep existing `USER.md`/`MEMORY.md` cleanup out of the wiki; route new durable project facts to `omh-memory-new`, and connector access or workspace permissions to `omh-external-connector-readiness`.

## `wiki_blueprint/v1` fields

- `audience_scale` / `shared_audience` — personal, small_group, team, organization, or unknown. Shared means more than one writer, which starts at two.
- `agent_readers` / `agent_reader_rules` — whether a machine reads the wiki, and the requirements that appear when it does.
- `destination` — the classified store, from the destination classifier rather than a vendor assumption.
- `organization_model` / `alternative_model` — name, rationale, fits_when, breaks_when, skeleton, audience note.
- `skeleton` / `entry_points` — sections or namespaces, plus the page a reader lands on first.
- `conventions` — naming, linking, and entry-point rules for this audience.
- `maintenance` — owner, cadence, duplication, retirement, and access rules; `unmaintained` when nobody owns it.
- `seed_page_cap` — at most ten pages worth creating today, each with a one-line purpose.
- `ecosystem_candidates` — upstream skills worth evaluating first, metadata only.
- `missing_facts` — what the interview still needs; never guessed.

A blueprint is a prepared design artifact. It is not evidence that a store was created, written to, migrated, or that any page exists.
