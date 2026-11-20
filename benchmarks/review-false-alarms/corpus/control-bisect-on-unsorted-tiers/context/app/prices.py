import bisect


def price_for(tiers: list[tuple[int, int]], quantity: int) -> int:
    """Unit price in cents for quantity; tiers are (min_quantity, unit_price) pairs."""
    thresholds = [min_quantity for min_quantity, _ in tiers]
    index = bisect.bisect_right(thresholds, quantity) - 1
    return tiers[max(index, 0)][1]
