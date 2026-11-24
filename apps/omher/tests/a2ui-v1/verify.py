"""Offline conformance of actual renderer inputs (not hand-authored sample messages).
Run with a Python environment that already has jsonschema + referencing and installed app dev deps.
"""
import copy
import hashlib
import json
import subprocess
import os
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
HASHES = {
    "catalog": "d4ce11f8fff2da8d5fd0b2793db524f6aa7eef541eefb6fe2b71f0efc17cbfa9",
    "common_types": "c4e78305be1de73eecb37f8179ba169730250611703683af291b18135a6430dc",
    "agent_to_renderer": "2f575f783fdda0e4d175fe5d331661655e4a4901613262322792dae7e823761d",
}


def main():
    registry = Registry()  # no network retrieval
    schemas = {}
    for name, digest in HASHES.items():
        raw = (HERE / (name + ".json")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"schema pin mismatch: {name}")
        schemas[name] = schema = json.loads(raw)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    protocol, catalog, common = [schemas[n] for n in ("agent_to_renderer", "catalog", "common_types")]
    for base, name, schema in [(protocol, "catalog.json", catalog), (catalog, "common_types.json", common)]:
        registry = registry.with_resource(urljoin(base["$id"], name), Resource.from_contents(schema))
    validator = Draft202012Validator(protocol, registry=registry)
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / "messages.json"
        subprocess.run([str(APP / "node_modules/.bin/vitest"), "run", "src/sessions/dag/Evidence.test.tsx"],
                       cwd=APP, env={**os.environ, "OMHER_SCHEMA_CAPTURE": str(output)}, check=True)
        messages = json.loads(output.read_text())
    if len(messages) != 2:
        raise ValueError("expected actual run and selected-node messages")
    for message in messages:
        if message["createSurface"]["catalogId"] != catalog["$id"]:
            raise ValueError("unexpected default catalog")
        validator.validate(message)
    # Negative controls independently exercise protocol envelope and catalog child schema, not just hash pins.
    invalid = copy.deepcopy(messages[0])
    invalid["createSurface"]["components"][0]["child"] = ["body"]
    if validator.is_valid(invalid) or validator.is_valid({**messages[0], "unexpected": True}):
        raise ValueError("protocol or catalog not enforced")
    print("2 production createSurface messages valid against pinned protocol/common/catalog; 2 negative controls rejected")


if __name__ == "__main__":
    main()
