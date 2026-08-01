from avalon.game.models import Alignment, AvalonError, Role


class RoleInformationResult:
    # Private information one player should receive after role assignment.
    def __init__(self, viewer_id, role, visible_evil_player_ids):
        self.viewer_id = int(viewer_id)
        self.role = role
        self.visible_evil_player_ids = list(visible_evil_player_ids)

    @property
    def alignment(self):
        return self.role.alignment

    def public_dict(self):
        return {
            "viewer_id": self.viewer_id,
            "role": self.role.value,
            "alignment": self.alignment.value,
            "visible_evil_player_ids": list(self.visible_evil_player_ids),
        }


def role_bits(role):
    # These 0/1 values are the role attributes used by the Boolean rule.
    role = _clean_role(role)
    is_evil = 1 if role.alignment == Alignment.EVIL else 0
    return {
        "is_merlin": 1 if role == Role.MERLIN else 0,
        "is_assassin": 1 if role == Role.ASSASSIN else 0,
        "is_minion": 1 if role == Role.MINION else 0,
        "is_loyal_servant": 1 if role == Role.LOYAL_SERVANT else 0,
        "is_evil": is_evil,
        "is_good": 1 - is_evil,
    }


def can_view_target_evil(viewer_role, target_role, same_player):
    # Merlin sees evil players.
    # Evil players see other evil players.
    viewer = role_bits(viewer_role)
    target = role_bits(target_role)
    same_player_bit = 1 if same_player else 0

    merlin_case = viewer["is_merlin"] & target["is_evil"]
    evil_case = viewer["is_evil"] & target["is_evil"] & (1 - same_player_bit)
    return merlin_case | evil_case


def visibility_bits_for_viewer(viewer_id, roles):
    roles = _clean_roles(roles)
    viewer_id = int(viewer_id)
    if not 0 <= viewer_id < len(roles):
        raise AvalonError("Invalid viewer id.")
    viewer_role = roles[viewer_id]
    return [
        can_view_target_evil(
            viewer_role=viewer_role,
            target_role=target_role,
            same_player=(viewer_id == target_id),
        )
        for target_id, target_role in enumerate(roles)
    ]


def visible_evil_player_ids_for_viewer(viewer_id, roles):
    bits = visibility_bits_for_viewer(viewer_id, roles)
    return [player_id for player_id, bit in enumerate(bits) if bit]


def role_information_for_viewer(viewer_id, roles):
    roles = _clean_roles(roles)
    viewer_id = int(viewer_id)
    if not 0 <= viewer_id < len(roles):
        raise AvalonError("Invalid viewer id.")
    return RoleInformationResult(
        viewer_id=viewer_id,
        role=roles[viewer_id],
        visible_evil_player_ids=visible_evil_player_ids_for_viewer(viewer_id, roles),
    )


def role_information_for_all(roles):
    roles = _clean_roles(roles)
    return [
        role_information_for_viewer(viewer_id, roles)
        for viewer_id in range(len(roles))
    ]


def private_role_lines(player_id, player_names, roles):
    # Same display rule as the current trusted engine, but based on Boolean visibility.
    roles = _clean_roles(roles)
    info = role_information_for_viewer(player_id, roles)
    return private_role_lines_from_visible(
        player_id=player_id,
        player_names=player_names,
        role=info.role,
        visible_evil_player_ids=info.visible_evil_player_ids,
    )


def private_role_lines_from_visible(player_id, player_names, role, visible_evil_player_ids):
    # Same text format, but caller already computed the visible evil list.
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


def _clean_roles(roles):
    if not roles:
        raise AvalonError("Role information requires at least one role.")
    return [_clean_role(role) for role in roles]
