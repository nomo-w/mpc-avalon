import math
import secrets

from .cards import card_from_encoded_value


# A fixed prime modulus for the Mental Poker prototype.
# This is enough for a study prototype, not production cryptography.
MENTAL_POKER_PRIME = (1 << 127) - 1


class MentalPokerCryptoError(ValueError):
    pass


class CommutativeCipherKey:
    # Simple commutative encryption key:
    # encrypt(m) = m^secret mod p
    # decrypt(c) = c^(secret^-1 mod p-1) mod p

    def __init__(self, secret_exponent, modulus=MENTAL_POKER_PRIME):
        self.modulus = int(modulus)
        self.secret_exponent = int(secret_exponent)
        if self.modulus <= 3:
            raise MentalPokerCryptoError("modulus is too small")
        if math.gcd(self.secret_exponent, self.modulus - 1) != 1:
            raise MentalPokerCryptoError("secret exponent must be invertible modulo p-1")
        self.decrypt_exponent = pow(self.secret_exponent, -1, self.modulus - 1)

    @classmethod
    def generate(cls, modulus=MENTAL_POKER_PRIME):
        modulus = int(modulus)
        order = modulus - 1
        while True:
            secret_exponent = secrets.randbelow(order - 2) + 2
            if math.gcd(secret_exponent, order) == 1:
                return cls(secret_exponent=secret_exponent, modulus=modulus)

    def encrypt_value(self, value):
        value = _validate_group_value(value, self.modulus)
        return pow(value, self.secret_exponent, self.modulus)

    def decrypt_value(self, value):
        value = _validate_group_value(value, self.modulus)
        return pow(value, self.decrypt_exponent, self.modulus)

    def encrypt_deck(self, deck_values):
        return [self.encrypt_value(value) for value in deck_values]

    def decrypt_deck(self, deck_values):
        return [self.decrypt_value(value) for value in deck_values]


def _validate_group_value(value, modulus):
    value = int(value)
    if not 1 < value < modulus:
        raise MentalPokerCryptoError("encrypted card value must be between 2 and p-1")
    return value


def card_plaintext(card):
    # encoded_value starts at 1, but 1 is a bad group value because 1^k is always 1.
    return card.encoded_value + 1


def card_from_plaintext(cards, plaintext):
    encoded_value = int(plaintext) - 1
    return card_from_encoded_value(cards, encoded_value)


def deck_plaintexts(cards):
    return [card_plaintext(card) for card in cards]


def cards_from_plaintexts(cards, plaintext_values):
    return [card_from_plaintext(cards, value) for value in plaintext_values]
