# Parallel Tools

Load this on-demand contract after the compact `parallel-tools` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants a general Hermes update unrelated to parallel-tool capability.
- No version or capability question has been asked yet.
- The request needs a repository code change rather than a local version check.

## Examples

Good example:

- Prompt: update hermes for parallel tools — can you check if I'm on a current enough version?
- Expected behavior: Report the installed version and each MCP server's `supports_parallel_tool_calls` value, say that built-in read-only tools already run concurrently, and offer the per-server flag as one diff only for a server whose calls cannot interfere with one another.
- Why: Whether tools run in parallel turns on each MCP server's flag, not on the version, so the version is read and reported and the flag is what is offered.

Bad example:

- Prompt: parallel-tools: update your memory with what we discussed.
- Expected behavior: Route to a memory workflow instead of a parallel-tool capability check.
- Why: Memory update is unrelated to parallel-tool capability or Hermes version.

## Full Input, Output, and Artifact Expectations

Required inputs:

- installed Hermes version
- current parallel-tool capability status

Expected outputs:

- read-only diagnosis of the installed version and each MCP server's `supports_parallel_tool_calls` value (absent is false)
- one diff-approved `mcp_servers.<name>.supports_parallel_tool_calls: true` per named MCP server; an update command only when the user asks to update
- a capability status report naming which parallel-tool features are active

Artifact expectations:

- capability status note when the wrapper captures it
