# Session Forensics Rules

Load this before you open a Hermes session store, a JSON Lines session record, or a delegated child's transcript to explain what an agent run did. `omh quality-evidence agent-debug` already follows several of these rules for the rows it reads: it opens `state.db` with `mode=ro`, caps each cell with `--max-row-bytes`, and cites message ids or record lines. `omh quality-evidence session-usage` reports per-surface totals the same read-only way. These rules govern every read you make past those commands, and the report you write from either.

## 1. Intake before any query

Write the question down before the first read. It has five parts:

| Part | Example of a filled part |
| --- | --- |
| Session | an id, `latest`, or a named profile's store |
| Turn range | the turns around the complaint, or "unknown" |
| Expected | what the user thought the run would do |
| Observed | what they saw instead |
| Observable | the one thing to measure: a repeated tool call, a stall, token spend, a wrong result, a skill that never loaded |

For the agent-debug command, map the observable to the closest accepted `--observable <kind>`: `looping`, `repeated_work`, `goal_drift`, `context_loss`, `tool_stall`, `unexpected_cost`, or `unspecified` when none fits, which is where a wrong result or a skill that never loaded usually lands; `omh quality-evidence agent-debug --help` lists the current set. "It was slow" or "why did it do that" names a grievance and leaves the question open: ask for the missing part, one part per message. A request that already names one event, one measurement, or one turn is a complete question; answer it first and ask about the rest afterward. When the user cannot answer now, end the turn with the open parts as questions. A question you filled in on the user's behalf does not count as their answer, so no query runs on it.

## 2. Read-only, every source

- Open SQLite stores through a read-only URI, for example `sqlite3 'file:<hermes_home>/state.db?mode=ro'`. The primary home and each profile under `profiles/<name>/` keep separate stores; count rows that match the session id in each before reading, and read the one that holds it. The command reads a profile's store when the global flag comes before the subcommand: `omh --hermes-home <hermes_home>/profiles/<name> quality-evidence agent-debug …`.
- A session record, a log, or a transcript file is opened for reading only. Never edit, rename, move, truncate, or remove one, and never write a scratch file next to it; working copies go to a scratch location outside the Hermes home.
- Asking for a diagnosis of their own session lets you read it. It does not let you change it or reset the agent that produced it. Replaying or re-running the session needs the user's own go-ahead: when the quality bar calls for a reproduced failure, propose the reproduction to the user and wait for their answer, because the diagnosis request alone does not authorize it.

## 3. Bound the length of every read

A single row or line can hold megabytes: a tool result with a whole file, an encoded image, a serialized context. An unbounded read of one such row fills the context that the analysis needs.

- In SQL, select `length(content)` first, then the text through `substr(content, 1, <cap>)`; never select a whole `content` or `tool_calls` column across a session.
- For a JSON Lines record, read through a per-line byte cap: the agent-debug command's `--session-record` mode with `--max-row-bytes`, or a line filter that cuts each line at a fixed width.
- A row over the cap is reported as unread, by reference, and nothing is inferred from it. A count taken over a capped or row-limited read is labelled partial.

## 4. Who wrote each row

Only text the human typed is the user's words. Several things land in user-role or adjacent rows and were written by software:

- hook output and injected system reminders,
- plugin or OMH context blocks added before a turn,
- compaction summaries, marked `_compressed_summary`,
- tool results, which hold what the tool returned (host guard refusals and OMH-appended text included), and are neither a user instruction nor the model's own claim.

In a delegated child's transcript, every user-role turn is the parent agent's brief; the human never typed there. Trace an instruction found in a child back to the parent session before attributing it to the child or to the user. Every quotation in the report names its speaker: user, assistant, tool name, hook, summary, or parent agent.

## 5. Numbers come from this session or stay out

- Each count, duration, token figure, or cost in the report comes from a query or command run over this session, and the report shows that query or command beside the figure. A figure from memory, from a public price list, or from what is typical is written as "not computed" instead.
- Count tool calls by distinct `tool_call_id`: a compaction re-persists rows under new ids, so a plain row count over-counts.
- Take durations from row timestamps. A flag such as compacted or active describes the store as it is now, not the moment a call ran.
- Report cost only from the run's own recorded price or charge; with none recorded, report tokens and say cost is not computed.
- The source in the checkout today may not be the code that ran; confirm the revision before explaining behaviour from source.

## 6. Sharing waits for the user

- An export package is `omh quality-evidence agent-debug-export`: without `--confirm-export` it prints the package and writes nothing, and it is written only after the user has reviewed that package. Build one only when the user asks for it.
- Issue text, a comment, or any message to a third party is shown to the user verbatim and sent only after they approve that exact text. Agreement with the diagnosis is not approval to post it.
- Session content carries paths, credentials, and other people's words. State that the export's leak scan can miss something and that the user reviews every file before passing it on.

## 7. What a finding needs

A finding cites a session id plus message ids, or `record:line`; one without a citation is dropped, not softened. The cited rows go into the competing-hypotheses step of the quality bar as evidence for or against, and causation still needs the revert-verify step there.
