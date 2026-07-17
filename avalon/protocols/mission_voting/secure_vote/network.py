import asyncio
import contextlib
import json


MAX_MESSAGE_BYTES = 1000000


# This file is only for client-to-client MPC messages.
# It is different from avalon/networking, because that one is for client-server.
# During mission vote, mission team clients connect with each other directly.


async def send_json(writer, message):
    data = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("network message is too large")
    writer.write(data + b"\n")
    await writer.drain()


async def receive_json(reader):
    raw = await reader.readline()
    if not raw:
        raise ConnectionError("peer closed the connection")
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError("network message is too large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


class PartyEndpoint:
    # One player's address for MPC connection.

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def validate(self):
        if not self.host.strip():
            raise ValueError("endpoint host cannot be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("endpoint port must be between 1 and 65535")


class _PeerConnection:
    def __init__(self, reader, writer, send_lock, receive_lock):
        self.reader = reader
        self.writer = writer
        self.send_lock = send_lock
        self.receive_lock = receive_lock


class PeerNetwork:
    # Full mesh peer network for one secure vote.
    # To avoid duplicate connections:
    # party i connects to parties with smaller id,
    # and accepts connections from parties with larger id.

    def __init__(self, party_id, endpoints, listen_host, connect_timeout=30.0, retry_delay=0.1):
        if not 0 <= party_id < len(endpoints):
            raise ValueError("invalid party_id")
        if len(endpoints) < 2:
            raise ValueError("at least two MPC parties are required")
        for endpoint in endpoints:
            endpoint.validate()

        self.party_id = party_id
        self.endpoints = endpoints
        self.listen_host = listen_host
        self.connect_timeout = connect_timeout
        self.retry_delay = retry_delay

        self._server = None
        self._connections = {}
        self._connections_changed = asyncio.Condition()
        self._closed = asyncio.Event()
        self._handler_tasks = set()

    @property
    def party_count(self):
        return len(self.endpoints)

    async def start(self):
        # Start local listener first, so other players can connect to us.
        own_endpoint = self.endpoints[self.party_id]
        self._server = await asyncio.start_server(
            self._handle_incoming,
            host=self.listen_host,
            port=own_endpoint.port,
        )

        # Connect to lower-numbered parties. Higher-numbered parties will connect to us.
        await asyncio.gather(
            *(self._connect_with_retry(peer_id) for peer_id in range(self.party_id))
        )

        # Wait until all peer connections are ready before the MPC starts.
        async with self._connections_changed:
            await asyncio.wait_for(
                self._connections_changed.wait_for(
                    lambda: len(self._connections) == self.party_count - 1
                ),
                timeout=self.connect_timeout,
            )

    async def _connect_with_retry(self, peer_id):
        endpoint = self.endpoints[peer_id]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.connect_timeout
        last_error = None
        # Some clients may start a little later, so we retry for a short time.
        while loop.time() < deadline:
            try:
                reader, writer = await asyncio.open_connection(
                    endpoint.host, endpoint.port
                )
                await send_json(
                    writer,
                    {
                        "type": "peer_hello",
                        "party_id": self.party_id,
                    },
                )
                await self._store_connection(peer_id, reader, writer)
                return
            except (ConnectionError, OSError) as exc:
                last_error = exc
                await asyncio.sleep(self.retry_delay)
        raise TimeoutError(
            f"party {self.party_id} could not connect to party {peer_id} "
            f"at {endpoint.host}:{endpoint.port}: {last_error}"
        )

    async def _handle_incoming(self, reader, writer):
        task = asyncio.current_task()
        if task is not None:
            self._handler_tasks.add(task)
        try:
            hello = await asyncio.wait_for(
                receive_json(reader), timeout=self.connect_timeout
            )
            if hello.get("type") != "peer_hello":
                raise ValueError("first peer message must be peer_hello")
            peer_id = int(hello["party_id"])
            if not self.party_id < peer_id < self.party_count:
                raise ValueError(
                    "incoming connections must come from a higher-numbered party"
                )
            # After the connection is stored, this handler just waits until close().
            await self._store_connection(peer_id, reader, writer)
            await self._closed.wait()
        except Exception:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            raise
        finally:
            if task is not None:
                self._handler_tasks.discard(task)

    async def _store_connection(self, peer_id, reader, writer):
        async with self._connections_changed:
            if peer_id in self._connections:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                raise RuntimeError(f"duplicate connection for party {peer_id}")
            self._connections[peer_id] = _PeerConnection(
                reader=reader,
                writer=writer,
                send_lock=asyncio.Lock(),
                receive_lock=asyncio.Lock(),
            )
            self._connections_changed.notify_all()

    def _connection(self, peer_id):
        if peer_id == self.party_id:
            raise ValueError("cannot send a peer message to yourself")
        try:
            return self._connections[peer_id]
        except KeyError as exc:
            raise RuntimeError(f"party {peer_id} is not connected") from exc

    async def send(self, peer_id, message_type, tag, payload):
        connection = self._connection(peer_id)
        # One lock per peer, so two coroutines do not write half messages together.
        async with connection.send_lock:
            await send_json(
                connection.writer,
                {
                    "type": message_type,
                    "tag": tag,
                    "payload": payload,
                },
            )

    async def receive(self, peer_id, expected_type, expected_tag):
        connection = self._connection(peer_id)
        # One receive lock per peer, so messages are consumed in order.
        async with connection.receive_lock:
            message = await receive_json(connection.reader)
        if message.get("type") != expected_type:
            raise RuntimeError(
                f"expected {expected_type!r} from party {peer_id}, "
                f"received {message.get('type')!r}"
            )
        if message.get("tag") != expected_tag:
            raise RuntimeError(
                f"expected tag {expected_tag!r} from party {peer_id}, "
                f"received {message.get('tag')!r}"
            )
        payload = message.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("peer message payload must be an object")
        return payload

    async def broadcast(self, message_type, tag, payload):
        await asyncio.gather(
            *(
                self.send(
                    peer_id,
                    message_type=message_type,
                    tag=tag,
                    payload=payload,
                )
                for peer_id in range(self.party_count)
                if peer_id != self.party_id
            )
        )

    async def receive_from_all(self, expected_type, expected_tag):
        peers = [
            peer_id
            for peer_id in range(self.party_count)
            if peer_id != self.party_id
        ]
        values = await asyncio.gather(
            *(
                self.receive(
                    peer_id,
                    expected_type=expected_type,
                    expected_tag=expected_tag,
                )
                for peer_id in peers
            )
        )
        return dict(zip(peers, values))

    async def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if self._server is not None:
            # Stop accepting new peers first.
            # After that we close all active streams by ourselves.
            self._server.close()

        # Stop the handler tasks, or wait_closed may wait too long.
        handler_tasks = list(self._handler_tasks)
        for task in handler_tasks:
            task.cancel()

        writers = [connection.writer for connection in self._connections.values()]
        for writer in writers:
            writer.close()
        for writer in writers:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)

        await asyncio.gather(*handler_tasks, return_exceptions=True)
        if self._server is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
