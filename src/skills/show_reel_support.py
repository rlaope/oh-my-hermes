"""Read the reviewed, fixed companion inventory via package resources, never cwd."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json

from .support_files import SkillSupportTemplate

SHOW_REEL_RESOURCES = (
    "README.md", "LICENSE.upstream", "upstream-manifest.json",
    "assets/engine/engine.js", "assets/engine/fx.js", "assets/engine/scenes.js", "assets/engine/index.html",
    "scripts/new_project.py", "scripts/render.mjs", "scripts/font-coverage.mjs",
    "scripts/timeline.py", "scripts/synth_music.py", "scripts/mix.py",
    "scripts/motion_check.py", "scripts/qa_check.py",
    "scripts/contact_sheet.py", "scripts/finish.py", "scripts/preflight.py",
    "scripts/prep_images.py", "scripts/music_tools.py", "scripts/tools/cutout.swift",
    "scripts/eleven.py", "scripts/narrate.py", "scripts/codex_ref_image.sh", "assets/sfx_presets.json",
    "examples/timing.json", "examples/music-spec.json", "examples/README.md",
)

REVISION = "64521220a2f8e91cb9894400c48c15b7f45205d6"
UPSTREAM_SOURCES = {
    "LICENSE": "d20cf1fae030dacd0a5775ca23e0d3e4a4abf677e1a6f0f8ef34603cc20d7f53",
    "SKILL.md": "1e74898ee151d8b117b54bb0b2f5a7bdb0bbe9ee345781015b36e04dde70dd4c",
    "assets/engine/index.html": "4140bc2a6be1bdc00cfab85e4d4e1bb838be9845c9898ec1fede3e71238641ae",
    "assets/engine/engine.js": "b595f361e0e1f661f2cbe816326c54a893c4c668492120772c917e01fa1b2bb0",
    "assets/engine/fx.js": "cf028c72328aacc6a6a307538fa3f3668e6890b063f021b915dc061aa92c6f1d",
    "assets/engine/scenes.js": "70ba3bcb53f4d061cd0e5789bea154bbf17901628fa5202d1b5c61954b14607b",
    "scripts/render.mjs": "52ac114394256491721b3c86fdd7a7eb42796dd350701d38688382827a18d3a7",
    "scripts/timeline.py": "95e872e1fb23f1509e8e60b64294c275260ced1aeaa27f66e5ba3cd00a6f8d77",
    "scripts/synth_music.py": "bd035ddeee3790e0990cdd4841942fd92fca4ba6533487427cd6ce78d625a4f7",
    "scripts/mix.py": "569f5b2e285dd7239f20c278e274119ec5b685c2906a4dc270c161cc0e686f7d",
    "scripts/motion_check.py": "d2feb0d8dba77a1bd389507faf35cb2c761977c10565ef45b108de99ee2dc7c1",
    "scripts/qa_check.py": "0765be750b043e0d99d544f52367ab512f04b391988f3f05faa47b0d1ebc5c15",
    "scripts/new_project.py": "b43f42fca4ba4ccd3b69c5d5372199b102b36de0f2dc496c2ad9f4d425200023",
    "scripts/contact_sheet.py": "212c64f25800ed3d1ce51d06d1efda3b8270a9f8c91f8496e2824fb3d70a814b",
    "scripts/finish.py": "a2218856972c2c56de1d8bcd1e105417e71a2f51a9c75bf595724690967ba54b",
    "scripts/preflight.py": "18b933e6e2ecb7fb54b2a1908ac9529555ad68bb129f7e8c8fe0ce7084b1c0ec",
    "scripts/prep_images.py": "7fa0534b90cbb801ed0bb2d5d5eb0a5e7ad69816eb91bf4d0b241ee8b2e3897b",
    "scripts/music_tools.py": "297e12e8ffd7dfc667134b27a97c2a67770a754fe1ff1048a882dc90ccabc4a5",
    "scripts/tools/cutout.swift": "292e252c05bd2775945fa6a56b8734436aa6fa6323e9a33e79e645e5ba050729",
    "scripts/eleven.py": "ad61f1a5431a18d059202b999b50c7b16826a8b872fcef05b975047787985ce1",
    "scripts/narrate.py": "7148e331b3cc66c5af4ff0d3515f21b0f76cda7f7138fc188c32bd4ad88b2dd3",
    "scripts/codex_ref_image.sh": "84d9c732e11f38ab2d4dbb5dac77e8de2dbdb05be08cbe816c5dcef913e48484",
    "assets/sfx_presets.json": "4d6459d9728bfb52a1499bcd3b0f51d3989d98e723f8fbe263557ad9d23355d2",
    "references/techniques.md": "bb6f32abb1f557b58958748e0461b57f2da117a1ffc360e5148e56a418976cc8",
    "references/design.md": "d4e8ff5a84db3658e6d070dd1c5df62e60c83bcd478c794727147f339942db4f",
    "references/engine.md": "2639e9fdb49a846bb18d1a4382890f228e5a85f3123637588d7e21668864fcf6",
    "references/audio.md": "671d920b4ccde7444a686cc32a1e8d860d914b06487138c69faf8b86fe32c885",
    "references/qa.md": "bb5cbfaaba8ed87a8cdcbb1d92566760ee872dbdfe5605198fa81bb033262727",
    "references/brief.md": "8838231f3c5c117bd5f428e3691e13b972fd4c76390b92a6d8e91b283780fd7b",
    "references/story.md": "83aa6ce6d962ae736bc35a032d327c77490b4fbba536f2d74e9fa2fceeef15a0",
    "references/images.md": "8c16d6c61f7ccae5fbc98758da65728ca470da31ad84d3ffb76097cce2b084b1",
}
DERIVATIONS = {
    "LICENSE.upstream": ["LICENSE"],
    "assets/engine/engine.js": ["assets/engine/engine.js"],
    "assets/engine/fx.js": ["assets/engine/fx.js"],
    "assets/engine/scenes.js": ["assets/engine/scenes.js"],
    "assets/engine/index.html": ["assets/engine/index.html"],
    "scripts/new_project.py": ["scripts/new_project.py"],
    "scripts/render.mjs": ["scripts/render.mjs"],
    "scripts/timeline.py": ["scripts/timeline.py"],
    "scripts/synth_music.py": ["scripts/synth_music.py"],
    "scripts/mix.py": ["scripts/mix.py"],
    "scripts/motion_check.py": ["scripts/motion_check.py"],
    "scripts/qa_check.py": ["scripts/qa_check.py"],
    "scripts/contact_sheet.py": ["scripts/contact_sheet.py"],
    "scripts/finish.py": ["scripts/finish.py"],
    "scripts/preflight.py": ["scripts/preflight.py"],
    "scripts/prep_images.py": ["scripts/prep_images.py"],
    "scripts/music_tools.py": ["scripts/music_tools.py"],
    "scripts/tools/cutout.swift": ["scripts/tools/cutout.swift"],
    "scripts/eleven.py": ["scripts/eleven.py"],
    "scripts/narrate.py": ["scripts/narrate.py"],
    "scripts/codex_ref_image.sh": ["scripts/codex_ref_image.sh"],
    "assets/sfx_presets.json": ["assets/sfx_presets.json"],
}
# What each derived file changes from its upstream source; the file's own header says the same.
MODIFICATIONS = {
    "LICENSE.upstream": ("unmodified_license", "License verbatim"),
    "assets/engine/engine.js": ("upstream_with_notice", "Upstream bytes unmodified below a prepended attribution notice"),
    "assets/engine/fx.js": ("upstream_with_notice", "Upstream bytes unmodified below a prepended attribution notice"),
    "assets/engine/scenes.js": ("upstream_with_notice", "Upstream bytes unmodified below a prepended attribution notice"),
    "assets/engine/index.html": ("modified_derivative", "fonts.css link moved after the inline style so explicit-font tokens win; attribution notice"),
    "scripts/new_project.py": ("modified_derivative", "Upstream folder layout and engine template; explicit local fonts with family/weight read from the font, no download or npm setup, existing project refused"),
    "scripts/render.mjs": ("modified_derivative", "Puppeteer adapter with a realpath allowlist server; keeps upstream --scale/--sub/--shutter/--crf 16/--preset/--from/--to/--every; serial capture piped to FFmpeg with frame-clock throttling off; project.json cuts keep sub-frame samples inside each shot"),
    "scripts/timeline.py": ("modified_derivative", "Explicit cue graph plus the upstream script.json composition with a stdlib envelope; music.dropN cues from the analysis"),
    "scripts/synth_music.py": ("modified_derivative", "Seeded section score and SFX rewritten for stdlib PCM"),
    "scripts/mix.py": ("modified_derivative", "Cue placement, speech ducking and gain automation adapted to stdlib PCM; required tracks fail closed; reports SFX buried under the bed"),
    "scripts/motion_check.py": ("modified_derivative", "Native-fps change-area stills, cuts and opposing-pair flashes with general/kinetic profiles, end-card exclusion, reference comparison and authored intentional holds; stdlib"),
    "scripts/qa_check.py": ("modified_derivative", "Audio-mode-aware decode and measurements; H.264 level ceiling and macOS hardware-decode policy keys; no STT client"),
    "scripts/contact_sheet.py": ("modified_derivative", "English messages, tool paths overridable (default from PATH) and explicit --label-font, FFmpeg tile path without Pillow, -fps_mode for FFmpeg 8+"),
    "scripts/finish.py": ("modified_derivative", "English messages and suffixes, tool paths overridable (default from PATH), outputs must be new, failing spec exits 1, 1080p share copy pinned to H.264 level 4.2"),
    "scripts/preflight.py": ("modified_derivative", "Local-only checks of the passed browser/dependency root, tool paths overridable (default from PATH) and key presence; no provider call, install or font scan"),
    "scripts/prep_images.py": ("modified_derivative", "English messages, Pillow prerequisite stated, cutout tool compiled into the output folder"),
    "scripts/music_tools.py": ("modified_derivative", "English messages, tool paths overridable (default from PATH), outputs must be new, numpy only for analyze/gap, synth_music event keys accepted, gap writes 16-bit PCM for mix.py; analyze takes a tempo hint and fit window and reports grid strength, alternatives and drops"),
    "scripts/tools/cutout.swift": ("modified_derivative", "Comments translated to English; attribution notice"),
    "scripts/eleven.py": ("modified_derivative", "Opt-in provider client run only by the user: key from ELEVENLABS_API_KEY only (no .env/home/config lookup), on curl stdin; no default voice or language; curl -q and --form-string; English messages; tool paths overridable (default from PATH)"),
    "scripts/narrate.py": ("modified_derivative", "Opt-in, user's own key: refuses without ELEVENLABS_API_KEY (exit 2), refuses (exit 2) without script.json voice or language, no sys.path edit, English messages"),
    "scripts/codex_ref_image.sh": ("modified_derivative", "Opt-in, user's own signed-in codex CLI; refuses without it (exit 2); prompt and messages in English"),
    "assets/sfx_presets.json": ("unmodified_upstream", "Upstream bytes verbatim (JSON allows no notice)"),
}
# Skill references translated from upstream: English translation of the complete text, cross-references
# renamed to references/craft-*.md, with an OMH header that maps upstream commands to this toolkit.
# techniques.md is split at T10 into two references to stay under the per-reference size ceiling.
CRAFT_REFERENCES = {
    "craft-workflow": "SKILL.md", "craft-brief": "references/brief.md", "craft-story": "references/story.md",
    "craft-audio": "references/audio.md", "craft-images": "references/images.md", "craft-design": "references/design.md",
    "craft-engine": "references/engine.md", "craft-techniques": "references/techniques.md",
    "craft-techniques-2": "references/techniques.md", "craft-qa": "references/qa.md",
}


def provenance_manifest():
    root = files("omh.skills").joinpath("show_reel_toolkit")
    entries = {}
    for name in SHOW_REEL_RESOURCES:
        if name == "upstream-manifest.json":
            continue
        source_paths = DERIVATIONS.get(name, [])
        classification, notice = MODIFICATIONS.get(name, ("original_omh", "Original OMH companion guidance/helper/example"))
        entries[name] = {
            "local_sha256": hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest(),
            "classification": classification,
            "upstream": [{"path": source, "sha256": UPSTREAM_SOURCES[source]} for source in source_paths],
            "modification_notice": notice,
            "license": "MIT",
        }
    craft = files("omh.skills").joinpath("show_reel_craft")
    references = {
        f"references/{name}.md": {
            "local_sha256": hashlib.sha256(craft.joinpath(f"{name}.md").read_bytes()).hexdigest(),
            "classification": "translated_derivative",
            "upstream": [{"path": source, "sha256": UPSTREAM_SOURCES[source]}],
            "modification_notice": f"Translated from upstream {source}@{REVISION[:9]}: complete English translation; cross-references renamed to references/craft-*.md; host install paths made placeholders; the default narration voice named by role; inline OMH notes where the locale/brief policy overrides an upstream default; OMH header",
            "license": "MIT",
        }
        for name, source in CRAFT_REFERENCES.items()
    }
    return {"schema": "omh_show_reel_provenance/v1", "repository": "https://github.com/revfactory/showreel", "revision": REVISION, "copyright": "Copyright (c) 2026 Minho Hwang (revfactory)", "license": "LICENSE.upstream", "self_hash": "excluded; outer native/portable inventory hashes this file", "files": entries, "references": references}


def show_reel_support_templates():
    root = files("omh.skills").joinpath("show_reel_toolkit")
    texts = {name: root.joinpath(name).read_text(encoding="utf-8") for name in SHOW_REEL_RESOURCES}
    provenance = json.loads(texts["upstream-manifest.json"])
    expected = set(SHOW_REEL_RESOURCES) - {"upstream-manifest.json"}
    if provenance.get("schema") != "omh_show_reel_provenance/v1" or set(provenance.get("files", {})) != expected:
        raise ValueError("invalid closed toolkit provenance inventory")
    for name in expected:
        if hashlib.sha256(texts[name].encode("utf-8")).hexdigest() != provenance["files"][name].get("local_sha256"):
            raise ValueError(f"toolkit provenance digest mismatch: {name}; regenerate from reviewed canonical resources")
    return [SkillSupportTemplate("show-reel", "toolkit/" + name, texts[name]) for name in SHOW_REEL_RESOURCES]
