import unittest

from omh.coding import unit_execution_state as ues


class UnitExecutionStateVocabularyTests(unittest.TestCase):
    def test_every_state_is_exactly_one_of_terminal_stuck_or_running(self):
        for state in ues.UNIT_EXECUTION_STATES:
            memberships = [
                state in ues.UNIT_TERMINAL_STATES,
                state in ues.UNIT_STUCK_STATES,
                state == ues.UNIT_STATE_RUNNING,
            ]
            self.assertEqual(sum(memberships), 1, state)

    def test_verified_is_the_only_success_state(self):
        successes = [s for s in ues.UNIT_EXECUTION_STATES if s == ues.UNIT_STATE_VERIFIED]
        self.assertEqual(successes, ["verified"])
        self.assertTrue(ues.is_terminal("verified"))
        self.assertTrue(ues.is_terminal("failed"))
        self.assertFalse(ues.is_terminal("running"))

    def test_unverified_ends_a_unit_without_claiming_success_or_failure(self):
        # #2461: completed work whose verification was never observed.
        self.assertTrue(ues.is_terminal("unverified"))
        self.assertFalse(ues.is_stuck("unverified"))
        self.assertNotIn(ues.UNIT_STATE_UNVERIFIED, (ues.UNIT_STATE_FAILED, ues.UNIT_STATE_VERIFIED))

    def test_a_stalled_unit_is_stuck_not_terminal_and_not_running(self):
        self.assertTrue(ues.is_stuck("progress_stalled"))
        self.assertFalse(ues.is_terminal("progress_stalled"))
        self.assertNotEqual(ues.UNIT_STATE_PROGRESS_STALLED, ues.UNIT_STATE_RUNNING)


if __name__ == "__main__":
    unittest.main()
