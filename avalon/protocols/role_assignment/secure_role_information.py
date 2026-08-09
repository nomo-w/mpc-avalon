from avalon.game.models import Role
from avalon.protocols.mission_voting.secure_vote.circuits import role_knowledge_circuit
from avalon.protocols.mission_voting.secure_vote.gmw import GMWParty

from .role_information import private_role_lines_from_visible, role_bits


class SecureRoleInformationResult:
    def __init__(self, session_id, role, visible_evil_player_ids, private_lines):
        self.session_id = session_id
        self.role = role
        self.visible_evil_player_ids = list(visible_evil_player_ids)
        self.private_lines = list(private_lines)


async def run_secure_role_information(
    party_id,
    endpoints,
    listen_host,
    session_id,
    local_role,
    player_names,
    rsa_key_size=2048,
    connect_timeout=30.0,
):
    # Compute Avalon role information without opening the full role table.
    # Each output is opened only to the player who needs to see it.
    if isinstance(local_role, Role):
        role = local_role
    else:
        role = Role(str(local_role))

    party_count = len(endpoints)
    if len(player_names) != party_count:
        raise ValueError("there must be one player name per role information party")

    runtime = GMWParty(
        party_id=party_id,
        endpoints=endpoints,
        listen_host=listen_host,
        session_id=session_id,
        rsa_key_size=rsa_key_size,
        connect_timeout=connect_timeout,
    )
    await runtime.start()
    try:
        # Everyone checks that the public player order is the same.
        await runtime.confirm_public_configuration(
            {
                "protocol": "avalon-role-information-gmw-v1",
                "session_id": session_id,
                "player_names": list(player_names),
                "party_count": party_count,
            }
        )

        local_bits = role_bits(role)
        merlin_shares = []
        evil_shares = []
        for owner_id in range(party_count):
            # Each player shares two private bits: is_merlin and is_evil.
            # Only the owner knows the real values at this point.
            owner_merlin = local_bits["is_merlin"] if party_id == owner_id else 0
            owner_evil = local_bits["is_evil"] if party_id == owner_id else 0
            merlin_shares.append(
                await runtime.share_private_input(
                    owner_id=owner_id,
                    local_value=owner_merlin,
                    wire_name=f"role-is-merlin-{owner_id}",
                )
            )
            evil_shares.append(
                await runtime.share_private_input(
                    owner_id=owner_id,
                    local_value=owner_evil,
                    wire_name=f"role-is-evil-{owner_id}",
                )
            )

        visible_evil_player_ids = []
        for viewer_id in range(party_count):
            for target_id in range(party_count):
                # This circuit answers: can viewer_id see target_id as evil?
                output_share = await role_knowledge_circuit(
                    runtime=runtime,
                    viewer_is_merlin_share=merlin_shares[viewer_id],
                    viewer_is_evil_share=evil_shares[viewer_id],
                    target_is_evil_share=evil_shares[target_id],
                    same_player=(viewer_id == target_id),
                    circuit_name=f"role-info:view-{viewer_id}:target-{target_id}",
                )
                visible = await runtime.reveal_to_party(
                    output_share=output_share,
                    output_name=f"view-{viewer_id}-target-{target_id}",
                    target_party_id=viewer_id,
                )
                if viewer_id == party_id and visible:
                    visible_evil_player_ids.append(target_id)

        private_lines = private_role_lines_from_visible(
            player_names=player_names,
            role=role,
            visible_evil_player_ids=visible_evil_player_ids,
        )
        return SecureRoleInformationResult(
            session_id=session_id,
            role=role,
            visible_evil_player_ids=visible_evil_player_ids,
            private_lines=private_lines,
        )
    finally:
        await runtime.close()
