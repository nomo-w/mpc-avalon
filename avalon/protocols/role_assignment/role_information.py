from avalon.game.models import Alignment, Role


def role_bits(role):
    # These two bits are enough for Merlin/evil visibility.
    role = _clean_role(role)
    is_evil = 1 if role.alignment == Alignment.EVIL else 0
    return {
        "is_merlin": 1 if role == Role.MERLIN else 0,
        "is_evil": is_evil,
    }


def private_role_lines_from_visible(player_names, role, visible_evil_player_ids):
    # Build the private text shown only on this player's client.
    role = _clean_role(role)
    visible_evil_player_ids = list(visible_evil_player_ids)
    alignment = role.alignment
    lines = [f"You are {role.value} ({alignment.value})."]
    if role == Role.MERLIN:
        visible = _format_player_list(visible_evil_player_ids, player_names)
        lines.append(f"Merlin information: Evil players are {visible}.")
    elif alignment == Alignment.EVIL:
        if visible_evil_player_ids:
            visible = _format_player_list(visible_evil_player_ids, player_names)
            lines.append("Evil information: Other evil players are " + visible + ".")
        else:
            lines.append("Evil information: You are the only evil player.")
    else:
        lines.append("You have no additional information.")
    return lines


def _format_player_list(player_ids, player_names):
    return ", ".join(
        f"{player_id}:{player_names[player_id]}"
        for player_id in player_ids
    )


def _clean_role(role):
    if isinstance(role, Role):
        return role
    return Role(str(role))
