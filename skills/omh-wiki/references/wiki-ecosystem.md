# Wiki Ecosystem Candidates

Upstream `0xNyk/awesome-hermes-agent` entries whose OMH coverage names the `wiki` surface, derived from the
catalog snapshot retrieved 2026-07-27 at commit `27389ad544f9`.

Check Hermes' own skills first: the bundled `obsidian` skill (`skills/note-taking/obsidian`), and the optional
`llm-wiki` and `notion` skills (not installed by default on current Hermes main; `hermes skills install`).
The list below is a community snapshot, several entries are documentation about Hermes rather than wiki or
vault skills, and it ages: re-check an entry's repository before relying on it.

Check this list before designing a bespoke structure. Route a promising candidate to `omh-skill-scout` for
evaluation; adopting one is a separate decision with its own evidence.

## hermes-agent-docs

- Source: https://github.com/mudrii/hermes-agent-docs
- Section: Guides & Documentation | maturity: beta
- Summary: Comprehensive community documentation for Hermes Agent. Covers v0.2.0 in detail, useful supplement to the official docs for deployment patterns.
- OMH coverage: partial (adoption priority medium)
- Related surfaces: wiki, content-operator, source-finder, workspace-audit, doctor, toolbelt-readiness

## Hermes Console

- Source: https://github.com/dannyshmueli/obsidian-hermes-console
- Section: Integrations & Bridges | maturity: beta
- Summary: Obsidian integration for Hermes Agent. Runs Hermes in a tabbed terminal inside Obsidian and bridges selected-note/cursor context through a local companion plugin, with background status alerts when agent runs finish.
- OMH coverage: partial (adoption priority high)
- Related surfaces: memory-sync, wiki, workflow-learning, instinct-ledger, skill-health

## HermesWiki

- Source: https://github.com/martymcenroe/HermesWiki
- Section: Guides & Documentation | maturity: beta
- Summary: Community-maintained wiki with practical patterns and deployment advice for building autonomous agents with Hermes.
- OMH coverage: partial (adoption priority medium)
- Related surfaces: wiki, content-operator, source-finder, workspace-audit, doctor, toolbelt-readiness

## keepnotes

- Source: https://github.com/keepnotes-ai/keep
- Section: Memory Providers | maturity: beta
- Summary: Reflective memory layer. Stores and resurfaces notes at contextually relevant moments.
- OMH coverage: partial (adoption priority high)
- Related surfaces: memory-sync, wiki, workflow-learning, instinct-ledger, skill-health

## loremaster

- Source: https://github.com/loremaster-ai/loremaster
- Section: Skills & Plugins | maturity: experimental
- Summary: AI scrum-master and PM skill pack extracted from a production multi-project deployment. Sprint ceremonies with planning poker, backlog proposals with verifiable done criteria, plan-conflict detection, and a per-project wiki vault with a knowledge graph. Every external write (Jira, wiki commits) goes through per-item human approval. MIT.
- OMH coverage: partial (adoption priority high)
- Related surfaces: memory-sync, wiki, workflow-learning, instinct-ledger, skill-health

## obsidian-auto-context

- Source: https://github.com/SkillForge-Labs/obsidian-auto-context
- Section: Skills & Plugins | maturity: experimental
- Summary: Captures each session's findings, decisions, and action items into an Obsidian vault as tagged, wiki-linked Markdown with daily-note rollups. Secrets are redacted before anything touches disk. MIT.
- OMH coverage: partial (adoption priority high)
- Related surfaces: memory-sync, wiki, prompt-import-readiness, external-connector-readiness, skill-scout

## personal-api

- Source: https://github.com/beiyuii/personal-api-skill
- Section: Skills & Plugins | maturity: experimental
- Summary: Turn your Obsidian vault into an identity layer any AI agent can read in under 30 seconds
- OMH coverage: partial (adoption priority high)
- Related surfaces: memory-sync, wiki, prompt-import-readiness, external-connector-readiness, skill-scout

Static catalog parsed from upstream README. This is not plugin installation, runtime load, safety review, or endorsement evidence.
