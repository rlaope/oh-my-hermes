"""`bigfile-ab` split: work that lives deep inside one large Python module.

Measures the read outline (`src/plugin_bundle/omh/read_outline.py`): a truncated
`read_file` of a large file gains the whole file's symbols with line ranges.
Both templates put the module at 4,500-5,500 lines (past Hermes' 2,000-line
read window and its 100,000-character budget) and the work past line 3,000:

- `B-DEEP-BUG`: a pricing helper defined past line 3,000 has an off-by-one
  threshold. The failing test names the symptom (a crate of exactly N pieces is
  quoted like loose pieces), never the helper or the line.
- `B-DEEP-RENAME`: rename a public function defined past line 3,000, used near
  the top of the module, deep in it, in a second module and in the tests, next
  to a same-named method, a log string and a comment that must stay.

The filler is generated, seeded and parseable: classes of rate tables whose
methods do arithmetic, so the module reads like a real one and is not a page of
repeated lines. Expected quotes come from executing the CORRECT module text at
materialize time, so the golden never hand-copies a number.
"""

from __future__ import annotations

import ast
import random
from typing import Any

BIGFILE_AB_SPLIT = "bigfile-ab"
BIGFILE_AB_TEMPLATES = (("DEEP-BUG", "edit"), ("DEEP-RENAME", "edit"))
MODULE = "src/benchapp/tariffs.py"
INVOICE = "src/benchapp/invoice.py"
TESTS = "tests/test_tariffs.py"
OLD_NAME = "consolidation_credit"
NEW_NAME = "bulk_piece_credit"

_NOUNS = ("parcel", "freight", "pallet", "courier", "customs", "harbor", "depot", "transit", "cargo", "relay",
          "ferry", "convoy", "dock", "berth", "hub", "lane", "sorting", "airway", "railhead", "bonded")
_VERBS = ("price", "weigh", "score", "rank", "scale", "settle", "clamp", "spread", "blend", "audit")
_FIELDS = ("weight", "distance", "volume", "pieces", "value", "fuel", "night", "remote", "fragile", "priority")
_SUFFIXES = ("Table", "Ledger", "Schedule", "Matrix", "Grid", "Band")


def _method(randomizer: random.Random, verb: str, field: str, noun: str) -> list[str]:
    k = [randomizer.randint(2, 97) for _ in range(6)]
    shape = randomizer.randrange(4)
    head = [f"    def {verb}_{field}(self, amount: int) -> int:",
            f'        """{verb.capitalize()} the {field} component of one {noun} leg."""']
    if shape == 0:
        body = ["        total = 0",
                "        for step, rate in enumerate(self.rates):",
                f"            if amount > rate * {k[0]}:",
                f"                total += rate * (step + {k[1]})",
                "            else:",
                f"                total -= {k[2]}",
                f"        if total < {k[3]}:",
                f"            total = {k[3]}",
                f"        return total + {k[4]}"]
    elif shape == 1:
        body = [f"        window = [rate for rate in self.rates if rate % {k[0] % 7 + 2} != 0]",
                "        if not window:",
                f"            return amount * {k[1]}",
                f"        peak = max(window) + {k[2]}",
                f"        floor = min(window) - {k[3]}",
                f"        return (amount * peak - floor) // {k[4] % 9 + 1}"]
    elif shape == 2:
        body = [f"        bands = {{'low': {k[0]}, 'mid': {k[1]}, 'high': {k[2]}}}",
                f"        if amount < bands['low']:",
                f"            key = 'low'",
                f"        elif amount < bands['low'] + bands['mid']:",
                f"            key = 'mid'",
                "        else:",
                f"            key = 'high'",
                f"        return bands[key] * len(self.rates) + amount % {k[3] % 11 + 2}"]
    else:
        body = ["        acc = amount",
                "        for rate in self.rates:",
                f"            acc = (acc * {k[0] % 5 + 1} + rate) % {k[1] * 100 + 7}",
                f"        if acc % {k[2] % 3 + 2} == 0:",
                f"            acc += {k[3]}",
                f"        return acc - {k[4] % 13}"]
    return head + body + [""]


def _filler_class(randomizer: random.Random, index: int) -> list[str]:
    noun = randomizer.choice(_NOUNS)
    name = f"{noun.capitalize()}{randomizer.choice(_SUFFIXES)}{index}"
    rates = [randomizer.randint(1, 60) for _ in range(randomizer.randint(4, 9))]
    lines = [f"class {name}:", f'    """Rate table for {noun} legs (block {index})."""', "",
             "    def __init__(self) -> None:", f"        self.rates = {rates!r}", ""]
    fields = randomizer.sample(_FIELDS, randomizer.randint(5, 8))
    for field in fields:
        lines += _method(randomizer, randomizer.choice(_VERBS), field, noun)
    return lines + ["", ""]


