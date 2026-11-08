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
            "distill this 70B into an 8B",
            "prune 50% of the weights in llama with SparseGPT",
            "should we do quantization-aware training or post-training quantization",
            "make the model smaller so our llm fits on one 24GB GPU",
            "which calibration data should I use for GPTQ",
            "quantize the model with gptq",
            "이 모델 양자화해줘",
            "지식 증류로 작은 모델 만들어줘",
            "GGUF로 양자화해줘",
            "70B 모델을 8B로 증류해줘",
            "llama 모델 경량화해줘",
            "distill our 7b model into a 1b for the phone",
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
            # A word of statistics, 3D, games, signals or know-how beside a
            # shared phrase is not a word of model weights.
            "prune the model of unused parameters before I fit the ANOVA again",
            "3D 모델 경량화해서 GPU 부하 줄이고 싶어",
            "make the model smaller so the GPU renders faster in Blender",
            "the churn model has poor accuracy, distill the model into a one-page summary for execs",
            "quantize the model of the grid to 8-bit color for the pixel art",
            "compress the model weights file with gzip for upload",
            "run a knowledge distillation workshop so seniors pass know-how to new hires",
            "팀 노하우를 지식 증류해서 문서로 정리해줘",
            "회귀 모델 파라미터 줄이고 모델 압축해줘",
            "이미지를 4비트로 양자화해줘",
            "증류수 사러 가야 해",
            # A billion is money, data or volume unless a second size or the
            # word model follows; a bit width is a palette or a retro look.
            "distill 5b gallons of whisky",
            "distill the 10b dataset into a sample",
            "our 2b budget model needs pruning, prune the model",
            "the 3b plan: distill the model of our sales funnel into a slide",
            "게임 모델 8비트로 양자화해서 레트로 느낌 내줘",
            "3D 모델 압축해서 양자화된 정점으로 저장해줘",
            "the transformer model in my electrical grid sim is too detailed, prune the model",
            "post-training quantization of the ADC signal in the firmware",
            "we raised 2b and spent 1b, distill the lessons into a memo",
            "distill 40b rows down to 2b rows for the dashboard",
            "distill the 5b compute budget into a plan for 2b next year",
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
            ("distill this model into a smaller one", True),
            ("prune the model of unused parameters before I fit the ANOVA again", True),
            ("compress the model so it loads faster on the GPU in Unity", True),
            ("knowledge distillation in education means what", True),
            ("knowledge distillation", False),
            ("distill the model into a 1.5b student", True),
            ("our 2b budget model needs pruning, prune the model", True),
            ("post-training quantization of the ADC signal in the firmware", True),
            ("should we do quantization-aware training or post-training quantization", False),
            ("8-bit quantization of our llama checkpoint", False),
            ("quantize the model to 4-bit", True),
            ("quantize this model", False),
        ):
            with self.subTest(message=message):
                self.assertIs(everyday_sense_phrase_unanchored(SKILL, normalized_phrase(message)), withdrawn)


class ModelCompressionParameterCountTests(unittest.TestCase):
    def test_a_size_names_a_model_only_twice_or_before_the_word_model(self) -> None:
        from omh.routing.model_compression_cues import names_a_model_by_parameter_count

        for message, named in (
            ("distill this 70B into an 8B", True),
            ("distill our 7b model into a 1b for the phone", True),
            ("70B 모델을 8B로 증류해줘", True),
            ("the 70b model is too slow", True),
            ("distill 5b gallons of whisky", False),
            ("distill the 10b dataset into a sample", False),
            ("our 2b budget model needs pruning", False),
            ("quantize it to 8bit", False),
            ("this 70B is too expensive, distill it into an 8B student", True),
            ("we raised 2b and spent 1b, distill the lessons into a memo", False),
            ("distill 40b rows down to 2b rows for the dashboard", False),
            ("distill the 5b compute budget into a plan for 2b next year", False),
            ("cut 2b to 1b for marketing, distill the plan into a memo", False),
        ):
            with self.subTest(message=message):
                self.assertIs(names_a_model_by_parameter_count(normalized_phrase(message)), named)


if __name__ == "__main__":
    unittest.main()
