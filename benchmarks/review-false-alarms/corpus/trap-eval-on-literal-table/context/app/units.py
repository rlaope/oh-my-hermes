# Kept as text so the table reads the way the spec sheet writes it.
_FACTORS = {
    "km": "1000",
    "m": "1",
    "cm": "1 / 100",
    "mm": "1 / 1000",
    "um": "1 / 1000000",
}
_SCALE = {unit: float(eval(expr, {"__builtins__": {}}, {})) for unit, expr in _FACTORS.items()}


def to_metres(value: float, unit: str) -> float:
    return value * _SCALE[unit]
