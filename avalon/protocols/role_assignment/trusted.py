from avalon.game.rules import build_roles


class TrustedRoleAssignmentProtocol:
    # Current role assignment is trusted.
    # Server shuffles roles here, so server knows all roles for now.
    # Later this file can be replaced by secure role assignment.

    def __init__(self, rng):
        self.rng = rng

    def assign_roles(self, num_players):
        roles = build_roles(num_players)
        self.rng.shuffle(roles)
        return roles
