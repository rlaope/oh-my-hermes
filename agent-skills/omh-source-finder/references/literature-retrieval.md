# Literature Retrieval

Load this reference when the candidates are scholarly papers: a related-work list, "what should I read on X", or the papers behind a method. It narrows `search-method.md` for papers. It never raises the caps in `search-method.md`, and every query and read still goes through the host's own tools.

## Pick the corpus by topic

Query only the corpora the topic needs. Calling every corpus by habit spends the budget for nothing.

| Topic | Corpus | Host route |
| --- | --- | --- |
| ML, CS, math, physics preprints | arXiv | Hermes' bundled `arxiv` skill, or `export.arxiv.org/api/query?search_query=...` |
| Journals, conferences, citation counts, any field | OpenAlex | `api.openalex.org/works?search=...` (no key needed; the shared free budget is small) |
| Biology preprints | bioRxiv, through OpenAlex | `api.openalex.org/works?search=...&filter=primary_location.source.id:S4306402567` |
| Biomedical and clinical journals | PubMed | `eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=...&retmode=json`, then `esummary` for titles and DOIs |

When the topic sits between fields, query two corpora in the same round. bioRxiv is a subset of OpenAlex, and PubMed journals mostly overlap OpenAlex, so overlap between those results is expected and is not a second source.

## Write the query

- Build keyword queries only from the user's words and words already seen in results. Never guess what an acronym stands for.
- For a semantic or graph search, write one short question in the user's own terms, without padding.
- When a keyword query mixes ordinary words with acronyms (2 to 10 characters, starting with a letter, at least two capitals, such as `RLVR` or `KV-cache`), run one extra query of only those acronyms in the same round. It counts as part of the first round.
- Fix one publication window and one ordering (relevance, recency or citations) for the request, and keep them for every round. Do not widen the window halfway through.

## Rate difficulty, then spend at most that many follow-ups

Rate the request 1 to 10 before the first round.

| Difficulty | Follow-up rounds |
| --- | --- |
| 1-3 | 0 |
| 4-7 | 1 (the cap in `search-method.md`) |
| 8-10 | 1, or 2 only under a depth budget the user declared in `research_progress/v1` |

A follow-up round targets one named gap: a missing method, benchmark, organization, venue, title phrase or subtopic. Calls about the same gap count as one round. A round that only rephrases an earlier query is not allowed. Stop as soon as coverage is enough. The table is a ceiling, not a target.

## Dedupe and rank

1. Merge results across corpora. Match on the exact id first, then a DOI or arXiv id in the metadata, then the exact normalized title.
2. For an arXiv paper that also appears elsewhere, keep the arXiv record, because it has full text.
3. Never compare arXiv-side votes or popularity with OpenAlex citation counts as numbers. They measure different things. Rank across corpora by topical fit.
4. Return 5 to 15 candidates, strongest first. Fewer strong papers beat padding.
5. Every candidate must come from a result the host actually returned in this request. Never add a paper id from memory. If none survives, report the gap instead of filling it.

Record each kept paper as a `paper` candidate in `link_observed` state with `hermes_tool` provenance, the corpus named in `evidence_note`, and the query URL as `evidence_uri`. A listing is not a read: abstract, full text and claims stay unclaimed until a read is observed.

## Read after ranking, not before

- A "find papers" or "what should I read" request ends at the ranked list.
- When the request needs claims, methods or a comparison, finish ranking first, then hand to `ulw-research` the 3 to 5 papers that carry the answer, or to `omh-paper-learning` for one supplied paper, to read and cite.

## Attribution

The corpus routing, difficulty-scaled follow-ups and cross-corpus dedupe adapt practices of the `alphaXiv/OpenResearch` project (MIT). No upstream text is reproduced. OMH binds them to its own search caps, candidate states and host-owned tools.
