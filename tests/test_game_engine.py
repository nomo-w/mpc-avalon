import unittest

from avalon.game.engine import AvalonEngine
from avalon.game.models import Alignment, AvalonError, GamePhase


def make_engine():
    return AvalonEngine(["Alice", "Bob", "Charlie", "David", "Eve"])


def set_team_proposal_phase(engine):
    engine.set_phase(GamePhase.TEAM_PROPOSAL)


class GameEngineTests(unittest.TestCase):
    def test_engine_rejects_bad_player_setup(self):
        with self.assertRaises(AvalonError):
            AvalonEngine(["A", "B", "C", "D"])
        with self.assertRaises(AvalonError):
            AvalonEngine(["A", "B", "C", "D", "D"])
        with self.assertRaises(AvalonError):
            AvalonEngine(
                ["A", "B", "C", "D", "E"],
                mpc_endpoints=[("127.0.0.1", 1)],
            )

    def test_only_leader_can_propose_valid_team(self):
        engine = make_engine()
        set_team_proposal_phase(engine)

        with self.assertRaises(AvalonError):
            engine.propose_team(actor_id=1, team_ids=[0, 1])
        with self.assertRaises(AvalonError):
            engine.propose_team(actor_id=0, team_ids=[0])
        with self.assertRaises(AvalonError):
            engine.propose_team(actor_id=0, team_ids=[0, 0])
        with self.assertRaises(AvalonError):
            engine.propose_team(actor_id=0, team_ids=[0, 9])

        team = engine.propose_team(actor_id=0, team_ids=[0, 1])
        self.assertEqual(team, [0, 1])
        self.assertEqual(engine.phase, GamePhase.TEAM_APPROVAL_VOTE)

    def test_team_vote_approval_moves_to_secure_mission_vote(self):
        engine = make_engine()
        set_team_proposal_phase(engine)
        engine.propose_team(actor_id=0, team_ids=[0, 1])

        self.assertFalse(engine.submit_team_vote(0, True))
        with self.assertRaises(AvalonError):
            engine.submit_team_vote(0, False)
        with self.assertRaises(AvalonError):
            engine.resolve_team_vote()

        engine.submit_team_vote(1, True)
        engine.submit_team_vote(2, True)
        engine.submit_team_vote(3, False)
        complete = engine.submit_team_vote(4, False)
        self.assertTrue(complete)

        approved, approvals, rejects = engine.resolve_team_vote()
        self.assertTrue(approved)
        self.assertEqual(approvals, 3)
        self.assertEqual(rejects, 2)

        engine.apply_team_vote_result(approved)
        self.assertEqual(engine.phase, GamePhase.SECURE_MISSION_VOTE)

    def test_five_rejected_teams_make_evil_win(self):
        engine = make_engine()
        set_team_proposal_phase(engine)

        for _ in range(5):
            leader = engine.leader_id
            team = [leader, (leader + 1) % len(engine.players)]
            engine.propose_team(actor_id=leader, team_ids=team)
            for player_id in range(len(engine.players)):
                engine.submit_team_vote(player_id, False)
            approved, _, _ = engine.resolve_team_vote()
            engine.apply_team_vote_result(approved)

        self.assertTrue(engine.game_over)
        self.assertEqual(engine.phase, GamePhase.GAME_OVER)
        self.assertEqual(engine.winner, Alignment.EVIL)

    def test_secure_vote_results_must_come_from_team_and_match(self):
        engine = make_engine()
        engine.current_team = [0, 1]
        engine.set_phase(GamePhase.SECURE_MISSION_VOTE)

        with self.assertRaises(AvalonError):
            engine.submit_secure_vote_result(3, "s1", "s1", False)
        with self.assertRaises(AvalonError):
            engine.submit_secure_vote_result(0, "wrong", "s1", False)

        self.assertFalse(engine.submit_secure_vote_result(0, "s1", "s1", True))
        with self.assertRaises(AvalonError):
            engine.submit_secure_vote_result(0, "s1", "s1", True)
        self.assertTrue(engine.submit_secure_vote_result(1, "s1", "s1", False))

        with self.assertRaises(AvalonError):
            engine.resolve_secure_vote_results()

    def test_mission_scores_update_winner_and_phase(self):
        engine = make_engine()
        for _ in range(3):
            engine.current_team = [0, 1]
            engine.set_phase(GamePhase.SECURE_MISSION_VOTE)
            engine.apply_mission_result(mission_failed=False)

        self.assertFalse(engine.game_over)
        self.assertEqual(engine.successful_missions, 3)
        self.assertEqual(engine.phase, GamePhase.ASSASSINATION)

        engine = make_engine()
        for _ in range(3):
            engine.current_team = [0, 1]
            engine.set_phase(GamePhase.SECURE_MISSION_VOTE)
            engine.apply_mission_result(mission_failed=True)

        self.assertTrue(engine.game_over)
        self.assertEqual(engine.failed_missions, 3)
        self.assertEqual(engine.winner, Alignment.EVIL)

    def test_assassination_result_uses_hidden_merlin_check(self):
        engine = make_engine()
        engine.set_phase(GamePhase.ASSASSINATION)
        winner = engine.resolve_assassination_from_hidden_check(1, True)
        self.assertEqual(winner, Alignment.EVIL)

        engine = make_engine()
        engine.set_phase(GamePhase.ASSASSINATION)
        winner = engine.resolve_assassination_from_hidden_check(1, False)
        self.assertEqual(winner, Alignment.GOOD)

        engine = make_engine()
        engine.set_phase(GamePhase.ASSASSINATION)
        with self.assertRaises(AvalonError):
            engine.resolve_assassination_from_hidden_check(99, False)


if __name__ == "__main__":
    unittest.main()
