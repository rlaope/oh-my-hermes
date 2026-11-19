"""Host facts for `harness_fit`: what six agent hosts do with a skill folder.

One `HostFacts` per host. Each fact (scan roots, listing windows, catalog
budgets, read caps, placeholder substitution, what a frontmatter defect costs)
names its source in `provenance`, and every source key is spelled out in
`SOURCES` with the version and date it was verified against.

Most facts were read from NVIDIA SkillEvaluator 1.0.1's harness profiles
(Apache-2.0), which record what its authors measured with canary probes against
each host. Only the facts were taken. The data layout, the field names and all
wording here are OMH's own, and no upstream code was read or reused. The
Hermes window, linked-file and result-budget facts were re-read from the
Hermes source itself. `docs/SKILL-SOURCES.md` records the upstream so the
tracker notices when the profiles change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

SKILLEVALUATOR = "skillevaluator-1.0.1"
HERMES_SOURCE = "hermes-agent-source"
OMH_FIT = "omh-fit-2026-11-19"

SOURCES: dict[str, str] = {
    SKILLEVALUATOR: (
        "NVIDIA/SkillEvaluator v1.0.1 (tag 914c15cb3f31562ccffdc9a7166002a87ed2ce1e), harness "
        "profile <host>.yaml, Apache-2.0; each profile's own `verified` block names the host "
        "version and the 2026-11-01 probe date. Facts only; no code or wording reused."
    ),
    HERMES_SOURCE: (
        "NousResearch/hermes-agent 3b4215785882 (main, committed 2026-11-09), read on 2026-11-19: "
        "agent/skill_utils.py clip_skill_description, iter_skill_index_files (nested walk, followed "
        "links, pruned support and cache folders) and get_external_skills_dirs, hermes_cli profiles "
        "(each profile's HERMES_HOME holds its own skills/), tools/skills_tool.py linked-file globs, "
        "tools/budget_config.py DEFAULT_RESULT_SIZE_CHARS."
    ),
    OMH_FIT: (
        "OMH fit against SkillEvaluator 1.0.1 output for oh-my-hermes a5649293 on 2026-11-19: "
        "the OpenClaw read size it reported for the 19 flagged SKILL.md files equals characters "
        "+ 3 per wide (CJK) character + 73 for 18 of them; omh-memory-sync measured 3 higher."
    ),
}


@dataclass(frozen=True)
class HostFacts:
    """What one host does with a skill; `None` or empty means the host has no such limit."""

    host: str
    display_name: str
    prefix: str
    verified_version: str
    verified_date: str
    verified_source: str
    project_roots: tuple[str, ...]
    user_roots: tuple[str, ...]
    project_roots_need_trust: bool = False
    # Further user roots as `/`-separated globs, one `*` per folder name.
    root_globs: tuple[str, ...] = ()
    # The host also reads its active home's skills/ and the folders its config
    # adds (Hermes: `$HERMES_HOME/skills` and `skills.external_dirs`).
    config_roots: bool = False
    # The host finds SKILL.md at any depth below a root. Otherwise it is known
    # to find skills up to `max_grouping_depth` grouping folders below the root
    # (`None`: only directly under it), and a deeper skill gets
    # `grouping_effect` (`None`: no recorded fact, so `unverified`).
    walks_nested: bool = False
    max_grouping_depth: int | None = None
    grouping_effect: str | None = None
    # How much of one description the skill list shows. `listing_unit` is
    # `hermes_clip` (word-boundary clip), `codepoints`, `codepoints_with_when_to_use`,
    # `utf16` (UTF-16 code units) or `compact` (a cut applied only over the catalog cap).
    listing_unit: str | None = None
    listing_limit: int | None = None
    listing_effect: str | None = None
    # How much of the whole catalog the skill list holds. `budget_kind` is
    # `context_share` (a share of the context window), `skill_or_char_cap`, or
    # `full_description_count` (only the first N skills keep their description).
    budget_kind: str | None = None
    budget_effect: str | None = None
    budget_context_share: float | None = None
    budget_unit: str | None = None
    budget_per_token: int | None = None
    budget_unknown_context: int | None = None
    budget_max_tokens: int | None = None
    budget_max_skills: int | None = None
    budget_max_chars: int | None = None
    # Delivering the body.
    view_budget_chars: int | None = None
    read_caps: tuple[tuple[int | None, int], ...] = ()
    read_wide_weight: int | None = None
    read_overhead_chars: int | None = None
    long_line_chars: int | None = None
    # The skill tool's own output cap on the body it delivers (frontmatter
    # stripped), separate from the per-line cut of the file-read tool.
    body_cap_lines: int | None = None
    body_cap_bytes: int | None = None
    # Folders whose files the skill view lists: (folder, name globs, recursive).
    linked_files: tuple[tuple[str, tuple[str, ...], bool], ...] = ()
    file_cap_bytes: int | None = None
    # Token class (`arguments`, `skill_dir`, `positional`) -> effect when it is
    # live prose in the body. A class the host substitutes correctly is absent.
    placeholder_effects: Mapping[str, str] = field(default_factory=dict)
    # Frontmatter or file defect -> effect on this host; absent means the host
    # is recorded as unaffected, `unverified` that no fact says what it does.
    defect_effects: Mapping[str, str] = field(default_factory=dict)
    provenance: Mapping[str, str] = field(default_factory=dict)


FACT_FIELDS = (
    "project_roots", "user_roots", "project_roots_need_trust", "root_globs", "config_roots",
    "walks_nested", "max_grouping_depth", "grouping_effect",
    "listing_unit", "listing_limit", "listing_effect",
    "budget_kind", "budget_effect", "budget_context_share", "budget_unit", "budget_per_token",
    "budget_unknown_context", "budget_max_tokens", "budget_max_skills", "budget_max_chars",
    "view_budget_chars", "read_caps", "read_wide_weight", "read_overhead_chars",
    "long_line_chars", "body_cap_lines", "body_cap_bytes", "linked_files", "file_cap_bytes", "placeholder_effects", "defect_effects",
)


def _cite(source: str, *fields: str) -> dict[str, str]:
    return {name: source for name in fields}


_HOSTS = (
    HostFacts(
        host="hermes",
        display_name="Hermes Agent",
        prefix="HERMES",
        verified_version="main @ 3b4215785882",
        verified_date="2026-11-19",
        verified_source=(
            "hermes-agent source read by OMH; SkillEvaluator 1.0.1 verified main @ c419cf7c864a "
            "on 2026-11-01"
        ),
        project_roots=(".hermes/skills", ".agents/skills"),
        user_roots=("~/.hermes/skills",),
        project_roots_need_trust=True,
        root_globs=("~/.hermes/profiles/*/skills",),
        config_roots=True,
        walks_nested=True,
        listing_unit="hermes_clip",
        listing_limit=60,
        listing_effect="advisory",
        view_budget_chars=100_000,
        linked_files=(
            ("references", ("*.md",), False),
            ("templates", ("*.md", "*.py", "*.yaml", "*.yml", "*.json", "*.tex", "*.sh"), True),
            ("assets", ("*",), True),
            ("scripts", ("*.py", "*.sh", "*.bash", "*.js", "*.ts", "*.rb"), False),
        ),
        placeholder_effects={"arguments": "degraded", "skill_dir": "degraded"},
        defect_effects={
            "desc_missing": "degraded", "desc_empty": "degraded", "duplicate_key": "advisory",
            "casing": "not_loaded", "symlink": "not_loaded",
            "desc_typed": "unverified", "desc_list": "unverified", "desc_map": "unverified",
            "tab_indent": "unverified", "yaml_unsupported": "unverified",
        },
        provenance={
            **_cite(SKILLEVALUATOR, "project_roots", "user_roots", "project_roots_need_trust",
                    "listing_effect", "placeholder_effects", "defect_effects"),
            **_cite(HERMES_SOURCE, "root_globs", "config_roots", "walks_nested", "listing_unit", "listing_limit",
                    "view_budget_chars", "linked_files"),
        },
    ),
    HostFacts(
        host="claude-code",
        display_name="Claude Code",
        prefix="CLAUDE",
        verified_version="2.1.316",
        verified_date="2026-11-01",
        verified_source="closed source, bundled JS inspected (SkillEvaluator 1.0.1 profile)",
        project_roots=(".claude/skills",),
        user_roots=("~/.claude/skills",),
        max_grouping_depth=0,
        grouping_effect="not_loaded",
        listing_unit="codepoints_with_when_to_use",
        listing_limit=1536,
        listing_effect="degraded",
        budget_kind="context_share",
        budget_effect="degraded",
        budget_context_share=0.01,
        budget_unit="chars",
        budget_per_token=4,
        budget_unknown_context=8_000,
        file_cap_bytes=1_048_576,
        placeholder_effects={"positional": "degraded"},
        defect_effects={
            "desc_missing": "degraded", "desc_empty": "degraded", "duplicate_key": "advisory",
            "casing": "degraded",
            "desc_typed": "degraded", "desc_list": "degraded", "desc_map": "degraded",
            "yaml_unsupported": "unverified",
        },
        provenance=_cite(
            SKILLEVALUATOR, "project_roots", "user_roots", "max_grouping_depth", "grouping_effect", "listing_unit",
            "listing_limit", "listing_effect", "budget_kind", "budget_effect", "budget_context_share", "budget_unit",
            "budget_per_token", "budget_unknown_context", "file_cap_bytes", "placeholder_effects",
            "defect_effects",
        ),
    ),
    HostFacts(
        host="codex",
        display_name="OpenAI Codex CLI",
        prefix="CODEX",
        verified_version="0.166.0",
        verified_date="2026-11-01",
        verified_source="rust-v0.166.0 @ 593389380740 (SkillEvaluator 1.0.1 profile)",
        project_roots=(".agents/skills", ".codex/skills"),
        user_roots=("~/.agents/skills", "~/.codex/skills"),
        max_grouping_depth=5,
        grouping_effect="not_loaded",
        listing_unit="codepoints",
        listing_limit=1024,
        listing_effect="degraded",
        budget_kind="context_share",
        budget_effect="degraded",
        budget_context_share=0.02,
        budget_unit="bytes",
        budget_per_token=4,
        budget_unknown_context=8_000,
        budget_max_tokens=10_000,
        placeholder_effects={"arguments": "degraded", "skill_dir": "degraded"},
        defect_effects={
            "desc_missing": "not_loaded", "desc_empty": "not_loaded", "duplicate_key": "not_loaded",
            "casing": "not_loaded", "symlink": "not_loaded",
            "desc_typed": "not_loaded", "desc_list": "not_loaded", "desc_map": "not_loaded",
            "tab_indent": "not_loaded", "yaml_unsupported": "unverified",
        },
        provenance=_cite(
            SKILLEVALUATOR, "project_roots", "user_roots", "max_grouping_depth", "grouping_effect", "listing_unit",
            "listing_limit", "listing_effect", "budget_kind", "budget_effect", "budget_context_share", "budget_unit",
            "budget_per_token", "budget_unknown_context", "budget_max_tokens", "placeholder_effects",
            "defect_effects",
        ),
    ),
    HostFacts(
        host="openclaw",
        display_name="OpenClaw",
        prefix="OPENCLAW",
        verified_version="2026.10.9",
        verified_date="2026-11-01",
        verified_source="v2026.10.9 @ 88a19e0d8677 (SkillEvaluator 1.0.1 profile)",
        project_roots=("skills", ".agents/skills"),
        user_roots=("~/.agents/skills", "~/.openclaw/skills"),
        listing_unit="compact",
        listing_limit=220,
        listing_effect="degraded",
        budget_kind="skill_or_char_cap",
        budget_effect="advisory",
        budget_max_skills=150,
        budget_max_chars=18_000,
        read_caps=((100_000, 16_000), (200_000, 32_000), (None, 64_000)),
        read_wide_weight=4,
        read_overhead_chars=73,
        file_cap_bytes=256_000,
        placeholder_effects={"arguments": "degraded", "skill_dir": "degraded"},
        defect_effects={
            "desc_missing": "not_loaded", "desc_empty": "not_loaded", "duplicate_key": "not_loaded",
            "casing": "degraded", "symlink": "not_loaded", "dir_link_escape": "not_loaded",
            "desc_typed": "unverified", "desc_map": "unverified",
            "tab_indent": "not_loaded", "yaml_unsupported": "unverified",
        },
        provenance={
            **_cite(SKILLEVALUATOR, "project_roots", "user_roots", "listing_unit", "listing_limit",
                    "listing_effect", "budget_kind", "budget_effect", "budget_max_skills",
                    "budget_max_chars", "read_caps", "read_wide_weight", "file_cap_bytes",
                    "placeholder_effects", "defect_effects"),
            **_cite(OMH_FIT, "read_overhead_chars"),
        },
    ),
    HostFacts(
        host="opencode",
        display_name="OpenCode",
        prefix="OPENCODE",
        verified_version="1.19.5",
        verified_date="2026-11-01",
        verified_source="v1.19.5 @ 810c0eba1a73 (SkillEvaluator 1.0.1 profile)",
        project_roots=(".opencode/skills", ".opencode/skill", ".claude/skills", ".agents/skills"),
        user_roots=("~/.config/opencode/skills", "~/.claude/skills", "~/.agents/skills"),
        walks_nested=True,
        long_line_chars=2_000,
        body_cap_lines=2_000,
        body_cap_bytes=51_200,
        placeholder_effects={"arguments": "degraded", "skill_dir": "degraded", "positional": "degraded"},
        defect_effects={
            "name_missing": "not_loaded", "desc_missing": "not_loaded", "desc_empty": "degraded",
            "duplicate_key": "not_loaded", "casing": "degraded",
            "desc_typed": "not_loaded", "desc_list": "not_loaded", "desc_map": "not_loaded",
            "yaml_unsupported": "unverified",
        },
        provenance=_cite(
            SKILLEVALUATOR, "project_roots", "user_roots", "walks_nested", "long_line_chars", "body_cap_lines",
            "body_cap_bytes", "placeholder_effects", "defect_effects",
        ),
    ),
    HostFacts(
        host="copilot-cli",
        display_name="GitHub Copilot CLI",
        prefix="COPILOT",
        verified_version="1.0.105",
        verified_date="2026-11-01",
        verified_source="closed source, cli-main.js inspected (SkillEvaluator 1.0.1 profile)",
        project_roots=(".github/skills", ".agents/skills", ".claude/skills"),
        user_roots=("~/.copilot/skills", "~/.agents/skills"),
        max_grouping_depth=3,
        listing_unit="utf16",
        listing_limit=1024,
        listing_effect="not_loaded",
        budget_kind="full_description_count",
        budget_effect="advisory",
        budget_max_skills=32,
        placeholder_effects={"arguments": "degraded", "skill_dir": "degraded"},
        defect_effects={
            "no_frontmatter": "not_loaded", "desc_missing": "degraded", "desc_empty": "degraded",
            "duplicate_key": "not_loaded", "casing": "degraded",
            "desc_typed": "not_loaded", "desc_list": "not_loaded", "desc_map": "not_loaded",
            "tab_indent": "not_loaded", "yaml_unsupported": "unverified",
        },
        provenance=_cite(
            SKILLEVALUATOR, "project_roots", "user_roots", "max_grouping_depth", "listing_unit", "listing_limit",
            "listing_effect", "budget_kind", "budget_effect", "budget_max_skills",
            "placeholder_effects", "defect_effects",
        ),
    ),
)

HOSTS: dict[str, HostFacts] = {facts.host: facts for facts in _HOSTS}
