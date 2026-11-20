from datetime import timedelta
import unittest
from unittest import mock

from app import sessions
from app.clock import utc_now
from app.models import Session


class SessionTests(unittest.TestCase):
    def test_expires_at_is_naive_utc(self):
        self.assertIsNone(Session(user_id=1).expires_at.tzinfo)
        self.assertIsNone(utc_now().tzinfo)

    def test_expired_after_ttl(self):
        session = Session(user_id=1)
        later = session.expires_at + timedelta(seconds=1)
        with mock.patch.object(sessions, "utc_now", return_value=later):
            self.assertTrue(sessions.is_expired(session))
            self.assertEqual(sessions.remaining(session), timedelta(0))
