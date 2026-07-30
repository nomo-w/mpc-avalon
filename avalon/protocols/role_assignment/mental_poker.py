import random

from avalon.game.rules import build_roles

from .cards import build_role_cards
from .mental_poker_crypto import (
    CommutativeCipherKey,
    MENTAL_POKER_PRIME,
    card_from_plaintext,
    deck_plaintexts,
)


class MentalPokerDealResult:
    # Result object for the local prototype.
    # In the final networked version, each player should only receive their own card.
    def __init__(self, cards, encrypted_deck, player_cards, shuffle_steps):
        self.cards = cards
        self.encrypted_deck = encrypted_deck
        self.player_cards = player_cards
        self.shuffle_steps = shuffle_steps

    def role_for_player(self, player_id):
        return self.player_cards[int(player_id)].role

    def card_for_player(self, player_id):
        return self.player_cards[int(player_id)]

    def player_roles(self):
        return [card.role for card in self.player_cards]

    def private_dict_for_player(self, player_id):
        card = self.card_for_player(player_id)
        return {
            "player_id": int(player_id),
            "card_id": card.card_id,
            "role": card.role.value,
            "card_label": card.label,
        }


class MentalPokerRoleDealingPrototype:
    # Prototype for secure role dealing.
    # Each party encrypts and shuffles the deck once.
    # Then each dealt card is decrypted only for its owner.

    def __init__(self, rng=None, modulus=MENTAL_POKER_PRIME):
        self.rng = rng or random.SystemRandom()
        self.modulus = int(modulus)

    def generate_keys(self, player_count):
        return [
            CommutativeCipherKey.generate(modulus=self.modulus)
            for _ in range(int(player_count))
        ]

    def encrypt_and_shuffle_deck(self, deck_values, keys):
        deck = list(deck_values)
        shuffle_steps = []
        for party_id, key in enumerate(keys):
            deck = key.encrypt_deck(deck)
            self.rng.shuffle(deck)
            shuffle_steps.append(
                {
                    "party_id": party_id,
                    "deck_size": len(deck),
                }
            )
        return deck, shuffle_steps

    def decrypt_card_for_player(self, encrypted_card, player_id, keys):
        # In a real network protocol, other parties would remove their layers
        # and send only this card onward to the owner.
        player_id = int(player_id)
        value = int(encrypted_card)
        for helper_id, key in enumerate(keys):
            if helper_id == player_id:
                continue
            value = key.decrypt_value(value)
        return keys[player_id].decrypt_value(value)

    def deal(self, num_players, keys=None):
        num_players = int(num_players)
        cards = build_role_cards(num_players)
        keys = list(keys or self.generate_keys(num_players))
        if len(keys) != num_players:
            raise ValueError("there must be one Mental Poker key per player")

        deck_values = deck_plaintexts(cards)
        encrypted_deck, shuffle_steps = self.encrypt_and_shuffle_deck(deck_values, keys)

        player_cards = []
        for player_id in range(num_players):
            plaintext = self.decrypt_card_for_player(
                encrypted_card=encrypted_deck[player_id],
                player_id=player_id,
                keys=keys,
            )
            player_cards.append(card_from_plaintext(cards, plaintext))

        return MentalPokerDealResult(
            cards=cards,
            encrypted_deck=encrypted_deck,
            player_cards=player_cards,
            shuffle_steps=shuffle_steps,
        )


def deal_roles_with_mental_poker(num_players, rng=None):
    # Convenience helper for demos and tests.
    prototype = MentalPokerRoleDealingPrototype(rng=rng)
    return prototype.deal(num_players)


def check_dealt_roles_match_rules(result):
    expected = sorted(role.value for role in build_roles(len(result.player_cards)))
    actual = sorted(role.value for role in result.player_roles())
    return actual == expected
