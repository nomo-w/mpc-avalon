import argparse
import asyncio
import contextlib
import secrets

from avalon.game.engine import AvalonEngine
from avalon.game.models import Alignment, AvalonError, GamePhase
from avalon.networking.json_stream import receive_json, send_json
from avalon.networking.messages import error, message
from avalon.protocols.mission_voting.gmw import GMWMissionVotingProtocol
from avalon.protocols.role_assignment.trusted import TrustedRoleAssignmentProtocol


# The server is the public judge of this game.
# It knows public state: players, leader, team, scores, phase.
# It should not receive plaintext mission votes.


class PlayerConnection:
    def __init__(self, player_id, name, mpc_host, mpc_port, reader, writer):
        self.player_id = player_id
        self.name = name
        self.mpc_host = mpc_host
        self.mpc_port = mpc_port
        self.reader = reader
        self.writer = writer


class GameServer:
    def __init__(self, host, port, expected_players, seed=None, rsa_key_size=2048):
        if expected_players < 5 or expected_players > 10:
            raise ValueError("--players must be between 5 and 10")
        self.host = host
        self.port = port
        self.expected_players = expected_players
        self.seed = seed
        self.rsa_key_size = rsa_key_size

        self.players = {}
        self._join_lock = asyncio.Lock()
        self._incoming = asyncio.Queue()
        self._game_task = None
        self._done = asyncio.Event()
        self._aborted = False
        self.engine = None
        self.mission_voting = GMWMissionVotingProtocol(self)
        self.plaintext_mission_vote_messages_seen = 0

    async def serve(self):
        # Start the public TCP server. Clients connect here first.
        server = await asyncio.start_server(self._handle_connection, host=self.host, port=self.port)
        addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
        print(f"Avalon server listening on {addresses}")
        print(f"Waiting for {self.expected_players} player(s).")
        async with server:
            await self._done.wait()
            server.close()
            await self._close_player_writers()
            await server.wait_closed()

    async def _handle_connection(self, reader, writer):
        player = None
        try:
            # First message must be join, because server needs player name
            # and the MPC address used later by secure mission voting.
            join = await receive_json(reader)
            if join.get("type") != "join":
                raise AvalonError("First message must be join.")
            player = await self._register_player(join, reader, writer)
            await self._read_player_messages(player)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await send_json(writer, error(str(exc)))
        finally:
            if player is not None and not self._done.is_set():
                # Put disconnect into the same queue as normal messages.
                # Then game loop can handle it in one place.
                await self._incoming.put((player.player_id, {"type": "disconnect", "message": "player disconnected"}))
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _register_player(self, join, reader, writer):
        async with self._join_lock:
            # Join is locked, so two clients cannot get the same player id.
            if self._game_task is not None:
                raise AvalonError("Game has already started.")
            if len(self.players) >= self.expected_players:
                raise AvalonError("Game is already full.")

            name = str(join.get("name", "")).strip()
            mpc_host = str(join.get("mpc_host", "")).strip()
            mpc_port = int(join.get("mpc_port", 0))
            if not name:
                raise AvalonError("Player name cannot be empty.")
            if any(existing.name == name for existing in self.players.values()):
                raise AvalonError(f"Player name {name!r} is already in use.")
            if not mpc_host:
                raise AvalonError("mpc_host cannot be empty.")
            if not 1 <= mpc_port <= 65535:
                raise AvalonError("mpc_port must be between 1 and 65535.")
            if any(
                existing.mpc_host == mpc_host and existing.mpc_port == mpc_port
                for existing in self.players.values()
            ):
                raise AvalonError("MPC endpoint is already in use.")

            player_id = len(self.players)
            player = PlayerConnection(
                player_id=player_id,
                name=name,
                mpc_host=mpc_host,
                mpc_port=mpc_port,
                reader=reader,
                writer=writer,
            )
            self.players[player_id] = player
            # Tell this client its fixed public player id.
            await send_json(
                writer,
                message("joined", player_id=player_id, players_expected=self.expected_players),
            )
            await self._broadcast_lobby()
            print(f"Player {player_id} joined: {name} at {mpc_host}:{mpc_port}")

            if len(self.players) == self.expected_players:
                # When enough players join, game starts automatically.
                self._game_task = asyncio.create_task(self._run_game())
            return player

    async def _read_player_messages(self, player):
        # All client messages are put into one queue.
        # The current game phase decides which message is valid.
        while not self._done.is_set():
            incoming = await receive_json(player.reader)
            await self._incoming.put((player.player_id, incoming))

    async def _broadcast_lobby(self):
        await self.broadcast(
            message(
                "lobby_update",
                players=[
                    {"player_id": p.player_id, "name": p.name}
                    for p in self.players.values()
                ],
                players_expected=self.expected_players,
            )
        )

    async def _run_game(self):
        try:
            ordered = [self.players[index] for index in range(self.expected_players)]
            # AvalonEngine only contains game rules and public state.
            self.engine = AvalonEngine(
                [player.name for player in ordered],
                seed=self.seed,
                mpc_endpoints=[(player.mpc_host, player.mpc_port) for player in ordered],
            )
            await self.broadcast(message("game_started", players=self.engine.public_dict()["players"]))

            # Current role assignment is trusted. Server shuffles roles here.
            # Later this part can be replaced by a secure role assignment module.
            self.engine.set_phase(GamePhase.TRUSTED_ROLE_ASSIGNMENT)
            role_protocol = TrustedRoleAssignmentProtocol(self.engine.rng)
            self.engine.set_roles(role_protocol.assign_roles(len(ordered)))
            for player in self.engine.players:
                await self.send_to(
                    player.player_id,
                    message(
                        "role_info",
                        role=player.role.value if player.role else None,
                        alignment=player.alignment.value if player.role else None,
                        private_lines=self.engine.private_role_lines_for(player.player_id),
                    ),
                )

            self.engine.set_phase(GamePhase.TEAM_PROPOSAL)
            await self.broadcast_state()
            # Main loop: run one phase, update state, then continue.
            while not self.engine.game_over:
                if self.engine.phase == GamePhase.TEAM_PROPOSAL:
                    await self._run_team_proposal()
                elif self.engine.phase == GamePhase.SECURE_MISSION_VOTE:
                    await self._run_secure_mission_vote()
                elif self.engine.phase == GamePhase.ASSASSINATION:
                    await self._run_assassination()
                elif self.engine.phase == GamePhase.GAME_OVER:
                    break
                else:
                    raise AvalonError(f"Unexpected phase {self.engine.phase.value}")

            await self._broadcast_game_over()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._aborted = True
            await self.broadcast(message("game_aborted", message=str(exc)))
            print(f"Game aborted: {exc}")
        finally:
            self._done.set()

    async def _run_team_proposal(self):
        assert self.engine is not None
        # Only current leader can choose a team.
        await self.send_to(
            self.engine.leader_id,
            message(
                "action_required",
                action="choose_team",
                team_size=self.engine.current_team_size,
            ),
        )
        while True:
            player_id, incoming = await self._next_message()
            try:
                if incoming.get("type") == "disconnect":
                    raise ConnectionError(incoming["message"])
                if incoming.get("type") != "team_proposal":
                    raise AvalonError("Expected a team_proposal message.")
                team = self.engine.propose_team(player_id, incoming.get("player_ids", []))
                await self.broadcast(
                    message(
                        "team_proposed",
                        leader_id=player_id,
                        team=team,
                    )
                )
                # After leader proposes, all players vote approve/reject.
                await self._collect_team_votes()
                return
            except AvalonError as exc:
                await self.send_to(player_id, error(str(exc)))

    async def _collect_team_votes(self):
        assert self.engine is not None
        await self.broadcast_state()
        # Team approval vote is public in Avalon.
        # So after all players vote, server will show who approved/rejected.
        await self.broadcast(
            message(
                "action_required",
                action="team_vote",
                team=list(self.engine.current_team),
            )
        )
        while len(self.engine.team_votes) < len(self.engine.players):
            player_id, incoming = await self._next_message()
            try:
                if incoming.get("type") == "disconnect":
                    raise ConnectionError(incoming["message"])
                if incoming.get("type") != "team_vote":
                    raise AvalonError("Expected a team_vote message.")
                complete = self.engine.submit_team_vote(
                    player_id,
                    bool(incoming.get("approve")),
                )
                await self.send_to(player_id, message("team_vote_recorded"))
                if complete:
                    break
            except AvalonError as exc:
                await self.send_to(player_id, error(str(exc)))

        approved, approvals, rejects = self.engine.resolve_team_vote()
        vote_details = [
            {
                "player_id": player_id,
                "name": self.engine.players[player_id].name,
                "approve": approve,
            }
            for player_id, approve in sorted(self.engine.team_votes.items())
        ]
        await self.broadcast(
            message(
                "team_vote_result",
                approved=approved,
                approvals=approvals,
                rejects=rejects,
                team=list(self.engine.current_team),
                votes=vote_details,
            )
        )
        self.engine.apply_team_vote_result(approved)
        await self.broadcast_state()

    async def _run_secure_mission_vote(self):
        assert self.engine is not None
        session_id = (
            f"game-{secrets.token_hex(4)}-mission-"
            f"{self.engine.current_mission_number}"
        )
        # The server coordinates the secure voting session,
        # but it does not collect Success/Fail plaintext votes.
        mission_failed = await self.mission_voting.resolve_vote(
            team_player_ids=list(self.engine.current_team),
            fail_threshold=self.engine.current_fail_threshold,
            session_id=session_id,
        )
        mission_number = self.engine.current_mission_number
        self.engine.apply_mission_result(mission_failed)
        await self.broadcast(
            message(
                "mission_result",
                session_id=session_id,
                mission_number=mission_number,
                mission_failed=mission_failed,
                mission_succeeded=not mission_failed,
                successful_missions=self.engine.successful_missions,
                failed_missions=self.engine.failed_missions,
            )
        )
        await self.broadcast_state()

    async def coordinate_gmw_vote(self, team_player_ids, fail_threshold, session_id):
        assert self.engine is not None
        team_members = [
            {
                "player_id": player_id,
                "name": self.engine.players[player_id].name,
            }
            for player_id in team_player_ids
        ]
        await self.broadcast(
            message(
                "secure_mission_vote_preparing",
                session_id=session_id,
                team_player_ids=team_player_ids,
                team_members=team_members,
                fail_threshold=fail_threshold,
            )
        )
        await asyncio.gather(
            *(
                self.send_to(
                    player_id,
                    message(
                        "prepare_secure_mission_vote",
                        session_id=session_id,
                        team_player_ids=team_player_ids,
                        team_members=team_members,
                        fail_threshold=fail_threshold,
                    ),
                )
                for player_id in team_player_ids
            )
        )

        # Step 1: ask team members to enter mission vote locally.
        # They only tell server "I am ready", not the vote value.
        ready_players = set()
        while len(ready_players) < len(team_player_ids):
            player_id, incoming = await self._next_message()
            try:
                if incoming.get("type") == "disconnect":
                    raise ConnectionError(incoming["message"])
                if incoming.get("type") == "mission_vote":
                    self.plaintext_mission_vote_messages_seen += 1
                    raise AvalonError("Plaintext mission votes are not accepted by the server.")
                if incoming.get("type") != "secure_vote_ready":
                    raise AvalonError("Expected a secure_vote_ready message.")
                if player_id not in team_player_ids:
                    raise AvalonError("Only mission team members prepare mission votes.")
                if str(incoming.get("session_id", "")) != session_id:
                    raise AvalonError("Secure vote readiness used the wrong session ID.")
                if player_id in ready_players:
                    raise AvalonError("You already prepared this mission vote.")
                ready_players.add(player_id)
                await self.send_to(player_id, message("secure_vote_ready_recorded"))
            except AvalonError as exc:
                await self.send_to(player_id, error(str(exc)))

        # Step 2: send each team member the peer addresses.
        # After this, clients talk to each other directly for GMW + OT.
        endpoints = [
            {
                "host": self.engine.players[player_id].mpc_host,
                "port": self.engine.players[player_id].mpc_port,
            }
            for player_id in team_player_ids
        ]
        await asyncio.gather(
            *(
                self.send_to(
                    player_id,
                    message(
                        "start_secure_mission_vote",
                        protocol="avalon-gmw-rsa-ot-v1",
                        session_id=session_id,
                        team_player_ids=team_player_ids,
                        party_player_ids=team_player_ids,
                        fail_threshold=fail_threshold,
                        endpoints=endpoints,
                        rsa_key_size=self.rsa_key_size,
                    ),
                )
                for player_id in team_player_ids
            )
        )

        # Step 3: every team client sends back the same final Boolean result.
        # The result is mission_failed only. It is not "who voted Fail".
        while len(self.engine.secure_vote_results) < len(team_player_ids):
            player_id, incoming = await self._next_message()
            try:
                if incoming.get("type") == "disconnect":
                    raise ConnectionError(incoming["message"])
                if incoming.get("type") == "mission_vote":
                    self.plaintext_mission_vote_messages_seen += 1
                    raise AvalonError("Plaintext mission votes are not accepted by the server.")
                if incoming.get("type") != "secure_vote_result":
                    raise AvalonError("Expected a secure_vote_result message.")
                complete = self.engine.submit_secure_vote_result(
                    player_id=player_id,
                    session_id=str(incoming.get("session_id", "")),
                    expected_session_id=session_id,
                    mission_failed=bool(incoming.get("mission_failed")),
                )
                await self.send_to(player_id, message("secure_vote_result_recorded"))
                if complete:
                    break
            except AvalonError as exc:
                await self.send_to(player_id, error(str(exc)))

        return self.engine.resolve_secure_vote_results()

    async def _run_assassination(self):
        assert self.engine is not None
        assassin_id = self.engine.assassin().player_id
        # If Good gets three successful missions, Assassin may guess Merlin.
        await self.broadcast_state()
        await self.broadcast(message("assassination_started", assassin_id=assassin_id))
        await self.send_to(
            assassin_id,
            message("action_required", action="assassinate"),
        )
        while True:
            player_id, incoming = await self._next_message()
            try:
                if incoming.get("type") == "disconnect":
                    raise ConnectionError(incoming["message"])
                if incoming.get("type") != "assassination_target":
                    raise AvalonError("Expected an assassination_target message.")
                target_id = int(incoming.get("target_id"))
                winner = self.engine.resolve_assassination(player_id, target_id)
                await self.broadcast(
                    message(
                        "assassination_result",
                        assassin_id=player_id,
                        target_id=target_id,
                        winner=winner.value,
                    )
                )
                return
            except AvalonError as exc:
                await self.send_to(player_id, error(str(exc)))

    async def _broadcast_game_over(self):
        assert self.engine is not None
        await self.broadcast(
            message(
                "game_over",
                winner=self.engine.winner.value if self.engine.winner else None,
                roles=self.engine.reveal_roles(),
                plaintext_mission_vote_messages_seen=self.plaintext_mission_vote_messages_seen,
            )
        )

    async def _next_message(self):
        player_id, incoming = await self._incoming.get()
        if self._aborted:
            raise AvalonError("The game was aborted.")
        return player_id, incoming

    async def broadcast_state(self):
        assert self.engine is not None
        await self.broadcast(message("public_state", state=self.engine.public_dict()))

    async def broadcast(self, payload):
        await asyncio.gather(
            *(self.send_to(player_id, payload) for player_id in list(self.players)),
            return_exceptions=True,
        )

    async def send_to(self, player_id, payload):
        player = self.players.get(player_id)
        if player is None:
            return
        await send_json(player.writer, payload)

    async def _close_player_writers(self):
        for player in list(self.players.values()):
            player.writer.close()
        for player in list(self.players.values()):
            with contextlib.suppress(Exception):
                await player.writer.wait_closed()


async def async_main(args):
    server = GameServer(
        host=args.host,
        port=args.port,
        expected_players=args.players,
        seed=args.seed,
        rsa_key_size=args.rsa_key_size,
    )
    await server.serve()


def main():
    parser = argparse.ArgumentParser(description="Networked command-line Avalon server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--players", type=int, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--rsa-key-size", type=int, default=2048)
    args = parser.parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("Server stopped.")


if __name__ == "__main__":
    main()
