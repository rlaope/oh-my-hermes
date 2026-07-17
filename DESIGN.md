# OMH static-site design contract

## Purpose

The static site explains a local orchestration product to technical operators
and Hermes users. Pages must make ownership and evidence boundaries readable
before adding decorative detail. This document is a design decision source; it
is not implementation, browser, accessibility, or visual-QA PASS evidence.

## Foundations

- Use the existing `site/styles.css` tokens: white canvas, soft neutral
  surfaces, ink text, muted support text, teal action accents, blue observed
  evidence, and warm prepared-state warning.
- Keep the existing serif display face, system sans body face, and monospace
  contract labels. Do not introduce external fonts or raw colors.
- Use the existing 4px-derived spacing rhythm, `--page` content width,
  `--radius-frame`, `--radius-control`, and low-contrast structural borders.
- Preserve the visible focus ring and the site’s short transform/color
  transitions. Static documentation must remain useful with reduced motion.

## Design-orchestration comparison

The comparison pages serve one job: show why a broad design request needs a
structured handoff instead of a generic brief.

- The baseline is intentionally labelled illustrative and generic. It uses
  weak hierarchy and unstructured content only as a contrast, never as a
  recommended OMH interface.
- The applied page uses task-first hierarchy: request → direction → lane
  ownership → executor boundary → visual evidence requirements.
- The signature element is an evidence rail that keeps prepared and observed
  states visible without claiming completion.
- Reusable comparison primitives are a contrast header, contract panels,
  ordered lane rails, and state badges. Any future reuse must retain the same
  ownership and evidence language.

## Responsive and accessibility rules

- At desktop, comparison content may use two or three columns; below 760px it
  must stack without horizontal overflow.
- Semantic landmarks, a skip link, readable text contrast, keyboard focus, and
  non-color-only state labels are required.
- Do not rely on animation to reveal content. The small rail transitions must
  be optional under `prefers-reduced-motion`.

## Review criteria

The applied sample is clearer only if a reviewer can identify the primary task,
design direction, specialist owner boundaries, executor-selection gap, and
required visual evidence faster than on the baseline. Screenshot comparison is
PR evidence only and never upgrades the prepared product contract to PASS.
