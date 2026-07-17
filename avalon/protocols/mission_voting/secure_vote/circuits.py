from itertools import combinations

from .gmw import GMWParty


class GateNamer:
    # This small class only gives different names to gates.
    # Different names help network messages not mix together.
    def __init__(self, prefix):
        self.prefix = prefix
        self.counter = 0

    def next(self, label):
        value = f"{self.prefix}:{self.counter}:{label}"
        self.counter += 1
        return value


async def secure_or(runtime, left_share, right_share, namer):
    # GMW code only has XOR and AND as basic gates.
    # So here we build OR by this Boolean formula:
    # a OR b = a XOR b XOR (a AND b)
    product = await runtime.and_gate(
        left_share,
        right_share,
        gate_name=namer.next("or-and"),
    )
    parity = runtime.xor_gate(left_share, right_share)
    return runtime.xor_gate(parity, product)


async def secure_or_many(runtime, shares, namer):
    if not shares:
        return runtime.public_constant(0)
    current = list(shares)
    # We join the OR gates level by level.
    # This is easier to read than one very long expression.
    while len(current) > 1:
        next_level = []
        iterator = iter(current)
        for left in iterator:
            try:
                right = next(iterator)
            except StopIteration:
                next_level.append(left)
                break
            next_level.append(
                await secure_or(runtime, left, right, namer=namer)
            )
        current = next_level
    return current[0]


async def threshold_one_circuit(runtime, fail_vote_shares, namer):
    # Result is 1 if at least one player voted Fail.
    return await secure_or_many(runtime, fail_vote_shares, namer=namer)


async def threshold_two_circuit(runtime, fail_vote_shares, namer):
    # Result is 1 if at least two players voted Fail.
    # Avalon team size is small, so we use a simple way:
    # check every pair, then OR all pair results.
    if len(fail_vote_shares) < 2:
        return runtime.public_constant(0)
    pair_terms = []
    for pair_index, (left, right) in enumerate(combinations(fail_vote_shares, 2)):
        pair_terms.append(
            await runtime.and_gate(
                left,
                right,
                gate_name=namer.next(f"threshold2-pair-{pair_index}"),
            )
        )
    return await secure_or_many(runtime, pair_terms, namer=namer)


async def mission_failed_threshold_circuit(runtime, fail_vote_shares, fail_threshold, circuit_name="mission-threshold"):
    # Avalon mission result only needs threshold 1 or threshold 2.
    # threshold 1: one Fail is enough.
    # threshold 2: at least two Fails are needed.
    if not fail_vote_shares:
        raise ValueError("mission voting requires at least one private vote")
    if fail_threshold == 1:
        return await threshold_one_circuit(
            runtime,
            fail_vote_shares,
            namer=GateNamer(f"{circuit_name}:t1"),
        )
    if fail_threshold == 2:
        return await threshold_two_circuit(
            runtime,
            fail_vote_shares,
            namer=GateNamer(f"{circuit_name}:t2"),
        )
    raise NotImplementedError(
        "the current Avalon prototype implements fail thresholds 1 and 2 only"
    )



async def role_knowledge_circuit(runtime, viewer_is_merlin_share, viewer_is_evil_share,
    target_is_evil_share, same_player, circuit_name="role-knowledge"):
    # This is not used by current game flow.
    # It is kept for future secure role information.
    # Output 1 means viewer is allowed to know target is evil.
    namer = GateNamer(circuit_name)
    merlin_sees_target = await runtime.and_gate(
        viewer_is_merlin_share,
        target_is_evil_share,
        gate_name=namer.next("merlin-and-target-evil"),
    )
    evil_sees_evil = await runtime.and_gate(
        viewer_is_evil_share,
        target_is_evil_share,
        gate_name=namer.next("viewer-evil-and-target-evil"),
    )
    if same_player:
        evil_sees_evil = runtime.public_constant(0)
    return await secure_or(
        runtime,
        merlin_sees_target,
        evil_sees_evil,
        namer=namer,
    )


def mission_failed_reference(votes, fail_threshold):
    if not votes:
        raise ValueError("at least one mission vote is required")
    if fail_threshold not in (1, 2):
        raise ValueError("fail_threshold must be 1 or 2")
    if any(vote not in (0, 1) for vote in votes):
        raise ValueError("votes must be 0=Success or 1=Fail")
    return sum(votes) >= fail_threshold


def role_knowledge_reference(viewer_is_merlin, viewer_is_evil, target_is_evil, same_player):
    # Same idea as role_knowledge_circuit, but written in normal Python.
    # It is useful when checking the circuit result.
    values = (viewer_is_merlin, viewer_is_evil, target_is_evil, same_player)
    if any(value not in (0, 1) for value in values):
        raise ValueError("role circuit inputs must be bits")
    return int(
        bool(viewer_is_merlin and target_is_evil)
        or bool(viewer_is_evil and target_is_evil and not same_player)
    )
