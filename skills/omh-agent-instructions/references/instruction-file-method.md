# Instruction File Method

Load this while writing or updating an agent instruction file. OMH prepares the text; the executor runs the commands and writes the file, and only inside the marked region.

## 1. Which file, where

| File | Read by | Note |
| --- | --- | --- |
| `AGENTS.md` | Codex, Hermes Agent, and most agents that follow the open format | nested files apply to their directory; the closest file wins |
| `CLAUDE.md` | Claude Code | may point at `AGENTS.md` instead of repeating it |
| `GEMINI.md` | Gemini CLI | |
| `.cursor/rules/*.mdc`, `.cursorrules` | Cursor | rules carry their own globs |
| `.github/copilot-instructions.md` | GitHub Copilot | |
| `.hermes.md`, `HERMES.md` | Hermes Agent | the nearest one between the working directory and the repository root |

When several exist, keep one source and point the others at it, so two files cannot disagree. A pointer works only for a reader that follows it, so check how each reader loads before choosing which file holds the text:

- **Hermes Agent loads one project file type per session.** It takes the first type that has a non-empty file and reads no other: `.hermes.md` or `HERMES.md`, the nearest from the working directory up to the repository root; then `AGENTS.md`; then `CLAUDE.md`, in the working directory only; then `.cursorrules` with `.cursor/rules/*.mdc`, in the working directory only. Outside a repository it looks in the working directory alone. It follows no pointer written inside the file it loaded, so a `.hermes.md` that only points elsewhere is all Hermes reads, and `CLAUDE.md` reaches Hermes only where neither of the first two types exists. In a repository Hermes works in, keep the text in `AGENTS.md`, make `CLAUDE.md` and the rest pointers, and add no `.hermes.md`.
- **Hermes Agent reads every `AGENTS.md` on that path.** Each directory from the repository root down to the working directory adds its own file, root first, and a file identical to one already read is skipped, so a nested file adds to the root file rather than replacing it.
- **An `AGENTS.override.md` replaces the `AGENTS.md` beside it** for Hermes Agent, in that one directory. It is usually untracked, so an edit to the committed `AGENTS.md` there changes nothing for a session that finds the override. The inventory lists every override, and a drift check reads the override rather than the committed file.

## 2. The marked region

```text
<!-- omh:agent-instructions:begin -->
... prepared content ...
<!-- omh:agent-instructions:end -->
```

- Replace only the text between the markers. Everything before and after is hand-written and stays byte-for-byte.
- When the markers are absent, insert them once, around the new section, and change nothing else.
- Never nest a second pair, and never move hand-written text into the region.

## 3. Sections, in order

1. **Build and test**: the exact commands, each marked `verified (exit 0, <date>)` or `unverified`, with the environment they need (`PYTHONPATH`, a service, a toolchain version file).
2. **Generated files**: for each one, its source, the command that regenerates it, and the gate that checks it. Say "never hand-edit" once, here.
3. **Gates**: which checks are byte-exact, and which fail on a count the author must re-derive.
4. **Pitfalls**: each entry names the symptom, the cause, and what it cost, so a reader can tell a scar from a preference.
5. **Conventions** the code cannot show: branch names, commit trailers, the language of the text.

**Size.** Hermes truncates a project context file past 20,000 characters by default (the cap rises with the model's context window): it keeps the first 70% and the last 20% and drops the middle, warning in the log and the chat status line and leaving a marker that lists the omitted sections. After writing, tell the owner in your reply (not in the file) whether the file is under 20,000 characters. If it is over, keep Build and test and Gates first, shorten the pitfalls, and move long reference text into a linked document.

**Overlap.** If a hand-written section outside the region already states a command or fact the region would, do not repeat it: list the overlap in `instruction_file_inventory/v1` and ask the owner whether the region links to it or the hand-written text moves in. Two copies of one command can disagree.

## 4. What never goes in

| Tempting line | Why it drifts | Write instead |
| --- | --- | --- |
| "the suite has 4,100 tests" | the next merge changes it | the command that runs the suite |
| "the router is at line 212 of `chat.py`" | any edit above it moves it | the symbol name |
| "we have 134 skills" | the catalog grows | the command or file that counts them |
| a restatement of what a function does | the code already says it, and the two diverge | nothing |
| a secret, a token, or a private hostname | the file is read by every agent and often published | the name of the variable that holds it |

The injected copy of an instruction file is a snapshot of the session start. A long session re-reads the file from the default branch before relying on it.
