"""Contract for the reference-file mechanisms registered below.

The first seven are the rows of issue #1714's table, each one skill that
declared a discipline in its body and shipped no procedure for it; `loop`'s
design review (issue #2049) joined later under the same contract. The
capability is the reference file, and the body pointer is the only thing that
makes it reachable -- a reference nothing points at is a file in the pack, not
a capability.

Everything here re-derives from the producers (`builtin_skill_reference_templates()`
and `builtin_definitions()`), never from the generated `skills/` tree, so
dropping a template from the producer fails these tests even while the stale
generated file still sits on disk.

The structural-token assertions are the part that has to earn its place. They
do not check that a reference is well written; they check that the specific
mechanism its issue named is present, by the named artifact it is built from:
the id scheme, the three coverage states, the manifest section names, the
ownership rule. A reference rewritten into an essay that keeps the heading and
drops the ids fails here, which is the whole point -- the failure mode for this
kind of change is prose that reads like a procedure and names nothing.
"""

from __future__ import annotations

import re
import unittest

from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import workflow_skill_from_definition
from omh.skills.validation import STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING


# skill -> (reference path, the pointer substring its body must carry).
#
# The pointer substring is the reference's filename rather than a sentence, so
# rewording a pointer stays free while deleting one fails. What must not move
# is that some line of the always-loaded body names the file.
MECHANISM_POINTERS: dict[str, tuple[str, str]] = {
    "verification-gate": (
        "references/requirement-coverage-map.md",
        "references/requirement-coverage-map.md",
    ),
    "deep-interview": (
        "references/ambiguity-taxonomy.md",
        "references/ambiguity-taxonomy.md",
    ),
    "ultrawork": (
        "references/file-ownership-manifest.md",
        "references/file-ownership-manifest.md",
    ),
    "code-review": (
        "references/review-lenses.md",
        "references/review-lenses.md",
    ),
    "todo-checklist": (
        "references/requirements-quality-checklist.md",
        "references/requirements-quality-checklist.md",
    ),
    "ai-slop-cleaner": (
        "references/prose-lexicon.md",
        "references/prose-lexicon.md",
    ),
    "plan": (
        "references/project-constitution.md",
        "references/project-constitution.md",
    ),
    "loop": (
        "references/loop-design-review.md",
        "references/loop-design-review.md",
    ),
}

# The named artifacts each mechanism is built from. A reference that keeps its
# heading and loses these has lost the mechanism.
MECHANISM_TOKENS: dict[str, tuple[str, ...]] = {
    "verification-gate": (
        "FR-###",           # the stable functional-requirement id scheme
        "SC-###",           # the stable success-criterion id scheme
        "Evidence",         # the third column, where a task claim becomes checkable
        "Coverage",         # the gap pass
        "Critical",         # the top severity level
        "fifty",            # the finding cap
        "overflow",         # what happens past the cap
        "read-only",        # the boundary that keeps prepared_not_observed honest
    ),
    "deep-interview": (
        "Clear",            # the three per-category coverage states
        "Partial",
        "Missing",
        "five questions asked",  # the session cap
        "write",            # the write-back target, the thing OMH lacked
    ),
    "ultrawork": (
        "streams:",         # manifest section names
        "files:",
        "shared:",
        "conflict_risk:",
        "Split the file",   # the first rung of the resolution ladder
        "never an option",  # the rung that does not exist
    ),
    "code-review": (
        "Regression gap",   # the three verification-gap shapes
        "Missing-adoption gap",
        "Broken-verification gap",
        "Adversarial",      # the other four lenses
        "Edge case",
        "Structure",
        "Prose",
    ),
    "todo-checklist": (
        "CHK###",           # the item id scheme
        "Completeness",     # the six quality tags
        "Clarity",
        "Consistency",
        "Measurability",
        "Coverage",
        "Gap",
        "does not tick its own boxes",  # the ownership rule
    ),
    "ai-slop-cleaner": (
        "Tier 1A",          # the tier split that separates evidence from style
        "Tier 1B",
        "Tier 2",
        "Tier 3",
        "P0",               # the pattern severities
        "P1",
        "P2",
        "profile",          # the per-context register
    ),
    "plan": (
        "MUST",             # the normative split
        "SHOULD",
        "changing the plan",  # the conflict direction, the whole mechanism
        "Amendment",
    ),
    "loop": (
        "loopability_assessment/v1",      # the existing classifier this review starts after
        "measured-loop-discipline.md",    # the scored case, named instead of restated
        "fence",                          # the paths the loop may not edit, beside the finish line
        "git diff --name-only",           # how the fence is checked at judging time
        "Is Not the Builder",             # the judge separation
        "self-modifying",                 # loops that change their own rules
        "approved_auto_safe",             # the memory-capture rule this one is kept apart from
        "Self-grading",                   # pre-launch failure-check items
        "Unfenced check",
        "Questions left for mid-run",
    ),
}

# A reference body is cached across sessions, so anything that ages inside one
# silently goes stale. Dates and live counts belong in the issue or the ledger.
_DATE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")
_VOLATILE_COUNT = re.compile(
    r"\b\d{2,}\s+(skills?|references?|cases?|entries|rows|triggers?)\b", re.IGNORECASE
)


def _references_by_key() -> dict[tuple[str, str], str]:
    return {
        (template.skill_name, template.relative_path): template.content
        for template in builtin_skill_reference_templates()
    }


