import argparse
import asyncio
import contextlib
import io
import os
import socket
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from avalon.game.rules import build_roles
from client import AvalonClient
from server import GameServer


PLAYER_NAMES = ["Alice", "Bob", "Charlie", "David", "Eve"]


class ScriptedInputProvider:
    # This replaces manual terminal input in the system test.
    # It keeps the full server/client flow, but answers automatically.

    async def choose_team(self, state, team_size):
        mission_number = int(state.get("mission_number", 1))
        teams = {
            1: [0, 1],
            2: [0, 1, 2],
            3: [2, 3],
            4: [0, 2, 4],
            5: [1, 3, 4],
        }
        team = teams.get(mission_number, list(range(team_size)))
        return team[:team_size]

    async def approve_team(self, team, state):
        return True

    async def mission_vote(self, role, session_id):
        # The system test uses all Success votes.
        # This makes the game reach assassination after three missions.
        return 0

    async def assassination_target(self, state):
        return 0


def free_ports(count):
    sockets = []
    ports = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            ports.append(sock.getsockname()[1])
            sockets.append(sock)
        return ports
    finally:
        for sock in sockets:
            sock.close()


async def run_game(timeout):
    player_count = len(PLAYER_NAMES)
    ports = free_ports(player_count + 1)
    server_port = ports[0]
    mpc_ports = ports[1:]

    server = GameServer(
        host="127.0.0.1",
        port=server_port,
        expected_players=player_count,
    )
    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.2)

    clients = []
    client_tasks = []
    for name, mpc_port in zip(PLAYER_NAMES, mpc_ports):
        client = AvalonClient(
            host="127.0.0.1",
            port=server_port,
            name=name,
            mpc_host="127.0.0.1",
            mpc_port=mpc_port,
            listen_host="127.0.0.1",
            input_provider=ScriptedInputProvider(),
            mpc_timeout=90.0,
        )
        clients.append(client)
        client_tasks.append(asyncio.create_task(client.run()))

    try:
        await asyncio.wait_for(asyncio.gather(*client_tasks), timeout=timeout)
        await asyncio.wait_for(server_task, timeout=10.0)
    finally:
        for task in client_tasks:
            if not task.done():
                task.cancel()
        if not server_task.done():
            server._done.set()
            server_task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.gather(*client_tasks, return_exceptions=True)
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await server_task

    check_result(server, clients)
    return server


def check_result(server, clients):
    if server.engine is None:
        raise AssertionError("server did not create the game engine")
    if server._aborted:
        raise AssertionError("server aborted the game")
    if not server.engine.game_over:
        raise AssertionError("game did not finish")
    if server.engine.successful_missions != 3:
        raise AssertionError("system test expected three successful missions")
    if server.engine.failed_missions != 0:
        raise AssertionError("system test expected zero failed missions")
    if server.plaintext_mission_vote_messages_seen != 0:
        raise AssertionError("server received plaintext mission votes")

    player_ids = {client.player_id for client in clients}
    if player_ids != set(range(len(clients))):
        raise AssertionError("not all clients received a valid player id")
    if any(client.role is None for client in clients):
        raise AssertionError("some clients did not receive a role")

    expected_roles = Counter(role.value for role in build_roles(len(clients)))
    actual_roles = Counter(role.value for role in server.final_role_reveals.values())
    if actual_roles != expected_roles:
        raise AssertionError("final role reveal does not match Avalon rules")


async def run_with_optional_logs(timeout, verbose):
    if verbose:
        return await run_game(timeout)

    logs = io.StringIO()
    try:
        with contextlib.redirect_stdout(logs):
            return await run_game(timeout)
    except Exception:
        print("\nCaptured system test output:")
        print(logs.getvalue())
        raise


def main():
    parser = argparse.ArgumentParser(description="Run one automated 5-player Avalon system test")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print("Running automated 5-player system test...")
    server = asyncio.run(run_with_optional_logs(args.timeout, args.verbose))

    role_counts = Counter(role.value for role in server.final_role_reveals.values())
    roles = ", ".join(f"{role}: {count}" for role, count in sorted(role_counts.items()))
    print("System test passed.")
    print(f"Winner: {server.engine.winner.value}")
    print(f"Missions: {server.engine.successful_missions} success, {server.engine.failed_missions} fail")
    print(f"Final role counts: {roles}")


if __name__ == "__main__":
    main()
