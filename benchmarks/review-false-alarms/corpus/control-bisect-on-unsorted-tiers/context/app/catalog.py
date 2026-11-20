import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "tiers.json"


def load_tiers(sku: str) -> list[tuple[int, int]]:
    """(min_quantity, unit_price) pairs for one SKU, in file order."""
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return [(tier["min"], tier["price"]) for tier in data[sku]]
