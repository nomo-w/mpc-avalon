import argparse
import asyncio

from avalon.game.models import Alignment, Role
from avalon.networking.json_stream import receive_json, send_json
from avalon.networking.messages import message
from avalon.protocols.mission_voting.secure_vote.network import PartyEndpoint
from avalon.protocols.mission_voting.secure_vote.protocol import (
    MissionVoteConfiguration,
    run_secure_mission_vote,
)
from avalon.protocols.role_assignment.network_mental_poker import (
    run_network_mental_poker_role_assignment,
)
from avalon.protocols.role_assignment.secure_role_information import (
    run_secure_role_information,
)


# The client is one player's terminal program.
# It connects to server for public game messages.
# During mission voting, it also connects to other mission members for MPC.


def parse_yes_no(raw):
    value = raw.strip().lower()
    if value in {"y", "yes"}:
        return True
    if value in {"n", "no"}:
        return False
    raise ValueError("Please enter y or n.")


def parse_mission_vote(raw):
    value = raw.strip().lower()
    if value in {"s", "success", "succeed", "0"}:
        return 0
    if value in {"f", "fail", "failed", "1"}:
        return 1
    raise ValueError("Please enter success or fail.")


class ConsoleInputProvider:
    # All command line input is kept in this class.
    # This makes AvalonClient mostly handle network messages.

    async def choose_team(self, state, team_size):
        self._show_players(state)
        while True:
            raw = await asyncio.to_thread(
                input,
                f"Select {team_size} players by ID, separated by spaces: ",
            )
            try:
                team = [int(value) for value in raw.split()]
            except ValueError:
                print("Please enter numeric player IDs.")
                continue
            if len(team) != team_size:
                print(f"Please select exactly {team_size} players.")
                continue
            return team

    async def approve_team(self, team, state):
        names = self._names_for(team, state)
        while True:
            raw = await asyncio.to_thread(input, f"Approve team {names}? [y/n]: ")
            try:
                return parse_yes_no(raw)
            except ValueError as exc:
                print(exc)

    async def mission_vote(self, role, session_id):
        del session_id
        if role.alignment == Alignment.GOOD:
            # Good player cannot choose Fail in normal Avalon rule.
            print("You are Good. Mission vote is Success.")
            await asyncio.to_thread(input, "Press Enter to submit Success...")
            return 0
        while True:
            raw = await asyncio.to_thread(
                input,
                "Private mission vote [Success/Fail]: ",
            )
            try:
                return parse_mission_vote(raw)
            except ValueError as exc:
                print(exc)

    async def assassination_target(self, state):
        self._show_players(state)
        while True:
            raw = await asyncio.to_thread(input, "Choose a player ID to assassinate: ")
            try:
                return int(raw)
            except ValueError:
                print("Please enter a numeric player ID.")

    def _show_players(self, state):
        print("Players:")
        for player in state.get("players", []):
            print(f"  {player['player_id']}: {player['name']}")

    def _names_for(self, player_ids, state):
        names = {
            int(player["player_id"]): str(player["name"])
            for player in state.get("players", [])
        }
        return ", ".join(f"{player_id}:{names.get(player_id, '?')}" for player_id in player_ids)


