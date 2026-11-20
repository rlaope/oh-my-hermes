"""The app's one clock.

Every timestamp this app stores or compares is a naive datetime in UTC: the
database column has no zone, and mixing aware and naive values raises. Use
utc_now() instead of datetime.now().
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
