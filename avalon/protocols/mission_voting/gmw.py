class GMWMissionVotingProtocol:
    # Small adapter used by server.
    # It lets server call mission voting as one protocol object.

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def resolve_vote(self, team_player_ids, fail_threshold, session_id):
        return await self.coordinator.coordinate_gmw_vote(
            team_player_ids=team_player_ids,
            fail_threshold=fail_threshold,
            session_id=session_id,
        )