def _sections(seed: int, threshold: int, percent: int) -> dict[str, list[str]]:
    """The code blocks that matter, keyed by where they go."""
    fixed_compare = "    if pieces < CONSOLIDATION_THRESHOLD:"
    return {
        "head": [
            '"""Shipping tariff engine: quotes in cents for one shipment."""',
            "",
            "import logging",
            "",
            "LOG = logging.getLogger(__name__)",
            "",
            f"MINIMUM_CHARGE_CENTS = {200 + seed % 50}",
            f"CONSOLIDATION_THRESHOLD = {threshold}",
            f"CREDIT_PERCENT = {percent}",
            f"EXPRESS_PERCENT = {120 + seed % 30}",
            f"ZONE_BASE_CENTS = {{'A': {300 + seed % 40}, 'B': {420 + seed % 35}, 'C': {610 + seed % 45}}}",
            "",
            "",
            "class Shipment:",
            '    """One shipment as the quote sees it."""',
            "",
            "    def __init__(self, weight_grams: int, zone: str, pieces: int, declared_value: int, express: bool = False) -> None:",
            "        self.weight_grams = weight_grams",
            "        self.zone = zone",
            "        self.pieces = pieces",
            "        self.declared_value = declared_value",
            "        self.express = express",
            "",
            "",
            "def quote_shipment(shipment: Shipment) -> int:",
            '    """Price one shipment in cents."""',
            "    total = zone_base_cents(shipment.zone) + weight_cents(shipment.weight_grams)",
            "    total += insurance_cents(shipment.declared_value)",
            f"    total -= {OLD_NAME}(shipment.pieces, total)",
            "    if shipment.express:",
            "        total = express_uplift(total)",
            "    return max(total, MINIMUM_CHARGE_CENTS)",
            "",
            "",
        ],
        "zone": [
            "def zone_base_cents(zone: str) -> int:",
            '    """Base charge for the destination zone; unknown zones price as the dearest."""',
            "    return ZONE_BASE_CENTS.get(zone, max(ZONE_BASE_CENTS.values()))",
            "",
            "",
        ],
        "weight": [
            "def weight_cents(weight_grams: int) -> int:",
            '    """Weight charge: every started 500 g costs the same."""',
            "    started = -(-weight_grams // 500)",
            f"    return started * {35 + seed % 20}",
            "",
            "",
        ],
        "audit": [
            "def audit_crate_quote(pieces: int, subtotal: int) -> str:",
            '    """A one-line audit trail for a crate quote."""',
            f"    return f'pieces={{pieces}} credit={{{OLD_NAME}(pieces, subtotal)}}'",
            "",
            "",
        ],
        "insurance": [
            "def insurance_cents(declared_value: int) -> int:",
            '    """Insurance on the declared value, nothing under the free allowance."""',
            f"    allowance = {5000 + seed % 1000}",
            "    if declared_value <= allowance:",
            "        return 0",
            "    return (declared_value - allowance) // 100",
            "",
            "",
        ],
        "credit": [
            f"def {OLD_NAME}(pieces: int, subtotal: int) -> int:",
            '    """Credit for a multi-piece crate, once it reaches the threshold; capped at three tiers."""',
            "    # The crate rule: a full crate ships cheaper than its pieces would loose.",
            fixed_compare,
            "        return 0",
            "    tier = min(pieces // CONSOLIDATION_THRESHOLD, 3)",
            "    return subtotal * tier * CREDIT_PERCENT // 100",
            "",
            "",
            "class LegacyCrate:",
            '    """The pre-2024 crate rule, kept for archived invoices."""',
            "",
            f"    def {OLD_NAME}(self) -> int:",
            f"        return {10 + seed % 9}",
            "",
            "",
        ],
        "estimator": [
            "class CrateEstimator:",
            '    """Estimates a crate\'s credit before the shipment exists."""',
            "",
            "    def estimate(self, pieces: int, subtotal: int) -> int:",
            "        try:",
            f"            return {OLD_NAME}(pieces, subtotal)",
            "        except ValueError:",
            f'            LOG.warning("{OLD_NAME} failed for an estimate")',
            "            raise",
            "",
            "",
        ],
        "express": [
            "def express_uplift(total: int) -> int:",
            '    """Express shipments pay a percentage on top."""',
            "    return total * EXPRESS_PERCENT // 100",
            "",
            "",
        ],
    }


# Where each block lands, as a fraction of the filler, then a line floor the
# deep blocks must clear.
_PLACEMENT = (("zone", 0.16), ("weight", 0.34), ("audit", 0.45), ("insurance", 0.55),
              ("credit", 0.72), ("estimator", 0.86), ("express", 0.94))
