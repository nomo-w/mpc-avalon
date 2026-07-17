import hashlib
import json
import secrets

from .network import PeerNetwork
from .ot import NetworkObliviousTransfer, RSAKeyPair


# This file is the small GMW runtime used by mission voting.
# The main idea is simple:
# 1. Every secret bit is split into XOR shares.
# 2. Each player only keeps one share, so one share does not show the vote.
# 3. XOR and NOT can be calculated locally.
# 4. AND needs OT, because AND mixes two players' private shares.


def _validate_bit(value, name="bit"):
    if value not in (0, 1):
        raise ValueError(f"{name} must be 0 or 1")
    return int(value)


class GMWStatistics:
    def __init__(self, input_wires, xor_gates, not_gates, and_gates, oblivious_transfers):
        self.input_wires = input_wires
        self.xor_gates = xor_gates
        self.not_gates = not_gates
        self.and_gates = and_gates
        self.oblivious_transfers = oblivious_transfers


class GMWParty:
    # One object means one player in one secure voting session.

    def __init__(self, party_id, endpoints, listen_host, session_id, rsa_key_size=2048, connect_timeout=30.0):
        if not session_id.strip():
            raise ValueError("session_id cannot be empty")
        self.party_id = party_id
        self.party_count = len(endpoints)
        self.session_id = session_id.strip()
        self.network = PeerNetwork(
            party_id=party_id,
            endpoints=endpoints,
            listen_host=listen_host,
            connect_timeout=connect_timeout,
        )
        self._rsa_key_size = rsa_key_size
        self._ot = None
        self._started = False

        self._input_wires = 0
        self._xor_gates = 0
        self._not_gates = 0
        self._and_gates = 0
        self._ots = 0

    async def start(self):
        if self._started:
            raise RuntimeError("GMW party has already started")
        # RSA private key is only kept by this local player.
        # It is used by OT, not sent to other players.
        key_pair = RSAKeyPair.generate(key_size=self._rsa_key_size)
        self._ot = NetworkObliviousTransfer(
            network=self.network,
            key_pair=key_pair,
        )
        await self.network.start()
        self._started = True

    async def close(self):
        await self.network.close()
        self._started = False

    def _require_started(self):
        if not self._started or self._ot is None:
            raise RuntimeError("GMW party has not been started")

    @property
    def statistics(self):
        return GMWStatistics(
            input_wires=self._input_wires,
            xor_gates=self._xor_gates,
            not_gates=self._not_gates,
            and_gates=self._and_gates,
            oblivious_transfers=self._ots,
        )

    def public_constant(self, value):
        # Public value also needs to look like shares.
        # Party 0 keeps the real bit, other parties keep 0.
        bit = _validate_bit(value)
        return bit if self.party_id == 0 else 0

    async def confirm_public_configuration(self, value):
        # All players must use the same team list and threshold.
        # We only compare hash here, because the data is public and small.
        self._require_started()
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        tag = f"{self.session_id}:public-config"
        await self.network.broadcast(
            message_type="config_digest",
            tag=tag,
            payload={"sha256": digest},
        )
        received = await self.network.receive_from_all(
            expected_type="config_digest",
            expected_tag=tag,
        )
        mismatches = [
            peer_id
            for peer_id, payload in received.items()
            if payload.get("sha256") != digest
        ]
        if mismatches:
            raise RuntimeError(
                f"public MPC configuration differs for parties {mismatches}"
            )

    async def share_private_input(self, owner_id, local_value, wire_name):
        # The vote owner splits one bit into many random shares.
        # XOR of all shares equals the original private vote.
        self._require_started()
        if not 0 <= owner_id < self.party_count:
            raise ValueError("invalid input owner")
        local_value = _validate_bit(local_value, name="input")
        self._input_wires += 1
        tag = f"{self.session_id}:input:{wire_name}:owner:{owner_id}"

        if self.party_id == owner_id:
            own_share = local_value
            for peer_id in range(self.party_count):
                if peer_id == owner_id:
                    continue
                peer_share = secrets.randbits(1)
                own_share ^= peer_share
                await self.network.send(
                    peer_id,
                    message_type="input_share",
                    tag=tag,
                    payload={"share": peer_share},
                )
            return own_share

        payload = await self.network.receive(
            owner_id,
            expected_type="input_share",
            expected_tag=tag,
        )
        return _validate_bit(int(payload["share"]), name="input share")

    def xor_gate(self, left_share, right_share):
        self._require_started()
        left_share = _validate_bit(left_share, name="left share")
        right_share = _validate_bit(right_share, name="right share")
        self._xor_gates += 1
        return left_share ^ right_share

    def not_gate(self, input_share):
        self._require_started()
        input_share = _validate_bit(input_share, name="input share")
        self._not_gates += 1
        # Only one party changes its share, then the final XOR value is flipped.
        return input_share ^ (1 if self.party_id == 0 else 0)

    async def and_gate(self, left_share, right_share, gate_name):
        # AND gate is the hard part in GMW.
        # Each pair of players uses 1-out-of-4 OT.
        # The receiver chooses by its two local bits, but the sender does not
        # know which choice is used. So the private shares are still hidden.
        self._require_started()
        assert self._ot is not None
        left_share = _validate_bit(left_share, name="left share")
        right_share = _validate_bit(right_share, name="right share")
        self._and_gates += 1

        output_share = left_share & right_share
        for sender_id in range(self.party_count):
            for receiver_id in range(sender_id + 1, self.party_count):
                tag = (
                    f"{self.session_id}:and:{gate_name}:"
                    f"pair:{sender_id}-{receiver_id}"
                )
                if self.party_id == sender_id:
                    random_share = secrets.randbits(1)
                    # Receiver's choice is made from its two input shares.
                    messages = tuple(
                        random_share
                        ^ (left_share & receiver_b)
                        ^ (receiver_a & right_share)
                        for receiver_a in (0, 1)
                        for receiver_b in (0, 1)
                    )
                    await self._ot.send_one_of_four(
                        receiver_id=receiver_id,
                        messages=(
                            messages[0],
                            messages[1],
                            messages[2],
                            messages[3],
                        ),
                        tag=tag,
                    )
                    output_share ^= random_share
                    self._ots += 1
                elif self.party_id == receiver_id:
                    choice = (left_share << 1) | right_share
                    received_share = await self._ot.receive_one_of_four(
                        sender_id=sender_id,
                        choice=choice,
                        tag=tag,
                    )
                    output_share ^= received_share
                    self._ots += 1

        return output_share

    async def reveal_to_all(self, output_share, output_name):
        # Only the final mission result is opened.
        # Intermediate shares and private votes are not opened.
        self._require_started()
        output_share = _validate_bit(output_share, name="output share")
        tag = f"{self.session_id}:output:{output_name}"
        await self.network.broadcast(
            message_type="output_share",
            tag=tag,
            payload={"share": output_share},
        )
        received = await self.network.receive_from_all(
            expected_type="output_share",
            expected_tag=tag,
        )
        result = output_share
        for payload in received.values():
            result ^= _validate_bit(int(payload["share"]), name="output share")
        return result
