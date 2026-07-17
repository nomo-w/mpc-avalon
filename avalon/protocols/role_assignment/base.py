class RoleAssignmentProtocol:
    # Only a small parent class for role assignment modules.
    # Real code should return one role for each player id.

    def assign_roles(self, num_players):
        raise NotImplementedError
