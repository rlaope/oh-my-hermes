# Forms and Input

Load this before writing a form, a text composer (chat box, comment field),
or a dialog. The `omh-accessibility-audit` skill's FORM rules check the same ground
after the code exists; these rules put it in the first draft, where it costs
least.

## Labels and descriptions

- Every control has a visible label tied to it in markup (`<label for>`, a
  wrapping label, or `aria-labelledby`). A placeholder is an example value,
  never the label: it disappears on the first keystroke.
- Help text and the error message are linked with `aria-describedby`, which
  every screen reader reads. Add `aria-errormessage` only on top of
  `aria-invalid="true"`, and only when the screen readers the product targets
  are known to honor it. A format hint sits above the field, where the
  browser's autofill list cannot cover it.
- Required fields say so in text, and no state is carried by color alone.
- A personal-data field declares its autofill purpose (`autocomplete` such as
  `email`, `name`, `tel`, `street-address`, `one-time-code`,
  `current-password`, `new-password`) and the matching `type` / `inputmode`,
  so the right keyboard and the password manager both appear.

## When an error appears

- Validate when the user commits a value (blur) or submits, not on each
  keystroke of a value still being typed: a postcode with three of its five
  digits entered is unfinished, not wrong. CSS `:user-invalid` has this
  timing built in; JavaScript validation keeps a per-field touched flag for
  the same effect.
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
- After a failed submit, use one announcement channel, not two. Either move
  focus to the first invalid field and put only a short count ("2 fields
  need attention") into a live region that was already in the page before
  the error, or, when no field is at fault, move focus to the summary itself
  (`tabindex="-1"`, not a live region). Focusing an element and announcing
  the same content reads it twice.
- A failed submit keeps everything the user typed. Clearing the form on an
  error is data loss.
- A conflict (409: the record changed since it was loaded) is its own state,
  not a generic error: say that someone else changed it, keep the user's
  edit, and offer reload or overwrite. Never overwrite silently.

## One submit in flight

- The guard lives in the form's `submit` handler, not on the button's click:
  Enter in a field submits the form without going through the button, even
  an `aria-disabled` one. While a submit is pending, that handler returns
  early, so a double click, Enter, and a shortcut are all refused.
- The submit control shows the pending state ("Saving…") and stays
  focusable (`aria-disabled`, not `disabled`), so focus does not drop to the
  page.
- When the endpoint is not naturally idempotent, the request carries an
  idempotency key created once per user intent and reused on retry, so a
  retry after a timeout does not create the record twice.
- An optimistic submit follows the cancel / snapshot / apply, restore on
  error, invalidate on settle triple in the `omh-frontend-refactor` skill's
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
  return without sending. Some Safari versions hand the confirming Enter to
  script after `compositionend`, when the flag already reads false, so the
  recommended check inside the Enter branch is
  `event.isComposing || event.keyCode === 229`. In a framework that wraps
  events, read both from the native event.
- Only a codebase that refuses `keyCode` uses the timing fallback, and it
  has to be exact: record `event.timeStamp` of the last `compositionend`,
  and skip an Enter whose own `event.timeStamp` is within about 50 ms of it
  in absolute value (Safari can stamp the keydown earlier than the
  `compositionend`). Compare the two events' timestamps; a clock read inside
  the handler (`Date.now()`, `performance.now()`) drifts whenever the main
  thread is busy.
- Shift+Enter inserts a newline. Run the composition check before any
  Enter branch, modified or not (Ctrl+Enter, Cmd+Enter included): it costs
  nothing, and not every IME is known to leave modified Enter alone.
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
- A dialog holding unsaved input asks before discarding it on an accidental
  close. Under the HTML close-watcher rules (shipped in Chromium; check
  other engines), a modal's `cancel` can be prevented only once per user
  activation, so a second Escape closes it anyway: ask on the first Escape,
  or open it with `closedby="none"`, give it an explicit close control that
  runs the check, and handle Escape yourself (keydown on the dialog) so it
  runs the same check; `closedby="none"` turns close requests off entirely,
  and keyboard users would otherwise lose Escape.
- Keeping the page behind a modal still is partly an enhancement.
  `overscroll-behavior: contain` on the dialog stops scroll chaining when the
  dialog's own content overflows. Stopping scroll over the backdrop, or
  inside a dialog whose content does not overflow, relies on
  `overscroll-behavior` applying to a non-scrolling container (`overflow:
  hidden` plus `overscroll-behavior: contain` on `::backdrop`). That works
  in Chrome and Edge 144+ and Firefox 150+, not in Safari, and cannot be
  feature-detected: `@supports` and `CSS.supports()` answer true everywhere.
  Ship it as a progressive enhancement and say which browsers get it; when
  the support target needs a hard lock in every browser, use the project's
  scroll lock.
- A destructive confirmation names the action on its button ("Delete
  project"), never "OK".

## Check the support target

`:user-invalid`, `popover`, `closedby`, and the newest dialog behaviors
arrived in engines at different times. Check each against the
browser-support target named in the brief. A feature newer than the target
(by default, anything only Baseline Newly available) ships behind feature
detection with a fallback, or the target changes on purpose. A behavior that
cannot be detected (the backdrop scroll above) cannot take that path: it
ships only as an enhancement whose absence the page tolerates, or a
different technique covers the target.

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