def _bodies_by_name() -> dict[str, str]:
    bodies = {}
    for definition in builtin_definitions():
        try:
            bodies[definition.name] = workflow_skill_from_definition(
                definition, definition.name
            ).content
        except (ValueError, KeyError):
            continue
    return bodies


class ReferenceMechanismTests(unittest.TestCase):
    def test_every_named_skill_has_its_reference_in_the_producer(self) -> None:
        references = _references_by_key()
        for skill, (path, _) in MECHANISM_POINTERS.items():
            with self.subTest(skill=skill):
                self.assertIn(
                    (skill, path),
                    references,
                    f"{skill} lost {path} from builtin_skill_reference_templates()",
                )

    def test_every_body_points_at_its_reference(self) -> None:
        """The pointer is what makes the reference reachable.

        A reference in the pack that no body names costs install bytes and is
        never opened, which is indistinguishable from not shipping it.
        """
        bodies = _bodies_by_name()
        for skill, (_, pointer) in MECHANISM_POINTERS.items():
            with self.subTest(skill=skill):
                self.assertIn(skill, bodies, f"{skill} is not an installable body")
                self.assertIn(
                    pointer,
                    bodies[skill],
                    f"{skill} body does not name {pointer}; the reference is unreachable",
                )

    def test_every_reference_carries_its_mechanism(self) -> None:
        references = _references_by_key()
        for skill, tokens in MECHANISM_TOKENS.items():
            path = MECHANISM_POINTERS[skill][0]
            content = references[(skill, path)]
            for token in tokens:
                with self.subTest(skill=skill, token=token):
                    self.assertIn(
                        token,
                        content,
                        f"{path} no longer names {token!r}; the mechanism is gone even "
                        "though the file is still there",
                    )

    def test_no_reference_records_a_date_or_a_volatile_count(self) -> None:
        """Cache-placement rule: a reference body outlives the state it describes.

        Scoped to the references registered above, deliberately. Eight references
        that predate #1714 carry a date, mostly a platform or specification
        version where the date is the fact rather than a timestamp of when
        someone wrote the file. Widening this assertion to the whole set would
        fail on content nobody registering here reviewed, and the honest way to
        adopt those is to read each one, not to make them my gate's problem.
        """
        references = _references_by_key()
        for skill, (path, _) in MECHANISM_POINTERS.items():
            content = references[(skill, path)]
            with self.subTest(reference=f"{skill}/{path}"):
                self.assertIsNone(
                    _DATE.search(content),
                    f"{skill}/{path} records a date; it will read as current forever",
                )
                self.assertIsNone(
                    _VOLATILE_COUNT.search(content),
                    f"{skill}/{path} records a count of live repository state",
                )

    def test_pointers_cost_one_line_each(self) -> None:
        """The budget claim: the mechanism is paid outside the body.

        Each body may name its reference on at most one line. A mechanism that
        spreads back into the always-loaded text is the failure this whole
        placement exists to avoid, and it would not be caught by the byte
        ceiling until it was already large.
        """
        bodies = _bodies_by_name()
        for skill, (_, pointer) in MECHANISM_POINTERS.items():
            with self.subTest(skill=skill):
                naming = [
                    line for line in bodies[skill].splitlines() if pointer in line
                ]
                self.assertEqual(
                    len(naming),
                    1,
                    f"{skill} names {pointer} on {len(naming)} lines; the pointer is one line",
                )

    def test_every_touched_body_stays_under_the_per_skill_ceiling(self) -> None:
        """`ultrawork` is the one with no room, which is why its pointer is terse."""
        bodies = _bodies_by_name()
        for skill in MECHANISM_POINTERS:
            with self.subTest(skill=skill):
                size = len(bodies[skill].encode("utf-8"))
                self.assertLessEqual(
                    size,
                    STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING,
                    f"{skill} body is {size} bytes; shorten the pointer before "
                    "raising the ceiling",
                )

    def test_the_reference_is_where_the_length_went(self) -> None:
        """Each mechanism is substantial, and none of it is in the body.

        Without this, the contract above is satisfiable by a stub reference and
        a pointer, which reads as delivered and carries no procedure.
        """
        references = _references_by_key()
        for skill, (path, _) in MECHANISM_POINTERS.items():
            with self.subTest(skill=skill):
                self.assertGreater(
                    len(references[(skill, path)]),
                    2000,
                    f"{path} is too short to carry a procedure a reader can follow",
                )


class ReferenceRegistrationTests(unittest.TestCase):
    def test_reference_paths_are_unique_per_skill(self) -> None:
        keys = [
            (template.skill_name, template.relative_path)
            for template in builtin_skill_reference_templates()
        ]
        self.assertEqual(len(keys), len(set(keys)), "a reference path is registered twice")

    def test_portable_projection_has_no_dangling_pointer(self) -> None:
        """A projected body may not name a reference the projection drops.

        `agent_skill_reference_templates()` fails closed on an unlisted path, so
        adding a body pointer without reviewing the reference for portability
        ships a pointer at a file that is not in the portable pack.
        """
        from omh.skills.render import agent_skill_reference_templates, agent_skill_templates

        shipped = {
            f"{template.skill_name}/{template.relative_path}"
            for template in agent_skill_reference_templates()
        }
        for template in agent_skill_templates():
            for path in re.findall(
                r"`([a-z0-9-]+)/(references/[a-z0-9-]+\.md)`", template.content
            ):
                with self.subTest(skill=template.name, reference="/".join(path)):
                    self.assertIn(
                        "/".join(path),
                        shipped,
                        f"{template.name} names {path[1]} of {path[0]}, which the "
                        "portable projection does not carry",
                    )
