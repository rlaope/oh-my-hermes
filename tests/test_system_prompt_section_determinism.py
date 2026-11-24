"""OMH's session-frozen system-prompt text is byte-stable across processes.

Hermes freezes plugin sections into a session's system prompt, and a provider
prompt cache only hits when that prefix is byte-identical. Two sessions that
render the same inputs in different processes (a gateway restart, a cron run,
a `delegate_task` child) must therefore produce the same bytes: no set or
dict-hash order, clock, mtime or random value may reach the text. Each
render runs in its own interpreter with a different `PYTHONHASHSEED` and
`TZ`, so string-hash order differs between the two.

OMH adds no skill index or skill-candidate text to the system prompt: Hermes
renders the skills index itself, and OMH's candidate line rides
`pre_llm_call` (the user-turn side), so the sections below are all of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.hooks import llm_hooks

_TESTS_DIR = Path(__file__).resolve().parent

# Several custom identities with set-like inputs: a hash-ordered iteration
# anywhere on the render path would reorder them between the two seeds.
_IDENTITIES = {
    "schema_version": "omh_identity_profiles/v1",
    "identities": {
        name: {"prompt": f"{name} scope: review, perf, scripts, [brackets] <tags> 审", "model_chain": [{"model_id": "m"}]}
        for name in ("zeta", "alpha", "mu", "beta-review", "omega", "kappa", "delta", "pi")
    },
}

_RENDER = r"""
import json, sys
from _local_package import load_local_package
load_local_package()
from omh.plugin_bundle.omh.hooks.llm_hooks import awareness_system_prompt_section
from omh.plugin_bundle.omh.omh_identities import identity_catalog_context
from omh.plugin_bundle.omh.child_calibration import child_calibration_section
from omh.plugin_bundle.omh.delegation_protocol import delegation_protocol_section
from omh.plugin_bundle.omh.main_calibration import main_calibration_section
home, empty = sys.argv[1], sys.argv[2]
out = {}
for platform in ("cli", "discord", "cron", "subagent"):
    for model in ("claude-opus-4-8", "kimi-k3"):
        info = {"session_id": f"s-{platform}-{model}", "platform": platform, "model": model, "omh_home": home}
        out[f"{platform}/{model}"] = {
            "omh.awareness": awareness_system_prompt_section(info),
            "omh.awareness/no-identities": awareness_system_prompt_section({**info, "omh_home": empty}),
            "omh.child-calibration": child_calibration_section(info),
            "omh.delegation-protocol": delegation_protocol_section(info),
            "omh.main-calibration": main_calibration_section(info),
        }
out["identity_catalog"] = identity_catalog_context(home)
out["identity_catalog/800"] = identity_catalog_context(home, max_chars=800)
# Write UTF-8 bytes: on Windows the child's text stdout uses the ANSI code page
# (cp1252), which turns an em dash into 0x97 and breaks the parent's json.loads.
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, sort_keys=True).encode("utf-8"))
"""


def _render_in_subprocess(home: Path, empty: Path, seed: str, tz: str) -> bytes:
    env = {**os.environ, "PYTHONHASHSEED": seed, "TZ": tz}
    result = subprocess.run(
        [sys.executable, "-c", _RENDER, str(home), str(empty)],
        cwd=_TESTS_DIR, env=env, capture_output=True, check=False, timeout=240,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.decode("utf-8", "replace")[-4000:])
    return result.stdout


class SystemPromptSectionDeterminismTests(unittest.TestCase):
    def test_sections_render_identical_bytes_in_two_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home, empty = Path(tmp) / "omh", Path(tmp) / "empty"
            (home / "routing").mkdir(parents=True)
            empty.mkdir()
            (home / "routing" / "identities.json").write_text(json.dumps(_IDENTITIES), encoding="utf-8")
            first = _render_in_subprocess(home, empty, "0", "UTC")
            # Touch the document between renders: an mtime must not reach the text.
            os.utime(home / "routing" / "identities.json", (1, 1))
            second = _render_in_subprocess(home, empty, "4242", "Asia/Seoul")
        self.assertEqual(first, second)
        rendered = json.loads(first)
        # The fixture exercises the catalog, not an empty render.
        self.assertIn("- custom:zeta", rendered["identity_catalog"])
        self.assertIn("- custom:alpha", rendered["cli/claude-opus-4-8"]["omh.awareness"])

    def test_machine_paced_platforms_mirror_hermes(self) -> None:
        # Hermes `agent/prompt_caching.py` MACHINE_PACED_SOURCES at caafe5389a.
        self.assertEqual(
            llm_hooks.MACHINE_PACED_PLATFORMS,
            frozenset({"subagent", "cron", "oneshot", "webhook", "kanban", "api", "api_server", "tool",
                       "batch", "curator", "a2a", "msgraph_webhook", "gateway_hygiene"}),
        )


if __name__ == "__main__":
    unittest.main()
