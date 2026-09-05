"""Static delegation of the live-model tool framework benchmark tests.

``benchmarks/live-model-tools/v1/tests/test_framework.py`` is the upstream
source of truth for the benchmark framework contract, but it lives outside
``tests/`` so the static sharding inventory cannot see it. This wrapper
statically declares one delegator method per upstream test and executes the
real upstream implementation through the safe path-loader pattern (an explicit
``spec_from_file_location`` load plus the local package bootstrap, never an
import of an untrusted path). The delegated runs therefore exercise the exact
upstream behavior, including the paid-live authorization blocks, without this
file duplicating any assertion.

``UpstreamDelegationParityTests`` AST-parses the upstream file and compares it
with this file's declarations, so any upstream addition, removal, or rename
fails loudly here instead of silently vanishing from the shard plan.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest

from _local_package import load_local_package

load_local_package()

UPSTREAM: Path = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "live-model-tools"
    / "v1"
    / "tests"
    / "test_framework.py"
)
UPSTREAM_LIB: Path = UPSTREAM.parent.parent / "lib"
UPSTREAM_MODULE_NAME = "omh_live_model_tool_framework_upstream"

# Wrapper class -> upstream class. A new upstream TestCase class without a
# wrapper entry fails the parity test loudly, and a wrapper class that is not
# listed here fails it too.
UPSTREAM_CLASS_BY_WRAPPER: dict[str, str] = {
    "OmhBenchmarkFrameworkDelegationTests": "OmhBenchmarkFrameworkTests",
    "OmhTargetedManifestAnalysisDelegationTests": "OmhTargetedManifestAnalysisTests",
}


def _local_module_names() -> tuple[str, ...]:
    return tuple(sorted(
        path.stem
        for path in UPSTREAM_LIB.glob("*.py")
        if path.stem != "__init__"
    ))


@contextmanager
def _upstream_import_scope() -> Iterator[None]:
    """Temporarily prefer benchmark-local bare imports without polluting tests."""
    local_names = _local_module_names()
    saved_modules = {name: sys.modules.get(name) for name in local_names}
    original_path = list(sys.path)
    for name in local_names:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(UPSTREAM_LIB))
    try:
        yield
    finally:
        sys.path[:] = original_path
        for name, saved in saved_modules.items():
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved


def _load_upstream() -> ModuleType:
    """Load the upstream test module by explicit path, cached per process."""

    cached = sys.modules.get(UPSTREAM_MODULE_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(UPSTREAM_MODULE_NAME, UPSTREAM)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[UPSTREAM_MODULE_NAME] = module
    loaded = False
    try:
        with _upstream_import_scope():
            spec.loader.exec_module(module)
        loaded = True
    finally:
        if not loaded:
            sys.modules.pop(UPSTREAM_MODULE_NAME, None)
    return module


class _UpstreamDelegationBase(unittest.TestCase):
    """Shared delegation engine; declares no test methods itself."""

    def _delegate(self, class_name: str, method_name: str) -> None:
        module = _load_upstream()
        attribute = getattr(module, class_name)
        if not isinstance(attribute, type) or not issubclass(attribute, unittest.TestCase):
            self.fail(f"upstream test class is missing: {class_name}")
        case = attribute(method_name)
        method = getattr(case, method_name)
        if not callable(method):
            self.fail(f"upstream test method is missing: {method_name}")
        with _upstream_import_scope():
            case.debug()


class OmhBenchmarkFrameworkDelegationTests(_UpstreamDelegationBase):
    def test_doctor_reports_omh_hermes_child_contract(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_doctor_reports_omh_hermes_child_contract",
        )

    def test_fake_smoke_is_offline_and_passes(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_fake_smoke_is_offline_and_passes",
        )

    def test_artifact_gate_rejects_prompt_secret_and_absolute_path(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_artifact_gate_rejects_prompt_secret_and_absolute_path",
        )

    def test_output_symlink_and_workspace_symlinks_are_rejected(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_output_symlink_and_workspace_symlinks_are_rejected",
        )

    def test_live_harness_is_blocked_without_explicit_flag(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_live_harness_is_blocked_without_explicit_flag",
        )

    def test_live_harness_requires_explicit_call_budget(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_live_harness_requires_explicit_call_budget",
        )

    def test_offline_receipt_counts_zero_paid_calls(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_offline_receipt_counts_zero_paid_calls",
        )

    def test_help_names_omh_and_never_omo(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_help_names_omh_and_never_omo",
        )

    def test_run_record_schema_matches_observation_summary(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_run_record_schema_matches_observation_summary",
        )

    def test_analysis_compares_equal_task_digests(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_analysis_compares_equal_task_digests",
        )

    def test_analysis_pairs_the_family_arm_against_the_override(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_analysis_pairs_the_family_arm_against_the_override",
        )

    def test_bench_cli_schedules_the_family_condition_offline(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_bench_cli_schedules_the_family_condition_offline",
        )

    def test_analysis_rejects_unscheduled_model_claim_matrix(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_analysis_rejects_unscheduled_model_claim_matrix",
        )

    def test_analysis_rejects_optimized_development_split(self) -> None:
        self._delegate(
            "OmhBenchmarkFrameworkTests",
            "test_analysis_rejects_optimized_development_split",
        )


class OmhTargetedManifestAnalysisDelegationTests(_UpstreamDelegationBase):
    def test_targeted_manifest_cli_analyze_end_to_end(self) -> None:
        self._delegate(
            "OmhTargetedManifestAnalysisTests",
            "test_targeted_manifest_cli_analyze_end_to_end",
        )

    def test_targeted_manifest_cli_rejects_mismatched_manifest(self) -> None:
        self._delegate(
            "OmhTargetedManifestAnalysisTests",
            "test_targeted_manifest_cli_rejects_mismatched_manifest",
        )

    def test_cli_analyze_defaults_to_canonical_manifest(self) -> None:
        self._delegate(
            "OmhTargetedManifestAnalysisTests",
            "test_cli_analyze_defaults_to_canonical_manifest",
        )


class UpstreamDelegationParityTests(unittest.TestCase):
    """Fail loudly when upstream and this wrapper drift apart."""

    def _test_methods(self, path: Path) -> dict[str, tuple[str, ...]]:
        """Statically collect each TestCase class and its test methods."""

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bases: dict[str, tuple[str, ...]] = {}
        methods: dict[str, tuple[str, ...]] = {}
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases[node.name] = tuple(ast.unparse(base) for base in node.bases)
            methods[node.name] = tuple(
                member.name
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
                and member.name.startswith("test")
            )

        def inherits_test_case(name: str) -> bool:
            for base in bases.get(name, ()):
                if base in {"unittest.TestCase", "unittest.case.TestCase"}:
                    return True
                if base in bases and inherits_test_case(base):
                    return True
            return False

        return {
            name: methods[name] for name in sorted(methods) if inherits_test_case(name)
        }

    def test_wrapper_delegators_match_upstream_exactly(self) -> None:
        upstream = self._test_methods(UPSTREAM)
        wrapper = self._test_methods(Path(__file__))
        self.assertEqual(
            sorted(upstream),
            sorted(UPSTREAM_CLASS_BY_WRAPPER.values()),
            "every upstream TestCase class needs a UPSTREAM_CLASS_BY_WRAPPER entry",
        )
        self.assertEqual(
            set(wrapper),
            set(UPSTREAM_CLASS_BY_WRAPPER) | {"UpstreamDelegationParityTests", "_UpstreamDelegationBase"},
            "wrapper TestCase classes must be exactly the mapped delegators plus parity/base",
        )
        for wrapper_class, upstream_class in UPSTREAM_CLASS_BY_WRAPPER.items():
            self.assertEqual(
                sorted(wrapper[wrapper_class]),
                sorted(upstream[upstream_class]),
                f"{wrapper_class} must declare a delegator for exactly every "
                f"{upstream_class} test",
            )


if __name__ == "__main__":
    unittest.main()