_DEEP_FLOOR = {"credit": 3000, "estimator": 3000}


def module_text(seed: int) -> tuple[str, dict[str, int]]:
    """The CORRECT module and the first line of each placed block."""
    randomizer = random.Random(seed * 7 + 1)
    threshold = randomizer.randint(8, 12)
    percent = randomizer.randint(6, 14)
    sections = _sections(seed, threshold, percent)
    fillers = [_filler_class(randomizer, index) for index in range(randomizer.randint(60, 68))]
    filler_lines = sum(len(block) for block in fillers)
    lines = list(sections["head"])
    starts: dict[str, int] = {}
    placements = iter(_PLACEMENT)
    pending = next(placements, None)
    written = 0
    for block in fillers:
        lines += block
        written += len(block)
        while pending is not None and written >= pending[1] * filler_lines and len(lines) >= _DEEP_FLOOR.get(pending[0], 0):
            starts[pending[0]] = len(lines) + 1
            lines += sections[pending[0]]
            pending = next(placements, None)
    while pending is not None:
        starts[pending[0]] = len(lines) + 1
        lines += sections[pending[0]]
        pending = next(placements, None)
    return "\n".join(lines).rstrip("\n") + "\n", {**starts, "threshold": threshold}


_CASES = ((1, 400, "A", 0, False), (3, 2600, "B", 7000, False), (-1, 1200, "C", 0, False),
          (0, 900, "A", 0, False), (1, 900, "B", 9000, True), (0, 5100, "C", 12000, True),
          (2, 1500, "Z", 0, False), (5, 700, "A", 0, False))


def _quote_cases(text: str, threshold: int) -> list[dict[str, Any]]:
    namespace: dict[str, Any] = {"__name__": "bigfile_reference"}
    exec(compile(text, "tariffs_reference.py", "exec"), namespace)  # noqa: S102 - our own generated source
    cases = []
    for offset, weight, zone, value, express in _CASES:
        pieces = max(1, threshold + offset) if offset != 5 else threshold * 5
        shipment = namespace["Shipment"](weight, zone, pieces, value, express)
        cases.append({"args": [weight, zone, pieces, value, express], "cents": namespace["quote_shipment"](shipment)})
    return cases


def bigfile_fixture(name: str, seed: int) -> tuple[dict[str, str], dict[str, Any]]:
    text, starts = module_text(seed)
    threshold = starts["threshold"]
    cases = _quote_cases(text, threshold)
    crate = next(case for case in cases if case["args"][2] == threshold)
    loose = next(case for case in cases if case["args"][2] == threshold - 1)
    invoice = (
        f"from benchapp.tariffs import Shipment, {OLD_NAME}, quote_shipment\n\n\n"
        "def invoice_line(shipment: Shipment) -> str:\n"
        f"    credit = {OLD_NAME}(shipment.pieces, quote_shipment(shipment))\n"
        "    return f'{shipment.pieces} pieces, credit {credit}'\n"
    )
    args = ", ".join(repr(value) for value in crate["args"])
    loose_args = ", ".join(repr(value) for value in loose["args"])
    tests = (
        "from benchapp.tariffs import Shipment, quote_shipment\n\n\n"
        "def test_single_parcel_quote():\n"
        f"    assert quote_shipment(Shipment({loose_args})) == {loose['cents']}\n\n\n"
        "def test_full_crate_quote():\n"
        f"    # A crate of exactly {threshold} pieces.\n"
        f"    assert quote_shipment(Shipment({args})) == {crate['cents']}\n"
    )
    if name == "DEEP-BUG":
        fixed = "    if pieces < CONSOLIDATION_THRESHOLD:"
        buggy = "    if pieces <= CONSOLIDATION_THRESHOLD:"
        if text.count(fixed) != 1:
            raise AssertionError("bigfile fixture: the fixed comparison must occur once")
        files = {MODULE: text.replace(fixed, buggy), INVOICE: invoice, TESTS: tests}
        golden = {"allowed_paths": [MODULE, TESTS], "cases": cases, "min_tests": 2, "bug_line": text.splitlines().index(fixed) + 1}
        return files, golden
    if name == "DEEP-RENAME":
        files = {MODULE: text, INVOICE: invoice, TESTS: tests}
        preserved = [line for line in text.splitlines() if "LOG.warning(" in line or line.startswith("    # The crate rule")]
        golden = {"allowed_paths": [INVOICE, MODULE, TESTS], "cases": cases, "min_tests": 2,
                  "legacy": 10 + seed % 9, "preserved_lines": {MODULE: preserved},
                  "definition_line": starts["credit"]}
        return files, golden
    raise ValueError(f"unknown bigfile template {name}")


