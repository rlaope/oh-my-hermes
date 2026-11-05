# TUI Vim Inline Character Search

## ADDED Requirements

### Requirement: CS-1 Directional atom search
In Vim NORMAL and unmasked mode, the Composer SHALL accept f/F/t/T followed by one valid target.

**Planning context**: Status: proposed planning contract; all CS target behavior is UNPROVEN. Findings establish only baseline/seams and stock Vim reference. Apply and exact semantics need Human approval. Indices in ASCII examples are zero-based except the stock Vim reference in findings.

#### Scenario: Directional landing
```yaml
{
  "scenario_id": "cs-directions",
  "when": "fresh text `xabcQabcx`, caret 4, receives fx, Fx, tx or Tx",
  "then": "carets respectively 8, 0, 7, 1; text/register/undo unchanged, NORMAL, pending false",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-directions-assert"
      }
    ]
  }
}
```
- **WHEN** fresh text `xabcQabcx`, caret 4, receives fx, Fx, tx or Tx
- **THEN** carets respectively 8, 0, 7, 1; text/register/undo unchanged, NORMAL, pending false.

#### Scenario: Atomic matching
```yaml
{
  "scenario_id": "cs-atoms",
  "when": "targets are space, digit, punctuation, an NFC-equivalent grapheme or a substring found only inside a chip/image label",
  "then": "ordinary complete atoms match at boundaries, NFC targets match whole graphemes, and chip/image internals do not match or split; traversed metadata is intact",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-atoms-assert"
      }
    ]
  }
}
```
- **WHEN** targets are space, digit, punctuation, an NFC-equivalent grapheme or a substring found only inside a chip/image label
- **THEN** ordinary complete atoms match at boundaries, NFC targets match whole graphemes, and chip/image internals do not match or split; traversed metadata is intact.

##### Normative continuation of CS-1
Let i be the starting _atoms index, [s,e) its _line_of interval, and m the requested matching atom strictly beyond i in the requested direction. f/F land at m; t lands at m-1; T lands at m+1. Search SHALL stop before NEWLINE or buffer ends, never wrap and never use display rows. Match means complete NFC grapheme equality with an ordinary text atom; a chip or image token is never a candidate and target text inside a chip/image label is not searched. Space, punctuation and digits are literal targets. An input target SHALL be NFC-normalized and contain exactly one printable grapheme, excluding NEWLINE, tab/control text and reserved image tokens; a multi-codepoint grapheme is permitted.

### Requirement: CS-2 Pending target and cancellation
After f/F/t/T (standalone or after d/c/y and counts), the Composer SHALL hold the prefix/operator/counts pending without moving/editing.

