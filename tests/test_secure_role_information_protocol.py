import asyncio

from avalon.game.models import Role
from avalon.protocols.role_assignment.secure_role_information import (
    run_secure_role_information,
)

from tests.protocol_test_utils import (
    ProtocolAsyncTestCase,
    localhost_endpoints,
    unique_session,
)


class SecureRoleInformationProtocolTests(ProtocolAsyncTestCase):
    async def test_role_information_is_revealed_to_correct_players(self):
        roles = [
            Role.MERLIN,
            Role.ASSASSIN,
            Role.MINION,
            Role.LOYAL_SERVANT,
        ]
        player_names = ["Alice", "Bob", "Charlie", "David"]
        endpoints = localhost_endpoints(len(roles))
        session_id = unique_session("role-info-test")

        tasks = [
            run_secure_role_information(
                party_id=party_id,
                endpoints=endpoints,
                listen_host="127.0.0.1",
                session_id=session_id,
                local_role=roles[party_id],
                player_names=player_names,
                connect_timeout=10.0,
            )
            for party_id in range(len(roles))
        ]
        results = await asyncio.gather(*tasks)

        self.assertEqual(results[0].visible_evil_player_ids, [1, 2])
        self.assertEqual(results[1].visible_evil_player_ids, [2])
        self.assertEqual(results[2].visible_evil_player_ids, [1])
        self.assertEqual(results[3].visible_evil_player_ids, [])

        self.assertIn("Merlin information", "\n".join(results[0].private_lines))
        self.assertIn("Other evil players", "\n".join(results[1].private_lines))
        self.assertIn("no additional information", "\n".join(results[3].private_lines))


if __name__ == "__main__":
    import unittest
    unittest.main()
