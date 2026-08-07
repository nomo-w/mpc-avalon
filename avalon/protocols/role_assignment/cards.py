from avalon.game.models import AvalonError
from avalon.game.rules import build_roles


class RoleCard:
    # Mental Poker needs every card to be unique, even if two cards have same role.
    def __init__(self, card_id, role, copy_index):
        self.card_id = int(card_id)
        self.role = role
        self.copy_index = int(copy_index)

    @property
    def label(self):
        # Example: "Loyal Servant of Arthur#1".
        return f"{self.role.value}#{self.copy_index}"

    @property
    def encoded_value(self):
        # Later encryption works more cleanly with positive non-zero values.
        return self.card_id + 1


def build_role_cards(num_players):
    roles = build_roles(num_players)
    seen = {}
    cards = []
    for card_id, role in enumerate(roles):
        copy_index = seen.get(role, 0)
        seen[role] = copy_index + 1
        cards.append(RoleCard(card_id=card_id, role=role, copy_index=copy_index))
    return cards


def card_from_encoded_value(cards, encoded_value):
    encoded_value = int(encoded_value)
    for card in cards:
        if card.encoded_value == encoded_value:
            return card
    raise AvalonError(f"Unknown encoded role card value: {encoded_value}")
