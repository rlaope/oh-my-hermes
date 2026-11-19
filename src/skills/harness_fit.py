"""Offline check of how six agent hosts load one skill folder or a catalog of them.

`check_skill` and `check_catalog` read SKILL.md files and the files beside them
and say, per host, whether the skill loads, loads degraded, or is not loaded,
with one finding per reason and its fix. Nothing here runs a host, calls a
model, or opens a network connection: every verdict comes from the host facts
in `harness_fit_hosts`, which carry their own provenance.

The checks come in eight classes: the listing window (how much of one
description a host's skill list shows), the catalog budget (how much of the
whole folder the list holds), body read caps, the linked-file layout Hermes
lists, live placeholders, install roots, frontmatter and file defects, and
openings that two skills share. Placeholder tokens inside code spans or fenced
blocks are documentation, not live text, and never count.

Output schema `omh_skill_eval/v1`. `context_tokens=0` means the model context
is unknown, which selects each host's smallest budget.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .catalog_types import OMH_DESCRIPTION_PREFIX
from .harness_fit_hosts import HOSTS, HostFacts
from .skill_index import index_opening_collisions

SCHEMA = "omh_skill_eval/v1"
MANIFEST = "SKILL.md"

_EFFECT_RANK = {"advisory": 0, "degraded": 1, "not_loaded": 2}

# Hermes' index clip (agent/skill_utils.py `clip_skill_description` on main):
# over 60 characters, keep the words that end within the first 57, drop
# trailing separators, and append "...". Read from the source, re-expressed.
_HERMES_CUT_HEAD = 58
_HERMES_SUFFIX = "..."
_HERMES_TRAILING = re.compile(r"[\s.,;:\-\u2013\u2014(/]+$")
_LAST_WORD = re.compile(r"\s\S*$")

# A phrase that tells the model when to pick the skill.
_WHEN_CUE = re.compile(
    r"\b(?:use|load|invoke|pick)(?: (?:this|it|me))?(?: skill)? (?:when|whenever|if|for|to)\b"
    r"|\bwhen (?:the user|a user|you|asked|someone)\b"
    r"|\btrigger(?:s|ed)?\b",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
_PLACEHOLDERS = {
    "arguments": re.compile(r"(?<!\\)\$ARGUMENTS\b"),
    "skill_dir": re.compile(r"(?<!\\)\$\{?CLAUDE_SKILL_DIR\b\}?"),
    "positional": re.compile(r"(?<![\\\w$])\$\d"),
}
_PLACEHOLDER_TEXT = {
    "arguments": ("$ARGUMENTS", "Describe the expected input in words, or keep the token inside a code span."),
    "skill_dir": ("${CLAUDE_SKILL_DIR}", "Refer to files by paths relative to SKILL.md."),
    "positional": (
        "a $<digit> token",
        "Write amounts as USD 4.00 (or put the token in a code span); $<digit> is an argument slot here.",
    ),
}
_PLACEHOLDER_OUTCOME = {
    "arguments": "does not substitute $ARGUMENTS, so the model reads the literal token",
    "skill_dir": "does not substitute ${CLAUDE_SKILL_DIR}, so the model reads the literal token",
    "positional": "treats $<digit> as an argument slot, so text like $4.00 changes when the skill runs with arguments",
}

_DEFECTS = {
    "no_skill_md": ("NO_SKILL_MD", "No SKILL.md in the folder.", "Add SKILL.md."),
    "no_frontmatter": (
        "NO_FRONTMATTER", "SKILL.md has no closed frontmatter block.",
        "Open SKILL.md with a --- block holding name and description.",
    ),
    "name_missing": ("NAME_MISSING", "Frontmatter has no name.", "Add a name equal to the folder name."),
    "desc_missing": (
        "DESC_MISSING", "Frontmatter has no string description.", "Add a one-line string description.",
    ),
    "desc_empty": ("DESC_EMPTY", "The description is empty.", "Write a one-line description."),
    "duplicate_key": ("DUPLICATE_KEY", "Frontmatter repeats a key.", "Keep one copy of each key."),
    "casing": (
        "CASING", "The manifest is not spelled SKILL.md.", "Rename the file to SKILL.md, uppercase.",
    ),
    "symlink": (
        "SYMLINK", "SKILL.md is a symlink.",
        "Copy SKILL.md into the folder; a symlinked folder is fine where a symlinked file is not.",
    ),
}


@dataclass(frozen=True)
class _Skill:
    path: Path
    folder: str
    manifest: str | None
    symlinked: bool
    text: str
    raw_bytes: int
    has_frontmatter: bool
    keys: tuple[str, ...]
    fields: Mapping[str, object]
    body: str
    body_offset: int

    @property
    def name(self) -> str:
        value = self.fields.get("name")
        return value.strip() if isinstance(value, str) and value.strip() else self.folder

    @property
    def description(self) -> str | None:
        value = self.fields.get("description")
        return value.strip() if isinstance(value, str) else None


@dataclass(frozen=True)
class _Catalog:
    folder: str
    skills: tuple[_Skill, ...]

    @property
    def size(self) -> int:
        return len(self.skills)

    @property
    def desc_chars(self) -> int:
        return sum(len(skill.description or "") for skill in self.skills)

    @property
    def desc_bytes(self) -> int:
        return sum(len((skill.description or "").encode("utf-8")) for skill in self.skills)

    def as_dict(self) -> dict[str, object]:
        return {"size": self.size, "desc_chars": self.desc_chars, "folder": self.folder}


# --- reading ---------------------------------------------------------------

def _scalar(lines: list[str], index: int, value: str) -> tuple[object, int]:
    """One top-level frontmatter value starting at `lines[index]`; returns (value, next index)."""
    following = index + 1
    continuation: list[str] = []
    while following < len(lines) and (lines[following][:1] in (" ", "\t") or not lines[following].strip()):
        continuation.append(lines[following])
        following += 1
    while continuation and not continuation[-1].strip():
        continuation.pop()
        following -= 1
    value = value.strip()
    if value[:1] in ("|", ">"):
        parts = [line.strip() for line in continuation]
        return ("\n" if value[0] == "|" else " ").join(parts).strip(), following
    if not value:
        return (None if not continuation else object()), following
    if value[0] == '"':
        joined = " ".join([value] + [line.strip() for line in continuation])
        try:
            return json.loads(joined), following
        except json.JSONDecodeError:
            return joined.strip('"'), following
    if value[0] == "'":
        joined = " ".join([value] + [line.strip() for line in continuation])
        return joined[1:-1].replace("''", "'") if joined.endswith("'") else joined[1:], following
    if value[0] in ("[", "{"):
        return object(), following
    return " ".join([value] + [line.strip() for line in continuation]), following


def _frontmatter(text: str) -> tuple[bool, tuple[str, ...], dict[str, object], str, int]:
    """(closed block found, keys in order, top-level fields, body, file lines before the body)."""
    lines = text.removeprefix("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return False, (), {}, text, 0
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return False, (), {}, text, 0
    block = lines[1:end]
    keys: list[str] = []
    fields: dict[str, object] = {}
    index = 0
    while index < len(block):
        match = re.match(r"^([A-Za-z0-9_][\w.-]*)\s*:(.*)$", block[index])
        if match is None:
            index += 1
            continue
        keys.append(match.group(1))
        value, index = _scalar(block, index, match.group(2))
        fields[match.group(1)] = value
    return True, tuple(keys), fields, "\n".join(lines[end + 1:]), end + 1


def _read_skill(path: Path) -> _Skill:
    try:
        names = sorted(os.listdir(path))
    except OSError:
        names = []
    manifest = MANIFEST if MANIFEST in names else next((name for name in names if name.lower() == "skill.md"), None)
    text, raw_bytes, symlinked = "", 0, False
    if manifest is not None:
        manifest_path = path / manifest
        symlinked = manifest_path.is_symlink()
        try:
            raw = manifest_path.read_bytes()
        except OSError:
            raw = b""
        raw_bytes = len(raw)
        text = raw.decode("utf-8", errors="replace")
    has_frontmatter, keys, fields, body, offset = _frontmatter(text)
    return _Skill(path, path.name, manifest, symlinked, text, raw_bytes, has_frontmatter, keys, fields, body, offset)


def _has_manifest(folder: Path) -> bool:
    try:
        return any(name.lower() == "skill.md" for name in os.listdir(folder))
    except OSError:
        return False


def _catalog(folder: Path) -> _Catalog:
    try:
        children = sorted(child for child in folder.iterdir() if child.is_dir() and not child.name.startswith("."))
    except OSError:
        children = []
    return _Catalog(str(folder), tuple(_read_skill(child) for child in children if _has_manifest(child)))


def _text_files(skill: _Skill) -> Iterable[tuple[str, str]]:
    for directory, dirs, files in os.walk(skill.path):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            path = Path(directory, name)
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if b"\0" in raw:
                continue
            try:
                yield path.relative_to(skill.path).as_posix(), raw.decode("utf-8")
            except UnicodeDecodeError:
                continue


# --- measures ----------------------------------------------------------------

def hermes_listing(description: str) -> str:
    """The description text Hermes main shows in its skill index."""
    if len(description) <= 60:
        return description
    head = description[:_HERMES_CUT_HEAD]
    boundary = _LAST_WORD.search(head)
    if boundary is None or boundary.start() == 0:
        return description[:57] + _HERMES_SUFFIX
    return _HERMES_TRAILING.sub("", head[: boundary.start()]) + _HERMES_SUFFIX


def _hermes_window_hides_when(description: str) -> tuple[bool, str]:
    """(nothing in the visible window says when to use the skill, visible text)."""
    listed = hermes_listing(description)
    if listed == description:
        return False, listed
    visible = listed.removesuffix(_HERMES_SUFFIX)
    cue = _WHEN_CUE.search(description)
    if cue is not None and cue.end() <= len(visible):
        return False, listed
    if description.startswith(OMH_DESCRIPTION_PREFIX) and ":" in description:
        situation = description[: description.index(":")]
        if visible.startswith(situation):
            return False, listed
    return True, listed


def _live_text(body: str, offset: int = 0) -> list[tuple[int, str]]:
    """Body lines with fenced blocks dropped and code spans blanked, numbered as SKILL.md lines."""
    live: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(body.splitlines(), offset + 1):
        opener = _FENCE.match(line)
        if fence is not None:
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
                fence = None
            continue
        if opener:
            fence = opener.group(1)
            continue
        live.append((number, _CODE_SPAN.sub(" ", line)))
    return live


def _wide_chars(text: str) -> int:
    return sum(1 for char in text if unicodedata.east_asian_width(char) in ("W", "F"))


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _list_budget(facts: HostFacts, context_tokens: int) -> int:
    if context_tokens <= 0:
        return facts.budget_unknown_context or 0
    tokens = context_tokens * (facts.budget_context_share or 0)
    if facts.budget_max_tokens is not None:
        tokens = min(tokens, facts.budget_max_tokens)
    return int(tokens * (facts.budget_per_token or 0))


def _read_cap(facts: HostFacts, context_tokens: int) -> int:
    for below, cap in facts.read_caps:
        if below is None or context_tokens < below:
            return cap
    return facts.read_caps[-1][1]


def _linked(facts: HostFacts, relative: str) -> bool:
    parts = relative.split("/")
    for folder, globs, recursive in facts.linked_files:
        if parts[0] != folder or len(parts) < 2 or (not recursive and len(parts) != 2):
            continue
        if any(fnmatch.fnmatchcase(parts[-1], pattern) for pattern in globs):
            return True
    return False


def _install_root(skill_dir: Path, install_root: str | None) -> str | None:
    if install_root is not None:
        return install_root.strip().rstrip("/")
    parent = skill_dir.resolve().parent
    try:
        relative = parent.relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        relative = None
    user_roots = {root for facts in HOSTS.values() for root in facts.user_roots}
    if relative is not None and f"~/{relative}" in user_roots:
        return f"~/{relative}"
    # Only dotted roots are inferred from the path: a bare `skills/` folder is
    # also the usual name of a source pack, so it counts as OpenClaw's
    # workspace root only when the caller says so.
    project_roots = {root for facts in HOSTS.values() for root in facts.project_roots if root.startswith(".")}
    posix = parent.as_posix()
    matches = [root for root in project_roots if posix == root or posix.endswith("/" + root)]
    return max(matches, key=len) if matches else None


# --- findings ----------------------------------------------------------------

def _finding(finding_id: str, effect: str, message: str, fix: str) -> dict[str, str]:
    return {"id": finding_id, "effect": effect, "message": message, "fix": fix}


def _defects(skill: _Skill) -> list[str]:
    if skill.manifest is None:
        return ["no_skill_md"]
    found: list[str] = []
    if skill.manifest != MANIFEST:
        found.append("casing")
    if skill.symlinked:
        found.append("symlink")
    if not skill.has_frontmatter:
        found.append("no_frontmatter")
    name = skill.fields.get("name")
    if not isinstance(name, str) or not name.strip():
        found.append("name_missing")
    if skill.description is None:
        found.append("desc_missing")
    elif not skill.description:
        found.append("desc_empty")
    if len(skill.keys) != len(set(skill.keys)):
        found.append("duplicate_key")
    return found


def _host_findings(
    facts: HostFacts, skill: _Skill, catalog: _Catalog, context_tokens: int, root: str | None,
    defects: list[str], live: list[tuple[int, str]], files: list[tuple[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    name = facts.display_name
    prefix = facts.prefix
    findings: list[dict[str, str]] = []

    root_state = "not_checked"
    if root is not None:
        scanned = root in facts.project_roots or root in facts.user_roots
        root_state = "scanned" if scanned else "not_scanned"
        if not scanned:
            findings.append(_finding(
                f"{prefix}_ROOT", "not_loaded",
                f"{name} does not scan {root}; it reads {', '.join(facts.project_roots + facts.user_roots)}.",
                f"Install the skill under one of the roots {name} scans.",
            ))
        elif facts.project_roots_need_trust and root in facts.project_roots:
            findings.append(_finding(
                f"{prefix}_ROOT_TRUST", "advisory",
                f"{name} lists skills under {root} only after the repository is trusted.",
                "Trust the repository in Hermes, or install the skill under ~/.hermes/skills.",
            ))

    if "no_skill_md" in defects:
        findings.append(_finding(f"{prefix}_NO_SKILL_MD", "not_loaded", *_DEFECTS["no_skill_md"][1:]))
        return root_state, findings
    for defect in defects:
        effect = facts.defect_effects.get(defect)
        if effect is not None:
            suffix, message, fix = _DEFECTS[defect]
            findings.append(_finding(f"{prefix}_{suffix}", effect, f"{name}: {message}", fix))

    description = skill.description or ""
    over_catalog_cap = facts.budget_kind == "skill_or_char_cap" and (
        catalog.size > (facts.budget_max_skills or 0) or catalog.desc_chars > (facts.budget_max_chars or 0)
    )
    window_id, effect = f"{prefix}_DESC_WINDOW", facts.listing_effect or "advisory"
    if facts.listing_unit == "hermes_clip" and description:
        hidden, listed = _hermes_window_hides_when(description)
        if hidden:
            findings.append(_finding(
                window_id, effect,
                f"{name} lists this skill as {listed!r}: neither the situation nor a 'use when' cue fits in it.",
                "Open the description with the situation it serves, short enough to end inside 57 characters.",
            ))
    elif facts.listing_unit == "codepoints" and len(description) > (facts.listing_limit or 0):
        findings.append(_finding(
            window_id, effect,
            f"{name} cuts the {len(description):,}-character description at {facts.listing_limit:,}.",
            f"Cut the description by {len(description) - (facts.listing_limit or 0):,} characters.",
        ))
    elif facts.listing_unit == "codepoints_with_when_to_use":
        extra = skill.fields.get("when_to_use")
        listed_chars = len(description) + (len(extra) if isinstance(extra, str) else 0)
        if listed_chars > (facts.listing_limit or 0):
            findings.append(_finding(
                window_id, effect,
                f"{name} cuts description plus when_to_use ({listed_chars:,} characters) at {facts.listing_limit:,}.",
                f"Keep description and when_to_use within {facts.listing_limit:,} characters together.",
            ))
    elif facts.listing_unit == "utf16" and _utf16_units(description) > (facts.listing_limit or 0):
        findings.append(_finding(
            window_id, effect,
            f"{name} drops a skill whose description is over {facts.listing_limit:,} UTF-16 units "
            f"(this one is {_utf16_units(description):,}).",
            f"Cut the description to {facts.listing_limit:,} UTF-16 units or fewer (an emoji counts 2).",
        ))
    elif facts.listing_unit == "compact" and over_catalog_cap and len(description) > (facts.listing_limit or 0):
        findings.append(_finding(
            window_id, effect,
            f"Over {name}'s catalog cap, descriptions are cut to {facts.listing_limit} characters; this one is "
            f"{len(description):,}.",
            f"Keep the description within {facts.listing_limit} characters, situation first.",
        ))

    budget_id = f"{prefix}_LIST_BUDGET"
    if facts.budget_kind == "context_share":
        budget = _list_budget(facts, context_tokens)
        used = catalog.desc_bytes if facts.budget_unit == "bytes" else catalog.desc_chars
        if used > budget:
            basis = "unknown context" if context_tokens <= 0 else f"{context_tokens:,}-token context"
            findings.append(_finding(
                budget_id, facts.budget_effect or "degraded",
                f"{catalog.size} skills in this folder carry {used:,} description {facts.budget_unit}; {name}'s "
                f"skill list holds about {budget:,} at {basis}, so descriptions are shortened or dropped.",
                "Shorten every description in the folder (situation first) or install fewer skills there.",
            ))
    elif over_catalog_cap:
        findings.append(_finding(
            budget_id, facts.budget_effect or "advisory",
            f"{catalog.size} skills / {catalog.desc_chars:,} description characters: past {facts.budget_max_skills} "
            f"skills or {facts.budget_max_chars:,} characters {name} leaves some skills out of its list.",
            "Shorten descriptions or install fewer skills in one folder.",
        ))
    elif facts.budget_kind == "full_description_count" and catalog.size > (facts.budget_max_skills or 0):
        findings.append(_finding(
            budget_id, facts.budget_effect or "advisory",
            f"{catalog.size} skills here: {name} shows full descriptions for the first {facts.budget_max_skills} "
            "only and lists the rest by name.",
            f"Keep {facts.budget_max_skills} or fewer skills in one place, or give each a self-explaining name.",
        ))

    if facts.view_budget_chars is not None:
        view_chars = len(json.dumps(skill.text, ensure_ascii=False))
        if view_chars > facts.view_budget_chars:
            findings.append(_finding(
                f"{prefix}_VIEW_BUDGET", "degraded",
                f"Loading the skill returns about {view_chars:,} characters, over {name}'s "
                f"{facts.view_budget_chars:,}-character tool-result budget, so the model gets a preview.",
                "Move detail out of SKILL.md into references/ files.",
            ))
    if facts.read_caps:
        weighted = len(skill.text) + ((facts.read_wide_weight or 1) - 1) * _wide_chars(skill.text)
        weighted += facts.read_overhead_chars or 0
        cap = _read_cap(facts, context_tokens)
        if weighted > cap:
            basis = "unknown context" if context_tokens <= 0 else f"{context_tokens:,}-token context"
            findings.append(_finding(
                f"{prefix}_READ_CAP", "degraded",
                f"SKILL.md reads as {weighted:,} weighted characters (wide characters count "
                f"{facts.read_wide_weight}); {name} caps a skill read at {cap:,} at {basis}.",
                "Keep SKILL.md within about 15,000 characters and move detail into references/ files.",
            ))
    if facts.long_line_chars is not None:
        # SKILL.md itself arrives through the skill tool, which cuts whole
        # output, not lines; the per-line cut is the read tool's.
        long_files = sorted({relative for relative, content in files if relative != skill.manifest
                             and any(len(line) > facts.long_line_chars for line in content.splitlines())})
        if long_files:
            findings.append(_finding(
                f"{prefix}_LONG_LINES", "advisory",
                f"{name} cuts lines over {facts.long_line_chars:,} characters when the model reads them: "
                f"{', '.join(long_files)}.",
                f"Wrap long lines under {facts.long_line_chars:,} characters.",
            ))
    if facts.file_cap_bytes is not None and skill.raw_bytes > facts.file_cap_bytes:
        findings.append(_finding(
            f"{prefix}_FILE_CAP", "not_loaded",
            f"{name} rejects a SKILL.md over {facts.file_cap_bytes:,} bytes (this one is {skill.raw_bytes:,}).",
            "Move detail into references/ files.",
        ))

    if facts.linked_files:
        # A file the skill view leaves out is still reachable when SKILL.md
        # names its path. A folder of its own (toolkit/) counts as named when
        # SKILL.md names any path inside it, because that entry file can lead
        # to the rest; a stray file inside a listed folder must be named itself.
        listed_folders = {folder for folder, _globs, _recursive in facts.linked_files}
        unnamed: dict[str, int] = {}
        for relative in _all_files(skill):
            if relative == skill.manifest or _linked(facts, relative) or relative in skill.text:
                continue
            top = relative.split("/")[0]
            if "/" in relative and top not in listed_folders and f"{top}/" in skill.text:
                continue
            group = f"{top}/" if "/" in relative else top
            unnamed[group] = unnamed.get(group, 0) + 1
        if unnamed:
            listing = ", ".join(f"{group} ({count})" if group.endswith("/") else group
                                for group, count in sorted(unnamed.items()))
            folders = ", ".join(folder for folder, _globs, _recursive in facts.linked_files)
            findings.append(_finding(
                f"{prefix}_LINKED_LAYOUT", "advisory",
                f"{sum(unnamed.values())} files sit outside what {name} lists ({folders}) and SKILL.md does not "
                f"name their path: {listing}.",
                "Name the folder's path in SKILL.md where it is used, or move the files into a listed folder.",
            ))

    for token_class, effect in sorted(facts.placeholder_effects.items()):
        lines = [number for number, line in live if _PLACEHOLDERS[token_class].search(line)]
        if lines:
            token, fix = _PLACEHOLDER_TEXT[token_class]
            shown = ", ".join(str(number) for number in lines[:5]) + (", ..." if len(lines) > 5 else "")
            findings.append(_finding(
                f"{prefix}_PLACEHOLDER_{token_class.upper()}", effect,
                f"{name} {_PLACEHOLDER_OUTCOME[token_class]}: {token} appears in prose on SKILL.md line {shown}.",
                fix,
            ))
    return root_state, findings


def _all_files(skill: _Skill) -> Iterable[str]:
    for directory, dirs, files in os.walk(skill.path):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for name in sorted(files):
            if not name.startswith("."):
                yield Path(directory, name).relative_to(skill.path).as_posix()


def _status(findings: list[dict[str, str]]) -> str:
    worst = max((_EFFECT_RANK[item["effect"]] for item in findings), default=0)
    return {0: "loads", 1: "degraded", 2: "not_loaded"}[worst]


def _static(skill: _Skill, defects: list[str], selected: list[HostFacts]) -> list[dict[str, str]]:
    def worst(effects: Iterable[str | None]) -> str:
        ranked = [effect for effect in effects if effect is not None]
        return max(ranked, key=_EFFECT_RANK.__getitem__) if ranked else "advisory"

    static: list[dict[str, str]] = []
    for defect in defects:
        suffix, message, fix = _DEFECTS[defect]
        effect = "not_loaded" if defect == "no_skill_md" else worst(f.defect_effects.get(defect) for f in selected)
        static.append(_finding(f"STATIC_{suffix}", effect, message, fix))
    name = skill.fields.get("name")
    if isinstance(name, str) and name.strip() and name.strip() != skill.folder:
        static.append(_finding(
            "STATIC_NAME_MISMATCH", "advisory",
            f"The name {name.strip()!r} differs from the folder {skill.folder!r}.",
            "Make the name equal to the folder name.",
        ))
    caps = [facts.file_cap_bytes for facts in HOSTS.values() if facts.file_cap_bytes is not None]
    if skill.manifest is not None and caps and skill.raw_bytes > min(caps):
        static.append(_finding(
            "STATIC_SIZE", worst("not_loaded" for f in selected if f.file_cap_bytes and skill.raw_bytes > f.file_cap_bytes),
            f"SKILL.md is {skill.raw_bytes:,} bytes, over the smallest host file cap ({min(caps):,}).",
            "Move detail into references/ files.",
        ))
    return static


def _overlap(catalog: _Catalog) -> list[dict[str, object]]:
    pairs = [(skill.name, skill.description) for skill in catalog.skills if skill.description]
    groups = index_opening_collisions(pairs)
    return [{"opening": opening, "skills": sorted(skills)} for opening, skills in sorted(groups.items())]


def _selected(hosts: Iterable[str] | None) -> list[HostFacts]:
    names = list(HOSTS) if hosts is None else list(hosts)
    unknown = [name for name in names if name not in HOSTS]
    if unknown:
        raise ValueError(f"unknown host(s) {', '.join(unknown)}; known: {', '.join(HOSTS)}")
    return [HOSTS[name] for name in names]


def _evaluate(
    skill: _Skill, catalog: _Catalog, overlap: list[dict[str, object]], selected: list[HostFacts],
    context_tokens: int, install_root: str | None,
) -> dict[str, object]:
    defects = _defects(skill)
    live = _live_text(skill.body, skill.body_offset)
    needs_files = any(facts.long_line_chars is not None for facts in selected)
    files = list(_text_files(skill)) if needs_files and skill.manifest else []
    root = _install_root(skill.path, install_root)
    rows: list[dict[str, object]] = []
    for facts in selected:
        root_state, findings = _host_findings(facts, skill, catalog, context_tokens, root, defects, live, files)
        rows.append({
            "host": facts.host,
            "display_name": facts.display_name,
            "verified": {"version": facts.verified_version, "date": facts.verified_date,
                         "source": facts.verified_source},
            "root": root_state,
            "status": _status(findings),
            "findings": findings,
        })
    return {
        "schema": SCHEMA,
        "target": str(skill.path),
        "hosts": rows,
        "catalog": catalog.as_dict(),
        "static": _static(skill, defects, selected),
        "overlap": [group for group in overlap if skill.name in group["skills"]],
        "summary": {
            "not_loaded": sum(1 for row in rows if row["status"] == "not_loaded"),
            "degraded": sum(1 for row in rows if row["status"] == "degraded"),
        },
    }


def check_skill(
    skill_dir: Path, *, hosts: Iterable[str] | None = None, context_tokens: int = 0,
    install_root: str | None = None,
) -> dict[str, object]:
    """Per-host verdict for one skill folder; its parent folder is the catalog it is listed in.

    `install_root` names the root the skill is installed under (`.claude/skills`,
    `~/.hermes/skills`, `skills`); by default it is read off a dotted parent
    path, and otherwise roots are reported `not_checked`.
    """
    skill_dir = Path(skill_dir)
    selected = _selected(hosts)
    catalog = _catalog(skill_dir.parent)
    skill = next((item for item in catalog.skills if item.path.name == skill_dir.name), None) or _read_skill(skill_dir)
    return _evaluate(skill, catalog, _overlap(catalog), selected, context_tokens, install_root)


def check_catalog(
    root: Path, *, hosts: Iterable[str] | None = None, context_tokens: int = 0,
    install_root: str | None = None,
) -> dict[str, object]:
    """Per-skill verdicts for every skill folder directly under `root`, plus catalog totals."""
    root = Path(root)
    selected = _selected(hosts)
    catalog = _catalog(root)
    overlap = _overlap(catalog)
    if install_root is None:
        probe = catalog.skills[0].path if catalog.skills else root / "_"
        install_root = _install_root(probe, None)
    results = [_evaluate(skill, catalog, overlap, selected, context_tokens, install_root) for skill in catalog.skills]
    counts: dict[str, int] = {}
    for result in results:
        for row in result["hosts"]:
            for finding in row["findings"]:
                counts[finding["id"]] = counts.get(finding["id"], 0) + 1
        for finding in result["static"]:
            counts[finding["id"]] = counts.get(finding["id"], 0) + 1
    return {
        "schema": SCHEMA,
        "target": str(root),
        "catalog": catalog.as_dict(),
        "skills": results,
        "overlap": overlap,
        "summary": {
            "skills": len(results),
            "not_loaded": sum(r["summary"]["not_loaded"] for r in results),
            "degraded": sum(r["summary"]["degraded"] for r in results),
            "findings": dict(sorted(counts.items())),
        },
    }
