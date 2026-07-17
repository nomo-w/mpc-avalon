from enum import Enum


class AvalonError(ValueError):
    # Error for invalid game action, like wrong phase or wrong team size.
    pass


class Alignment(str, Enum):
    GOOD = "Good"
    EVIL = "Evil"


class Role(str, Enum):
    MERLIN = "Merlin"
    ASSASSIN = "Assassin"
    MINION = "Minion of Mordred"
    LOYAL_SERVANT = "Loyal Servant of Arthur"

    @property
    def alignment(self):
        if self in {Role.ASSASSIN, Role.MINION}:
            return Alignment.EVIL
        return Alignment.GOOD


class GamePhase(str, Enum):
    # Main phases used by server and client display.
    LOBBY = "LOBBY"
    TRUSTED_ROLE_ASSIGNMENT = "TRUSTED_ROLE_ASSIGNMENT"
    TEAM_PROPOSAL = "TEAM_PROPOSAL"
    TEAM_APPROVAL_VOTE = "TEAM_APPROVAL_VOTE"
    SECURE_MISSION_VOTE = "SECURE_MISSION_VOTE"
    MISSION_RESULT = "MISSION_RESULT"
    ASSASSINATION = "ASSASSINATION"
    GAME_OVER = "GAME_OVER"


class Player:
    # Public player info plus private role after assignment.
    def __init__(self, player_id, name, role=None, mpc_host="", mpc_port=0):
        self.player_id = player_id
        self.name = name
        self.role = role
        self.mpc_host = mpc_host
        self.mpc_port = mpc_port

    @property
    def alignment(self):
        if self.role is None:
            raise AvalonError("Role has not been assigned yet.")
        return self.role.alignment

    @property
    def is_evil(self):
        return self.alignment == Alignment.EVIL

    @property
    def is_merlin(self):
        return self.role == Role.MERLIN

    @property
    def is_assassin(self):
        return self.role == Role.ASSASSIN


class GameConfig:
    # Rule table for different player numbers.
    def __init__(self, num_players, mission_team_sizes, fail_thresholds, num_evil):
        self.num_players = num_players
        self.mission_team_sizes = mission_team_sizes
        self.fail_thresholds = fail_thresholds
        self.num_evil = num_evil


STANDARD_CONFIGS = {
    # mission_team_sizes means how many players go to each of 5 missions.
    # fail_thresholds means how many Fail votes make the mission fail.
    5: GameConfig(5, [2, 3, 2, 3, 3], [1, 1, 1, 1, 1], 2),
    6: GameConfig(6, [2, 3, 4, 3, 4], [1, 1, 1, 1, 1], 2),
    7: GameConfig(7, [2, 3, 3, 4, 4], [1, 1, 1, 2, 1], 3),
    8: GameConfig(8, [3, 4, 4, 5, 5], [1, 1, 1, 2, 1], 3),
    9: GameConfig(9, [3, 4, 4, 5, 5], [1, 1, 1, 2, 1], 3),
    10: GameConfig(10, [3, 4, 4, 5, 5], [1, 1, 1, 2, 1], 4),
}
