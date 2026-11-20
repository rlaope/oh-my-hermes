from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.clock import utc_now

SESSION_TTL = timedelta(hours=12)


@dataclass
class Session:
    user_id: int
    expires_at: datetime = field(default_factory=lambda: utc_now() + SESSION_TTL)
