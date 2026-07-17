from .models import AvalonError, Role, STANDARD_CONFIGS


def build_roles(num_players):
    # Build the role list first. Role assignment code will shuffle it later.
    if num_players not in STANDARD_CONFIGS:
        raise AvalonError("Avalon supports 5 to 10 players.")

    config = STANDARD_CONFIGS[num_players]
    num_good = num_players - config.num_evil
    roles = [Role.MERLIN, Role.ASSASSIN]
    roles.extend([Role.MINION] * (config.num_evil - 1))
    roles.extend([Role.LOYAL_SERVANT] * (num_good - 1))
    return roles
