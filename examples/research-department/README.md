# Research Department Example

This fixture shows how OMH prepares a Hermes-native research department workflow
without claiming the research has already run.

Example chat request:

```text
Use OMH research-department for: every morning check competitor news and send a Slack digest only if something changed.
```

Hermes can present the prepared lanes:

```text
Scout: collect source candidates into source_inbox.raw_findings.
Analyst: synthesize processed notes and conflicts.
Briefer: prepare a digest or report with unresolved gaps visible.
```

The artifact keeps these states separate:

```text
prepared: topic, cadence, delivery target, source boundaries, optional integrations
not observed: source retrieval, NotebookLM execution, Obsidian write, scheduler enablement, Slack delivery
```

Use the CLI backend for deterministic smoke checks:

```sh
omh ops research-department "every morning check competitor news and send a Slack digest only if something changed" --dry-run
omh ops research-department-list
omh ops research-department-show <plan-id>
```
