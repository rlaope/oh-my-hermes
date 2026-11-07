# Accessibility Rule IDs and the Fix Partition

The finding vocabulary for an accessibility audit. Prose findings are not
comparable across reruns and cannot be handed to an executor in parts; a rule
ID, a severity, a WCAG criterion, and a fix class can.

## How a finding is written

Read the target surface completely, collect every finding, then report. One
row per finding:

`rule ID | severity | location | WCAG criterion | fix class | the fix`

Severity is `critical` (the surface is unusable for someone), `major` (a task
is degraded or a control is mislabelled to assistive technology), or `minor`
(comprehension or convention). Severity ranks findings; it is not the audit
verdict, which stays PASS/HOLD/BLOCK on observed evidence.

## The fix partition, which is the load-bearing half

A fix is `auto` **only when the correct output is derivable from the markup
itself**. It is `manual` whenever producing it requires knowing what the
content *means*.

- Derivable: an image inside a control that already carries a text label is
  decorative, so its text alternative is the empty one. The structure decided
  it, not a reader.
- Not derivable: what a meaningful image actually depicts, what a link
  actually goes to, what a field actually asks for. No amount of markup
  yields those.

Marking a meaning-dependent fix `auto` is a defect in the audit, not a
convenience for the fixer: it produces confident, wrong alternative text,
which reads worse to assistive technology than the missing attribute did.
When a rule's fix is partly structural and partly semantic, the row is split
into its `auto` half and its `manual` half rather than rounded to either.

## Rules

### Images

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| IMG-1 | Image with no text alternative | critical | 1.1.1 | `auto` when decorative by context, else `manual` |
| IMG-2 | Decorative image not marked decorative to assistive technology | minor | 1.1.1 | `auto` |

### Links and buttons

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| LNK-1 | Link with no accessible name | critical | 2.4.4, 4.1.2 | `manual` |
| LNK-2 | Link text that does not describe its destination | minor | 2.4.4 | `manual` |
| LNK-3 | Link opening a new context with no warning (advisory: 3.2.5 is AAA) | minor | 3.2.5 | `manual` |
| BTN-1 | Button with no accessible name | critical | 4.1.2 | `manual` |

### Forms

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| FORM-1 | Control with no programmatically associated label | critical | 1.3.1, 3.3.2, 4.1.2 | `manual` |
| FORM-2 | Label associated with a control that does not exist | major | 1.3.1 | `manual` |
| FORM-3 | Personal-data field with no autofill purpose declared | minor | 1.3.5 | `manual` |

### Roles and states

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| ARIA-1 | Role that is not a valid role name | major | 4.1.2 | `manual` |
| ARIA-2 | Focusable element hidden from assistive technology | critical | 2.4.3, 4.1.2 | split: whether it should be reachable at all (a closed menu or dialog should not) is `manual`; once decided, removing the hiding or removing it from the tab order (`tabindex=-1` or `inert`) is `auto` |
| ARIA-3 | Decorative vector graphic exposed to assistive technology | major | 1.1.1 | `auto` when decorative by context, else `manual` |

### Keyboard and focus

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| KEY-1 | Positive tab index overriding document order | major | 2.4.3 | `auto` (neutralize), and the resulting order is re-walked |
| KEY-2 | Pointer handler on a non-interactive element with no keyboard path | major | 2.1.1 | split: role and focusability `auto`, the key handler `manual` |
| KEY-3 | No visible focus indicator (2.4.7), or the focused component entirely hidden behind author content such as a sticky header (2.4.11); partial overlap is advisory (2.4.12, AAA) | major | 2.4.7, 2.4.11 | `manual` |
| KEY-4 | Keyboard trap: focus enters a region and cannot leave by keyboard | critical | 2.1.2 | `manual` |
| RFL-1 | Content lost, or needing two-direction scrolling, at 320 CSS px width (256 CSS px height for horizontally scrolling content such as vertical text) / 400% zoom; not a finding for content that requires two-dimensional layout (data tables, maps, diagrams, video, games, toolbars) | major | 1.4.10 | `manual` |
| TGT-1 | Pointer target under 24x24 CSS px with none of the 2.5.8 exceptions (spacing, equivalent control, inline in a sentence, user-agent-controlled, essential) | major | 2.5.8 | `manual` |
| STAT-1 | Dynamic status or error not announced (no live region or focus move) | major | 4.1.3 | `manual` |

### Structure

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| SEM-1 | Page language not declared | critical | 3.1.1 | split: adding the attribute is `auto` only when the page language is already supplied; choosing the value is `manual` |
| SEM-2 | Heading level skipped | major | 1.3.1 | `manual` |
| SEM-3 | No main landmark | major | 1.3.1, 2.4.1 | `manual` |
| SEM-4 | Embedded frame with no title | major | 2.4.1, 4.1.2 | `manual` |
| SEM-5 | Layout table exposed as a data table | minor | 1.3.1 | `auto` |

### Color and contrast

| ID | Finding | Severity | WCAG | Fix class |
| --- | --- | --- | --- | --- |
| COL-1 | Color as the only carrier of meaning | minor | 1.4.1 | `manual` |
| COL-2 | Color declared inline, contrast unverifiable from source | minor | 1.4.3 | `manual` (measure, then judge against 4.5:1 text / 3:1 large text) |
| COL-3 | UI component boundary, state or meaningful graphic under 3:1 (not for inactive components or a control whose appearance the user agent sets) | major | 1.4.11 | `manual` |

A finding the table does not cover takes the next number of the nearest
prefix and goes into the rerun list, so reruns stay comparable. A target size
of 44x44 is AAA (2.5.5) or platform guidance: report it as advisory, never as an
AA failure.

Detection criteria are written against structure, not one framework's syntax:
a rule holds for a template language when the same structural condition can be
seen in it, and a syntax that hides the condition (a fully dynamic binding, a
name computed at runtime) is reported as unverifiable-from-source rather than
as a pass.

## Rerun and handoff

Rule IDs are what make a second audit comparable to the first: a finding is
resolved when its ID no longer matches at that location, carried when it
still does, and new otherwise. The `auto` rows are the only ones that can be
handed to an executor as a batch; the `manual` rows go back with the question
each one needs answered.

## Boundary

A rule ID classifies a finding and a fix class describes a fix - neither is
evidence the fix was applied. The audit verdict still requires observed
keyboard and assistive-technology evidence after the change, and a scan that
produced these findings is not a keyboard walk.
