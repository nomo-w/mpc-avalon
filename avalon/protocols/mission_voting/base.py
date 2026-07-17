class MissionVotingProtocol:
    # Only a small parent class for mission voting modules.
    # Real code should return True when mission failed.

    async def resolve_vote(self, team_player_ids, fail_threshold, session_id):
        raise NotImplementedError
