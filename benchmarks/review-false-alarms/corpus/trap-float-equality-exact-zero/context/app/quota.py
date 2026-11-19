def usage_label(used: int, limit: int) -> str:
    if limit <= 0:
        return "unlimited"
    ratio = used / limit
    if ratio == 0.0:
        return "unused"
    return f"{ratio:.0%} used"
