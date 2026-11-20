from app.clock import utc_now


def is_valid(token) -> bool:
    if token.revoked:
        return False
    return token.expires_at > utc_now()
