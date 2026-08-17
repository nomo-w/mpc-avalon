import unittest

from avalon.protocols.mission_voting.secure_vote.circuits import (
    mission_failed_reference,
    role_knowledge_reference,
)


class MissionReferenceTests(unittest.TestCase):
    def test_threshold_one_reference(self):
        self.assertFalse(mission_failed_reference([0, 0, 0], 1))
        self.assertTrue(mission_failed_reference([0, 0, 1], 1))
        self.assertTrue(mission_failed_reference([1, 1, 0], 1))

    def test_threshold_two_reference(self):
        self.assertFalse(mission_failed_reference([1, 0, 0, 0, 0], 2))
        self.assertTrue(mission_failed_reference([1, 1, 0, 0, 0], 2))

    def test_reference_rejects_bad_votes(self):
        with self.assertRaises(ValueError):
            mission_failed_reference([], 1)
        with self.assertRaises(ValueError):
            mission_failed_reference([0, 2], 1)
        with self.assertRaises(ValueError):
            mission_failed_reference([0, 1], 3)

    def test_role_knowledge_reference(self):
        self.assertEqual(role_knowledge_reference(1, 0, 1, 0), 1)
        self.assertEqual(role_knowledge_reference(0, 1, 1, 0), 1)
        self.assertEqual(role_knowledge_reference(0, 1, 1, 1), 0)
        self.assertEqual(role_knowledge_reference(0, 0, 1, 0), 0)

        with self.assertRaises(ValueError):
            role_knowledge_reference(2, 0, 1, 0)


if __name__ == "__main__":
    unittest.main()