class AvalonClient:
    def __init__(self, host, port, name, mpc_host, mpc_port, listen_host, input_provider=None, mpc_timeout=60.0):
        self.host = host
        self.port = port
        self.name = name
        self.mpc_host = mpc_host
        self.mpc_port = mpc_port
        self.listen_host = listen_host
        self.input_provider = input_provider or ConsoleInputProvider()
        self.mpc_timeout = mpc_timeout

        self.player_id = None
        self.role = None
        self.alignment = None
        self.state = {}
        self.reader = None
        self.writer = None
        # Mission vote is saved here after player input.
        # Later GMW code reads it and never sends plaintext vote to server.
        self.pending_mission_votes = {}
        # Used to avoid printing same public state many times.
        self._last_printed_state = None

    async def run(self):
        # This is the public connection to Avalon server.
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        try:
            await self._send(
                message(
                    "join",
                    name=self.name,
                    mpc_host=self.mpc_host,
                    mpc_port=self.mpc_port,
                )
            )
            while True:
                incoming = await receive_json(self.reader)
                done = await self.handle_message(incoming)
                if done:
                    return
        finally:
            if self.writer is not None:
                self.writer.close()
                await self.writer.wait_closed()

    async def handle_message(self, incoming):
        # Server messages are handled here.
        # Some messages only print text, some messages ask user for action.
        message_type = incoming.get("type")
        if message_type == "joined":
            self.player_id = int(incoming["player_id"])
            print(f"Joined as Player {self.player_id}: {self.name}")
        elif message_type == "lobby_update":
            print(f"Lobby: {len(incoming.get('players', []))}/{incoming.get('players_expected')} players connected.")
        elif message_type == "game_started":
            print("Game started.")
        elif message_type == "role_info":
            self.role = Role(str(incoming["role"]))
            self.alignment = Alignment(str(incoming["alignment"]))
            print("\nPrivate role information")
            print("-" * 40)
            for line in incoming.get("private_lines", []):
                print(line)
            print("-" * 40)
        elif message_type == "public_state":
            self.state = dict(incoming["state"])
            # Server may send public state after several events.
            # If it is same as before, do not print again.
            if self.state != self._last_printed_state:
                self._print_state()
                self._last_printed_state = dict(self.state)
        elif message_type == "team_proposed":
            print(f"Leader proposed team: {self._names_for_ids(incoming['team'])}")
        elif message_type == "team_vote_result":
            result = "approved" if incoming["approved"] else "rejected"
            print(
                f"Team {result}: {incoming['approvals']} approve, "
                f"{incoming['rejects']} reject."
            )
            print("Public team approval votes:")
            for vote in incoming.get("votes", []):
                choice = "Approve" if vote["approve"] else "Reject"
                print(f"  {vote['player_id']}:{vote['name']} - {choice}")
        elif message_type == "secure_mission_vote_preparing":
            # Everyone can see the mission team.
            # Only selected members need to type a private mission vote.
            print(
                "Mission team: "
                + self._names_for_members(incoming.get("team_members", []))
            )
            if self.player_id not in {int(value) for value in incoming["team_player_ids"]}:
                print("Secure mission vote is preparing; not on this mission.")
        elif message_type == "start_secure_role_assignment":
            await self._run_secure_role_assignment(incoming)
        elif message_type == "prepare_secure_mission_vote":
            await self._prepare_secure_mission_vote(incoming)
        elif message_type == "start_secure_mission_vote":
            await self._run_secure_mission_vote(incoming)
        elif message_type == "mission_result":
            print(
                "Mission failed."
                if incoming["mission_failed"]
                else "Mission succeeded."
            )
        elif message_type == "assassination_started":
            if incoming.get("assassin_hidden"):
                print("Assassination phase. Waiting for the Assassin.")
            else:
                print(f"Assassination phase. Assassin is Player {incoming['assassin_id']}.")
        elif message_type == "assassination_result":
            print(
                f"Assassin chose Player {incoming['target_id']}. "
                f"Winner: {incoming['winner']}."
            )
        elif message_type == "check_assassination_target":
            await self._send_assassination_target_check(incoming)
        elif message_type == "request_final_role_reveal":
            await self._send_final_role_reveal()
        elif message_type == "action_required":
            await self._handle_action(incoming)
        elif message_type == "error":
            print(f"Server error: {incoming.get('message')}")
        elif message_type == "role_assignment_done_recorded":
            print("Secure role assignment complete.")
        elif message_type == "final_role_reveal_recorded":
            print("Final role reveal recorded.")
        elif message_type == "secure_role_information_complete":
            print("Secure role information complete.")
        elif message_type == "game_aborted":
            raise RuntimeError(f"Game aborted: {incoming.get('message')}")
        elif message_type == "game_over":
            print("\nGame over")
            print("=" * 40)
            print(f"Winner: {incoming.get('winner')}")
            print("Final roles:")
            for role in incoming.get("roles", []):
                print(
                    f"  {role['player_id']}: {role['name']} - "
                    f"{role['role']} ({role['alignment']})"
                )
            return True
        return False

    async def _handle_action(self, incoming):
        # action_required means this client must send something back.
        action = incoming.get("action")
        if action == "choose_team":
            team = await self.input_provider.choose_team(
                self.state,
                int(incoming["team_size"]),
            )
            await self._send(message("team_proposal", player_ids=team))
        elif action == "team_vote":
            team = [int(value) for value in incoming["team"]]
            approve = await self.input_provider.approve_team(team, self.state)
            await self._send(message("team_vote", approve=approve))
        elif action == "assassinate":
            target_id = await self.input_provider.assassination_target(self.state)
            await self._send(message("assassination_target", target_id=target_id))
        elif action == "assassinate_if_assassin":
            # In Mental Poker mode, only the local Assassin should act.
            if self.role == Role.ASSASSIN:
                target_id = await self.input_provider.assassination_target(self.state)
                await self._send(message("assassination_target", target_id=target_id))
            else:
                print("Waiting for the Assassin to choose a target.")

    async def _run_secure_role_assignment(self, incoming):
        # Mental Poker role assignment runs between all players.
        # The server only starts the session and gives peer addresses.
        if self.player_id is None:
            raise RuntimeError("Client has not received a player ID.")
        if incoming.get("protocol") != "avalon-mental-poker-v1":
            raise RuntimeError("Server requested an unsupported role protocol.")

        party_player_ids = [int(value) for value in incoming["party_player_ids"]]
        if self.player_id not in party_player_ids:
            return
        party_id = party_player_ids.index(self.player_id)
        endpoints = [
            PartyEndpoint(str(item["host"]), int(item["port"]))
            for item in incoming["endpoints"]
        ]
        session_id = str(incoming["session_id"])

        print("Secure role assignment is running.")
        role_result = await run_network_mental_poker_role_assignment(
            party_id=party_id,
            endpoints=endpoints,
            listen_host=self.listen_host,
            session_id=session_id,
            connect_timeout=self.mpc_timeout,
        )
        self.role = role_result.role
        self.alignment = role_result.role.alignment

        # After dealing, role information is computed as private Boolean outputs.
        info_result = await run_secure_role_information(
            party_id=party_id,
            endpoints=endpoints,
            listen_host=self.listen_host,
            session_id=session_id + ":role-info",
            local_role=self.role,
            player_names=[str(value) for value in incoming["player_names"]],
            rsa_key_size=int(incoming["rsa_key_size"]),
            connect_timeout=self.mpc_timeout,
        )
        print("\nPrivate role information")
        print("-" * 40)
        for line in info_result.private_lines:
            print(line)
        print("-" * 40)

        # Tell server the secure role assignment finished.
        # Do not send the role here, because server should not know it now.
        await self._send(
            message(
                "role_assignment_done",
                session_id=role_result.session_id,
            )
        )

    async def _send_assassination_target_check(self, incoming):
        # The selected target reveals only whether it is Merlin.
        # This is enough to decide the assassination result.
        if self.player_id is None:
            raise RuntimeError("Client has not received a player ID.")
        if self.role is None:
            raise RuntimeError("Client has not received role information.")
        target_id = int(incoming["target_id"])
        if target_id != self.player_id:
            return
        await self._send(
            message(
                "assassination_target_check",
                target_id=target_id,
                is_merlin=(self.role == Role.MERLIN),
            )
        )

    async def _send_final_role_reveal(self):
        # Roles are public at game over, so now client can reveal it.
        if self.role is None:
            raise RuntimeError("Client has not received role information.")
        await self._send(
            message(
                "final_role_reveal",
                role=self.role.value,
                alignment=self.role.alignment.value,
            )
        )

    async def _run_secure_mission_vote(self, incoming):
        # This is the real secure voting part.
        # By this time, the local vote is already typed and saved.
        if self.player_id is None:
            raise RuntimeError("Client has not received a player ID.")
        if self.role is None:
            raise RuntimeError("Client has not received role information.")
        if incoming.get("protocol") != "avalon-gmw-rsa-ot-v1":
            raise RuntimeError("Server requested an unsupported secure vote protocol.")

        party_player_ids = [int(value) for value in incoming["party_player_ids"]]
        if self.player_id not in party_player_ids:
            return
        # party_id is local id inside this MPC session.
        # It may be different from public Avalon player id.
        party_id = party_player_ids.index(self.player_id)
        endpoints = [
            PartyEndpoint(str(item["host"]), int(item["port"]))
            for item in incoming["endpoints"]
        ]
        team_ids = tuple(range(len(party_player_ids)))
        session_id = str(incoming["session_id"])
        # In current design, all MPC parties are mission team members.
        configuration = MissionVoteConfiguration.create(
            session_id=session_id,
            team_ids=team_ids,
            fail_threshold=int(incoming["fail_threshold"]),
            party_count=len(endpoints),
        )

        try:
            local_vote = self.pending_mission_votes.pop(session_id)
        except KeyError as exc:
            raise RuntimeError("Mission vote was not prepared before GMW start.") from exc

        outcome = await run_secure_mission_vote(
            party_id=party_id,
            endpoints=endpoints,
            listen_host=self.listen_host,
            configuration=configuration,
            local_fail_vote=local_vote,
            rsa_key_size=int(incoming["rsa_key_size"]),
            connect_timeout=self.mpc_timeout,
        )
        # Send only the final mission_failed result to server.
        # All mission members should send the same result.
        await self._send(
            message(
                "secure_vote_result",
                session_id=outcome.session_id,
                mission_failed=outcome.mission_failed,
                statistics={
                    "and_gates": outcome.statistics.and_gates,
                    "xor_gates": outcome.statistics.xor_gates,
                    "oblivious_transfers_for_this_party": outcome.statistics.oblivious_transfers,
                },
            )
        )

    async def _prepare_secure_mission_vote(self, incoming):
        # First step of secure mission vote:
        # player enters private vote locally, then tells server "ready".
        if self.player_id is None:
            raise RuntimeError("Client has not received a player ID.")
        if self.role is None:
            raise RuntimeError("Client has not received role information.")
        session_id = str(incoming["session_id"])
        team_ids = {int(value) for value in incoming["team_player_ids"]}
        if self.player_id not in team_ids:
            return
        print(
            "You are on this mission team: "
            + self._names_for_members(incoming.get("team_members", []))
        )
        local_vote = await self.input_provider.mission_vote(self.role, session_id)
        self.pending_mission_votes[session_id] = local_vote
        await self._send(message("secure_vote_ready", session_id=session_id))

    def _print_state(self):
        # Print short public status for each phase.
        if not self.state:
            return
        print(
            f"\nPhase: {self.state['phase']} | "
            f"Mission {self.state['mission_number']}/5 | "
            f"Success {self.state['successful_missions']} - "
            f"Fail {self.state['failed_missions']} | "
            f"Leader: Player {self.state['leader_id']}"
        )
        print(
            f"Team size: {self.state['mission_team_size']} | "
            f"Fail threshold: {self.state['fail_threshold']} | "
            f"Rejected teams: {self.state['rejected_team_proposals']}/5"
        )

    def _names_for_ids(self, player_ids):
        names = {
            int(player["player_id"]): str(player["name"])
            for player in self.state.get("players", [])
        }
        return ", ".join(f"{int(player_id)}:{names.get(int(player_id), '?')}" for player_id in player_ids)

    def _names_for_members(self, members):
        if members:
            return ", ".join(
                f"{int(member['player_id'])}:{member['name']}"
                for member in members
            )
        return self._names_for_ids([])

    async def _send(self, payload):
        if self.writer is None:
            raise RuntimeError("Client is not connected.")
        # All client-server messages go through this helper.
        await send_json(self.writer, payload)


async def async_main(args):
    mpc_host = args.advertise_host or "127.0.0.1"
    client = AvalonClient(
        host=args.host,
        port=args.port,
        name=args.name,
        mpc_host=mpc_host,
        mpc_port=args.mpc_port,
        listen_host=args.listen_host,
        mpc_timeout=args.mpc_timeout,
    )
    await client.run()


def main():
    parser = argparse.ArgumentParser(description="Networked command-line Avalon client")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--advertise-host",
        help="IP/hostname other player clients use to reach this client for MPC",
    )
    parser.add_argument(
        "--listen-host",
        default="0.0.0.0",
        help="local interface for this client's MPC listener",
    )
    parser.add_argument("--mpc-port", type=int, required=True)
    parser.add_argument("--mpc-timeout", type=float, default=60.0)
    args = parser.parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("Client stopped.")


if __name__ == "__main__":
    main()
