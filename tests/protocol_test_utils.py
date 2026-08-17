import asyncio
import socket
import unittest
import uuid

from avalon.protocols.mission_voting.secure_vote.network import PartyEndpoint


class ProtocolAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        loop = asyncio.get_running_loop()
        loop.set_debug(False)
        loop.slow_callback_duration = 10.0


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


def localhost_endpoints(count):
    return [
        PartyEndpoint("127.0.0.1", port)
        for port in free_ports(count)
    ]


def unique_session(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
