import unittest
from collections import Counter

from avalon.game.models import AvalonError, STANDARD_CONFIGS, Role
from avalon.game.rules import build_roles


class GameRulesTests(unittest.TestCase):
    def test_standard_configs_cover_5_to_10_players(self):
        self.assertEqual(set(STANDARD_CONFIGS), {5, 6, 7, 8, 9, 10})
        for player_count, config in STANDARD_CONFIGS.items():
            self.assertEqual(config.num_players, player_count)
            self.assertEqual(len(config.mission_team_sizes), 5)
            self.assertEqual(len(config.fail_thresholds), 5)

    def test_five_player_roles_match_avalon_rules(self):
        roles = build_roles(5)
        counts = Counter(roles)
        self.assertEqual(len(roles), 5)
        self.assertEqual(counts[Role.MERLIN], 1)
        self.assertEqual(counts[Role.ASSASSIN], 1)
        self.assertEqual(counts[Role.MINION], 1)
        self.assertEqual(counts[Role.LOYAL_SERVANT], 2)

    def test_larger_games_have_correct_number_of_evil_players(self):
        for player_count, config in STANDARD_CONFIGS.items():
            roles = build_roles(player_count)
            evil_count = sum(1 for role in roles if role.alignment.value == "Evil")
            self.assertEqual(evil_count, config.num_evil)

    def test_seven_or_more_players_need_two_fails_on_fourth_mission(self):
        for player_count in range(7, 11):
            config = STANDARD_CONFIGS[player_count]
            self.assertEqual(config.fail_thresholds[3], 2)

    def test_invalid_player_count_is_rejected(self):
        with self.assertRaises(AvalonError):
            build_roles(4)
        with self.assertRaises(AvalonError):
            build_roles(11)


if __name__ == "__main__":
    unittest.main()
