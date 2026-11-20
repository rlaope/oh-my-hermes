from datetime import datetime, timezone


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(timezone.utc)