#### Scenario: Literal target completion
```yaml
{
  "scenario_id": "cs-pending",
  "when": "fresh `a2b2c` at caret 0 receives 2f and then target 2, or a target looks like d, i, a, g, r, f, ;, comma or space",
  "then": "2f stays pending without edits; final 2 lands at caret 3; all target-looking commands are consumed as literals and cannot start operators, counts, INSERT or leader",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-pending-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `a2b2c` at caret 0 receives 2f and then target 2, or a target looks like d, i, a, g, r, f, ;, comma or space
- **THEN** 2f stays pending without edits; final 2 lands at caret 3; all target-looking commands are consumed as literals and cannot start operators, counts, INSERT or leader.

#### Scenario: Cancel pending search
```yaml
{
  "scenario_id": "cs-cancel",
  "when": "f/F/t/T and d/c/y variants with both counts pending receive Escape or another invalid target event",
  "then": "pending drops with no search motion/edit/INSERT, register/memory preserved and next command fresh; Paste and Ctrl undo/redo keep only their existing event effects",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-cancel-assert"
      }
    ]
  }
}
```
- **WHEN** f/F/t/T and d/c/y variants with both counts pending receive Escape or another invalid target event
- **THEN** pending drops with no search motion/edit/INSERT, register/memory preserved and next command fresh; Paste and Ctrl undo/redo keep only their existing event effects.

##### Normative continuation of CS-2
The next unmodified CHAR target SHALL complete search before parsing it as a digit, operator, i/a/g/r, repeat or leader. Escape SHALL consume cancellation, clear all transient state and preserve caret/text/mode/register/search memory; the next command starts fresh. Non-target keys (including BACKSPACE, DELETE, Enter, arrows, modified CHAR and invalid CHAR payloads) SHALL cancel and be consumed without dispatch. Paste SHALL instead retain the existing paste behavior after dropping pending state. Shared Ctrl undo/redo SHALL retain their existing undo/redo behavior after dropping pending state. Completion, miss and cancellation SHALL leave no transient counts/operator/prefix/leader.

### Requirement: CS-3 Counts and atomic miss
Search SHALL consume min(pre-count times post-operator-count,9999), with each missing count equal to 1, and select the nth occurrence strictly in the requested direction.

#### Scenario: Occurrence and product counts
```yaml
{
  "scenario_id": "cs-count",
  "when": "fresh `abcbdbebfbgb` at caret 0 receives 2fb, d2fb, or 2d3fb; oversized counts are also exercised",
  "then": "2fb lands at 3; d2fb removes `abcb`; 2d3fb removes all six b occurrences through the final b characterwise; counts cap at 9999 and insufficient matches do nothing",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-count-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `abcbdbebfbgb` at caret 0 receives 2fb, d2fb, or 2d3fb; oversized counts are also exercised
- **THEN** 2fb lands at 3; d2fb removes `abcb`; 2d3fb removes all six b occurrences through the final b characterwise; counts cap at 9999 and insufficient matches do nothing.

#### Scenario: No match and hard line boundary
```yaml
{
  "scenario_id": "cs-miss",
  "when": "fresh `abc` plus NEWLINE plus `b` at caret 0 receives fz, 2fb, dfz, cfz, yfz, or search on an empty line/buffer",
  "then": "no movement/edit/INSERT/register or undo/redo change; later-line b cannot satisfy 2fb; pending false, prior successful search preserved",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-miss-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `abc` plus NEWLINE plus `b` at caret 0 receives fz, 2fb, dfz, cfz, yfz, or search on an empty line/buffer
- **THEN** no movement/edit/INSERT/register or undo/redo change; later-line b cannot satisfy 2fb; pending false, prior successful search preserved.

##### Normative continuation of CS-3
Thus 2fb seeks the second b, not two atoms. Too few matches, invalid target, an empty logical line/buffer, or ;/, without remembered search SHALL be a clean no-op: caret/text/mode/register/chip/image metadata, undo/redo and remembered successful search unchanged; pending drops. In particular an unsuccessful c-search SHALL NOT enter INSERT. A partially satisfied count SHALL NOT partially move, edit or replace remembered search.

### Requirement: CS-4 Characterwise operator endpoints
A successful search combined with d/c/y SHALL act on these half-open atom ranges, converted through _atoms bounds: forward f [i,m+1), forward t [i,m), backward F [m,i), backward T [m+1,i).

#### Scenario: All operator endpoint directions
```yaml
{
  "scenario_id": "cs-spans",
  "when": "fresh `xabcQabcx` at caret 4 receives each d/c/y crossed with fx, tx, Fx and Tx",
  "then": "selected texts respectively `Qabcx`, `Qabc`, `xabc`, `abc`; d results respectively `xabc`, `xabcx`, `Qabcx`, `xQabcx`; c/y follow the stated mode/caret/register rules",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-spans-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `xabcQabcx` at caret 4 receives each d/c/y crossed with fx, tx, Fx and Tx
- **THEN** selected texts respectively `Qabcx`, `Qabc`, `xabc`, `abc`; d results respectively `xabc`, `xabcx`, `Qabcx`, `xQabcx`; c/y follow the stated mode/caret/register rules.

#### Scenario: Successful adjacent till versus miss
```yaml
{
  "scenario_id": "cs-adjacent",
  "when": "fresh `xQ` at caret 1 receives dTx, cTx or yTx; fresh `Qx` at caret 0 receives dtx; cfz is checked separately",
  "then": "adjacent Tx is a successful empty span: d/y preserve text/caret/register; c enters INSERT with no new text undo entry; forward dtx removes Q only; cfz stays NORMAL",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-adjacent-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `xQ` at caret 1 receives dTx, cTx or yTx; fresh `Qx` at caret 0 receives dtx; cfz is checked separately
- **THEN** adjacent Tx is a successful empty span: d/y preserve text/caret/register; c enters INSERT with no new text undo entry; forward dtx removes Q only; cfz stays NORMAL.

#### Scenario: Shared operator metadata and undo
```yaml
{
  "scenario_id": "cs-effects",
  "when": "successful d/c/y spans cross whole chip and image atoms; change is followed by replacement typing, Escape, undo and redo, and captured text is put",
  "then": "d is one undo step; c deletion+typing is one step; y/motions add no text undo; full metadata round-trips under existing put/undo rules, with no promise to undo register/search memory",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-effects-assert"
      }
    ]
  }
}
```
- **WHEN** successful d/c/y spans cross whole chip and image atoms; change is followed by replacement typing, Escape, undo and redo, and captured text is put
- **THEN** d is one undo step; c deletion+typing is one step; y/motions add no text undo; full metadata round-trips under existing put/undo rules, with no promise to undo register/search memory.

##### Normative continuation of CS-4
Forward spans include the original caret; backward spans exclude it. The matching target is included by f/F and excluded by t/T. No range includes NEWLINE. This asymmetry intentionally follows Vim directional operator endpoints. d deletes, stays NORMAL and clamps at the span start. c deletes and enters INSERT at span start using existing change-typing undo grouping. y leaves text unchanged, remains NORMAL and moves to span start. Nonempty spans capture exact text plus chip/image metadata in the characterwise register. A successful empty T span (adjacent backward target) SHALL leave d/y and register unchanged; c SHALL enter INSERT at the unchanged caret without a text undo step until typing. A miss SHALL remain distinct from this successful empty span.

### Requirement: CS-5 Remembered search and repeat direction
Only a successful completed explicit f/F/t/T SHALL replace remembered search (kind,target), including a successful zero-distance till.

#### Scenario: Forward reverse and operator repeats
```yaml
{
  "scenario_id": "cs-repeat",
  "when": "fresh `xabcxabcxabcx` at caret 0 receives fx; then comma; or, from the fx; state, d-comma; fresh till cases are also exercised",
  "then": "fx; reaches 8, comma returns to 4, next ; reaches 8; d-comma at 8 removes indices [4,8) and preserves original f/x memory; f/F/t/T direction pairs use the same rule",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-repeat-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `xabcxabcxabcx` at caret 0 receives fx; then comma; or, from the fx; state, d-comma; fresh till cases are also exercised
- **THEN** fx; reaches 8, comma returns to 4, next ; reaches 8; d-comma at 8 removes indices [4,8) and preserves original f/x memory; f/F/t/T direction pairs use the same rule.

#### Scenario: Memory lifecycle and no-memory repeats
```yaml
{
  "scenario_id": "cs-memory",
  "when": "successful search is followed by failure/cancel, mode entry, undo/redo, independent Composer, set_vim, submit or clear; ;/, are pressed with no memory",
  "then": "failure/cancel and ordinary resets retain the last success, count not retained; independent/cleared instances no-op and drop pending counts/operators; submit/set_vim/clear erase memory",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-memory-assert"
      }
    ]
  }
}
```
- **WHEN** successful search is followed by failure/cancel, mode entry, undo/redo, independent Composer, set_vim, submit or clear; ;/, are pressed with no memory
- **THEN** failure/cancel and ordinary resets retain the last success, count not retained; independent/cleared instances no-op and drop pending counts/operators; submit/set_vim/clear erase memory.

##### Normative continuation of CS-5
Count is not remembered. Failure, invalid input and cancellation SHALL preserve previous memory. ; SHALL repeat remembered kind/direction; comma SHALL use its opposite (f<->F, t<->T) for that command without rewriting memory, so a subsequent ; returns to the original direction. Repeats SHALL work standalone and with d/c/y, take counts through the same multiplication/cap, and operate on the current line/current text rather than cached offsets. Memory SHALL survive ordinary pending resets, Escape, INSERT entry, unrelated motion/edit, history loads and undo/redo, but be cleared by set_vim (either value), successful submit and explicit composer clear. It SHALL be per Composer instance, nonpersistent and excluded from undo snapshots.

### Requirement: CS-6 Till-repeat progression and counted repeats
For each repeated t/T step only, if its nearest directional match is the immediately adjacent target whose till landing would equal the current caret, the resolver SHALL skip that match and seek the next one.

#### Scenario: Progress without getting stuck
```yaml
{
  "scenario_id": "cs-till-repeat",
  "when": "fresh `aXbXcX` at caret 0 receives tX followed by ;, ;, comma; mirrored T case and counted/operator repeat are exercised",
  "then": "explicit tX stays 0; ; reaches 2, next ; reaches 4, comma reaches 2; 2; from 0 reaches 4; backward T mirrors this; operator repeat uses final match and one combined span",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-till-repeat-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `aXbXcX` at caret 0 receives tX followed by ;, ;, comma; mirrored T case and counted/operator repeat are exercised
- **THEN** explicit tX stays 0; ; reaches 2, next ; reaches 4, comma reaches 2; 2; from 0 reaches 4; backward T mirrors this; operator repeat uses final match and one combined span.

#### Scenario: Counted repeat failure is atomic
```yaml
{
  "scenario_id": "cs-repeat-miss",
  "when": "fresh `aXbXcX` at 0 has remembered t/X and receives 3;, c3;, or a repeat whose only match is across NEWLINE",
  "then": "all remain at original caret with text/register/mode/undo unchanged, memory retained and pending false; no partial two-step progress or INSERT",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-repeat-miss-assert"
      }
    ]
  }
}
```
- **WHEN** fresh `aXbXcX` at 0 has remembered t/X and receives 3;, c3;, or a repeat whose only match is across NEWLINE
- **THEN** all remain at original caret with text/register/mode/undo unchanged, memory retained and pending false; no partial two-step progress or INSERT.

##### Normative continuation of CS-6
Explicit t/T SHALL NOT skip it: adjacent targets are successful zero-distance motions. A repeat count SHALL mean that many progressing repeat steps, calculated speculatively; intermediate landings are not applied until every step succeeds. For example on aXbXcX from index 0, tX stays 0, ; reaches 2, next ; reaches 4, and 2; from 0 reaches 4. If any counted repeat step fails, the complete command SHALL no-op rather than leave a partial landing/span. An operator repeat SHALL form one span from its original caret to the final selected match using the effective direction/type in CS-4. This deliberately defines a small deterministic contract rather than all stock Vim counted-till subtleties.

### Requirement: CS-7 Compatibility and ordered integration
The new dispatch SHALL operate only in Vim NORMAL unmasked mode.

#### Scenario: Preserve existing routing
```yaml
{
  "scenario_id": "cs-isolation",
  "when": "literal f/F/t/T/;/, text is entered in INSERT, non-Vim or masked mode, and the original leader/Alt/motion/operator/object regression corpus runs",
  "then": "literal input and existing commands preserve baseline behavior; pending space target is not leader; search does not steal word-object, replace or g-prefix followers",
  "evidence": {
    "required": true,
    "coverage": "assertions",
    "assertions": [
      {
        "assertion_id": "cs-isolation-assert"
      }
    ]
  }
}
```
- **WHEN** literal f/F/t/T/;/, text is entered in INSERT, non-Vim or masked mode, and the original leader/Alt/motion/operator/object regression corpus runs
- **THEN** literal input and existing commands preserve baseline behavior; pending space target is not leader; search does not steal word-object, replace or g-prefix followers.

##### Normative continuation of CS-7
Existing non-Vim, masked and INSERT input, standalone i/a, r/g, word motions, accepted iw/aw object semantics, leader followers, legacy/modern Alt word moves, submit and undo/redo SHALL retain their established behavior except the explicitly consumed invalid pending-search events of CS-2. Existing key constants, dependencies and configuration SHALL remain unchanged. Integration SHALL preserve word-object prefix completion precedence and common operator effects.
