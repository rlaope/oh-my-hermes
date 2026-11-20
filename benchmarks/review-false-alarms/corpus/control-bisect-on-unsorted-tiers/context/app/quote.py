from app import catalog
from app.prices import price_for


def quote(sku: str, quantity: int) -> int:
    tiers = catalog.load_tiers(sku)
    return price_for(tiers, quantity) * quantity
