#!/usr/bin/env python3
"""Deterministic offline harness for controller and validator smoke tests."""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def write(value):
    path = Path(os.environ["LMT_OUTPUT"])
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def locations(routes: Path):
    text = routes.read_text(encoding="utf-8")
    decision = next(node.name for node in ast.parse(text).body if isinstance(node, ast.ClassDef))
    rows = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if decision in line and not line.lstrip().startswith("#") and "DECOY" not in line:
            rows.append({"path":"src/benchapp/routes.py","line":line_no,"kind":"definition" if line.startswith("class ") else "reference"})
    return rows


# Reference-only edits for the lsp-ab rename templates (what a semantic rename produces).
SEMANTIC_RENAMES = {
    "RENAME-ALIAS": {
        "src/benchapp/quota.py": [("def compute_quota(units", "def allocate_quota(units")],
        "src/benchapp/api.py": [("import compute_quota", "import allocate_quota"), ('["compute_quota"]', '["allocate_quota"]')],
        "src/benchapp/service.py": [("import compute_quota as", "import allocate_quota as")],
        "src/benchapp/report.py": [("quota.compute_quota(units)", "quota.allocate_quota(units)")],
        "tests/test_quota.py": [("api import compute_quota", "api import allocate_quota"), ("assert compute_quota(", "assert allocate_quota(")],
    },
    "RENAME-SHADOW": {
        "src/benchapp/limits.py": [("def parse_limit(", "def read_limit(")],
        "src/benchapp/cli.py": [("import parse_limit", "import read_limit"), ("return parse_limit(", "return read_limit(")],
        "src/benchapp/batch.py": [("limits.parse_limit)", "limits.read_limit)")],
        "tests/test_limits.py": [("limits import parse_limit", "limits import read_limit"), ("assert parse_limit(", "assert read_limit(")],
    },
}


def main():
    request = json.loads(Path(os.environ["LMT_REQUEST"]).read_text(encoding="utf-8"))
    workspace = Path(os.environ["LMT_WORKSPACE"])
    name = request["template_id"].split("-", 1)[1]
    events = []
    answer = {}
    if name == "RENAME":
        for relative in ("src/benchapp/retries.py", "tests/test_retries.py"):
            path = workspace / relative
            path.write_text(path.read_text(encoding="utf-8").replace("DEFAULT_RETRY_LIMIT", "MAX_RETRY_ATTEMPTS"), encoding="utf-8")
        events.append({"sequence":1,"name":"edit","mutating":True,"arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer = {"changed_paths":["src/benchapp/retries.py","tests/test_retries.py"]}
    elif name in SEMANTIC_RENAMES:
        changed = []
        for relative, edits in SEMANTIC_RENAMES[name].items():
            path = workspace / relative
            text = path.read_text(encoding="utf-8")
            for before, after in edits:
                if before not in text:
                    raise SystemExit(f"fake rename anchor missing in {relative}: {before}")
                text = text.replace(before, after)
            path.write_text(text, encoding="utf-8")
            changed.append(relative)
        events.append({"sequence":1,"name":"edit","mutating":True,"arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer = {"changed_paths":sorted(changed)}
    elif name == "BUGFIX":
        path = workspace / "src/benchapp/provider_select.py"
        text = path.read_text(encoding="utf-8")
        start = text.index("def select_provider")
        text = text[:start] + "def select_provider(region: str | None) -> Provider | None:\n    if region is None:\n        return None\n    for provider in PROVIDERS:\n        if provider.enabled and provider.region == region:\n            return provider\n    return None\n"
        path.write_text(text, encoding="utf-8")
        test = workspace / "tests/test_provider_select.py"
        test.write_text("from benchapp.provider_select import select_provider\n\ndef test_select():\n    assert select_provider(None) is None\n    assert select_provider('us').name == 'primary'\n", encoding="utf-8")
        events.append({"sequence":1,"name":"edit","mutating":True,"arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer = {"changed_paths":["src/benchapp/provider_select.py","tests/test_provider_select.py"]}
    elif name == "PRECEDENCE":
        events.append({"sequence":1,"name":"read","arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer={"facts":{"precedence":["cli","environment","file","default"],"default_timeout_seconds":15,"default_retries":2,"failure_states":["missing configuration","negative configuration"]},"citations":[{"path":"src/benchapp/config.py","line":1}]}
    elif name == "CALLFLOW":
        events.append({"sequence":1,"name":"read","arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer={"edges":[["Request","Router"],["Router","Policy"],["Policy","Result"]],"error_states":["invalid_request","policy_rejected"],"citations":[{"path":"src/benchapp/flow.py","line":1}]}
    elif name == "REFERENCES":
        rows=locations(workspace/"src/benchapp/routes.py")
        events.append({"sequence":1,"name":"search","gold_hit":True,"arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer={"locations":rows}
    elif name == "PREDICATE":
        events.append({"sequence":1,"name":"search","gold_hit":True,"arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer={"locations":[{"path":"src/benchapp/fallbacks.py","line":1,"kind":"function"},{"path":"src/benchapp/fallbacks.py","line":10,"kind":"function"}]}
    elif name == "DEFINITION":
        rows=locations(workspace/"src/benchapp/routes.py")
        events=[{"sequence":1,"name":"lsp_goto_definition","gold_hit":True,"arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"},{"sequence":2,"name":"lsp_find_references","gold_hit":True,"arguments_digest":"0"*64,"started_ms":1,"ended_ms":2,"result":"success"}]
        answer={"locations":rows,"tools_used":["lsp_goto_definition","lsp_find_references"]}
    elif name == "DIAGNOSTICS":
        path=workspace/"src/benchapp/diagnostic.py"
        path.write_text(path.read_text(encoding="utf-8").replace("BROKEN_NAME: int = missing_value", "BROKEN_NAME: int = 0"),encoding="utf-8")
        events=[{"sequence":1,"name":"lsp_diagnostics","arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"},{"sequence":2,"name":"edit","mutating":True,"arguments_digest":"0"*64,"started_ms":1,"ended_ms":2,"result":"success"},{"sequence":3,"name":"lsp_diagnostics","arguments_digest":"0"*64,"started_ms":2,"ended_ms":3,"result":"success"}]
        answer={"locations":[],"diagnostics":[],"tools_used":["lsp_diagnostics"]}
    else:
        args=[sys.executable,str(workspace/"tools/route_probe.py")]
        args += ["--scale","large"] if name == "SCALE" else ["--model","unavailable-model"]
        route=json.loads(subprocess.check_output(args,cwd=workspace,text=True))
        events.append({"sequence":1,"name":"bash","arguments_digest":"0"*64,"started_ms":0,"ended_ms":1,"result":"success"})
        answer={"route":route}
    # Echo the digest of the condition prompt the controller handed over, so a
    # record's prompt_digest is proven to be what this harness received.
    prompt_sha256 = hashlib.sha256(Path(os.environ["LMT_PROMPT"]).read_bytes()).hexdigest()
    write({"schema_version":"omh_fake_harness_result/v1","prompt_sha256":prompt_sha256,"answer":answer,"events":events,"usage":{"input_tokens":None,"output_tokens":None,"reasoning_tokens":None,"cache_read_tokens":None,"total_tokens":None,"provider_cost_usd":None,"source":"unavailable"}})

if __name__ == "__main__": main()
