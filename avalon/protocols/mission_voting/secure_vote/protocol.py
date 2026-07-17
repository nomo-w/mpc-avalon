from .circuits import mission_failed_reference, mission_failed_threshold_circuit
from .gmw import GMWParty


# This file connects Avalon mission vote with the GMW code.
# Client code calls run_secure_mission_vote().
# It prepares public config, sends private vote shares,
# runs the threshold circuit, and opens only the final result.


class MissionVoteConfiguration:
    def __init__(self, session_id, team_ids, fail_threshold):
        self.session_id = session_id
        self.team_ids = team_ids
        self.fail_threshold = fail_threshold

    @classmethod
    def create(cls, session_id, team_ids, fail_threshold, party_count):
        # Clean and check all public data before running MPC.
        clean_session = session_id.strip()
        if not clean_session:
            raise ValueError("session_id cannot be empty")
        team = tuple(int(value) for value in team_ids)
        if not team:
            raise ValueError("mission team cannot be empty")
        if len(set(team)) != len(team):
            raise ValueError("mission team contains duplicate party IDs")
        if any(value < 0 or value >= party_count for value in team):
            raise ValueError("mission team contains an invalid party ID")
        if fail_threshold not in (1, 2):
            raise ValueError("Avalon fail_threshold must currently be 1 or 2")
        if fail_threshold > len(team):
            raise ValueError("fail threshold cannot exceed the mission team size")
        return cls(
            session_id=clean_session,
            team_ids=team,
            fail_threshold=fail_threshold,
        )

    def public_dict(self):
        # This data is public. All MPC players compare it before voting.
        return {
            "protocol": "avalon-gmw-rsa-ot-v1",
            "session_id": self.session_id,
            "team_ids": list(self.team_ids),
            "fail_threshold": self.fail_threshold,
        }


class MissionVoteOutcome:
    def __init__(self, session_id, mission_failed, statistics):
        self.session_id = session_id
        self.mission_failed = mission_failed
        self.statistics = statistics

    @property
    def mission_succeeded(self):
        return not self.mission_failed


async def run_secure_mission_vote(
    party_id,
    endpoints,
    listen_host,
    configuration,
    local_fail_vote,
    rsa_key_size=2048,
    connect_timeout=30.0,
):
    # Run one secure mission vote.
    # In current version, only mission team members join this MPC session.
    # local_fail_vote is 0 for Success and 1 for Fail.
    if local_fail_vote not in (0, 1):
        raise ValueError("local_fail_vote must be 0=Success or 1=Fail")
    if len(endpoints) < 2:
        raise ValueError("at least two game players are required")

    configuration = MissionVoteConfiguration.create(
        session_id=configuration.session_id,
        team_ids=configuration.team_ids,
        fail_threshold=configuration.fail_threshold,
        party_count=len(endpoints),
    )
    runtime = GMWParty(
        party_id=party_id,
        endpoints=endpoints,
        listen_host=listen_host,
        session_id=configuration.session_id,
        rsa_key_size=rsa_key_size,
        connect_timeout=connect_timeout,
    )
    await runtime.start()
    try:
        # This prevents one player from using a different team list or threshold.
        await runtime.confirm_public_configuration(configuration.public_dict())

        vote_shares = []
        for owner_id in configuration.team_ids:
            owner_input = local_fail_vote if party_id == owner_id else 0
            # Each vote is shared by its owner.
            # Other players receive one random-looking share.
            vote_shares.append(
                await runtime.share_private_input(
                    owner_id=owner_id,
                    local_value=owner_input,
                    wire_name=f"mission-vote-{owner_id}",
                )
            )

        # Circuit returns a shared bit: 1 means mission failed.
        result_share = await mission_failed_threshold_circuit(
            runtime,
            vote_shares,
            fail_threshold=configuration.fail_threshold,
        )
        mission_failed = bool(
            await runtime.reveal_to_all(
                result_share,
                output_name="mission-failed",
            )
        )
        return MissionVoteOutcome(
            session_id=configuration.session_id,
            mission_failed=mission_failed,
            statistics=runtime.statistics,
        )
    finally:
        await runtime.close()


__all__ = [
    "MissionVoteConfiguration",
    "MissionVoteOutcome",
    "mission_failed_reference",
    "run_secure_mission_vote",
]
