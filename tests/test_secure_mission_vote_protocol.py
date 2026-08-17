import asyncio

from avalon.protocols.mission_voting.secure_vote.circuits import (
    mission_failed_reference,
)
from avalon.protocols.mission_voting.secure_vote.protocol import (
    MissionVoteConfiguration,
    run_secure_mission_vote,
)

from tests.protocol_test_utils import (
    ProtocolAsyncTestCase,
    localhost_endpoints,
    unique_session,
)


class SecureMissionVoteProtocolTests(ProtocolAsyncTestCase):
    async def run_vote(self, votes, fail_threshold):
        endpoints = localhost_endpoints(len(votes))
        session_id = unique_session("mission-vote-test")
        configuration = MissionVoteConfiguration.create(
            session_id=session_id,
            team_ids=tuple(range(len(votes))),
            fail_threshold=fail_threshold,
            party_count=len(votes),
        )
        tasks = [
            run_secure_mission_vote(
                party_id=party_id,
                endpoints=endpoints,
                listen_host="127.0.0.1",
                configuration=configuration,
                local_fail_vote=votes[party_id],
                connect_timeout=10.0,
            )
            for party_id in range(len(votes))
        ]
        return await asyncio.gather(*tasks)

    async def test_threshold_one_fails_with_one_fail_vote(self):
        votes = [0, 0, 1]
        outcomes = await self.run_vote(votes, fail_threshold=1)

        expected = mission_failed_reference(votes, 1)
        self.assertTrue(expected)
        self.assertTrue(all(outcome.mission_failed == expected for outcome in outcomes))
        self.assertEqual(len({outcome.session_id for outcome in outcomes}), 1)
        self.assertTrue(all(outcome.statistics.and_gates > 0 for outcome in outcomes))

    async def test_threshold_one_succeeds_with_all_success_votes(self):
        votes = [0, 0, 0]
        outcomes = await self.run_vote(votes, fail_threshold=1)

        expected = mission_failed_reference(votes, 1)
        self.assertFalse(expected)
        self.assertTrue(all(outcome.mission_failed == expected for outcome in outcomes))

    async def test_threshold_two_needs_two_fail_votes(self):
        one_fail = [1, 0, 0]
        one_fail_outcomes = await self.run_vote(one_fail, fail_threshold=2)
        self.assertFalse(mission_failed_reference(one_fail, 2))
        self.assertTrue(all(not outcome.mission_failed for outcome in one_fail_outcomes))

        two_fails = [1, 1, 0]
        two_fail_outcomes = await self.run_vote(two_fails, fail_threshold=2)
        self.assertTrue(mission_failed_reference(two_fails, 2))
        self.assertTrue(all(outcome.mission_failed for outcome in two_fail_outcomes))


if __name__ == "__main__":
    import unittest
    unittest.main()
