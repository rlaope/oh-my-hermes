from __future__ import annotations

import re
import unittest

from _local_package import load_local_package

load_local_package()

from omh.routing.localization import normalized_phrase
from omh.routing.policy import everyday_sense_phrase_unanchored
from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.wrapper.contract import build_chat_interaction_payload

SKILL = "model-compression"
REFERENCE_PATH = "references/compression-method.md"
SIBLINGS = ("inference-serving", "model-finetuning", "rules-distill", "model-optimization")


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


def _route(message: str) -> dict[str, object]:
    return build_chat_interaction_payload(message, source="discord")["route"]


def _reference() -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == SKILL and template.relative_path == REFERENCE_PATH
    )


class ModelCompressionCatalogTests(unittest.TestCase):
    """A smaller model is kept only when it holds quality on the person's own task."""

    def test_the_target_comes_first_and_the_gate_compares_with_the_baseline(self) -> None:
        mine = _definition(SKILL)
        self.assertEqual(mine.expected_outputs[0], "compression_target/v1")
        for schema in mine.expected_outputs:
            with self.subTest(schema=schema):
                self.assertEqual(len([line for line in mine.artifact_expectations if line.startswith(schema)]), 1)
        gate = next(line for line in mine.artifact_expectations if line.startswith("compression_quality_gate/v1"))
        self.assertIn("uncompressed baseline", gate)
        self.assertIn("secondary signal", gate)
        self.assertTrue(mine.safety_rules[0].endswith("perplexity alone never keeps a compressed model."))
        self.assertIn("held-out eval", mine.safety_rules[2])

    def test_every_command_in_the_reference_names_its_source_page(self) -> None:
        commands = _reference().split("## 3. Commands", 1)[1].split("## 4.", 1)[0]
        sections = [section for section in commands.split("\n### ")[1:]]
        self.assertGreaterEqual(len(sections), 8)
        for section in sections:
            with self.subTest(section=section.splitlines()[0]):
                self.assertRegex(section, r"(?m)^Source: https://\S+$")
        body = next(template.content for template in builtin_skill_templates() if template.name == SKILL)
        self.assertIn(REFERENCE_PATH, body)

    def test_the_method_ladder_starts_without_training(self) -> None:
        ladder = _reference().split("## 2. Choose the method", 1)[1].split("## 3.", 1)[0]
        rungs = [line.split("|")[1].strip() for line in ladder.splitlines() if re.match(r"^\| \d ", line)]
        self.assertEqual(rungs, ["1", "2", "3", "4", "5"])
        self.assertIn("no calibration data", ladder.split("| 1 |", 1)[1].split("\n", 1)[0])
        self.assertIn("Distillation", ladder.split("| 5 |", 1)[1].split("\n", 1)[0])

    def test_siblings_and_this_skill_name_each_other_once(self) -> None:
        mine = _definition(SKILL).do_not_use_when
        for other in SIBLINGS:
            with self.subTest(sibling=other):
                self.assertEqual(len([text for text in mine if f"`{other}`" in text]), 1)
                theirs = [text for text in _definition(other).do_not_use_when if f"`{SKILL}`" in text]
                self.assertEqual(len(theirs), 1)

    def test_no_sibling_still_says_omh_has_no_pruning_workflow(self) -> None:
        for template in builtin_skill_reference_templates():
            if template.skill_name in SIBLINGS:
                with self.subTest(reference=f"{template.skill_name}/{template.relative_path}"):
                    self.assertNotIn("no pruning workflow", template.content)
        for other in SIBLINGS:
            with self.subTest(sibling=other):
                self.assertFalse(any("no pruning workflow" in text for text in _definition(other).do_not_use_when))


class ModelCompressionRoutingTests(unittest.TestCase):
    def test_compression_requests_dispatch_here(self) -> None:
        for message in (
            "quantize this model",
            "distill this model",
            "distill this model into a smaller one",
            "prune 50% of the weights in llama with SparseGPT",
            "should we do quantization-aware training or post-training quantization",
            "make this model smaller so it fits on a 24GB GPU without losing quality",
            "which calibration data should I use for GPTQ",
            "quantize the model to 4-bit for our 12gb gpu",
            "이 모델 양자화해줘",
            "지식 증류로 작은 모델 만들어줘",
            "모델 경량화해서 gpu 메모리 줄여줘",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], SKILL)

    def test_the_same_words_elsewhere_stay_away(self) -> None:
        for message in (
            "compress this video",
            "quantize the colors in this image",
            "prune the hedge",
            "distill whisky",
            "모델 하우스 압축",
            "distill our model of customer churn into a one-pager",
            "prune the model of unused variables before the regression",
            "structured pruning of our apple trees",
            "8-bit quantization of the audio signal",
            "make the model smaller in blender",
            "3d 모델 경량화해줘",
            "게임 캐릭터 모델 압축",
            "our teacher student ratio is too high",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertNotEqual(route["selected_skill"], SKILL)
                self.assertNotEqual(route.get("candidate_skill"), SKILL)

    def test_sibling_territory_keeps_its_owner(self) -> None:
        for message, owner in (
            ("serve this quantized model with vLLM", "inference-serving"),
            ("which quantization should we serve on llama.cpp", "inference-serving"),
            ("fine-tune llama on our tickets with qlora", "model-finetuning"),
            ("distill rules from this session", "rules-distill"),
            ("onboard new model", "model-optimization"),
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], owner)

    def test_a_shared_phrase_needs_a_word_of_model_weights_outside_it(self) -> None:
        for message, withdrawn in (
            ("make the model smaller in blender", True),
            ("8-bit quantization of the audio signal", True),
            ("distill our model of customer churn into a one-pager", True),
            ("distill this model into a smaller one", False),
            ("8-bit quantization of our llama checkpoint", False),
            ("quantize the model to 4-bit", False),
            ("quantize this model", False),
        ):
            with self.subTest(message=message):
                self.assertIs(everyday_sense_phrase_unanchored(SKILL, normalized_phrase(message)), withdrawn)


if __name__ == "__main__":
    unittest.main()
