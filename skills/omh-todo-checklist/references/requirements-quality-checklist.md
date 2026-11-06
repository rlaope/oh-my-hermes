# Requirements-Quality Checklist

A plan checklist tracks work. This is a different artifact that happens to share
the shape: a checklist whose items interrogate the **requirements**, not the
implementation. Load it when asked to review whether a spec, issue, or plan is
fit to be built from, before anyone starts building.

Think of the requirement text as a program written in English. This checklist is
its test suite. Every item asks whether the requirements are written well enough
to build and accept against - never whether the code works. The code has its own
tests and `omh-verification-gate` owns them.

## The line an item may not cross

An item that can only be answered by running the software is in the wrong
artifact.

- Wrong: does the endpoint return the right status on a duplicate submission?
- Right: does the spec say what happens on a duplicate submission?
- Wrong: does the list load quickly?
- Right: is "quickly" given a threshold and a measurement point?

The test is mechanical. If answering the item requires the built system, move it
to a verification checklist. If it can be answered by reading the requirement
text alone, it belongs here.

## Item shape

```
- [ ] CHK### - <question about the requirements> [<Quality>, <source ref>]
```

- `CHK###` is stable and assigned once. Renumbering breaks every reference to a
  prior review.
- The text is a question, ending in a question mark. A declarative item hides
  whether it is asking or asserting.
- `<Quality>` is exactly one of the six below.
- `<source ref>` points at what the item is about: a requirement id, a section,
  or `Gap` when the item exists precisely because nothing in the document covers
  it.

## The six qualities

Every item is tagged with one. The tag is what makes the finished checklist
readable as a diagnosis rather than a list.

| Quality | The question behind it |
| --- | --- |
| Completeness | is the case covered at all? |
| Clarity | can it be read only one way? |
| Consistency | is the same rule stated the same way everywhere it appears? |
| Measurability | can a person or a command decide whether it is met? |
| Coverage | are the non-obvious paths present - errors, empties, limits, permissions? |
| Gap | is something absent that a builder will have to invent? |

## Ownership: the generator does not tick its own boxes

The party that writes the items does not decide they pass. This is the rule the
artifact rests on, and it has one reason: an author checking their own item
re-reads their own intent, not the document.

- Generating or appending items leaves every one of them `[ ]`.
- `[x]` means a reviewer judged the requirement-quality criterion satisfied. It
  never means the work is done.
- A model may help evaluate an item when a reviewer asks it to, item by item,
  with the reason stated. It may not sweep the list.
- A generated checklist that arrives with boxes already ticked is void. Reset it
  and say why, rather than trusting marks whose owner is unknown.

This is the same boundary `prepared_not_observed` draws everywhere else in OMH:
the checklist is prepared, and a reviewer's marks are the only thing on it that
is observed.

## Building one

1. Name the domain the checklist covers and say what it excludes. A checklist
   over everything gets skimmed.
2. Read the requirement text and write one item per distinct doubt, tagged.
3. Sort by quality, then by source reference, so a reader sees all the
   measurability problems together.
4. Stop when the next item would restate the previous one at a different
   altitude. Length is not coverage, and a long list trains reviewers to tick
   without reading.

## Reading a completed one

Unchecked items are the output. Report them grouped by quality: several
`Measurability` misses mean the spec cannot be accepted against, several `Gap`
entries mean the builder is being asked to design. A fully ticked checklist says
the requirements are fit to build from. It says nothing at all about the build.
