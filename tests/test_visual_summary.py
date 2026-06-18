from __future__ import annotations

from copy import deepcopy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.paths import OmhPaths
from omh.visual_summary import (
    POSTER_ARCHETYPES,
    SOURCE_KINDS,
    build_visual_observation,
    build_visual_prompt_card,
    image_generation_setup_fallback,
    list_visual_observations,
    normalize_source_kind,
    parse_section_arg,
    resolve_aspect_ratio,
    resolve_poster_archetype,
    resolve_visual_format,
    validate_visual_observation,
    validate_visual_prompt_card,
    visual_wrapper_actions,
    write_visual_observation,
)


class VisualSummaryTests(unittest.TestCase):
    def test_structured_card_contains_required_prompt_contract(self) -> None:
        card = build_visual_prompt_card(
            kind="PR",
            headline="PR Review Card",
            audience="reviewers",
            language="bilingual",
            sections=[
                {"role": "summary", "title": "What changed", "image_text": "Setup copy is safer and clearer."},
                {"role": "risk", "title": "Review focus", "image_text": "Check install claims against tests."},
            ],
            capability_state="connected",
            created_at="2026-06-18T01:13:25Z",
        )

        self.assertEqual(card["schema_version"], "visual_prompt_card/v1")
        self.assertEqual(card["source_kind"], "github_pr")
        self.assertEqual(card["copy_mode"], "structured")
        self.assertEqual(card["languages"], ["en", "ko"])
        self.assertFalse(card["requires_human_or_hermes_review"])
        self.assertEqual(card["aspect_ratio"], "square_1_1")
        self.assertEqual(card["visual_format"], "pr_review_infographic")
        self.assertEqual(card["domain_key"], "developer")
        self.assertEqual(card["visual_theme"]["domain_key"], "developer")
        self.assertEqual(card["poster_archetype"], "technical_brutalist")
        self.assertEqual(card["poster_archetype_profile"]["schema_version"], "poster_archetype/v1")
        self.assertEqual(card["poster_archetype_profile"]["id"], "technical_brutalist")
        self.assertEqual(card["layout"]["type"], "pr_review_infographic")
        self.assertEqual(card["layout"]["poster_archetype"], "technical_brutalist")
        self.assertEqual(card["style_direction"]["domain_key"], "developer")
        self.assertEqual(card["style_direction"]["poster_archetype"], "technical_brutalist")
        self.assertIn("Review focus", card["format_profile"]["structure"])
        self.assertEqual(card["image_text"]["footer"], "OMH generated")
        self.assertIn("OMH generated", card["generation_prompt"])
        self.assertIn("Detected visual domain: developer / developer workflow", card["generation_prompt"])
        self.assertIn("Poster archetype contract (poster_archetype/v1): Technical brutalist systems poster", card["generation_prompt"])
        self.assertIn("Source kind controls information structure", card["generation_prompt"])
        self.assertIn("raw systems panels", card["generation_prompt"])
        self.assertIn("format contract", card["visual_theme"]["format_contract"])
        self.assertIn("Premium image standard", card["layout"]["quality_rule"])
        self.assertIn("source kind, domain scene, and poster archetype separate", card["layout"]["poster_archetype_rule"])
        self.assertIn("Background plate requirement", card["layout"]["background_plate_rule"])
        self.assertIn("Material and texture direction", card["generation_prompt"])
        self.assertIn("Camera and rendering treatment", card["generation_prompt"])
        self.assertIn("generate_visual_image", card["available_actions"])
        self.assertEqual(card["capability_detection"]["state"], "connected")
        self.assertEqual(card["capability_setup"]["schema_version"], "image_generation_setup/v1")
        self.assertFalse(card["capability_setup"]["required"])
        self.assertEqual(card["capability_setup"]["next_action"], "generate_visual_image")
        self.assertIn("Do not invent facts", card["negative_prompt"])
        self.assertIn("PR review infographic", card["generation_prompt"])
        self.assertIn("developer workspace", card["generation_prompt"])
        self.assertIn("image_generated", card["not_evidence_until_observed"])
        self.assertEqual(validate_visual_prompt_card(card), [])

    def test_prompt_card_defaults_are_deterministic(self) -> None:
        args = {
            "kind": "PR",
            "headline": "PR Review Card",
            "sections": [
                {"role": "summary", "title": "What changed", "image_text": "Setup copy is safer and clearer."},
                {"role": "risk", "title": "Review focus", "image_text": "Check install claims against tests."},
            ],
        }

        first = build_visual_prompt_card(**args)
        second = build_visual_prompt_card(**args)

        self.assertEqual(first, second)
        self.assertRegex(first["card_id"], r"^github-pr-[0-9a-f]{12}$")
        self.assertNotIn("created_at", first)

    def test_all_source_kind_templates_are_supported(self) -> None:
        for kind in SOURCE_KINDS:
            with self.subTest(kind=kind):
                card = build_visual_prompt_card(
                    kind=kind,
                    source_text="First supplied line.\nSecond supplied line.\nThird supplied line.",
                )

                self.assertEqual(card["source_kind"], kind)
                self.assertEqual(card["copy_mode"], "extractive_draft")
                self.assertTrue(card["requires_human_or_hermes_review"])
                self.assertGreaterEqual(len(card["sections"]), 3)
                self.assertIn("missing_structured_inputs", card)

    def test_horizontal_prompt_does_not_force_vertical_wording(self) -> None:
        card = build_visual_prompt_card(
            kind="release",
            aspect_ratio="horizontal_16_9",
            sections=[{"role": "summary", "title": "What is new", "image_text": "A safer visual card workflow."}],
        )

        self.assertIn("horizontal_16_9", card["generation_prompt"])
        self.assertNotIn("boxed vertical img summary card", card["generation_prompt"])

    def test_visual_formats_are_source_specific_and_support_long_scroll(self) -> None:
        self.assertEqual(resolve_visual_format("meeting"), "meeting_recap_card")
        self.assertEqual(resolve_visual_format("report"), "report_digest_card")
        self.assertEqual(resolve_visual_format("issue"), "issue_triage_card")
        self.assertEqual(resolve_aspect_ratio("auto", resolve_visual_format("github_pr")), "square_1_1")
        self.assertEqual(resolve_aspect_ratio("auto", resolve_visual_format("report")), "long_scroll")

        report = build_visual_prompt_card(
            kind="report",
            aspect_ratio="long_scroll",
            sections=[
                {"role": "summary", "title": "Executive summary", "image_text": "Revenue grew while support cost increased."},
                {"role": "metric", "title": "Metric", "image_text": "Activation improved after setup copy changes."},
            ],
        )

        self.assertEqual(report["source_kind"], "report_summary")
        self.assertEqual(report["visual_format"], "report_digest_card")
        self.assertEqual(report["aspect_ratio"], "long_scroll")
        self.assertIn("report dashboard", report["format_profile"]["theme_direction"])
        self.assertIn("long vertical document-style canvas", report["generation_prompt"])
        self.assertIn("Do not force every source kind into the same grid", report["generation_prompt"])
        self.assertIn("high-fidelity photographic", report["generation_prompt"])

    def test_visual_theme_adapts_to_domain_without_losing_common_format(self) -> None:
        security = build_visual_prompt_card(
            kind="issue",
            headline="Security Risk Triage Card",
            sections=[
                {
                    "role": "signal",
                    "title": "Signal",
                    "image_text": "Unusual admin login attempts spiked after a password reset and MFA failure campaign.",
                }
            ],
        )
        shopping = build_visual_prompt_card(
            kind="github_pr",
            headline="Checkout Feature Implementation Review",
            sections=[
                {
                    "role": "summary",
                    "title": "What changed",
                    "image_text": "Cart now supports guest checkout, coupon validation, shipping estimates, and product inventory edge cases.",
                }
            ],
        )
        sports = build_visual_prompt_card(
            kind="research",
            headline="Sports Market Research Brief",
            sections=[
                {
                    "role": "finding",
                    "title": "Key finding",
                    "image_text": "Youth basketball gear demand clusters around league-day shoes, compression wear, and team bundles.",
                }
            ],
        )
        fashion = build_visual_prompt_card(
            kind="report",
            headline="Fashion Lookbook Launch Digest",
            sections=[
                {
                    "role": "summary",
                    "title": "Editorial focus",
                    "image_text": "The new streetwear collection needs outfit annotations, fabric swatches, and runway-ready release copy.",
                }
            ],
        )

        self.assertEqual(security["visual_theme"]["label"], "security operations")
        self.assertEqual(security["poster_archetype"], "cinematic_key_art")
        self.assertIn("Cinematic key-art poster", security["generation_prompt"])
        self.assertIn("security operations center", security["generation_prompt"])
        self.assertEqual(shopping["visual_theme"]["label"], "commerce and shopping")
        self.assertEqual(shopping["poster_archetype"], "product_ad")
        self.assertIn("checkout receipt", shopping["generation_prompt"])
        self.assertEqual(sports["visual_theme"]["label"], "sports field and gear")
        self.assertEqual(sports["poster_archetype"], "sports_event")
        self.assertIn("Sports event poster", sports["generation_prompt"])
        self.assertIn("court markings", sports["generation_prompt"])
        self.assertEqual(fashion["visual_theme"]["label"], "fashion editorial")
        self.assertEqual(fashion["poster_archetype"], "luxury_lookbook")
        self.assertIn("Luxury lookbook poster", fashion["generation_prompt"])
        self.assertIn("fashion editorial set", fashion["generation_prompt"])

        for card in (security, shopping, sports, fashion):
            with self.subTest(card=card["card_id"]):
                self.assertEqual(card["layout"]["brand_mark"], "OMH generated")
                self.assertEqual(card["image_text"]["footer"], "OMH generated")
                self.assertIn("evidence footer", card["layout"]["composition_rule"])
                self.assertIn("scene_quality", card["visual_theme"])
                self.assertIn("background_plate", card["visual_theme"])
                self.assertIn("material_texture", card["visual_theme"])
                self.assertIn("depth_lighting", card["visual_theme"])
                self.assertIn("camera_treatment", card["visual_theme"])
                self.assertIn("poster_archetype_profile", card)
                self.assertEqual(card["poster_archetype_profile"]["schema_version"], "poster_archetype/v1")
                self.assertIn("Poster visual grammar", card["generation_prompt"])
                self.assertIn("flat vector clipart", card["visual_theme"]["avoid_style"])
                self.assertIn("Premium scene reference", card["generation_prompt"])
                self.assertIn("Background plate:", card["generation_prompt"])
                self.assertIn("Material and texture direction", card["generation_prompt"])
                self.assertIn("Depth and lighting direction", card["generation_prompt"])
                self.assertIn("Camera and rendering treatment", card["generation_prompt"])
                self.assertIn("Do not reuse a generic dark glass card", card["generation_prompt"])
                self.assertEqual(validate_visual_prompt_card(card), [])

    def test_poster_archetypes_are_explicit_visual_grammar_not_source_or_domain(self) -> None:
        self.assertEqual(resolve_poster_archetype("research"), "data_infographic")
        for archetype in POSTER_ARCHETYPES:
            with self.subTest(archetype=archetype):
                card = build_visual_prompt_card(
                    kind="research",
                    headline="Market research briefing",
                    poster_archetype=archetype,
                    sections=[
                        {
                            "role": "finding",
                            "title": "Finding",
                            "image_text": "Customer research points to onboarding confusion and missing proof.",
                        }
                    ],
                )

                self.assertEqual(card["source_kind"], "research_briefing")
                self.assertEqual(card["domain_key"], "research")
                self.assertEqual(card["visual_theme"]["label"], "research synthesis")
                self.assertEqual(card["visual_theme"]["domain_key"], "research")
                self.assertEqual(card["poster_archetype"], archetype)
                self.assertEqual(card["poster_archetype_profile"]["id"], archetype)
                self.assertIn(card["poster_archetype_profile"]["label"], card["generation_prompt"])
                self.assertIn("Source kind controls information structure", card["generation_prompt"])
                self.assertEqual(validate_visual_prompt_card(card), [])

    def test_rejects_invalid_poster_archetype_and_missing_archetype_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported poster archetype"):
            build_visual_prompt_card(
                kind="meeting",
                poster_archetype="bauhaus_space_opera",
                sections=[{"role": "summary", "title": "Summary", "image_text": "A short note."}],
            )

        card = build_visual_prompt_card(
            kind="meeting",
            sections=[{"role": "summary", "title": "Summary", "image_text": "A short note."}],
        )
        broken = dict(card)
        broken.pop("poster_archetype_profile")
        self.assertIn("poster_archetype_profile must be an object", validate_visual_prompt_card(broken))

        broken_theme_missing = dict(card)
        broken_theme_missing.pop("visual_theme")
        self.assertIn("visual_theme must be an object", validate_visual_prompt_card(broken_theme_missing))

        broken_layout = deepcopy(card)
        broken_layout["layout"]["poster_archetype"] = "swiss_grid"
        self.assertIn("layout.poster_archetype must match poster_archetype", validate_visual_prompt_card(broken_layout))

        broken_theme = deepcopy(card)
        broken_theme["visual_theme"]["domain_key"] = "security"
        self.assertIn("visual_theme.domain_key must match domain_key", validate_visual_prompt_card(broken_theme))

        broken_style = deepcopy(card)
        broken_style["style_direction"]["poster_archetype"] = "sports_event"
        self.assertIn("style_direction.poster_archetype must match poster_archetype", validate_visual_prompt_card(broken_style))

    def test_visual_prompt_rejects_color_swap_template_quality(self) -> None:
        card = build_visual_prompt_card(
            kind="issue",
            headline="Security Prompt Injection Review",
            sections=[
                {
                    "role": "signal",
                    "title": "Signal",
                    "image_text": "A prompt injection attempt tries to leak tool output and bypass authentication controls.",
                }
            ],
        )

        self.assertIn("cinematic security operations room", card["visual_theme"]["scene_quality"])
        self.assertIn("photo-real SOC analyst desk", card["visual_theme"]["background_plate"])
        self.assertIn("matte graphite panels", card["visual_theme"]["material_texture"])
        self.assertIn("screen reflections", card["visual_theme"]["depth_lighting"])
        self.assertIn("35mm cinematic close-up", card["visual_theme"]["camera_treatment"])
        self.assertIn("plain gradient backdrops", card["generation_prompt"])
        self.assertIn("color-swapped templates", card["generation_prompt"])
        self.assertIn("low-detail wallpaper", card["generation_prompt"])
        self.assertIn("before placing the readable card modules", card["generation_prompt"])
        self.assertIn("rich subject-specific environment first", card["generation_prompt"])

    def test_visual_copy_can_be_denser_when_canvas_can_expand(self) -> None:
        long_text = (
            "A long research card should keep enough concrete source detail for the image generator "
            "to render a useful briefing without shrinking the text into unreadable poster copy."
        )
        card = build_visual_prompt_card(
            kind="research",
            aspect_ratio="long_scroll",
            sections=[{"role": "finding", "title": "Detailed finding", "image_text": long_text}],
        )

        self.assertGreater(card["sections"][0]["max_words"], 18)
        self.assertIn("extend the canvas", card["layout"]["density_rule"])
        self.assertIn("Visible text may be moderately dense", card["generation_prompt"])
        self.assertIn("long vertical document-style canvas", card["generation_prompt"])

    def test_extractive_draft_uses_bounded_source_without_fabricated_claims(self) -> None:
        source = "\n".join(f"Observed line {index} from the supplied notes." for index in range(1, 80))
        card = build_visual_prompt_card(kind="meeting", source_text=source)

        self.assertEqual(card["copy_mode"], "extractive_draft")
        self.assertLessEqual(len(card["source_excerpt"]), 1200)
        combined_copy = " ".join(section["image_text"] for section in card["sections"])
        self.assertIn("Observed line 1", combined_copy)
        self.assertNotIn("owner", combined_copy.lower())
        self.assertNotIn("tests passed", combined_copy.lower())
        self.assertTrue(card["requires_human_or_hermes_review"])

    def test_rejects_unsupported_kind_language_and_malformed_sections(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported visual source kind"):
            normalize_source_kind("poster")
        with self.assertRaisesRegex(ValueError, "unsupported visual language"):
            build_visual_prompt_card(
                kind="meeting",
                language="fr",
                sections=[{"role": "summary", "title": "Summary", "image_text": "Text"}],
            )
        with self.assertRaisesRegex(ValueError, "exactly three"):
            parse_section_arg("summary:Title:Text:extra")
        with self.assertRaisesRegex(ValueError, "provide at least one"):
            build_visual_prompt_card(kind="meeting")

    def test_generate_action_requires_connected_capability(self) -> None:
        self.assertNotIn("generate_visual_image", visual_wrapper_actions("unknown"))
        self.assertNotIn("generate_visual_image", visual_wrapper_actions("prompt_only"))
        self.assertIn("generate_visual_image", visual_wrapper_actions("connected"))
        self.assertIn("choose_image_generator", visual_wrapper_actions("unknown"))
        self.assertIn("setup_image_generator", visual_wrapper_actions("prompt_only"))
        self.assertNotIn("choose_image_generator", visual_wrapper_actions("connected"))

        setup = image_generation_setup_fallback("unknown")
        self.assertEqual(setup["schema_version"], "image_generation_setup/v1")
        self.assertTrue(setup["required"])
        self.assertEqual(setup["recommended_option"], "gpt-image")
        self.assertEqual(setup["next_action"], "choose_image_generator")
        self.assertIn("GPT image tool", {option["label"] for option in setup["options"]})
        self.assertIn("not generated image", setup["setup_boundary"])

    def test_visual_observation_validation_and_store_boundaries(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            artifact = root / "card.png"
            card_id = "20260618T011325Z-github-pr-abc123"

            generated = build_visual_observation(
                card_id=card_id,
                observation_type="generated-image",
                path_or_uri=str(artifact),
                evidence_summary="Wrapper reported generated PNG file.",
                observed_at="2026-06-18T01:13:25Z",
            )

            self.assertEqual(generated["schema_version"], "visual_observation/v1")
            self.assertEqual(generated["observation_type"], "generated_image_observed")
            self.assertEqual(generated["artifact"]["mime_type"], "image/png")
            self.assertIn("visual_qa_passed", generated["does_not_prove"])
            self.assertEqual(validate_visual_observation(generated), [])

            file_uri = build_visual_observation(
                card_id=card_id,
                observation_type="generated-image",
                path_or_uri=artifact.as_uri(),
                evidence_summary="Wrapper reported generated PNG file URI.",
                observed_at="2026-06-18T01:13:26Z",
            )
            self.assertEqual(validate_visual_observation(file_uri), [])

            written = write_visual_observation(paths, generated)
            self.assertEqual(list_visual_observations(paths)[0]["observation_id"], written["observation_id"])
            self.assertTrue(paths.visual_observations_index_path.exists())

            with self.assertRaisesRegex(ValueError, "absolute local path or URI"):
                build_visual_observation(
                    card_id=card_id,
                    observation_type="visual-qa",
                    path_or_uri="relative/card.png",
                    evidence_summary="QA checked.",
                )
            with self.assertRaisesRegex(ValueError, "mime_type"):
                build_visual_observation(
                    card_id=card_id,
                    observation_type="delivery",
                    path_or_uri=str(root / "card.gif"),
                    evidence_summary="Posted to channel.",
                )
            with self.assertRaisesRegex(ValueError, "evidence_summary"):
                build_visual_observation(
                    card_id=card_id,
                    observation_type="generated-image",
                    path_or_uri=str(artifact),
                    evidence_summary="",
                )


if __name__ == "__main__":
    unittest.main()
