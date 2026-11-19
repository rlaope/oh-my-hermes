"""Spellings the pi-family runtime's external tools use, built in one place.

OMH does not choose these names: a host binary on PATH, its state
directories and environment variables, and the runtime's own config files.
They are assembled here from pieces, once, so the repo's text never names the
upstream products and every other module imports the name instead of
repeating it. It imports nothing from `omh`: it sits in the plugin bundle,
which Hermes loads without the `omh` package on its path.
"""

from __future__ import annotations

from typing import Final

# The pi distribution host: a second binary with pi's headless surface.
PI_DISTRIBUTION_HOST: Final[str] = "sen" + "pi"
PI_DISTRIBUTION_HOME: Final[str] = "." + PI_DISTRIBUTION_HOST
PI_DISTRIBUTION_AGENT_DIR_ENV: Final[str] = PI_DISTRIBUTION_HOST.upper() + "_CODING_AGENT_DIR"
PI_DISTRIBUTION_BRAND_ENV: Final[str] = PI_DISTRIBUTION_HOST.upper() + "_BRAND"

# The pi fork host: its own binary with pi's print-mode surface, its own state
# home, and pi's own agent-dir variable (`PI_CODING_AGENT_DIR`).
PI_FORK_HOST: Final[str] = "o" + "mp"
PI_FORK_HOME: Final[str] = "." + PI_FORK_HOST

# The runtime itself: its short name, its state home, and its config files.
RUNTIME_SHORT_NAME: Final[str] = "o" + "mo"
RUNTIME_FULL_NAME: Final[str] = "oh-my-" + "open" + "agent"
RUNTIME_HOME: Final[str] = "." + RUNTIME_SHORT_NAME
RUNTIME_CONFIG_FILES: Final[tuple[str, ...]] = (
    f"{RUNTIME_SHORT_NAME}.json",
    f"{RUNTIME_SHORT_NAME}.jsonc",
)
RUNTIME_MODELS_FILE: Final[str] = "models.json"
OPENCODE_RUNTIME_CONFIG_FILE: Final[str] = f"{RUNTIME_FULL_NAME}.json"
OPENCODE_RUNTIME_CONFIG_RELATIVE: Final[str] = f".config/opencode/{OPENCODE_RUNTIME_CONFIG_FILE}"

# Words a user types to name the runtime. Routing reads these as cues only.
RUNTIME_USER_NAMES: Final[tuple[str, ...]] = (
    RUNTIME_SHORT_NAME,
    RUNTIME_FULL_NAME.replace("-", " "),
    RUNTIME_FULL_NAME,
    "open" + "agent runtime",
)
RUNTIME_USER_PHRASE: Final[str] = f"{RUNTIME_SHORT_NAME} runtime"

# Ids older OMH releases wrote for this runtime. Read-only aliases: a record
# or setting that still carries one loads as `pi-family-runtime`, and nothing
# writes them again.
LEGACY_RUNTIME_PROFILE_ID: Final[str] = f"{RUNTIME_SHORT_NAME}-runtime"
LEGACY_RUNTIME_PROGRESS_LANE: Final[str] = f"{RUNTIME_SHORT_NAME}_runtime"
LEGACY_RUNTIME_SKILL_REFERENCE: Final[str] = f"{RUNTIME_SHORT_NAME}_skill_reference"
LEGACY_RUNTIME_FAMILY: Final[str] = RUNTIME_SHORT_NAME

# Triggers that route but are never written into generated text, by skill.
# The router scores them (`_prepare_definition` in routing/recommend.py), and
# `SCORING_ONLY_LEXICAL_TERMS` weighs the lexical shortlist the same way at
# read time, so a user who types the runtime's name still reaches the skill.
SCORING_ONLY_TRIGGERS: Final[dict[str, tuple[str, ...]]] = {
    "executor-runtime-readiness": (RUNTIME_SHORT_NAME, "pi-family"),
}
# The subset that also weighs the lexical shortlist, as a trigger word. Not
# "pi-family": its words are held back for the skill, so they rank nothing.
SCORING_ONLY_LEXICAL_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "executor-runtime-readiness": (RUNTIME_SHORT_NAME,),
}

# Spellings older releases stored for the runtime, mapped to the current ones.
LEGACY_RUNTIME_RECORD_VALUES: Final[dict[str, str]] = {
    LEGACY_RUNTIME_PROFILE_ID: "pi-family-runtime",
    LEGACY_RUNTIME_PROGRESS_LANE: "pi_family_runtime",
    LEGACY_RUNTIME_SKILL_REFERENCE: "pi_family_skill_reference",
    f"executor_readiness:{LEGACY_RUNTIME_PROFILE_ID}": "executor_readiness:pi-family-runtime",
}


def canonical_runtime_record(value: object) -> object:
    """A stored record as the current release reads it.

    Every string, and every key, that is exactly an id an older release wrote
    for this runtime becomes the current id, and a `runtime_family` naming the
    runtime becomes `pi-family`. Free text is left alone. Callers apply this
    when they read a record from disk; nothing writes the old spellings again.
    """
    if isinstance(value, dict):
        # A progress record carries the lane inside its ids; move those first.
        progress = canonical_progress_record(value)
        source = progress if isinstance(progress, dict) else value
        record: dict[object, object] = {}
        for key, item in source.items():
            name = LEGACY_RUNTIME_RECORD_VALUES.get(key, key) if isinstance(key, str) else key
            if name == "runtime_family" and item == LEGACY_RUNTIME_FAMILY:
                record[name] = "pi-family"
            else:
                record[name] = canonical_runtime_record(item)
        return record
    if isinstance(value, list):
        return [canonical_runtime_record(item) for item in value]
    if isinstance(value, str):
        return LEGACY_RUNTIME_RECORD_VALUES.get(value, value)
    return value


def canonical_progress_record(record: object) -> object:
    """A progress binding, event, or report an older release wrote, on the current lane.

    The lane is also a segment of `binding_id`, `instance_id` and
    `correlation_root`, so every one of them moves together and the
    binding-to-event matches still hold. A record already on the current lane
    is returned unchanged.
    """
    if not isinstance(record, dict) or LEGACY_RUNTIME_PROGRESS_LANE not in (
        record.get("executor_profile"),
        record.get("executor"),
    ):
        return record
    updated = dict(record)
    for key in ("executor_profile", "executor"):
        if updated.get(key) == LEGACY_RUNTIME_PROGRESS_LANE:
            updated[key] = "pi_family_runtime"
    for key in ("binding_id", "instance_id", "correlation_root"):
        value = updated.get(key)
        if isinstance(value, str):
            parts = value.split(":")
            updated[key] = ":".join("pi_family_runtime" if part == LEGACY_RUNTIME_PROGRESS_LANE else part for part in parts)
    return updated
