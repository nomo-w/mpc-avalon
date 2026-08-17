import asyncio
from collections import Counter

from avalon.game.rules import build_roles
from avalon.protocols.role_assignment.network_mental_poker import (
    run_network_mental_poker_role_assignment,
)

from tests.protocol_test_utils import (
    ProtocolAsyncTestCase,
    localhost_endpoints,
    unique_session,
)


class SecureRoleAssignmentProtocolTests(ProtocolAsyncTestCase):
    async def test_five_players_receive_valid_unique_role_cards(self):
        party_count = 5
        endpoints = localhost_endpoints(party_count)
        session_id = unique_session("role-assignment-test")

        tasks = [
            run_network_mental_poker_role_assignment(
                party_id=party_id,
                endpoints=endpoints,
                listen_host="127.0.0.1",
                session_id=session_id,
                connect_timeout=10.0,
            )
            for party_id in range(party_count)
        ]
        results = await asyncio.gather(*tasks)

        expected_roles = Counter(build_roles(party_count))
        actual_roles = Counter(result.role for result in results)
        self.assertEqual(actual_roles, expected_roles)
        self.assertEqual(len({result.card.card_id for result in results}), party_count)
        self.assertTrue(all(result.session_id == session_id for result in results))


if __name__ == "__main__":
    import unittest
    unittest.main()
