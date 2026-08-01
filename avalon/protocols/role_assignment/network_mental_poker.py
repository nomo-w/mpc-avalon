import random

from avalon.protocols.mission_voting.secure_vote.network import PeerNetwork

from .cards import build_role_cards
from .mental_poker_crypto import (
    CommutativeCipherKey,
    MENTAL_POKER_PRIME,
    card_from_plaintext,
    deck_plaintexts,
)


class NetworkMentalPokerResult:
    def __init__(self, session_id, card):
        self.session_id = session_id
        self.card = card
        self.role = card.role


async def run_network_mental_poker_role_assignment(
    party_id,
    endpoints,
    listen_host,
    session_id,
    connect_timeout=30.0,
    rng=None,
):
    # This is the networked version of the Mental Poker role dealing prototype.
    # Each client takes one turn to encrypt and shuffle the role deck.
    if not session_id.strip():
        raise ValueError("session_id cannot be empty")
    party_count = len(endpoints)
    if party_count < 2:
        raise ValueError("Mental Poker role assignment needs at least two players")

    rng = rng or random.SystemRandom()
    cards = build_role_cards(party_count)
    deck = deck_plaintexts(cards)
    key = CommutativeCipherKey.generate(modulus=MENTAL_POKER_PRIME)

    network = PeerNetwork(
        party_id=party_id,
        endpoints=endpoints,
        listen_host=listen_host,
        connect_timeout=connect_timeout,
    )
    await network.start()
    try:
        # Step 1: every party encrypts and shuffles the whole deck once.
        for dealer_id in range(party_count):
            tag = f"{session_id}:role-deck-step:{dealer_id}"
            if party_id == dealer_id:
                # Only this dealer knows this encryption layer.
                deck = key.encrypt_deck(deck)
                rng.shuffle(deck)
                await network.broadcast(
                    message_type="role_deck_step",
                    tag=tag,
                    payload={"deck": [str(value) for value in deck]},
                )
            else:
                # Other parties receive the next encrypted deck.
                payload = await network.receive(
                    dealer_id,
                    expected_type="role_deck_step",
                    expected_tag=tag,
                )
                deck = [int(value) for value in payload["deck"]]

        # Step 2: card i belongs to party i.
        # Everyone helps remove layers, but only the owner removes the final layer.
        own_card = None
        for owner_id in range(party_count):
            partly_decrypted = int(deck[owner_id])
            for helper_id in range(party_count):
                if helper_id == owner_id:
                    continue
                tag = f"{session_id}:role-card:{owner_id}:helper:{helper_id}"
                if party_id == helper_id:
                    # This helper removes only its own encryption layer.
                    partly_decrypted = key.decrypt_value(partly_decrypted)
                    await network.broadcast(
                        message_type="role_card_layer_removed",
                        tag=tag,
                        payload={"value": str(partly_decrypted)},
                    )
                else:
                    # Everyone follows the same partial-decryption chain.
                    payload = await network.receive(
                        helper_id,
                        expected_type="role_card_layer_removed",
                        expected_tag=tag,
                    )
                    partly_decrypted = int(payload["value"])

            if party_id == owner_id:
                plaintext = key.decrypt_value(partly_decrypted)
                own_card = card_from_plaintext(cards, plaintext)

        if own_card is None:
            raise RuntimeError("Mental Poker did not produce a local role card")
        card = own_card
        return NetworkMentalPokerResult(session_id=session_id, card=card)
    finally:
        await network.close()
