# Pitch

- **Problem**: normal-mode `diw` currently consumes the operator and then moves with `w`; it does not remove the word under the caret.
- **Appetite**: one planning-only additive slice; later implementation stays within Composer and focused regression tests, subject to Human approval.
- **Solution boundary**: define `iw` and `aw` for existing delete/change/yank operators, with exact ranges and cancellation, while keeping existing editing paths intact.
- **Rabbit holes / no-gos**: no character search, punctuation-aware word classes, parser rewrite, new dependencies, or leader/shortcut redesign.
- **Success / stop signal**: a strictly valid package with explicit UNPROVEN target assertions and unchecked work; stop or reshape if preserving existing motions and leader precedence requires wider changes.
