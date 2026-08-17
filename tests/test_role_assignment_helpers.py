import unittest
from collections import Counter

from avalon.game.models import AvalonError, Role
from avalon.game.rules import build_roles
from avalon.protocols.role_assignment.cards import (
    build_role_cards,
    card_from_encoded_value,
)
from avalon.protocols.role_assignment.mental_poker_crypto import (
    CommutativeCipherKey,
    MentalPokerCryptoError,
    card_from_plaintext,
    card_plaintext,
    deck_plaintexts,
)
from avalon.protocols.role_assignment.role_information import (
    private_role_lines_from_visible,
    role_bits,
)


class RoleCardTests(unittest.TestCase):
    def test_role_cards_are_unique_and_match_rules(self):
        cards = build_role_cards(5)
        self.assertEqual(len(cards), 5)
        self.assertEqual(len({card.card_id for card in cards}), 5)
        self.assertEqual(len({card.encoded_value for card in cards}), 5)

        expected_roles = Counter(build_roles(5))
        actual_roles = Counter(card.role for card in cards)
        self.assertEqual(actual_roles, expected_roles)

    def test_encoded_value_can_find_same_card(self):
        cards = build_role_cards(5)
        for card in cards:
            decoded = card_from_encoded_value(cards, card.encoded_value)
            self.assertIs(decoded, card)

        with self.assertRaises(AvalonError):
            card_from_encoded_value(cards, 999)


class MentalPokerCryptoTests(unittest.TestCase):
    def test_encrypt_then_decrypt_returns_plaintext(self):
        key = CommutativeCipherKey(secret_exponent=5)
        value = 42
        encrypted = key.encrypt_value(value)
        self.assertNotEqual(encrypted, value)
        self.assertEqual(key.decrypt_value(encrypted), value)

    def test_encryption_order_is_commutative(self):
        key_a = CommutativeCipherKey(secret_exponent=5)
        key_b = CommutativeCipherKey(secret_exponent=11)
        value = 42

        a_then_b = key_b.encrypt_value(key_a.encrypt_value(value))
        b_then_a = key_a.encrypt_value(key_b.encrypt_value(value))
        self.assertEqual(a_then_b, b_then_a)

    def test_card_plaintexts_can_be_decoded(self):
        cards = build_role_cards(5)
        plaintexts = deck_plaintexts(cards)
        self.assertEqual(len(plaintexts), 5)
        self.assertTrue(all(value > 1 for value in plaintexts))

        for card in cards:
            plaintext = card_plaintext(card)
            self.assertIs(card_from_plaintext(cards, plaintext), card)

    def test_bad_crypto_values_are_rejected(self):
        with self.assertRaises(MentalPokerCryptoError):
            CommutativeCipherKey(secret_exponent=2)

        key = CommutativeCipherKey(secret_exponent=5)
        with self.assertRaises(MentalPokerCryptoError):
            key.encrypt_value(1)


class RoleInformationHelperTests(unittest.TestCase):
    def test_role_bits_for_merlin_evil_and_good(self):
        self.assertEqual(role_bits(Role.MERLIN), {"is_merlin": 1, "is_evil": 0})
        self.assertEqual(role_bits(Role.ASSASSIN), {"is_merlin": 0, "is_evil": 1})
        self.assertEqual(role_bits(Role.MINION), {"is_merlin": 0, "is_evil": 1})
        self.assertEqual(role_bits(Role.LOYAL_SERVANT), {"is_merlin": 0, "is_evil": 0})

    def test_private_role_text_for_merlin(self):
        names = ["Alice", "Bob", "Charlie"]
        lines = private_role_lines_from_visible(
            player_names=names,
            role=Role.MERLIN,
            visible_evil_player_ids=[1, 2],
        )
        self.assertIn("You are Merlin (Good).", lines)
        self.assertIn("Merlin information: Evil players are 1:Bob, 2:Charlie.", lines)

    def test_private_role_text_for_evil_and_good(self):
        names = ["Alice", "Bob", "Charlie"]
        evil_lines = private_role_lines_from_visible(
            player_names=names,
            role=Role.ASSASSIN,
            visible_evil_player_ids=[2],
        )
        self.assertIn("Evil information: Other evil players are 2:Charlie.", evil_lines)

        alone_lines = private_role_lines_from_visible(
            player_names=names,
            role=Role.ASSASSIN,
            visible_evil_player_ids=[],
        )
        self.assertIn("Evil information: You are the only evil player.", alone_lines)

        good_lines = private_role_lines_from_visible(
            player_names=names,
            role=Role.LOYAL_SERVANT,
            visible_evil_player_ids=[],
        )
        self.assertIn("You have no additional information.", good_lines)


if __name__ == "__main__":
    unittest.main()
