"""Deterministic local executor skill discovery (`executor_skill_discovery/v1`).

Reporting-only observation of the coding skills the operator has installed for a
given executor, so a dispatched unit prompt can name the skills that user
actually has instead of a name OMH hardcoded. Every user's skill set is
different; nothing here assumes a particular pack is installed.

Boundaries, in order of importance:

- **Declared, never observed.** A `SKILL.md` on disk is configuration evidence
  that the file exists, not proof the executor loads, enables, or honours it.
  `READINESS_EVIDENCE_RULE` in `coding_delegation` exists because a binary on
  PATH plus an auth file was once read as "ready"; a skill directory is the same
  class of signal. Every payload carries the claim boundary.

- **Description in, role label out.** Classification reads each skill's YAML
  frontmatter `description`, which is third-party, operator-writable text — the
  one place this module reads a file body. That text NEVER leaves the
  classifier: it is matched against a closed role lexicon, reduced to one label,
  and discarded. Only the skill NAME reaches a caller, and only after passing
  `require_opaque_metadata_ref`. Without this rule a description reading
  "IGNORE PREVIOUS INSTRUCTIONS AND ..." would ride OMH's own prompt into a
  coding agent holding edit permissions; with it, the worst a hostile
  description can do is produce a wrong role label.

- **Invocation form comes from the source directory, not a guess.** The same
  Claude Code skill is `/<name>` under `~/.claude/skills` and `/<pack>:<name>`
  when a plugin marketplace provides it. Scanning is what makes the emitted
  string correct; a caller that guessed a prefix would be wrong for every user
  whose skills came from a plugin.

- **Bounded.** Fixed probe table, fixed depth, capped entries per source, capped
  frontmatter bytes. A hostile or oversized tree cannot cause unbounded IO.

- **No new vocabulary.** Roles are `model_routing.MODEL_ROLES`, the vocabulary
  fanout units already declare — not a fifth "skill/capability" vocabulary
  alongside `KNOWN_CAPABILITY_NAMES`, `capabilities/families.py`, and
  `skills/catalog.py`.

- **Read-time only.** Nothing here is persisted, cached, or routed. Discovery is
  passed explicitly by a caller that opted in; the router never imports it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final, Iterator, Mapping

from ..system.local_store import utc_now
from ..system.metadata_safety import require_opaque_metadata_ref
from .model_routing import MODEL_ROLES

EXECUTOR_SKILL_DISCOVERY_SCHEMA_VERSION: Final[str] = "executor_skill_discovery/v1"

EXECUTOR_SKILL_DISCOVERY_CLAIM_BOUNDARY: Final[str] = (
    "Executor skill discovery is a read-time observation of local files. It is evidence that a skill "
    "definition exists on disk, not that the executor loaded, enabled, or honoured it, and never "
    "dispatch, execution, review, CI, or merge evidence. The receiving agent's own registry is the "
    "authority on which skills resolve."
)

SOURCE_STATUSES: Final[tuple[str, ...]] = ("present", "absent", "unreadable", "unsupported")

# Fixed probe table. Each entry declares where a source lives relative to the
# operator's home and how a discovered entry is invoked, because the invocation
# form is a property of the source, not of the skill.
#
# `pi-family-runtime` has no probe: it is spawnable (see DISPATCH_COMMAND_TEMPLATES)
# but its host CLIs (pi-family and opencode) have no skill layout this repo can
# verify, and guessing a path would fabricate an environment. It still gets an
# explicit `unsupported` sources entry so a dry run shows WHY no skills are
# sequenced instead of an empty payload with no trace.
_CLAUDE_USER_SKILLS: Final[str] = ".claude/skills"
_CLAUDE_PLUGINS: Final[str] = ".claude/plugins"
# Codex roots follow Codex's own loader (openai/codex `host_roots.rs`):
# `$CODEX_HOME` (default `~/.codex`) holds prompts and skills, and the
# `.agents/skills` roots — per user and per repo — hold the agent-skills packs
# OMH itself installs for Codex. All skill roots invoke as `$name`.
_CODEX_HOME_DEFAULT: Final[str] = ".codex"
_CODEX_HOME_ENV: Final[str] = "CODEX_HOME"
_AGENT_SKILLS: Final[str] = ".agents/skills"

_PI_FAMILY_RUNTIME_SOURCE_REASON: Final[str] = (
    "no skill probe exists for the pi-family runtime: its host CLIs (pi-family and opencode) declare no "
    "skill layout this repo can verify, so none is scanned"
)

# A plugin's own manifest may live at either location depending on how it was
# packaged; the first parseable candidate wins.
_PLUGIN_MANIFEST_CANDIDATES: Final[tuple[str, ...]] = (".claude-plugin/plugin.json", "plugin.json")

# Caps. Chosen so the discovery block stays small next to UNIT_PROMPT_MAX_BYTES
# (8000) in unit_prompt_protocol; the chain that reaches a prompt is capped
# separately and much lower.
_MAX_ENTRIES_PER_SOURCE: Final[int] = 200
_MAX_MARKETPLACE_PACKS: Final[int] = 40
_MAX_FRONTMATTER_BYTES: Final[int] = 4096
_MAX_MANIFEST_BYTES: Final[int] = 16384

# How much a hit in the skill's own name outweighs one in its description. A
# name is the author's most compressed statement of purpose; a description
# mentions neighbouring concerns in passing ("implement, then review"), which is
# exactly what made first-match-wins misclassify — every coding skill's
# description mentions review somewhere.
_NAME_HIT_WEIGHT: Final[int] = 3
_DESCRIPTION_HIT_WEIGHT: Final[int] = 1

# Closed role lexicon. Matching is token-membership against these sets, never a
# raw substring scan. Scores are summed per role and the highest wins; ties
# break by the order below, so a genuine review skill (several review-lexicon
# hits) outranks an implementation skill that mentions review once.
# `review` is deliberately LAST. Almost every coding skill's description
# mentions review in passing — an autonomous-loop skill listing "$code-review"
# as one pipeline stage scored a 1-1 tie against implementation and, when review
# sorted first, was filed as a review skill. Ranking review last means a single
# stray mention loses every tie, and a genuine review skill still wins on count.
_ROLE_LEXICON: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    ("brain", frozenset({"plan", "planning", "planner", "architect", "architecture", "strategy", "decompose"})),
    ("research", frozenset({"research", "investigate", "investigation", "explore", "search", "survey", "trace"})),
    ("docs", frozenset({"docs", "doc", "documentation", "readme", "changelog", "writer", "writing"})),
    ("design_visual", frozenset({"design", "designer", "ui", "ux", "visual", "frontend", "layout", "css"})),
    (
        "implementation",
        frozenset(
            {
                # "code" is deliberately absent: it names the domain, not a
                # role, and it appears in every review/design/docs skill about
                # code — including "code-reviewer", which it filed as
                # implementation.
                "implement", "implementation", "coding", "build", "refactor", "fix", "debug",
                "test", "tests", "qa",
                # Execution-shaped vocabulary: loop/goal/autonomy skills are
                # implementation lanes, and without these their descriptions hit
                # nothing but an incidental "reviewer".
                "loop", "autonomous", "autonomy", "execute", "execution", "orchestrate", "orchestration",
                "workflow", "pipeline", "completion", "deliver", "delivery",
            }
        ),
    ),
    ("review", frozenset({"review", "reviewer", "critique", "critic", "audit", "auditor", "lint"})),
)


def discovered_executor_skills(
    profile: str,
    home: Path | None = None,
    *,
    project_root: Path | None = None,
) -> dict[str, object]:
    """Return the metadata-only discovery payload for one executor profile.

    Only the selected profile is probed: exactly one handoff is built per
    delegation, so a table covering every profile would be dead weight.
    """
    base = home if home is not None else Path.home()
    codex_home = _codex_home(base, honour_env=home is None)
    sources: dict[str, object] = {}
    skills: list[dict[str, str]] = []
    rejected = 0
    shadowed = 0
    # Codex resolves a duplicate skill name to the first root in its
    # precedence order, so only that copy is reported; the later copies are
    # counted, never listed, so a dry run can see that shadowing happened.
    # Keyed on the invocation: a `/name` prompt and a `$name` skill are
    # distinct commands and do not shadow each other.
    seen_invocations: set[str] | None = set() if profile == "codex" else None
    for source_id, entries, status, reason in _probe_profile(profile, base, project_root, codex_home):
        source: dict[str, str] = {"status": status}
        if reason:
            source["reason"] = reason
        sources[source_id] = source
        for name, invocation, description in entries:
            safe = _safe_name(name)
            if safe is None:
                rejected += 1
                continue
            resolved_invocation = invocation.replace(_NAME_PLACEHOLDER, safe)
            if seen_invocations is not None:
                if resolved_invocation in seen_invocations:
                    shadowed += 1
                    continue
                seen_invocations.add(resolved_invocation)
            role, score = classify_role_scored(description, safe)
            skills.append(
                {
                    "name": safe,
                    "invocation": resolved_invocation,
                    "role": role,
                    "role_score": score,
                    "source": source_id,
                }
            )
    skills.sort(key=lambda entry: (str(entry["role"]), -int(entry["role_score"]), str(entry["name"])))
    return {
        "schema_version": EXECUTOR_SKILL_DISCOVERY_SCHEMA_VERSION,
        "observed_at": utc_now(),
        "executor_profile": profile,
        "sources": sources,
        "skills": skills,
        "rejected_name_count": rejected,
        "shadowed_name_count": shadowed,
        "claim_boundary": EXECUTOR_SKILL_DISCOVERY_CLAIM_BOUNDARY,
    }


def skills_for_role(discovery: Mapping[str, object] | None, role: str, *, limit: int) -> list[dict[str, str]]:
    """Return up to `limit` discovered skills matching one role.

    Ranked by classification score first — the skill whose name and description
    most clearly state the role wins — then by name for determinism. Ranking by
    name alone once picked `/ai-slop-cleaner` as the implementation skill purely
    because it sorts before `/ultrawork`.
    """
    if not isinstance(discovery, Mapping) or limit <= 0:
        return []
    entries = discovery.get("skills")
    if not isinstance(entries, list):
        return []
    matched = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and str(entry.get("role", "")) == role and entry.get("name")
    ]
    matched.sort(key=_role_rank)
    return [dict(entry) for entry in matched[:limit]]


def _role_rank(entry: Mapping[str, object]) -> tuple[int, str, str]:
    try:
        score = int(entry.get("role_score", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    return (-score, str(entry.get("name", "")), str(entry.get("source", "")))


def classify_role(description: str, name: str) -> str:
    """Reduce a skill description and name to one closed-vocabulary role."""
    return classify_role_scored(description, name)[0]


def classify_role_scored(description: str, name: str) -> tuple[str, int]:
    """Reduce a skill description and name to one role label plus its match score.

    The description text is consumed here and never returned — callers receive a
    role label and an integer only. Scoring rather than first-match-wins:
    descriptions name neighbouring concerns in passing, so a single stray
    "review" must not outrank an implementation skill's several implementation
    hits. The score also ranks skills WITHIN a role, so the skill that states
    its role most clearly is offered first.
    """
    name_tokens = _tokens(name)
    description_tokens = _tokens(description)
    if not name_tokens and not description_tokens:
        return ("", 0)
    best_role = ""
    best_score = 0
    for role, lexicon in _ROLE_LEXICON:
        score = _NAME_HIT_WEIGHT * len(name_tokens & lexicon) + _DESCRIPTION_HIT_WEIGHT * len(
            description_tokens & lexicon
        )
        if score > best_score:
            best_role, best_score = role, score
    return (best_role, best_score)


# --- Sequence arrangement -------------------------------------------------
#
# A unit is one bounded piece of work, not a tour of the operator's skill
# library. These recipes state what a unit of each role actually needs, in the
# order it needs it: an implementation unit wants scoping, the work, then a
# review of its own diff — never a docs skill it will not open. One skill per
# step; a step offering three alternatives is a decision the executor must make
# before starting, one named skill is a suggestion it can take or drop.
ROLE_SEQUENCE_RECIPES: Final[dict[str, tuple[str, ...]]] = {
    "implementation": ("brain", "implementation", "review"),
    "brain": ("research", "brain"),
    "research": ("research", "brain"),
    "review": ("review",),
    "design_visual": ("design_visual", "implementation", "review"),
    "docs": ("research", "docs"),
}
# An unrouted coding unit is an implementation unit in shape.
DEFAULT_SEQUENCE_RECIPE: Final[tuple[str, ...]] = ROLE_SEQUENCE_RECIPES["implementation"]

SEQUENCE_STEP_PURPOSES: Final[dict[str, str]] = {
    "brain": "scope the change and agree the plan before editing",
    "research": "investigate before deciding",
    "implementation": "do the implementation",
    "design_visual": "the visual/UI work",
    "review": "review your own diff before committing",
    "docs": "update the documentation the change affects",
}

SKILL_SELECTION_CARD_SCHEMA_VERSION: Final[str] = "executor_skill_selection/v1"

SKILL_SELECTION_CLAIM_BOUNDARY: Final[str] = (
    "A skill selection card is prepared advisory data derived from declared local files. Offering it, "
    "or dispatching with any of its options, is never evidence that a skill loaded, resolved, or ran."
)


def suggested_skill_sequence(
    discovery: Mapping[str, object] | None,
    unit_role: str,
    *,
    rank: int = 0,
) -> list[dict[str, str]]:
    """Arrange discovered skills into the recipe sequence for one unit role.

    `rank` selects the rank-th best skill per step (0 = top pick); a step whose
    role has no skill at that rank falls back to the top pick, and a step with
    no matching skill at all is dropped. Duplicates across steps are dropped so
    an autonomous-loop skill classified once never appears twice.
    """
    steps: list[dict[str, str]] = []
    used: set[str] = set()
    for role in ROLE_SEQUENCE_RECIPES.get(unit_role, DEFAULT_SEQUENCE_RECIPE):
        matches = [
            match
            for match in skills_for_role(discovery, role, limit=rank + len(used) + 1)
            if match["invocation"] not in used
        ]
        if not matches:
            continue
        pick = matches[min(rank, len(matches) - 1)]
        used.add(pick["invocation"])
        steps.append(
            {
                "invocation": str(pick["invocation"]),
                "role": role,
                "purpose": SEQUENCE_STEP_PURPOSES[role],
            }
        )
    return steps


def skill_interview_recommended(discovery: Mapping[str, object] | None) -> bool:
    """Whether dispatch should double-check the skill arrangement with the user.

    Fires only when a genuine arrangement choice exists: at least two classified
    skills spanning at least two distinct roles. Zero or one skill leaves
    nothing to arrange, so the direct path stays direct; an explicit
    `skill_sequence` on the unit (including `[]` for none) records the answer
    and suppresses the question entirely.
    """
    if not isinstance(discovery, Mapping):
        return False
    entries = discovery.get("skills")
    if not isinstance(entries, list):
        return False
    roles = {str(entry.get("role", "")) for entry in entries if isinstance(entry, Mapping) and entry.get("role")}
    classified = sum(1 for entry in entries if isinstance(entry, Mapping) and entry.get("role"))
    return classified >= 2 and len(roles) >= 2


def skill_selection_card(
    discovery: Mapping[str, object] | None,
    unit_role: str,
) -> dict[str, object] | None:
    """Build the deep-interview card for one unit, or None when no choice exists.

    Options 1-3 are concrete arranged sequences (as many as are genuinely
    distinct); option 4 is manual entry; option 5 is no skills at all. The card
    is deterministic data for whichever wrapper asks the question — OMH itself
    never blocks dispatch on it.
    """
    if not skill_interview_recommended(discovery):
        return None
    profile = str(discovery.get("executor_profile", "")) if isinstance(discovery, Mapping) else ""
    recommended = suggested_skill_sequence(discovery, unit_role, rank=0)
    if not recommended:
        return None
    options: list[dict[str, object]] = [
        {
            "option": 1,
            "kind": "suggested_sequence",
            "label": "Recommended sequence",
            "sequence": recommended,
        }
    ]
    primary_only = recommended[:1] if len(recommended) > 1 else []
    if primary_only:
        options.append(
            {
                "option": 2,
                "kind": "suggested_sequence",
                "label": "Minimal — first step only",
                "sequence": primary_only,
            }
        )
    alternate = suggested_skill_sequence(discovery, unit_role, rank=1)
    if alternate and alternate != recommended and len(options) < 3:
        options.append(
            {
                "option": len(options) + 1,
                "kind": "suggested_sequence",
                "label": "Alternate picks",
                "sequence": alternate,
            }
        )
    options.append(
        {
            "option": 4,
            "kind": "manual_sequence",
            "label": "Type the sequence yourself",
            "how": 'declare skill_sequence: ["/your-skill", ...] on the unit and re-dispatch',
        }
    )
    options.append(
        {
            "option": 5,
            "kind": "no_skills",
            "label": "No skills — dispatch the pure prompt",
            "how": "declare skill_sequence: [] on the unit and re-dispatch",
        }
    )
    return {
        "schema_version": SKILL_SELECTION_CARD_SCHEMA_VERSION,
        "executor_profile": profile,
        "unit_role": unit_role,
        "status": "choice_offered",
        "default_when_unanswered": "option 1 (the recommended sequence) rides the prompt automatically",
        "options": options,
        "claim_boundary": SKILL_SELECTION_CLAIM_BOUNDARY,
    }


_NAME_PLACEHOLDER: Final[str] = "{name}"


def _codex_home(base: Path, *, honour_env: bool) -> Path:
    """Return Codex's home: `$CODEX_HOME` when set (and no explicit home was
    passed), else `<base>/.codex` — the same default Codex itself uses."""
    if honour_env:
        configured = os.environ.get(_CODEX_HOME_ENV, "").strip()
        if configured:
            return Path(configured).expanduser()
    return base / _CODEX_HOME_DEFAULT


def _probe_profile(
    profile: str,
    base: Path,
    project_root: Path | None,
    codex_home: Path,
) -> Iterator[tuple[str, list[tuple[str, str, str]], str, str]]:
    if profile == "claude-code":
        yield (*_skill_dir_source("claude_user_skills", base / _CLAUDE_USER_SKILLS, f"/{_NAME_PLACEHOLDER}"), "")
        yield (*_plugin_skill_source("claude_plugin_skills", base / _CLAUDE_PLUGINS), "")
        if project_root is not None:
            yield (
                *_skill_dir_source(
                    "claude_project_skills", project_root / ".claude" / "skills", f"/{_NAME_PLACEHOLDER}"
                ),
                "",
            )
        return
    if profile == "codex":
        # Yielded in Codex's precedence order (first wins on a duplicate
        # name): repo agent skills, then `$CODEX_HOME` prompts (addressed by
        # file stem) and skills, then the user's agent skills. Only the
        # project root's `.agents/skills` is probed — OMH knows the root, not
        # the executor's eventual cwd below it.
        skill = f"${_NAME_PLACEHOLDER}"
        if project_root is not None:
            yield (
                *_skill_dir_source(
                    "codex_repo_agent_skills", project_root / _AGENT_SKILLS, skill, confine_to_root=True
                ),
                "",
            )
        yield (*_prompt_file_source("codex_prompts", codex_home / "prompts", f"/{_NAME_PLACEHOLDER}"), "")
        yield (*_skill_dir_source("codex_skills", codex_home / "skills", skill, confine_to_root=True), "")
        yield (
            *_skill_dir_source("codex_user_agent_skills", base / _AGENT_SKILLS, skill, confine_to_root=True),
            "",
        )
        return
    if profile == "pi-family-runtime":
        # An explicit unsupported entry, not silence: without it a dry run
        # shows `sources: {}` and the operator cannot tell "no skills
        # installed" from "OMH never looked".
        yield ("pi_family_runtime_skills", [], "unsupported", _PI_FAMILY_RUNTIME_SOURCE_REASON)
        return
    return


def _skill_dir_source(
    source_id: str,
    root: Path,
    invocation: str,
    *,
    confine_to_root: bool = False,
) -> tuple[str, list[tuple[str, str, str]], str]:
    """Entries for one `<root>/<name>/SKILL.md` tree.

    With `confine_to_root`, a symlinked skill directory is listed only when it
    resolves inside `root`; one that escapes (or cannot be resolved) is
    skipped, so a link cannot point discovery at an arbitrary tree. Hidden
    directories such as Codex's `.system` never list: without a SKILL.md of
    their own they are skipped here, and with one their names fail
    `_safe_name` and are counted as rejected.
    """
    if not root.is_dir():
        return (source_id, [], "absent")
    entries: list[tuple[str, str, str]] = []
    try:
        children = sorted(child for child in root.iterdir() if child.is_dir())
        resolved_root = root.resolve() if confine_to_root else root
    except (OSError, RuntimeError):
        return (source_id, [], "unreadable")
    for child in children[:_MAX_ENTRIES_PER_SOURCE]:
        if confine_to_root and child.is_symlink() and not _resolves_within(child, resolved_root):
            continue
        definition = child / "SKILL.md"
        if not definition.is_file():
            continue
        entries.append((child.name, invocation, _frontmatter_description(definition)))
    return (source_id, entries, "present")


def _resolves_within(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def _prompt_file_source(
    source_id: str,
    root: Path,
    invocation: str,
) -> tuple[str, list[tuple[str, str, str]], str]:
    if not root.is_dir():
        return (source_id, [], "absent")
    try:
        children = sorted(root.glob("*.md"))
    except OSError:
        return (source_id, [], "unreadable")
    entries = [
        (child.stem, invocation, _frontmatter_description(child))
        for child in children[:_MAX_ENTRIES_PER_SOURCE]
        if child.is_file()
    ]
    return (source_id, entries, "present")


def _plugin_skill_source(source_id: str, root: Path) -> tuple[str, list[tuple[str, str, str]], str]:
    """Discover plugin-provided skills, which invoke as `/<plugin>:<name>`.

    Two layouts, probed in preference order. Installed plugin skills live in
    the cache layout (`cache/<marketplace>/<plugin>/<version>/skills/...`), so
    it wins whenever it yields anything; the marketplace-clone layout
    (`marketplaces/<dir>/plugins/<plugin>/skills/...`, plus the legacy
    `marketplaces/<dir>/.claude/skills` shape) is the fallback. In both, the
    namespace prefix is the plugin's own manifest name when readable — that is
    the prefix the receiving agent resolves — and the directory name only as a
    fallback: a cache dir `ui-ux-pro-max-skill` holding a plugin named
    `ui-ux-pro-max` must emit `/ui-ux-pro-max:design`, not a prefix no
    registry knows.
    """
    cache = _plugin_cache_probe(source_id, root / "cache")
    if cache[2] == "present":
        return cache
    marketplace = _marketplace_clone_probe(source_id, root / "marketplaces")
    if marketplace[2] == "present":
        return marketplace
    if "unreadable" in (cache[2], marketplace[2]):
        return (source_id, [], "unreadable")
    return (source_id, [], "absent")


def _plugin_cache_probe(source_id: str, root: Path) -> tuple[str, list[tuple[str, str, str]], str]:
    """Probe `cache/<marketplace>/<plugin>/<version>/` plugin roots."""
    if not root.is_dir():
        return (source_id, [], "absent")
    try:
        marketplaces = sorted(child for child in root.iterdir() if child.is_dir())
    except OSError:
        return (source_id, [], "unreadable")
    entries: list[tuple[str, str, str]] = []
    for marketplace in marketplaces[:_MAX_MARKETPLACE_PACKS]:
        try:
            plugins = sorted(child for child in marketplace.iterdir() if child.is_dir())
        except OSError:
            continue
        for plugin_dir in plugins[:_MAX_MARKETPLACE_PACKS]:
            version_root = _plugin_version_root(plugin_dir)
            if version_root is not None:
                entries.extend(_plugin_dir_entries(source_id, version_root, plugin_dir.name))
    if not entries:
        return (source_id, [], "absent")
    return (source_id, entries[:_MAX_ENTRIES_PER_SOURCE], "present")


def _marketplace_clone_probe(source_id: str, root: Path) -> tuple[str, list[tuple[str, str, str]], str]:
    """Probe marketplace clones: `plugins/<plugin>/` roots first, then the
    legacy `.claude/skills` shape namespaced by the marketplace directory name."""
    if not root.is_dir():
        return (source_id, [], "absent")
    try:
        clones = sorted(child for child in root.iterdir() if child.is_dir())
    except OSError:
        return (source_id, [], "unreadable")
    entries: list[tuple[str, str, str]] = []
    for clone in clones[:_MAX_MARKETPLACE_PACKS]:
        plugins_dir = clone / "plugins"
        if plugins_dir.is_dir():
            try:
                plugin_dirs = sorted(child for child in plugins_dir.iterdir() if child.is_dir())
            except OSError:
                plugin_dirs = []
            for plugin_dir in plugin_dirs[:_MAX_MARKETPLACE_PACKS]:
                entries.extend(_plugin_dir_entries(source_id, plugin_dir, plugin_dir.name))
        pack_name = _safe_name(clone.name)
        if pack_name is None:
            continue
        _, legacy_entries, status = _skill_dir_source(
            source_id, clone / ".claude" / "skills", f"/{pack_name}:{_NAME_PLACEHOLDER}"
        )
        if status == "present":
            entries.extend(legacy_entries)
    if not entries:
        return (source_id, [], "absent")
    return (source_id, entries[:_MAX_ENTRIES_PER_SOURCE], "present")


def _plugin_version_root(plugin_dir: Path) -> Path | None:
    """Pick one version directory per cached plugin.

    Sorted-last is a deterministic tiebreak, not semver comparison; the common
    cache holds a single version dir (often literally named `unknown`), and a
    wrong pick among several still names skills the operator has installed.
    """
    try:
        versions = sorted(child for child in plugin_dir.iterdir() if child.is_dir())
    except OSError:
        return None
    return versions[-1] if versions else None


def _plugin_dir_entries(source_id: str, plugin_root: Path, fallback_name: str) -> list[tuple[str, str, str]]:
    """Entries for one plugin root, namespaced by its manifest name."""
    manifest = _plugin_manifest(plugin_root)
    namespace: str | None = None
    declared_name = manifest.get("name", "")
    if isinstance(declared_name, str) and declared_name:
        namespace = _safe_name(declared_name)
    if namespace is None:
        namespace = _safe_name(fallback_name)
    if namespace is None:
        return []
    skills_root = plugin_root / _plugin_skills_dirname(manifest)
    _, entries, status = _skill_dir_source(source_id, skills_root, f"/{namespace}:{_NAME_PLACEHOLDER}")
    return entries if status == "present" else []


def _plugin_manifest(plugin_root: Path) -> dict[str, object]:
    """Return the plugin's parsed manifest, or `{}`.

    Missing, unreadable, oversized, and malformed manifests all reduce to the
    same `{}` — the caller then falls back to the directory name, which keeps
    a broken manifest from hiding a plugin whose skills are really installed.
    Only a bounded prefix is read, matching the frontmatter reader's IO bound.
    """
    for relative in _PLUGIN_MANIFEST_CANDIDATES:
        path = plugin_root / relative
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                loaded = json.loads(handle.read(_MAX_MANIFEST_BYTES))
        except (OSError, ValueError):
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}


def _plugin_skills_dirname(manifest: Mapping[str, object]) -> str:
    """Return the manifest's optional `skills` directory, or the default.

    The value is third-party text naming a path, so it is confined to the
    plugin root: absolute paths, drive/scheme colons, and `..` segments all
    fall back to the default rather than letting a manifest point discovery at
    an arbitrary tree.
    """
    declared = manifest.get("skills", "")
    if not isinstance(declared, str) or not declared.strip():
        return "skills"
    candidate = declared.strip()
    if candidate.startswith(("/", "\\")) or ":" in candidate:
        return "skills"
    parts = [part for part in candidate.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return "skills"
    return "/".join(parts)


def _frontmatter_description(path: Path) -> str:
    """Return the `description` scalar from a leading `---` block, or an empty string.

    Hand-rolled on purpose: this repo ships zero runtime dependencies, so no
    YAML parser is available. Only a bounded prefix of the file is read, and
    only the one key is extracted; every other line is discarded unparsed.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_MAX_FRONTMATTER_BYTES)
    except OSError:
        return ""
    lines = head.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return ""
        key, separator, value = stripped.partition(":")
        if separator and key.strip() == "description":
            return value.strip().strip("'\"")
    return ""


def _safe_name(value: str) -> str | None:
    try:
        return require_opaque_metadata_ref(value, field="discovered skill name")
    except ValueError:
        return None


def _tokens(value: str) -> frozenset[str]:
    lowered = "".join(char if char.isalnum() else " " for char in value.casefold())
    return frozenset(token for token in lowered.split() if token)


__all__ = [
    "DEFAULT_SEQUENCE_RECIPE",
    "EXECUTOR_SKILL_DISCOVERY_CLAIM_BOUNDARY",
    "EXECUTOR_SKILL_DISCOVERY_SCHEMA_VERSION",
    "MODEL_ROLES",
    "ROLE_SEQUENCE_RECIPES",
    "SEQUENCE_STEP_PURPOSES",
    "SKILL_SELECTION_CARD_SCHEMA_VERSION",
    "SKILL_SELECTION_CLAIM_BOUNDARY",
    "SOURCE_STATUSES",
    "classify_role",
    "classify_role_scored",
    "discovered_executor_skills",
    "skill_interview_recommended",
    "skill_selection_card",
    "skills_for_role",
    "suggested_skill_sequence",
]