def prompt(name: str, seed: int) -> str:
    threshold = module_text(seed)[1]["threshold"]
    if name == "DEEP-BUG":
        return (f"The test tests/test_tariffs.py::test_full_crate_quote fails: a shipment of exactly {threshold} "
                "pieces is quoted as if it got no crate discount. Find the cause in the benchapp package and fix it "
                "without changing any other behavior. Return JSON with changed_paths.")
    if name == "DEEP-RENAME":
        return (f"Rename the module-level function {OLD_NAME} in src/benchapp/tariffs.py to {NEW_NAME} at its "
                "definition and everywhere it is referenced, without changing behavior. Keep the unrelated "
                f"LegacyCrate.{OLD_NAME} method, string literals and comments unchanged. Return JSON with changed_paths.")
    raise ValueError(f"unknown bigfile template {name}")


_PROBE_CHECKS = """
from benchapp import tariffs
from benchapp.invoice import invoice_line
for case in CASES:
    weight, zone, pieces, value, express = case["args"]
    got = tariffs.quote_shipment(tariffs.Shipment(weight, zone, pieces, value, express))
    assert got == case["cents"], (case, got)
"""


def bigfile_ok(name: str, workspace: Any, golden: dict[str, Any], behaviour_ok: Any) -> bool:
    """Semantic check; ``behaviour_ok(workspace, test_file, checks, min_tests)`` runs checks and tests fresh."""
    checks = f"CASES = {golden['cases']!r}\n{_PROBE_CHECKS}"
    if name == "DEEP-BUG":
        ast.parse((workspace / MODULE).read_text(encoding="utf-8"))
        return behaviour_ok(workspace, TESTS, checks, golden["min_tests"])
    if name != "DEEP-RENAME":
        return False
    sources = {relative: (workspace / relative).read_text(encoding="utf-8") for relative in golden["allowed_paths"]}
    trees = {relative: ast.parse(text) for relative, text in sources.items()}
    module = trees[MODULE]
    functions = {node.name for node in module.body if isinstance(node, ast.FunctionDef)}
    if OLD_NAME in functions or NEW_NAME not in functions:
        return False
    legacy = next((node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "LegacyCrate"), None)
    if legacy is None or OLD_NAME not in {node.name for node in legacy.body if isinstance(node, ast.FunctionDef)}:
        return False
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == OLD_NAME for alias in node.names):
                return False
            if isinstance(node, ast.Name) and node.id == OLD_NAME:
                return False
    present = sources[MODULE].splitlines()
    if any(line not in present for line in golden["preserved_lines"][MODULE]):
        return False
    checks += (
        f"from benchapp.tariffs import LegacyCrate, CrateEstimator, {NEW_NAME}, audit_crate_quote\n"
        f"assert LegacyCrate().{OLD_NAME}() == {golden['legacy']}\n"
        f"assert CrateEstimator().estimate(30, 1000) == {NEW_NAME}(30, 1000)\n"
        f"assert audit_crate_quote(30, 1000) == f'pieces=30 credit={{{NEW_NAME}(30, 1000)}}'\n"
        "assert invoice_line(tariffs.Shipment(400, 'A', 30, 0)).startswith('30 pieces, credit ')\n"
    )
    return behaviour_ok(workspace, TESTS, checks, golden["min_tests"])


def reference_edit(name: str, workspace: Any) -> list[str]:
    """What a correct fix or rename writes (fake harness and tests)."""
    if name == "DEEP-BUG":
        path = workspace / MODULE
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("    if pieces <= CONSOLIDATION_THRESHOLD:", "    if pieces < CONSOLIDATION_THRESHOLD:"),
                        encoding="utf-8")
        return [MODULE]
    changed = []
    for relative in (INVOICE, MODULE):
        path = workspace / relative
        text = path.read_text(encoding="utf-8")
        text = text.replace(f"def {OLD_NAME}(pieces", f"def {NEW_NAME}(pieces")
        text = text.replace(f"{OLD_NAME}(shipment.pieces", f"{NEW_NAME}(shipment.pieces")
        text = text.replace(f"{{{OLD_NAME}(pieces, subtotal)}}", f"{{{NEW_NAME}(pieces, subtotal)}}")
        text = text.replace(f"return {OLD_NAME}(pieces, subtotal)", f"return {NEW_NAME}(pieces, subtotal)")
        text = text.replace(f"Shipment, {OLD_NAME}, quote_shipment", f"Shipment, {NEW_NAME}, quote_shipment")
        path.write_text(text, encoding="utf-8")
        changed.append(relative)
    return sorted(changed)
