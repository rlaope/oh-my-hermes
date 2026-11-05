# TUI Vim Word Objects

## ADDED Requirements

### Requirement: WO-1 Inner word ranges
The Composer SHALL define `iw` using its NORMAL `_atoms()` sequence: a blank atom is exactly a member of WORD_BREAKS (space or tab), a word atom is neither such a blank nor NEWLINE, and the initial selection is the maximal same-class run containing the caret. Punctuation and NBSP are word constituents. Paste-chip atoms containing internal spaces SHALL remain indivisible nonblank atoms.

**Planning context**: Status: proposed planning contract; every target scenario below is UNPROVEN. Baseline findings are not feature acceptance. `iw`/`aw` intentionally use WORD-style punctuation treatment, not full Vim lowercase-word classes. WORD_BREAKS is space/tab only; unlike existing `.isspace()` motions, NBSP is not an object delimiter. Newline is a separate hard boundary. Apply requires Human approval and the checks in acceptance-plan.md.

#### Scenario: Inner word from interior
```yaml
scenario_id: wo-inner
when: 'NORMAL Vim unmasked Composer has text `alpha beta gamma`, caret 8, and receives `diw`'
then: 'text becomes `alpha  gamma`, caret 6, NORMAL, no pending state; register text is `beta`, linewise false'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-inner-range
```
- **WHEN** NORMAL Vim unmasked Composer has text `alpha beta gamma`, caret 8, and receives `diw`
- **THEN** text becomes `alpha  gamma`, caret 6, NORMAL, no pending state; register text is `beta`, linewise false.

#### Scenario: Whitespace is an inner object
```yaml
scenario_id: wo-whitespace
when: 'text is `one  \\ttwo`, caret 4 and the command is `diw`'
then: 'the whole maximal space/tab run is removed, leaving `onetwo`; punctuation in `foo.bar-baz` remains one word; NBSP inside `one\\u00a0two` is nonbreak'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-whitespace-range
```
- **WHEN** text is `one  \ttwo`, caret 4 and the command is `diw`
- **THEN** the whole maximal space/tab run is removed, leaving `onetwo`; punctuation in `foo.bar-baz` remains one word; NBSP inside `one\u00a0two` is nonbreak.

### Requirement: WO-2 Around word ranges
The Composer SHALL define `aw` on a word as that whole word plus the entire immediately trailing space/tab run when present, otherwise the immediately leading space/tab run at logical-line end. A sole word selects itself. When starting on blanks, `aw` SHALL select the entire current blank run and the next word, without adding trailing blanks; if there is no following word on that logical line, it selects only that blank run. Newlines are never padding.

#### Scenario: Around prefers trailing blanks
```yaml
scenario_id: wo-around
when: 'text is `one  two\\t  three`, caret on `two`, and `daw` is received'
then: '`two\\t  ` is removed (all trailing space/tab atoms), leaving `one  three`; `daw` on final `two` in `one  two` removes `  two`, leaving `one`'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-around-range
```
- **WHEN** text is `one  two\t  three`, caret on `two`, and `daw` is received
- **THEN** `two\t  ` is removed (all trailing space/tab atoms), leaving `one  three`; `daw` on final `two` in `one  two` removes `  two`, leaving `one`.

#### Scenario: Around starting on blanks
```yaml
scenario_id: wo-around-blank
when: 'text is `one  two  three`, caret 3, and `daw` is received'
then: 'the current blank run plus next word (`  two`) is removed, leaving `one  three`; terminal blanks with no following word select only that run'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-around-blank-range
```
- **WHEN** text is `one  two  three`, caret 3, and `daw` is received
- **THEN** the current blank run plus next word (`  two`) is removed, leaving `one  three`; terminal blanks with no following word select only that run.

### Requirement: WO-3 Object counts
The Composer SHALL reuse `_take_count()` (pre-operator count multiplied by post-operator count, default 1, cap 9999).

#### Scenario: Counts multiply with defined units
```yaml
scenario_id: wo-count
when: 'text is `a b c d e`, caret 0 and `2d2iw` is received'
then: 'four alternating maximal runs (`a b `) are removed, leaving `c d e`; `2daw` removes `a b `; oversized counts cap at 9999 and stop at the logical line end'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-count-range
```
- **WHEN** text is `a b c d e`, caret 0 and `2d2iw` is received
- **THEN** four alternating maximal runs (`a b `) are removed, leaving `c d e`; `2daw` removes `a b `; oversized counts cap at 9999 and stop at the logical line end.

##### Normative continuation of WO-3
`iw` SHALL count alternating maximal word/blank runs from the current run inclusive. `aw` SHALL count words: starting on a word, include up to N consecutive words and intervening blanks, then trailing padding or leading fallback for the aggregate span; starting on blanks, include the initial blank run plus up to N following words and intervening blanks, but no trailing padding. All counts SHALL stop at logical-line end, select available runs/words without error, and never loop past the bound. Counts are accepted before the operator or between operator and descriptor, not after i/a.

### Requirement: WO-4 Operator object pending lifecycle
The Composer SHALL recognize i/a as object descriptors only with d/c/y already pending.

#### Scenario: Descriptor holds operator and counts
```yaml
scenario_id: wo-pending
when: 'the keys `2`, `d`, `3`, `i` arrive in NORMAL'
then: 'text/caret/register are unchanged, pending is true with operator/counts retained; final `w` completes the six-run selection and clears all pending state'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-pending-state
```
- **WHEN** the keys `2`, `d`, `3`, `i` arrive in NORMAL
- **THEN** text/caret/register are unchanged, pending is true with operator/counts retained; final `w` completes the six-run selection and clears all pending state.

