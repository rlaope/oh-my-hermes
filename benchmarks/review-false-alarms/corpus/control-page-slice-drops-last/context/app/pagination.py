def page(items: list, number: int, size: int) -> list:
    """Items on page `number` (1-based), at most `size` of them."""
    if number < 1 or size < 1:
        raise ValueError("page number and size start at 1")
    start = (number - 1) * size
    end = start + size - 1
    return items[start:end]
