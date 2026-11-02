# Forms and Input

Load this before writing a form, a text composer (chat box, comment field),
or a dialog. The accessibility-audit skill's FORM rules check the same ground
after the code exists; these rules put it in the first draft, where it costs
least.

## Labels and descriptions

- Every control has a visible label tied to it in markup (`<label for>`, a
  wrapping label, or `aria-labelledby`). A placeholder is an example value,
  never the label: it disappears on the first keystroke.
- Help text is linked with `aria-describedby`; the error message with
  `aria-errormessage` or `aria-describedby`. A format hint sits above the
  field, where the browser's autofill list cannot cover it.
- Required fields say so in text, and no state is carried by color alone.
- A personal-data field declares its autofill purpose (`autocomplete` such as
  `email`, `name`, `tel`, `street-address`, `one-time-code`,
  `current-password`, `new-password`) and the matching `type` / `inputmode`,
  so the right keyboard and the password manager both appear.

## When an error appears

- Validate when the user commits a value (blur) or submits, not on each
  keystroke of a value still being typed: `user@gm` is not an error yet.
  CSS `:user-invalid` has this timing built in; JavaScript validation keeps a
  per-field touched flag for the same effect.
- Once a field shows an error, re-check it on input, so the error clears the
  moment the value becomes valid.
- `aria-invalid` turns on at the same moment the visual error appears. Set
  earlier, a screen reader announces "invalid" when a user first tabs into an
  empty required field.
- Error text names the problem and the next step (copy rules:
  `taste-foundations.md`, section `Interface copy`).

## Server errors land on fields

- Client validation is a convenience; the server's answer is the authority.
  Map each field path in the error response onto its field (the backend
  skill's error envelope carries field paths:
  `omh-backend/references/service-contract.md`). A path with no matching
  field, and an error with no field, goes to one form-level summary.
- After a failed submit, move focus to the first invalid field, or to the
  summary when no field is at fault, and announce the summary once through a
  live region.
- A failed submit keeps everything the user typed. Clearing the form on an
  error is data loss.
- A conflict (409: the record changed since it was loaded) is its own state,
  not a generic error: say that someone else changed it, keep the user's
  edit, and offer reload or overwrite. Never overwrite silently.

## One submit in flight

- While a submit is pending, the control shows it ("Saving…") and a second
  submit is refused, whether it comes from a double click, Enter, or a
  shortcut. Keep the button focusable while pending (`aria-disabled` plus an
  early return) so focus does not fall back to the page.
- When the endpoint is not naturally idempotent, the request carries an
  idempotency key created once per user intent and reused on retry, so a
  retry after a timeout does not create the record twice.
- An optimistic submit follows the cancel / snapshot / apply, restore on
  error, invalidate on settle triple in the frontend-refactor skill's
  `omh-frontend-refactor/references/state-discipline.md`, section 6.

## Enter to submit, and IME composition

Korean, Japanese, and Chinese input goes through an input method editor (IME),
and Enter confirms the candidate being composed. A handler that sends on
every Enter sends half-composed text: the most common defect in chat UIs for
these languages.

- A single-line input inside a `<form>` needs no handler: the browser's own
  Enter submission already waits for composition. Do not add one.
- A multiline field with a custom Enter-to-send checks composition first:
  when the key event reports `isComposing`, the Enter belongs to the IME, so
  return without sending. Some Safari versions deliver `compositionend`
  before the confirming Enter, so the flag already reads false; also treat
  `keyCode === 229` as composing, or ignore an Enter that arrives within a few
  milliseconds of `compositionend`. In a framework that wraps events, read
  the flag from the native event.
- Shift+Enter inserts a newline. Ctrl/Cmd+Enter shortcuts do not collide
  with IME confirmation.
- A visible submit button always remains; the key is an accelerator, not the
  only path.
- Verify it by typing Korean or Japanese with a real IME and pressing Enter
  to confirm a candidate: nothing is sent until the next Enter. Reading the
  handler is not that check.

## Dialogs

- Prefer the platform `<dialog>` opened with `showModal()` (top layer, inert
  background, Escape to close) and the `popover` attribute for non-modal
  overlays over hand-built focus traps.
- On open, focus moves into the dialog: its first field, or its heading when
  it has no field. Escape closes it, and on close focus returns to the
  control that opened it.
- The page behind a modal does not scroll: `overscroll-behavior: contain` on
  the dialog, and on its `::backdrop` together with `overflow: hidden`, or
  the project's existing scroll lock.
- A dialog holding unsaved input asks before discarding it on an accidental
  close.
- A destructive confirmation names the action on its button ("Delete
  project"), never "OK".

## Check the support target

`:user-invalid`, `popover`, and the newest dialog behaviors arrived in
engines at different times. Check each against the browser-support target
named in the brief; one newer than the target ships behind feature detection
with a fallback.

## Boundary

These rules shape the prepared contract and the first draft. Whether a form
behaves is observed in a browser: a keyboard-only pass, a screen-reader
announcement, a real IME test, a double-click on submit. A rule listed here is
not evidence that it holds.

## Attribution

The validation timing, error announcement, IME-safe Enter, and dialog scroll
rules adapt ideas from the `modern-web-guidance` skill guides in
`GoogleChrome/modern-web-guidance` (Apache-2.0). No text from them is
reproduced, the wording here is OMH's own, and OMH requires neither that
package's command-line tool nor any network fetch.
