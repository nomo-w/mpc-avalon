import hashlib
import math
import secrets

from cryptography.hazmat.primitives.asymmetric import rsa

from .network import PeerNetwork


# This file implements a small RSA based OT.
# OT means "oblivious transfer":
# the receiver gets only one message from several messages,
# but the sender does not know which one is taken.
# In this project it is used by GMW AND gates.
# This is for prototype and study, not production level crypto.


class RSAKeyPair:
    def __init__(self, modulus, public_exponent, private_exponent):
        self.modulus = modulus
        self.public_exponent = public_exponent
        self.private_exponent = private_exponent

    @classmethod
    def generate(cls, key_size=2048):
        if key_size < 2048:
            raise ValueError("RSA key size must be at least 2048 bits")
        # The cryptography library creates the real RSA key.
        # We only keep n, e, d because the OT formula only needs these numbers.
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )
        numbers = private_key.private_numbers()
        return cls(
            modulus=numbers.public_numbers.n,
            public_exponent=numbers.public_numbers.e,
            private_exponent=numbers.d,
        )


class OTOffer:
    def __init__(self, modulus, public_exponent, challenges):
        self.modulus = modulus
        self.public_exponent = public_exponent
        self.challenges = challenges


class OTReceiverState:
    def __init__(self, choice, secret):
        self.choice = choice
        self.secret = secret


def _random_coprime(modulus):
    # RSA calculation needs a number that has inverse relation with modulus.
    while True:
        candidate = secrets.randbelow(modulus - 3) + 2
        if math.gcd(candidate, modulus) == 1:
            return candidate


def _kdf_bit(key, modulus, context, index):
    # Turn a large RSA result into one mask bit.
    # context and index make different OT messages use different masks.
    key_length = (modulus.bit_length() + 7) // 8
    key_bytes = key.to_bytes(key_length, byteorder="big")
    digest = hashlib.sha256(
        b"avalon-gmw-rsa-ot-v1\x00"
        + context.encode("utf-8")
        + b"\x00"
        + index.to_bytes(4, byteorder="big")
        + key_bytes
    ).digest()
    return digest[0] & 1


def create_offer(key_pair, message_count):
    if message_count < 2:
        raise ValueError("oblivious transfer needs at least two messages")
    # Sender first creates random public challenges.
    # These values are safe to send out.
    challenges = []
    seen = set()
    while len(challenges) < message_count:
        value = secrets.randbelow(key_pair.modulus)
        if value not in seen:
            seen.add(value)
            challenges.append(value)
    return OTOffer(
        modulus=key_pair.modulus,
        public_exponent=key_pair.public_exponent,
        challenges=tuple(challenges),
    )


def create_query(offer, choice):
    if not 0 <= choice < len(offer.challenges):
        raise ValueError("OT choice is outside the offered message range")
    # Receiver hides its choice by adding an RSA blinded random number.
    # Sender can answer all positions, but cannot see which one is useful.
    secret = _random_coprime(offer.modulus)
    blinded = pow(secret, offer.public_exponent, offer.modulus)
    query = (offer.challenges[choice] + blinded) % offer.modulus
    return query, OTReceiverState(choice=choice, secret=secret)


def answer_query(key_pair, offer, query, message_bits, context):
    if len(message_bits) != len(offer.challenges):
        raise ValueError("the number of OT messages does not match the offer")
    if any(bit not in (0, 1) for bit in message_bits):
        raise ValueError("this prototype transfers bits only")
    if offer.modulus != key_pair.modulus:
        raise ValueError("offer was created with a different RSA key")

    # Sender builds one ciphertext for each possible choice.
    # Only the ciphertext at receiver's real choice can be opened correctly.
    ciphertexts = []
    for index, (challenge, message_bit) in enumerate(zip(offer.challenges, message_bits)):
        candidate = pow(
            (query - challenge) % key_pair.modulus,
            key_pair.private_exponent,
            key_pair.modulus,
        )
        pad = _kdf_bit(
            key=candidate,
            modulus=key_pair.modulus,
            context=context,
            index=index,
        )
        ciphertexts.append(message_bit ^ pad)
    return tuple(ciphertexts)


def recover_message(offer, state, ciphertexts, context):
    if len(ciphertexts) != len(offer.challenges):
        raise ValueError("the OT response has the wrong number of ciphertexts")
    if any(bit not in (0, 1) for bit in ciphertexts):
        raise ValueError("invalid OT ciphertext bit")
    # Receiver only knows the secret for one position, so only one message opens.
    pad = _kdf_bit(
        key=state.secret,
        modulus=offer.modulus,
        context=context,
        index=state.choice,
    )
    return ciphertexts[state.choice] ^ pad


class NetworkObliviousTransfer:
    # This wrapper sends OT messages on the peer-to-peer network.

    def __init__(self, network, key_pair):
        self.network = network
        self.key_pair = key_pair

    async def send_one_of_four(self, receiver_id, messages, tag):
        # Sender sends the offer, waits for receiver query,
        # then sends back four masked bits.
        offer = create_offer(self.key_pair, message_count=4)
        await self.network.send(
            receiver_id,
            message_type="ot_offer",
            tag=tag,
            payload={
                "n": str(offer.modulus),
                "e": offer.public_exponent,
                "x": [str(value) for value in offer.challenges],
            },
        )
        query_payload = await self.network.receive(
            receiver_id,
            expected_type="ot_query",
            expected_tag=tag,
        )
        query = int(query_payload["v"])
        ciphertexts = answer_query(
            self.key_pair,
            offer,
            query=query,
            message_bits=messages,
            context=tag,
        )
        await self.network.send(
            receiver_id,
            message_type="ot_response",
            tag=tag,
            payload={"ciphertexts": list(ciphertexts)},
        )

    async def receive_one_of_four(self, sender_id, choice, tag):
        # Receiver reads the offer, sends a hidden choice,
        # then opens only the selected bit from sender response.
        offer_payload = await self.network.receive(
            sender_id,
            expected_type="ot_offer",
            expected_tag=tag,
        )
        offer = OTOffer(
            modulus=int(offer_payload["n"]),
            public_exponent=int(offer_payload["e"]),
            challenges=tuple(int(value) for value in offer_payload["x"]),
        )
        if len(offer.challenges) != 4:
            raise RuntimeError("GMW AND gates require 1-out-of-4 OT")
        query, state = create_query(offer, choice=choice)
        await self.network.send(
            sender_id,
            message_type="ot_query",
            tag=tag,
            payload={"v": str(query)},
        )
        response_payload = await self.network.receive(
            sender_id,
            expected_type="ot_response",
            expected_tag=tag,
        )
        ciphertexts = tuple(int(value) for value in response_payload["ciphertexts"])
        return recover_message(
            offer,
            state,
            ciphertexts=ciphertexts,
            context=tag,
        )
