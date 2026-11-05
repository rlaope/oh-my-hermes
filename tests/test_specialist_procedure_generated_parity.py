from __future__ import annotations

from pathlib import Path
import unittest

from _local_package import load_local_package
from specialist_procedure_contract_support import TARGETS

load_local_package()
from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import builtin_skill_templates, workflow_reference_payload


class SpecialistProcedureContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definitions = {definition.name: definition for definition in builtin_definitions()}
        self.finance = self.definitions["finance-analysis"]

    def test_machine_payload_and_shipped_target_bytes_match_catalog(self) -> None:
        payloads = {item["name"]: item for item in workflow_reference_payload()["skills"]}
        templates = {template.name: template.content for template in builtin_skill_templates()}
        references = {
            template.skill_name: template.content
            for template in builtin_skill_reference_templates()
            if template.relative_path == "references/procedure.md"
        }
        self.assertEqual(set(references), TARGETS)

        for name in sorted(TARGETS):
            definition = self.definitions[name]
            expected_steps = [
                {
                    "step_id": step.step_id,
                    "kind": step.kind,
                    "input_refs": list(step.input_refs),
                    "output_refs": list(step.output_refs),
                    "check_ids": list(step.check_ids),
                    "instruction": step.instruction,
                    **({"on_fail": {
                        "still_stands": list(step.on_fail.still_stands),
                        "downgrade_to": step.on_fail.downgrade_to,
                        "handback": step.on_fail.handback,
                        "fallback_skill": step.on_fail.fallback_skill,
                    }} if step.on_fail is not None else {}),
                }
                for step in definition.procedure_steps
            ]
            with self.subTest(name=name):
                expected_checks = [
                    {
                        "check_id": check.check_id,
                        "required_result_fields": list(check.required_result_fields),
                        "instruction": check.instruction,
                    }
                    for check in definition.procedure_checks
                ]
                self.assertEqual(payloads[name]["procedure_checks"], expected_checks)
                self.assertEqual(payloads[name]["procedure_steps"], expected_steps)
                shipped = Path(f"skills/omh-{name}/SKILL.md").read_text(encoding="utf-8")
                shipped_reference = Path(f"skills/omh-{name}/references/procedure.md").read_text(encoding="utf-8")
                self.assertEqual(shipped, templates[name])
                self.assertEqual(shipped_reference, references[name])


if __name__ == "__main__":
    unittest.main()