#### Scenario: Invalid followers and cancellation do not leak
```yaml
scenario_id: wo-cancel
when: 'an object descriptor is pending and receives Escape, unsupported `x`, or digit `2`'
then: 'the command is discarded without editing, moving, changing register, or entering INSERT; the invalid follower is consumed and a subsequent `w` is an ordinary motion; set_vim and Paste clear object state through existing reset paths'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-cancel-state
```
- **WHEN** an object descriptor is pending and receives Escape, unsupported `x`, or digit `2`
- **THEN** the command is discarded without editing, moving, changing register, or entering INSERT; the invalid follower is consumed and a subsequent `w` is an ordinary motion; set_vim and Paste clear object state through existing reset paths.

##### Normative continuation of WO-4
The descriptor SHALL retain the operator and both counts until the next key; only w completes the object. An unsupported follower, including digits, SHALL cancel and consume the pending sequence without fallthrough. Escape, set_vim, Paste, shared undo/redo, and existing non-character cancellation paths SHALL clear object state through `_drop_pending`; the existing handling of the cancelling event itself SHALL remain unchanged. Pending/leader precedence SHALL include the descriptor without creating a second state machine.

### Requirement: WO-5 Shared operator effects
Completed nonempty d/c/y objects SHALL use existing characterwise yank, replace, change, caret-clamp, register/put and handle undo/redo semantics. d SHALL remain NORMAL, c SHALL enter INSERT at span start with replacement typing joined to its change step, and y SHALL preserve text while moving caret to span start. Yank SHALL make no text undo step. The existing register behavior across undo/redo SHALL be preserved, not extended into a new register history.

#### Scenario: Delete change and yank reuse effects
```yaml
scenario_id: wo-operators
when: 'each of `diw`, `ciw`, `yiw`, `daw`, `caw`, `yaw` completes a nonempty span'
then: 'd deletes and stays NORMAL; c deletes and enters INSERT at start; y preserves text and stays NORMAL with caret at span start; each captures the exact selected span in the characterwise register'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-operator-effects
```
- **WHEN** each of `diw`, `ciw`, `yiw`, `daw`, `caw`, `yaw` completes a nonempty span
- **THEN** d deletes and stays NORMAL; c deletes and enters INSERT at start; y preserves text and stays NORMAL with caret at span start; each captures the exact selected span in the characterwise register.

#### Scenario: Undo and register metadata remain existing behavior
```yaml
scenario_id: wo-undo
when: 'a nonempty object delete, change with replacement typing, or yank is followed by undo/redo or put'
then: 'delete is one undo step; change deletion plus replacement typing is one step; yank creates no text undo step; undo/redo restore text/caret/chips/images under existing rules without promising to rewind the register; put uses the captured text/metadata'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-undo-register
```
- **WHEN** a nonempty object delete, change with replacement typing, or yank is followed by undo/redo or put
- **THEN** delete is one undo step; change deletion plus replacement typing is one step; yank creates no text undo step; undo/redo restore text/caret/chips/images under existing rules without promising to rewind the register; put uses the captured text/metadata.

### Requirement: WO-6 Line and atomic boundary safety
Object spans SHALL be half-open atom-index ranges within the current logical line, converted through `_atoms()` bounds. NEWLINE SHALL be an exclusive hard boundary, including an empty line. Clusters, chips and image tokens SHALL remain whole; chip/image metadata SHALL be captured and restored through existing primitives. An empty selection SHALL leave d/y and their register unchanged; c SHALL enter INSERT consistently with existing empty change behavior, without fabricating a text undo step.

#### Scenario: Empty lines newline boundaries and atoms
```yaml
scenario_id: wo-edges
when: 'object commands address empty text, a blank line, a multi-line draft, a grapheme, a chip, or an image token'
then: 'empty d/y are no-ops preserving register; empty c enters INSERT without an undo entry until text is typed; neither object includes NEWLINE or crosses a logical line; clusters/chips/image atoms are never split and register metadata remains intact'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-empty-line-atomic
```
- **WHEN** object commands address empty text, a blank line, a multi-line draft, a grapheme, a chip, or an image token
- **THEN** empty d/y are no-ops preserving register; empty c enters INSERT without an undo entry until text is typed; neither object includes NEWLINE or crosses a logical line; clusters/chips/image atoms are never split and register metadata remains intact.

### Requirement: WO-7 Compatibility and bounded surface
The change SHALL be confined to unmasked Vim NORMAL operator-object handling. Non-Vim, INSERT and masked typing, standalone i/a, existing motions and repeated operators, g/r prefixes, Alt+b/f and application leader/shortcut behavior SHALL remain unchanged. Existing `.isspace()` word-motion helpers SHALL not be changed to match the narrower new object predicate. No new dependencies, key constants, persistent configuration or search commands SHALL be introduced.

#### Scenario: Non-Vim and existing normal commands remain intact
```yaml
scenario_id: wo-isolation
when: 'literal `diw`/`daw` is typed in Vim INSERT, non-Vim, or masked input, and existing motions/operators/leader cases run'
then: 'literal text inserts through existing input paths; standalone i/a remain INSERT commands; dw/cw/yw/dd/cc/yy, g/r prefixes, Alt+b/f, pending Escape handling and leader/application routing preserve their existing behavior'
evidence:
  required: true
  coverage: assertions
  assertions:
    - assertion_id: wo-isolation-regressions
```
- **WHEN** literal `diw`/`daw` is typed in Vim INSERT, non-Vim, or masked input, and existing motions/operators/leader cases run
- **THEN** literal text inserts through existing input paths; standalone i/a remain INSERT commands; dw/cw/yw/dd/cc/yy, g/r prefixes, Alt+b/f, pending Escape handling and leader/application routing preserve their existing behavior.
