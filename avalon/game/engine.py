import random

from .models import (
    Alignment,
    AvalonError,
    GamePhase,
    Player,
    Role,
    STANDARD_CONFIGS,
)


# This file is the normal Avalon rule engine.
# It does not do network and does not do crypto.
# Server calls this class to check teams, votes, mission result and winner.


class PublicSnapshot:
    def __init__(self, phase, players, leader_id, mission_number, mission_team_size, fail_threshold, successful_missions, failed_missions, rejected_team_proposals, current_team, winner):
        self.phase = phase
        self.players = players
        self.leader_id = leader_id
        self.mission_number = mission_number
        self.mission_team_size = mission_team_size
        self.fail_threshold = fail_threshold
        self.successful_missions = successful_missions
        self.failed_missions = failed_missions
        self.rejected_team_proposals = rejected_team_proposals
        self.current_team = current_team
        self.winner = winner


class AvalonEngine:
    def __init__(self, player_names, seed=None, mpc_endpoints=None):
        self.player_names = player_names
        self.seed = seed
        self.mpc_endpoints = mpc_endpoints
        self.phase = GamePhase.LOBBY
        self.leader_id = 0
        self.mission_index = 0
        self.successful_missions = 0
        self.failed_missions = 0
        self.rejected_team_proposals = 0
        self.current_team = []
        self.team_votes = {}
        self.secure_vote_results = {}
        self.game_over = False
        self.winner = None

        # Basic player and config check.
        names = [name.strip() for name in self.player_names if name.strip()]
        if len(names) not in STANDARD_CONFIGS:
            raise AvalonError("Please provide between 5 and 10 player names.")
        if len(set(names)) != len(names):
            raise AvalonError("Player names must be unique.")
        self.config = STANDARD_CONFIGS[len(names)]
        endpoints = list(self.mpc_endpoints or [("", 0)] * len(names))
        if len(endpoints) != len(names):
            raise AvalonError("There must be one MPC endpoint per player.")
        self.players = [
            Player(i, name, mpc_host=endpoints[i][0], mpc_port=endpoints[i][1])
            for i, name in enumerate(names)
        ]
        self.rng = random.Random(self.seed)

    @property
    def current_mission_number(self):
        return self.mission_index + 1

    @property
    def current_team_size(self):
        return self.config.mission_team_sizes[self.mission_index]

    @property
    def current_fail_threshold(self):
        return self.config.fail_thresholds[self.mission_index]

    @property
    def current_leader(self):
        return self.players[self.leader_id]

    def require_phase(self, phase):
        # Many actions are only valid in one phase.
        if self.phase != phase:
            raise AvalonError(f"Action is not allowed during {self.phase.value}.")

    def set_phase(self, phase):
        if self.game_over and phase != GamePhase.GAME_OVER:
            raise AvalonError("The game is already over.")
        self.phase = phase

    def set_roles(self, roles):
        if len(roles) != len(self.players):
            raise AvalonError("Role count does not match player count.")
        for player, role in zip(self.players, roles):
            player.role = role

    def evil_players(self):
        return [player for player in self.players if player.is_evil]

    def merlin(self):
        merlins = [player for player in self.players if player.role == Role.MERLIN]
        if len(merlins) != 1:
            raise AvalonError("There should be exactly one Merlin.")
        return merlins[0]

    def assassin(self):
        assassins = [player for player in self.players if player.role == Role.ASSASSIN]
        if len(assassins) != 1:
            raise AvalonError("There should be exactly one Assassin.")
        return assassins[0]

    def private_role_lines_for(self, player_id):
        # Build private information shown only to one player.
        # This is trusted role assignment version, so server knows it here.
        player = self.players[player_id]
        if player.role is None:
            raise AvalonError("Roles have not been assigned yet.")
        lines = [f"You are {player.role.value} ({player.alignment.value})."]
        if player.role == Role.MERLIN:
            evil = ", ".join(f"{p.player_id}:{p.name}" for p in self.evil_players())
            lines.append(f"Merlin information: Evil players are {evil}.")
        elif player.is_evil:
            others = [
                f"{p.player_id}:{p.name}"
                for p in self.evil_players()
                if p.player_id != player_id
            ]
            if others:
                lines.append("Evil information: Other evil players are " + ", ".join(others) + ".")
            else:
                lines.append("Evil information: You are the only evil player.")
        else:
            lines.append("You have no additional information.")
        return lines

    def validate_team(self, team_ids):
        # Check leader selected correct number of different players.
        team = [int(value) for value in team_ids]
        if len(team) != self.current_team_size:
            raise AvalonError(f"This mission requires exactly {self.current_team_size} players.")
        if len(set(team)) != len(team):
            raise AvalonError("A player cannot be selected more than once.")
        if any(player_id < 0 or player_id >= len(self.players) for player_id in team):
            raise AvalonError("Invalid player ID in team.")
        return team

    def propose_team(self, actor_id, team_ids):
        # Leader proposes team, then game moves to approval vote.
        self.require_phase(GamePhase.TEAM_PROPOSAL)
        if actor_id != self.leader_id:
            raise AvalonError("Only the current leader can propose a team.")
        team = self.validate_team(team_ids)
        self.current_team = team
        self.team_votes.clear()
        self.set_phase(GamePhase.TEAM_APPROVAL_VOTE)
        return team

    def submit_team_vote(self, player_id, approve):
        # Team approval votes are public after all players voted.
        self.require_phase(GamePhase.TEAM_APPROVAL_VOTE)
        if player_id in self.team_votes:
            raise AvalonError("You have already voted on this team.")
        self.team_votes[player_id] = bool(approve)
        return len(self.team_votes) == len(self.players)

    def resolve_team_vote(self):
        # More approve than reject means team is accepted.
        self.require_phase(GamePhase.TEAM_APPROVAL_VOTE)
        if len(self.team_votes) != len(self.players):
            raise AvalonError("Not all players have voted on the team.")
        approvals = sum(1 for value in self.team_votes.values() if value)
        rejects = len(self.players) - approvals
        approved = approvals > len(self.players) / 2
        return approved, approvals, rejects

    def apply_team_vote_result(self, approved):
        # If team is approved, next step is secure mission vote.
        # If rejected five times, Evil wins by Avalon rule.
        if approved:
            self.rejected_team_proposals = 0
            self.secure_vote_results.clear()
            self.set_phase(GamePhase.SECURE_MISSION_VOTE)
            return
        self.rejected_team_proposals += 1
        self.current_team = []
        self.team_votes.clear()
        self.advance_leader()
        if self.rejected_team_proposals >= 5:
            self.finish(Alignment.EVIL)
        else:
            self.set_phase(GamePhase.TEAM_PROPOSAL)

    def submit_secure_vote_result(self, player_id, session_id, expected_session_id, mission_failed):
        # Server receives only the final secure result from each mission member.
        # It should not receive each player's private Success/Fail vote.
        self.require_phase(GamePhase.SECURE_MISSION_VOTE)
        if session_id != expected_session_id:
            raise AvalonError("Secure vote result used the wrong session ID.")
        if player_id not in self.current_team:
            raise AvalonError("Only mission team members submit secure vote results.")
        if player_id in self.secure_vote_results:
            raise AvalonError("You have already submitted the secure vote result.")
        self.secure_vote_results[player_id] = bool(mission_failed)
        return len(self.secure_vote_results) == len(self.current_team)

    def resolve_secure_vote_results(self):
        # All mission members should calculate same final result.
        self.require_phase(GamePhase.SECURE_MISSION_VOTE)
        if len(self.secure_vote_results) != len(self.current_team):
            raise AvalonError("Not all mission team members submitted secure vote results.")
        values = set(self.secure_vote_results.values())
        if len(values) != 1:
            raise AvalonError("Players disagreed on the secure mission result.")
        return values.pop()

    def apply_mission_result(self, mission_failed):
        # Update score after mission result is opened.
        self.require_phase(GamePhase.SECURE_MISSION_VOTE)
        self.set_phase(GamePhase.MISSION_RESULT)
        if mission_failed:
            self.failed_missions += 1
        else:
            self.successful_missions += 1

        self.current_team = []
        self.team_votes.clear()
        self.secure_vote_results.clear()

        if self.failed_missions >= 3:
            self.finish(Alignment.EVIL)
            return
        if self.successful_missions >= 3:
            self.set_phase(GamePhase.ASSASSINATION)
            return

        self.mission_index += 1
        self.advance_leader()
        self.set_phase(GamePhase.TEAM_PROPOSAL)

    def resolve_assassination(self, actor_id, target_id):
        # Good side needs Merlin to survive the final assassination.
        self.require_phase(GamePhase.ASSASSINATION)
        if actor_id != self.assassin().player_id:
            raise AvalonError("Only the Assassin can choose the assassination target.")
        if not 0 <= target_id < len(self.players):
            raise AvalonError("Invalid assassination target.")
        if self.players[target_id].role == Role.MERLIN:
            self.finish(Alignment.EVIL)
        else:
            self.finish(Alignment.GOOD)
        assert self.winner is not None
        return self.winner

    def finish(self, winner):
        self.game_over = True
        self.winner = winner
        self.phase = GamePhase.GAME_OVER

    def advance_leader(self):
        self.leader_id = (self.leader_id + 1) % len(self.players)

    def public_snapshot(self):
        # This is the public state that server sends to all clients.
        return PublicSnapshot(
            phase=self.phase.value,
            players=[
                {"player_id": player.player_id, "name": player.name}
                for player in self.players
            ],
            leader_id=self.leader_id,
            mission_number=self.current_mission_number,
            mission_team_size=self.current_team_size,
            fail_threshold=self.current_fail_threshold,
            successful_missions=self.successful_missions,
            failed_missions=self.failed_missions,
            rejected_team_proposals=self.rejected_team_proposals,
            current_team=list(self.current_team),
            winner=self.winner.value if self.winner else None,
        )

    def public_dict(self):
        return self.public_snapshot().__dict__

    def reveal_roles(self):
        return [
            {
                "player_id": player.player_id,
                "name": player.name,
                "role": player.role.value if player.role else None,
                "alignment": player.alignment.value if player.role else None,
            }
            for player in self.players
        ]
