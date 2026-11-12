# Editorial Layout

Layout is the part of a page that is decided before colour and type: the
skeleton, the whitespace, the order of attention, where one section ends, and
where images sit. This reference covers those choices only. Palette and type
stay with `references/design-system-contract.md`; the direction itself is named
in `references/taste-foundations.md`.

## Hierarchy before boxes

Build the order of attention from whitespace and type-size contrast first.
Group related items with space and thin rules, and reach for a filled or
bordered box only when the item is a separate object the reader acts on. A page
where every group sits in a box has no group that leads, because the boxes
carry the same weight.

## The seven axes

Choose one value per axis and write one line of reason, taken from the subject:
what the page shows, how many images it has and at what ratio, and how much
text it carries. The values below are a vocabulary to start from, not a closed
list; a value that fits the subject and is not listed is allowed.

1. **Skeleton / grid** - single column, two-column split, left margin with a
   pinned label, asymmetric twelve-column, stacked full-bleed bands, offset
   columns.
2. **First screen** - oversized type alone, type beside one large image,
   full-bleed image with a text panel, a product capture under one line, an
   index of what the page contains.
3. **Section boundary** - thin rule, a change of ground, empty space only, a
   label in the margin, a full-width image, a hard edge between bands.
4. **Image placement** - full-bleed, inset with a caption, split against the
   text, overlapping a type block, a strip of small frames, one image per
   section pinned while text moves.
5. **Signature moment** - one oversized figure, a pull quote, a single
   product capture at true size, a timeline, a before and after pair, a large
   closing line.
6. **Density** - sparse with one idea per screen, a steady reading column,
   mixed with one dense block per section, dense and tabular throughout.
7. **Screen corners and navigation** - what sits at the edges of the screen:
   one top bar, an identity label in one corner with the main action in the
   opposite one, a floating bar, a side rail, a text-only index, navigation
   folded into the first screen. Corner radius is not this axis; it belongs
   to the contract's Shapes section.

State the seven values and their reasons in the plan before building. A value
with no reason from the subject is the unmade decision this list exists to
expose.

## Choosing against the familiar

Taking the most familiar value on every axis yields an average page, because
nothing on it came from the subject. As a judgement rule: pick at least two
axes from the less familiar candidates, and write what in the subject earns
each. This is a review prompt, not a quota; a stated reason that the familiar
value fits keeps it.

## Differ from the previous output

A user who receives pages that all share one composition has received one page
several times. Before choosing, read the record of the last few pages built for
this user, and change at least three of the seven axes from the most recent
one. When the user asks for "like last time", follow the record instead.

The record is one line per page with these fields: date, project, and the seven
axis values. Keep it in a file under the project; when there is no project,
keep it under the user's state directory. This reference names the fields and
leaves the path to the project's own conventions. Append the line when the page
is accepted, so a rejected draft does not count as history.

## One frame, varied interiors

Inside one site, pages share the frame: skeleton, navigation and what sits in
the screen corners, section boundary, and theme. They do not share the inner
composition, because a shared frame already makes them one site. Within a page,
consecutive sections of the same kind change composition. Candidates: a
timeline, a mirrored split, one large figure with one line, three small cases,
a step-by-step story. Three sections in a row built from the same card row read
as one section repeated.

## One mode per page

A light page stays light from the first screen to the footer, and a dark page
stays dark. A single section flipped to the other mode reads as a different
page pasted in, unless the flip marks the one signature moment and the plan
says so.

## Static first

Build the page with no motion, hover effect, scroll effect, or shader. Capture
it at the widths that matter and review the still. Add motion only after the
still layout holds on its own, and then sparingly, one effect for one reason.
Motion added early hides weak hierarchy behind movement, and a reviewer cannot
tell which of the two is carrying the page.

## Images

1. Use what exists first: images already in the project and real captures of
   the product. Generate an image only when nothing exists for the slot.
2. Lay text over the image in HTML. Never bake text into the image file: baked
   text cannot be translated, corrected, or read by a screen reader.
3. Compose the image with the text area left empty, so the overlay does not
   fight the subject.
4. Generate at the aspect ratio of the slot. Cropping a generated image to fit
   moves the subject out of the composition that was approved.
5. Make the dark variant an edit of the approved light image, changing lighting
   and background only, not a new generation. The composition then stays put
   when the theme flips.
6. Open each image and look at it before placing it. A file that exists is not
   evidence that it shows the right thing.

## Phone width

Multi-column, margin, and split skeletons fold to one column. A label pinned in
a margin returns to the flow, above the content it names. After the fold, run
the mobile density gate in `references/mobile-density-gate.md`; the fold alone
does not show the page holds at phone width.

## Record the choice

Put one comment at the top of the page's stylesheet with the chosen axis
values, in the same order as the record line. The next person to edit the page,
and the next build for this user, can read the decision without reverse
engineering it from the CSS.

## Boundary

This reference shapes the prepared layout and the plan for it. It does not
substitute for observed rendered evidence: the visual-QA owner judges what
shipped, at each width, from a capture.
