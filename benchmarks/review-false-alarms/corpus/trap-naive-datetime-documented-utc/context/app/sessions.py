from datetime import timedelta

from app.clock import utc_now


def is_expired(session) -> bool:
    return session.expires_at <= utc_now()


def remaining(session) -> timedelta:
    return max(session.expires_at - utc_now(), timedelta(0))
