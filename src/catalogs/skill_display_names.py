"""The `omh-`/`ulw-` display rule: the label a canonical catalog name renders as.

The skill catalog (`omh.skills.catalog_types`) re-exports everything here and
remains its public import path. It lives outside the `omh.skills` package so a
caller that only needs a label, such as the TUI launch card, can name skills
without the package `__init__` importing the whole catalog. Stdlib only.
"""

from __future__ import annotations


OMH_SKILL_NAME_PREFIX = "omh-"

# Canonical catalog names that get a hand-picked display label instead of the
# mechanical prefix. The override lookup runs before the idempotency guard in
# omh_skill_display_name() because that guard tests the INPUT name, not the
# override value: the two orders diverge only for an override KEY that already
# starts with `omh-`, which a prefix-first implementation would short-circuit
# before ever reaching its override. No current key does, so the ordering is a
# forward-looking contract rather than a live behavior.
OMH_SKILL_DISPLAY_NAME_OVERRIDES = {
    "oh-my-hermes": "omh-routing",
    # `product-docs` avoids reserving the generic canonical word `docs` while
    # preserving the public skill name requested by users.
    "product-docs": "omh-docs",
    # `strategy-brief` says what the output is, not what the skill does for
    # you. The skill turns goals and evidence into options, tradeoffs, and a
    # recommendation - it helps you decide. The canonical name stays put
    # (directory, manifest, tap URL, triggers); only the label a reader sees
    # changes.
    "strategy-brief": "omh-decide",
    # `ulw` already carries the "ultra". `ulw-ultrawork` says it twice, and the
    # duplicated syllable is the part a reader has to skip past to reach the
    # word that means something. Canonical names are untouched.
    "context": "ulw-context",
    "deep-interview": "ulw-interview",
    "ralplan": "ulw-plan",
    "ultragoal": "ulw-goal",
    "ultraprocess": "ulw-process",
    "ultraqa": "ulw-qa",
    "ultrawork": "ulw-work",
    # `ulw-performance` spells the domain out; `ulw-perf` is the label an
    # operator actually scans for in a status line, and the engine family
    # already abbreviates (`ulw-plan`, `ulw-qa`). Canonical name stays put.
    "ultraperf": "ulw-perf",
    # The `-operator` suffix names the implementation pattern, not the job. A
    # reader scanning a picker wants the job: the browser one drives web pages,
    # the terminal one scopes shell commands, the apps one reaches email/Slack/
    # Notion-style providers. Two labels also correct outright misreads:
    # `voice-operator` shapes terse voice/mobile-style REQUESTS (it does not
    # speak), and `img-summary` GENERATES image prompt cards (it does not
    # summarize images). Canonical names stay put everywhere, and the old
    # `omh-<canonical>` labels keep routing as historical aliases.
    "browser-operator": "omh-browser",
    "workspace-file-operator": "omh-files",
    "command-operator": "omh-terminal",
    "connector-operator": "omh-apps",
    "live-info-operator": "omh-live-info",
    "media-input-operator": "omh-media-input",
    "voice-operator": "omh-voice-input",
    "img-summary": "omh-image-cards",
    # The owner's own name for the graph run: people type `dag ulw` and `/dag-ulw`, and Hermes slugs the
    # rendered `name` into the slash command, so the label is the canonical name itself.
    "dag-ulw": "dag-ulw",
}

ULW_SKILL_NAME_PREFIX = "ulw-"

# The workflow-engine skills: the ones that drive a run rather than do a domain
# job. A user reaching for `ultrawork` wants an execution engine pointed at
# whatever they are already doing; a user reaching for `content-operator` wants
# that specific job done. The two read differently in a status line, so they get
# different labels.
#
# Membership is enumerated rather than derived from `category`, because the
# members span execution, clarification, research, planning, optimization, and
# verification -
# the grouping is what the skill is FOR, not where it sits in the catalog. Keep
# it small and explicit: a domain skill that drifts in here would make the
# distinction meaningless, which is the only thing the split is buying.
ULW_ENGINE_SKILL_NAMES = frozenset(
    {
        "context",
        "dag-ulw",
        "deep-interview",
        "loop",
        "maestro",
        "ralph",
        "ralplan",
        "research",
        "team",
        "ultragoal",
        "ultraprocess",
        "ultraperf",
        "ultraqa",
        "ultrawork",
    }
)


def omh_skill_display_name(name: str) -> str:
    """Return the rendered frontmatter label for a canonical catalog name.

    This is a display identifier that, since the relabel, also names the
    `skills/<label>/` install directory. The canonical `SkillDefinition.name`
    still owns the install manifest `name`, routing keys, and every CLI
    argument.
    """
    text = name.strip()
    override = OMH_SKILL_DISPLAY_NAME_OVERRIDES.get(text)
    if override is not None:
        return override
    prefix = ULW_SKILL_NAME_PREFIX if text in ULW_ENGINE_SKILL_NAMES else OMH_SKILL_NAME_PREFIX
    if text.startswith(prefix):
        return text
    return f"{prefix}{text}"
