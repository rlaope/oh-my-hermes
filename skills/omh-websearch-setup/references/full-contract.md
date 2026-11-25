# Websearch Setup

Load this on-demand contract after the compact `websearch-setup` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants Hermes to run a web search now, not configure how web search is set up.
- The request needs a repository code change rather than a local `.env` or Hermes config edit.

## Examples

Good example:

- Prompt: make web search cheaper — I have a scraper account I want to use for reading pages, and search can stay free.
- Expected behavior: Read the `web` section and `.env` key names, guide the provider API key setup as one diff approval, then set `web.extract_backend` to that provider and `web.search_backend` to a free backend the user picks from `hermes tools` as a second, separate diff approval, and read both keys back.
- Why: The request needs the two independently-approved writes this skill exists to keep separate, aimed at keys Hermes consumes.

Bad example:

- Prompt: websearch-setup: search the web for the latest news.
- Expected behavior: Run or route to the search request directly instead of starting a setup walkthrough.
- Why: A live search request is not a configuration request.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the Hermes config `web` section (`backend`, `search_backend`, `extract_backend`, `provider_tier`, `keyless_fallback`) as non-secret metadata; an absent key is the Hermes default
- the backend names `hermes tools` lists under Web Search & Extract
- provider API key availability; value through secure entry or user-side setup only

Expected outputs:

- read-only diagnosis of which backend serves search and which serves extract, and why: its own per-capability key, a shared `web.backend` or managed-gateway selection, credential detection, the keyless free tier, or, when nothing else resolves, Hermes' default backend; on some releases any per-capability key counts as a selection, so the other capability skips detection and lands on Hermes' default backend, which verify reads rather than infers
- a diff-approved `.env` write adding the provider API key, approved on its own, or the user's own key entry in `hermes tools`
- a diff-approved `web` backend or tier change (`web.search_backend`, `web.extract_backend`, `web.provider_tier.<name>: free|paid`, `web.keyless_fallback`), approved separately from the key write
- verification checklist reading back each written `web` key from the merged `web` section and the provider key name's presence

Artifact expectations:

- setup verification note when the wrapper captures it
